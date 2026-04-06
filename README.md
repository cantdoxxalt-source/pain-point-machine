# Pain Point Machine

A multiagent Python system that scans Reddit for high-pain user posts, qualifies them as sales leads using Claude, and drafts personalized outreach messages.

**Pipeline:** `Scan Reddit → Score Pain → Qualify Leads → Draft Outreach`

Currently targeting **r/hairloss** — easily configurable for any subreddit/niche.

---

## Architecture

```
main.py                    ← CLI entry point (8 commands)
agents/
├── config.py              ← shared settings, env vars
├── scanner.py             ← PRAW Reddit scanner + pain scoring engine
├── qualifier.py           ← Claude-powered lead qualification
├── writer.py              ← Claude-powered outreach drafting
├── orchestrator.py        ← pipeline coordinator (scan → qualify → draft)
└── store.py               ← SQLite persistence (pain points, leads, outreach, runs)
```

### Agent Responsibilities

| Agent | Input | Output | Needs API? |
|-------|-------|--------|------------|
| **Scanner** | Subreddit name | Scored pain points | Reddit API |
| **Qualifier** | Pain points | Qualified leads (buy intent, urgency, solvability) | Claude API |
| **Writer** | Qualified leads | Personalized outreach drafts | Claude API |
| **Orchestrator** | Config | Full pipeline execution + report | Both |
| **Store** | Any agent output | SQLite persistence | None |

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/YOUR_USERNAME/pain-point-machine.git
cd pain-point-machine
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

**Reddit API:** Create an app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps/) (select "script" type).

**Anthropic API:** Get a key at [console.anthropic.com](https://console.anthropic.com/).

### 3. Run

```bash
# Full pipeline (scan → qualify → draft)
python main.py pipeline

# Or run stages individually:
python main.py scan                          # scan Reddit only (no Claude calls)
python main.py scan --subreddit tressless    # different subreddit
python main.py qualify                       # qualify stored pain points
python main.py draft                         # draft outreach for qualified leads

# View results:
python main.py status                        # database stats
python main.py leads                         # top qualified leads
python main.py outbox                        # drafted messages ready to send
python main.py export -o results.json        # export everything as JSON
```

---

## How It Works

### Stage 1: Scanner (`agents/scanner.py`)

Scans r/hairloss using PRAW. Scores each post/comment using a **3-tier keyword engine**:

| Tier | Weight | Examples |
|------|--------|----------|
| 3 — Desperation | ×3 | "desperate", "nothing works", "last resort", "depressed" |
| 2 — Frustration | ×2 | "frustrated", "shedding", "side effects", "getting worse" |
| 1 — Concern | ×1 | "minoxidil", "transplant", "advice", "treatment" |

**Multipliers** boost scores based on:
- **Engagement** — high upvotes/comments = validated pain
- **Recency** — posts <7 days old score higher
- **Length** — longer posts with signals = richer context

The `scan_multi()` function sweeps new + hot + top(week) for maximum coverage.

### Stage 2: Qualifier (`agents/qualifier.py`)

Sends pain points to Claude in batches. For each post, Claude scores:
- **Buy Intent (0-10):** likelihood to pay for a solution
- **Urgency (0-10):** how time-sensitive is the pain
- **Solvability (0-10):** can our product actually help

Final lead score = `(buy × 0.4) + (urgency × 0.3) + (solvability × 0.3)`

### Stage 3: Writer (`agents/writer.py`)

Drafts personalized Reddit DMs/comments. Rules enforced:
- Lead with empathy, not product pitch
- Reference the person's specific situation
- No fake reviews, no pressure tactics
- Soft CTA: "happy to share more if interested"

### Persistence (`agents/store.py`)

SQLite database with 4 tables:
- `pain_points` — raw scanner output (deduped by URL)
- `leads` — qualified leads with scores + reasoning
- `outreach` — drafted messages tied to leads
- `runs` — pipeline execution log

Deduplicates across runs — re-scanning won't re-process the same posts.

---

## Configuration

All settings in `agents/config.py`, overridable via environment variables:

| Setting | Default | Purpose |
|---------|---------|---------|
| `DEFAULT_SUBREDDIT` | hairloss | Target subreddit |
| `SCAN_POST_LIMIT` | 100 | Posts per sort mode |
| `SCAN_MIN_SCORE` | 2.0 | Minimum pain score |
| `QUAL_MIN_PAIN_SCORE` | 4.0 | Min scanner score to attempt qualification |
| `QUAL_MIN_LEAD_SCORE` | 6.0 | Min lead score to pass to writer |
| `ANTHROPIC_MODEL` | claude-sonnet-4-20250514 | Claude model for qualification + writing |
| `OUTREACH_TONE` | empathetic | Message tone: empathetic, direct, casual |
| `OUTREACH_MAX_LENGTH` | 300 | Max words per outreach message |

---

## Extending

**Add a new subreddit:**
```bash
python main.py pipeline --subreddit tressless
python main.py pipeline --subreddit alopecia
```

**Use scanner standalone:**
```python
from agents.scanner import scan_multi, score_text

# Full Reddit scan
results = scan_multi("hairloss")

# Score any text (no Reddit needed)
score, signals = score_text("I'm desperate, losing my hair and nothing works")
# => (9.0, ["desperate", "losing hair", "nothing works"])
```

**Add custom pain signals:** Edit `PAIN_SIGNALS` dict in `agents/scanner.py`.

---

## License

MIT
