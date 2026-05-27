"""Every external link in the dashboard must open in a new tab.

ROOT CAUSE of the reported bug (confirmed by probe): Streamlit's
``st.html()`` sanitiser strips the ``target`` attribute from anchors,
even though ``rel="noopener noreferrer"`` is preserved.  As a result
clicking a source chip kept the user in the current tab (or, in
Streamlit Cloud / behind ngrok, navigated to an empty Streamlit
viewport).  ``st.markdown(html, unsafe_allow_html=True)`` does NOT
strip ``target`` — that is the supported way to render anchor tags
that open in a new tab.

We enforce TWO contracts:
  1. Source-level — every ``<a href=…>`` literal in the dashboard
     source must already declare ``target="_blank"`` and a ``rel``
     containing ``"noopener"``.  Catches regressions early.
  2. Source-level — the card-render helper must NOT use ``st.html``
     for HTML that includes such anchors; it must use
     ``st.markdown(..., unsafe_allow_html=True)`` so the ``target``
     attribute survives sanitisation.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).parent.parent
APP = REPO / "dashboard" / "app.py"


def _anchor_tags_with_href(source: str) -> list[str]:
    """Return every f-string <a ...> opening tag containing an href."""
    return re.findall(r"<a\s[^>]*href=[^>]*>", source)


def test_every_anchor_has_target_blank_and_rel_noopener():
    src = APP.read_text(encoding="utf-8")
    anchors = _anchor_tags_with_href(src)
    assert anchors, "Could not find any <a href=…> in dashboard/app.py"

    missing = []
    for tag in anchors:
        if 'target="_blank"' not in tag:
            missing.append(("no target=_blank", tag))
            continue
        if "noopener" not in tag:
            missing.append(("no rel=noopener", tag))

    assert not missing, (
        "Each <a> with href must have target=\"_blank\" AND rel including "
        "\"noopener\" so links reliably open in a new tab. "
        f"Missing on {len(missing)} tag(s): {missing}"
    )


def test_card_renderer_uses_markdown_not_html():
    """The article-card HTML contains <a target="_blank"> links. It must be
    rendered via st.markdown(..., unsafe_allow_html=True), not st.html(),
    because st.html silently strips the target attribute."""
    src = APP.read_text(encoding="utf-8")

    # Find the _render_card function body and check it uses st.markdown.
    fn = re.search(
        r"def _render_card\(.*?(?=\n# |\n\S)",
        src,
        re.DOTALL,
    )
    assert fn, "Could not locate _render_card() in dashboard/app.py"

    body = fn.group(0)
    assert "st.markdown" in body and "unsafe_allow_html=True" in body, (
        "_render_card() must call st.markdown(card, unsafe_allow_html=True) so "
        "that target=\"_blank\" survives Streamlit's HTML sanitiser. "
        "Using st.html() strips the target attribute and the link no longer "
        "opens in a new tab."
    )
    # And it must NOT use st.html(card) — that's the specific anti-pattern.
    assert not re.search(r"st\.html\s*\(\s*card\s*\)", body), (
        "_render_card() still calls st.html(card) — switch to "
        "st.markdown(card, unsafe_allow_html=True) instead."
    )


def test_competitor_intel_card_uses_markdown_not_html():
    """The 'Articles by Bank' card render path under Competitor Intel renders
    title anchors too. Same constraint applies."""
    src = APP.read_text(encoding="utf-8")
    # The variable is named card2 in that scope.
    assert not re.search(r"st\.html\s*\(\s*card2\s*\)", src), (
        "Competitor Intel 'Articles by Bank' still calls st.html(card2). "
        "Switch to st.markdown(card2, unsafe_allow_html=True) so the title "
        "link opens in a new tab."
    )
