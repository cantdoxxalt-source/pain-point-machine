"""
Shared configuration for the Pain Point Machine.

All tunables live here so agents stay in sync.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Reddit / PRAW
# ---------------------------------------------------------------------------
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "pain-point-machine/1.0")

# ---------------------------------------------------------------------------
# Anthropic / Claude
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# ---------------------------------------------------------------------------
# Scanner defaults
# ---------------------------------------------------------------------------
DEFAULT_SUBREDDIT = "hairloss"
SCAN_POST_LIMIT = 100
SCAN_COMMENT_DEPTH = 5
SCAN_MIN_SCORE = 2.0

# ---------------------------------------------------------------------------
# Qualifier thresholds
# ---------------------------------------------------------------------------
QUAL_MIN_PAIN_SCORE = 4.0        # minimum scanner score to even attempt qualification
QUAL_MIN_LEAD_SCORE = 6.0        # minimum final lead score to pass to writer
QUAL_BATCH_SIZE = 20             # how many leads to qualify per Claude call

# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------
OUTREACH_TONE = "empathetic"     # empathetic | direct | casual
OUTREACH_MAX_LENGTH = 300        # words
OUTREACH_PRODUCT_NAME = os.getenv("PRODUCT_NAME", "")
OUTREACH_PRODUCT_URL = os.getenv("PRODUCT_URL", "")
OUTREACH_PRODUCT_DESC = os.getenv("PRODUCT_DESCRIPTION", "")

# ---------------------------------------------------------------------------
# Store / persistence
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "pain_machine.db")

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
PIPELINE_SORTS = ["new", "hot", "top"]
PIPELINE_TIME_FILTER = "week"
