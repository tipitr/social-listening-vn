"""Streamlit dashboard — Social Listening VN: Home Loan Product Intelligence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# set_page_config MUST come before any other Streamlit call (including st.secrets).
st.set_page_config(page_title="Home Loan Intel", page_icon="🏠", layout="wide")

# ── Dark "Bloomberg / Bank-grade" stylesheet ─────────────────────────────────
# OLED dark mode with IBM Plex Sans + Plex Mono. KBank green is the only
# accent — every positive indicator, focus state, and CTA. Subtle green glow
# on hover gives the trading-desk feel. Single CSS block does the heavy
# lifting; underlying Streamlit widgets stay the same.
st.html(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
      /* ── Base / dark canvas ───────────────────────────────────────── */
      html, body, [class*="css"], .stApp, .main, [data-testid="stAppViewContainer"] {
        font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        color: #F8FAFC;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
      }
      .stApp, [data-testid="stAppViewContainer"], .main {
        background: #020617 !important;
        background-image:
          radial-gradient(circle at 0% 0%, rgba(34,197,94,0.04), transparent 40%),
          radial-gradient(circle at 100% 0%, rgba(59,130,246,0.03), transparent 40%);
      }
      [data-testid="stHeader"] { background: transparent !important; }
      [data-testid="stToolbar"] { background: transparent !important; }

      /* ── Sidebar — dark surface ─────────────────────────────────── */
      [data-testid="stSidebar"], [data-testid="stSidebarContent"],
      section[data-testid="stSidebar"] > div {
        background: #070D1C !important;
        border-right: 1px solid #1E293B !important;
      }
      [data-testid="stSidebar"] * { color: #CBD5E1 !important; }
      [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
      [data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 {
        color: #F8FAFC !important;
      }
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
        color: #F8FAFC !important;
      }
      [data-testid="stSidebar"] hr { border-top: 1px solid #1E293B !important; }
      /* Sidebar collapse arrow */
      [data-testid="stSidebarCollapseButton"] button,
      [data-testid="collapsedControl"] {
        background: #070D1C !important;
        color: #94A3B8 !important;
      }

      /* ── Plotly charts — eliminate any leftover white edges ─────── */
      [data-testid="stPlotlyChart"], .stPlotlyChart, .js-plotly-plot,
      .plotly, .plot-container {
        background: transparent !important;
      }
      .js-plotly-plot .plotly .main-svg { background: transparent !important; }
      .modebar { background: transparent !important; }
      .modebar-btn path { fill: #64748B !important; }

      /* Headings — Plex Sans bold, tight tracking */
      h1, h2, h3, h4, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.015em;
        color: #F8FAFC !important;
      }
      h1, .stMarkdown h1 { font-size: 1.9rem !important; line-height: 1.15; font-weight: 700 !important; }
      h2, .stMarkdown h2 { font-size: 1.4rem !important; line-height: 1.2; }
      h3, .stMarkdown h3 { font-size: 1.1rem !important; line-height: 1.3; font-weight: 600 !important; }

      p, span, div, label, .stMarkdown { color: #CBD5E1; }

      /* Caption */
      .stCaption, [data-testid="stCaptionContainer"], small {
        font-family: 'IBM Plex Mono', monospace !important;
        color: #64748B !important;
        font-size: 0.75rem !important;
        letter-spacing: 0.02em;
        text-transform: uppercase;
      }

      /* ── Layout container ─────────────────────────────────────────── */
      .block-container {
        padding-top: 2rem !important;
        padding-bottom: 4rem !important;
        max-width: 1320px;
      }

      /* ── Tabs — terminal-style underline ──────────────────────────── */
      [data-testid="stTabs"] [role="tablist"] {
        gap: 0;
        border-bottom: 1px solid #1E293B;
        padding-bottom: 0;
        margin-bottom: 1.5rem;
        background: transparent;
      }
      [data-testid="stTabs"] [role="tab"] {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        color: #64748B !important;
        padding: 14px 18px !important;
        border-radius: 0 !important;
        background: transparent !important;
        border-bottom: 2px solid transparent !important;
        transition: all 0.15s ease;
        letter-spacing: 0.02em;
      }
      [data-testid="stTabs"] [role="tab"]:hover {
        color: #22C55E !important;
        background: rgba(34,197,94,0.04) !important;
      }
      [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
        color: #F8FAFC !important;
        border-bottom: 2px solid #22C55E !important;
        background: transparent !important;
        box-shadow: 0 1px 0 #22C55E, 0 -10px 30px rgba(34,197,94,0.10) inset;
      }

      /* ── KPI metrics — Bloomberg tiles ────────────────────────────── */
      [data-testid="stMetric"] {
        background: linear-gradient(180deg, #0F172A 0%, #0A1124 100%);
        border: 1px solid #1E293B;
        border-radius: 8px;
        padding: 16px 18px;
        box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset;
        transition: all 0.15s ease;
        position: relative;
        overflow: hidden;
      }
      [data-testid="stMetric"]::before {
        content: "";
        position: absolute; top: 0; left: 0; right: 0; height: 1px;
        background: linear-gradient(90deg, transparent, rgba(34,197,94,0.4), transparent);
        opacity: 0;
        transition: opacity 0.2s ease;
      }
      [data-testid="stMetric"]:hover {
        border-color: #334155;
        box-shadow: 0 0 0 1px rgba(34,197,94,0.15), 0 8px 24px rgba(0,0,0,0.4);
        transform: translateY(-1px);
      }
      [data-testid="stMetric"]:hover::before { opacity: 1; }
      [data-testid="stMetricLabel"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.65rem !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #64748B !important;
      }
      [data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 1.9rem !important;
        font-weight: 600 !important;
        color: #F8FAFC !important;
        line-height: 1.1;
        font-variant-numeric: tabular-nums;
        text-shadow: 0 0 24px rgba(34,197,94,0.06);
      }
      [data-testid="stMetricDelta"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.72rem !important;
        font-weight: 500 !important;
        font-variant-numeric: tabular-nums;
        letter-spacing: 0.02em;
      }

      /* ── Popover filter triggers — terminal pills ──────────────────── */
      [data-testid="stPopover"] button {
        font-family: 'IBM Plex Mono', monospace !important;
        font-weight: 500 !important;
        font-size: 0.75rem !important;
        background: #0F172A !important;
        border: 1px solid #1E293B !important;
        border-radius: 6px !important;
        padding: 8px 14px !important;
        color: #CBD5E1 !important;
        transition: all 0.15s ease;
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      [data-testid="stPopover"] button:hover {
        border-color: #22C55E !important;
        background: #131C32 !important;
        color: #22C55E !important;
      }

      /* Popover panel (multiselect) */
      [data-testid="stPopover"] [data-baseweb="popover"] > div {
        background: #0F172A !important;
        border: 1px solid #1E293B !important;
      }

      /* ── Radio (view mode) — segmented terminal ────────────────────── */
      [data-testid="stRadio"] > div {
        gap: 2px;
        background: #0A1124;
        padding: 4px;
        border-radius: 8px;
        display: inline-flex;
        border: 1px solid #1E293B;
      }
      [data-testid="stRadio"] label {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.82rem !important;
        padding: 6px 14px !important;
        border-radius: 6px !important;
        cursor: pointer;
        transition: all 0.15s ease;
        color: #94A3B8 !important;
      }
      [data-testid="stRadio"] label:hover { color: #22C55E !important; }
      [data-testid="stRadio"] label:has(input:checked) {
        background: #1A2440 !important;
        color: #F8FAFC !important;
        box-shadow: 0 0 0 1px rgba(34,197,94,0.20);
      }
      [data-testid="stRadio"] input { display: none !important; }

      /* ── Buttons ──────────────────────────────────────────────────── */
      .stButton button, .stDownloadButton button {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.82rem !important;
        border-radius: 6px !important;
        background: #0F172A !important;
        border: 1px solid #1E293B !important;
        color: #CBD5E1 !important;
        transition: all 0.15s ease;
      }
      .stButton button:hover, .stDownloadButton button:hover {
        border-color: #22C55E !important;
        color: #22C55E !important;
        background: #131C32 !important;
        box-shadow: 0 0 16px rgba(34,197,94,0.12);
      }

      /* ── Dividers ─────────────────────────────────────────────────── */
      hr, [data-testid="stMarkdownContainer"] hr {
        border: none;
        border-top: 1px solid #1E293B;
        margin: 1.75rem 0;
      }

      /* ── Expander ─────────────────────────────────────────────────── */
      [data-testid="stExpander"] {
        border: 1px solid #1E293B !important;
        border-radius: 8px !important;
        background: #0F172A !important;
      }
      [data-testid="stExpander"] summary {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 500 !important;
        color: #CBD5E1 !important;
      }
      [data-testid="stExpander"] summary:hover { color: #22C55E !important; }

      /* ── Dataframes — dark terminal table ──────────────────────────── */
      [data-testid="stDataFrame"] {
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #1E293B;
        background: #0F172A;
      }
      [data-testid="stDataFrame"] * {
        font-family: 'IBM Plex Mono', monospace !important;
        color: #CBD5E1 !important;
        background: transparent !important;
      }

      /* ── Alerts ───────────────────────────────────────────────────── */
      [data-testid="stAlert"] {
        border-radius: 8px !important;
        font-family: 'IBM Plex Sans', sans-serif !important;
        background: #0F172A !important;
        border: 1px solid #1E293B !important;
        color: #CBD5E1 !important;
      }

      /* ── Card hover lift ──────────────────────────────────────────── */
      .editorial-card, .terminal-card {
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
      }
      .terminal-card:hover, .editorial-card:hover {
        transform: translateY(-1px);
        border-color: #334155 !important;
        box-shadow: 0 0 0 1px rgba(34,197,94,0.12), 0 12px 32px rgba(0,0,0,0.45) !important;
      }

      /* ── Hero block — trading-desk briefing ───────────────────────── */
      .hero-wrap {
        background:
          linear-gradient(135deg, rgba(34,197,94,0.06) 0%, transparent 50%),
          linear-gradient(180deg, #0F172A 0%, #0A1124 100%);
        border: 1px solid #1E293B;
        border-radius: 12px;
        padding: 32px 36px;
        margin-bottom: 24px;
        box-shadow: 0 1px 0 rgba(255,255,255,0.03) inset, 0 12px 40px rgba(0,0,0,0.4);
        position: relative;
        overflow: hidden;
      }
      .hero-wrap::before {
        content: "";
        position: absolute; top: 0; left: 0; right: 0; height: 1px;
        background: linear-gradient(90deg, transparent, rgba(34,197,94,0.5), transparent);
      }
      .hero-wrap::after {
        content: "";
        position: absolute; top: 0; right: 0;
        width: 320px; height: 320px;
        background: radial-gradient(circle at top right, rgba(34,197,94,0.10), transparent 60%);
        pointer-events: none;
      }
      .hero-kicker {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.68rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: #22C55E;
        margin-bottom: 14px;
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 4px 10px;
        background: rgba(34,197,94,0.10);
        border: 1px solid rgba(34,197,94,0.25);
        border-radius: 4px;
      }
      .hero-kicker::before {
        content: "";
        width: 6px; height: 6px; border-radius: 50%;
        background: #22C55E;
        box-shadow: 0 0 8px #22C55E;
        animation: pulse 2s ease-in-out infinite;
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }
      .hero-headline {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 2.1rem;
        font-weight: 700;
        line-height: 1.18;
        color: #F8FAFC;
        letter-spacing: -0.02em;
        margin: 12px 0 12px;
        max-width: 920px;
      }
      .hero-deck {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 0.95rem;
        font-weight: 400;
        line-height: 1.55;
        color: #94A3B8;
        margin: 0;
        max-width: 760px;
      }
      .hero-meta {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.72rem;
        color: #64748B;
        margin-top: 18px;
        padding-top: 16px;
        border-top: 1px solid #1E293B;
        display: flex;
        gap: 18px;
        flex-wrap: wrap;
        align-items: center;
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .hero-byline {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: #94A3B8;
      }
      .hero-dot {
        width: 3px; height: 3px; border-radius: 50%;
        background: #334155;
        display: inline-block;
      }

      /* Selectbox + multiselect dark restyle */
      [data-baseweb="select"] > div, [data-baseweb="input"] > div {
        background: #0F172A !important;
        border-color: #1E293B !important;
        color: #CBD5E1 !important;
      }
      [data-baseweb="tag"] {
        background: rgba(34,197,94,0.12) !important;
        border: 1px solid rgba(34,197,94,0.3) !important;
        color: #86EFAC !important;
      }

      /* Mobile */
      @media (max-width: 768px) {
        .hero-wrap { padding: 24px 20px; }
        .hero-headline { font-size: 1.5rem; }
        .hero-deck { font-size: 0.9rem; }
        [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        .block-container { padding-top: 1.5rem !important; }
      }
    </style>
    """
)

# Streamlit Cloud exposes Secrets as st.secrets but doesn't reliably mirror
# them to os.environ — so we do it manually BEFORE importing pipeline.db,
# which reads DATABASE_URL via os.getenv at module load time.
#
# We flatten secrets so both shapes work:
#   flat:        DATABASE_URL = "..."
#   sectioned:   [env]\nDATABASE_URL = "..."
#
# Only touch st.secrets if a secrets file actually exists — otherwise
# Streamlit renders a noisy red "No secrets files found" banner to end users.
WANTED_SECRETS = ("DATABASE_URL", "ANTHROPIC_API_KEY", "FIRECRAWL_API_KEY",
                  "FACEBOOK_ACCESS_TOKEN", "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET")
_secret_paths = [
    Path.home() / ".streamlit" / "secrets.toml",
    Path(__file__).parent.parent / ".streamlit" / "secrets.toml",
]
if any(p.exists() for p in _secret_paths):
    try:
        flat: dict = {}
        for top_key in list(st.secrets.keys()):
            value = st.secrets[top_key]
            if hasattr(value, "keys"):  # a TOML table — flatten it in
                for k, v in value.items():
                    flat[k] = v
            else:
                flat[top_key] = value
        for _key in WANTED_SECRETS:
            if _key in flat:
                os.environ[_key] = str(flat[_key])
    except Exception:
        # Running locally without secrets.toml is fine — .env covers it.
        pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import db  # noqa: E402
from pipeline.config_loader import load_banks as _load_banks_yaml  # noqa: E402
from pipeline.config_loader import load_keywords as _load_keywords_yaml  # noqa: E402
from pipeline.timeutils import days_ago_iso  # noqa: E402

from dashboard.source_taxonomy import classify_source  # noqa: E402
from dashboard.theme import THEME, SENT_COLOR, CAT_COLOR, CATEGORY_CHIP  # noqa: E402
from dashboard.wordcloud_view import render_png as render_wordcloud_png  # noqa: E402

# ── Plotly dark template (Bloomberg/terminal look) ───────────────────────────
# Registered once so every chart inherits the OLED background + Plex Mono
# axis text without needing per-chart `update_layout` calls.
import plotly.io as _pio  # noqa: E402

_DARK = THEME["dark"]
_pio.templates["kbank_dark"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="IBM Plex Sans, sans-serif",
            color=_DARK["text_muted"],
            size=12,
        ),
        title=dict(font=dict(family="IBM Plex Sans", color=_DARK["text"], size=14)),
        xaxis=dict(
            gridcolor=_DARK["divider"],
            zerolinecolor=_DARK["border"],
            linecolor=_DARK["border"],
            tickfont=dict(family="IBM Plex Mono", size=11, color=_DARK["text_subtle"]),
            title=dict(font=dict(family="IBM Plex Sans", color=_DARK["text_muted"], size=12)),
        ),
        yaxis=dict(
            gridcolor=_DARK["divider"],
            zerolinecolor=_DARK["border"],
            linecolor=_DARK["border"],
            tickfont=dict(family="IBM Plex Mono", size=11, color=_DARK["text_subtle"]),
            title=dict(font=dict(family="IBM Plex Sans", color=_DARK["text_muted"], size=12)),
        ),
        legend=dict(font=dict(family="IBM Plex Sans", color=_DARK["text_muted"], size=11)),
        hoverlabel=dict(
            bgcolor=_DARK["surface_alt"],
            bordercolor=_DARK["border_strong"],
            font=dict(family="IBM Plex Mono", color=_DARK["text"], size=12),
        ),
        colorway=[
            _DARK["accent"], _DARK["info"], _DARK["warning"], _DARK["danger"],
            "#A855F7", "#EC4899", "#06B6D4", "#84CC16",
        ],
    )
)
_pio.templates.default = "kbank_dark"

# ── Styling ──────────────────────────────────────────────────────────────────
# SENT_COLOR / CAT_COLOR are imported from dashboard.theme — that module is the
# single source of truth for the KBank-Vietnam visual identity. Adjust palettes
# there, not here.

SENT_ICON   = {"positive": "😊", "neutral": "😐", "negative": "😞"}
INTENT_LABEL = {
    "seeking_info":       "🔍 Seeking Info",
    "sharing_experience": "💬 Experience",
    "complaint":          "⚠️ Complaint",
    "promotion":          "📢 Promotion",
}
PRIORITY_ORDER = ["complaint", "interest_rate", "promotion", "loan_approval",
                  "bank_comparison", "general"]

# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_data(days: int) -> pd.DataFrame:
    try:
        df = db.read_sql_df(
            """SELECT id, source, source_url, title, url,
                      category, sentiment, intent,
                      summary_vi, summary_en, scraped_at
               FROM articles
               WHERE scraped_at >= :cutoff
               ORDER BY scraped_at DESC""",
            params={"cutoff": days_ago_iso(days)},
        )
    except Exception:
        # DB not ready yet (first run) — show empty dashboard.
        return pd.DataFrame()
    if not df.empty:
        # format="ISO8601" accepts any valid ISO 8601 string regardless of
        # whether microseconds are present. Different scrapers in the
        # pipeline produce slightly different shapes — news/forum scrapers
        # call now_iso() which includes microseconds, while the Facebook
        # scrapers build their timestamps from Unix epoch seconds (no
        # microseconds). Without this hint pandas infers the format from
        # row 1 and then errors on the first row with a different shape.
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], format="ISO8601")
    return df


@st.cache_data(ttl=60)
def load_prev_period(days: int) -> pd.DataFrame:
    """Articles from the period IMMEDIATELY BEFORE the current N-day window.

    Example: days=7 → returns articles from 8–14 days ago, used as the
    baseline for period-over-period deltas in the KPI strip.
    """
    try:
        return db.read_sql_df(
            """SELECT id, category, sentiment, intent
               FROM articles
               WHERE scraped_at >= :prev_start AND scraped_at < :prev_end""",
            params={
                "prev_start": days_ago_iso(days * 2),
                "prev_end":   days_ago_iso(days),
            },
        )
    except Exception:
        return pd.DataFrame()


def pct_delta(curr: int, prev: int) -> str | None:
    """Format a period-over-period delta like '+23%' or '-12%'.

    Returns None when prev is 0 (Streamlit hides the delta in that case —
    cleaner than showing 'NaN' or 'inf'). Also returns None when both are 0.
    """
    if prev == 0:
        return None
    delta = ((curr - prev) / prev) * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.0f}%"


@st.cache_data(ttl=3600)
def load_home_loan_cfg() -> dict:
    return _load_keywords_yaml().get("home_loan", {})


@st.cache_data(ttl=60)
def get_last_scrape_iso() -> str | None:
    """ISO timestamp of the most recent scrape heartbeat, or None if never run."""
    try:
        df = db.read_sql_df(
            "SELECT MAX(created_at) AS last FROM usage_log WHERE service = 'scrape_run'"
        )
        if df.empty or df.iloc[0]["last"] is None:
            return None
        return str(df.iloc[0]["last"])
    except Exception:
        return None


def _scrape_health_badge() -> str:
    """HTML badge showing how stale the latest scrape is.

    Uses the functional success/warning/danger tokens from theme.py so the
    badge re-skins automatically if the brand palette ever changes again.
    """
    from datetime import datetime
    from pipeline.timeutils import LOCAL_TZ

    last_iso = get_last_scrape_iso()
    if not last_iso:
        return (f'<span style="background:{THEME["warning_bg"]};color:{THEME["warning_fg"]};'
                f'padding:4px 10px;border-radius:14px;font-size:13px;font-weight:600">'
                f'⏳ No scrape recorded yet — first scheduled run at 7 AM Vietnam time</span>')

    try:
        last_dt = datetime.fromisoformat(last_iso.replace("Z", ""))
    except ValueError:
        return ""

    now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    hours = (now - last_dt).total_seconds() / 3600

    if hours < 25:  # daily cron + a little wiggle room
        bg, fg, icon, label = THEME["success_bg"], THEME["success_fg"], "🟢", f"{int(max(hours, 0))}h ago"
    elif hours < 49:
        bg, fg, icon, label = THEME["warning_bg"], THEME["warning_fg"], "🟡", f"{int(hours)}h ago — may be stale"
    else:
        bg, fg, icon, label = THEME["danger_bg"], THEME["danger_fg"], "🔴", f"{int(hours/24)}d ago — automation may be broken"

    return (f'<span style="background:{bg};color:{fg};padding:4px 10px;'
            f'border-radius:14px;font-size:13px;font-weight:600">'
            f'{icon} Last daily scrape: {label}</span>')


@st.cache_data(ttl=300, show_spinner=False)
def _wordcloud_bytes(texts_tuple: tuple) -> bytes | None:
    """Cached wordcloud render. texts_tuple is hashable (tuple of strings)."""
    return render_wordcloud_png(list(texts_tuple), load_home_loan_cfg())


@st.cache_data(ttl=3600)
def load_banks() -> dict:
    """Returns {short_name: {type, name_en, aliases, ...}} from banks.yaml."""
    cfg = _load_banks_yaml()
    banks = {}
    for category in ("state_owned", "private", "foreign"):
        for b in cfg.get(category, []):
            banks[b["short_name"]] = {
                "type":     category,
                "name_en":  b.get("name_en", b["short_name"]),
                "aliases":  b.get("aliases", [b["short_name"]]),
                "promo_rate":   b.get("promo_rate", ""),
                "max_term_yrs": b.get("max_term_yrs", ""),
                "notes":    b.get("notes", ""),
            }
    return banks


import re as _re

def detect_banks(text: str, banks: dict) -> list[str]:
    """Return short_names of banks mentioned in text (whole-word match only)."""
    t = (text or "").lower()
    found = []
    for short_name, info in banks.items():
        for alias in info["aliases"]:
            pattern = r"(?<![a-z])" + _re.escape(alias.lower()) + r"(?![a-z])"
            if _re.search(pattern, t):
                found.append(short_name)
                break
    return found


# ── Sidebar — single source of truth for ALL filters ────────────────────────
# Date range + Source + Sentiment + Category live here together so the user
# only ever looks in one place to change what they're seeing. The horizontal
# filter bar that used to sit under the hero is gone.

with st.sidebar:
    st.markdown("## Home Loan Intel")
    st.caption("Social signal · KBank Vietnam")
    st.divider()

    # ── Date range ─────────────────────────────────────────────
    st.markdown("**Date range**")
    _preset_labels = ["Today", "7d", "14d", "30d", "Custom"]
    _preset_days   = {"Today": 1, "7d": 7, "14d": 14, "30d": 30}
    if "date_preset" not in st.session_state:
        st.session_state["date_preset"] = "7d"
    preset = st.radio(
        "Date preset", _preset_labels,
        index=_preset_labels.index(st.session_state["date_preset"]),
        horizontal=True, label_visibility="collapsed",
    )
    st.session_state["date_preset"] = preset
    if preset == "Custom":
        days = st.slider("Days", 1, 30, 7, label_visibility="collapsed")
    else:
        days = _preset_days[preset]

# Load data here so the rest of the sidebar (which needs source list) can
# render with knowledge of what's actually in the data set.
df_all = load_data(days)
banks  = load_banks()

SENTIMENT_OPTS = ["positive", "neutral", "negative"]
sources = sorted(df_all["source"].dropna().unique().tolist()) if not df_all.empty else []

# Persist filter selections across reruns
if "sel_src"  not in st.session_state: st.session_state["sel_src"]  = sources
if "sel_sent" not in st.session_state: st.session_state["sel_sent"] = SENTIMENT_OPTS[:]
if "sel_cat"  not in st.session_state: st.session_state["sel_cat"]  = PRIORITY_ORDER[:]
# Reconcile sources if the underlying list changed (e.g. new source added)
st.session_state["sel_src"] = [s for s in st.session_state["sel_src"] if s in sources] or sources

with st.sidebar:
    st.divider()
    st.markdown("**Filters**")
    st.session_state["sel_src"] = st.multiselect(
        "Source", sources, default=st.session_state["sel_src"],
    )
    st.session_state["sel_sent"] = st.multiselect(
        "Sentiment", SENTIMENT_OPTS, default=st.session_state["sel_sent"],
    )
    st.session_state["sel_cat"] = st.multiselect(
        "Category", PRIORITY_ORDER, default=st.session_state["sel_cat"],
    )

    # Reset filters button — quick escape hatch when too narrow
    _n_active = (
        (0 if len(st.session_state["sel_src"])  == len(sources)         else 1) +
        (0 if len(st.session_state["sel_sent"]) == len(SENTIMENT_OPTS)  else 1) +
        (0 if len(st.session_state["sel_cat"])  == len(PRIORITY_ORDER)  else 1)
    )
    if _n_active and st.button(f"Reset {_n_active} filter(s)", use_container_width=True):
        st.session_state["sel_src"]  = sources
        st.session_state["sel_sent"] = SENTIMENT_OPTS[:]
        st.session_state["sel_cat"]  = PRIORITY_ORDER[:]
        st.rerun()

    st.divider()
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

sel_src  = st.session_state["sel_src"]
sel_sent = st.session_state["sel_sent"]
sel_cat  = st.session_state["sel_cat"]

# ── Hero "Story of the Day" ──────────────────────────────────────────────────
# Auto-generates an editorial headline from the actual data so the dashboard
# opens like a daily briefing rather than a control panel.
def _hero_headline(df: pd.DataFrame, df_prev: pd.DataFrame, days: int) -> tuple[str, str]:
    """Return (headline, deck) — picks the most newsworthy angle from this period."""
    if df.empty:
        return ("No signal yet — the queue is quiet.",
                "Widen the date range or wait for the next daily scrape to surface fresh chatter.")

    total = len(df)
    neg   = int((df["sentiment"] == "negative").sum())
    pos   = int((df["sentiment"] == "positive").sum())
    comp  = int((df["category"] == "complaint").sum())
    promo = int((df["category"] == "promotion").sum())
    seek  = int((df["intent"] == "seeking_info").sum())

    neg_pct = (neg / total * 100) if total else 0
    pos_pct = (pos / total * 100) if total else 0

    prev_total = len(df_prev)
    delta_pct  = ((total - prev_total) / prev_total * 100) if prev_total else 0

    # Most-mentioned competitor this period (excluding KBank itself)
    top_bank = ""
    if "banks_mentioned" in df.columns:
        from collections import Counter
        bc = Counter()
        for lst in df["banks_mentioned"].dropna():
            for b in lst:
                if b.lower() != "kbank":
                    bc[b] += 1
        if bc:
            top_bank = bc.most_common(1)[0][0]

    # Pick the strongest angle
    if neg_pct >= 35 and comp >= 3:
        h = f"Complaint volume climbs — {comp} pain-point signals this {days}-day window."
        d = (f"Negative sentiment sits at {neg_pct:.0f}% of the conversation. Customer Voice tab "
             f"surfaces the specific threads buyers are flagging.")
    elif promo >= 4 and top_bank:
        h = f"{top_bank} leads a fresh competitor push — {promo} promotional moves on the radar."
        d = (f"Rate war activity is up. Competitor Intel tab breaks down who's offering what, "
             f"with sentiment by bank.")
    elif delta_pct >= 25 and prev_total:
        h = f"Conversation volume up {delta_pct:.0f}% — the home-loan story is heating up."
        d = (f"{total} articles tracked in the last {days} days vs {prev_total} prior. "
             f"Pos {pos_pct:.0f}% / Neg {neg_pct:.0f}%.")
    elif delta_pct <= -25 and prev_total:
        h = f"Conversation cooling — volume down {abs(delta_pct):.0f}% vs the prior {days} days."
        d = (f"{total} articles in window. Quieter weeks are a chance to look at what stuck — "
             f"check the Insights tab for the slower-burn signal.")
    elif seek >= 5:
        h = f"{seek} potential buyers are asking — the funnel is talking."
        d = (f"Seeking-info intent dominates the queue. Customer Voice tab has the exact "
             f"questions; Action Queue surfaces the urgent ones first.")
    elif top_bank:
        h = f"{top_bank} dominates this week's mortgage chatter."
        d = (f"{total} articles tracked. Sentiment splits Pos {pos_pct:.0f}% / Neg {neg_pct:.0f}%. "
             f"Competitor Intel tab has the per-bank breakdown.")
    else:
        h = f"{total} mortgage signals tracked across forums, Facebook, and the press."
        d = (f"Pos {pos_pct:.0f}% / Neg {neg_pct:.0f}%. The Action Queue has the items that "
             f"need attention first.")
    return h, d

# ── Apply filters (moved up so hero/KPIs see the SAME filtered data) ─────────

df = df_all.copy()
if not df.empty:
    if sel_src:  df = df[df["source"].isin(sel_src)]
    if sel_sent: df = df[df["sentiment"].isin(sel_sent)]
    if sel_cat:  df = df[df["category"].isin(sel_cat)]

    # Detect bank mentions
    combined = df["title"].fillna("") + " " + df["summary_en"].fillna("") + " " + df["summary_vi"].fillna("")
    df["banks_mentioned"] = combined.apply(lambda t: detect_banks(t, banks))

    # Real-estate developer mentions — Competitor Watch wants these too.
    # banks.yaml only contains banks, but Vinhomes / Masterise / Novaland
    # offer their own home-financing programs and absolutely count as
    # competitive intel for KBank's mortgage product.
    _RE_DEVELOPERS = {
        "Vinhomes":  ["vinhomes"],
        "Masterise": ["masterise"],
        "Novaland":  ["novaland"],
    }
    def _detect_realestate(text: str) -> list:
        t = (text or "").lower()
        return [name for name, aliases in _RE_DEVELOPERS.items()
                if any(alias in t for alias in aliases)]
    df["realestate_mentioned"] = combined.apply(_detect_realestate)

    # Boolean — used as Competitor Watch's gate. True if the article
    # mentions any bank OR any real-estate developer we track. We keep
    # banks_mentioned and realestate_mentioned separate so the Competitor
    # Intel tab's charts (which are bank-specific) aren't polluted.
    df["mentions_competitor"] = (
        df["banks_mentioned"].apply(bool) | df["realestate_mentioned"].apply(bool)
    )

    # Source-type bucket (facebook / forum / news) — drives the Customer
    # Voice and Competitor Watch view modes in the Action Feed.
    df["source_type"] = df["source"].apply(classify_source)

# ── Hero "Story of the Day" ──────────────────────────────────────────────────
# Now reads from the SAME filtered df as the KPIs below, so the headline can
# never lie about what the user is looking at.
_df_prev_for_hero = load_prev_period(days)
_headline, _deck = _hero_headline(df, _df_prev_for_hero, days)

from datetime import datetime as _dt
_today_str = _dt.now().strftime("%a · %d %b %Y")

# Source mix surfaces in the hero meta now (replaces the orphan caption that
# used to live between hero and KPIs).
_src_mix = df["source_type"].value_counts().to_dict() if not df.empty else {}
_src_mix_str = " · ".join(
    f"{_src_mix.get(t, 0)} {t}" for t in ("forum", "facebook", "news") if _src_mix.get(t, 0)
)

# Active filter chip in hero meta — so user sees at a glance that they're
# looking at a filtered view (and the hero stats reflect that filter).
_filter_chip = ""
_active_filter_count = (
    (0 if len(sel_src)  == len(sources)         else 1) +
    (0 if len(sel_sent) == len(SENTIMENT_OPTS)  else 1) +
    (0 if len(sel_cat)  == len(PRIORITY_ORDER)  else 1)
)
if _active_filter_count:
    _filter_chip = (
        f'<span class="hero-dot"></span>'
        f'<span style="color:#22C55E;font-weight:500">'
        f'{_active_filter_count} filter(s) active</span>'
    )

st.html(
    f"""
    <div class="hero-wrap">
      <div class="hero-kicker">Today's Briefing · Home Loan Vietnam</div>
      <h1 class="hero-headline">{_headline}</h1>
      <p class="hero-deck">{_deck}</p>
      <div class="hero-meta">
        <span class="hero-byline">{_today_str}</span>
        <span class="hero-dot"></span>
        <span>Window: last {days}d</span>
        <span class="hero-dot"></span>
        <span>{len(df)} articles ({_src_mix_str or "none"})</span>
        {_filter_chip}
        <span class="hero-dot"></span>
        {_scrape_health_badge()}
      </div>
    </div>
    """
)

if df.empty:
    st.info("No articles match the current filters. Try clearing filters in the sidebar or widening the date range.")
    st.stop()

# KPI strip — counts for the current window + period-over-period deltas
total      = len(df)
complaints = int((df["category"] == "complaint").sum())
promos     = int((df["category"] == "promotion").sum())
seekers    = int((df["intent"] == "seeking_info").sum())
neg        = int((df["sentiment"] == "negative").sum())

# Same KPIs over the previous N-day window so we can show "+12% vs last period"
df_prev = load_prev_period(days)
if df_prev.empty:
    total_p = complaints_p = promos_p = seekers_p = neg_p = 0
else:
    total_p      = len(df_prev)
    complaints_p = int((df_prev["category"] == "complaint").sum())
    promos_p     = int((df_prev["category"] == "promotion").sum())
    seekers_p    = int((df_prev["intent"] == "seeking_info").sum())
    neg_p        = int((df_prev["sentiment"] == "negative").sum())

# delta_color="inverse" flips the green/red so that "more complaints" shows
# red (bad) and "fewer complaints" shows green (good). Same for negative
# sentiment and competitor promos.
# Labels stripped of emojis — they don't match Plex Mono and trip the
# `no-emoji-icons` accessibility rule. Section meaning lives in the
# uppercase Plex Mono label color and position instead.
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Articles",        total,      delta=pct_delta(total, total_p),
          help=f"Compared to previous {days} days")
k2.metric("Complaints",            complaints, delta=pct_delta(complaints, complaints_p),
          delta_color="inverse", help="Pain points + dissatisfaction signals")
k3.metric("Competitor Promos",     promos,     delta=pct_delta(promos, promos_p),
          delta_color="inverse", help="Promotional pushes from rival banks")
k4.metric("Potential Customers",   seekers,    delta=pct_delta(seekers, seekers_p),
          help="Articles where intent = seeking_info")
k5.metric("Negative Sentiment",    neg,        delta=pct_delta(neg, neg_p),
          delta_color="inverse", help="Negative-toned mentions across all sources")

# Export current filtered articles as CSV
_csv_cols = ["scraped_at", "source", "category", "sentiment", "intent",
             "title", "summary_vi", "summary_en", "url"]
_csv_df = df[[c for c in _csv_cols if c in df.columns]]
_csv_bytes = _csv_df.to_csv(index=False).encode("utf-8-sig")  # BOM so Excel reads UTF-8

dl_left, dl_spacer = st.columns([1, 5])
with dl_left:
    st.download_button(
        f"⬇️ Export {len(df)} articles (CSV)",
        data=_csv_bytes,
        file_name=f"home_loan_articles_{days}d.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
# Order matches user mental model: summary → drill-in → comparison → narrative.
# Cost is an admin/ops view, hidden unless ?admin=1 is in the URL.
_qp = st.query_params
_admin_mode = _qp.get("admin", "0") == "1"

_tab_labels = ["Daily Brief", "Analytics", "Competitors", "AI Insights"]
if _admin_mode:
    _tab_labels.append("Cost")

_tabs = st.tabs(_tab_labels)
# Tab order reflects user journey: actionable first → broad analytics →
# competitor lens → AI summary. Daily Brief surfaces what needs attention now;
# Analytics is the slower-burn dashboard.
tab_action_feed  = _tabs[0]   # "Daily Brief"
tab_overview     = _tabs[1]   # "Analytics"
tab_competitor   = _tabs[2]   # "Competitors"
tab_insights     = _tabs[3]   # "AI Insights"
tab_cost         = _tabs[4] if _admin_mode else None

# ═══════════════════════════════════════════════════════════
# TAB 1 — ACTION FEED  (priority-sorted articles)
# ═══════════════════════════════════════════════════════════

with tab_action_feed:
    # ── Section visual config (used by both view modes) ─────────────────────
    # Headings stay verbatim (emojis preserved); colors come from THEME["category"]
    # so a future palette change updates everything in one place.
    _SECTION_HEADINGS = {
        "complaint":       "🚨 Complaints & Pain Points",
        "interest_rate":   "💰 Rate Intelligence",
        "promotion":       "📢 Competitor Promotions",
        "loan_approval":   "📑 Loan Approval Topics",
        "bank_comparison": "🏦 Bank Comparisons",
        "general":         "📰 General News",
    }
    sections = {
        cat: (_SECTION_HEADINGS[cat], THEME["category"][cat]["bg"], THEME["category"][cat]["accent"])
        for cat in _SECTION_HEADINGS
    }
    cat_rank = {c: i for i, c in enumerate(PRIORITY_ORDER)}

    def _badge(text, bg, fg="white"):
        return (f'<span style="background:{bg};color:{fg};padding:2px 10px;'
                f'border-radius:20px;font-size:12px;font-weight:600;white-space:nowrap">{text}</span>')

    # Per-sentiment card tint overrides the section default so negative items
    # stand out even when grouped under a "neutral" category like General News.
    # Mapped onto the functional danger/success tokens for brand alignment.
    SENT_BG = {
        "negative": (THEME["danger_bg"],  THEME["danger_fg"]),
        "positive": (THEME["success_bg"], THEME["success_fg"]),
        "neutral":  (None,                None),
    }

    # Session-scoped dismissal: marking an item "Done" hides it for this
    # browser session only. Keeps the queue actionable without needing a DB.
    if "dismissed_ids" not in st.session_state:
        st.session_state["dismissed_ids"] = set()

    def _priority_reasons(row) -> list[str]:
        """Human-readable reasons this item is in the action queue."""
        reasons = []
        if row.get("category") == "complaint":
            reasons.append("🚨 Complaint")
        if row.get("sentiment") == "negative":
            reasons.append("🔻 Negative")
        if row.get("category") == "promotion":
            reasons.append("📢 Competitor move")
        if row.get("category") == "interest_rate":
            reasons.append("💰 Rate signal")
        if row.get("intent") == "seeking_info":
            reasons.append("🔍 Potential customer")
        return reasons

    def _priority_score(row) -> float:
        """Lower = more urgent. Combines category rank, sentiment, and recency."""
        score = cat_rank.get(row.get("category"), 99) * 100
        if row.get("sentiment") == "negative":
            score -= 250  # negative trumps category — promote a "negative general" above a "neutral promotion"
        elif row.get("sentiment") == "positive":
            score += 50
        if row.get("intent") == "seeking_info":
            score -= 30
        # Recency: subtract hours-since to favor newer items
        ts = row.get("scraped_at")
        if pd.notna(ts):
            from datetime import datetime
            hrs = max(0, (datetime.now() - ts.to_pydatetime().replace(tzinfo=None)).total_seconds() / 3600)
            score += min(hrs, 168) * 0.1  # cap at 1 week so very old items don't drown out
        return score

    def _render_card(row, *, section_bg: str, section_accent: str, show_priority_reasons: bool = False):
        """Render one article card — Bloomberg/terminal-style dark surface.

        Layout: mono category tag + sentiment dot + monospace date, bold sans
        title, bilingual summary, thin meta footer. Negative items glow red.
        """
        sent    = row.get("sentiment") or "neutral"
        src     = row.get("source") or ""
        title   = row.get("title")  or "(no title)"
        url     = row.get("url")    or ""
        en      = row.get("summary_en") or ""
        vi      = row.get("summary_vi") or ""
        intent  = INTENT_LABEL.get(row.get("intent") or "", "")
        date    = row["scraped_at"].strftime("%d %b · %H:%M") if pd.notna(row["scraped_at"]) else ""
        b_names = row.get("banks_mentioned") or []
        cat     = row.get("category") or "general"

        # Sentiment colors mapped to dark-palette accents
        sent_color_dark = {
            "positive": "#22C55E",
            "neutral":  "#64748B",
            "negative": "#EF4444",
        }.get(sent, "#64748B")

        chip = CATEGORY_CHIP.get(cat, CATEGORY_CHIP["general"])
        cat_label = cat.replace("_", " ").upper()
        cat_chip = (
            f'<span style="background:{chip["bg"]};color:{chip["fg"]};'
            f'padding:3px 9px;border-radius:4px;font-size:0.68rem;font-weight:500;'
            f'letter-spacing:0.10em;font-family:\'IBM Plex Mono\',monospace">{cat_label}</span>'
        )

        sent_dot = (
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'color:{sent_color_dark};font-size:0.68rem;font-weight:500;'
            f'font-family:\'IBM Plex Mono\',monospace;text-transform:uppercase;letter-spacing:0.10em">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{sent_color_dark};'
            f'box-shadow:0 0 8px {sent_color_dark};display:inline-block"></span>{sent}</span>'
        )

        bank_badges = "".join(
            f'<span style="background:rgba(59,130,246,0.12);color:#93C5FD;'
            f'padding:2px 8px;border-radius:4px;font-size:0.68rem;margin-right:4px;'
            f'font-weight:500;font-family:\'IBM Plex Mono\',monospace;'
            f'letter-spacing:0.04em">{b}</span>'
            for b in b_names
        )
        reason_badges = ""
        if show_priority_reasons:
            reasons = _priority_reasons(row)
            reason_badges = "".join(
                f'<span style="background:rgba(245,158,11,0.12);color:#FCD34D;'
                f'padding:2px 8px;border-radius:4px;font-size:0.68rem;margin-right:4px;'
                f'font-weight:500;font-family:\'IBM Plex Mono\',monospace;'
                f'letter-spacing:0.04em">{r}</span>'
                for r in reasons
            )

        # Title — Plex Sans, tight, bright on dark
        title_html = (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#F8FAFC;font-family:\'IBM Plex Sans\',sans-serif;'
            f'font-weight:600;font-size:1.02rem;line-height:1.35;text-decoration:none;'
            f'display:block;margin:12px 0 8px;letter-spacing:-0.01em">{title}</a>'
            if url else
            f'<span style="color:#F8FAFC;font-family:\'IBM Plex Sans\',sans-serif;'
            f'font-weight:600;font-size:1.02rem;line-height:1.35;display:block;'
            f'margin:12px 0 8px;letter-spacing:-0.01em">{title}</span>'
        )

        src_type = classify_source(src)
        src_icon = {"facebook": "FB", "forum": "FRM", "news": "NEWS"}.get(src_type, "SRC")
        src_html = (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#64748B;font-size:0.7rem;text-decoration:none;'
            f'font-weight:500;font-family:\'IBM Plex Mono\',monospace;'
            f'letter-spacing:0.06em">[{src_icon}] {src}</a>'
            if url else
            f'<span style="color:#64748B;font-size:0.7rem;'
            f'font-family:\'IBM Plex Mono\',monospace;letter-spacing:0.06em">[{src_icon}] {src}</span>'
        )

        # Top accent strip — negative glows red, positive glows green
        accent_strip = ""
        if sent == "negative":
            accent_strip = (
                'border-top:1px solid #EF4444;'
                'box-shadow:0 -1px 12px rgba(239,68,68,0.18), 0 1px 0 rgba(255,255,255,0.02) inset;'
            )
        elif sent == "positive":
            accent_strip = (
                'border-top:1px solid #22C55E;'
                'box-shadow:0 -1px 12px rgba(34,197,94,0.15), 0 1px 0 rgba(255,255,255,0.02) inset;'
            )
        else:
            accent_strip = 'box-shadow:0 1px 0 rgba(255,255,255,0.02) inset;'

        card = (
            f'<div class="terminal-card" style="background:linear-gradient(180deg,#0F172A 0%,#0A1124 100%);'
            f'border:1px solid #1E293B;{accent_strip}'
            f'border-radius:8px;padding:18px 20px;margin-bottom:10px">'
            # Top meta row
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;flex-wrap:wrap;gap:8px">'
            f'<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
            f'{cat_chip}{sent_dot}'
            f'</div>'
            f'<span style="color:#475569;font-size:0.68rem;'
            f'font-family:\'IBM Plex Mono\',monospace;letter-spacing:0.08em">{date}</span>'
            f'</div>'
            # Headline
            f'{title_html}'
            # Bilingual summary
            f'<p style="margin:6px 0 4px;color:#CBD5E1;font-size:0.86rem;line-height:1.55;'
            f'font-family:\'IBM Plex Sans\',sans-serif">EN · {en or "—"}</p>'
            f'<p style="margin:0 0 14px;color:#94A3B8;font-size:0.82rem;'
            f'line-height:1.5;font-family:\'IBM Plex Sans\',sans-serif">VI · {vi or "—"}</p>'
            # Footer meta row
            f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;'
            f'padding-top:10px;border-top:1px solid #1A2236">'
            f'{src_html}'
            f'<span style="color:#334155">·</span>'
            f'{bank_badges}{reason_badges}'
            f'<span style="margin-left:auto;color:#475569;font-size:0.65rem;'
            f'font-family:\'IBM Plex Mono\',monospace;font-weight:500;text-transform:uppercase;'
            f'letter-spacing:0.10em">{intent}</span>'
            f'</div>'
            f'</div>'
        )
        # IMPORTANT: must be st.markdown(unsafe_allow_html=True), NOT st.html().
        # st.html()'s sanitiser strips the target="_blank" attribute from anchors,
        # so source-chip and title clicks would navigate the current tab instead
        # of opening a new tab. st.markdown preserves target.
        st.markdown(card, unsafe_allow_html=True)

    # ── View-mode toggle ────────────────────────────────────────────────────
    # Three audience-specific cuts of the same priority queue. "Browse All"
    # (the legacy category-grouped view) was retired — it duplicated what the
    # Analytics tab's "Category breakdown" already shows, and added a 4th
    # mental model where 3 were already enough.
    VIEW_MODES = ["Action Queue", "Customer Voice", "Competitor Watch"]
    view_mode = st.radio(
        "View mode", VIEW_MODES,
        horizontal=True, label_visibility="collapsed",
        key="action_view_mode",
    )

    # Pre-filter the dataframe by audience cut. Same priority-ranking + Done
    # button flow reused across all three so the UX stays consistent.
    if view_mode == "Customer Voice":
        df_view = df[df["source_type"] == "forum"]
        view_subtitle = "Forum threads — what buyers are actually saying. Newer + negative items surface first."
        empty_message = "No forum chatter in this window. Try widening the date range."
    elif view_mode == "Competitor Watch":
        # Competitor intel = anything that names a competitor — bank or
        # real-estate developer — anywhere in title/summary. FB posts
        # (always competitor marketing) are unconditionally included on
        # top so the view doesn't go silent on quiet news days.
        df_view = df[
            (df["source_type"] == "facebook")
            | df["mentions_competitor"]
        ]
        view_subtitle = "Anything naming a competitor bank or developer — FB marketing, forum comparisons, press coverage."
        empty_message = "No competitor mentions in this window. Try widening the date range."
    else:
        df_view = df
        view_subtitle = "Sorted by urgency — complaints and negatives surface first. Dismiss handled items to clear them."
        empty_message = "Queue empty — nothing else flagged for review in this window."

    # ── Priority-sorted list with Done buttons ──────────────────────────────
    df_q = df_view.copy()
    if df_q.empty:
        st.info(empty_message)
    else:
        df_q["_score"] = df_q.apply(_priority_score, axis=1)
        df_q = df_q[~df_q["id"].isin(st.session_state["dismissed_ids"])]
        df_q = df_q.sort_values("_score").head(20)

        dismissed_n = len(st.session_state["dismissed_ids"])
        header_l, header_r = st.columns([4, 2])
        with header_l:
            st.markdown(f"### {len(df_q)} items need a look")
            st.caption(view_subtitle)
        with header_r:
            if dismissed_n:
                if st.button(f"Restore {dismissed_n} dismissed", use_container_width=True):
                    st.session_state["dismissed_ids"] = set()
                    st.rerun()

        if df_q.empty:
            st.success("You've cleared every item in this view.")
        else:
            for _, row in df_q.iterrows():
                cat = row.get("category") or "general"
                section_bg     = sections.get(cat, sections["general"])[1]
                section_accent = sections.get(cat, sections["general"])[2]
                _render_card(row, section_bg=section_bg, section_accent=section_accent,
                             show_priority_reasons=True)
                # Dismiss button under each card
                b_left, _b_sp = st.columns([1, 7])
                with b_left:
                    if st.button("Done", key=f"done_{row['id']}", use_container_width=True):
                        st.session_state["dismissed_ids"].add(row["id"])
                        st.rerun()


# ═══════════════════════════════════════════════════════════
# TAB 2 — COMPETITOR INTEL
# ═══════════════════════════════════════════════════════════

with tab_competitor:
    # ── Bank reference table ──────────────────────────────────────────────
    # Note: we used to show a "Promo Rate" / "Max Term" column here, but
    # banks publish multiple rate tiers (fixed 1/2/3/5 yr + floating) that
    # change monthly. Storing one number per bank is misleading. If/when
    # we want live rate intel, the right approach is parsing % values out
    # of the scraped article titles per bank, not hard-coding in banks.yaml.
    with st.expander("📚 Bank Reference — Home Loan Products in Vietnam", expanded=False):
        ref_rows = []
        TYPE_LABEL = {"state_owned": "🏛️ State", "private": "🏢 Private", "foreign": "🌏 Foreign"}
        for short_name, info in banks.items():
            ref_rows.append({
                "Bank":  short_name,
                "Type":  TYPE_LABEL.get(info["type"], info["type"]),
                "Notes": (info.get("notes") or "").strip()[:160],
            })
        st.dataframe(pd.DataFrame(ref_rows).set_index("Bank"),
                     use_container_width=True, height=420)

    st.divider()

    # Explode bank mentions into a flat table
    rows_banks = []
    for _, row in df.iterrows():
        for b in (row.get("banks_mentioned") or []):
            binfo = banks.get(b, {})
            rows_banks.append({
                "bank":       b,
                "bank_type":  binfo.get("type", "unknown"),
                "sentiment":  row["sentiment"],
                "category":   row["category"],
                "title":      row["title"],
                "url":        row["url"],
                "date":       row["scraped_at"],
                "summary_en": row.get("summary_en", ""),
            })

    if not rows_banks:
        # Empty state — instead of a flat "no data" line, surface what we DO
        # know (top topics + sentiment mix) and concrete next steps the user
        # can take. This keeps the tab useful even on quiet days.
        st.html(
            f"""
            <div style="background:{THEME["bg_alt"]};border:1px dashed {THEME["hero"]["border"]};
                        border-radius:14px;padding:24px 28px;text-align:center;margin:8px 0 20px">
              <div style="font-size:36px;line-height:1">🔍</div>
              <h3 style="margin:6px 0 4px;color:{THEME["text"]}">No banks mentioned by name</h3>
              <p style="color:{THEME["text_muted"]};margin:0 0 12px;font-size:14px">
                In the current date range, the scraped articles didn't reference
                any of the banks tracked in <code>config/banks.yaml</code>.
                That can mean a quiet week — or that competitors are being
                discussed by product names instead of brand names.
              </p>
            </div>
            """
        )

        st.markdown("**Try one of these instead:**")
        es_c1, es_c2, es_c3 = st.columns(3)
        with es_c1:
            st.markdown(
                "**📅 Widen the window**  \n"
                "Switch the date range in the sidebar to **14d** or **30d** — bank mentions "
                "are bursty around rate announcements and promo seasons."
            )
        with es_c2:
            st.markdown(
                "**🏷️ Check by category**  \n"
                "Use the **Category** filter to keep only *promotion* or *bank_comparison* "
                "articles. If banks are mentioned anywhere, they'll show up there first."
            )
        with es_c3:
            st.markdown(
                "**📚 Browse what's there**  \n"
                "Head to the **Overview** tab to see the top phrases word cloud — "
                "it surfaces whichever bank names *are* being mentioned, even if not in `banks.yaml`."
            )

        # Show top topics in current data as a fallback signal
        if not df.empty:
            st.divider()
            st.markdown("**What people *are* talking about (current filter)**")
            topic_df = df["category"].value_counts().head(5).reset_index()
            topic_df.columns = ["Category", "Articles"]
            st.dataframe(topic_df, use_container_width=True, hide_index=True)
    else:
        bdf = pd.DataFrame(rows_banks)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Mention Volume by Bank")
            vol = bdf["bank"].value_counts().reset_index()
            vol.columns = ["Bank", "Mentions"]
            # Colour by type
            # Three bank types — distinguishable colors that survive being seen
            # next to each other in the legend. info=blue is brand-friendly,
            # primary_light=mid-green stays on-brand, warning=amber is the
            # third leg of the contrast triangle.
            type_color = {
                "state_owned": THEME["info"],
                "private":     THEME["primary_light"],
                "foreign":     THEME["warning"],
            }
            vol["type"] = vol["Bank"].map(lambda b: banks.get(b, {}).get("type", "private"))
            vol["color"] = vol["type"].map(type_color)
            fig = px.bar(vol, x="Mentions", y="Bank", orientation="h",
                         color="type",
                         color_discrete_map=type_color,
                         height=max(300, len(vol) * 35),
                         labels={"type": "Bank type"})
            fig.update_layout(margin=dict(t=10, b=0, l=0, r=0),
                              yaxis_title=None, xaxis_title=None,
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Sentiment by Bank")
            sent_bank = (
                bdf.groupby(["bank", "sentiment"])
                .size().unstack(fill_value=0)
                .reindex(columns=["positive", "neutral", "negative"], fill_value=0)
                .reset_index()
            )
            fig2 = px.bar(
                sent_bank.melt(id_vars="bank", var_name="sentiment", value_name="count"),
                x="count", y="bank", color="sentiment",
                color_discrete_map=SENT_COLOR,
                orientation="h", barmode="stack",
                height=max(300, len(sent_bank) * 35),
            )
            fig2.update_layout(margin=dict(t=10, b=0, l=0, r=0),
                               yaxis_title=None, xaxis_title=None,
                               legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig2, use_container_width=True)

        # Category breakdown per bank
        st.subheader("What Are People Saying About Each Bank?")
        cat_bank = (
            bdf.groupby(["bank", "category"])
            .size().unstack(fill_value=0)
            .reset_index()
        )
        for col in PRIORITY_ORDER:
            if col not in cat_bank.columns:
                cat_bank[col] = 0
        cat_bank = cat_bank[["bank"] + PRIORITY_ORDER]
        st.dataframe(cat_bank.set_index("bank"), use_container_width=True)

        # Articles by bank
        st.subheader("Articles by Bank")
        sel_bank = st.selectbox("Select bank", sorted(bdf["bank"].unique()))
        bank_articles = bdf[bdf["bank"] == sel_bank].sort_values("date", ascending=False)
        for _, r in bank_articles.iterrows():
            sent_bg = SENT_COLOR.get(r["sentiment"], THEME["text_subtle"])
            date_str = r["date"].strftime("%d %b") if pd.notna(r["date"]) else ""
            title_html = (
                f'<a href="{r["url"]}" target="_blank" rel="noopener noreferrer" '
                f'style="color:{THEME["text"]};font-weight:600;font-size:14px;text-decoration:none">{r["title"]}</a>'
                if r["url"] else f'<span style="font-weight:600">{r["title"]}</span>'
            )
            card2 = (
                f'<div style="border:1px solid {THEME["card_border"]};border-radius:8px;'
                f'padding:12px 16px;margin-bottom:8px;background:{THEME["card_bg"]}">'
                f'<div style="margin-bottom:6px">'
                f'<span style="background:{sent_bg};color:white;padding:2px 8px;'
                f'border-radius:12px;font-size:11px;font-weight:600">'
                f'{SENT_ICON.get(r["sentiment"],"")} {r["sentiment"]}</span>'
                f'<span style="color:{THEME["text_subtle"]};font-size:12px;margin-left:8px">{date_str}</span>'
                f'</div>'
                f'{title_html}'
                f'<p style="margin:6px 0 0;color:{THEME["text_muted"]};font-size:13px">&#127468;&#127463; {r["summary_en"] or "&mdash;"}</p>'
                f'</div>'
            )
            # See _render_card() — st.markdown preserves target="_blank",
            # st.html() strips it. Without this swap, clicking the title chip
            # in the "Articles by Bank" list would navigate the current tab.
            st.markdown(card2, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
# TAB 3 — OVERVIEW CHARTS
# ═══════════════════════════════════════════════════════════

with tab_overview:
    # ── Hero "Today's signal" card ──────────────────────────────────────────
    # One-glance summary of what changed period-over-period. Built from the
    # existing KPI values (no LLM call), so it's instant and free.

    def _delta_phrase(label: str, curr: int, prev: int, bad_when_up: bool) -> str | None:
        """Render a phrase like '↑ complaints +25%' when the change is material.

        Returns None when the metric is uninteresting (no change, or both 0)
        so we can skip it in the headline.
        """
        if curr == 0 and prev == 0:
            return None
        if prev == 0:
            return None  # avoid divide-by-zero / misleading 'infinity%'
        delta_pct = (curr - prev) / prev * 100
        if abs(delta_pct) < 5:
            return None  # noise — skip
        arrow = "▲" if delta_pct > 0 else "▼"
        good = (delta_pct < 0) if bad_when_up else (delta_pct > 0)
        color = THEME["success"] if good else THEME["danger"]
        sign = "+" if delta_pct > 0 else ""
        return (f'<span style="color:{color};font-weight:600">'
                f'{arrow} {label} {sign}{delta_pct:.0f}%</span>')

    _movers = [
        _delta_phrase("complaints",         complaints, complaints_p, bad_when_up=True),
        _delta_phrase("negative sentiment", neg,        neg_p,        bad_when_up=True),
        _delta_phrase("competitor promos",  promos,     promos_p,     bad_when_up=True),
        _delta_phrase("potential customers", seekers,   seekers_p,    bad_when_up=False),
    ]
    _movers = [m for m in _movers if m]
    if _movers:
        _movers_html = " · ".join(_movers[:3])
    else:
        _movers_html = f'<span style="color:{THEME["text_muted"]}">no material change vs last period</span>'

    _top_source = ""
    if not df.empty and "source" in df.columns:
        _top_source = df["source"].value_counts().idxmax()

    st.html(
        f"""
        <div style="background:{THEME["hero"]["bg_gradient"]};
                    border:1px solid {THEME["hero"]["border"]};
                    border-left:6px solid {THEME["hero"]["accent"]};
                    border-radius:14px;padding:18px 22px;margin-bottom:18px">
          <div style="font-size:12px;text-transform:uppercase;letter-spacing:1.5px;
                      color:{THEME["hero"]["kicker_fg"]};font-weight:700;margin-bottom:6px">
            ✨ Today's signal · last {days} days
          </div>
          <div style="font-size:18px;color:{THEME["text"]};line-height:1.5;font-weight:500">
            <strong>{total}</strong> articles tracked{(', leading source <strong>' + _top_source + '</strong>') if _top_source else ''}.
            Movers: {_movers_html}.
          </div>
        </div>
        """
    )

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Sentiment")
        sd = df["sentiment"].value_counts().reset_index()
        sd.columns = ["Sentiment", "Count"]
        fig = px.pie(sd, names="Sentiment", values="Count",
                     color="Sentiment", color_discrete_map=SENT_COLOR,
                     hole=0.55, height=280)
        fig.update_traces(textposition="outside", textinfo="percent+label")
        fig.update_layout(showlegend=False, margin=dict(t=20,b=0,l=0,r=0))
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Category")
        cd = df["category"].value_counts().reset_index()
        cd.columns = ["Category", "Count"]
        fig = px.bar(cd, x="Count", y="Category", orientation="h",
                     color="Category", color_discrete_map=CAT_COLOR, height=280)
        fig.update_layout(showlegend=False, margin=dict(t=20,b=0,l=0,r=0),
                          yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)

    with c3:
        st.subheader("Intent")
        id_ = df["intent"].value_counts().reset_index()
        id_.columns = ["Intent", "Count"]
        id_["Intent"] = id_["Intent"].map(INTENT_LABEL).fillna(id_["Intent"])
        fig = px.bar(id_, x="Count", y="Intent", orientation="h", height=250,
                     color_discrete_sequence=[THEME["primary_light"]])
        fig.update_layout(showlegend=False, margin=dict(t=20,b=0,l=0,r=0),
                          yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)

    with c4:
        st.subheader("Source × Sentiment")
        ss = df.groupby(["source","sentiment"]).size().reset_index(name="Count")
        fig = px.bar(ss, x="Count", y="source", color="sentiment",
                     color_discrete_map=SENT_COLOR, orientation="h",
                     barmode="stack", height=250)
        fig.update_layout(margin=dict(t=20,b=0,l=0,r=0),
                          yaxis_title=None, xaxis_title=None,
                          legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)

    # ── Volume by Source Type ─────────────────────────────────────────────
    # Quick sanity check on the source-mix: lets the reader see at a glance
    # if Facebook bank pages are starting to dominate the article stream,
    # which inflates the "positive sentiment" and "competitor promo" KPIs.
    st.subheader("Volume by Source Type")
    src_type_df = (
        df["source_type"]
        .map({"facebook": "📘 Facebook", "forum": "💬 Forum", "news": "📰 News"})
        .value_counts()
        .reset_index()
    )
    src_type_df.columns = ["Source Type", "Articles"]
    SOURCE_TYPE_COLORS = {
        "📘 Facebook": THEME["info"],         # blue — distinct from brand greens
        "💬 Forum":    THEME["primary"],      # brand green — the customer-voice channel
        "📰 News":     THEME["text_subtle"],  # neutral grey
    }
    fig_st = px.bar(
        src_type_df, x="Articles", y="Source Type", orientation="h",
        color="Source Type", color_discrete_map=SOURCE_TYPE_COLORS,
        height=160, text_auto=True,
    )
    fig_st.update_layout(showlegend=False, margin=dict(t=10, b=0, l=0, r=0),
                         yaxis_title=None, xaxis_title=None)
    st.plotly_chart(fig_st, use_container_width=True)

    # Volume by day
    st.subheader("Article Volume by Day")
    vol_df = df.copy()
    vol_df["date"] = vol_df["scraped_at"].dt.strftime("%d %b")
    vol_day = vol_df.groupby(["date", "sentiment"]).size().reset_index(name="Count")
    fig = px.bar(
        vol_day, x="date", y="Count", color="sentiment",
        color_discrete_map=SENT_COLOR, barmode="stack", height=260,
        text_auto=True,
    )
    fig.update_traces(textfont_size=11)
    fig.update_layout(
        margin=dict(t=10, b=10, l=0, r=0),
        xaxis_title=None, yaxis_title=None,
        yaxis=dict(tickformat="d", dtick=1),
        legend=dict(orientation="h", y=-0.25),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Word cloud ────────────────────────────────────────────────────────
    st.divider()
    wc_col1, wc_col2 = st.columns([1, 5])
    with wc_col1:
        st.subheader("Top Phrases")
        wc_choice = st.selectbox(
            "Category",
            ["All"] + PRIORITY_ORDER,
            index=0,
            label_visibility="collapsed",
        )
    with wc_col2:
        st.caption(
            "Most-mentioned words and 2-word phrases in titles and Vietnamese summaries. "
            "Your own search keywords (vay mua nhà, mua nhà…) are filtered out so the cloud "
            "shows what people are *adding* to the conversation."
        )

    wc_df = df if wc_choice == "All" else df[df["category"] == wc_choice]
    wc_texts = (
        wc_df["title"].fillna("").tolist()
        + wc_df["summary_vi"].fillna("").tolist()
    )

    if not wc_texts or not any(wc_texts):
        st.info("Not enough text to build a word cloud for this selection.")
    else:
        png = _wordcloud_bytes(tuple(wc_texts))
        if png:
            st.image(png, use_column_width=True)
        else:
            st.info("No phrases left after filtering for this selection.")


# ═══════════════════════════════════════════════════════════
# TAB 4 — INSIGHTS  (AI-generated report)
# ═══════════════════════════════════════════════════════════

with tab_insights:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline.insight_agent import generate_report, get_latest_report, markdown_to_html

    st.subheader("🧠 Social Listening Expert")
    st.caption(
        "AI-generated weekly brief for the home loan product team — "
        "plain-English insights and prioritised actions."
    )

    col_btn, col_days, col_spacer = st.columns([1, 1, 4])
    with col_days:
        report_days = st.selectbox("Period", [7, 14, 30], index=0,
                                   format_func=lambda d: f"Last {d} days")
    with col_btn:
        st.write("")
        run_report = st.button("⚡ Generate Report", type="primary")

    st.divider()

    report_md: str | None = None

    if run_report:
        report_placeholder = st.empty()
        accumulated: list[str] = []

        with st.spinner("Analysing articles and generating insights…"):
            def _stream_to_ui(chunk: str):
                accumulated.append(chunk)
                report_placeholder.markdown("".join(accumulated))

            try:
                report_md = generate_report(days=report_days, stream_callback=_stream_to_ui)
                report_placeholder.markdown(report_md)
                st.success("Report saved to data/reports/")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Failed to generate report: {e}")
    else:
        report_md = get_latest_report()
        if report_md:
            st.markdown(report_md)
        else:
            st.info(
                "No report generated yet. "
                "Click **⚡ Generate Report** above to create your first insight brief."
            )

    if report_md:
        from pipeline.timeutils import now_local
        stamp = now_local().strftime("%Y%m%d_%H%M")
        st.divider()
        dl1, dl2, dl_spacer = st.columns([1, 1, 4])
        with dl1:
            st.download_button(
                "⬇️ Markdown (.md)",
                data=report_md.encode("utf-8"),
                file_name=f"insight_report_{stamp}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "⬇️ HTML (print → PDF)",
                data=markdown_to_html(report_md).encode("utf-8"),
                file_name=f"insight_report_{stamp}.html",
                mime="text/html",
                use_container_width=True,
                help="Open the HTML file in any browser and use Print → Save as PDF",
            )


# ═══════════════════════════════════════════════════════════
# TAB 5 — COST TRACKER  (admin-only: visible when ?admin=1 is in the URL)
# ═══════════════════════════════════════════════════════════

def _render_cost_tab():
    import os, requests as _req

    st.subheader("💰 API Usage & Cost Tracker")
    st.caption("Tracks every Claude and Firecrawl call made by this app.")

    st.info(
        "**How the scraper saves money:** Plain requests (free) are tried first on every site. "
        "Firecrawl is only called when a site blocks us or uses JavaScript rendering. "
        "If you see 0 Firecrawl calls — that's good, all sites responded normally today."
    )

    @st.cache_data(ttl=30)
    def load_usage_log():
        try:
            return db.read_sql_df("SELECT * FROM usage_log ORDER BY created_at DESC")
        except Exception:
            return pd.DataFrame()

    @st.cache_data(ttl=300)
    def get_firecrawl_credits():
        key = os.getenv("FIRECRAWL_API_KEY", "")
        if not key:
            return None
        try:
            r = _req.get(
                "https://api.firecrawl.dev/v1/team/credits",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    usage_df = load_usage_log()
    fc_credits = get_firecrawl_credits()

    # ── KPI row ──────────────────────────────────────────────
    claude_df = usage_df[usage_df["service"].str.startswith("claude")] if not usage_df.empty else pd.DataFrame()
    total_cost   = claude_df["cost_usd"].sum()   if not claude_df.empty else 0
    total_tokens = (claude_df["tokens_in"].sum() + claude_df["tokens_out"].sum()) if not claude_df.empty else 0
    total_calls  = len(claude_df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Claude Cost",   f"${total_cost:.4f}")
    c2.metric("Total Tokens Used",   f"{total_tokens:,}")
    c3.metric("Total API Calls",     total_calls)

    if fc_credits:
        remaining = fc_credits.get("remaining_credits", fc_credits.get("credits", "—"))
        c4.metric("Firecrawl Credits Left", remaining)
    else:
        c4.metric("Firecrawl Credits Left", "—")

    st.divider()

    if usage_df.empty:
        st.info("No usage logged yet — costs will appear here after the next categorizer or report run.")
    else:
        usage_df["created_at"] = pd.to_datetime(usage_df["created_at"])
        usage_df["date"] = usage_df["created_at"].dt.strftime("%d %b")

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Cost by Service")
            svc = usage_df.groupby("service")["cost_usd"].sum().reset_index()
            svc.columns = ["Service", "Cost (USD)"]
            fig = px.bar(svc, x="Service", y="Cost (USD)",
                         color="Service", height=260,
                         color_discrete_sequence=[THEME["info"], THEME["primary"], THEME["warning"]])
            fig.update_layout(showlegend=False, margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            st.subheader("Daily Cost Trend")
            daily = usage_df.groupby("date")["cost_usd"].sum().reset_index()
            daily.columns = ["Date", "Cost (USD)"]
            fig2 = px.line(daily, x="Date", y="Cost (USD)", markers=True, height=260)
            fig2.update_layout(margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Usage Log")
        display = usage_df[["created_at", "service", "model", "tokens_in", "tokens_out",
                             "cost_usd", "items_processed"]].copy()
        display.columns = ["Time", "Service", "Model", "Tokens In", "Tokens Out",
                           "Cost (USD)", "Items"]
        display["Cost (USD)"] = display["Cost (USD)"].map("${:.4f}".format)
        display["Time"] = display["Time"].dt.strftime("%d %b %H:%M")
        st.dataframe(display, use_container_width=True, hide_index=True)


if tab_cost is not None:
    with tab_cost:
        _render_cost_tab()
