"""The software version (file VERSION in the project folder: V0, V1, V2 …)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def current(root: Path = ROOT) -> str:
    f = root / "VERSION"
    return f.read_text().strip() if f.exists() else "V0"


def number(label: str) -> int:
    """V12 → 12 (a label without a number counts as 0)."""
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else 0
