"""Pipeline runtime modules must call load_dotenv(override=True).

ROOT CAUSE (observed 2026-05-27): the categorizer crashed with
"Could not resolve authentication method" even though ANTHROPIC_API_KEY
was set correctly in .env. python-dotenv's default behavior is
``override=False``, which means an environment variable already set in
the shell — even if it's the empty string — wins against the .env value.

The user had ``ANTHROPIC_API_KEY=""`` exported from a shell startup
script. load_dotenv() refused to replace it, so the categorizer
received ``api_key=""`` and the Anthropic SDK rejected it.

CONTRACT this test enforces:
  Every runtime pipeline module that reads secrets from .env must call
  load_dotenv(override=True) so the .env file wins against empty shell
  exports.

EXCEPTION: pipeline/db.py intentionally uses override=False because in
GitHub Actions / Streamlit Cloud, real DATABASE_URL is set as a
platform secret and the .env in the repo (if any) should NOT override
it. That asymmetry is documented inline in db.py.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).parent.parent

# Files that load secrets from .env at module load time. Each one must
# use override=True so .env wins against an empty shell-exported value.
def _find_load_dotenv_call(src: str):
    """Return the full ``load_dotenv(...)`` call string, balanced parens.

    A plain regex would stop at the first ``)``, but ``load_dotenv(
    Path(__file__).parent.parent / ".env", override=False)`` contains
    inner parens that throw off ``[^)]*``. We count brackets manually.
    """
    start = src.find("load_dotenv(")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                class _M:  # tiny shim so callers can use .group(0) like a re.Match
                    def __init__(self, s): self._s = s
                    def group(self, _=0): return self._s
                return _M(src[start:i + 1])
    return None


RUNTIME_FILES = [
    "pipeline/categorizer.py",
    "pipeline/insight_agent.py",
    "pipeline/collector.py",
    "pipeline/scheduler.py",
    "scrapers/facebook.py",
    "scrapers/facebook_scraper3.py",
    "scrapers/firecrawl_scraper.py",
    "scrapers/smart_scraper.py",
]


def test_runtime_load_dotenv_uses_override_true():
    """Each runtime module must pass override=True to load_dotenv().

    Without this, an empty ANTHROPIC_API_KEY/RAPIDAPI_KEY/etc. exported
    in the user's shell would silently shadow the real values in .env.
    """
    failures = []
    for rel_path in RUNTIME_FILES:
        src = (REPO / rel_path).read_text(encoding="utf-8")
        m = _find_load_dotenv_call(src)
        if not m:
            failures.append(f"{rel_path}: no load_dotenv() call found")
            continue
        if "override=True" not in m.group(0):
            failures.append(
                f"{rel_path}: load_dotenv() must use override=True so empty "
                f"shell variables can't shadow .env values. Found: {m.group(0)}"
            )

    assert not failures, "\n".join(failures)


def test_db_intentionally_uses_override_false():
    """pipeline/db.py is the exception — production secrets (GitHub Actions,
    Streamlit Cloud) should win over a stale local .env. That asymmetry
    is intentional and documented inline. Keep it that way."""
    src = (REPO / "pipeline" / "db.py").read_text(encoding="utf-8")
    m = _find_load_dotenv_call(src)
    assert m, "pipeline/db.py must still call load_dotenv()"
    assert "override=False" in m.group(0), (
        "pipeline/db.py must keep override=False so GitHub Actions / "
        "Streamlit Cloud secrets win over a stale local .env."
    )
