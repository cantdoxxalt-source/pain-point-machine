"""
Lead Qualifier Agent

Takes raw pain points from the scanner and uses Claude to assess:
  - buy_intent   (0-10): how likely is this person to pay for a solution?
  - urgency      (0-10): how time-sensitive is their pain?
  - solvability  (0-10): can our product actually help them?

Final lead_score = weighted average of the three.

Usage:
    from agents.qualifier import qualify_leads
    qualified = qualify_leads(pain_points)
"""

import json
import logging

import anthropic

from agents.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    QUAL_MIN_PAIN_SCORE,
    QUAL_MIN_LEAD_SCORE,
    QUAL_BATCH_SIZE,
    OUTREACH_PRODUCT_NAME,
    OUTREACH_PRODUCT_DESC,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a lead qualification analyst for a sales team. You evaluate Reddit posts/comments
from people experiencing hair loss problems and score them as potential leads.

Our product: {product_name}
Description: {product_desc}

For each post, you MUST return a JSON object with these exact fields:
- buy_intent (0-10): How likely is this person to spend money on a solution? Look for:
  mentions of products tried, willingness to spend, asking for recommendations, comparing options.
- urgency (0-10): How time-sensitive is their pain? Look for:
  recent onset, rapid progression, upcoming events, emotional distress level.
- solvability (0-10): Can our product realistically help this person? Consider:
  their specific problem type, stage of hair loss, whether they've tried similar solutions.
- reasoning (string): 1-2 sentence explanation of your scores.

Return ONLY a JSON array of objects, one per post. No markdown, no extra text."""

USER_PROMPT_TEMPLATE = """\
Score these {count} posts as leads. Return a JSON array with {count} objects.
Each object must have: buy_intent, urgency, solvability, reasoning.

Posts:
{posts_json}"""


def _build_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def qualify_leads(
    pain_points: list[dict],
    min_pain_score: float = QUAL_MIN_PAIN_SCORE,
    min_lead_score: float = QUAL_MIN_LEAD_SCORE,
    batch_size: int = QUAL_BATCH_SIZE,
) -> list[dict]:
    """
    Qualify a list of pain points using Claude.

    Args:
        pain_points: raw output from scanner.scan() or scanner.scan_multi()
        min_pain_score: skip pain points below this scanner score
        min_lead_score: only return leads above this final score
        batch_size: how many to send per API call

    Returns:
        List of qualified lead dicts with scores + reasoning, sorted by lead_score desc.
    """
    # Filter by minimum pain score
    candidates = [p for p in pain_points if p["score"] >= min_pain_score]
    if not candidates:
        log.info("No candidates above min_pain_score=%.1f", min_pain_score)
        return []

    log.info("Qualifying %d candidates (from %d total)", len(candidates), len(pain_points))
    client = _build_client()
    all_leads = []

    # Process in batches
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        leads = _qualify_batch(client, batch)
        all_leads.extend(leads)

    # Filter by minimum lead score
    qualified = [l for l in all_leads if l["lead_score"] >= min_lead_score]
    qualified.sort(key=lambda x: x["lead_score"], reverse=True)

    log.info("Qualified %d leads from %d candidates", len(qualified), len(candidates))
    return qualified


def _qualify_batch(client: anthropic.Anthropic, batch: list[dict]) -> list[dict]:
    """Send a batch of pain points to Claude for scoring."""
    # Prepare condensed post data for the prompt
    posts_for_prompt = []
    for idx, p in enumerate(batch):
        posts_for_prompt.append({
            "index": idx,
            "author": p["author"],
            "text": p["text"][:400],
            "signals": p["matched_signals"],
            "pain_score": p["score"],
            "upvotes": p["upvotes"],
        })

    system = SYSTEM_PROMPT.format(
        product_name=OUTREACH_PRODUCT_NAME or "(not configured)",
        product_desc=OUTREACH_PRODUCT_DESC or "(not configured)",
    )
    user_msg = USER_PROMPT_TEMPLATE.format(
        count=len(batch),
        posts_json=json.dumps(posts_for_prompt, indent=2),
    )

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        scores = _parse_scores(raw)
    except anthropic.APIError as e:
        log.error("Claude API error during qualification: %s", e)
        return []
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Failed to parse Claude response: %s\nRaw: %s", e, raw[:500])
        return []

    if len(scores) != len(batch):
        log.warning("Expected %d scores, got %d — aligning by index", len(batch), len(scores))

    results = []
    for idx, pp in enumerate(batch):
        if idx >= len(scores):
            break
        s = scores[idx]
        buy = _clamp(s.get("buy_intent", 0))
        urg = _clamp(s.get("urgency", 0))
        sol = _clamp(s.get("solvability", 0))
        lead_score = (buy * 0.4) + (urg * 0.3) + (sol * 0.3)

        results.append({
            **pp,
            "lead_score": round(lead_score, 2),
            "buy_intent": buy,
            "urgency": urg,
            "solvability": sol,
            "reasoning": s.get("reasoning", ""),
        })

    return results


def _parse_scores(raw: str) -> list[dict]:
    """Parse Claude's JSON response, handling common formatting issues."""
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    return json.loads(cleaned)


def _clamp(val, lo: float = 0, hi: float = 10) -> float:
    try:
        return max(lo, min(hi, float(val)))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Qualify leads from scanner JSON")
    parser.add_argument("input", help="Path to scanner JSON output")
    parser.add_argument("--min-pain", type=float, default=QUAL_MIN_PAIN_SCORE)
    parser.add_argument("--min-lead", type=float, default=QUAL_MIN_LEAD_SCORE)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with open(args.input) as f:
        pain_points = json.load(f)

    results = qualify_leads(pain_points, args.min_pain, args.min_lead)

    if args.json:
        print(json.dumps(results[:args.top], indent=2))
    else:
        for i, r in enumerate(results[:args.top], 1):
            print(f"{i:>3}. [Lead: {r['lead_score']:>5.1f}]  u/{r['author']}")
            print(f"     Buy: {r['buy_intent']:.0f}  Urg: {r['urgency']:.0f}  Sol: {r['solvability']:.0f}")
            print(f"     {r['reasoning']}")
            print(f"     -> {r['source_url']}")
            print()

    print(f"Qualified leads: {len(results)}")
