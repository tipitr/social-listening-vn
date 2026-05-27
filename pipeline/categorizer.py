"""Categorize articles via Claude API and write results back to the database."""

import json
import logging
import os
import re
from pathlib import Path

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

_VALID_SENTIMENTS  = {"positive", "negative", "neutral"}
_VALID_CATEGORIES  = {"interest_rate", "loan_approval", "bank_comparison",
                      "complaint", "promotion", "general"}
_VALID_INTENTS     = {"seeking_info", "sharing_experience", "complaint", "promotion"}


def _fetch_batch(batch_size: int, min_len: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            _FETCH_UNCATEGORIZED,
            {"batch_size": batch_size, "min_len": min_len},
        ).fetchall()
    return [dict(r) for r in rows]


def _update_batch(results: list[dict]) -> int:
    with db.connect() as conn:
        conn.executemany(_UPDATE_ARTICLE, results)
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


def _build_user_message(articles: list[dict]) -> str:
    items = [
        {"id": a["id"], "title": a["title"], "content": a.get("summary", "")}
        for a in articles
    ]
    return (
        "Phân tích các bài viết sau và trả về JSON array:\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
    )


def run() -> int:
    """Categorize all pending articles. Returns total count categorized."""
    init_db()

    cfg = load_settings()
    batch_size = cfg.get("categorizer", {}).get("batch_size", 20)
    min_len    = cfg.get("categorizer", {}).get("min_content_length", 20)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    total_categorized = 0

    while True:
        batch = _fetch_batch(batch_size, min_len)
        if not batch:
            break

        logger.info("Processing batch of %d articles (ids %d–%d)",
                    len(batch), batch[0]["id"], batch[-1]["id"])
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": _build_user_message(batch)}],
            )
            raw = response.content[0].text
            parsed = _extract_json(raw)
            validated = [_validate(item) for item in parsed]
            saved = _update_batch(validated)
            total_categorized += saved
            logger.info("  → categorized %d articles", saved)

            # Log token usage — Sonnet 4.6: $3/$15 per 1M in/out
            u = response.usage
            cost = (u.input_tokens / 1_000_000 * 3) + (u.output_tokens / 1_000_000 * 15)
            log_usage("claude_categorizer", MODEL, u.input_tokens, u.output_tokens, cost, saved)

        except json.JSONDecodeError as exc:
            # Transient — Claude occasionally returns half-truncated JSON.
            # Skip this batch but keep processing the rest so a single bad
            # response doesn't strand the day's articles uncategorized.
            logger.error("Failed to parse JSON response for batch (skipping): %s", exc)
            continue
        except anthropic.AuthenticationError as exc:
            # NOT transient — a bad key won't fix itself, no point looping.
            logger.error("Authentication failed — check ANTHROPIC_API_KEY: %s", exc)
            break
        except anthropic.APIError as exc:
            # Transient — 529 (overloaded), 503, transient network. Same
            # rationale: keep going. The next batch may well succeed.
            logger.error("Claude API error for batch (skipping): %s", exc)
            continue

    logger.info("Done. Total categorized this run: %d", total_categorized)
    return total_categorized


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
