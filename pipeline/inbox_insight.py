"""Inbox insight agent — turns categorized inbox messages into a short brief.

Where the dashboard charts answer "how many / what topic", this answers the
"so what — and what should we do about it". It reads the topic-tagged inbox
messages, hands Claude the distribution plus example messages, and gets back a
tight markdown brief: top themes, what's rising, and recommended actions.

The brief is cached to ``data/reports/inbox_insight_latest.md`` so the dashboard
can show it instantly and only regenerate on demand.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from pipeline import db
from pipeline.config_loader import load_keywords
from pipeline.timeutils import now_iso

load_dotenv(override=True)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
REPORT_PATH = Path(__file__).parent.parent / "data" / "reports" / "inbox_insight_latest.md"

SYSTEM_PROMPT = """\
You are a customer-insight analyst for a bank's HOME-LOAN team. You are given
private customer inbox messages (already translated to English and grouped by
topic). Write a SHORT, sharp brief in markdown — for a busy marketing/product
lead — with exactly these sections:

## 🔑 Top themes
3–4 bullets. Each: the theme, what customers actually want, and roughly how many
messages. Lead with the biggest.

## 📈 What stands out
2–3 bullets on notable or rising signals (e.g. a recurring question that implies
confusion or unmet demand).

## ✅ Recommended actions
2–3 concrete, specific actions the team could take this week (e.g. "add a
mortgage-rollover line to the page FAQ", "route new-inquiry DMs to a loan
officer within 1h"). No fluff.

Keep the whole thing under ~250 words. Be specific and grounded in the data —
do not invent themes that aren't in the messages."""


def _topic_labels() -> dict:
    return load_keywords().get("inbox", {}).get("topics", {})


def _load_messages() -> list[dict]:
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT topic, sentiment, summary_en, message, sent_at "
                "FROM inbox_messages WHERE summary_en IS NOT NULL "
                "ORDER BY sent_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("Could not load inbox messages: %s", exc)
        return []


def _build_context(messages: list[dict]) -> str:
    labels = _topic_labels()
    counts = Counter(m.get("topic") or "other" for m in messages)

    blocks = [f"Total home-loan inbox messages: {len(messages)}\n",
              "Topic distribution:"]
    for topic, n in counts.most_common():
        blocks.append(f"  - {topic} ({labels.get(topic, topic)}): {n}")

    blocks.append("\nExample messages per topic (English summaries):")
    for topic, _ in counts.most_common():
        examples = [m["summary_en"] for m in messages
                    if (m.get("topic") or "other") == topic and m.get("summary_en")][:6]
        blocks.append(f"\n[{topic}]")
        blocks.extend(f"  • {e}" for e in examples)
    return "\n".join(blocks)


def generate_inbox_insight() -> str:
    """Generate + cache the inbox insight brief. Returns markdown (or a notice)."""
    messages = _load_messages()
    if len(messages) < 3:
        return ("_Not enough inbox messages yet to find themes "
                "(need at least 3 categorized messages)._")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user",
                   "content": "Here is the inbox data:\n\n" + _build_context(messages)}],
    )
    brief = response.content[0].text.strip()

    try:
        from pipeline.collector import log_usage
        u = response.usage
        cost = (u.input_tokens / 1_000_000 * 3) + (u.output_tokens / 1_000_000 * 15)
        log_usage("claude_inbox_insight", MODEL, u.input_tokens, u.output_tokens, cost, len(messages))
    except Exception as exc:
        logger.warning("Could not log inbox-insight usage: %s", exc)

    full = f"_Generated {now_iso()[:16].replace('T', ' ')} · {len(messages)} messages_\n\n{brief}"
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(full, encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not cache inbox insight: %s", exc)
    return full


def get_latest_inbox_insight() -> Optional[str]:
    """Return the cached brief, or None if none generated yet."""
    try:
        return REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else None
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(generate_inbox_insight())
