"""More part-material and tool-steel grades for the Price master (roadmap stage 53).

Each new grade is a SUB material of an existing MAIN material (Master data → Materials → Material type, or Tool materials
→ material type) and starts from an existing reference grade:

    * its Materials / Tool materials row (material type = the main material of the reference unless given),
    * EXAMPLE prices in every country where the reference has an approved price: the same value, source
      "EXAMPLE: same as <reference> until you enter your price" (part RM, scrap value, tool steel),
    * a copy of the reference's flow-simulation, process-window, sheet-metal and machining rows (EXAMPLE), so the
      simulation, process parameters, strip / press and machining engines work with the new grade at once.

Only rows are added (idempotent); existing rows and rates are never changed. Densities are typical datasheet values,
marked EXAMPLE in the notes: check them against your supplier's datasheet.
"""

from __future__ import annotations

from contextlib import closing

from . import master_data, mould_db, rates

NOTE = "EXAMPLE grade (stage 53): density typical, price = reference grade until you enter yours"

# (part type, new grade, reference grade, density g/cm³, main material when not the reference's type)
PART_GRADES = [
    # PP: mineral (CaCO3, = talc filled) and glass filled
    ("plastic", "PP CaCO3 10 % (mineral filled)", "PP (polypropylene)", 0.98, None),
    ("plastic", "PP CaCO3 20 % (mineral / talc filled)", "PP (polypropylene)", 1.05, None),
    ("plastic", "PP CaCO3 30 % (mineral filled)", "PP (polypropylene)", 1.14, None),
    ("plastic", "PP GF 10 % (glass filled)", "PP (polypropylene)", 0.97, None),
    ("plastic", "PP GF 20 % (glass filled)", "PP (polypropylene)", 1.04, None),
    ("plastic", "PP GF 30 % (glass filled)", "PP (polypropylene)", 1.12, None),
    # ABS colours
    ("plastic", "ABS Colour White", "ABS", 1.05, None),
    ("plastic", "ABS Colour Black", "ABS", 1.05, None),
    ("plastic", "ABS Sparkle", "ABS", 1.06, None),
    # GI (IS 277 / EN 10346) drawing qualities
    ("sheet_metal", "GI D (IS 277 GP, DX51D)", "Galvanised steel GI", 7.85, None),
    ("sheet_metal", "GI DD (drawing, DX52D)", "Galvanised steel GI", 7.85, None),
    ("sheet_metal", "GI EDD (deep drawing, DX53D)", "Galvanised steel GI", 7.85, None),
    ("sheet_metal", "GI IF (interstitial free, DX54D / DX56D)", "Galvanised steel GI", 7.85, None),
    # zinc die-casting alloys
    ("die_casting", "Zinc Zamak 2 (ZnAl4Cu3, ZP2)", "Zinc Zamak 3", 6.8, None),
    ("die_casting", "Zinc Zamak 5 (ZnAl4Cu1, ZP5)", "Zinc Zamak 3", 6.7, None),
    ("die_casting", "Zinc Zamak 7 (high purity)", "Zinc Zamak 3", 6.6, None),
    ("die_casting", "Zinc ZA-8 (ZnAl8Cu1)", "Zinc Zamak 3", 6.3, None),
    ("die_casting", "Zinc ZA-12 (ZnAl11Cu1)", "Zinc Zamak 3", 6.0, None),
    ("die_casting", "Zinc ZA-27 (ZnAl27Cu2)", "Zinc Zamak 3", 5.0, None),
    # aluminium die-casting alloys
    ("die_casting", "Aluminium ALDC1 / ADC1 (A413, AlSi12)", "Aluminium ADC12 / A383", 2.66, None),
    ("die_casting", "Aluminium ALDC2 / ADC3 (A360, AlSi10Mg)", "Aluminium ADC12 / A383", 2.63, None),
    ("die_casting", "Aluminium ADC10 (AlSi8Cu3)", "Aluminium ADC12 / A383", 2.74, None),
    ("die_casting", "Aluminium AlSi9Cu3 (EN AC-46000)", "Aluminium ADC12 / A383", 2.75, None),
    ("die_casting", "Aluminium LM2 (AlSi10Cu2)", "Aluminium ADC12 / A383", 2.74, None),
    ("die_casting", "Aluminium LM24 (AlSi8Cu3Fe)", "Aluminium ADC12 / A383", 2.74, None),
    # aluminium gravity / sand casting alloys
    ("foundry", "Aluminium LM4 (AlSi5Cu3)", "Aluminium LM6 / A356", 2.75, None),
    ("foundry", "Aluminium LM25 (AlSi7Mg, A356)", "Aluminium LM6 / A356", 2.68, None),
    ("foundry", "Aluminium AC4C (JIS, AlSi7Mg)", "Aluminium LM6 / A356", 2.68, None),
    # aluminium sheet
    ("sheet_metal", "Aluminium 1100 / 1050 (commercially pure)", "Aluminium 5052", 2.71, None),
    ("sheet_metal", "Aluminium 3003 (Al-Mn)", "Aluminium 5052", 2.73, None),
    ("sheet_metal", "Aluminium 5083 (Al-Mg)", "Aluminium 5052", 2.66, None),
    ("sheet_metal", "Aluminium 6061-T6 sheet", "Aluminium 5052", 2.70, None),
    # aluminium bar
    ("machined", "Aluminium 6082-T6 bar (HE30)", "Aluminium 6061-T6 bar", 2.70, None),
    ("machined", "Aluminium 6063-T6 bar", "Aluminium 6061-T6 bar", 2.69, None),
    ("machined", "Aluminium 7075-T6 bar", "Aluminium 6061-T6 bar", 2.81, None),
    ("machined", "Aluminium 2014-T6 bar (HE15)", "Aluminium 6061-T6 bar", 2.80, None),
    # brass bar and sheet
    ("machined", "Brass CW617N (CuZn40Pb2, forging) bar", "Brass CW614N (free-cutting) bar", 8.43, None),
    ("machined", "Brass CW508L (CuZn37) bar", "Brass CW614N (free-cutting) bar", 8.44, None),
    ("machined", "Brass CW602N (DZR, dezincification resistant) bar", "Brass CW614N (free-cutting) bar", 8.45, None),
    ("machined", "Brass CW712R (naval brass) bar", "Brass CW614N (free-cutting) bar", 8.41, None),
    ("sheet_metal", "Brass CuZn37 (CW508L) sheet", "Brass CW614N (free-cutting) bar", 8.44, "Brass sheet"),
    ("sheet_metal", "Brass CuZn30 (CW505L, cartridge) sheet", "Brass CW614N (free-cutting) bar", 8.53, "Brass sheet"),
    # copper casting alloys
    ("foundry", "Gunmetal LG2 (CC491K, CuSn5Zn5Pb5)", "Bronze", 8.8, None),
    ("foundry", "Brass casting CuZn39Pb1Al-C (CC754S)", "Bronze", 8.4, None),
    ("foundry", "Phosphor bronze PB1 (CuSn10P)", "Bronze", 8.8, None),
]

# (new tool steel, reference, density, hardness, application or None = reference's)
TOOL_GRADES = [
    ("D3 (1.2080)", "D2 (1.2379)", 7.7, "58-62 HRC", None),
    ("O1 (1.2510)", "D2 (1.2379)", 7.8, "57-61 HRC", None),
    ("A2 (1.2363)", "D2 (1.2379)", 7.85, "57-61 HRC", None),
    ("M2 (1.3343) HSS", "D2 (1.2379)", 8.1, "62-65 HRC", None),
    ("DC53 (Daido)", "SKD11 (JIS)", 7.87, "60-63 HRC", None),
    ("1.2767 (45NiCrMo16)", "2738 (1.2738)", 7.85, "50-54 HRC", None),
    ("1.2714 (55NiCrMoV7) die block", "H13 (1.2344)", 7.85, "38-44 HRC", None),
    ("H11 (1.2343)", "1.2343 ESR", 7.8, "44-48 HRC", None),
    ("718H (P20+Ni)", "2738 (1.2738)", 7.85, "33-37 HRC prehardened", None),
    ("1.2085 (stainless pre-hardened)", "1.2316 ESR (stainless)", 7.7, "29-33 HRC pre-hardened", None),
    ("EN31 (100Cr6) punches / guides", "D2 (1.2379)", 7.83, "58-62 HRC", None),
    ("EN24 (34CrNiMo6) plates", "Mould base steel (4140 / 1.7225)", 7.85, "28-32 HRC", None),
]

COPY_TABLES = ("flow_materials", "process_windows", "sheet_materials", "machining_data")
# engine data (flow, sheet, machining rows) from another grade than the price reference
ENGINE_REF = {"Brass CuZn37 (CW508L) sheet": "Copper", "Brass CuZn30 (CW505L, cartridge) sheet": "Copper"}


def _approved(cat: str, item: str) -> list[dict]:
    """Latest approved version of a rate in every country."""
    with closing(rates._connect()) as con:
        rows = con.execute("SELECT * FROM rates WHERE category = ? AND item = ? AND status = 'approved' "
                           "ORDER BY country, month, approved_date, id", (cat, item)).fetchall()
    last: dict[str, dict] = {}
    for r in rows:
        last[r["country"]] = rates._row(r)
    return list(last.values())


def _has_rate(cat: str, item: str, country: str) -> bool:
    with closing(rates._connect()) as con:
        return con.execute("SELECT 1 FROM rates WHERE category=? AND item=? AND country=? LIMIT 1",
                           (cat, item, country)).fetchone() is not None


def _copy_rates(cat: str, ref: str, new: str) -> int:
    n = 0
    for r in _approved(cat, ref):
        if _has_rate(cat, new, r["country"]):
            continue
        rates.create({"category": cat, "item": new, "country": r["country"], "value": r["value"], "unit": r["unit"],
                      "currency": r["currency"], "month": r["month"],
                      "source": f"EXAMPLE: same as {ref} until you enter your price", "is_example": True},
                     approve=True, origin="seed", approver="Example seed", system=True)
        n += 1
    return n


def seed() -> dict:
    """Add the grades, their EXAMPLE prices and engine rows. Idempotent; returns what was added."""
    out = {"materials": 0, "tool_materials": 0, "rates": 0, "engine_rows": 0}
    md = master_data.tables()
    mats = md["Materials"]
    by_name = {r["material"]: r for r in mats}
    added_parts = []
    for part_type, name, ref, density, main in PART_GRADES:
        r = by_name.get(ref)
        if r is None:
            continue
        if not any(m["material"] == name and m["part_type"] == part_type for m in mats):
            mtype = main or r["material_type"]
            first = not any(m["part_type"] == part_type and m["material_type"] == mtype for m in mats)
            row = {k: "" for k in r} | {"part_type": part_type, "material": name, "material_type": mtype,
                                        "recommended": "yes" if first else "",   # a new main material: its first grade
                                        "density_g_cm3": density, "notes": f"{NOTE} ({ref})"}
            mats.append(row)
            out["materials"] += 1
        added_parts.append((name, ref))
    if out["materials"]:
        master_data.write(md)
    db = mould_db.tables()
    tools = {r["code"]: r for r in db["tool_materials"]}
    for code, ref, density, hardness, application in TOOL_GRADES:
        r = tools.get(ref)
        if r is None or code in tools:
            continue
        db["tool_materials"].append(dict(r) | {"code": code, "density_g_cm3": density, "hardness": hardness, "make": "",
                                                 "application": application or r["application"], "is_example": True,
                                                 "notes": f"{NOTE} ({ref})"})
        tools[code] = db["tool_materials"][-1]
        out["tool_materials"] += 1
    for name, ref in added_parts:
        eref = ENGINE_REF.get(name, ref)
        for t in COPY_TABLES:
            rows = db.get(t) or []
            src = next((x for x in rows if x["material"] == eref), None)
            if src and not any(x["material"] == name for x in rows):
                rows.append(dict(src) | {"material": name, "is_example": True, "notes": f"EXAMPLE: same as {eref} (stage 53)"})
                out["engine_rows"] += 1
    if out["tool_materials"] or out["engine_rows"]:
        mould_db.write(db)
    for name, ref in added_parts:
        out["rates"] += _copy_rates("material", ref, name) + _copy_rates("material_scrap", ref, name)
    for code, ref, *_ in TOOL_GRADES:
        if code in tools:
            out["rates"] += _copy_rates("tool_material", ref, code)
    return out
