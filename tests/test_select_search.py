"""Search box on long dropdowns (frontend/select-search.js): loaded on every page, and works in a browser
(filters by any word, code or group heading; Enter / click picks and fires change; Esc keeps the value)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"


def test_every_logged_in_page_loads_the_search():
    pages = [p for p in FRONT.glob("*.html") if "/static/auth.js" in p.read_text(encoding="utf-8")]
    assert len(pages) >= 10
    missing = [p.name for p in pages if '<script src="/static/select-search.js"></script>' not in p.read_text(encoding="utf-8")]
    assert not missing, f"add select-search.js to {missing}"
    assert ".ss-pop" in (FRONT / "style.css").read_text(encoding="utf-8")


def test_minimum_is_twelve_choices():
    assert re.search(r"SEARCH_MIN = 12;", (FRONT / "select-search.js").read_text(encoding="utf-8"))


def test_search_in_a_browser():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    if subprocess.run([node, "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "js" / "select_search_check.js")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr


def test_other_grades_hint_is_short():
    """The part panel names at most 3 other grades of the type (fin foil has 131), the rest as a count + 'choose'."""
    js = (FRONT / "parts.js").read_text(encoding="utf-8")
    assert "r.grades.filter((g) => g !== r.material).map(esc).join" not in js
    assert "others.slice(0, 3)" in js and 'id="chooseOtherGrade"' in js
    assert "DTCSelectSearch.open(sel)" in js
