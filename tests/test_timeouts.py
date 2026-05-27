"""TDD for fix #5: external calls must have explicit timeouts so the
scheduler / dashboard never hang indefinitely.

ROOT CAUSE (from audit):
  - scrapers/firecrawl_scraper.py & scrapers/smart_scraper.py call
    app.scrape_url(...) with no timeout.
  - pipeline/insight_agent.py calls client.messages.stream(...) with no timeout.
  - pipeline/db.py calls psycopg2.connect(**_pg_kwargs(...)) without
    connect_timeout, so a dead Supabase can hang a Streamlit page load.

We verify by inspecting the code (test the contract, not the network).
That keeps the tests fast and offline.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

REPO = Path(__file__).parent.parent


def _read(rel_path: str) -> str:
    return (REPO / rel_path).read_text(encoding="utf-8")


def test_firecrawl_scraper_passes_timeout():
    """scrapers/firecrawl_scraper.py must pass a timeout to scrape_url."""
    src = _read("scrapers/firecrawl_scraper.py")
    # Find the scrape_url call and assert "timeout" is one of the keyword args
    call_match = re.search(r"app\.scrape_url\([^)]*\)", src, re.DOTALL)
    assert call_match, "Could not find app.scrape_url(...) call in firecrawl_scraper.py"
    assert "timeout" in call_match.group(0), (
        "scrape_url() in firecrawl_scraper.py needs a timeout=… arg "
        "to prevent indefinite hangs"
    )


def test_smart_scraper_passes_timeout():
    """scrapers/smart_scraper.py _fetch_firecrawl must pass a timeout."""
    src = _read("scrapers/smart_scraper.py")
    call_match = re.search(r"app\.scrape_url\([^)]*\)", src, re.DOTALL)
    assert call_match, "Could not find app.scrape_url(...) call in smart_scraper.py"
    assert "timeout" in call_match.group(0), (
        "scrape_url() in smart_scraper.py needs a timeout=… arg"
    )


def test_psycopg2_connect_has_connect_timeout():
    """pipeline/db.py must pass connect_timeout to psycopg2.connect.

    Otherwise a dead Postgres host can hang Streamlit page loads for the OS
    default (~75s) on every request.
    """
    src = _read("pipeline/db.py")
    # _pg_kwargs builds the dict passed to psycopg2.connect — assert it
    # includes a connect_timeout key.
    pg_kwargs = re.search(r"def _pg_kwargs.*?return\s*\{[^}]+\}", src, re.DOTALL)
    assert pg_kwargs, "Could not locate _pg_kwargs in pipeline/db.py"
    assert "connect_timeout" in pg_kwargs.group(0), (
        "_pg_kwargs() needs a connect_timeout key so psycopg2.connect "
        "doesn't hang on dead Postgres hosts"
    )


def test_anthropic_insight_stream_has_timeout():
    """pipeline/insight_agent.py must time out the streaming Claude call.

    Streaming calls without a timeout can hang the dashboard "Generate Report"
    spinner forever if the API stalls mid-stream.
    """
    src = _read("pipeline/insight_agent.py")
    # The client.messages.stream(...) call is multiline — match the whole arg list
    call = re.search(r"client\.messages\.stream\((.*?)\)\s*as\s*stream", src, re.DOTALL)
    assert call, "Could not find client.messages.stream(...) call in insight_agent.py"
    # Either kwarg "timeout=" or "options=…timeout" is acceptable
    assert "timeout" in call.group(1), (
        "client.messages.stream(...) in insight_agent.py needs a timeout "
        "so a stalled stream doesn't hang the dashboard"
    )
