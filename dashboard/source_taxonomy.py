"""Source-type taxonomy: maps every article ``source`` string to one of
three audience-meaningful buckets.

Why three buckets:
    The dashboard has three different audiences leaning on the same
    article stream for different jobs.

      forum     → "Customer Voice" view (what buyers actually say)
      facebook  → "Competitor Watch" view (what bank/realestate
                  marketers push out)
      news      → press coverage; everything else; sensible default

Why not derive from URLs:
    The ``source`` field in the DB is a controlled vocabulary set by
    each scraper module (scrapers/news.py, scrapers/forums.py, etc.).
    Hardcoding the mapping here means changing the taxonomy is a
    one-file edit — no DB migration, no scraper refactor.

How to add a new source:
    Append the canonical source name (matching the literal string the
    scraper emits) to the matching set below. Then add a test row to
    tests/test_source_taxonomy.py to pin the assignment.
"""

from __future__ import annotations

SOURCE_TYPES: tuple = ("facebook", "forum", "news")

# Facebook page names — match the ``name`` field of each entry in
# config/sources.yaml's facebook_pages list.
_FACEBOOK_SOURCES = frozenset({
    # Direct bank competitors
    "Vietcombank", "Techcombank", "VPBank", "MBBank", "ACB", "BIDV",
    # Foreign-bank peers
    "ShinhanVN",
    # Real estate developers (customer-voice-adjacent — these pages have
    # buyer chatter in comments — but conceptually still "what marketers
    # push", so they live in Competitor Watch alongside banks.)
    "Vinhomes", "Masterise", "Novaland",
})

# Forum source labels — emitted by scrapers/forums.py and scrapers/smart_scraper.py.
_FORUM_SOURCES = frozenset({
    "OTOFUN", "6Giay",
})

# Everything else (news sites, future sources, unknown strings) is "news"
# by default. We don't list news sources explicitly — it'd be a long
# maintenance treadmill — and an unknown source falling into "news"
# means it appears in Action Queue and Browse All but doesn't pollute
# the Customer Voice / Competitor Watch cuts. Safe default.


def classify_source(source: str | None) -> str:
    """Return one of SOURCE_TYPES for the given canonical source name.

    Case-sensitive on purpose: the source field is set by scraper code,
    not by users. Case-sensitive matching catches typos in sources.yaml
    instead of silently coercing them.
    """
    if not source:
        return "news"
    if source in _FACEBOOK_SOURCES:
        return "facebook"
    if source in _FORUM_SOURCES:
        return "forum"
    return "news"
