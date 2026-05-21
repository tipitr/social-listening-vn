"""Copy DATABASE_URL from .env to the macOS clipboard, byte-for-byte clean.

Use this when you need to paste the URL into GitHub Actions secrets or
Streamlit Cloud — bypasses copy/paste line-wrap and smart-quote issues.

    python3 scripts/copy_db_url.py
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

url = os.getenv("DATABASE_URL", "").strip()
if not url:
    sys.exit("DATABASE_URL not found in .env")

subprocess.run(["pbcopy"], input=url.encode(), check=True)

print(f"✓ Copied DATABASE_URL to clipboard ({len(url)} chars)")
print()
print(f"  starts:  {url[:50]}...")
print(f"  ends:    ...{url[-30:]}")
print()
print("Now paste (Cmd+V) into the GitHub secret value field.")
