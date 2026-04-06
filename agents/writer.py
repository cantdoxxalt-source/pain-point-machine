"""
Outreach Writer Agent

Takes qualified leads and drafts personalized, empathetic outreach messages
using Claude. Each message references the user's specific pain points
without being salesy or robotic.

Usage:
    from agents.writer import draft_messages
    drafts = draft_messages(qualified_leads)
"""

import json
import logging

import anthropic

from agents.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    OUTREACH_TONE,
    OUTREACH_MAX_LENGTH,
    OUTREACH_PRODUCT_NAME,
    OUTREACH_PRODUCT_URL,
    OUTREACH_PRODUCT_DESC,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a copywriter who drafts Reddit DMs/comments for a hair loss product company.
Your job is to write genuine, helpful outreach messages to people struggling with hair loss.

Product: {product_name}
URL: {product_url}
Description: {product_desc}

RULES:
1. Tone: {tone}. Sound like a real person who has been through this, NOT a salesperson.
2. Reference the person's SPECIFIC situation from their post — no generic messages.
3. Lead with empathy and shared experience, not product pitch.
4. Mention the product naturally, as something that helped you or someone you know.
5. Keep it under {max_length} words.
6. NO fake reviews, NO exaggerated claims, NO pressure tactics.
7. Include a soft CTA — "happy to share more if you're interested" style, not "BUY NOW".
8. Do NOT use emojis excessively. One or two max.

For each lead, return a JSON object:
{{"message": "the drafted message", "hook": "1-line summary of the angle used"}}

Return ONLY a JSON array. No markdown, no extra text."""

USER_PROMPT_TEMPLATE = """\
Draft outreach messages for these {count} leads. Return a JSON array of {count} objects.

Leads:
{leads_json}"""


def _build_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def draft_messages(
    leads: list[dict],
    tone: str = OUTREACH_TONE,
    max_length: int = OUTREACH_MAX_LENGTH,
    batch_size: int = 10,
) -> list[dict]:
    """
    Draft outreach messages for qualified leads.

    Args:
        leads: output from qualifier.qualify_leads()
        tone: empathetic | direct | casual
        max_length: max words per message
        batch_size: leads per API call

    Returns:
        List of lead dicts enriched with 'draft_message' and 'hook' fields.
    """
    if not leads:
        return []

    log.info("Drafting messages for %d leads", len(leads))
    client = _build_client()
    all_drafts = []

    for i in range(0, len(leads), batch_size):
        batch = leads[i:i + batch_size]
        drafts = _draft_batch(client, batch, tone, max_length)
        all_drafts.extend(drafts)

    return all_drafts


def _draft_batch(client: anthropic.Anthropic, batch: list[dict],
                 tone: str, max_length: int) -> list[dict]:
    """Draft messages for a batch of leads."""
    leads_for_prompt = []
    for idx, lead in enumerate(batch):
        leads_for_prompt.append({
            "index": idx,
            "author": lead.get("pp_author", lead.get("author", "")),
            "text": lead.get("pp_text", lead.get("text", ""))[:400],
            "signals": lead.get("pp_signals", lead.get("matched_signals", [])),
            "lead_score": lead.get("lead_score", 0),
            "buy_intent": lead.get("buy_intent", 0),
            "urgency": lead.get("urgency", 0),
            "reasoning": lead.get("reasoning", ""),
        })

    system = SYSTEM_PROMPT.format(
        product_name=OUTREACH_PRODUCT_NAME or "[YOUR PRODUCT]",
        product_url=OUTREACH_PRODUCT_URL or "[YOUR URL]",
        product_desc=OUTREACH_PRODUCT_DESC or "[YOUR DESCRIPTION]",
        tone=tone,
        max_length=max_length,
    )
    user_msg = USER_PROMPT_TEMPLATE.format(
        count=len(batch),
        leads_json=json.dumps(leads_for_prompt, indent=2),
    )

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        drafts = _parse_drafts(raw)
    except anthropic.APIError as e:
        log.error("Claude API error during drafting: %s", e)
        return []
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Failed to parse Claude response: %s\nRaw: %s", e, raw[:500])
        return []

    results = []
    for idx, lead in enumerate(batch):
        if idx >= len(drafts):
            break
        d = drafts[idx]
        message = d.get("message", "")
        results.append({
            **lead,
            "draft_message": message,
            "hook": d.get("hook", ""),
            "word_count": len(message.split()),
        })

    return results


def _parse_drafts(raw: str) -> list[dict]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Draft outreach from qualified leads JSON")
    parser.add_argument("input", help="Path to qualified leads JSON")
    parser.add_argument("--tone", default=OUTREACH_TONE, choices=["empathetic", "direct", "casual"])
    parser.add_argument("--max-length", type=int, default=OUTREACH_MAX_LENGTH)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with open(args.input) as f:
        leads = json.load(f)

    results = draft_messages(leads, args.tone, args.max_length)

    if args.json:
        print(json.dumps(results[:args.top], indent=2))
    else:
        for i, r in enumerate(results[:args.top], 1):
            print(f"{'='*60}")
            print(f"#{i}  u/{r.get('pp_author', r.get('author', '?'))}  "
                  f"[Lead: {r.get('lead_score', 0):.1f}]")
            print(f"Hook: {r['hook']}")
            print(f"Words: {r['word_count']}")
            print(f"-" * 60)
            print(r["draft_message"])
            print()

    print(f"Drafted: {len(results)} messages")
