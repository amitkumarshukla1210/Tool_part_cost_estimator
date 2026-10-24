"""Bring the data of an installation up to what the installed version needs, without touching what is there (roadmap stage 25).

Run by upgrade.py after the new files are in place, by Install_Tool, and safe to run any time (every step only adds what is missing):
    1  project database      new tables and columns are created in data/projects.sqlite
    2  master data           the rows and parameters a version introduces are added (Component classes, Tool detail rules, Foundry materials,
                             review checklist, stage rules, machines and bases of the capacity ladders …); rows you edited are never changed
    3  self-test             the app starts, the version is read and the master data validates

    python -m backend.app.migrate
Each new version that needs more than a seed adds its function to STEPS.
"""

from __future__ import annotations

import json
import sys


def _project_db() -> dict:
    from . import projects_db
    projects_db.engine()
    return {"tables": len(projects_db.meta.tables)}


def _seeds() -> dict:
    from . import capacity_db, fea, foundry_design, sheet_compare, tool_components, tool_design, tool_internals, tool_review
    return {"machines_and_bases": capacity_db.extend(), "stage_rules": tool_design.seed(), "fea_parameters": fea.seed(),
            "components": tool_components.seed(), "details": tool_internals.seed(), "review": tool_review.seed(),
            "foundry": foundry_design.seed(), "sheet_compare": sheet_compare.seed()}


def _self_test() -> dict:
    from fastapi.testclient import TestClient
    from . import costing_setup, master_data, mould_db
    from .main import app
    c = TestClient(app)
    r = c.get("/api/version")
    assert r.status_code == 200, r.text
    mould_db.SET.validate(mould_db.tables())             # every master-data row and formula is checked, nothing is written
    costing_setup.SET.validate(costing_setup.tables())
    master_data.tables()
    return {"version": r.json()["version"]}


STEPS = [("project database", _project_db), ("master data", _seeds), ("self-test", _self_test)]


def run() -> dict:
    out = {}
    for name, fn in STEPS:
        out[name] = fn()
    return out


def main() -> int:
    try:
        print(json.dumps(run(), indent=1, default=str))
        return 0
    except Exception as exc:
        print(f"MIGRATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
