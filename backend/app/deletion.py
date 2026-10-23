"""Delete a part or a whole project with its history, cost versions, tool designs and stored files (dashboard Delete button).

Everything that belongs to the part goes in one transaction: revisions, RM / tool / part cost versions, tool designs with components, reviews and
quotes, BOM lines, moulded-in insert links, the history log and the stored files nothing else uses. Cannot be undone: the preview says what goes.
CAPEX lines keep their budget but lose the link to the deleted part.
"""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select, update

from . import file_store, register
from . import projects_db as db


class DeleteError(register.RegisterError):
    pass


def _part_rows(conn, part_id: int) -> dict:
    p = conn.execute(select(db.parts).where(db.parts.c.id == part_id)).mappings().first()
    if not p:
        raise DeleteError(f"Part {part_id} does not exist.")
    return dict(p)


def _counts(conn, part_id: int) -> dict:
    n = lambda q: conn.execute(q).scalar() or 0
    designs = [r[0] for r in conn.execute(select(db.tool_designs.c.id).where(db.tool_designs.c.part_id == part_id))]
    return {"revisions": n(select(func.count()).select_from(db.revisions).where(db.revisions.c.part_id == part_id)),
            "rm_costs": n(select(func.count()).select_from(db.rm_costs).where(db.rm_costs.c.part_id == part_id)),
            "tool_costs": n(select(func.count()).select_from(db.tool_costs).where(db.tool_costs.c.part_id == part_id)),
            "piece_costs": n(select(func.count()).select_from(db.piece_costs).where(db.piece_costs.c.part_id == part_id)),
            "tool_designs": len(designs),
            "tool_components": n(select(func.count()).select_from(db.tool_components).where(db.tool_components.c.design_id.in_(designs))) if designs else 0,
            "bom_lines": n(select(func.count()).select_from(db.bom_lines).where(or_(db.bom_lines.c.parent_part_id == part_id, db.bom_lines.c.child_part_id == part_id))),
            "history": n(select(func.count()).select_from(db.history).where((db.history.c.entity == "part") & (db.history.c.entity_id == part_id)))}


def preview_part(part_id: int) -> dict:
    with db.engine().connect() as conn:
        p = _part_rows(conn, part_id)
        c = _counts(conn, part_id)
        parents = conn.execute(select(func.count(func.distinct(db.bom_lines.c.parent_part_id))).where(db.bom_lines.c.child_part_id == part_id)).scalar() or 0
        children = conn.execute(select(func.count()).select_from(db.part_inserts).where(db.part_inserts.c.part_id == part_id)).scalar() or 0
    return {"part_id": part_id, "part_code": p["part_code"], "name": p["name"], "counts": c, "used_in_assemblies": parents, "inserts_linked": children}


def _file_ids(conn, part_id: int) -> set[int]:
    ids = set()
    for rid, f, t in conn.execute(select(db.revisions.c.id, db.revisions.c.file_id, db.revisions.c.thumbnail_file_id).where(db.revisions.c.part_id == part_id)):
        ids |= {x for x in (f, t) if x}
    designs = [r[0] for r in conn.execute(select(db.tool_designs.c.id, db.tool_designs.c.summary).where(db.tool_designs.c.part_id == part_id))]
    for did, summary in conn.execute(select(db.tool_designs.c.id, db.tool_designs.c.summary).where(db.tool_designs.c.part_id == part_id)):
        if isinstance(summary, dict) and summary.get("fea_file_id"):
            ids.add(summary["fea_file_id"])
    if designs:
        comps = [r[0] for r in conn.execute(select(db.tool_components.c.id, db.tool_components.c.file_id).where(db.tool_components.c.design_id.in_(designs)))]
        ids |= {r[0] for r in conn.execute(select(db.tool_components.c.file_id).where(db.tool_components.c.design_id.in_(designs))) if r[0]}
        if comps:
            ids |= {r[0] for r in conn.execute(select(db.tool_component_revs.c.file_id).where(db.tool_component_revs.c.component_id.in_(comps))) if r[0]}
    return ids


def _prune_files(conn, ids: set[int]) -> list:
    """Remove the files rows (and return their paths) that nothing references any more."""
    gone = []
    for fid in ids:
        used = (conn.execute(select(func.count()).select_from(db.revisions).where(or_(db.revisions.c.file_id == fid, db.revisions.c.thumbnail_file_id == fid))).scalar()
                or conn.execute(select(func.count()).select_from(db.tool_components).where(db.tool_components.c.file_id == fid)).scalar()
                or conn.execute(select(func.count()).select_from(db.tool_component_revs).where(db.tool_component_revs.c.file_id == fid)).scalar()
                or conn.execute(select(func.count()).select_from(db.bom_extracts).where(db.bom_extracts.c.file_id == fid)).scalar())
        if not used:
            for (summary,) in conn.execute(select(db.tool_designs.c.summary)):
                if isinstance(summary, dict) and summary.get("fea_file_id") == fid:
                    used = True
                    break
        if used:
            continue
        row = conn.execute(select(db.files).where(db.files.c.id == fid)).mappings().first()
        if row:
            gone.append(file_store.path_of(dict(row)))
            conn.execute(delete(db.files).where(db.files.c.id == fid))
    return gone


def _delete_part(conn, part_id: int) -> list:
    _part_rows(conn, part_id)
    files = _file_ids(conn, part_id)
    rev_ids = [r[0] for r in conn.execute(select(db.revisions.c.id).where(db.revisions.c.part_id == part_id))]
    design_ids = [r[0] for r in conn.execute(select(db.tool_designs.c.id).where(db.tool_designs.c.part_id == part_id))]
    conn.execute(delete(db.bom_lines).where(or_(db.bom_lines.c.parent_part_id == part_id, db.bom_lines.c.child_part_id == part_id)))
    conn.execute(update(db.capex_items).where(db.capex_items.c.part_id == part_id).values(part_id=None))
    # explicit deletes in dependency order (the foreign keys cascade too; this keeps it independent of the pragma)
    if design_ids:
        comp_ids = [r[0] for r in conn.execute(select(db.tool_components.c.id).where(db.tool_components.c.design_id.in_(design_ids)))]
        if comp_ids:
            conn.execute(delete(db.tool_component_revs).where(db.tool_component_revs.c.component_id.in_(comp_ids)))
        for t in (db.tool_components, db.tool_reviews, db.tool_quotes):
            conn.execute(delete(t).where(t.c.design_id.in_(design_ids)))
        conn.execute(delete(db.tool_designs).where(db.tool_designs.c.id.in_(design_ids)))
    for t in (db.rm_costs, db.tool_costs, db.piece_costs):
        conn.execute(delete(t).where(t.c.part_id == part_id))
    conn.execute(delete(db.part_inserts).where(or_(db.part_inserts.c.part_id == part_id, db.part_inserts.c.insert_part_id == part_id)))
    conn.execute(delete(db.revisions).where(db.revisions.c.part_id == part_id))
    conn.execute(delete(db.history).where((db.history.c.entity == "part") & (db.history.c.entity_id == part_id)))
    if rev_ids:
        conn.execute(delete(db.history).where((db.history.c.entity == "revision") & (db.history.c.entity_id.in_(rev_ids))))
    conn.execute(delete(db.parts).where(db.parts.c.id == part_id))
    return _prune_files(conn, files)


def _unlink(paths: list) -> None:
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def delete_part(part_id: int) -> dict:
    with db.engine().begin() as conn:
        p = _part_rows(conn, part_id)
        counts = _counts(conn, part_id)
        paths = _delete_part(conn, part_id)
        register._log(conn, "project", p["project_id"], "part_deleted", {"part": p["part_code"], "name": p["name"], "removed": counts})
    _unlink(paths)
    _clear_caches()
    return {"deleted": part_id, "part_code": p["part_code"], "removed": counts, "files_removed": len(paths)}


def preview_project(project_id: int) -> dict:
    with db.engine().connect() as conn:
        pr = conn.execute(select(db.projects).where(db.projects.c.id == project_id)).mappings().first()
        if not pr:
            raise DeleteError(f"Project {project_id} does not exist.")
        parts = [r[0] for r in conn.execute(select(db.parts.c.id).where(db.parts.c.project_id == project_id))]
        tot = {}
        for pid in parts:
            for k, v in _counts(conn, pid).items():
                tot[k] = tot.get(k, 0) + v
        variants = conn.execute(select(func.count()).select_from(db.variants).where(db.variants.c.project_id == project_id)).scalar() or 0
        capex = conn.execute(select(func.count()).select_from(db.capex_items).where(db.capex_items.c.project_id == project_id)).scalar() or 0
    return {"project_id": project_id, "code": pr["code"], "name": pr["name"], "parts": len(parts), "variants": variants, "capex_lines": capex, "counts": tot}


def delete_project(project_id: int) -> dict:
    with db.engine().begin() as conn:
        pr = conn.execute(select(db.projects).where(db.projects.c.id == project_id)).mappings().first()
        if not pr:
            raise DeleteError(f"Project {project_id} does not exist.")
        parts = [r[0] for r in conn.execute(select(db.parts.c.id).where(db.parts.c.project_id == project_id))]
        paths, n_parts = [], len(parts)
        for pid in parts:
            paths += _delete_part(conn, pid)
        var_ids = [r[0] for r in conn.execute(select(db.variants.c.id).where(db.variants.c.project_id == project_id))]
        if var_ids:
            conn.execute(delete(db.bom_lines).where(db.bom_lines.c.variant_id.in_(var_ids)))
            conn.execute(delete(db.history).where((db.history.c.entity == "variant") & (db.history.c.entity_id.in_(var_ids))))
        conn.execute(delete(db.capex_items).where(db.capex_items.c.project_id == project_id))
        conn.execute(update(db.bom_extracts).where(db.bom_extracts.c.project_id == project_id).values(project_id=None))
        conn.execute(delete(db.variants).where(db.variants.c.project_id == project_id))
        conn.execute(delete(db.history).where((db.history.c.entity == "project") & (db.history.c.entity_id == project_id)))
        conn.execute(delete(db.projects).where(db.projects.c.id == project_id))
    _unlink(paths)
    _clear_caches()
    return {"deleted": project_id, "code": pr["code"], "parts_removed": n_parts, "files_removed": len(paths)}


def _clear_caches() -> None:
    from . import design_pack, tool_design_store
    for c in (getattr(design_pack, "CACHE", None), getattr(tool_design_store, "_SHAPES", None)):
        if c is not None:
            c.clear()
