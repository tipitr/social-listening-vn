"""Draft starter content from a mined customer question.

Closes the loop: a recurring question ("How do I apply for a home loan?")
becomes a ready-to-edit FAQ answer + social caption in KBank Vietnam's voice —
so the marketing team goes from "what to write" to "a draft to polish" in one
click.

Compliance guard: the draft must NOT invent specific rates, fees, or
guarantees — those are filled in by the team with placeholders.
"""

from __future__ import annotations

import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are a marketing copywriter for KBank Vietnam's home-loan team. A customer
keeps asking the given question. Write short, friendly, on-brand starter content
the team can edit and publish, in VIETNAMESE (that's the customer audience).

Return markdown with exactly:

**FAQ answer** — 2–4 helpful sentences answering the question plainly.

**Social caption** — 1–2 sentences + a clear call to action.

Compliance — IMPORTANT: do NOT invent specific interest rates, fees, loan
amounts, approval times, or guarantees. Where a specific figure would go, use a
bracketed placeholder like [lãi suất hiện tại] or [hạn mức vay] for the team to
fill in. Keep it warm and clear, not salesy. Under 120 words total."""


def draft_for_question(question: str, topic_label: str = "") -> str:
    """Return a markdown draft (FAQ answer + social caption) for a question."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user",
                   "content": f"Topic: {topic_label}\nCustomer question: {question}"}],
    )
    try:
        from pipeline.collector import log_usage
        u = resp.usage
        cost = (u.input_tokens / 1_000_000 * 3) + (u.output_tokens / 1_000_000 * 15)
        log_usage("claude_inbox_draft", MODEL, u.input_tokens, u.output_tokens, cost, 1)
    except Exception:
        pass
    return resp.content[0].text.strip()
