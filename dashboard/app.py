"""Streamlit dashboard — Social Listening VN: Home Loan Product Intelligence."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import db  # noqa: E402
from pipeline.config_loader import load_banks as _load_banks_yaml  # noqa: E402
from pipeline.config_loader import load_keywords as _load_keywords_yaml  # noqa: E402
from pipeline.timeutils import days_ago_iso  # noqa: E402

from dashboard.wordcloud_view import render_png as render_wordcloud_png  # noqa: E402

st.set_page_config(page_title="Home Loan Intel", page_icon="🏠", layout="wide")

# ── Styling ──────────────────────────────────────────────────────────────────

SENT_COLOR  = {"positive": "#27ae60", "neutral": "#95a5a6", "negative": "#e74c3c"}
SENT_ICON   = {"positive": "😊", "neutral": "😐", "negative": "😞"}
CAT_COLOR   = {
    "interest_rate":   "#2980b9",
    "loan_approval":   "#8e44ad",
    "bank_comparison": "#d35400",
    "complaint":       "#e74c3c",
    "promotion":       "#16a085",
    "general":         "#7f8c8d",
}
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
        df["scraped_at"] = pd.to_datetime(df["scraped_at"])
    return df


@st.cache_data(ttl=3600)
def load_home_loan_cfg() -> dict:
    return _load_keywords_yaml().get("home_loan", {})


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


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏠 Home Loan Intel")
    st.divider()
    days = st.slider("Date range (days)", 1, 30, 7)
    df_all = load_data(days)
    banks  = load_banks()

    if not df_all.empty:
        sources   = sorted(df_all["source"].dropna().unique().tolist())
        sel_src   = st.multiselect("Source", sources, default=sources)
        sel_sent  = st.multiselect("Sentiment",
                                   ["positive", "neutral", "negative"],
                                   default=["positive", "neutral", "negative"])
        sel_cat   = st.multiselect("Category", PRIORITY_ORDER,
                                   default=PRIORITY_ORDER)
    st.divider()
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# ── Apply filters ─────────────────────────────────────────────────────────────

df = df_all.copy()
if not df.empty:
    if sel_src:  df = df[df["source"].isin(sel_src)]
    if sel_sent: df = df[df["sentiment"].isin(sel_sent)]
    if sel_cat:  df = df[df["category"].isin(sel_cat)]

    # Detect bank mentions
    combined = df["title"].fillna("") + " " + df["summary_en"].fillna("") + " " + df["summary_vi"].fillna("")
    df["banks_mentioned"] = combined.apply(lambda t: detect_banks(t, banks))

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("# 🏠 Home Loan — Social Intelligence")
st.caption(f"Last {days} days · {len(df)} articles · times shown in GMT+7 · refreshes every 60s")

if df.empty:
    st.info("No articles match the current filters.")
    st.stop()

# KPI strip
total     = len(df)
complaints = (df["category"] == "complaint").sum()
promos     = (df["category"] == "promotion").sum()
seekers    = (df["intent"] == "seeking_info").sum()
neg        = (df["sentiment"] == "negative").sum()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Articles",    total)
k2.metric("🚨 Complaints",     complaints,
          delta=f"{'High' if complaints > total * 0.3 else 'Normal'}",
          delta_color="inverse")
k3.metric("📢 Competitor Promos", promos)
k4.metric("🔍 Potential Customers", seekers)
k5.metric("😞 Negative Sentiment",  neg)

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

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Action Feed", "🏦 Competitor Intel", "📊 Overview", "🧠 Insights", "💰 Cost"])

# ═══════════════════════════════════════════════════════════
# TAB 1 — ACTION FEED  (priority-sorted articles)
# ═══════════════════════════════════════════════════════════

with tab1:
    # Sort by priority: complaints first, then interest_rate, then promos…
    cat_rank = {c: i for i, c in enumerate(PRIORITY_ORDER)}
    df_feed  = df.copy()
    df_feed["_rank"] = df_feed["category"].map(cat_rank).fillna(99)
    df_feed  = df_feed.sort_values(["_rank", "scraped_at"], ascending=[True, False])

    # Section headers
    sections = {
        "complaint":      ("🚨 Complaints & Pain Points",   "#fdf2f2", "#e74c3c"),
        "interest_rate":  ("💰 Rate Intelligence",           "#f0f7ff", "#2980b9"),
        "promotion":      ("📢 Competitor Promotions",       "#f0fff8", "#16a085"),
        "loan_approval":  ("📑 Loan Approval Topics",        "#faf5ff", "#8e44ad"),
        "bank_comparison":("🏦 Bank Comparisons",            "#fff8f0", "#d35400"),
        "general":        ("📰 General News",                "#fafafa", "#7f8c8d"),
    }

    def _badge(text, bg, fg="white"):
        return (f'<span style="background:{bg};color:{fg};padding:2px 10px;'
                f'border-radius:20px;font-size:12px;font-weight:600;white-space:nowrap">{text}</span>')

    for cat, (heading, card_bg, accent) in sections.items():
        grp = df_feed[df_feed["category"] == cat]
        if grp.empty:
            continue
        st.html(f"<h3 style='margin:0 0 8px'>{heading} <small style='color:{accent};font-size:16px'>{len(grp)}</small></h3>")

        for _, row in grp.iterrows():
            sent    = row.get("sentiment") or "neutral"
            src     = row.get("source") or ""
            title   = row.get("title")  or "(no title)"
            url     = row.get("url")    or ""
            en      = row.get("summary_en") or ""
            vi      = row.get("summary_vi") or ""
            intent  = INTENT_LABEL.get(row.get("intent") or "", "")
            date    = row["scraped_at"].strftime("%d %b %H:%M") if pd.notna(row["scraped_at"]) else ""
            b_names = row.get("banks_mentioned") or []

            sent_bg = SENT_COLOR.get(sent, "#95a5a6")

            bank_badges = "".join(
                f'<span style="background:#eaf4fb;color:#2471a3;padding:2px 8px;'
                f'border-radius:12px;font-size:11px;margin-right:4px">{b}</span>'
                for b in b_names
            )

            title_html = (
                f'<a href="{url}" target="_blank" style="color:#1a1a1a;font-weight:700;'
                f'font-size:15px;text-decoration:none">{title}</a>'
                if url else f'<span style="font-weight:700;font-size:15px">{title}</span>'
            )

            src_html = (
                f'<a href="{url}" target="_blank" style="background:#ecf0f1;color:#555;'
                f'padding:2px 8px;border-radius:12px;font-size:11px;text-decoration:none">🔗 {src}</a>'
                if url else _badge(src, "#ecf0f1", "#555")
            )

            card = (
                f'<div style="background:{card_bg};border:1px solid #e8e8e8;'
                f'border-left:4px solid {accent};border-radius:10px;'
                f'padding:14px 18px;margin-bottom:10px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.05)">'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:8px">'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
                f'{_badge(SENT_ICON.get(sent,"") + " " + sent, sent_bg)}'
                f'{src_html}{bank_badges}'
                f'</div>'
                f'<span style="color:#999;font-size:12px">{date}</span>'
                f'</div>'
                f'{title_html}'
                f'<p style="margin:8px 0 3px;color:#2c3e50;font-size:14px">&#127468;&#127463; {en or "&mdash;"}</p>'
                f'<p style="margin:0;color:#666;font-size:13px;font-style:italic">&#127483;&#127475; {vi or "&mdash;"}</p>'
                f'<div style="margin-top:8px">'
                f'<span style="background:#f4f4f4;color:#555;padding:2px 8px;'
                f'border-radius:12px;font-size:11px">{intent}</span>'
                f'</div></div>'
            )
            st.html(card)

        st.html("<div style='margin-bottom:8px'></div>")


# ═══════════════════════════════════════════════════════════
# TAB 2 — COMPETITOR INTEL
# ═══════════════════════════════════════════════════════════

with tab2:
    # ── Bank reference table ──────────────────────────────────────────────
    with st.expander("📚 Bank Reference — Home Loan Products in Vietnam", expanded=False):
        ref_rows = []
        TYPE_LABEL = {"state_owned": "🏛️ State", "private": "🏢 Private", "foreign": "🌏 Foreign"}
        for short_name, info in banks.items():
            ref_rows.append({
                "Bank":       short_name,
                "Type":       TYPE_LABEL.get(info["type"], info["type"]),
                "Promo Rate": info.get("promo_rate", "—"),
                "Max Term":   f"{info.get('max_term_yrs','—')} yrs",
                "Notes":      (info.get("notes") or "").strip()[:120],
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
        st.info("No bank names detected in current articles. Try extending the date range.")
    else:
        bdf = pd.DataFrame(rows_banks)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Mention Volume by Bank")
            vol = bdf["bank"].value_counts().reset_index()
            vol.columns = ["Bank", "Mentions"]
            # Colour by type
            type_color = {"state_owned": "#2980b9", "private": "#27ae60", "foreign": "#8e44ad"}
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
        sel_bank = st.selectbox("Select bank", sorted(bdf["bank"].unique()),
                                format_func=lambda b: f"{b} ({banks.get(b,{}).get('promo_rate','')})  ")
        bank_articles = bdf[bdf["bank"] == sel_bank].sort_values("date", ascending=False)
        for _, r in bank_articles.iterrows():
            sent_bg = SENT_COLOR.get(r["sentiment"], "#95a5a6")
            date_str = r["date"].strftime("%d %b") if pd.notna(r["date"]) else ""
            title_html = (
                f'<a href="{r["url"]}" target="_blank" style="color:#1a1a1a;font-weight:600;'
                f'font-size:14px;text-decoration:none">{r["title"]}</a>'
                if r["url"] else f'<span style="font-weight:600">{r["title"]}</span>'
            )
            card2 = (
                f'<div style="border:1px solid #e8e8e8;border-radius:8px;'
                f'padding:12px 16px;margin-bottom:8px;background:#fff">'
                f'<div style="margin-bottom:6px">'
                f'<span style="background:{sent_bg};color:white;padding:2px 8px;'
                f'border-radius:12px;font-size:11px;font-weight:600">'
                f'{SENT_ICON.get(r["sentiment"],"")} {r["sentiment"]}</span>'
                f'<span style="color:#999;font-size:12px;margin-left:8px">{date_str}</span>'
                f'</div>'
                f'{title_html}'
                f'<p style="margin:6px 0 0;color:#555;font-size:13px">&#127468;&#127463; {r["summary_en"] or "&mdash;"}</p>'
                f'</div>'
            )
            st.html(card2)


# ═══════════════════════════════════════════════════════════
# TAB 3 — OVERVIEW CHARTS
# ═══════════════════════════════════════════════════════════

with tab3:
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
                     color_discrete_sequence=["#5dade2"])
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

with tab4:
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
# TAB 5 — COST TRACKER
# ═══════════════════════════════════════════════════════════

with tab5:
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
                         color_discrete_sequence=["#2980b9", "#16a085", "#8e44ad"])
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
