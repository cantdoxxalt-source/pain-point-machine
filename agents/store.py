"""
Persistence layer — SQLite store for scanned leads, qualifications, and outreach drafts.

Tables:
    pain_points   — raw scanner output
    leads         — qualified leads with scores + reasoning
    outreach      — drafted messages tied to leads
    runs          — pipeline execution log
"""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

from agents.config import DB_PATH

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pain_points (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url      TEXT UNIQUE NOT NULL,
    source_title    TEXT,
    author          TEXT,
    text            TEXT,
    score           REAL,
    matched_signals TEXT,       -- JSON array
    upvotes         INTEGER DEFAULT 0,
    comment_count   INTEGER DEFAULT 0,
    age_days        INTEGER DEFAULT 0,
    is_comment      INTEGER DEFAULT 0,
    scanned_at      TEXT NOT NULL,
    run_id          INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pain_point_id   INTEGER NOT NULL REFERENCES pain_points(id),
    lead_score      REAL NOT NULL,
    buy_intent      REAL DEFAULT 0,
    urgency         REAL DEFAULT 0,
    solvability     REAL DEFAULT 0,
    reasoning       TEXT,
    qualified_at    TEXT NOT NULL,
    status          TEXT DEFAULT 'new',  -- new | contacted | converted | rejected
    run_id          INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS outreach (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER NOT NULL REFERENCES leads(id),
    message         TEXT NOT NULL,
    tone            TEXT,
    word_count      INTEGER,
    drafted_at      TEXT NOT NULL,
    sent            INTEGER DEFAULT 0,
    sent_at         TEXT,
    run_id          INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subreddit       TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    posts_scanned   INTEGER DEFAULT 0,
    pain_points_found INTEGER DEFAULT 0,
    leads_qualified INTEGER DEFAULT 0,
    messages_drafted INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running'  -- running | completed | failed
);

CREATE TABLE IF NOT EXISTS subreddits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    enabled         INTEGER DEFAULT 1,
    added_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_keywords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword         TEXT UNIQUE NOT NULL,
    tier            INTEGER DEFAULT 2,   -- 1=concern, 2=frustration, 3=desperation
    added_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pp_author ON pain_points(author);
CREATE INDEX IF NOT EXISTS idx_pp_score ON pain_points(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(lead_score DESC);
"""


class Store:
    """SQLite-backed persistence for the Pain Point Machine."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)
        log.info("Database initialized at %s", self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def start_run(self, subreddit: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO runs (subreddit, started_at) VALUES (?, ?)",
                (subreddit, _now()),
            )
            return cur.lastrowid

    def finish_run(self, run_id: int, stats: dict, status: str = "completed"):
        with self._conn() as conn:
            conn.execute(
                """UPDATE runs SET finished_at=?, posts_scanned=?, pain_points_found=?,
                   leads_qualified=?, messages_drafted=?, status=? WHERE id=?""",
                (_now(), stats.get("posts_scanned", 0), stats.get("pain_points_found", 0),
                 stats.get("leads_qualified", 0), stats.get("messages_drafted", 0),
                 status, run_id),
            )

    # ------------------------------------------------------------------
    # Pain points
    # ------------------------------------------------------------------
    def save_pain_points(self, points: list[dict], run_id: int) -> list[int]:
        """Insert pain points, skip duplicates by source_url. Returns inserted IDs."""
        ids = []
        with self._conn() as conn:
            for p in points:
                try:
                    cur = conn.execute(
                        """INSERT INTO pain_points
                           (source_url, source_title, author, text, score,
                            matched_signals, upvotes, comment_count, age_days,
                            is_comment, scanned_at, run_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (p["source_url"], p["source_title"], p["author"],
                         p["text"], p["score"], json.dumps(p["matched_signals"]),
                         p["upvotes"], p["comment_count"], p["age_days"],
                         int(p["is_comment"]), _now(), run_id),
                    )
                    ids.append(cur.lastrowid)
                except sqlite3.IntegrityError:
                    # duplicate source_url — update score if higher
                    conn.execute(
                        """UPDATE pain_points SET score=MAX(score, ?), scanned_at=?
                           WHERE source_url=?""",
                        (p["score"], _now(), p["source_url"]),
                    )
        log.info("Saved %d new pain points (run %d)", len(ids), run_id)
        return ids

    def get_unqualified_pain_points(self, min_score: float = 0, limit: int = 100) -> list[dict]:
        """Get pain points that have no matching lead record yet."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT pp.* FROM pain_points pp
                   LEFT JOIN leads l ON l.pain_point_id = pp.id
                   WHERE l.id IS NULL AND pp.score >= ?
                   ORDER BY pp.score DESC LIMIT ?""",
                (min_score, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_pain_point(self, pp_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM pain_points WHERE id=?", (pp_id,)).fetchone()
        return _row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------
    def save_lead(self, pain_point_id: int, lead_score: float, buy_intent: float,
                  urgency: float, solvability: float, reasoning: str, run_id: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO leads
                   (pain_point_id, lead_score, buy_intent, urgency, solvability,
                    reasoning, qualified_at, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (pain_point_id, lead_score, buy_intent, urgency, solvability,
                 reasoning, _now(), run_id),
            )
            return cur.lastrowid

    def get_undrafted_leads(self, min_score: float = 0, limit: int = 50) -> list[dict]:
        """Get qualified leads that have no outreach draft yet."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT l.*, pp.text as pp_text, pp.author as pp_author,
                          pp.source_url as pp_url, pp.matched_signals as pp_signals
                   FROM leads l
                   JOIN pain_points pp ON pp.id = l.pain_point_id
                   LEFT JOIN outreach o ON o.lead_id = l.id
                   WHERE o.id IS NULL AND l.lead_score >= ? AND l.status = 'new'
                   ORDER BY l.lead_score DESC LIMIT ?""",
                (min_score, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_lead(self, lead_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT l.*, pp.text as pp_text, pp.author as pp_author,
                          pp.source_url as pp_url
                   FROM leads l JOIN pain_points pp ON pp.id = l.pain_point_id
                   WHERE l.id=?""",
                (lead_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def update_lead_status(self, lead_id: int, status: str):
        with self._conn() as conn:
            conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))

    # ------------------------------------------------------------------
    # Outreach
    # ------------------------------------------------------------------
    def save_outreach(self, lead_id: int, message: str, tone: str,
                      word_count: int, run_id: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO outreach (lead_id, message, tone, word_count, drafted_at, run_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (lead_id, message, tone, word_count, _now(), run_id),
            )
            return cur.lastrowid

    def mark_sent(self, outreach_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE outreach SET sent=1, sent_at=? WHERE id=?",
                (_now(), outreach_id),
            )

    def get_unsent_outreach(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT o.*, l.lead_score, pp.author as pp_author, pp.source_url as pp_url
                   FROM outreach o
                   JOIN leads l ON l.id = o.lead_id
                   JOIN pain_points pp ON pp.id = l.pain_point_id
                   WHERE o.sent = 0
                   ORDER BY l.lead_score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def stats(self) -> dict:
        with self._conn() as conn:
            pp = conn.execute("SELECT COUNT(*) as c FROM pain_points").fetchone()["c"]
            leads = conn.execute("SELECT COUNT(*) as c FROM leads").fetchone()["c"]
            drafts = conn.execute("SELECT COUNT(*) as c FROM outreach").fetchone()["c"]
            sent = conn.execute("SELECT COUNT(*) as c FROM outreach WHERE sent=1").fetchone()["c"]
            runs = conn.execute("SELECT COUNT(*) as c FROM runs").fetchone()["c"]
        return {
            "total_pain_points": pp,
            "total_leads": leads,
            "total_drafts": drafts,
            "total_sent": sent,
            "total_runs": runs,
        }

    def already_seen(self, source_url: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM pain_points WHERE source_url=?", (source_url,)
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Subreddits
    # ------------------------------------------------------------------
    def add_subreddit(self, name: str) -> bool:
        name = name.strip().lower().replace("r/", "").replace("/", "")
        if not name:
            return False
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO subreddits (name, added_at) VALUES (?, ?)",
                    (name, _now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_subreddit(self, sub_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM subreddits WHERE id=?", (sub_id,))

    def toggle_subreddit(self, sub_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE subreddits SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?",
                (sub_id,),
            )

    def get_subreddits(self, enabled_only: bool = False) -> list[dict]:
        with self._conn() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM subreddits WHERE enabled=1 ORDER BY name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM subreddits ORDER BY name"
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Custom keywords
    # ------------------------------------------------------------------
    def add_keyword(self, keyword: str, tier: int = 2) -> bool:
        keyword = keyword.strip().lower()
        tier = max(1, min(3, tier))
        if not keyword:
            return False
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO custom_keywords (keyword, tier, added_at) VALUES (?, ?, ?)",
                    (keyword, tier, _now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_keyword(self, kw_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM custom_keywords WHERE id=?", (kw_id,))

    def get_custom_keywords(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_keywords ORDER BY tier DESC, keyword"
            ).fetchall()
        return [dict(r) for r in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "matched_signals" in d and isinstance(d["matched_signals"], str):
        d["matched_signals"] = json.loads(d["matched_signals"])
    if "pp_signals" in d and isinstance(d["pp_signals"], str):
        d["pp_signals"] = json.loads(d["pp_signals"])
    return d
