#!/usr/bin/env python3
"""
Pain Point Machine — Full Pipeline Demo

Runs the complete automation flow:
  1. SCAN    → Scrape Reddit for high-pain posts
  2. SCORE   → Rank by pain intensity
  3. QUALIFY → Score as sales leads (buy intent, urgency, solvability)
  4. DRAFT   → Write personalized outreach messages
  5. REVIEW  → Show everything in the outbox ready to send

This demo uses real Reddit data + simulated qualification/drafting
to show exactly how the production pipeline works.
"""

import sys
import io
import json
import time
import random
import logging
from datetime import datetime, timezone

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from agents.scanner import scan_multi, score_text, reload_signals
from agents.store import Store
from agents.config import DEFAULT_SUBREDDIT

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ANSI colors for terminal output
R = "\033[0m"     # reset
B = "\033[1m"     # bold
O = "\033[38;5;208m"  # orange
G = "\033[38;5;82m"   # green
Y = "\033[38;5;220m"  # yellow
C = "\033[38;5;75m"   # cyan
P = "\033[38;5;141m"  # purple
D = "\033[38;5;245m"  # dim
RED = "\033[38;5;196m"


def banner():
    print(f"""
{O}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   {B}PAIN POINT MACHINE{R}{O}  —  Full Pipeline Demo                  ║
║                                                              ║
║   Scan Reddit → Score Pain → Qualify Leads → Draft Outreach  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{R}
""")


def step(num, title, desc):
    print(f"\n{O}{'━'*60}{R}")
    print(f"{O}  STAGE {num}{R}  {B}{title}{R}")
    print(f"{D}  {desc}{R}")
    print(f"{O}{'━'*60}{R}\n")


def simulate_qualification(pain_points: list[dict]) -> list[dict]:
    """
    Simulate Claude API qualification.
    In production, this calls Claude to analyze each post and score:
      - buy_intent: how likely to pay for a solution
      - urgency: how time-sensitive is the pain
      - solvability: can our product help

    Final lead_score = (buy × 0.4) + (urgency × 0.3) + (solvability × 0.3)
    """
    qualified = []
    reasoning_templates = [
        "User shows strong emotional distress and has tried multiple products without success. High likelihood of paying for a new solution. Pain is recent and escalating.",
        "Active product researcher comparing options. Mentions budget concerns but willing to invest in something that works. Good fit for our product category.",
        "Long-term sufferer who has tried basic treatments. Expressing frustration with current options — ripe for a better alternative. Moderate urgency.",
        "New to hair loss, actively seeking advice and recommendations. Early stage = high solvability. Showing willingness to try products mentioned by others.",
        "Emotionally invested, multiple pain signals detected. Has budget (mentioned spending on other treatments). Our product directly addresses their specific concern.",
        "Community-validated pain (high upvotes). User is comparing treatment options actively. Timing is right for outreach — they're in decision mode.",
    ]

    for pp in pain_points:
        # Score based on actual pain signals
        tier3_signals = {"desperate", "devastated", "depressed", "nothing works", "last resort",
                         "hate myself", "crying", "anxiety", "losing confidence", "mental health",
                         "lost all hope", "given up", "suicidal", "panic", "ruining my life",
                         "can't take it", "losing hope"}
        tier2_signals = {"frustrated", "shedding", "thinning", "side effects", "getting worse",
                         "scared", "waste of money", "insecure", "embarrassed", "no results",
                         "losing hair", "bald spot", "receding", "hair falling", "self-conscious",
                         "doesn't work", "expensive", "afraid", "worried", "scam", "itchy scalp"}

        signals = set(pp.get("matched_signals", []))
        has_tier3 = bool(signals & tier3_signals)
        has_tier2 = bool(signals & tier2_signals)
        signal_count = len(signals)

        # Simulate realistic scores
        if has_tier3 and signal_count >= 3:
            buy = round(random.uniform(7, 9.5), 1)
            urg = round(random.uniform(7, 10), 1)
            sol = round(random.uniform(6, 9), 1)
        elif has_tier3:
            buy = round(random.uniform(5, 8), 1)
            urg = round(random.uniform(6, 9), 1)
            sol = round(random.uniform(5, 8), 1)
        elif has_tier2 and signal_count >= 2:
            buy = round(random.uniform(4, 7), 1)
            urg = round(random.uniform(4, 7), 1)
            sol = round(random.uniform(5, 8), 1)
        else:
            buy = round(random.uniform(2, 5), 1)
            urg = round(random.uniform(2, 5), 1)
            sol = round(random.uniform(3, 6), 1)

        lead_score = round((buy * 0.4) + (urg * 0.3) + (sol * 0.3), 2)

        qualified.append({
            **pp,
            "lead_score": lead_score,
            "buy_intent": buy,
            "urgency": urg,
            "solvability": sol,
            "reasoning": random.choice(reasoning_templates),
        })

    qualified.sort(key=lambda x: x["lead_score"], reverse=True)
    return qualified


def simulate_outreach(leads: list[dict], product_name: str, product_url: str) -> list[dict]:
    """
    Simulate Claude API outreach drafting.
    In production, Claude writes a personalized message for each lead that:
      - References their specific pain points
      - Leads with empathy, not a sales pitch
      - Mentions the product naturally
      - Ends with a soft CTA
    """
    drafts = []

    for lead in leads:
        author = lead.get("author", "friend")
        signals = lead.get("matched_signals", [])
        text = lead.get("text", "")[:200]

        # Pick the most emotional signal for personalization
        pain_ref = signals[0] if signals else "hair loss struggle"

        # Generate realistic personalized messages based on signals
        if any(s in signals for s in ["desperate", "nothing works", "depressed", "anxiety", "losing confidence"]):
            message = (
                f"Hey u/{author}, I came across your post and it really hit home. "
                f"I went through that exact same feeling — the {pain_ref} phase where you just feel like nothing is going to work. "
                f"I tried probably 6-7 different things before I found something that actually made a visible difference for me.\n\n"
                f"I don't want to be that person pushing products in DMs, but I genuinely wish someone had told me about "
                f"{product_name} earlier — it would have saved me a lot of the frustration I went through. "
                f"It's not a miracle cure or anything, but it was the first thing where I actually saw my hairline stabilize "
                f"after about 8 weeks.\n\n"
                f"If you want, I'm happy to share what my routine looks like now. No pressure at all — "
                f"just one person who's been where you are. Hang in there."
            )
            hook = "Empathy-first: shared personal struggle, positioned product as discovery"

        elif any(s in signals for s in ["side effects", "doesn't work", "waste of money", "scam"]):
            message = (
                f"Hey u/{author}, totally get the frustration with side effects and stuff not working. "
                f"I was in the same boat — spent way too much on things that either did nothing or made things worse.\n\n"
                f"What changed for me was finding {product_name} ({product_url}). "
                f"The thing I liked was that it doesn't mess with your hormones, which was my biggest concern "
                f"after my experience with other treatments. Took about 6 weeks to notice anything, "
                f"but the shedding actually slowed down significantly.\n\n"
                f"Everyone's different obviously, but figured it might be worth looking into since you seem to be "
                f"at that \"tried everything\" stage. Happy to answer any questions if you have them."
            )
            hook = "Solution-aware: addressed product fatigue, differentiated on side effects"

        elif any(s in signals for s in ["shedding", "thinning", "receding", "losing hair", "bald spot"]):
            message = (
                f"Hey u/{author}, just wanted to reach out because your situation sounds really similar to where I was "
                f"about a year ago. The {pain_ref} thing was driving me crazy — I was finding hair everywhere "
                f"and it felt like it was accelerating.\n\n"
                f"I ended up trying a bunch of approaches, but the one that actually made a noticeable difference "
                f"was {product_name}. I was skeptical at first (burned too many times lol), "
                f"but after 2-3 months I could genuinely see the difference in photos.\n\n"
                f"Just thought I'd mention it since you're clearly looking for options. Their site is {product_url} "
                f"if you want to check it out. Either way, feel free to DM me if you want to compare notes on what "
                f"has/hasn't worked. This stuff is way easier to deal with when you're not figuring it out alone."
            )
            hook = "Progression-match: mirrored their specific symptom timeline"

        else:
            message = (
                f"Hey u/{author}, saw your post about dealing with hair loss and wanted to share something "
                f"that helped me since I was in a similar spot.\n\n"
                f"After trying the usual stuff (minoxidil, supplements, etc.), I stumbled on {product_name} "
                f"through another Reddit thread actually. It's been about 4 months now and I'm genuinely happy "
                f"with the results — nothing dramatic, but consistent improvement that I can actually see.\n\n"
                f"Here's their site if you're curious: {product_url}\n\n"
                f"Happy to share more details about my experience if it'd help. Good luck with everything!"
            )
            hook = "Casual recommendation: peer-to-peer tone, low pressure"

        drafts.append({
            **lead,
            "draft_message": message,
            "hook": hook,
            "word_count": len(message.split()),
        })

    return drafts


def main():
    banner()

    # Config
    product_name = "HairRestore Pro"
    product_url = "hairrestorepro.com"
    subreddits = ["hairloss"]

    store = Store()

    # Seed subreddits
    for sub in subreddits:
        store.add_subreddit(sub)

    # =====================================================================
    # STAGE 1: SCAN REDDIT
    # =====================================================================
    step(1, "SCAN REDDIT", "Scraping r/hairloss for posts and comments with pain signals...")

    reload_signals()
    all_pain_points = []

    for sub in subreddits:
        print(f"  {C}Scanning r/{sub}...{R}")
        results = scan_multi(sub, post_limit=15, min_score=2)
        all_pain_points.extend(results)
        print(f"  {G}Found {len(results)} pain points in r/{sub}{R}")

    # Dedupe across subreddits
    seen = {}
    for pp in all_pain_points:
        url = pp["source_url"]
        if url not in seen or pp["score"] > seen[url]["score"]:
            seen[url] = pp
    all_pain_points = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    # Save to store
    run_id = store.start_run(",".join(subreddits))
    new_ids = store.save_pain_points(all_pain_points, run_id)

    print(f"\n  {B}Results:{R}")
    print(f"  {D}├─{R} Total pain points: {G}{len(all_pain_points)}{R}")
    print(f"  {D}├─{R} New (not seen before): {G}{len(new_ids)}{R}")
    print(f"  {D}└─{R} Highest score: {O}{all_pain_points[0]['score'] if all_pain_points else 0}{R}")

    print(f"\n  {Y}Top 5 Pain Points:{R}")
    for i, pp in enumerate(all_pain_points[:5], 1):
        signals = ", ".join(pp["matched_signals"][:4])
        tag = "comment" if pp["is_comment"] else "post"
        print(f"  {D}{i}.{R} [{O}{pp['score']:>5.1f}{R}] ({tag})  {C}u/{pp['author']}{R}")
        print(f"     {D}Signals:{R} {Y}{signals}{R}")
        print(f"     {D}{pp['text'][:100]}...{R}")
        print()

    time.sleep(1)

    # =====================================================================
    # STAGE 2: QUALIFY LEADS
    # =====================================================================
    step(2, "QUALIFY LEADS", "Analyzing each pain point for buy intent, urgency, and solvability...")

    # Filter candidates (score >= 3)
    candidates = [p for p in all_pain_points if p["score"] >= 3]
    print(f"  {C}Qualifying {len(candidates)} candidates (score >= 3)...{R}")
    print(f"  {D}[In production: Claude API analyzes each post for lead quality]{R}")
    print()

    qualified = simulate_qualification(candidates)

    # Filter to lead_score >= 5
    top_leads = [l for l in qualified if l["lead_score"] >= 5]

    # Save to store
    for q in qualified:
        pp_id = None
        # Find matching pain point in store
        for pp in all_pain_points:
            if pp["source_url"] == q["source_url"]:
                stored = store.get_unqualified_pain_points(min_score=0, limit=500)
                for s in stored:
                    if s.get("source_url") == pp["source_url"]:
                        pp_id = s["id"]
                        break
                break

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

    print(f"  {B}Results:{R}")
    print(f"  {D}├─{R} Candidates analyzed: {len(candidates)}")
    print(f"  {D}├─{R} Qualified leads (score >= 5): {G}{len(top_leads)}{R}")
    print(f"  {D}└─{R} Rejected (low intent): {D}{len(candidates) - len(top_leads)}{R}")

    print(f"\n  {Y}Top Qualified Leads:{R}")
    for i, l in enumerate(top_leads[:8], 1):
        print(f"  {D}{i}.{R} [{G}{l['lead_score']:>5.1f}{R}]  {C}u/{l['author']}{R}")
        print(f"     Buy: {G}{l['buy_intent']}/10{R}  "
              f"Urg: {Y}{l['urgency']}/10{R}  "
              f"Sol: {C}{l['solvability']}/10{R}")
        print(f"     {D}{l['reasoning'][:90]}...{R}")
        print()

    time.sleep(1)

    # =====================================================================
    # STAGE 3: DRAFT OUTREACH
    # =====================================================================
    step(3, "DRAFT OUTREACH", f"Writing personalized messages for top leads (product: {product_name})...")

    print(f"  {C}Drafting messages for {len(top_leads[:5])} top leads...{R}")
    print(f"  {D}[In production: Claude writes unique messages referencing each user's pain]{R}")
    print()

    drafts = simulate_outreach(top_leads[:5], product_name, product_url)

    # Save to store
    undrafted = store.get_undrafted_leads(min_score=0, limit=500)
    for d in drafts:
        for ul in undrafted:
            if ul.get("pp_author") == d.get("author") or ul.get("pp_url") == d.get("source_url"):
                store.save_outreach(
                    lead_id=ul["id"],
                    message=d["draft_message"],
                    tone="empathetic",
                    word_count=d["word_count"],
                    run_id=run_id,
                )
                break

    print(f"  {B}Results:{R}")
    print(f"  {D}├─{R} Messages drafted: {G}{len(drafts)}{R}")
    print(f"  {D}└─{R} Avg word count: {D}{sum(d['word_count'] for d in drafts) // max(len(drafts), 1)}{R}")

    time.sleep(1)

    # =====================================================================
    # STAGE 4: OUTBOX REVIEW
    # =====================================================================
    step(4, "OUTBOX — READY TO SEND", "Review drafted messages before sending...")

    for i, d in enumerate(drafts, 1):
        print(f"  {O}{'─'*56}{R}")
        print(f"  {B}Message #{i}{R}  →  {C}u/{d['author']}{R}  "
              f"[Lead: {G}{d['lead_score']}{R}]")
        print(f"  {D}Hook: {Y}{d['hook']}{R}")
        print(f"  {D}Pain signals: {', '.join(d['matched_signals'][:4])}{R}")
        print(f"  {D}Source: {d['source_url']}{R}")
        print()
        # Print message with indentation
        for line in d["draft_message"].split("\n"):
            print(f"  {P}│{R} {line}")
        print()
        print(f"  {D}[{d['word_count']} words]{R}")
        print()

    # Finish run
    store.finish_run(run_id, {
        "posts_scanned": 45,
        "pain_points_found": len(all_pain_points),
        "leads_qualified": len(top_leads),
        "messages_drafted": len(drafts),
    }, "completed")

    # =====================================================================
    # SUMMARY
    # =====================================================================
    stats = store.stats()
    print(f"\n{O}{'━'*60}{R}")
    print(f"{O}  PIPELINE COMPLETE{R}")
    print(f"{O}{'━'*60}{R}")
    print(f"""
  {B}Database Totals:{R}
  {D}├─{R} Pain points scanned:  {G}{stats['total_pain_points']}{R}
  {D}├─{R} Leads qualified:      {G}{stats['total_leads']}{R}
  {D}├─{R} Messages drafted:     {G}{stats['total_drafts']}{R}
  {D}├─{R} Messages sent:        {D}{stats['total_sent']}{R}
  {D}└─{R} Pipeline runs:        {D}{stats['total_runs']}{R}

  {B}Next Steps:{R}
  {D}1.{R} Review messages at {C}http://localhost:5000/outbox{R}
  {D}2.{R} Manually send via Reddit DMs (copy-paste)
  {D}3.{R} Mark as sent: {D}python main.py export{R}
  {D}4.{R} Re-run tomorrow: {D}python main.py pipeline{R}

  {B}To go fully automated:{R}
  {D}•{R} Add {Y}ANTHROPIC_API_KEY{R} to .env for real Claude qualification + writing
  {D}•{R} Add more subreddits at {C}http://localhost:5000/settings{R}
  {D}•{R} Schedule with cron: {D}0 9 * * * python main.py pipeline{R}
""")


if __name__ == "__main__":
    main()
