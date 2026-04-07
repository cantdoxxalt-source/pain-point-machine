"""
Reddit Pain Point Scanner Agent

Scans r/hairloss using Reddit's public JSON feed (NO API key required),
extracts posts and comments, scores them by pain intensity, and returns
ranked pain points for downstream agents.

Usage:
    from agents.scanner import scan, scan_multi, score_text
    results = scan()                         # defaults: r/hairloss, new, 100 posts
    results = scan(sort="hot", post_limit=50)
    results = scan_multi()                   # sweeps new + hot + top, deduped
"""

import re
import time
import logging
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from functools import lru_cache

from agents.config import (
    DEFAULT_SUBREDDIT,
    SCAN_POST_LIMIT,
    SCAN_COMMENT_DEPTH,
    SCAN_MIN_SCORE,
)

log = logging.getLogger(__name__)

# Reddit public JSON — no auth needed
REDDIT_BASE = "https://www.reddit.com"
HEADERS = {"User-Agent": "pain-point-machine/1.0"}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SUBREDDIT = DEFAULT_SUBREDDIT
POST_LIMIT = SCAN_POST_LIMIT
COMMENT_DEPTH = SCAN_COMMENT_DEPTH
MIN_SCORE = SCAN_MIN_SCORE

# Pain keywords grouped by intensity tier
PAIN_SIGNALS: dict[str, int] = {
    # Tier 3 — high desperation (weight 3)
    "desperate": 3, "devastated": 3, "suicidal": 3, "depressed": 3,
    "ruining my life": 3, "lost all hope": 3, "can't take it": 3,
    "hate myself": 3, "crying": 3, "anxiety": 3, "panic": 3,
    "nothing works": 3, "given up": 3, "last resort": 3,
    "losing confidence": 3, "mental health": 3,
    # Tier 2 — active pain / frustration (weight 2)
    "frustrated": 2, "embarrassed": 2, "self-conscious": 2,
    "insecure": 2, "afraid": 2, "worried": 2, "shedding": 2,
    "thinning": 2, "receding": 2, "bald spot": 2, "losing hair": 2,
    "hair falling": 2, "side effects": 2, "expensive": 2,
    "doesn't work": 2, "no results": 2, "getting worse": 2,
    "waste of money": 2, "scam": 2, "scared": 2,
    # Tier 1 — mild concern / curiosity (weight 1)
    "hairline": 1, "minoxidil": 1, "finasteride": 1, "dermaroller": 1,
    "transplant": 1, "prp": 1, "biotin": 1, "shampoo": 1,
    "supplement": 1, "regrowth": 1, "treatment": 1, "advice": 1,
    "what worked": 1, "recommendations": 1, "help": 1,
}

# ---------------------------------------------------------------------------
# Dynamic keyword loading (merges built-in + custom from DB)
# ---------------------------------------------------------------------------
_signal_cache: list[tuple[re.Pattern, str, int]] | None = None


def _compiled_signals() -> list[tuple[re.Pattern, str, int]]:
    global _signal_cache
    if _signal_cache is not None:
        return _signal_cache
    return _rebuild_signals()


def _rebuild_signals(custom_keywords: list[dict] | None = None) -> list[tuple[re.Pattern, str, int]]:
    """Rebuild signal patterns from built-in + custom keywords."""
    global _signal_cache
    merged = dict(PAIN_SIGNALS)

    if custom_keywords is None:
        try:
            from agents.store import Store
            store = Store()
            custom_keywords = store.get_custom_keywords()
        except Exception:
            custom_keywords = []

    for kw in custom_keywords:
        keyword = kw.get("keyword", "").strip().lower()
        tier = kw.get("tier", 2)
        if keyword:
            merged[keyword] = tier

    _signal_cache = [
        (re.compile(r'\b' + re.escape(sig) + r'\b', re.IGNORECASE), sig, weight)
        for sig, weight in merged.items()
    ]
    log.info("Loaded %d signals (%d built-in + %d custom)",
             len(_signal_cache), len(PAIN_SIGNALS), len(custom_keywords))
    return _signal_cache


def reload_signals():
    """Force reload signals (call after adding/removing custom keywords)."""
    global _signal_cache
    _signal_cache = None

# Engagement multipliers
UPVOTE_THRESHOLDS = [(50, 1.5), (20, 1.3), (10, 1.1)]
COMMENT_THRESHOLDS = [(30, 1.4), (15, 1.2), (5, 1.1)]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class PainPoint:
    """A single scored pain point extracted from Reddit."""
    text: str
    score: float
    source_url: str
    source_title: str
    author: str
    matched_signals: list[str] = field(default_factory=list)
    upvotes: int = 0
    comment_count: int = 0
    created_utc: float = 0.0
    is_comment: bool = False

    @property
    def age_days(self) -> int:
        return (datetime.now(timezone.utc) - datetime.fromtimestamp(self.created_utc, tz=timezone.utc)).days

    def to_dict(self) -> dict:
        return {
            "text": self.text[:500],
            "score": round(self.score, 2),
            "matched_signals": self.matched_signals,
            "source_url": f"https://reddit.com{self.source_url}",
            "source_title": self.source_title,
            "author": self.author,
            "upvotes": self.upvotes,
            "comment_count": self.comment_count,
            "age_days": self.age_days,
            "is_comment": self.is_comment,
        }


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------
def _engagement_multiplier(upvotes: int, comments: int) -> float:
    mult = 1.0
    for threshold, boost in UPVOTE_THRESHOLDS:
        if upvotes >= threshold:
            mult *= boost
            break
    for threshold, boost in COMMENT_THRESHOLDS:
        if comments >= threshold:
            mult *= boost
            break
    return mult


def _recency_multiplier(created_utc: float) -> float:
    age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(created_utc, tz=timezone.utc)).days
    if age_days <= 1:
        return 1.5
    elif age_days <= 3:
        return 1.3
    elif age_days <= 7:
        return 1.1
    elif age_days <= 30:
        return 1.0
    else:
        return 0.8


def score_text(text: str, upvotes: int = 0, comments: int = 0,
               created_utc: float = 0.0) -> tuple[float, list[str]]:
    """Score a piece of text for pain intensity. Returns (score, matched_signals)."""
    base_score = 0
    matched = []

    for pattern, signal, weight in _compiled_signals():
        hits = len(pattern.findall(text))
        if hits > 0:
            base_score += weight * hits
            matched.append(signal)

    if base_score == 0:
        return 0.0, []

    score = base_score
    score *= _engagement_multiplier(upvotes, comments)
    score *= _recency_multiplier(created_utc)

    word_count = len(text.split())
    if word_count > 200:
        score *= 1.2
    elif word_count > 100:
        score *= 1.1

    return score, matched


# ---------------------------------------------------------------------------
# Reddit JSON fetcher (NO API KEY NEEDED)
# ---------------------------------------------------------------------------
def _fetch_posts(subreddit: str, sort: str, limit: int,
                 time_filter: str = "week") -> list[dict]:
    """Fetch posts from Reddit's public JSON endpoint."""
    url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json"
    params = {"limit": min(limit, 100), "raw_json": 1}
    if sort == "top":
        params["t"] = time_filter

    all_posts = []
    after = None

    while len(all_posts) < limit:
        if after:
            params["after"] = after

        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            log.error("Reddit fetch error: %s", e)
            break

        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            if child.get("kind") == "t3":
                all_posts.append(child["data"])

        after = data.get("data", {}).get("after")
        if not after:
            break

        # Be polite — Reddit rate limits public JSON at ~1 req/sec
        time.sleep(1.2)

    return all_posts[:limit]


def _fetch_comments(permalink: str, limit: int = 5) -> list[dict]:
    """Fetch top comments for a post via public JSON."""
    url = f"{REDDIT_BASE}{permalink}.json"
    params = {"limit": limit, "sort": "top", "raw_json": 1}

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.debug("Comment fetch error for %s: %s", permalink, e)
        return []

    if not isinstance(data, list) or len(data) < 2:
        return []

    comments = []
    for child in data[1].get("data", {}).get("children", []):
        if child.get("kind") == "t1":
            comments.append(child["data"])
        if len(comments) >= limit:
            break

    return comments


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
def scan(
    subreddit: str = SUBREDDIT,
    post_limit: int = POST_LIMIT,
    sort: str = "new",
    time_filter: str = "week",
    min_score: float = MIN_SCORE,
) -> list[dict]:
    """
    Scan a subreddit and return scored pain points sorted by score descending.
    Uses Reddit's public JSON — no API key required.
    """
    log.info("Fetching r/%s/%s (limit=%d)...", subreddit, sort, post_limit)
    posts = _fetch_posts(subreddit, sort, post_limit, time_filter)
    log.info("Fetched %d posts from r/%s (%s)", len(posts), subreddit, sort)

    pain_points: list[PainPoint] = []

    for post in posts:
        title = post.get("title", "")
        body = post.get("selftext", "")
        combined_text = f"{title} {body}"
        upvotes = post.get("ups", 0)
        num_comments = post.get("num_comments", 0)
        created = post.get("created_utc", 0)
        permalink = post.get("permalink", "")
        author = post.get("author", "[deleted]") or "[deleted]"

        post_score, post_signals = score_text(combined_text, upvotes, num_comments, created)

        if post_score >= min_score:
            pain_points.append(PainPoint(
                text=combined_text.strip(),
                score=post_score,
                source_url=permalink,
                source_title=title,
                author=author,
                matched_signals=post_signals,
                upvotes=upvotes,
                comment_count=num_comments,
                created_utc=created,
                is_comment=False,
            ))

        # Fetch and score top comments
        if num_comments > 0:
            comments = _fetch_comments(permalink, COMMENT_DEPTH)
            time.sleep(0.8)  # rate limit

            for comment in comments:
                c_body = comment.get("body", "")
                c_ups = comment.get("ups", 0)
                c_created = comment.get("created_utc", 0)
                c_author = comment.get("author", "[deleted]") or "[deleted]"
                c_permalink = comment.get("permalink", permalink)

                c_score, c_signals = score_text(c_body, c_ups, 0, c_created)
                if c_score >= min_score:
                    pain_points.append(PainPoint(
                        text=c_body.strip(),
                        score=c_score,
                        source_url=c_permalink,
                        source_title=title,
                        author=c_author,
                        matched_signals=c_signals,
                        upvotes=c_ups,
                        comment_count=0,
                        created_utc=c_created,
                        is_comment=True,
                    ))

    return _dedupe_and_sort(pain_points)


def scan_multi(
    subreddit: str = SUBREDDIT,
    post_limit: int = POST_LIMIT,
    min_score: float = MIN_SCORE,
) -> list[dict]:
    """
    Sweep new + hot + top(week) for maximum coverage, deduplicated.
    Recommended entry point for downstream agents.
    """
    all_points: list[dict] = []
    for sort, tf in [("new", "week"), ("hot", "week"), ("top", "week")]:
        results = scan(subreddit, post_limit, sort, tf, min_score)
        all_points.extend(results)

    seen: dict[str, dict] = {}
    for r in all_points:
        url = r["source_url"]
        if url not in seen or r["score"] > seen[url]["score"]:
            seen[url] = r

    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)


def _dedupe_and_sort(pain_points: list[PainPoint]) -> list[dict]:
    seen: dict[str, PainPoint] = {}
    for pp in pain_points:
        key = f"{pp.author}:{hash(pp.text[:100])}"
        if key not in seen or pp.score > seen[key].score:
            seen[key] = pp

    results = sorted(seen.values(), key=lambda p: p.score, reverse=True)
    return [pp.to_dict() for pp in results]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Scan r/hairloss for pain points")
    parser.add_argument("--subreddit", default=SUBREDDIT, help="Subreddit to scan")
    parser.add_argument("--limit", type=int, default=POST_LIMIT, help="Posts to fetch per sort")
    parser.add_argument("--sort", default="new", choices=["new", "hot", "top", "multi"],
                        help="Sort mode. 'multi' sweeps new+hot+top combined")
    parser.add_argument("--time-filter", default="week",
                        choices=["hour", "day", "week", "month", "year", "all"],
                        help="Time filter for 'top' sort")
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument("--top", type=int, default=20, help="Show top N results")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    if args.sort == "multi":
        print(f"Multi-scan r/{args.subreddit} (new+hot+top, {args.limit} each)...\n")
        results = scan_multi(args.subreddit, args.limit, args.min_score)
    else:
        print(f"Scanning r/{args.subreddit} ({args.sort}, limit={args.limit})...\n")
        results = scan(args.subreddit, args.limit, args.sort, args.time_filter, args.min_score)

    if args.json:
        print(json.dumps(results[:args.top], indent=2))
    else:
        for i, r in enumerate(results[:args.top], 1):
            signals = ", ".join(r["matched_signals"][:5])
            tag = "comment" if r["is_comment"] else "post"
            print(f"{i:>3}. [{r['score']:>6.1f}] ({tag})  u/{r['author']}")
            print(f"     Signals: {signals}")
            print(f"     {r['text'][:120]}...")
            print(f"     -> {r['source_url']}")
            print()

    print(f"Total pain points found: {len(results)}")
