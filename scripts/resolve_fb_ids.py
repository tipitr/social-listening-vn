#!/usr/bin/env python3
"""One-shot helper: resolve every facebook_pages entry's numeric FB id
and print a YAML snippet you can paste back into config/sources.yaml.

Why this exists:
    The RapidAPI Facebook Scraper3 charges 1 API call to look up a
    page's numeric id, and 1 more to fetch its posts. Pinning the
    resolved id in sources.yaml as ``fb_id: "<id>"`` lets the daily
    cron skip the lookup forever, halving quota burn.

Usage:
    python3 scripts/resolve_fb_ids.py

    Then paste the printed YAML lines under each entry in
    config/sources.yaml.

Cost: 1 API call per unresolved page (~10 calls one-time).
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config_loader import load_sources  # noqa: E402

load_dotenv(override=True)

HOST = "facebook-scraper3.p.rapidapi.com"
KEY  = os.environ.get("RAPIDAPI_KEY")

if not KEY:
    print("RAPIDAPI_KEY not set — add it to .env first.", file=sys.stderr)
    sys.exit(1)

HEADERS = {"x-rapidapi-key": KEY, "x-rapidapi-host": HOST}


def resolve(query: str) -> str | None:
    r = requests.get(f"https://{HOST}/search/pages",
                     headers=HEADERS, params={"query": query}, timeout=20)
    if r.status_code != 200:
        print(f"  ! HTTP {r.status_code} for {query}: {r.text[:120]}")
        return None
    items = r.json().get("results") or r.json().get("data") or []
    if not items:
        print(f"  ! no result for {query}")
        return None
    first = items[0]
    return str(first.get("facebook_id") or first.get("page_id") or first.get("id") or "")


src = load_sources()
pages = src.get("facebook_pages", [])

print("\nPaste these into config/sources.yaml under each matching entry:\n")
print("─" * 60)

skipped = 0
resolved = 0
for p in pages:
    if p.get("fb_id"):
        skipped += 1
        continue
    query = p.get("page_id", p["name"])
    fb_id = resolve(query)
    if fb_id:
        print(f'  - name: {p["name"]}')
        print(f'    page_id: "{p.get("page_id", p["name"])}"')
        print(f'    fb_id: "{fb_id}"  # <-- add this')
        resolved += 1

print("─" * 60)
print(f"\n{resolved} resolved, {skipped} already had fb_id pinned.")
