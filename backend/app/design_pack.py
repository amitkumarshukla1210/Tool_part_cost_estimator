"""The design pack of a part (roadmap stage 20): corrected 3D design, tool design, drawings, simulation video and the
Excel / PDF / PowerPoint / 3D downloads, all from one build.

    plastic, die casting   simulation → draft correction on the 3D model → simulation again on the corrected part →
                           tool cost and mould concept in 3D on the corrected part → drawings, reports, video
    sheet metal            sheet tools + flat pattern + strip → stage-wise tool design (every stage of the sequence with its
                           die set in 3D, plan drawing, press) → reports, video

A build is cached in memory per part revision, so the downloads of one pack do not rebuild it.
"""

from __future__ import annotations

import io
import math
import time
import zipfile
from collections import OrderedDict

import numpy as np

from . import (capacity_db, corrections, fea, geometry, master_data, mould_db, outputs3d, rates, register, register_setup,
               report_render, simulation, software, tool_design)
from .register import ToolNotApplicable

CACHE: OrderedDict = OrderedDict()
CACHE_MAX = 4
VIDEO_MODES = ("full", "short", "none")


def _safe(code: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in code)


def _frames_tri(tri, colors, n, azim0, azim1, caption_fn, bounds, elev=22):
    out = []
    for k in range(n):
        t = k / max(n - 1, 1)
        c = colors(t) if callable(colors) else colors
        m = {"v": tri.reshape(-1, 3), "f": np.arange(len(tri) * 3).reshape(-1, 3), "color": (0.7, 0.7, 0.75)}
        out.append(outputs3d.render_png([m], elev=elev, azim=azim0 + (azim1 - azim0) * t, size=(6.4, 4.2), dpi=80, bounds=bounds,
                                        caption=caption_fn(t), colors=[c]))
    return out


# ------------------------------------------------------------ plastic and die casting

def _mould_kwargs(tool: dict, rev: dict, part_h: float = 0.0, area_cm2: float = 0.0) -> dict:
    qty = {l["element"]: l["quantity"] for l in tool.get("lines", []) if l.get("category") == "bought_out"}
    g = rev["geometry"]
    ax = g.get("pull_direction", "z")
    pick = lambda *words: int(next((q for k, q in qty.items() if all(w in k.lower() for w in words)), 0))
    return {"part_h": part_h or g["bbox_axes_mm"].get(ax, 0), "part_area_cm2": area_cm2 or g["projected_area_mm2"].get(ax, 0) / 100,
            "bom": {"ejector_pins": pick("ejector"), "return_pins": pick("return pin") or 4, "cooling_connectors": pick("cooling"),
                    "hot_runner": pick("hot runner nozzle") > 0, "slides": pick("slide mechanism"), "lifters": pick("lifter")}}


def mould_prepare(part_id: int, production: bool = False) -> dict:
    """Simulation, 3D correction, tool cost and mould 3D of a moulded part. Plastic and die casting go through the simulation and the
    draft correction; EPS and blow parts use the model as it is, opened along its stored pull direction at its middle."""
    d = register.part_detail(part_id, with_rm=False)
    part_type = register_setup.processes()[d["process"]]["part_type"]
    if part_type not in ("plastic", "die_casting"):
        _, rev, shape = register.part_shape(part_id)
        axis = rev["geometry"]["pull_direction"]
        z = corrections.to_z(shape, axis).BoundingBox()
        tool = register._tool_compute(part_id)
        parting = (z.zmin + z.zmax) / 2
        m3d = tool_design.mould_3d(shape, axis, parting, tool, regions=None, production=production, **_mould_kwargs(tool, rev))
        return {"d": d, "rev": rev, "part_type": part_type, "shape": shape, "fixed": shape, "axis": axis, "corr": None, "tool": tool,
                "m3d": m3d, "before": None, "after": None, "concept_res": {}, "facts": {}, "min_draft": None}
    d, rev, part_type, verts, tris, concept_res, facts = register._concept_inputs(part_id)
    _, _, shape = register.part_shape(part_id)
    density, _ = register._density(d["material"])
    g = rev["geometry"]
    before = simulation.run(verts, tris, part_type, facts, g["projected_area_mm2"])
    axis = before["opening_axis"]
    min_draft = before["results"]["min_draft_deg"]
    corr = corrections.apply_draft(shape, axis, min_draft)
    fixed = corr["shape"]
    m2 = geometry.analyze(fixed, part_type, density)
    v2, t2 = geometry.tessellate(fixed)
    across = sorted((v for a, v in m2.bbox_axes_mm.items() if a != axis), reverse=True)
    facts2 = facts | {"part_l": across[0], "part_w": across[1], "part_h": m2.bbox_axes_mm[axis],
                      "projected_area_cm2": m2.projected_area_mm2[axis] / 100, "volume_cm3": m2.volume_cm3,
                      "part_weight_g": m2.net_weight_g}
    after = simulation.run(v2, t2, part_type, facts2, m2.projected_area_mm2)
    tool = register._tool_compute(part_id)
    m3d = tool_design.mould_3d(fixed, axis, corr["parting_z_mm"], tool, regions=concept_res.get("regions"), production=production,
                               **_mould_kwargs(tool, rev, m2.bbox_axes_mm[axis], m2.projected_area_mm2[axis] / 100))
    return {"d": d, "rev": rev, "part_type": part_type, "shape": shape, "fixed": fixed, "axis": axis, "corr": corr, "tool": tool, "m3d": m3d,
            "before": before, "after": after, "concept_res": concept_res, "facts": facts, "min_draft": min_draft, "m2": m2, "v2": v2, "t2": t2,
            "verts": verts, "tris": tris, "density": density}


def _mould_pack(part_id: int, video: str) -> dict:
    P = mould_prepare(part_id)
    d, rev, part_type, shape, fixed, axis, corr, tool, m3d = (P[k] for k in ("d", "rev", "part_type", "shape", "fixed", "axis", "corr", "tool", "m3d"))
    before, after, min_draft, verts, tris, v2, t2, concept_res, facts = (P[k] for k in ("before", "after", "min_draft", "verts", "tris", "v2", "t2", "concept_res", "facts"))

    r0, r1 = before["results"], after["results"]
    mach = after["machine"]
    b_insert = next((c["shape"] for c in m3d["components"] if c["name"] == "B side insert"), None)
    bar = r1.get("cavity_bar") or master_data.parameters(part_type).get("cavity_pressure_bar", 400)
    fea_res = (fea.solve(b_insert, bar / 10.0, "cavity", master_data.parameters(part_type)) if b_insert is not None
               else {"available": False, "note": "No B side insert to check."})

    # ---- pictures
    pics_before, pics_after = simulation.pictures(before), simulation.pictures(after)
    part_mesh = {"name": "Part (corrected)", "group": "part", "color": (0.95, 0.8, 0.25), "v": np.asarray(v2, float), "f": np.asarray(t2, int)}
    orig_mesh = {"name": "Part (as received)", "group": "part", "color": (0.62, 0.66, 0.72), "v": np.asarray(verts, float), "f": np.asarray(tris, int)}
    tool_meshes = outputs3d.component_meshes(m3d["components"])
    closed = [dict(m) for m in tool_meshes]
    img_tool = outputs3d.render_png(tool_meshes, "Mould concept (open): corrected part, core and cavity inserts, base", azim=-50)
    img_part = outputs3d.render_png([part_mesh], "Corrected part")
    img_orig = outputs3d.render_png([orig_mesh], "Part as received")

    # ---- drawings and files
    code = _safe(d["part_code"])
    views = outputs3d.three_views(fixed)
    notes = [f"Drafted to {corr['target_deg']:g}° along {axis.upper()} (minimum required {min_draft:g}°), parting plane at {corr['parting_z_mm']:.1f} mm.",
             f"Volume change {corr['volume_change_pct']:+.2f} %. Low-draft wall {corr['before']['low_draft_cm2']:.1f} → {corr['after']['low_draft_cm2']:.2f} cm².",
             "Dimensions are overall sizes of the corrected model; the engineer's CAD drawing governs."]
    files = {}
    files[f"{code}_corrected_part.step"] = outputs3d.step_bytes([{"name": "corrected_part", "shape": fixed, "color": (0.95, 0.8, 0.25)}])
    files[f"{code}_corrected_drawing.pdf"] = outputs3d.drawing_pdf([{"views": views, "title": f"{d['part_code']} - {d['name']}: corrected part",
                                                                      "subtitle": f"Rev {rev['rev']} · {d['material']} · after simulation corrections", "notes": notes}])
    files[f"{code}_corrected_drawing.dxf"] = outputs3d.drawing_dxf(views, f"{d['part_code']} corrected")
    files[f"{code}_tool_design.step"] = outputs3d.step_bytes(m3d["components"], f"{code}_tool")
    tool_views = outputs3d.three_views(_compound([c["shape"] for c in m3d["components"] if c["group"] != "part"]))
    files[f"{code}_tool_design_drawing.pdf"] = outputs3d.drawing_pdf([{
        "views": tool_views, "title": f"{d['part_code']}: mould concept, base {m3d['base']}",
        "subtitle": f"{m3d['cavities_total']} cavities, mould base {m3d['base_mm'][0]:g} × {m3d['base_mm'][1]:g} mm, open {m3d['open_gap_mm']:g} mm",
        "notes": ["Concept layout from the sized base and cavity layout. The final tool design is made in the engineer's CAD."]}])
    scenes = [{"name": "Corrected part vs as received", "meshes": [dict(orig_mesh, color=(0.62, 0.66, 0.72)), part_mesh]},
              {"name": "Mould concept (use the open slider)", "meshes": tool_meshes}]
    files[f"{code}_3d_report.html"] = outputs3d.viewer_html(
        f"{d['part_code']} - 3D report", scenes,
        [f"Part rev {rev['rev']}, {d['material']}", f"Parting plane {corr['parting_z_mm']:.1f} mm, axis {axis.upper()}",
         f"Drafted faces: {len(corr['faces_drafted'])}", f"Mould base {m3d['base']}"] + ([m3d["note"]] if m3d["note"] else []))

    # ---- report
    machine_text = (f"{mach['name']} ({mach['tonnage_t']:g} t)" if mach.get("machine_id") else "no machine in the database")
    kpis = [("Part", f"{d['part_code']} - {d['name']}"), ("Revision", rev["rev"]), ("Material", d["material"]), ("Process", d["process"]),
            ("Opening direction", axis.upper()), ("Draft required (deg)", min_draft), ("Draft target used (deg)", corr["target_deg"]),
            ("Low-draft wall before (cm2)", round(corr["before"]["low_draft_cm2"], 2)), ("Low-draft wall after (cm2)", round(corr["after"]["low_draft_cm2"], 2)),
            ("Cycle time before / after (s)", f"{r0['cycle_s']:.1f} / {r1['cycle_s']:.1f}"),
            ("Clamp force before / after (t)", f"{r0['clamp_t']:.0f} / {r1['clamp_t']:.0f}"), ("Machine", machine_text),
            ("Mould base", m3d["base"]), ("Cavities", m3d["cavities_total"]),
            ("Tool cost per tool", f"{tool['currency']} {tool['value']:,.0f}"), ("Tool cost (INR)", f"{tool['value_inr']:,.0f}"),
            ("Insert FEA (Gmsh + CalculiX)", _fea_line(fea_res))]
    steps = [[s["label"] or s["name"], s["formula"], f"{s['value']:.3f}", s["unit"]] for s in after["steps"]]
    sections = [
        {"title": "Simulation: problems found on the part as received", "text": before["corrections"] or ["No corrections required."],
         "images": [(t, p) for t, p in pics_before]},
        {"title": "3D design correction", "text": [
            f"Draft added to {len(corr['faces_drafted'])} wall faces to {corr['target_deg']:g}° ({min_draft:g}° required), parting plane {corr['parting_z_mm']:.1f} mm.",
            f"Low-draft wall: {corr['before']['low_draft_cm2']:.1f} → {corr['after']['low_draft_cm2']:.2f} cm². Volume change {corr['volume_change_pct']:+.2f} %."
            + (f" {len(corr['faces_failed'])} face(s) could not be drafted by the kernel." if corr["faces_failed"] else ""),
            "Thick sections, thin walls and undercuts are not changed by software: they stay as Corrections required for R&D."],
         "table": {"headers": ["Face", "Type", "Draft (deg)", "Tool side"], "rows": [[f"{f['face_area_mm2']:.0f} mm2", f["type"], f["angle_deg"], f["tool_side"]] for f in corr["faces_drafted"]]
                   + [[f"{f['face_area_mm2']:.0f} mm2", "not drafted", "", f["reason"]] for f in corr["faces_failed"]]},
         "images": [("As received", img_orig), ("Corrected", img_part)]},
        {"title": "Simulation again on the corrected part", "text": after["corrections"] or ["No corrections required."],
         "images": [(t, p) for t, p in pics_after]},
        {"title": "Cycle, clamp force and machine", "text": [f"Machine selected from the database (0 to {capacity_db.MAX_T:g} t): {machine_text}."],
         "table": {"headers": ["Step", "Formula", "Value", "Unit"], "rows": steps}},
        {"title": "Tool design (concept 3D)", "text": [f"Mould base {m3d['base']} ({m3d['base_mm'][0]:g} × {m3d['base_mm'][1]:g} mm), {m3d['cavities_total']} cavit"
                                                       f"{'y' if m3d['cavities_total'] == 1 else 'ies'}; {tool['stage_c']['note']}."],
         "table": {"headers": ["Tool BOM line", "Group", "Cost"], "rows": [[l["element"], l.get("cost_group", ""), round(l.get("total", l.get("cost", 0)))] for l in tool["lines"]]},
         "images": [("Mould concept, open", img_tool)]},
    ]
    report = {"title": f"{d['part_code']} - {d['name']}", "subtitle": f"Design pack · rev {rev['rev']} · {d['material']} · {d['process']}",
              "example": bool(tool.get("example", {}).get("any")), "kpis": kpis, "sections": sections}
    sections.append(_fea_section(fea_res, f"cavity pressure {bar:g} bar on the B side insert, fixed on its back"))
    if fea_res.get("vtk"):
        files[f"{code}_fea_result.vtk"] = fea_res.pop("vtk")
    # ---- video
    if video != "none":
        files[f"{code}_simulation.mp4"] = outputs3d.video_mp4(_mould_video(before, after, tool_meshes, m3d, video), fps=10)
    mesh_note = fea_res
    summary = {"kind": "mould", "part_id": part_id, "part_code": d["part_code"], "rev": rev["rev"], "axis": axis,
               "draft_before_cm2": corr["before"]["low_draft_cm2"], "draft_after_cm2": corr["after"]["low_draft_cm2"],
               "faces_drafted": len(corr["faces_drafted"]), "faces_failed": len(corr["faces_failed"]),
               "machine": mach.get("machine_id"), "machine_t": mach.get("tonnage_t"), "clamp_t": r1["clamp_t"],
               "mould_base": m3d["base"], "cavities": m3d["cavities_total"], "tool_cost_inr": tool["value_inr"],
               "fea": {k: v for k, v in mesh_note.items() if k != "vtk"}, "corrections_before": before["corrections"], "corrections_after": after["corrections"]}
    return {"report": report, "files": files, "summary": summary}


def _fea_line(r: dict) -> str:
    if not r.get("available") or "max_deflection_mm" not in r:
        return r.get("note", "not run")
    return (f"{'OK' if r['ok'] else 'CHECK'}: deflection {r['max_deflection_mm']:.4f} mm (limit {r['deflection_limit_mm']:g}), "
            f"von Mises {r['max_von_mises_mpa']:.0f} MPa (limit {r['stress_limit_mpa']:.0f})")


def _fea_section(r: dict, what: str) -> dict:
    if not r.get("available") or "max_deflection_mm" not in r:
        return {"title": "Structural check (FEA)", "text": [r.get("note", "not run")]}
    return {"title": "Structural check (FEA)", "text": [
        f"Gmsh + CalculiX, linear elastic: {what}.", r["note"],
        ("Within the limits." if r["ok"] else "Over a limit: thicken the plate / insert or support it.")],
        "table": {"headers": ["Result", "Value", "Limit"], "rows": [
            ["Max deflection (mm)", round(r["max_deflection_mm"], 4), r["deflection_limit_mm"]],
            ["Max von Mises (MPa)", round(r["max_von_mises_mpa"], 1), round(r["stress_limit_mpa"], 1)],
            ["Pressure (MPa)", round(r["pressure_mpa"], 2), ""], ["Elements / nodes", f"{r['elements']} / {r['nodes']}", ""]]}}


def _compound(shapes):
    import cadquery as cq
    return cq.Compound.makeCompound(shapes)


def _mould_video(before: dict, after: dict, tool_meshes: list, m3d: dict, mode: str) -> list[bytes]:
    from matplotlib import pyplot as plt
    f = after["_faces"]
    tri = f["tri"]
    if len(tri) > outputs3d.MAX_RENDER_FACES:
        keep = np.arange(0, len(tri), math.ceil(len(tri) / outputs3d.MAX_RENDER_FACES))
    else:
        keep = np.arange(len(tri))
    tri = tri[keep]
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    bounds = (lo, hi)
    n = {"full": 16, "short": 8}[mode]
    th = f["thickness"][keep]
    lo_t, hi_t = (np.nanmin(th), np.nanmax(th)) if np.isfinite(th).any() else (0, 1)
    wallc = plt.get_cmap("viridis")(np.where(np.isnan(th), 0, (th - lo_t) / max(hi_t - lo_t, 1e-9)))
    wallc[np.isnan(th)] = (0.82, 0.85, 0.88, 1)
    res = after["results"]
    frames = _frames_tri(tri, wallc, n, -70, 20, lambda t: f"1 · Wall thickness {lo_t:.2f}–{hi_t:.2f} mm (corrected part)", bounds)
    # fill: faces coloured by distance from the gate (the lowest point along the opening axis) as the melt front advances
    cen = tri.mean(axis=1)
    ax = "xyz".index(after["opening_axis"])
    gate = cen[np.argmin(cen[:, ax])]
    dist = np.linalg.norm(cen - gate, axis=1)
    dist = dist / max(dist.max(), 1e-9)
    grey, melt = np.array([0.8, 0.82, 0.86, 1.0]), np.array([0.93, 0.45, 0.1, 1.0])
    fill_s, cool_s, cyc = res.get("fill_s", res.get("fill_s", 0)), res.get("cooling_s", res.get("solidify_s", 0)), res["cycle_s"]
    frames += _frames_tri(tri, lambda t: np.where((dist <= t)[:, None], melt, grey), n, 20, 20,
                          lambda t: f"2 · Filling {100 * t:.0f} % (fill {fill_s:.2f} s)", bounds)
    hot, cold = np.array([0.85, 0.12, 0.1, 1.0]), np.array([0.15, 0.4, 0.85, 1.0])
    frames += _frames_tri(tri, lambda t: np.tile(hot * (1 - t) + cold * t, (len(tri), 1)), n, 20, 40,
                          lambda t: f"3 · Cooling {t * cool_s:.1f} of {cool_s:.1f} s", bounds)
    # opening and ejection of the tool
    allb = np.concatenate([m["v"] for m in tool_meshes])
    top = allb.max(0) + np.array([0, 0, m3d["open_gap_mm"] * 1.6])
    tb = (allb.min(0), top)
    for k in range(n):
        t = k / max(n - 1, 1)
        moved = []
        for m in tool_meshes:
            lift = False
            mv = dict(m)
            if m["group"] == "upper" or lift:
                mv["v"] = m["v"] + np.array([0, 0, m3d["open_gap_mm"] * 0.6 * t])
            if m["group"] == "part":
                mv["v"] = m["v"] + np.array([0, 0, m3d["open_gap_mm"] * 0.4 * t])
            moved.append(mv)
        frames.append(outputs3d.render_png(moved, elev=18, azim=-50, size=(6.4, 4.2), dpi=80, bounds=tb,
                                           caption=f"4 · Tool opens, part ejected (open + eject {4 + 0:.0f}+ s of the {cyc:.1f} s cycle)"))
    return frames


# ------------------------------------------------------------ sheet metal

def sheet_prepare(part_id: int, mode: str | None = None) -> dict:
    """Sheet-metal context with the model corrected (bend radii, minimum holes), flat pattern, strip and the stage design."""
    from . import sheet_layout, sheet_tools
    d, rev, shape, blank, res = register._sheet_context(part_id)
    t = res["features"]["t"]
    res0, shape0 = res, shape
    mat = next(r for r in mould_db.tables()["sheet_materials"] if r["material"] == d["material"])
    corr = corrections.correct_sheet(shape, t, mat["min_bend_r_factor"], mat["min_hole_factor"],
                                     master_data.parameters("sheet_metal").get("default_bend_radius_factor", 1.0))
    geometry_used = rev["geometry"]
    if corr["changed"]:
        density, _ = register._density(d["material"])
        shape = corr["shape"]
        geometry_used = geometry.analyze(shape, "sheet_metal", density).to_dict() | {
            "wall_mm": t, "bend_count": rev["geometry"].get("bend_count") or 0}
        typed = dict(res["typed"])
        if any("bend" in c["kind"] and c.get("count") for c in corr["changes"]):
            typed["bend_radius_mm"] = corr["r_in_mm"]
        volume, _ = register._annual_volume(d)
        feat = sheet_tools.features(shape, geometry_used, blank, typed, density, volume, d["programme_life_years"])
        by_process = {"sheet_metal_progressive": "progressive", "sheet_metal_multistage": "multi_stage"}.get(d["process"], "")
        res = sheet_tools.run(feat, d["material"], typed, by_process) | {"part_id": part_id, "rev": rev["rev"], "typed": typed,
                                                                         "process": d["process"]}
    if mode and res["mode"] != mode:       # the other die type, for the progressive / stage comparison
        typed = {k: v for k, v in res["typed"].items() if k != "mode"}
        res = sheet_tools.run(res["features"], d["material"], typed, mode) | {"part_id": part_id, "rev": rev["rev"], "typed": res["typed"],
                                                                              "process": d["process"]}
    fp = sheet_layout.flat_pattern(shape, geometry_used, blank, t)
    sl = sheet_layout.strip_layout(fp, t, len(res["operations"]))
    country = (d["tool_country"] or d["country"] or register_setup.settings()["default_country"]).upper()
    design = tool_design.sheet_design(fp, sl, res, geometry_used, country, d["costing_month"] or rates.current_month())
    return {"d": d, "rev": rev, "shape": shape, "shape0": shape0, "blank": blank, "res": res, "res0": res0, "t": t, "corr": corr,
            "geometry": geometry_used, "fp": fp, "sl": sl, "design": design, "country": country}


def _sheet_pack(part_id: int, video: str) -> dict:
    from . import sheet_layout
    P = sheet_prepare(part_id)
    d, rev, shape, shape0, res, res0, t, corr, geometry_used, fp, sl, design, country = (
        P[k] for k in ("d", "rev", "shape", "shape0", "res", "res0", "t", "corr", "geometry", "fp", "sl", "design", "country"))
    code = _safe(d["part_code"])
    files, scenes, stage_pages, rows, comp_rows, stage_pics = {}, [], [], [], [], []
    progressive = design["mode"] == "progressive"
    if progressive:
        sol = tool_design.progressive_solids(design, fp, shape)
        meshes = outputs3d.component_meshes(sol)
        scenes.append({"name": "Progressive die: all stations", "meshes": meshes})
        files[f"{code}_progressive_die.step"] = outputs3d.step_bytes(sol, f"{code}_progressive")
        s0 = design["stages"][0]
        stage_pages.append({"views": outputs3d.three_views(_compound([x["shape"] for x in sol if x["group"] != "work"])),
                            "title": f"{d['part_code']} - progressive die, {len(design['stages'])} stations",
                            "subtitle": f"Die set {s0['values']['die_set_l_mm']:g} × {s0['values']['die_set_w_mm']:g} mm, shut height {s0['values']['shut_height_mm']:g} mm, "
                                        f"force {design['total_force_t']:g} t, press {s0['press'].get('name') or 'none fits'}",
                            "notes": ["Stations: " + ", ".join(f"{s['n']} {s['name']}" for s in design["stages"]),
                                      "Concept die set generated from the Stage tool rules; forming surfaces are detailed in the engineer's CAD."]})
        stage_pics.append(("Progressive die (open)", outputs3d.render_png(meshes, "Progressive die, all stations (open)", azim=-55)))
    for s in design["stages"]:
        press = s["press"]
        if not progressive:
            sol = tool_design.stage_solids(design, s, fp, shape)
            meshes = outputs3d.component_meshes(sol)
            scenes.append({"name": f"Stage {s['n']} {s['name']}", "meshes": meshes})
            files[f"{code}_stage{s['n']}_{_safe(s['code'])}.step"] = outputs3d.step_bytes(sol, f"{code}_stage{s['n']}")
            stage_pages.append({"views": outputs3d.three_views(_compound([x["shape"] for x in sol if x["group"] != "work"])),
                                "title": f"{d['part_code']} - stage {s['n']}: {s['name']}",
                                "subtitle": f"Die set {s['values']['die_set_l_mm']:g} × {s['values']['die_set_w_mm']:g} mm, shut height {s['values']['shut_height_mm']:g} mm, "
                                            f"force {s['force_t']:g} t, press {press.get('name') or 'none fits'}",
                                "notes": [f"Clearance {s['values']['clearance_mm']:.2f} mm per side; die block {s['values']['die_block_t_mm']:.0f} mm; "
                                          f"stripper {s['values']['stripper_t_mm']:.0f} mm; guide pillars {int(s['values']['pillars'])} × Ø{s['values']['pillar_dia_mm']:.0f}.",
                                          "Concept die set generated from the Stage tool rules; forming surfaces are detailed in the engineer's CAD."]})
            stage_pics.append((f"Stage {s['n']}: {s['name']}", outputs3d.render_png(meshes, f"Stage {s['n']} · {s['name']} (die open)", azim=-55)))
        rows.append([s["n"], s["name"], s["force_t"], s["design_force_t"], f"{s['values']['die_set_l_mm']:.0f} × {s['values']['die_set_w_mm']:.0f}",
                     s["values"]["shut_height_mm"], press.get("name") or "none fits", press.get("tonnage_t") or "", s["weight_kg"], s["steel_cost"]])
        for c in s["components"]:
            comp_rows.append([s["n"], s["name"], c["name"], c["steel"], c["length_mm"], c["width_mm"], c["thickness_mm"], c["qty"], c["weight_kg"], c["steel_cost"]])
    big = max(design["stages"], key=lambda x: x["force_t"])
    big_sol = (tool_design.progressive_solids(design, fp, shape) if progressive else tool_design.stage_solids(design, big, fp, shape))
    die_block = next((x["shape"] for x in big_sol if x["name"] == "Die block"), None)
    fea_res = {"available": False, "note": "No die block to check."}
    if die_block is not None:
        bbd = die_block.BoundingBox()
        force_n = (design["total_force_t"] if progressive else big["design_force_t"]) * 9806.65
        fea_res = fea.solve(die_block, force_n / (bbd.xlen * bbd.ylen), "top", master_data.parameters("sheet_metal"))
    files[f"{code}_stage_tool_drawings.pdf"] = outputs3d.drawing_pdf(stage_pages)
    files[f"{code}_blank.dxf"] = sheet_layout.blank_dxf(fp, d["part_code"])
    files[f"{code}_strip.dxf"] = sheet_layout.strip_dxf(fp, sl, d["part_code"])
    files[f"{code}_tool_pack.pdf"] = sheet_layout.pack_pdf(fp, sl, res, d, rev["rev"])
    views = outputs3d.three_views(shape)
    notes = ([f"Corrected: " + "; ".join(f"{c['kind']} x{c['count']} to {c['value_mm']} mm" for c in corr["changes"] if c.get("count"))] if corr["changed"]
             else ["No change needed to the model."]) + [f"Blank {fp['length_mm']:.1f} × {fp['width_mm']:.1f} mm ({fp['method']})"] + [p["message"] for p in res["problems"][:2]]
    files[f"{code}_corrected_drawing.pdf"] = outputs3d.drawing_pdf([{"views": views, "title": f"{d['part_code']} - {d['name']}: corrected part",
        "subtitle": f"Rev {rev['rev']} · {d['material']} · {t:g} mm", "notes": notes}])
    files[f"{code}_corrected_drawing.dxf"] = outputs3d.drawing_dxf(views, f"{d['part_code']} corrected")
    files[f"{code}_corrected_part.step"] = outputs3d.step_bytes([{"name": "corrected_part", "shape": shape, "color": (0.95, 0.8, 0.25)}])
    files[f"{code}_3d_report.html"] = outputs3d.viewer_html(f"{d['part_code']} - sheet-metal tool design", scenes,
        [f"{design['mode'].replace('_', ' ')} · {len(design['stages'])} stage(s)", f"Tool weight {design['tool_weight_kg']} kg", "Concept die sets: forming surfaces are for the engineer's CAD."])
    pics = [("Part as received", outputs3d.render_png(outputs3d.component_meshes([{"name": "part", "group": "part", "shape": shape, "color": (0.95, 0.8, 0.25)}]), "Part"))]
    kpis = [("Part", f"{d['part_code']} - {d['name']}"), ("Revision", rev["rev"]), ("Material", d["material"]), ("Thickness (mm)", t),
            ("Die type", design["mode"].replace("_", " ")), ("Stages", len(design["stages"])), ("Total force (t)", design["total_force_t"]),
            ("Largest press needed", max((s["press"].get("tonnage_t") or 0) for s in design["stages"]) or "none fits"),
            ("Tool weight (kg)", design["tool_weight_kg"]), ("Tool steel cost", f"{design['currency']} {design['steel_cost']:,}"),
            ("Blank (mm)", f"{fp['length_mm']:.1f} x {fp['width_mm']:.1f}"), ("Strip utilisation (%)", round(sl["best"]["values"]["utilisation_pct"], 1))]
    sections = [
        {"title": "Formability of the part as received", "text": [p["message"] for p in res0["problems"]] or ["No formability problems found."],
         "images": pics},
        {"title": "3D design correction", "text": (
            [f"{c['kind']}: {c['count']} changed to {c['value_mm']} mm" + (f" (from {c['from_mm']} mm)" if c.get("from_mm") else "")
             for c in corr["changes"] if c.get("count")] + [f"{c['kind']}: {c['failed']}" for c in corr["changes"] if c.get("failed")]
            + [f"Volume change {corr['volume_change_pct']:+.2f} %. Problems left after the correction: {len(res['problems'])}."]
            + [p["message"] for p in res["problems"]] + design["warnings"]) if corr["changed"] else
            ["The model needed no change: bend radii and holes are at or above the minimum." ] + [p["message"] for p in res["problems"]] + design["warnings"],
         "images": [("Corrected part", outputs3d.render_png(outputs3d.component_meshes([{"name": "part", "group": "part", "shape": shape, "color": (0.95, 0.8, 0.25)}]), "Corrected part"))]},
        {"title": "Stage-wise tool design", "text": [design["note"]],
         "table": {"headers": ["#", "Stage", "Force (t)", "Design force (t)", "Die set (mm)", "Shut height", "Press", "Press (t)", "Weight (kg)", "Steel cost"], "rows": rows},
         "images": stage_pics[:6]},
        {"title": "Strip layout", "text": [f"{sl['best']['feed']}; pitch {sl['best']['values']['pitch_mm']:.1f} mm, strip width {sl['best']['values']['strip_width_mm']:.1f} mm, "
                                           f"{int(sl['best']['values']['stations'])} stations."] + sl["problems"],
         "table": {"headers": ["Item", "Value", "Unit"], "rows": [[s["label"], round(s["value"], 2), s["unit"]] for s in sl["best"]["steps"]]}},
        {"title": "Tool components by stage", "table": {"headers": ["#", "Stage", "Component", "Steel", "L", "W", "T", "Qty", "Weight (kg)", "Steel cost"], "rows": comp_rows}},
        {"title": "Stage tool rules used", "table": {"headers": ["Stage", "Rule", "Formula", "Value", "Unit"],
         "rows": [[s["n"], x["name"], x["formula"], round(x["value"], 3), x["unit"]] for s in design["stages"][:1 if design["mode"] == "progressive" else 99] for x in s["steps"]]}},
    ]
    sections.append(_fea_section(fea_res, f"stage {big['n']} {big['name']} die block, {big['design_force_t']:g} t spread over its top face, fixed on its back"))
    kpis.append(("Die block FEA (Gmsh + CalculiX)", _fea_line(fea_res)))
    if fea_res.get("vtk"):
        files[f"{code}_fea_result.vtk"] = fea_res.pop("vtk")
    report = {"title": f"{d['part_code']} - {d['name']}", "subtitle": f"Design pack · rev {rev['rev']} · {d['material']} · sheet metal {design['mode'].replace('_', ' ')}",
              "example": design["is_example"], "kpis": kpis, "sections": sections}
    if video != "none":
        files[f"{code}_simulation.mp4"] = outputs3d.video_mp4(_sheet_video(design, fp, shape, video), fps=10)
    summary = {"kind": "sheet_metal", "part_id": part_id, "part_code": d["part_code"], "rev": rev["rev"], "mode": design["mode"],
               "stages": len(design["stages"]), "total_force_t": design["total_force_t"], "warnings": design["warnings"],
               "presses": [s["press"].get("machine_id") for s in design["stages"]], "tool_weight_kg": design["tool_weight_kg"],
               "problems": [p["message"] for p in res["problems"]], "problems_before": [p["message"] for p in res0["problems"]],
               "corrections": [c for c in corr["changes"] if c.get("count")], "fea": {k: v for k, v in fea_res.items() if k != "vtk"}, "springback_overbend_deg": res["values"].get("springback_deg")}
    return {"report": report, "files": files, "summary": summary}


def _sheet_video(design: dict, fp: dict, shape, mode: str) -> list[bytes]:
    frames = []
    n = {"full": 8, "short": 4}[mode]
    stages = design["stages"][:6]
    sets = ([(None, tool_design.progressive_solids(design, fp, shape))] if design["mode"] == "progressive"
            else [(s, tool_design.stage_solids(design, s, fp, shape, open_state=True)) for s in stages])
    for s, sol in sets:
        s = s or design["stages"][0]
        meshes = outputs3d.component_meshes(sol)
        allb = np.concatenate([m["v"] for m in meshes])
        gap = s["values"]["open_gap_mm"]
        bounds = (allb.min(0), allb.max(0))
        for k in range(n):
            t = 1 - k / max(n - 1, 1)                         # closing
            moved = [dict(m, v=m["v"] - np.array([0, 0, gap * (1 - t)])) if m["group"] == "upper" else m for m in meshes]
            frames.append(outputs3d.render_png(moved, elev=20, azim=-55, size=(6.4, 4.2), dpi=80, bounds=bounds,
                                               caption=(f"Progressive die · {len(design['stages'])} stations · {design['total_force_t']:g} t · die closing"
                                                    if design["mode"] == "progressive" else
                                                    f"Stage {s['n']}/{len(design['stages'])} · {s['name']} · {s['force_t']:g} t · die closing")))
    return frames


# ------------------------------------------------------------ public

def build(part_id: int, video: str = "short", force: bool = False) -> dict:
    if video not in VIDEO_MODES:
        raise ToolNotApplicable(f"video must be one of {', '.join(VIDEO_MODES)}.")
    d = register.part_detail(part_id, with_rm=False)
    proc = register_setup.processes().get(d["process"])
    if not proc:
        raise ToolNotApplicable("Set the part's process first.")
    part_type = proc["part_type"]
    rev = d["revisions"][0]["id"] if d["revisions"] else 0
    key = (part_id, rev, video, d.get("material"), d.get("process"), d.get("tool_country"), repr(d.get("tool_inputs")), repr(d.get("sheet_inputs")))
    if key in CACHE and not force:
        CACHE.move_to_end(key)
        return CACHE[key]
    t0 = time.time()
    if part_type in ("plastic", "die_casting"):
        out = _mould_pack(part_id, video)
    elif part_type == "sheet_metal":
        out = _sheet_pack(part_id, video)
    else:
        raise ToolNotApplicable("The design pack covers plastic moulds, die-casting dies and sheet-metal tools. "
                                "EPS, blow and foundry parts: use the 3D tool design page (production tool design) of the part.")
    code = _safe(d["part_code"])
    rep = out["report"]
    out["files"][f"{code}_design_report.xlsx"] = report_render.to_xlsx(rep)
    out["files"][f"{code}_design_report.pdf"] = report_render.to_pdf(rep)
    out["files"][f"{code}_design_report.pptx"] = report_render.to_pptx(rep)
    out["files"]["README.txt"] = _readme(code, out).encode()
    out["seconds"] = round(time.time() - t0, 1)
    CACHE[key] = out
    while len(CACHE) > CACHE_MAX:
        CACHE.popitem(last=False)
    return out


KINDS = {"xlsx": "_design_report.xlsx", "pdf": "_design_report.pdf", "pptx": "_design_report.pptx", "3d": "_3d_report.html",
         "drawing": "_corrected_drawing.pdf", "drawing-dxf": "_corrected_drawing.dxf", "corrected-step": "_corrected_part.step",
         "tool-step": "_tool_design.step", "tool-drawing": "_tool_design_drawing.pdf", "video": "_simulation.mp4",
         "stage-drawings": "_stage_tool_drawings.pdf", 
         "blank-dxf": "_blank.dxf", "strip-dxf": "_strip.dxf", "tool-pack": "_tool_pack.pdf"}
MEDIA = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf",
         "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "html": "text/html",
         "dxf": "application/dxf", "step": "application/step", "mp4": "video/mp4", "txt": "text/plain", "zip": "application/zip"}


def media_of(name: str) -> str:
    return MEDIA.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _readme(code: str, out: dict) -> str:
    lines = [f"Design to Cost - design pack of {out['summary']['part_code']} rev {out['summary']['rev']}", "",
             "Files:"] + [f"  {n}" for n in sorted(out["files"]) if n != "README.txt"]
    lines += ["", "STEP files open in FreeCAD (free), CadQuery, or any CAD system. DXF files open in LibreCAD / FreeCAD / any CAD.",
              "The 3D report (.html) opens in any browser, offline: rotate, zoom, explode, hide parts.",
              "Concept tool design only: the engineer's CAD governs the final tool. See the README of the project for limits."]
    return "\n".join(lines)


def zip_bytes(pack: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in pack["files"].items():
            z.writestr(name, content)
    return buf.getvalue()
