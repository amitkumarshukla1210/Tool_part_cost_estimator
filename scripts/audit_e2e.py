"""End-to-end audit of the whole tool, as a user would go: upload the 3D file, register the part, RM cost, tool cost,
simulation, tool design and drawings, machine, process parameters, part cost, country comparison, PO pack, project
dashboard and leader view, exports, logins. Every tool group at low and high volume, plus large parts.

    python scripts/audit_e2e.py                 # report to docs/audit_e2e_report.md
    python scripts/audit_e2e.py --only plastic  # cases whose name contains 'plastic'

Runs on temporary copies of the master data and an empty project database (your data is never touched).
A finding is: a server error, a file that does not open (PDF, Excel, DXF, STEP, ZIP), a cost that is zero / negative / NaN,
an answer slower than SLOW seconds, or "not applicable" (400) where the feature should apply.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / "samples"
SLOW = 60.0

# name, file, material, process, annual volume (None = default), expected part type
CASES = [
    ("plastic_low", "plastic_cover.step", "ABS", "injection_moulding", 20000, "plastic"),
    ("plastic_high", "plastic_cover.step", "PP (polypropylene)", "injection_moulding", 3000000, "plastic"),
    ("plastic_large", "large_plastic_tub.step", "PP (polypropylene)", "injection_moulding", 50000, "plastic"),
    ("insert_moulding", "insert_moulded_housing.step", "PA66 GF30", "insert_moulding", 100000, "plastic"),
    ("diecast_low", "plastic_cover.step", "Aluminium ADC12 / A383", "die_casting", 10000, "die_casting"),
    ("diecast_high", "plastic_cover.step", "Aluminium A380", "die_casting", 1000000, "die_casting"),
    ("foundry", "plastic_cover.step", "Grey cast iron FG260", "foundry", 20000, "foundry"),
    ("sheet_multistage", "example_bracket_revA.step", "Galvanised steel GI", "sheet_metal_multistage", 20000, "sheet_metal"),
    ("sheet_progressive_high", "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_progressive", 2000000, "sheet_metal"),
    ("sheet_drawn_large", "large_sheet_tray.step", "CRCA D513 EDD (deep drawing)", "sheet_metal_multistage", 50000, "sheet_metal"),
    ("sheet_channel_large", "large_sheet_channel.step", "Mild steel CRCA / HR", "sheet_metal_multistage", 30000, "sheet_metal"),
    ("eps", "plastic_cover.step", "EPS bead grade S (20 kg/m3)", "eps_moulding", 100000, "eps"),
    ("blow", "pet_bottle.step", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", 5000000, "blow"),
    ("machined", "plate_with_hole.step", "Mild steel CRCA / HR", "machined", 5000, ""),
]
TOOL_TYPES = ("plastic", "die_casting", "foundry", "sheet_metal", "eps", "blow")
MOULD_TYPES = ("plastic", "die_casting", "eps", "blow", "foundry")


def _env(tmp: Path) -> None:
    from backend.app import costing_db, master_data
    shutil.copy(master_data.DEFAULT_PATH, tmp / "master_data.xlsx")
    shutil.copy(costing_db.DEFAULT_PATH, tmp / "costing_db.sqlite")
    os.environ.update({"MASTER_DATA_PATH": str(tmp / "master_data.xlsx"), "COSTING_DB_PATH": str(tmp / "costing_db.sqlite"),
                       "DATABASE_URL": f"sqlite:///{tmp / 'projects.sqlite'}", "DTC_STORAGE_FOLDER": str(tmp / "storage"),
                       "DTC_BACKUP_FOLDER": str(tmp / "backups"), "DTC_MODE": "local"})


def _bad_numbers(obj, path="") -> list[str]:
    out = []
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        out.append(path or "value")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _bad_numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:200]):
            out += _bad_numbers(v, f"{path}[{i}]")
    return out


def _check_file(kind: str, content: bytes) -> str | None:
    """None if the file opens, else what is wrong."""
    try:
        if kind == "pdf":
            from pypdf import PdfReader
            if not content.startswith(b"%PDF") or not PdfReader(io.BytesIO(content)).pages:
                return "PDF does not open"
        elif kind == "xlsx":
            from openpyxl import load_workbook
            load_workbook(io.BytesIO(content))
        elif kind == "dxf":
            import ezdxf
            ezdxf.read(io.StringIO(content.decode("utf-8", "replace")))
        elif kind == "step":
            if not content.startswith(b"ISO-10303-21"):
                return "STEP header missing"
        elif kind == "zip":
            z = zipfile.ZipFile(io.BytesIO(content))
            bad = z.testzip()
            if bad:
                return f"ZIP member {bad} is corrupt"
            for n in z.namelist():
                ext = n.rsplit(".", 1)[-1].lower()
                if ext in ("pdf", "xlsx", "dxf", "step"):
                    why = _check_file(ext, z.read(n))
                    if why:
                        return f"{n}: {why}"
        elif kind == "png":
            if not content.startswith(b"\x89PNG"):
                return "PNG header missing"
        elif kind in ("mp4", "gif"):
            if len(content) < 1000:
                return "video too small"
    except Exception as exc:                                    # noqa: BLE001
        return f"{kind} does not open: {exc}"
    return None


class Audit:
    def __init__(self, client):
        self.c = client
        self.rows: list[dict] = []          # every call
        self.findings: list[dict] = []

    def call(self, case: str, method: str, url: str, expect: str = "ok", file_kind: str | None = None, **kw):
        """expect: ok (must be 200), any (200 or a 400 with a message), na (400 expected)."""
        t0 = time.time()
        try:
            r = getattr(self.c, method)(url, **kw)
            dt = time.time() - t0
            status, body = r.status_code, r
        except Exception:                                       # noqa: BLE001  (server error raised by the test client)
            dt = time.time() - t0
            self._find(case, url, "server error (exception)", traceback.format_exc().strip().splitlines()[-1])
            self.rows.append({"case": case, "url": url, "status": "EXC", "s": round(dt, 1)})
            return None
        self.rows.append({"case": case, "url": url, "status": status, "s": round(dt, 1)})
        if dt > SLOW:
            self._find(case, url, "slow", f"{dt:.0f} s")
        if status >= 500:
            self._find(case, url, f"HTTP {status}", r.text[:300])
            return None
        if status != 200:
            msg = ""
            try:
                msg = r.json().get("detail", "")
            except Exception:                                   # noqa: BLE001
                msg = r.text[:200]
            if expect == "ok":
                self._find(case, url, f"HTTP {status} where it should work", str(msg)[:300])
            elif not msg:
                self._find(case, url, f"HTTP {status} without a message", "")
            return None
        if expect == "na":
            self._find(case, url, "works where 'not applicable' was expected", "")
        if file_kind:
            why = _check_file(file_kind, body.content)
            if why:
                self._find(case, url, "broken file", why)
        elif "json" in (r.headers.get("content-type") or ""):
            data = r.json()
            bad = _bad_numbers(data)
            if bad:
                self._find(case, url, "NaN / infinite number", ", ".join(bad[:5]))
            return data
        return body

    def _find(self, case, url, what, detail):
        self.findings.append({"case": case, "url": url, "what": what, "detail": detail})


def _positive(audit, case, label, value):
    if value is None or not isinstance(value, (int, float)) or value <= 0 or math.isnan(value):
        audit._find(case, label, "cost missing / not positive", repr(value))


def run_case(a: Audit, name, file, material, process, volume, ptype) -> dict:
    c = a.c
    proj = c.post("/api/projects", json={"code": name.upper().replace("_", "-")[:18], "name": f"Audit {name}"}).json()
    with open(SAMPLES / file, "rb") as fh:
        m = a.call(name, "post", "/api/import/step", files={"file": (file, fh)})
    if not m:
        return {"case": name, "ok": False}
    code = f"{name.upper().replace('_', '-')[:14]}-1"
    r = a.call(name, "post", f"/api/import/{m['token']}/commit",
               json={"project_id": proj["id"], "items": {m["root"]: {"material": material, "process": process, "part_code": code}}})
    if not r:
        return {"case": name, "ok": False}
    pid = r["part_ids"][0]
    if volume:
        a.call(name, "put", f"/api/parts/{pid}", json={"annual_volume": volume})
    tool = ptype in TOOL_TYPES
    mould = ptype in MOULD_TYPES
    sheet = ptype == "sheet_metal"
    P = f"/api/parts/{pid}"
    out = {"case": name, "part_id": pid, "ok": True}
    d = a.call(name, "get", P)
    a.call(name, "get", f"{P}/trace")
    rm = a.call(name, "post", f"{P}/rm-cost", json={})
    a.call(name, "get", f"{P}/rm-cost/trace")
    a.call(name, "get", f"{P}/rm-cost/export.xlsx", file_kind="xlsx")
    a.call(name, "get", f"{P}/rm-cost/export.pdf", file_kind="pdf")
    a.call(name, "get", f"{P}/concept", expect="ok" if mould else "any")
    a.call(name, "get", f"{P}/design-loop")
    tc = a.call(name, "post", f"{P}/tool-cost", json={}, expect="ok" if tool else "any")
    a.call(name, "get", f"{P}/tool-cost/trace", expect="ok" if tool else "any")
    a.call(name, "get", f"{P}/tool-cost/export.xlsx", expect="ok" if tool else "any", file_kind="xlsx")
    a.call(name, "get", f"{P}/tool-cost/export.pdf", expect="ok" if tool else "any", file_kind="pdf")
    sim = a.call(name, "get", f"{P}/simulation", expect="ok" if mould else "any")
    if mould:
        a.call(name, "get", f"{P}/simulation/report.pdf", file_kind="pdf")
    if sheet:
        a.call(name, "get", f"{P}/sheet-tools")
        a.call(name, "get", f"{P}/sheet-layout")
        for k, fk in (("blank.dxf", "dxf"), ("strip.dxf", "dxf"), ("tool-pack.pdf", "pdf")):
            a.call(name, "get", f"{P}/sheet-layout/{k}", file_kind=fk)
        a.call(name, "get", f"{P}/forming-simulation.pdf", file_kind="pdf")
    else:
        a.call(name, "get", f"{P}/sheet-tools", expect="any")
    a.call(name, "get", f"{P}/correction", expect="any")
    pc = a.call(name, "post", f"{P}/piece-cost", json={}, expect="ok" if ptype else "any")
    stored = a.call(name, "get", P) or {}
    out["rm_inr"], out["tool_inr"], out["piece_inr"] = stored.get("rm_cost_inr"), stored.get("tool_capex_inr"), stored.get("piece_cost_inr")
    if ptype:
        _positive(a, name, "RM cost", out["rm_inr"])
        _positive(a, name, "part cost", out["piece_inr"])
        if out["rm_inr"] and out["piece_inr"] and out["piece_inr"] < out["rm_inr"]:
            a._find(name, "part cost", "part cost below its RM cost", f"{out['piece_inr']:.2f} < {out['rm_inr']:.2f}")
    if tool:
        _positive(a, name, "tool cost", out["tool_inr"])
    a.call(name, "get", f"{P}/piece-cost/trace", expect="ok" if ptype else "any")
    a.call(name, "get", f"{P}/piece-cost/export.xlsx", expect="ok" if ptype else "any", file_kind="xlsx")
    a.call(name, "get", f"{P}/piece-cost/export.pdf", expect="ok" if ptype else "any", file_kind="pdf")
    a.call(name, "get", f"{P}/drawing.pdf", file_kind="pdf")
    a.call(name, "get", f"{P}/drawing.dxf", file_kind="dxf")
    if tool:
        a.call(name, "get", f"{P}/tool-drawing.pdf", file_kind="pdf")
        a.call(name, "get", f"{P}/tool-drawing.dxf", file_kind="dxf")
        a.call(name, "get", f"{P}/po-pack.zip", file_kind="zip")
        # detailed tool design, stage 27 + 30-34
        a.call(name, "get", f"{P}/machine")
        a.call(name, "put", f"{P}/machine", json={"spec": None, "skipped": True})
        td = a.call(name, "get", f"{P}/tool-design")
        if td:
            out["tools"] = len(td["tools"])
            for t in td["tools"][:2]:
                q = {"die": t["key"]} if (len(td["tools"]) > 1 or t["key"] != "mould") else {}
                a.call(name, "get", f"{P}/tool-design.pdf", params=q, file_kind="pdf")
                a.call(name, "get", f"{P}/tool-design.step", params=q, file_kind="step")
                a.call(name, "get", f"{P}/tool-design.png", params=q, file_kind="png")
            a.call(name, "get", f"{P}/tool-design.zip", file_kind="zip")
        mc = a.call(name, "get", f"{P}/machine-check")
        if mc and td and mc["recommended"]["values"].get("tonnage_t") is not None:
            if mc["recommended"]["values"]["tonnage_t"] < max(t["force_t"] for t in mc["tools"]):
                a._find(name, "machine-check", "recommended tonnage below the tool force", "")
        dd = a.call(name, "get", f"{P}/drawing-data")
        if dd:
            a.call(name, "get", f"{P}/drawing-data.xlsx", file_kind="xlsx")
            item = next((i for t in dd["tools"] for i in t["items"]), None)
            if item:
                if not item["dimensions"]:
                    a._find(name, "drawing-data", "made part without dimension tolerances", item["name"])
                a.call(name, "put", f"{P}/drawing-data", json={"items": [{"tool": dd["tools"][0]["key"], "item": item["item"],
                       "fields": {"surface_treatment": "audit"}, "notes": ["audit note"]}]})
        a.call(name, "get", f"{P}/process-parameters")
        a.call(name, "get", f"{P}/process-parameters.xlsx", file_kind="xlsx")
        a.call(name, "get", f"{P}/process-parameters.pdf", file_kind="pdf")
    else:
        a.call(name, "get", f"{P}/tool-design", expect="any")
        a.call(name, "get", f"{P}/machine", expect="any")
        a.call(name, "get", f"{P}/process-parameters", expect="any")
    a.call(name, "get", f"{P}/country-comparison", expect="ok" if ptype else "any")
    a.call(name, "get", f"{P}/country-comparison/export.xlsx", expect="ok" if ptype else "any", file_kind="xlsx")
    a.call(name, "get", f"{P}/country-comparison/export.pdf", expect="ok" if ptype else "any", file_kind="pdf")
    a.call(name, "get", f"{P}/suppliers")
    # project level
    J = f"/api/projects/{proj['id']}"
    a.call(name, "post", f"{J}/piece-cost/recalculate", json={})
    a.call(name, "post", f"{J}/capex/build", json={})
    dash = a.call(name, "get", f"{J}/dashboard")
    a.call(name, "get", f"{J}/dashboard.pdf", file_kind="pdf")
    lead = a.call(name, "get", f"{J}/leader")
    a.call(name, "get", f"{J}/leader.xlsx", file_kind="xlsx")
    a.call(name, "get", f"{J}/leader.pdf", file_kind="pdf")
    if tool and out.get("tool_inr") and lead:
        out["leader"] = {k: lead.get(k) for k in ("tool_capex_inr", "capex_total_inr") if k in lead}
    return out


def logins(a: Audit) -> None:
    """Roles and tool groups with logins on (stages 22 and 30)."""
    from fastapi.testclient import TestClient
    from backend.app.main import app
    os.environ["DTC_MODE"] = "server"
    os.environ["DTC_ADMIN_PASSWORD"] = "correct horse battery"
    try:
        with TestClient(app) as s:
            aud = Audit(s)
            ok = s.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery"}).status_code == 200
            if not ok:
                a._find("logins", "/api/auth/login", "admin cannot log in", "")
                return
            for u, role, groups in (("eng", "engineer", ["sheet_metal"]), ("boss", "head", []), ("viewer1", "viewer", [])):
                aud.call("logins", "post", "/api/users", json={"username": u, "password": "correct horse battery", "role": role, "groups": groups})
            parts = s.get("/api/parts", params={"limit": 500}).json()["rows"]
            plastic = next((p for p in parts if p["process"] == "injection_moulding"), None)
            sheetp = next((p for p in parts if p["process"].startswith("sheet_metal")), None)
            s.post("/api/auth/logout")
            s.post("/api/auth/login", json={"username": "eng", "password": "correct horse battery"})
            seen = {p["process"] for p in s.get("/api/parts", params={"limit": 500}).json()["rows"]}
            if seen - {"sheet_metal_multistage", "sheet_metal_progressive", "machined", "bought_out", "assembly", ""}:
                a._find("logins", "/api/parts", "engineer sees parts outside the tool group", ", ".join(sorted(seen)))
            if plastic and s.get(f"/api/parts/{plastic['id']}").status_code != 403:
                a._find("logins", f"/api/parts/{plastic['id']}", "engineer opens another group's part", "")
            if sheetp and s.get(f"/api/parts/{sheetp['id']}/tool-cost").status_code not in (200,):
                a._find("logins", f"/api/parts/{sheetp['id']}/tool-cost", "engineer cannot open own group's part", "")
            if s.get("/api/users").status_code != 403:
                a._find("logins", "/api/users", "engineer can manage users", "")
            s.post("/api/auth/logout")
            s.post("/api/auth/login", json={"username": "viewer1", "password": "correct horse battery"})
            if s.post("/api/projects", json={"code": "VW", "name": "x"}).status_code != 403:
                a._find("logins", "/api/projects", "viewer can create a project", "")
            s.post("/api/auth/logout")
            s.post("/api/auth/login", json={"username": "boss", "password": "correct horse battery"})
            if plastic and s.get(f"/api/parts/{plastic['id']}").status_code != 200:
                a._find("logins", f"/api/parts/{plastic['id']}", "head of department cannot open a part", "")
            a.rows += aud.rows
            a.findings += aud.findings
    finally:
        os.environ["DTC_MODE"] = "local"


def global_checks(a: Audit) -> None:
    for url, kind in (("/api/parts/export.xlsx", "xlsx"), ("/api/examples/export.xlsx", "xlsx"), ("/api/admin/activity.xlsx", "xlsx"),
                      ("/api/suppliers/export.xlsx", "xlsx"), ("/api/master-data/download", "xlsx"), ("/api/mould-db/download", "xlsx"),
                      ("/api/costing-setup/download", "xlsx"), ("/api/rates/download", "xlsx"), ("/api/register-setup/download", "xlsx"),
                      ("/api/price-master/export.xlsx", "xlsx"), ("/api/import/template.xlsx", "xlsx")):
        a.call("global", "get", url, file_kind=kind)
    for url in ("/api/examples", "/api/rates/grid", "/api/price-master/grid", "/api/mhr", "/api/admin/about", "/api/admin/backups",
                "/api/register-meta", "/api/tool-bom/choices", "/api/mould-db", "/api/master-data"):
        a.call("global", "get", url)
    b = a.call("global", "post", "/api/admin/backups", json={})
    # round trip of the master data: download and upload again unchanged must work
    for down, up in (("/api/mould-db/download", "/api/mould-db/upload"), ("/api/master-data/download", "/api/master-data/upload")):
        content = a.c.get(down).content
        a.call("global", "post", up, files={"file": ("x.xlsx", content)})


def report(a: Audit, results: list[dict], out: Path, seconds: float) -> None:
    lines = ["# End-to-end audit report", "", f"Run on the current code, {time.strftime('%Y-%m-%d %H:%M')}, {len(a.rows)} calls in {seconds / 60:.1f} min.", ""]
    lines += ["| Case | Part type | Tools | RM INR | Tool CAPEX INR | Part cost INR | Findings |", "|---|---|---|---|---|---|---|"]
    types = {c[0]: c[5] for c in CASES}
    for r in results:
        case = (r["case"], 0, 0, 0, 0, types.get(r["case"], ""))
        f = [x for x in a.findings if x["case"] == r["case"]]
        fmt = lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) else "-"
        lines.append(f"| {r['case']} | {case[5] or '-'} | {r.get('tools', '-')} | {fmt(r.get('rm_inr'))} | {fmt(r.get('tool_inr'))} | {fmt(r.get('piece_inr'))} | {len(f) or 'none'} |")
    lines += ["", f"## Findings ({len(a.findings)})", ""]
    if not a.findings:
        lines.append("None.")
    for x in a.findings:
        lines.append(f"- **{x['case']}** `{x['url']}`: {x['what']}" + (f" - {x['detail']}" if x["detail"] else ""))
    slow = sorted((r for r in a.rows if isinstance(r["s"], float) and r["s"] > 10), key=lambda r: -r["s"])[:15]
    lines += ["", "## Slowest calls", ""] + [f"- {r['s']:.0f} s {r['case']} `{r['url']}`" for r in slow]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "audit_e2e_report.md"))
    ap.add_argument("--only", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="dtc_audit_"))
    _env(tmp)
    from fastapi.testclient import TestClient
    from backend.app.main import app
    a = Audit(TestClient(app))
    t0 = time.time()
    results = []
    for case in CASES:
        if args.only and args.only not in case[0]:
            continue
        print(f"== {case[0]}", flush=True)
        try:
            results.append(run_case(a, *case))
        except Exception:                                       # noqa: BLE001
            a._find(case[0], "(script)", "audit step crashed", traceback.format_exc().strip().splitlines()[-1])
            results.append({"case": case[0]})
        for x in a.findings:
            if x["case"] == case[0]:
                print(f"   FINDING {x['url']}: {x['what']} {x['detail'][:200]}", flush=True)
    if not args.only:
        print("== global", flush=True)
        global_checks(a)
        print("== logins", flush=True)
        logins(a)
    report(a, results, Path(args.out), time.time() - t0)
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": a.rows, "findings": a.findings, "results": results}, indent=1, default=str))
    print(f"{len(a.findings)} finding(s); report: {args.out}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
