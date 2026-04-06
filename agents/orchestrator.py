"""
Pipeline Orchestrator

Runs the full pipeline: scan → qualify → draft → store.
Handles deduplication across runs, logging, and error recovery.

Usage:
    from agents.orchestrator import run_pipeline
    report = run_pipeline()                    # full pipeline
    report = run_pipeline(dry_run=True)        # scan + qualify only, no drafts
    report = run_pipeline(subreddit="tressless")  # different subreddit
"""

import json
import logging
from datetime import datetime, timezone

from agents.config import (
    DEFAULT_SUBREDDIT,
    SCAN_POST_LIMIT,
    SCAN_MIN_SCORE,
    QUAL_MIN_PAIN_SCORE,
    QUAL_MIN_LEAD_SCORE,
    PIPELINE_SORTS,
    PIPELINE_TIME_FILTER,
)
from agents.scanner import scan, scan_multi
from agents.qualifier import qualify_leads
from agents.writer import draft_messages
from agents.store import Store

log = logging.getLogger(__name__)


def run_pipeline(
    subreddit: str = DEFAULT_SUBREDDIT,
    post_limit: int = SCAN_POST_LIMIT,
    min_pain_score: float = SCAN_MIN_SCORE,
    min_lead_score: float = QUAL_MIN_LEAD_SCORE,
    dry_run: bool = False,
    skip_qualify: bool = False,
    skip_draft: bool = False,
    store: Store | None = None,
) -> dict:
    """
    Execute the full pain-point-to-outreach pipeline.

    Args:
        subreddit: target subreddit
        post_limit: posts per sort mode
        min_pain_score: scanner threshold
        min_lead_score: qualifier threshold
        dry_run: if True, scan only — no Claude API calls
        skip_qualify: scan + store only
        skip_draft: scan + qualify, no drafts
        store: optional Store instance (creates one if None)

    Returns:
        Pipeline report dict with counts and sample results.
    """
    store = store or Store()
    run_id = store.start_run(subreddit)
    report = {
        "run_id": run_id,
        "subreddit": subreddit,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "posts_scanned": 0,
        "pain_points_found": 0,
        "new_pain_points": 0,
        "leads_qualified": 0,
        "messages_drafted": 0,
        "status": "running",
        "errors": [],
    }

    try:
        # ---- Stage 1: Scan ----
        log.info("=== Stage 1: Scanning r/%s ===", subreddit)
        pain_points = scan_multi(subreddit, post_limit, min_pain_score)
        report["pain_points_found"] = len(pain_points)
        report["posts_scanned"] = post_limit * len(PIPELINE_SORTS)

        if not pain_points:
            log.warning("No pain points found — pipeline complete")
            report["status"] = "completed"
            _finish(store, run_id, report)
            return report

        # Store pain points (dedupes by source_url)
        new_ids = store.save_pain_points(pain_points, run_id)
        report["new_pain_points"] = len(new_ids)
        log.info("Found %d pain points, %d new", len(pain_points), len(new_ids))

        if dry_run or skip_qualify:
            report["status"] = "completed"
            _finish(store, run_id, report)
            return report

        # ---- Stage 2: Qualify ----
        log.info("=== Stage 2: Qualifying leads ===")
        unqualified = store.get_unqualified_pain_points(min_score=QUAL_MIN_PAIN_SCORE)

        if not unqualified:
            log.info("No unqualified pain points to process")
            report["status"] = "completed"
            _finish(store, run_id, report)
            return report

        # Convert stored pain points to scanner-style dicts for qualifier
        scanner_format = []
        for pp in unqualified:
            scanner_format.append({
                "id": pp["id"],
                "text": pp["text"],
                "score": pp["score"],
                "matched_signals": pp["matched_signals"],
                "source_url": pp["source_url"],
                "source_title": pp["source_title"],
                "author": pp["author"],
                "upvotes": pp["upvotes"],
                "comment_count": pp["comment_count"],
                "age_days": pp["age_days"],
                "is_comment": bool(pp["is_comment"]),
            })

        qualified = qualify_leads(scanner_format, QUAL_MIN_PAIN_SCORE, min_lead_score)

        # Store qualified leads
        for q in qualified:
            pp_id = q.get("id")
            if pp_id:
                store.save_lead(
                    pain_point_id=pp_id,
                    lead_score=q["lead_score"],
                    buy_intent=q["buy_intent"],
                    urgency=q["urgency"],
                    solvability=q["solvability"],
                    reasoning=q["reasoning"],
                    run_id=run_id,
                )

        report["leads_qualified"] = len(qualified)
        log.info("Qualified %d leads", len(qualified))

        if skip_draft:
            report["status"] = "completed"
            _finish(store, run_id, report)
            return report

        # ---- Stage 3: Draft outreach ----
        log.info("=== Stage 3: Drafting outreach ===")
        undrafted = store.get_undrafted_leads(min_score=min_lead_score)

        if not undrafted:
            log.info("No undrafted leads to process")
            report["status"] = "completed"
            _finish(store, run_id, report)
            return report

        drafts = draft_messages(undrafted)

        # Store drafts
        for d in drafts:
            lead_id = d.get("id")
            if lead_id and d.get("draft_message"):
                store.save_outreach(
                    lead_id=lead_id,
                    message=d["draft_message"],
                    tone=d.get("tone", "empathetic"),
                    word_count=d.get("word_count", 0),
                    run_id=run_id,
                )

        report["messages_drafted"] = len(drafts)
        log.info("Drafted %d messages", len(drafts))

        report["status"] = "completed"

    except Exception as e:
        log.error("Pipeline failed: %s", e, exc_info=True)
        report["status"] = "failed"
        report["errors"].append(str(e))

    _finish(store, run_id, report)
    return report


def run_scan_only(subreddit: str = DEFAULT_SUBREDDIT, post_limit: int = SCAN_POST_LIMIT) -> dict:
    """Convenience: scan + store, no Claude calls."""
    return run_pipeline(subreddit=subreddit, post_limit=post_limit, dry_run=True)


def run_qualify_only(min_lead_score: float = QUAL_MIN_LEAD_SCORE) -> dict:
    """Qualify all unqualified pain points in the store."""
    return run_pipeline(skip_draft=True, min_lead_score=min_lead_score, post_limit=0)


def run_draft_only(min_lead_score: float = QUAL_MIN_LEAD_SCORE) -> dict:
    """Draft messages for all undrafted qualified leads."""
    store = Store()
    run_id = store.start_run(DEFAULT_SUBREDDIT)
    report = {"run_id": run_id, "messages_drafted": 0, "status": "running", "errors": []}

    try:
        undrafted = store.get_undrafted_leads(min_score=min_lead_score)
        if undrafted:
            drafts = draft_messages(undrafted)
            for d in drafts:
                lead_id = d.get("id")
                if lead_id and d.get("draft_message"):
                    store.save_outreach(
                        lead_id=lead_id,
                        message=d["draft_message"],
                        tone=d.get("tone", "empathetic"),
                        word_count=d.get("word_count", 0),
                        run_id=run_id,
                    )
            report["messages_drafted"] = len(drafts)
        report["status"] = "completed"
    except Exception as e:
        report["status"] = "failed"
        report["errors"].append(str(e))

    _finish(store, run_id, report)
    return report


def _finish(store: Store, run_id: int, report: dict):
    store.finish_run(run_id, {
        "posts_scanned": report.get("posts_scanned", 0),
        "pain_points_found": report.get("pain_points_found", 0),
        "leads_qualified": report.get("leads_qualified", 0),
        "messages_drafted": report.get("messages_drafted", 0),
    }, report["status"])

    log.info("=== Pipeline %s (run #%d) ===", report["status"], run_id)
    log.info("Pain points: %d found, %d new",
             report.get("pain_points_found", 0), report.get("new_pain_points", 0))
    log.info("Leads qualified: %d", report.get("leads_qualified", 0))
    log.info("Messages drafted: %d", report.get("messages_drafted", 0))
