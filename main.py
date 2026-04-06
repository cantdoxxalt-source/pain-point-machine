#!/usr/bin/env python3
"""
Pain Point Machine — CLI entry point.

Commands:
    python main.py scan             Scan Reddit, store pain points
    python main.py qualify          Qualify stored pain points into leads
    python main.py draft            Draft outreach for qualified leads
    python main.py pipeline         Run full scan → qualify → draft pipeline
    python main.py status           Show database stats
    python main.py leads            List top qualified leads
    python main.py outbox           Show drafted messages ready to send
    python main.py export           Export all data as JSON
"""

import argparse
import json
import logging
import sys

from agents.config import (
    DEFAULT_SUBREDDIT,
    SCAN_POST_LIMIT,
    SCAN_MIN_SCORE,
    QUAL_MIN_LEAD_SCORE,
)
from agents.store import Store
from agents.orchestrator import (
    run_pipeline,
    run_scan_only,
    run_qualify_only,
    run_draft_only,
)


def cmd_scan(args):
    """Scan subreddit and store pain points."""
    report = run_scan_only(args.subreddit, args.limit)
    print(f"\nScan complete.")
    print(f"  Pain points found: {report['pain_points_found']}")
    print(f"  New (not seen before): {report.get('new_pain_points', 0)}")
    if report["errors"]:
        print(f"  Errors: {report['errors']}")


def cmd_qualify(args):
    """Qualify unqualified pain points in the store."""
    report = run_qualify_only(args.min_lead_score)
    print(f"\nQualification complete.")
    print(f"  Leads qualified: {report['leads_qualified']}")
    if report["errors"]:
        print(f"  Errors: {report['errors']}")


def cmd_draft(args):
    """Draft outreach for undrafted leads."""
    report = run_draft_only(args.min_lead_score)
    print(f"\nDrafting complete.")
    print(f"  Messages drafted: {report['messages_drafted']}")
    if report["errors"]:
        print(f"  Errors: {report['errors']}")


def cmd_pipeline(args):
    """Run full pipeline: scan → qualify → draft."""
    report = run_pipeline(
        subreddit=args.subreddit,
        post_limit=args.limit,
        min_lead_score=args.min_lead_score,
    )
    print(f"\nPipeline {report['status']} (run #{report['run_id']})")
    print(f"  Pain points: {report['pain_points_found']} found, {report.get('new_pain_points', 0)} new")
    print(f"  Leads qualified: {report['leads_qualified']}")
    print(f"  Messages drafted: {report['messages_drafted']}")
    if report["errors"]:
        print(f"  Errors: {report['errors']}")


def cmd_status(args):
    """Show database stats."""
    store = Store()
    stats = store.stats()
    print("\nPain Point Machine — Status")
    print("=" * 40)
    print(f"  Total pain points:  {stats['total_pain_points']}")
    print(f"  Total leads:        {stats['total_leads']}")
    print(f"  Total drafts:       {stats['total_drafts']}")
    print(f"  Sent messages:      {stats['total_sent']}")
    print(f"  Pipeline runs:      {stats['total_runs']}")


def cmd_leads(args):
    """List top qualified leads."""
    store = Store()
    leads = store.get_undrafted_leads(min_score=0, limit=args.top)
    if not leads:
        print("No qualified leads yet. Run: python main.py qualify")
        return

    print(f"\nTop {len(leads)} Qualified Leads")
    print("=" * 60)
    for i, l in enumerate(leads, 1):
        print(f"{i:>3}. [Score: {l['lead_score']:.1f}]  u/{l.get('pp_author', '?')}")
        print(f"     Buy: {l['buy_intent']:.0f}  Urg: {l['urgency']:.0f}  Sol: {l['solvability']:.0f}")
        print(f"     {l.get('reasoning', '')[:100]}")
        print(f"     -> {l.get('pp_url', '')}")
        print()


def cmd_outbox(args):
    """Show drafted messages ready to send."""
    store = Store()
    drafts = store.get_unsent_outreach(limit=args.top)
    if not drafts:
        print("No unsent messages. Run: python main.py draft")
        return

    print(f"\nOutbox — {len(drafts)} messages ready")
    print("=" * 60)
    for i, d in enumerate(drafts, 1):
        print(f"#{i}  To: u/{d.get('pp_author', '?')}  [Lead: {d.get('lead_score', 0):.1f}]")
        print(f"    {d.get('pp_url', '')}")
        print(f"    ---")
        print(f"    {d['message'][:300]}")
        if len(d['message']) > 300:
            print(f"    ... ({d['word_count']} words)")
        print()


def cmd_export(args):
    """Export all data as JSON."""
    store = Store()
    data = {
        "stats": store.stats(),
        "pain_points": store.get_unqualified_pain_points(min_score=0, limit=9999),
        "leads": store.get_undrafted_leads(min_score=0, limit=9999),
        "outbox": store.get_unsent_outreach(limit=9999),
    }
    output = json.dumps(data, indent=2, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Exported to {args.output}")
    else:
        print(output)


def main():
    parser = argparse.ArgumentParser(
        prog="pain-machine",
        description="Pain Point Machine — Reddit lead gen pipeline",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # scan
    p_scan = sub.add_parser("scan", help="Scan Reddit for pain points")
    p_scan.add_argument("--subreddit", default=DEFAULT_SUBREDDIT)
    p_scan.add_argument("--limit", type=int, default=SCAN_POST_LIMIT)
    p_scan.set_defaults(func=cmd_scan)

    # qualify
    p_qual = sub.add_parser("qualify", help="Qualify stored pain points")
    p_qual.add_argument("--min-lead-score", type=float, default=QUAL_MIN_LEAD_SCORE)
    p_qual.set_defaults(func=cmd_qualify)

    # draft
    p_draft = sub.add_parser("draft", help="Draft outreach messages")
    p_draft.add_argument("--min-lead-score", type=float, default=QUAL_MIN_LEAD_SCORE)
    p_draft.set_defaults(func=cmd_draft)

    # pipeline
    p_pipe = sub.add_parser("pipeline", help="Run full pipeline")
    p_pipe.add_argument("--subreddit", default=DEFAULT_SUBREDDIT)
    p_pipe.add_argument("--limit", type=int, default=SCAN_POST_LIMIT)
    p_pipe.add_argument("--min-lead-score", type=float, default=QUAL_MIN_LEAD_SCORE)
    p_pipe.set_defaults(func=cmd_pipeline)

    # status
    p_status = sub.add_parser("status", help="Show database stats")
    p_status.set_defaults(func=cmd_status)

    # leads
    p_leads = sub.add_parser("leads", help="List qualified leads")
    p_leads.add_argument("--top", type=int, default=20)
    p_leads.set_defaults(func=cmd_leads)

    # outbox
    p_outbox = sub.add_parser("outbox", help="Show unsent drafts")
    p_outbox.add_argument("--top", type=int, default=20)
    p_outbox.set_defaults(func=cmd_outbox)

    # export
    p_export = sub.add_parser("export", help="Export all data as JSON")
    p_export.add_argument("-o", "--output", help="Output file path")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
