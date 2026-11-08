"""Every library the backend imports is installed by requirements.txt (pypdf was missing: on a fresh Windows install the PDFs
came out without the logo and company name, because the stamp quietly gave up)."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# imported names that come with a listed package (or with requirements-fea.txt)
COMES_WITH = {"OCP": "cadquery", "numpy": "cadquery", "PIL": "pillow", "mpl_toolkits": "matplotlib", "pydantic": "fastapi",
              "starlette": "fastapi", "pypdfium2": "pdfplumber", "gmsh": "requirements-fea.txt"}


def test_every_imported_library_is_in_requirements():
    req = set()
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            req.add(re.split(r"[<>=\[ ;]", line.strip())[0].lower().replace("-", "_"))
    mods = set()
    for p in (ROOT / "backend").rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods.add(n.module.split(".")[0])
    third = {m for m in mods if m not in sys.stdlib_module_names and m != "backend"}
    missing = sorted(m for m in third if m.lower() not in req and m not in COMES_WITH)
    assert not missing, f"add to requirements.txt: {missing}"
    assert "pypdf" in req                       # the logo stamp of every PDF needs it
