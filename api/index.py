"""Vercel serverless entry point — wraps the Flask dashboard app."""

import sys
import os

# Add project root to path so agents/ package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use /tmp for SQLite on Vercel (ephemeral but writable)
os.environ.setdefault("DB_PATH", "/tmp/pain_machine.db")

from dashboard import app
