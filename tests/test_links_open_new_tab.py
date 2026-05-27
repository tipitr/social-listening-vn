"""Every external link in the dashboard must open in a new tab.

ROOT CAUSE of the reported bug: source chips and title links in the
Action Feed use target="_blank" but no rel="noopener noreferrer".
Without rel, browsers (especially inside Streamlit's iframe when
accessed via ngrok / Streamlit Cloud) sometimes ignore target="_blank"
and navigate in the current tab — which drops the user out of the
dashboard.

We enforce the contract statically: every <a href="..."> in the
dashboard source must have BOTH target="_blank" AND a rel attribute
that contains "noopener".
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).parent.parent
APP = REPO / "dashboard" / "app.py"


def _anchor_tags_with_href(source: str) -> list[str]:
    """Return every f-string <a ...> opening tag containing an href."""
    # Match <a ...href=... > — we don't need to balance, the opening tag
    # always closes with > before any text content.
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
