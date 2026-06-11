"""Generate Streamlit Cloud secrets TOML from .env and copy to macOS clipboard.

Streamlit's secrets editor expects strict TOML. Hand-editing it from a template
runs into smart-quote and escaping issues — this script produces guaranteed
valid TOML and drops it straight onto your clipboard.

    python3 scripts/copy_streamlit_secrets.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
env = dotenv_values(ROOT / ".env")

if not env:
    sys.exit("Couldn't read .env — is the file there?")

# Keys that the app actually reads. Other .env entries (if any) are skipped.
WANTED = [
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "FIRECRAWL_API_KEY",
    "RAPIDAPI_KEY",          # competitor-page scraping (RapidAPI)
    "FACEBOOK_ACCESS_TOKEN",
    "FACEBOOK_PAGE_ID",      # KBank's own page — inbox + own-page posts
    "FACEBOOK_APP_ID",
    "FACEBOOK_APP_SECRET",
]

lines = []
for key in WANTED:
    value = env.get(key, "") or ""
    # json.dumps produces TOML-valid double-quoted strings with proper escaping.
    lines.append(f"{key} = {json.dumps(value)}")

toml = "\n".join(lines) + "\n"

subprocess.run(["pbcopy"], input=toml.encode(), check=True)

print(f"✓ Copied Streamlit secrets TOML to clipboard ({len(toml)} chars)\n")
print("Preview (values masked):")
print("─" * 60)
for key in WANTED:
    value = env.get(key, "") or ""
    masked = value[:6] + "…" if len(value) > 8 else value or "(empty)"
    print(f"  {key} = {masked!r}")
print("─" * 60)
print("\nNow paste (Cmd+V) into Streamlit Cloud's Secrets box.")
