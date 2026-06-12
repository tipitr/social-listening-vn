"""Question miner — turns each inbox topic into the top recurring questions.

A topic like "new_inquiry × 431" is too coarse to act on. This groups the
messages within a topic into the handful of DISTINCT questions customers
actually keep asking, each with a count and a representative example — so a
content writer gets a ready backlog ("answer these 8 questions") instead of 431
raw messages to read.

Output is cached to ``data/reports/inbox_questions.json`` and read by the
dashboard.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
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
QUESTIONS_PATH = Path(__file__).parent.parent / "data" / "reports" / "inbox_questions.json"
MIN_MESSAGES = 8     # topics smaller than this aren't worth clustering
MAX_QUESTIONS = 8    # cap questions surfaced per topic

SYSTEM_PROMPT = """\
You are a content strategist for a bank's home-loan team. You are given customer
enquiry items that all belong to ONE topic. Each item has an English summary and
the original Vietnamese message. Group them into the TOP distinct recurring
QUESTIONS customers ask — the level a content writer would each answer with one
FAQ entry, post, or page section.

Return ONLY a JSON array (no markdown), ordered by count descending, each item:
- "question": the canonical question, phrased clearly in English as a content
  writer would title it (e.g. "How do I start a home loan application?")
- "count": integer — roughly how many items fall under it
- "example": one short representative customer phrasing copied VERBATIM from the
  original Vietnamese messages (so copywriters can mirror real customer words)

Merge near-duplicates. Only include questions genuinely present. Max 8 items."""


def _topic_labels() -> dict:
    return load_keywords().get("inbox", {}).get("topics", {})


def _messages_by_topic() -> dict:
    by_topic = defaultdict(list)
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT topic, summary_en, message FROM inbox_messages "
                "WHERE summary_en IS NOT NULL AND topic IS NOT NULL"
            ).fetchall()
        for r in rows:
            d = dict(r)
            by_topic[d["topic"]].append({"summary": d["summary_en"], "vi": d["message"]})
    except Exception as exc:
        logger.warning("Could not load inbox messages: %s", exc)
    return by_topic


def _extract_json(text: str) -> list:
    import re
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    return json.loads(text)


def _mine_topic(client, topic: str, summaries: list) -> list:
    payload = json.dumps(summaries, ensure_ascii=False)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user",
                   "content": f"Topic: {topic}. Summaries:\n{payload}"}],
    )
    try:
        from pipeline.collector import log_usage
        u = resp.usage
        cost = (u.input_tokens / 1_000_000 * 3) + (u.output_tokens / 1_000_000 * 15)
        log_usage("claude_inbox_questions", MODEL, u.input_tokens, u.output_tokens, cost, len(summaries))
    except Exception:
        pass
    try:
        items = _extract_json(resp.content[0].text)
    except Exception as exc:
        logger.warning("Question parse failed for %s: %s", topic, exc)
        return []
    out = []
    for it in items[:MAX_QUESTIONS]:
        q = (it.get("question") or "").strip()
        if not q:
            continue
        out.append({
            "question": q[:160],
            "count": int(it.get("count", 0) or 0),
            "example": (it.get("example") or "").strip()[:160],
        })
    return out


def generate_question_map() -> dict:
    """Mine top questions per topic, cache to JSON, and return the map."""
    by_topic = _messages_by_topic()
    if not by_topic:
        return {}

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    result = {}
    # Largest topics first so the most valuable backlog is mined even if we stop early.
    for topic, summaries in sorted(by_topic.items(), key=lambda kv: -len(kv[1])):
        if len(summaries) < MIN_MESSAGES:
            continue
        logger.info("Mining questions for %s (%d messages)…", topic, len(summaries))
        questions = _mine_topic(client, topic, summaries)
        if questions:
            result[topic] = questions

    payload = {"generated": now_iso(), "topics": result}
    try:
        QUESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUESTIONS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not cache question map: %s", exc)
    return payload


def get_question_map() -> Optional[dict]:
    """Return the cached question map, or None if not generated yet."""
    try:
        if QUESTIONS_PATH.exists():
            return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    m = generate_question_map()
    for topic, qs in m.get("topics", {}).items():
        print(f"\n=== {topic} ===")
        for q in qs:
            print(f"  ({q['count']:>3}) {q['question']}")
