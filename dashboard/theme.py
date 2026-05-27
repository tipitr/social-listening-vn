"""Single source of truth for the dashboard's visual identity.

Why this lives outside dashboard/app.py:
    The insight report (pipeline/insight_agent.py) generates standalone HTML
    that we want branded too. Importing from dashboard/app.py would pull in
    Streamlit at report-generation time. Keeping the palette in a pure-Python
    module lets both surfaces share one set of brand tokens without that
    dependency.

How to use:
    >>> from dashboard.theme import THEME, SENT_COLOR, CAT_COLOR
    >>> THEME["primary"]              # '#138F2D'
    >>> THEME["sentiment"]["positive"] # '#138F2D'

The two aliases at the bottom (SENT_COLOR, CAT_COLOR) preserve the shape that
Plotly chart code already passes via ``color_discrete_map=...``, so no chart
needs to change when the palette is rebranded again later.

Design rationale:
    * Anchored on KBank's public brand green (#138F2D).
    * Positive sentiment intentionally collapses onto the brand color — good
      news == brand.
    * Negative stays red and complaints stay red. Affordance must override
      brand alignment: a green "complaint" badge would be confusing.
    * Loan-approval stays blue. With six adjacent green category cards in
      Action Feed, charts would lose distinguishability. One blue + one red
      preserves readability without diluting the green identity.
"""

from __future__ import annotations

THEME: dict = {
    # ── Core brand ──────────────────────────────────────────────────────────
    "primary":        "#138F2D",   # KBank green
    "primary_dark":   "#0E6B22",   # hover, headings on tinted bg
    "primary_darker": "#094D18",   # high-contrast text on light tints
    "primary_light":  "#3FAE52",   # secondary accents, chart highlights
    "primary_pale":   "#E6F4E9",   # card wash / tinted backgrounds
    "primary_paler":  "#F2FAF4",   # very subtle wells

    # ── Neutrals ────────────────────────────────────────────────────────────
    "bg":          "#FFFFFF",
    "bg_alt":      "#F4F6F4",      # warm-leaning grey (replaces #f4f6f8)
    "card_bg":     "#FFFFFF",
    "card_border": "#E5EAE6",
    "text":        "#1A1F2C",
    "text_muted":  "#5B6470",
    "text_subtle": "#8A93A0",
    "divider":     "#ECEFEC",

    # ── Functional (sentiment / status) ─────────────────────────────────────
    # bg = pale wash for tinted containers; fg = high-contrast text for the
    # same context (e.g. amber wash + amber-700 text on the scrape badge).
    "success":  "#138F2D", "success_bg": "#E6F4E9", "success_fg": "#0E6B22",
    "warning":  "#B7791F", "warning_bg": "#FDF4E1", "warning_fg": "#7A4F09",
    "danger":   "#C0392B", "danger_bg":  "#FBE9E7", "danger_fg":  "#8E2A1F",
    "info":     "#1F6FB2", "info_bg":    "#E8F1F8", "info_fg":    "#1F4F7A",

    # ── Sentiment palette (Plotly + badges) ─────────────────────────────────
    "sentiment": {
        "positive": "#138F2D",   # = primary (good news == brand)
        "neutral":  "#8A93A0",
        "negative": "#C0392B",
    },

    # ── Category palette: tonal green-led, with one red + one blue
    #    kept so stacked bars remain readable. ───────────────────────────────
    # Each entry has (accent, bg). bg = pale wash for section card wells.
    "category": {
        "complaint":       {"accent": "#C0392B", "bg": "#FBE9E7"},
        "interest_rate":   {"accent": "#0E6B22", "bg": "#E6F4E9"},
        "promotion":       {"accent": "#3FAE52", "bg": "#EEF8F0"},
        "loan_approval":   {"accent": "#1F6FB2", "bg": "#E8F1F8"},
        "bank_comparison": {"accent": "#B7791F", "bg": "#FDF4E1"},
        "general":         {"accent": "#5B6470", "bg": "#F2F4F2"},
    },

    # ── Hero "Today's signal" card ──────────────────────────────────────────
    "hero": {
        "bg_gradient": "linear-gradient(135deg,#E6F4E9 0%,#FFFFFF 60%)",
        "border":      "#C9E4CF",
        "accent":      "#138F2D",
        "kicker_fg":   "#0E6B22",   # uppercase "TODAY'S SIGNAL" label
    },
}

# ── Backwards-compat aliases ────────────────────────────────────────────────
# Existing Plotly calls already accept these shapes via
# ``color_discrete_map=SENT_COLOR`` / ``color_discrete_map=CAT_COLOR``. By
# rebuilding them from THEME we keep zero chart-code changes when the palette
# changes again later.
SENT_COLOR: dict[str, str] = THEME["sentiment"]
CAT_COLOR:  dict[str, str] = {k: v["accent"] for k, v in THEME["category"].items()}
