"""Shared test fixtures."""
import sys
from pathlib import Path

# Make `pipeline.` and `scrapers.` imports work without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))
