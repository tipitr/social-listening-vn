"""Tests for the source-type taxonomy used to segment Action Feed views.

Why a separate taxonomy: a single article in the database has a free-text
``source`` field (e.g. ``"OTOFUN"``, ``"Vietcombank"``, ``"CafeF"``).
Different audience views in the dashboard want different cuts of this:

  - Customer Voice = forums (organic buyer chatter)
  - Competitor Watch = Facebook bank/realestate pages (marketing posts)
  - Press Coverage = news sites (journalist analysis)

This taxonomy maps every known source string to exactly one of three
buckets. Tests pin the contract so an unknown source falls back to
"news" (the safest default — it just doesn't show up in the segmented
views, only in Action Queue / Browse All).
"""

from __future__ import annotations

import pytest

# Import the helper we're about to write. If the import fails, that's
# the RED state — the implementation hasn't landed yet.
from dashboard.source_taxonomy import classify_source, SOURCE_TYPES


def test_source_types_constant_is_exactly_three_buckets():
    assert SOURCE_TYPES == ("facebook", "forum", "news"), (
        f"Expected the three-bucket taxonomy, got {SOURCE_TYPES}"
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        # ── Facebook pages: banks ────────────────────────────────────
        ("Vietcombank",     "facebook"),
        ("Techcombank",     "facebook"),
        ("VPBank",          "facebook"),
        ("MBBank",          "facebook"),
        ("ACB",             "facebook"),
        ("BIDV",            "facebook"),
        ("ShinhanVN",       "facebook"),
        # ── Facebook pages: real estate developers ───────────────────
        ("Vinhomes",        "facebook"),
        ("Masterise",       "facebook"),
        ("Novaland",        "facebook"),
        # ── Forums ───────────────────────────────────────────────────
        ("OTOFUN",          "forum"),
        ("6Giay",           "forum"),
        # ── News sites ───────────────────────────────────────────────
        ("CafeF",           "news"),
        ("CafeF_Banking",   "news"),
        ("VnExpress",       "news"),
        ("VnExpress_Banking", "news"),
        ("CafeLand",        "news"),
        ("VnEconomy",       "news"),
        ("VietnamNet",      "news"),
        ("BatDongSan",      "news"),
        ("DanTri",          "news"),
        ("TuoiTre",         "news"),
    ],
)
def test_classify_source_known_names(source, expected):
    assert classify_source(source) == expected, (
        f"{source!r} should classify as {expected!r}"
    )


def test_unknown_source_defaults_to_news():
    """A future source we haven't catalogued shouldn't crash or silently
    enter Customer Voice / Competitor Watch. Default to 'news' so it shows
    up in Action Queue + Browse All but doesn't pollute the audience cuts."""
    assert classify_source("BrandNewScraper2027") == "news"
    assert classify_source("") == "news"
    assert classify_source(None) == "news"  # type: ignore[arg-type]


def test_classify_is_case_sensitive_on_purpose():
    """Source names come from a controlled set of scraper modules — they
    are not user input. Case-sensitive matching catches typos in
    sources.yaml instead of silently coercing them."""
    # "vietcombank" (lowercase) is NOT the canonical source name — the
    # facebook.py scraper emits "Vietcombank" with capital V.
    assert classify_source("vietcombank") == "news"  # falls through to default
    assert classify_source("Vietcombank") == "facebook"
