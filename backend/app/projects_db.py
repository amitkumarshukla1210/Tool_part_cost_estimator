"""Project database: projects, variants, BOM, parts, revisions, files, history.

This is YOUR project data (not master data), so it lives outside git:
    data/projects.sqlite        default; set DATABASE_URL for another database
                                (e.g. postgresql+psycopg://user:pw@server/dtc later)

SQLAlchemy Core keeps the same code working on SQLite now and PostgreSQL later.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Table,
                        Text, UniqueConstraint, create_engine, event)
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
meta = MetaData()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


projects = Table(
    "projects", meta,
    Column("id", Integer, primary_key=True),
    Column("code", String(40), nullable=False, unique=True),
    Column("name", String(200), nullable=False),
    Column("customer", String(200), default=""),
    Column("description", Text, default=""),
    Column("capex_budget_inr", Float),
    Column("created_by", String(100), default=""),
    Column("created_at", DateTime, default=now),
    Column("updated_at", DateTime, default=now, onupdate=now),
)

variants = Table(
    "variants", meta,
    Column("id", Integer, primary_key=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("code", String(40), nullable=False),
    Column("name", String(200), nullable=False),
    Column("target_bom_cost_inr", Float),
    Column("annual_volume", Integer),
    Column("notes", Text, default=""),
    Column("created_at", DateTime, default=now),
    UniqueConstraint("project_id", "code"),
)

files = Table(
    "files", meta,
    Column("id", Integer, primary_key=True),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("original_name", String(300), nullable=False),
    Column("stored_path", String(500), nullable=False),  # relative to the storage folder
    Column("size_bytes", Integer, nullable=False),
    Column("kind", String(30), nullable=False),          # step, thumbnail, drawing, ...
    Column("created_at", DateTime, default=now),
)

parts = Table(
    "parts", meta,
    Column("id", Integer, primary_key=True),
    Column("part_code", String(80), nullable=False, unique=True),
    Column("name", String(300), nullable=False),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("material", String(200), default=""),
    Column("process", String(60), default=""),
    Column("sourcing", String(40), default=""),
    Column("status", String(60), default=""),
    Column("annual_volume", Integer),
    Column("programme_life_years", Float),
    Column("target_piece_cost_inr", Float),
    Column("is_assembly", Boolean, default=False),
    Column("current_revision_id", Integer),
    Column("notes", Text, default=""),
    # bought-out price (inserts and other BOP parts): value, currency, where it came from, month
    Column("unit_price", Float),
    Column("price_currency", String(10), default=""),
    Column("price_source", String(200), default=""),
    Column("price_month", String(7), default=""),
    Column("price_is_example", Boolean, default=False),
    # simple shape + dimensions for a part without a 3D file, e.g. {"shape": "bush", "od_mm": 6, ...}
    Column("dimensions", JSON),
    Column("created_by", String(100), default=""),
    Column("created_at", DateTime, default=now),
    Column("updated_at", DateTime, default=now, onupdate=now),
    Index("ix_parts_project", "project_id"),
    Index("ix_parts_status", "status"),
    Index("ix_parts_process", "process"),
    Index("ix_parts_name", "name"),
)

revisions = Table(
    "revisions", meta,
    Column("id", Integer, primary_key=True),
    Column("part_id", ForeignKey("parts.id", ondelete="CASCADE"), nullable=False),
    Column("rev", String(20), nullable=False),
    Column("file_id", ForeignKey("files.id")),
    Column("thumbnail_file_id", ForeignKey("files.id")),
    Column("change_note", Text, default=""),
    Column("geometry", JSON),        # volume, area, bbox, projected areas, solids (from the CAD file)
    Column("source", String(200), default=""),  # e.g. "assembly demo.step / bracket_L", "Excel row 4"
    Column("created_by", String(100), default=""),
    Column("created_at", DateTime, default=now),
    UniqueConstraint("part_id", "rev"),
)

bom_lines = Table(
    "bom_lines", meta,
    Column("id", Integer, primary_key=True),
    Column("variant_id", ForeignKey("variants.id", ondelete="CASCADE"), nullable=False),
    Column("parent_part_id", ForeignKey("parts.id")),  # NULL = top level of the variant
    Column("child_part_id", ForeignKey("parts.id"), nullable=False),
    Column("quantity", Float, nullable=False),
    Column("position", Integer, default=0),
    UniqueConstraint("variant_id", "parent_part_id", "child_part_id"),
)

# Moulded-in inserts: the insert is a part of its own (usually bought-out), moulded into the body part.
part_inserts = Table(
    "part_inserts", meta,
    Column("id", Integer, primary_key=True),
    Column("part_id", ForeignKey("parts.id", ondelete="CASCADE"), nullable=False),         # the moulded / cast body
    Column("insert_part_id", ForeignKey("parts.id", ondelete="CASCADE"), nullable=False),  # the insert
    Column("quantity", Float, nullable=False),
    Column("detected", Boolean, default=False),   # found in the 3D assembly (and confirmed) rather than typed in
    Column("notes", Text, default=""),
    Column("created_at", DateTime, default=now),
    UniqueConstraint("part_id", "insert_part_id"),
)

history = Table(
    "history", meta,
    Column("id", Integer, primary_key=True),
    Column("entity", String(30), nullable=False),     # project, variant, part, revision, bom
    Column("entity_id", Integer, nullable=False),
    Column("action", String(40), nullable=False),     # created, updated, revision_added, ...
    Column("detail", JSON),                           # e.g. {"field": {"old": .., "new": ..}}
    Column("user", String(100), default=""),
    Column("at", DateTime, default=now),
    Index("ix_history_entity", "entity", "entity_id"),
)


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or f"sqlite:///{ROOT / 'data' / 'projects.sqlite'}"


@lru_cache(maxsize=4)
def _engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk(dbapi_con, _):
            dbapi_con.execute("PRAGMA foreign_keys = ON")
    meta.create_all(engine)
    _add_new_columns(engine)
    return engine


def _add_new_columns(engine: Engine) -> None:
    """Columns added in a newer version of the app are added to an existing database (data kept)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in meta.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for c in table.columns:
                if c.name not in have:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {c.name} {c.type.compile(engine.dialect)}'))


def engine() -> Engine:
    return _engine(database_url())
