"""Forum scrapers must reject classified-style listings.

OBSERVED PROBLEM (2026-05-28):
OTOFUN's real-estate sub-forum is dominated by personal listings —
people selling their apartment, renting out rooms, posting their phone
number with "chính chủ miễn trung gian". These match the existing
forum_keywords ("chung cư", "bán nhà", "căn hộ") so they slip into the
dashboard as noise, drowning real home-loan discussion.

Example titles from the live DB that DON'T belong in a home-loan
intelligence feed:

  "Bán chung cư lô góc 95m² – Eco Green City"
  "E bán căn chung cư 139M Đông nam – CT1 Hyundai Hillstate"
  "Gia đình tôi cần bán nhà ngõ 60 Dương Khuê, Mai Dịch"
  "Cho thuê phòng trọ khép kín..."
  "Bán nhà Tô Hiệu Hà Đông"

These are person-to-person classified ads. The team wants to hear from
*buyers* (asking, complaining, comparing banks) — not sellers/landlords.

THE FIX
Extend negative_filter in config/keywords.yaml with strong listing
markers. Real home-loan discussion never uses "cần bán", "cho thuê",
"chính chủ" as positive content, so these are safe to use as filters.
"""

from __future__ import annotations

import pytest


# Real classified-listing titles that must be rejected after the fix.
LISTING_TITLES_TO_REJECT = [
    "Bán chung cư lô góc 95m² – Eco Green City",
    "E bán căn chung cư 139M Đông nam – CT1 Hyundai Hillstate Hà Đông.",
    "Gia đình tôi cần bán nhà ngõ 60 Dương Khuê, Mai Dịch",
    "Cho thuê phòng trọ khép kín (ở được đến 4 người) trong chung cư mini mới",
    "Bán nhà Tô Hiệu Hà Đông",
    "Bán Chung cư CT7 Booyoung, diện tích 107m2",
    "Bán gấp chung cư 2 phòng ngủ, chính chủ miễn trung gian",
    "Chính chủ bán shophouse Vinhomes Smart City",
]

# Real home-loan discussion that MUST still pass — protects against
# over-filtering. These are the kind of posts the dashboard exists to
# surface.
HOMELOAN_DISCUSSION_TO_KEEP = [
    "Có cụ nào ở OF bị trắng tay vì mua nhà Usilk City SĐTL không ạ?",
    "Lãi suất vay mua nhà của Vietcombank hiện tại thế nào ạ?",
    "Cụ nào vay mua nhà ở Techcombank xong cho em hỏi điều kiện với",
    "Chung cư Melody Linh Đàm, có nên mua hay không ạ?",  # buyer asking
    "Hỏi về vay thế chấp mua chung cư, ngân hàng nào duyệt nhanh nhất?",
]


def _is_relevant_forum(text: str) -> bool:
    """Call the forum scraper's relevance filter against the real config."""
    from pipeline.config_loader import load_keywords
    from scrapers.forums import _all_keywords, _negative_keywords, _is_relevant
    cfg = load_keywords()
    return _is_relevant(text, _all_keywords(cfg), _negative_keywords(cfg))


@pytest.mark.parametrize("title", LISTING_TITLES_TO_REJECT)
def test_classified_listings_are_filtered_out(title):
    assert not _is_relevant_forum(title), (
        f"This title is a personal listing/classified ad and should not "
        f"land in the dashboard:\n  {title}"
    )


@pytest.mark.parametrize("title", HOMELOAN_DISCUSSION_TO_KEEP)
def test_homeloan_discussion_still_passes(title):
    assert _is_relevant_forum(title), (
        f"This title is a legitimate home-loan question/discussion and "
        f"MUST still pass the filter:\n  {title}"
    )
