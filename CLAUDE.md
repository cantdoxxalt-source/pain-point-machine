# Pain Point Machine — Multiagent Sales System

## Project Overview

A Python multiagent system that scans Reddit for high-pain user posts (starting with r/hairloss), scores them, and feeds them to downstream agents for lead qualification, outreach drafting, and sales automation.

The philosophy: **find people in pain, understand their pain deeply, then offer genuine help at the right moment.**

---

## File Structure

```
agents/
├── __init__.py          ← package init
├── scanner.py           ← Reddit pain point scanner (PRAW)
├── requirements.txt     ← Python deps
├── .env.example         ← env var template
├── (planned) qualifier.py    ← lead scoring / qualification agent
├── (planned) writer.py       ← outreach message drafting agent
├── (planned) orchestrator.py ← pipeline coordinator
└── (planned) store.py        ← results persistence layer
```

---

## Tech Stack

- **Python 3.11+**
- **PRAW** — Reddit API wrapper
- **python-dotenv** — env var loading from .env
- **(planned) Claude API** — for LLM-powered qualification and outreach drafting
- **(planned) SQLite / JSON** — local persistence

---

## Agent: Scanner (`agents/scanner.py`)

### Purpose
Scans a subreddit, extracts posts + top comments, and scores each by pain intensity using keyword matching + engagement/recency multipliers.

### Scoring Engine
Three-tier pain keyword dictionary:
- **Tier 3 (weight 3):** Desperation — "desperate", "depressed", "nothing works", "last resort", "mental health"
- **Tier 2 (weight 2):** Active frustration — "frustrated", "shedding", "side effects", "waste of money"
- **Tier 1 (weight 1):** General concern — "minoxidil", "transplant", "advice", "treatment"

Multipliers:
- **Engagement** — upvotes/comments boost (validated pain scores higher)
- **Recency** — posts <7 days boosted, >30 days penalized
- **Length** — longer posts with signals = richer context

### Key Functions
| Function | Purpose |
|----------|---------|
| `scan()` | Single-sort scan, returns `list[dict]` |
| `scan_multi()` | Sweeps new+hot+top(week), deduped — **recommended for downstream agents** |
| `score_text()` | Pure scoring function, no Reddit dependency — useful for testing |

### Output Schema
```python
{
    "text": str,              # post/comment body (max 500 chars)
    "score": float,           # composite pain score
    "matched_signals": list,  # which keywords fired
    "source_url": str,        # Reddit permalink
    "source_title": str,      # parent post title
    "author": str,            # Reddit username
    "upvotes": int,
    "comment_count": int,
    "age_days": int,
    "is_comment": bool,
}
```

### CLI Usage
```bash
cd agents && pip install -r requirements.txt

# Set creds (create app at reddit.com/prefs/apps, type "script")
cp .env.example .env  # fill in values

python scanner.py --sort hot --limit 50 --top 10
python scanner.py --sort multi --limit 100 --json > results.json
python scanner.py --sort top --time-filter month --top 5
```

### Programmatic Usage
```python
from agents.scanner import scan, scan_multi, score_text

# Full scan
results = scan_multi()

# Score arbitrary text (no Reddit needed)
score, signals = score_text("I'm desperate, nothing works and I'm losing all my hair")
```

---

## Planned Agents

### Qualifier (`qualifier.py`)
- Takes scanner output, uses Claude API to assess lead quality
- Filters for: high pain + solvable problem + likely buyer intent
- Outputs qualified leads with reasoning

### Writer (`writer.py`)
- Takes qualified leads, drafts personalized outreach
- Tone: empathetic, helpful, non-salesy
- References the user's specific pain points from their post

### Orchestrator (`orchestrator.py`)
- Runs the full pipeline: scan → qualify → draft
- Configurable schedule (cron or manual trigger)
- Deduplicates across runs to avoid re-contacting

### Store (`store.py`)
- Persists scan results, qualified leads, sent messages
- Tracks which users have been contacted
- SQLite or JSON flat file

---

## Environment Variables

| Var | Required | Purpose |
|-----|----------|---------|
| `REDDIT_CLIENT_ID` | Yes | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | Yes | Reddit app secret |
| `REDDIT_USER_AGENT` | Yes | PRAW user agent string |
| `ANTHROPIC_API_KEY` | Planned | For Claude-powered agents |

---

## Design Decisions

- Started with keyword scoring (not LLM) for the scanner — fast, cheap, deterministic
- LLM reserved for qualification and writing where nuance matters
- Single subreddit focus (r/hairloss) to start, easily extensible
- `scan_multi()` is the recommended entry point — catches both trending and fresh pain
- Pre-compiled regex patterns cached via `@lru_cache` for performance
