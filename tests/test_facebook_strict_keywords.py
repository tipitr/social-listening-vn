"""FB scrapers must use STRICT home-loan-only keywords, not the loose
``forum_keywords`` set.

PROBLEM OBSERVED (2026-05-27):
Two Facebook posts slipped through and landed in the database even
though neither was about home loans:

  - VPBank: "🚗 SỞ HỮU BYD DOLPHIN 2026 – LÃI SUẤT HẤP DẪN CHỈ TỪ 8.5%/NĂM"
    → CAR LOAN — but "lãi suất" (interest rate) in forum_keywords matched
  - Techcombank: "TĂNG TỐC TÀI CHÍNH - LÀM CHỦ KINH DOANH"
    → BUSINESS LOAN — but no negative_filter caught it because it didn't
      say "vay kinh doanh" verbatim

ROOT CAUSE:
``forum_keywords`` in config/keywords.yaml is intentionally permissive —
it contains short terms like ``"lãi suất"``, ``"vay nhà"``, ``"mua nhà"``
so that forum thread *titles* (which are short) get caught. But the
Facebook scrapers also import this list, and FB bank posts ARE marketing
copy that often mentions ``"lãi suất"`` without ever being about home
loans.

THE FIX:
Drop ``forum_keywords`` from the FB scrapers' keyword set. The remaining
four lists (vietnamese / interest_rate / credit / promotions) every term
contains an explicit housing word (``"mua nhà"``, ``"căn hộ"``,
``"chung cư"``, ``"bất động sản"``, ``"thế chấp"``…). Posts will only
match if they actually mention home loans.

CONSEQUENCE:
FB volume will drop — banks don't post about home loans daily. That's
correct. Customer voice (forums) still uses the broad forum_keywords
because forum thread titles are short and explicit home-loan phrasing
is less common there.
"""

from __future__ import annotations

import pytest


# ─── Data: real posts we've seen + what we expect ───────────────────────────

# These three are the actual cases. Pinning them as test cases means
# if anyone re-adds forum_keywords to the FB scrapers later, this test
# screams.
NON_HOMELOAN_POSTS_THAT_SHOULD_BE_REJECTED = [
    # Car loan with "lãi suất" — currently slips through because forum_keywords includes "lãi suất" alone
    "🚗 SỞ HỮU BYD DOLPHIN 2026 – LÃI SUẤT HẤP DẪN CHỈ TỪ 8.5%/NĂM Sẵn sàng trải nghiệm xe điện",
    # Business loan dressed up with finance buzzwords — no "nhà" anywhere
    "TĂNG TỐC TÀI CHÍNH - LÀM CHỦ KINH DOANH Cơ hội đến trong tích tắc",
    # Credit card promo — uses "vay" but for personal credit
    "Mở thẻ tín dụng VPBank nhận ưu đãi đặc biệt lãi suất 0%",
]

HOMELOAN_POSTS_THAT_SHOULD_PASS = [
    # Direct home loan promo
    "Ưu đãi vay mua nhà chỉ từ 5.5%/năm. Liên hệ ngay!",
    # Mortgage rate announcement
    "Lãi suất vay mua nhà tháng 5/2026 chỉ từ 6%",
    # Home loan process info
    "Hồ sơ vay mua nhà tại Techcombank — thủ tục đơn giản",
]


# ─── Tests ──────────────────────────────────────────────────────────────────

def _is_relevant_fb(text: str) -> bool:
    """Call the FB scraper's relevance filter against the real config."""
    from pipeline.config_loader import load_keywords
    from scrapers.facebook_scraper3 import _all_keywords, _negative_keywords, _is_relevant
    cfg = load_keywords()
    return _is_relevant(text, _all_keywords(cfg), _negative_keywords(cfg))


@pytest.mark.parametrize("post", NON_HOMELOAN_POSTS_THAT_SHOULD_BE_REJECTED)
def test_non_homeloan_posts_are_filtered_out(post):
    assert not _is_relevant_fb(post), (
        f"This post is NOT about home loans and should not pass the FB scraper's "
        f"relevance filter:\n  {post}"
    )


@pytest.mark.parametrize("post", HOMELOAN_POSTS_THAT_SHOULD_PASS)
def test_homeloan_posts_pass(post):
    assert _is_relevant_fb(post), (
        f"This post IS about home loans and should pass the relevance filter:\n  {post}"
    )


def test_facebook_scrapers_do_not_pull_forum_keywords():
    """Static check — neither facebook.py nor facebook_scraper3.py should
    reach into keywords.yaml's forum_keywords set. That set is meant for
    short forum thread titles, not FB marketing copy."""
    import re
    from pathlib import Path
    repo = Path(__file__).parent.parent
    for rel in ("scrapers/facebook.py", "scrapers/facebook_scraper3.py"):
        src = (repo / rel).read_text(encoding="utf-8")
        # Look at the _all_keywords function body specifically — the bank
        # name list and other config reads are fine, but _all_keywords
        # must not append forum_keywords.
        # Match the _all_keywords function body up to the next top-level
        # def (avoids over-matching the rest of the file).
        m = re.search(r"def _all_keywords\b(.*?)(?=\ndef |\Z)", src, re.DOTALL)
        assert m, f"{rel}: could not locate _all_keywords function"
        body = m.group(1)
        # Strip docstrings first — explanatory comments that mention the
        # word "forum_keywords" are fine. We only fail if there's an actual
        # .get("forum_keywords") call or similar code-level reference.
        body_no_docstr = re.sub(r'""".*?"""', "", body, flags=re.DOTALL)
        assert 'forum_keywords' not in body_no_docstr, (
            f"{rel}: _all_keywords still pulls forum_keywords. Drop it — "
            f"those short terms make the FB filter match car loans and "
            f"credit-card promos."
        )
