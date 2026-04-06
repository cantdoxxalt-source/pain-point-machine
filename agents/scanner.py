"""
Reddit Pain Point Scanner Agent

Scans r/hairloss using PRAW, extracts posts and comments,
scores them by pain intensity, and returns ranked pain points
for downstream sales agents to act on.

Usage:
    from agents.scanner import scan
    results = scan()                         # defaults: r/hairloss, new, 100 posts
    results = scan(sort="hot", post_limit=50)
    results = scan_multi()                   # sweeps new + hot + top, deduped
"""

import re
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from functools import lru_cache

import praw
from praw.exceptions import RedditAPIException

from agents.config import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT,
    DEFAULT_SUBREDDIT,
    SCAN_POST_LIMIT,
    SCAN_COMMENT_DEPTH,
    SCAN_MIN_SCORE,
)

log = logging.getLogger(__name__)

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

# Pre-compile all patterns once
@lru_cache(maxsize=1)
def _compiled_signals() -> list[tuple[re.Pattern, str, int]]:
    return [
        (re.compile(r'\b' + re.escape(sig) + r'\b', re.IGNORECASE), sig, weight)
        for sig, weight in PAIN_SIGNALS.items()
    ]

# Engagement multipliers
UPVOTE_THRESHOLDS = [(50, 1.5), (20, 1.3), (10, 1.1)]
COMMENT_THRESHOLDS = [(30, 1.4), (15, 1.2), (5, 1.1)]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class PainPoint:
    """A single scored pain point extracted from Reddit."""
    text: str                     # original text snippet
    score: float                  # composite pain score
    source_url: str               # permalink
    source_title: str             # post title
    author: str                   # Reddit username
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
    """Boost score based on engagement — high engagement = validated pain."""
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
    """Recent posts score higher — pain is freshest within 7 days."""
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
    """
    Score a piece of text for pain intensity.

    Returns (score, matched_signals).
    """
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
# Reddit scanner
# ---------------------------------------------------------------------------
def _build_client() -> praw.Reddit:
    """Build PRAW client from config (loaded via env vars)."""
    missing = []
    if not REDDIT_CLIENT_ID:
        missing.append("REDDIT_CLIENT_ID")
    if not REDDIT_CLIENT_SECRET:
        missing.append("REDDIT_CLIENT_SECRET")
    if missing:
        raise EnvironmentError(
            f"Missing env vars: {', '.join(missing)}. "
            "Set them in .env or export directly."
        )

    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )


def scan(
    subreddit: str = SUBREDDIT,
    post_limit: int = POST_LIMIT,
    sort: str = "new",
    time_filter: str = "week",
    min_score: float = MIN_SCORE,
) -> list[dict]:
    """
    Scan a subreddit and return scored pain points sorted by score descending.

    Args:
        subreddit: subreddit name (no r/ prefix)
        post_limit: max posts to fetch
        sort: "new", "hot", or "top"
        time_filter: for "top" sort — "hour", "day", "week", "month", "year", "all"
        min_score: minimum pain score to include

    Returns:
        List of pain point dicts, highest score first.
    """
    reddit = _build_client()
    sub = reddit.subreddit(subreddit)

    fetch_kwargs = {"limit": post_limit}
    if sort == "top":
        fetch_kwargs["time_filter"] = time_filter

    fetch = {"new": sub.new, "hot": sub.hot, "top": sub.top}
    try:
        submissions = list(fetch.get(sort, sub.new)(**fetch_kwargs))
    except RedditAPIException as e:
        log.error("Reddit API error during fetch: %s", e)
        return []

    log.info("Fetched %d posts from r/%s (%s)", len(submissions), subreddit, sort)
    pain_points: list[PainPoint] = []

    for post in submissions:
        combined_text = f"{post.title} {post.selftext}"
        post_score, post_signals = score_text(
            combined_text, post.score, post.num_comments, post.created_utc
        )

        if post_score >= min_score:
            pain_points.append(PainPoint(
                text=combined_text.strip(),
                score=post_score,
                source_url=post.permalink,
                source_title=post.title,
                author=str(post.author) if post.author else "[deleted]",
                matched_signals=post_signals,
                upvotes=post.score,
                comment_count=post.num_comments,
                created_utc=post.created_utc,
                is_comment=False,
            ))

        # Score top-level comments
        post.comment_sort = "top"
        post.comments.replace_more(limit=0)
        for comment in post.comments[:COMMENT_DEPTH]:
            c_score, c_signals = score_text(
                comment.body, comment.score, 0, comment.created_utc
            )
            if c_score >= min_score:
                pain_points.append(PainPoint(
                    text=comment.body.strip(),
                    score=c_score,
                    source_url=comment.permalink,
                    source_title=post.title,
                    author=str(comment.author) if comment.author else "[deleted]",
                    matched_signals=c_signals,
                    upvotes=comment.score,
                    comment_count=0,
                    created_utc=comment.created_utc,
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

    This is the recommended entry point for downstream agents —
    it catches both trending pain AND fresh posts.
    """
    all_points: list[dict] = []
    for sort, tf in [("new", "week"), ("hot", "week"), ("top", "week")]:
        results = scan(subreddit, post_limit, sort, tf, min_score)
        all_points.extend(results)

    # Dedupe across sorts by source_url
    seen: dict[str, dict] = {}
    for r in all_points:
        url = r["source_url"]
        if url not in seen or r["score"] > seen[url]["score"]:
            seen[url] = r

    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)


def _dedupe_and_sort(pain_points: list[PainPoint]) -> list[dict]:
    """Deduplicate by author+text hash, keep highest scoring, return sorted dicts."""
    seen: dict[str, PainPoint] = {}
    for pp in pain_points:
        key = f"{pp.author}:{hash(pp.text[:100])}"
        if key not in seen or pp.score > seen[key].score:
            seen[key] = pp

    results = sorted(seen.values(), key=lambda p: p.score, reverse=True)
    return [pp.to_dict() for pp in results]


# ---------------------------------------------------------------------------
# CLI entry point
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
