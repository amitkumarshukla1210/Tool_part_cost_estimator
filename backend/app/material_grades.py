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
    # ---- stage 54: more stainless, EN steels and plastics ----
    # stainless sheet
    ("sheet_metal", "Stainless steel 201 (J1)", "Stainless steel 304", 7.8, None),
    ("sheet_metal", "Stainless steel 202 (J4)", "Stainless steel 304", 7.8, None),
    ("sheet_metal", "Stainless steel 304L (1.4307)", "Stainless steel 304", 7.93, None),
    ("sheet_metal", "Stainless steel 316 (1.4401)", "Stainless steel 304", 7.98, None),
    ("sheet_metal", "Stainless steel 316L (1.4404)", "Stainless steel 304", 7.98, None),
    ("sheet_metal", "Stainless steel 409L (1.4512)", "Stainless steel 430", 7.7, None),
    ("sheet_metal", "Stainless steel 410 (1.4006)", "Stainless steel 430", 7.75, None),
    ("sheet_metal", "Stainless steel 441 (1.4509)", "Stainless steel 430", 7.7, None),
    ("sheet_metal", "Stainless steel 310S (1.4845)", "Stainless steel 304", 7.9, None),
    # stainless bar
    ("machined", "Stainless steel 303 bar (1.4305, free-machining)", "Stainless steel 304 bar", 7.93, None),
    ("machined", "Stainless steel 304L bar (1.4307)", "Stainless steel 304 bar", 7.93, None),
    ("machined", "Stainless steel 316 bar (1.4401)", "Stainless steel 304 bar", 7.98, None),
    ("machined", "Stainless steel 316L bar (1.4404)", "Stainless steel 304 bar", 7.98, None),
    ("machined", "Stainless steel 410 bar (1.4006)", "Stainless steel 304 bar", 7.75, None),
    ("machined", "Stainless steel 420 bar (1.4021)", "Stainless steel 304 bar", 7.75, None),
    ("machined", "Stainless steel 431 bar (1.4057)", "Stainless steel 304 bar", 7.7, None),
    ("machined", "Stainless steel 17-4PH bar (1.4542)", "Stainless steel 304 bar", 7.8, None),
    # EN / IS carbon and alloy steel bar
    ("machined", "EN3B (080M15, C15) bar", "Carbon steel EN8 (C45) bar", 7.85, None),
    ("machined", "EN9 (070M55, C55) bar", "Carbon steel EN8 (C45) bar", 7.85, None),
    ("machined", "EN14 (150M19, 20Mn5) bar", "Carbon steel EN8 (C45) bar", 7.85, None),
    ("machined", "EN18 (530M40, 41Cr4) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "EN24 (817M40, 34CrNiMo6) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "EN31 (535A99, 100Cr6) bar", "Alloy steel EN19 (42CrMo4) bar", 7.83, None),
    ("machined", "EN36 (655M13, 15NiCr13) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "EN353 (815M17) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "EN354 (820M17) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "EN41B (905M39, nitriding) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "EN45 (250A58, spring) bar", "Carbon steel EN8 (C45) bar", 7.85, None),
    ("machined", "EN47 (735A51, 51CrV4) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "20MnCr5 (1.7147) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "16MnCr5 (1.7131) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "SAE 8620 (1.6523) bar", "Alloy steel EN19 (42CrMo4) bar", 7.85, None),
    ("machined", "SAE 1018 (C18) bar", "Carbon steel EN8 (C45) bar", 7.85, None),
    # sheet and strip steel
    ("sheet_metal", "CRCA IS 513 CR1 / D (DC01)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "CRCA IS 513 CR2 / DD (DC03)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "CRCA IS 513 CR4 / IF (DC05 / DC06)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "HR IS 1079 HR2 / D (DD11)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "HRPO pickled & oiled (DD12)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "HR IS 2062 E250 (S235)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "HR IS 2062 E350 (S355)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "HSLA IS 5986 Fe 410 (S315MC)", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "HSLA S420MC", "Mild steel CRCA / HR", 7.85, None),
    ("sheet_metal", "Electro-galvanised EG (DC01+ZE, SECC)", "Galvanised steel GI", 7.85, None),
    ("sheet_metal", "Galvannealed GA (DX51D+ZF)", "Galvanised steel GI", 7.85, None),
    ("sheet_metal", "CRNO electrical steel M400-50A", "Mild steel CRCA / HR", 7.7, None),
    # plastics - commodity
    ("plastic", "PP homopolymer (injection grade)", "PP (polypropylene)", 0.905, None),
    ("plastic", "PP random copolymer (clear)", "PP (polypropylene)", 0.9, None),
    ("plastic", "PP UV stabilised", "PP (polypropylene)", 0.905, None),
    ("plastic", "HDPE (injection grade)", "PP (polypropylene)", 0.955, "Polyethylene (PE)"),
    ("plastic", "LDPE", "PP (polypropylene)", 0.92, "Polyethylene (PE)"),
    ("plastic", "LLDPE", "PP (polypropylene)", 0.92, "Polyethylene (PE)"),
    ("plastic", "PVC rigid (uPVC)", "PP (polypropylene)", 1.4, "PVC"),
    ("plastic", "PVC flexible", "PP (polypropylene)", 1.3, "PVC"),
    ("plastic", "HIPS (high impact polystyrene)", "ABS", 1.04, "Polystyrene (PS)"),
    ("plastic", "GPPS (general purpose polystyrene)", "ABS", 1.05, "Polystyrene (PS)"),
    # plastics - engineering
    ("plastic", "ABS high heat", "ABS", 1.05, None),
    ("plastic", "ABS electroplating grade", "ABS", 1.05, None),
    ("plastic", "ABS GF20 (glass filled)", "ABS", 1.22, None),
    ("plastic", "SAN (styrene acrylonitrile)", "ABS", 1.08, "SAN / ASA"),
    ("plastic", "ASA (UV resistant)", "ABS", 1.07, "SAN / ASA"),
    ("plastic", "PMMA (acrylic)", "ABS", 1.19, "Acrylic (PMMA)"),
    ("plastic", "PC GF10 (glass filled)", "PC (polycarbonate)", 1.26, None),
    ("plastic", "PC flame retardant V0", "PC (polycarbonate)", 1.2, None),
    ("plastic", "PC/PBT blend", "PC/ABS", 1.22, None),
    ("plastic", "PPO / PPE (Noryl)", "PC/ABS", 1.06, "PPO / PPE"),
    ("plastic", "PA6 GF30", "PA66 GF30", 1.36, None),
    ("plastic", "PA66 (unfilled)", "PA6", 1.14, None),
    ("plastic", "PA66 GF15", "PA66 GF30", 1.23, None),
    ("plastic", "PA12", "PA66 GF30", 1.01, None),
    ("plastic", "POM copolymer", "POM (acetal)", 1.41, None),
    ("plastic", "POM homopolymer (Delrin)", "POM (acetal)", 1.42, None),
    ("plastic", "PBT (unfilled)", "PBT GF30", 1.31, None),
    ("plastic", "PET GF30", "PBT GF30", 1.56, None),
    ("plastic", "PPS GF40", "PA66 GF30", 1.65, "PPS"),
    ("plastic", "TPE (thermoplastic elastomer)", "PP copolymer (impact)", 1.0, "Thermoplastic elastomer (TPE / TPU)"),
    ("plastic", "TPU (thermoplastic polyurethane)", "PP copolymer (impact)", 1.2, "Thermoplastic elastomer (TPE / TPU)"),
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
    # ---- stage 54 ----
    ("EN19 (42CrMo4) plates", "Mould base steel (4140 / 1.7225)", 7.85, "28-32 HRC", None),
    ("EN36 (case hardening) guides / pins", "EN8 (080M40)", 7.85, "58-62 HRC case", None),
    ("EN353 (case hardening) pins", "EN8 (080M40)", 7.85, "58-62 HRC case", None),
    ("SS 420 (1.2083) plates", "S136 / 1.2083 ESR", 7.75, "28-34 HRC pre-hardened", None),
    ("440C (1.4125) stainless wear parts", "S136 / 1.2083 ESR", 7.7, "56-60 HRC", None),
    ("SS 304 (non-magnetic parts)", "1.2316 ESR (stainless)", 7.93, "annealed", None),
    ("1.2311 + S (P20 free-machining)", "P20 (1.2311)", 7.85, "28-32 HRC prehardened", None),
    ("1.2344 ESR (H13 premium)", "H13 (1.2344)", 7.8, "44-50 HRC", None),
    ("1.2379 ESR (D2 premium)", "D2 (1.2379)", 7.7, "58-62 HRC", None),
    ("ASP 23 (powder HSS)", "D2 (1.2379)", 8.0, "60-66 HRC", None),
    ("Vanadis 4E (powder)", "D2 (1.2379)", 7.7, "58-62 HRC", None),
    ("Tungsten carbide (K20 / G20)", "BeCu", 14.5, "88-91 HRA", None),
    ("Ampcoloy 940 (CuNiSiCr)", "Beryllium copper C17510", 8.7, "92-98 HRB", None),
]

COPY_TABLES = ("flow_materials", "process_windows", "sheet_materials", "machining_data")
# engine data (flow, sheet, machining rows) from another grade than the price reference
ENGINE_REF = {"Brass CuZn37 (CW508L) sheet": "Copper", "Brass CuZn30 (CW505L, cartridge) sheet": "Copper",
              "Stainless steel 409L (1.4512)": "Stainless steel 430", "Stainless steel 410 (1.4006)": "Stainless steel 430",
              "Stainless steel 441 (1.4509)": "Stainless steel 430"}


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
