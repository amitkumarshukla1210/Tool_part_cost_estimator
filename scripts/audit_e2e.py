"""End-to-end audit of every tool group at a low and a high capacity: upload 3D → part → costs → design pack → tool design → review →
release → purchase orders → drawings, BOM and supplier ZIP, all downloaded and opened again to prove they are usable.

    python scripts/audit_e2e.py                    # all cases (about 15 min), report in docs/audit_e2e_report.md
    python scripts/audit_e2e.py --only plastic     # cases whose name contains "plastic"
    python scripts/audit_e2e.py --no-pack          # skip the design pack (simulation video) to be faster

Works on a temporary copy of the master data and an empty temporary database: nothing of yours is touched.
"""

from __future__ import annotations

import argparse
import io
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

CASES = [  # name, sample, material, process, group, capacity
    ("plastic_low", "plastic_small", "ABS", "injection_moulding", "plastic", "low"),
    ("plastic_high", "plastic_large", "PP (polypropylene)", "injection_moulding", "plastic", "high"),
    ("diecast_low", "diecast_small", "Aluminium ADC12 / A383", "die_casting", "die casting", "low"),
    ("diecast_high", "diecast_large", "Aluminium ADC12 / A383", "die_casting", "die casting", "high"),
    ("foundry_low", "foundry_small", "Grey cast iron FG260", "foundry", "foundry", "low"),
    ("foundry_high", "foundry_large", "Grey cast iron FG260", "foundry", "foundry", "high"),
    ("sheet_progressive_low", "sheet_small", "Mild steel CRCA / HR", "sheet_metal_progressive", "sheet metal progressive", "low"),
    ("sheet_stage_low", "sheet_small", "Mild steel CRCA / HR", "sheet_metal_multistage", "sheet metal stage", "low"),
    ("sheet_progressive_high", "sheet_large", "Mild steel CRCA / HR", "sheet_metal_progressive", "sheet metal progressive", "high"),
    ("sheet_stage_high", "sheet_large", "Mild steel CRCA / HR", "sheet_metal_multistage", "sheet metal stage", "high"),
    ("eps_low", "eps_small", "EPS bead grade S (20 kg/m3)", "eps_moulding", "EPS", "low"),
    ("eps_high", "eps_large", "EPS bead grade S (20 kg/m3)", "eps_moulding", "EPS", "high"),
    ("blow_low", "blow_small", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "blow", "low"),
    ("blow_high", "blow_large", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "blow", "high"),
]


class Audit:
    def __init__(self, name, group, capacity):
        self.name, self.group, self.capacity = name, group, capacity
        self.steps, self.facts, self.t0 = [], {}, time.time()

    def step(self, label, fn):
        t = time.time()
        try:
            detail = fn()
            self.steps.append((label, True, str(detail or "")[:200], round(time.time() - t, 1)))
            return detail
        except Exception as exc:                       # an audit records the failure and goes on
            self.steps.append((label, False, f"{type(exc).__name__}: {str(exc)[:240]}", round(time.time() - t, 1)))
            self.last_tb = traceback.format_exc()
            return None

    @property
    def ok(self):
        return all(s[1] for s in self.steps)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def run_case(client, case, pack=True) -> Audit:
    name, sample, material, process, group, capacity = case
    a = Audit(name, group, capacity)
    proj = client.post("/api/projects", json={"code": "AUD-" + name.upper(), "name": f"Audit {name}"}).json()
    path = ROOT / "samples" / "audit" / f"{sample}.step"

    def upload():
        with open(path, "rb") as fh:
            m = client.post("/api/import/step", files={"file": (path.name, fh)})
        expect(m.status_code == 200, m.text[:200])
        m = m.json()
        r = client.post(f"/api/import/{m['token']}/commit", json={"project_id": proj["id"], "items": {m["root"]: {"material": material, "process": process, "part_code": name.upper()[:24]}}})
        expect(r.status_code == 200, r.text[:200])
        return r.json()["part_ids"][0]
    pid = a.step("1 Upload 3D drawing and register the part", upload)
    if not pid:
        return a
    a.facts["part_id"] = pid
    d = client.get(f"/api/parts/{pid}").json()
    a.step("2 Part has a 3D file, revision A and geometry", lambda: expect(d["revisions"] and d["revisions"][0]["geometry"].get("volume_cm3"), "no geometry") or
           f"{d['revisions'][0]['geometry']['volume_cm3']:.0f} cm³, bbox {d['revisions'][0]['geometry'].get('bbox_mm')}")

    def rm():
        r = client.post(f"/api/parts/{pid}/rm-cost", json={})
        expect(r.status_code == 200, r.text[:200])
        j = r.json()
        return f"RM cost INR {j.get('net_rm_cost') or j.get('value')}"
    a.step("3 Raw-material cost", rm)

    if group not in ("foundry", "sheet metal progressive", "sheet metal stage"):
        def tool():
            r = client.post(f"/api/parts/{pid}/tool-cost", json={})
            expect(r.status_code == 200, r.text[:200])
            j = r.json()
            a.facts["tool_cost_inr"] = round(j.get("tool_cost_inr") or j.get("value_inr") or 0)
            return f"tool cost INR {a.facts['tool_cost_inr']:,}, cavities {j.get('cavities')}"
        a.step("4 Tool and mould cost (BOM costed)", tool)

    if pack and group not in ("foundry", "EPS", "blow"):          # the design pack (simulation, corrected drawing, PPT) covers plastic, die casting and sheet metal
        def dp():
            t = time.time()
            r = client.get(f"/api/parts/{pid}/design-pack.zip?video=none")
            expect(r.status_code == 200, r.text[:200])
            z = zipfile.ZipFile(io.BytesIO(r.content))
            names = z.namelist()
            kinds = {k: any(n.endswith(k) for n in names) for k in (".xlsx", ".pdf", ".pptx", ".step", ".dxf", "_3d_report.html")}
            expect(all(kinds.values()), f"missing {[k for k, v in kinds.items() if not v]}")
            return f"{len(names)} files, {time.time() - t:.0f} s"
        a.step("5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP", dp)

    def gen():
        r = client.post(f"/api/parts/{pid}/tool-designs", json={})
        expect(r.status_code == 200, r.text[:300])
        return r.json()
    des = a.step("6 Generate the production tool design", gen)
    if not des:
        return a
    did = des["id"]
    base = f"/api/tool-designs/{did}"
    made = [c for c in des["components"] if c["kind"] == "made"]
    std = [c for c in des["components"] if c["kind"] == "standard"]
    a.facts |= {"kind": des["kind"], "components": len(des["components"]), "made": len(made), "standard_3d": len(std), "bom_bought_out": len(des["bill"]["standard"]),
                "steel_kg": des["bill"]["totals"]["steel_kg"], "assembly_h": des["bill"]["totals"]["assembly_hours"], "force_t": des["summary"].get("total_force_t"),
                "presses": ", ".join(sorted({p for p in (des["summary"].get("presses") or []) if p})) or "-"}
    a.step("7 Tool design: no overlaps, valid solids", lambda: expect(des["summary"]["checks"]["errors"] == 0, f"{des['summary']['checks']['errors']} errors: " +
           "; ".join(i["text"] for i in des["summary"]["checks"]["issues"][:3])) or f"{len(made)} made parts, {len(std)} standard 3D parts")
    a.step("8 BOM: made parts with stock, weight, machining; bought-out list", lambda: expect(
        des["bill"]["totals"]["made_parts"] >= 3 and des["bill"]["totals"]["steel_kg"] > 0 and des["bill"]["standard"], "BOM incomplete") or
        f"{des['bill']['totals']['made_parts']} part numbers, {len(des['bill']['standard'])} bought-out lines, {des['bill']['totals']['steel_kg']} kg steel")

    def drawings():
        seen, n = set(), 0
        for c in made:
            if c["part_no"] in seen:
                continue
            seen.add(c["part_no"])
            pdf = client.get(f"{base}/components/{c['id']}/drawing.pdf")
            expect(pdf.status_code == 200 and pdf.content[:4] == b"%PDF", f"drawing {c['part_no']}: {pdf.status_code}")
            dxf = client.get(f"{base}/components/{c['id']}/drawing.dxf")
            expect(dxf.status_code == 200 and b"SECTION" in dxf.content[:400], f"dxf {c['part_no']}")
            step = client.get(f"{base}/components/{c['id']}/step")
            expect(step.status_code == 200 and b"ISO-10303" in step.content[:200], f"step {c['part_no']}")
            n += 1
        return f"{n} part numbers: PDF + DXF + STEP each"
    a.step("9 Tool part drawings (PDF, DXF) and STEP of every made part", drawings)

    def step_valid():
        import cadquery as cq
        c = made[0]
        raw = client.get(f"{base}/components/{c['id']}/step").content
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
            f.write(raw)
        shp = cq.importers.importStep(f.name).val()
        os.unlink(f.name)
        expect(shp.isValid() and shp.Volume() > 0, "STEP does not re-import as a valid solid")
        return f"{c['part_no']} re-imports, {shp.Volume() / 1000:.0f} cm³"
    a.step("10 Downloaded STEP opens again as a valid solid", step_valid)

    def machine():
        m = des["summary"].get("machine")
        expect(m and m["source"] == "recommended" and m["recommended"] and m["fit_ok"] == -1, "no recommended machine in the design")
        key = next(k for k in m["recommended"] if "tonnage" in k or "flask" in k)
        return f"machine not typed: the tool needs {key} = {m['recommended'][key]:g}" + (f"; closest {m['nearest_machine']['name']}" if m.get("nearest_machine") else "")
    a.step("10b Machine: recommended parameters of the finished tool", machine)

    def process():
        r = client.get(f"/api/parts/{pid}/process-parameters")
        expect(r.status_code == 200 and r.json()["parameters"], r.text[:200])
        j = r.json()
        return f"{len(j['parameters'])} settings, {len(j['risks'])} quality warning(s)"
    a.step("10c Process parameters for the best part quality", process)

    def mesh():
        m = client.get(f"{base}/mesh").json()
        expect(len(m["components"]) == len(des["components"]), "mesh components differ")
        return f"{len(m['components'])} components for the 3D viewer"
    a.step("11 3D viewer data (measure / view)", mesh)

    def correction():
        c = made[0]
        raw = client.get(f"{base}/components/{c['id']}/step").content
        r = client.post(f"{base}/components/{c['id']}/upload", files={"file": ("x.step", raw)}, data={"note": "audit: unchanged re-upload"})
        expect(r.status_code == 200, r.text[:200])
        return f"revision {r.json().get('rev') or r.json().get('component', {}).get('rev', '?')} after upload, recalculated"
    a.step("12 Correct a component by STEP upload (round trip)", correction)

    def review():
        d2 = client.get(base).json()
        for it in d2["review"]:
            if it["blocking"] and it["status"] not in ("ok", "na", "waived"):
                body = {"status": "ok", "comment": ""} if it["kind"] == "manual" else {"status": "waived", "comment": "audit: accepted"}
                r = client.post(f"{base}/review/{it['id']}", json=body)
                expect(r.status_code == 200, r.text[:200])
        return f"{len(d2['review'])} review items signed"
    a.step("13 Toolmaker review signed", review)
    def release():
        r = client.post(f"{base}/release", json={})
        if r.status_code != 200:
            iss = client.get(base).json()["summary"]["checks"]["issues"]
            expect(False, f"not released: {r.text[:120]} " + "; ".join(i["text"] for i in iss[:3]))
        expect(r.json().get("status") == "released", "not released")
        return "released"
    a.step("14 Release the design (drawing revision A)", release)

    def po():
        wb_r = client.get(f"{base}/files/xlsx")
        expect(wb_r.status_code == 200, "xlsx")
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(wb_r.content))
        expect({"BOM", "PO-1 Raw material", "PO-2 Machining", "PO-3 Bought-out", "Assembly"} <= set(wb.sheetnames), f"sheets {wb.sheetnames}")
        expect("Design to Cost" in [wb.worksheets[0].cell(r, 2).value for r in (1, 2)], "no logo / name on the Excel")
        rows = [r for r in wb["PO-1 Raw material"].iter_rows(values_only=True) if r and r[1] and str(r[1]).startswith(des["summary"]["part_code"])]
        expect(rows, "PO-1 has no part rows")
        from pypdf import PdfReader
        for kind in ("po-material", "po-machining", "po-bought-out", "assembly-pdf"):
            r = client.get(f"{base}/files/{kind}")
            expect(r.status_code == 200 and r.content[:4] == b"%PDF", f"{kind} not a PDF")
            expect("Design to Cost" in (PdfReader(io.BytesIO(r.content)).pages[0].extract_text() or ""), f"{kind}: no name")
        return f"workbook {len(wb.sheetnames)} sheets, PO-1 {len(rows)} lines, 3 PO PDFs + assembly sheet"
    a.step("15 Purchase orders: raw material, machining, bought-out (Excel + PDF)", po)

    def zipcheck():
        r = client.get(f"{base}/supplier-package.zip")
        expect(r.status_code == 200, r.text[:200])
        z = zipfile.ZipFile(io.BytesIO(r.content))
        n = z.namelist()
        n_made = len({c["part_no"] for c in made})
        expect(sum(x.startswith("step/") for x in n) == n_made and sum(x.startswith("drawings/") for x in n) == n_made, f"zip has {sum(x.startswith('step/') for x in n)} STEP for {n_made} parts")
        expect(any(x.startswith("po/") and x.endswith(".xlsx") for x in n) and any(x.startswith("assembly/") for x in n), "zip lacks PO / assembly")
        return f"{len(n)} files, {len(r.content) // 1024} KB"
    a.step("16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly)", zipcheck)

    if group.startswith("sheet metal"):
        def cmp_():
            r = client.post(f"/api/parts/{pid}/sheet-compare")
            expect(r.status_code == 200, r.text[:240])
            j = r.json()
            z = client.get(f"/api/parts/{pid}/sheet-compare/package.zip")
            expect(z.status_code == 200 and len(z.content) > 5000, "package")
            return f"{j['verdict']['label']} cheaper by INR {j['verdict']['saving_per_part']}; package {len(z.content) // 1024} KB"
        a.step("17 Progressive vs stage comparison and package", cmp_)
    a.facts["seconds"] = round(time.time() - a.t0)
    return a


def report(audits: list[Audit]) -> str:
    n_ok = sum(a.ok for a in audits)
    L = ["# End-to-end audit: every tool group, low and high capacity", "",
         f"Run on {time.strftime('%Y-%m-%d')} with `python scripts/audit_e2e.py` (sample parts in `samples/audit/`, made by `samples/make_audit_samples.py`).",
         "Each case goes from 3D upload to the supplier ZIP; every file is downloaded and opened again. Example rates and rules are still EXAMPLE values.", "",
         f"**{n_ok} of {len(audits)} cases passed all steps.**", "", "| Case | Group | Capacity | Result | Made parts | 3D standard parts | Force (t) | Press / base | Steel (kg) | Seconds |", "|---|---|---|---|---|---|---|---|---|---|"]
    for a in audits:
        f = a.facts
        L.append(f"| {a.name} | {a.group} | {a.capacity} | {'PASS' if a.ok else 'FAIL'} | {f.get('made', '')} | {f.get('standard_3d', '')} | {f.get('force_t', '') or ''} | {f.get('presses', '')} | {f.get('steel_kg', '')} | {f.get('seconds', '')} |")
    for a in audits:
        L += ["", f"## {a.name} ({a.group}, {a.capacity} capacity): {'PASS' if a.ok else 'FAIL'}", "", "| Step | Result | Detail | s |", "|---|---|---|---|"]
        for label, ok, detail, sec in a.steps:
            L.append(f"| {label} | {'ok' if ok else '**FAILED**'} | {detail.replace('|', '/')} | {sec} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-pack", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "audit_e2e_report.md"))
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="dtc_audit_"))
    from backend.app import costing_db, master_data
    shutil.copy(master_data.DEFAULT_PATH, tmp / "master_data.xlsx")
    shutil.copy(costing_db.DEFAULT_PATH, tmp / "costing_db.sqlite")
    os.environ.update({"MASTER_DATA_PATH": str(tmp / "master_data.xlsx"), "COSTING_DB_PATH": str(tmp / "costing_db.sqlite"),
                       "DATABASE_URL": f"sqlite:///{tmp / 'projects.sqlite'}", "DTC_STORAGE_FOLDER": str(tmp / "storage")})
    from fastapi.testclient import TestClient
    from backend.app.main import app
    client = TestClient(app)
    audits = []
    for case in CASES:
        if args.only and args.only not in case[0]:
            continue
        print(f"== {case[0]} …", flush=True)
        a = run_case(client, case, pack=not args.no_pack)
        for label, ok, detail, sec in a.steps:
            print(f"   {'ok  ' if ok else 'FAIL'} {label} ({sec} s) {detail if not ok else ''}", flush=True)
        audits.append(a)
    Path(args.out).write_text(report(audits))
    print(f"report: {args.out}: {sum(a.ok for a in audits)}/{len(audits)} cases passed")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if all(a.ok for a in audits) else 1


if __name__ == "__main__":
    sys.exit(main())
