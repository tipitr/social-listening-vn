"""Categorize articles via Claude API and write results back to the database."""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from pipeline import db
from pipeline.collector import init_db, log_usage
from pipeline.config_loader import load_settings

# override=True so an empty shell-exported ANTHROPIC_API_KEY (e.g. from a
# stale ~/.zshrc export) doesn't shadow the real value in .env.
load_dotenv(override=True)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích nội dung tài chính Việt Nam, chuyên về lĩnh vực \
vay mua nhà và tín dụng ngân hàng bán lẻ.

Nhiệm vụ: Phân tích danh sách bài viết và trả về JSON array.

Với mỗi bài viết, trả về object JSON với đúng các trường sau:
- "id": số nguyên ID của bài viết (giữ nguyên, không thay đổi)
- "sentiment": cảm xúc tổng thể — chỉ dùng một trong: "positive", "negative", "neutral"
- "category": chủ đề chính — chỉ dùng một trong:
    "interest_rate"   (lãi suất, lãi vay, lãi tiết kiệm)
    "loan_approval"   (xét duyệt vay, điều kiện vay, hồ sơ vay)
    "bank_comparison" (so sánh ngân hàng, đánh giá sản phẩm)
    "complaint"       (phàn nàn, khiếu nại, trải nghiệm tiêu cực)
    "promotion"       (khuyến mãi, ưu đãi, chương trình lãi suất thấp)
    "general"         (tin tức tổng hợp không thuộc nhóm trên)
- "intent": mục đích bài viết — chỉ dùng một trong:
    "seeking_info"        (đang hỏi, tìm kiếm thông tin)
    "sharing_experience"  (chia sẻ kinh nghiệm cá nhân)
    "complaint"           (phản ánh vấn đề, bức xúc)
    "promotion"           (quảng bá sản phẩm, dịch vụ)
- "summary_vi": tóm tắt ngắn gọn bằng tiếng Việt, tối đa một câu (dưới 100 ký tự)
- "summary_en": one-sentence English translation/summary of the article (under 120 characters)

Chỉ trả về JSON array thuần, không thêm markdown, không giải thích.\
"""

_FETCH_UNCATEGORIZED = """
    SELECT id, title, summary
    FROM articles
    WHERE (sentiment IS NULL OR summary_en IS NULL)
      AND id > :after
      AND length(COALESCE(title, '') || COALESCE(summary, '')) >= :min_len
    ORDER BY id
    LIMIT :batch_size;
"""

_UPDATE_ARTICLE = """
    UPDATE articles
    SET sentiment  = :sentiment,
        category   = :category,
        intent     = :intent,
        summary_vi = :summary_vi,
        summary_en = :summary_en
    WHERE id = :id;
"""

# Inbox messages get a richer `topic` (from config) + sentiment + translation.
_FETCH_UNCAT_INBOX = """
    SELECT id, message
    FROM inbox_messages
    WHERE (topic IS NULL OR summary_en IS NULL)
      AND id > :after
      AND length(COALESCE(message, '')) >= :min_len
    ORDER BY id
    LIMIT :batch_size;
"""

_UPDATE_INBOX = """
    UPDATE inbox_messages
    SET topic      = :topic,
        sentiment  = :sentiment,
        summary_vi = :summary_vi,
        summary_en = :summary_en
    WHERE id = :id;
"""

_VALID_SENTIMENTS  = {"positive", "negative", "neutral"}
_VALID_CATEGORIES  = {"interest_rate", "loan_approval", "bank_comparison",
                      "complaint", "promotion", "general"}
_VALID_INTENTS     = {"seeking_info", "sharing_experience", "complaint", "promotion"}


def _inbox_topics() -> dict:
    """Topic key → description, from config/keywords.yaml (inbox.topics)."""
    from pipeline.config_loader import load_keywords
    topics = load_keywords().get("inbox", {}).get("topics", {})
    return topics or {"other": "Home-loan related"}


def _build_inbox_prompt() -> str:
    topics = _inbox_topics()
    lines = "\n".join(f'    "{k}" — {v}' for k, v in topics.items())
    return (
        "Bạn là chuyên gia phân tích hội thoại chăm sóc khách hàng vay mua nhà "
        "của ngân hàng (tiếng Việt).\n\n"
        "Mỗi tin nhắn là một câu hỏi/yêu cầu RIÊNG của khách hàng gửi vào trang. "
        "Với mỗi tin nhắn, trả về object JSON với đúng các trường:\n"
        '- "id": số nguyên ID (giữ nguyên)\n'
        '- "topic": chủ đề — chỉ dùng MỘT trong các khóa sau:\n'
        f"{lines}\n"
        '- "sentiment": "positive" | "negative" | "neutral"\n'
        '- "summary_vi": tóm tắt ý định khách hàng bằng tiếng Việt (dưới 100 ký tự)\n'
        '- "summary_en": one-sentence English summary of what the customer wants '
        "(under 120 characters)\n\n"
        "Chỉ trả về JSON array thuần, không markdown, không giải thích."
    )


def _validate_inbox(item: dict) -> dict:
    valid_topics = set(_inbox_topics().keys())
    topic = item.get("topic")
    return {
        "id":         item["id"],
        "topic":      topic if topic in valid_topics else "other",
        "sentiment":  item.get("sentiment") if item.get("sentiment") in _VALID_SENTIMENTS else "neutral",
        "summary_vi": (item.get("summary_vi") or "")[:200],
        "summary_en": (item.get("summary_en") or "")[:300],
    }


def _fetch_batch(fetch_sql: str, batch_size: int, min_len: int, after: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            fetch_sql,
            {"batch_size": batch_size, "min_len": min_len, "after": after},
        ).fetchall()
    return [dict(r) for r in rows]


def _update_batch(update_sql: str, results: list[dict]) -> int:
    with db.connect() as conn:
        conn.executemany(update_sql, results)
    return len(results)


def _extract_json(text: str) -> list:
    """Parse JSON array from Claude response, tolerating markdown fences."""
    text = text.strip()
    # Strip ```json … ``` fences if present
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    return json.loads(text)


def _validate(item: dict) -> dict:
    """Normalise a single result dict; fall back to 'general'/'neutral' if invalid."""
    return {
        "id":         item["id"],
        "sentiment":  item.get("sentiment")  if item.get("sentiment")  in _VALID_SENTIMENTS  else "neutral",
        "category":   item.get("category")   if item.get("category")   in _VALID_CATEGORIES  else "general",
        "intent":     item.get("intent")     if item.get("intent")     in _VALID_INTENTS     else "seeking_info",
        "summary_vi": (item.get("summary_vi") or "")[:200],
        "summary_en": (item.get("summary_en") or "")[:300],
    }


def _build_user_message(items: list[dict]) -> str:
    """Items are already shaped as {id, title, content}."""
    return (
        "Phân tích các bài viết sau và trả về JSON array:\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
    )


_MAX_ATTEMPTS = 3


def _call_with_retry(client, **kwargs):
    """Call Claude, retrying transient API errors with 2s/4s backoff.

    AuthenticationError re-raises immediately (a bad key won't fix itself —
    it's an APIError subclass, so it must be caught first). After the final
    attempt the APIError propagates so the caller's skip-batch handling runs.
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise
        except anthropic.APIError as exc:
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            wait = 2 * (2 ** attempt)   # 2s, 4s
            logger.warning("Claude API error (attempt %d/%d), retrying in %ds: %s",
                           attempt + 1, _MAX_ATTEMPTS, wait, exc)
            time.sleep(wait)


def _categorize(fetch_sql: str, update_sql: str, to_item, label: str,
                system_prompt: str = SYSTEM_PROMPT, validate_fn=_validate,
                min_len_override: Optional[int] = None) -> int:
    """Shared loop: fetch uncategorized rows, label with Claude, write back.

    ``to_item`` maps a DB row to the {id, title, content} shape Claude reads.
    ``system_prompt`` / ``validate_fn`` differ between articles (6 categories)
    and inbox messages (richer topic taxonomy). ``min_len_override`` lets the
    inbox accept short-but-real enquiries (e.g. "vay thế chấp") that the
    article-tuned floor would skip.
    """
    init_db()

    cfg = load_settings()
    batch_size = cfg.get("categorizer", {}).get("batch_size", 20)
    min_len    = (min_len_override if min_len_override is not None
                  else cfg.get("categorizer", {}).get("min_content_length", 20))

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    total_categorized = 0
    after = 0   # id cursor — advances past failed batches so a bad batch
                # can't be refetched forever within one run

    while True:
        batch = _fetch_batch(fetch_sql, batch_size, min_len, after)
        if not batch:
            break

        logger.info("Processing batch of %d %s (ids %d–%d)",
                    len(batch), label, batch[0]["id"], batch[-1]["id"])
        try:
            response = _call_with_retry(
                client,
                model=MODEL,
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user",
                           "content": _build_user_message([to_item(r) for r in batch])}],
            )
            raw = response.content[0].text
            parsed = _extract_json(raw)
            validated = [validate_fn(item) for item in parsed]
            saved = _update_batch(update_sql, validated)
            total_categorized += saved
            logger.info("  → categorized %d %s", saved, label)

            # Log token usage — Sonnet 4.6: $3/$15 per 1M in/out
            u = response.usage
            cost = (u.input_tokens / 1_000_000 * 3) + (u.output_tokens / 1_000_000 * 15)
            log_usage("claude_categorizer", MODEL, u.input_tokens, u.output_tokens, cost, saved)

            # Advance past this batch even on success: the fetch is ORDER BY id,
            # so every NULL row ≤ batch[-1]["id"] was IN this batch. If Claude's
            # response omitted an item (valid JSON, missing ids), the unstamped
            # row would otherwise be refetched forever within this run. Advancing
            # defers it to the next run — same treatment as a failed batch.
            after = batch[-1]["id"]

        except json.JSONDecodeError as exc:
            # Claude occasionally returns half-truncated JSON. Skip PAST this
            # batch (cursor) so the rest of the day's items still get labeled;
            # the skipped rows stay NULL and are retried on the next run.
            logger.error("Failed to parse JSON response for batch (skipping past it): %s", exc)
            after = batch[-1]["id"]
            continue
        except anthropic.AuthenticationError as exc:
            # NOT transient — a bad key won't fix itself, no point looping.
            logger.error("Authentication failed — check ANTHROPIC_API_KEY: %s", exc)
            break
        except anthropic.APIError as exc:
            # Already retried 3x inside _call_with_retry. Move past the batch.
            logger.error("Claude API error for batch after retries (skipping past it): %s", exc)
            after = batch[-1]["id"]
            continue

    logger.info("Done. Total %s categorized this run: %d", label, total_categorized)
    return total_categorized


def run() -> int:
    """Categorize all pending articles. Returns total count categorized."""
    return _categorize(
        _FETCH_UNCATEGORIZED, _UPDATE_ARTICLE,
        lambda r: {"id": r["id"], "title": r["title"], "content": r.get("summary", "")},
        "articles",
    )


def run_inbox() -> int:
    """Categorize all pending inbox messages with the richer topic taxonomy."""
    return _categorize(
        _FETCH_UNCAT_INBOX, _UPDATE_INBOX,
        lambda r: {"id": r["id"], "title": "", "content": r["message"]},
        "inbox messages",
        system_prompt=_build_inbox_prompt(),
        validate_fn=_validate_inbox,
        min_len_override=5,   # inbox enquiries are short ("vay thế chấp" = 12 chars)
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
