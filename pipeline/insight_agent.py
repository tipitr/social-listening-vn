"""Social Listening Expert Agent — generates a business insight report from collected articles."""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import db  # noqa: E402
from pipeline.config_loader import load_banks as _load_banks_yaml  # noqa: E402
from pipeline.timeutils import days_ago_iso, now_local  # noqa: E402

load_dotenv()

REPORTS_DIR = Path(__file__).parent.parent / "data" / "reports"

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """\
You are a Senior Social Listening Analyst specialising in Vietnam's retail home loan market.
You work for a home loan product team. Your job is to turn raw news and forum data into
clear, actionable business intelligence.

Your audience is the home loan product team — marketing managers, product managers, and
business leads. They are NOT technical. Write like you are presenting at a Monday morning
business review:
- Plain English (use Vietnamese terms only for bank names, product names, or direct quotes)
- No data-science jargon
- Every finding must connect to a business implication
- Every recommendation must be specific and actionable

Report structure — follow it exactly:

## 1. Executive Summary
3 sentences max. What happened this period, and what matters most.

## 2. Key Themes
Top 3–4 topics dominating the conversation this period. For each:
- What people are saying (with 1–2 direct examples from the data)
- Why it matters for our home loan product

## 3. Sentiment Snapshot
Overall mood of the market. What is driving positive vs. negative sentiment?
Flag any emerging risks or signals the team should watch.

## 4. Competitor Intelligence
Which banks are being discussed? What are people saying about them?
Highlight gaps or opportunities relative to competitors.
If no specific banks are named in the data, analyse the broader competitive signals instead.

## 5. Customer Pain Points
Specific complaints and frustrations surfaced in the data.
Quote or paraphrase actual article titles/summaries where possible.
Connect each pain point to a product or service implication.

## 6. Market Opportunities
- People actively seeking home loan information (potential leads to capture)
- Positive promotions or products gaining traction that we could match or counter

## 7. Recommended Actions
Exactly 3–5 prioritised actions. For each:

🔴 URGENT / 🟡 THIS WEEK / 🟢 THIS MONTH
**Action:** [what to do — specific, not vague]
**Why:** [the data point that supports this]
**How:** [concrete next step the team can take tomorrow]

Be direct. Skip preamble. If the data is thin (fewer than 10 articles),
say so honestly at the top and caveat your findings accordingly.\
"""


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_banks() -> dict:
    cfg = _load_banks_yaml()
    aliases = {}
    for cat in ("state_owned", "private", "foreign"):
        for b in cfg.get(cat, []):
            aliases[b["short_name"]] = {
                "aliases":    b.get("aliases", [b["short_name"]]),
                "type":       cat,
                "promo_rate": b.get("promo_rate", ""),
            }
    return aliases


def _detect_banks(text: str, banks: dict) -> list[str]:
    t = (text or "").lower()
    found = []
    for name, info in banks.items():
        for alias in info["aliases"]:
            pat = r"(?<![a-z])" + re.escape(alias.lower()) + r"(?![a-z])"
            if re.search(pat, t):
                found.append(name)
                break
    return found


def _load_articles(days: int) -> list[dict]:
    try:
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT id, source, title, url, category, sentiment, intent,
                       summary_en, summary_vi, scraped_at
                FROM articles
                WHERE scraped_at >= :cutoff
                ORDER BY scraped_at DESC
            """, {"cutoff": days_ago_iso(days)}).fetchall()
    except Exception:
        # DB not initialised yet (no scrape has run) — return empty.
        return []
    return [dict(r) for r in rows]


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(articles: list[dict], bank_aliases: dict) -> str:
    for a in articles:
        text = " ".join(filter(None, [a.get("title"), a.get("summary_en"), a.get("summary_vi")]))
        a["banks_mentioned"] = _detect_banks(text, bank_aliases)

    sentiments  = Counter(a["sentiment"] for a in articles if a["sentiment"])
    categories  = Counter(a["category"]  for a in articles if a["category"])
    intents     = Counter(a["intent"]    for a in articles if a["intent"])
    sources     = Counter(a["source"]    for a in articles)

    bank_count = Counter()
    bank_sent  = {}
    for a in articles:
        for b in a["banks_mentioned"]:
            bank_count[b] += 1
            bank_sent.setdefault(b, Counter())[a.get("sentiment") or "unknown"] += 1

    n = len(articles)
    lines = [
        f"DATA SUMMARY — {n} articles",
        "",
        "Sources: " + ", ".join(f"{s}({c})" for s, c in sources.most_common()),
        "Sentiment: " + ", ".join(f"{s}={c}({c*100//n}%)" for s, c in sentiments.most_common()),
        "Categories: " + ", ".join(f"{c}={v}" for c, v in categories.most_common()),
        "Intents: " + ", ".join(f"{i}={v}" for i, v in intents.most_common()),
    ]

    if bank_count:
        lines += ["", "BANK MENTIONS:"]
        for bank, cnt in bank_count.most_common():
            info = bank_aliases.get(bank, {})
            sent_str = " | ".join(f"{s}:{v}" for s, v in bank_sent[bank].most_common())
            lines.append(
                f"  {bank} ({info.get('type','')}, promo {info.get('promo_rate','')}): "
                f"{cnt} mention(s) [{sent_str}]"
            )
    else:
        lines += ["", "BANK MENTIONS: none detected — banks mentioned generically or not named"]

    cat_order = ["complaint", "interest_rate", "promotion", "loan_approval", "bank_comparison", "general"]
    by_cat: dict[str, list] = {}
    for a in articles:
        by_cat.setdefault(a.get("category") or "general", []).append(a)

    lines += ["", "ARTICLES BY CATEGORY:"]
    for cat in cat_order:
        group = by_cat.get(cat, [])
        if not group:
            continue
        lines.append(f"\n[{cat.upper()}] — {len(group)} articles")
        for a in group:
            en    = (a.get("summary_en") or a.get("title") or "")[:160]
            vi    = (a.get("summary_vi") or "")[:100]
            sent  = a.get("sentiment") or "?"
            banks = ", ".join(a["banks_mentioned"]) if a["banks_mentioned"] else ""
            line  = f"  • [{sent}] {en}"
            if banks: line += f"  (Banks: {banks})"
            lines.append(line)
            if vi:   lines.append(f"    VI: {vi}")

    return "\n".join(lines)


# ── Report generation ─────────────────────────────────────────────────────────

def generate_report(days: int = 7, stream_callback=None) -> str:
    """
    Generate an insight report.
    If stream_callback is provided, it is called with each text chunk as it arrives.
    Returns the full markdown report string.
    """
    articles    = _load_articles(days)
    bank_aliases = _load_banks()

    if not articles:
        return (
            f"# No Data\n\n"
            f"No articles found in the last {days} days. "
            f"Run the collector first:\n\n```\npython3 -m pipeline.collector\n```"
        )

    context = _build_context(articles, bank_aliases)
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    parts: list[str] = []

    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[{
            "type":          "text",
            "text":          SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role":    "user",
            "content": (
                f"Generate the weekly social listening insight report.\n\n"
                f"Date: {now_local().strftime('%B %d, %Y')}\n"
                f"Period: last {days} days\n\n"
                f"{context}"
            ),
        }],
    ) as stream:
        for chunk in stream.text_stream:
            parts.append(chunk)
            if stream_callback:
                stream_callback(chunk)
        final = stream.get_final_message()

    report = "".join(parts)

    # Log token usage — Opus 4.7: $5/$25 per 1M in/out
    try:
        from pipeline.collector import log_usage
        u = final.usage
        cost = (u.input_tokens / 1_000_000 * 5) + (u.output_tokens / 1_000_000 * 25)
        log_usage("claude_insight", MODEL, u.input_tokens, u.output_tokens, cost, len(articles))
    except Exception:
        pass

    now = now_local()
    header = (
        f"# Social Listening Insight Report\n"
        f"**Generated:** {now.strftime('%B %d, %Y %H:%M')} (GMT+7)&nbsp;&nbsp;"
        f"**Period:** last {days} days&nbsp;&nbsp;"
        f"**Articles:** {len(articles)}\n\n---\n\n"
    )
    full_report = header + report

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"insight_{now.strftime('%Y%m%d_%H%M')}.md"
    out.write_text(full_report, encoding="utf-8")

    return full_report


def get_latest_report() -> Optional[str]:
    """Return the most recently saved report, or None."""
    if not REPORTS_DIR.exists():
        return None
    files = sorted(REPORTS_DIR.glob("insight_*.md"), reverse=True)
    return files[0].read_text(encoding="utf-8") if files else None


def markdown_to_html(md_text: str) -> str:
    """Convert a markdown report to a standalone HTML document.

    Print-friendly styling so the team can open the file in any browser,
    hit Ctrl/Cmd+P, and save as PDF without needing a server-side PDF lib.
    """
    import markdown as _md

    body = _md.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Social Listening Insight Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
          max-width: 820px; margin: 40px auto; padding: 0 24px;
          color: #1a1a1a; line-height: 1.6; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  h2 {{ border-bottom: 1px solid #eee; padding-bottom: 6px; margin-top: 36px; font-size: 20px; }}
  h3 {{ margin-top: 24px; font-size: 16px; }}
  code, pre {{ background: #f6f6f6; padding: 2px 6px; border-radius: 4px; font-size: 0.92em; }}
  pre {{ padding: 12px; overflow-x: auto; }}
  blockquote {{ border-left: 3px solid #ccc; margin: 0; padding-left: 16px; color: #555; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 12px; text-align: left; }}
  th {{ background: #fafafa; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 24px 0; }}
  @media print {{ body {{ margin: 20px; max-width: none; }} }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"\nGenerating report for last {days} days...\n{'─'*60}\n")

    def _print(chunk: str):
        print(chunk, end="", flush=True)

    report = generate_report(days, stream_callback=_print)
    saved  = sorted(REPORTS_DIR.glob("insight_*.md"), reverse=True)[0]
    print(f"\n\n{'─'*60}\nSaved to: {saved}\n")
