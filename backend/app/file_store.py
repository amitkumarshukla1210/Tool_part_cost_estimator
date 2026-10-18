"""CAD file storage: every file is kept once, under its SHA-256 checksum.

    <storage folder>/files/ab/abcdef....step

The storage folder is a setting in master data (Part register setup → Register
settings → storage_folder). The database keeps the original name, size,
checksum and the path relative to the storage folder, so the folder can be
moved (e.g. to a server disk) by changing that one setting.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select

from . import projects_db as db
from . import register_setup


def _root() -> Path:
    return register_setup.storage_root()


def put(content: bytes, original_name: str, kind: str, conn) -> dict:
    """Store bytes (if new) and return the files row."""
    sha = hashlib.sha256(content).hexdigest()
    row = conn.execute(select(db.files).where(db.files.c.sha256 == sha)).mappings().first()
    if row:
        return dict(row)
    suffix = Path(original_name).suffix.lower()[:10]
    rel = Path("files") / sha[:2] / f"{sha}{suffix}"
    target = _root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(content)
        tmp.replace(target)
    res = conn.execute(db.files.insert().values(sha256=sha, original_name=original_name, stored_path=rel.as_posix(),
                                                size_bytes=len(content), kind=kind))
    return dict(conn.execute(select(db.files).where(db.files.c.id == res.inserted_primary_key[0])).mappings().one())


def path_of(file_row: dict) -> Path:
    return _root() / file_row["stored_path"]


def scratch_dir(name: str) -> Path:
    """A working folder inside storage (e.g. for an assembly import waiting for confirmation)."""
    p = _root() / "imports" / name
    p.mkdir(parents=True, exist_ok=True)
    return p
