"""Repository paths used by developer tooling."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "deployment"
STATE_DIR = DEV_DIR / ".state"
