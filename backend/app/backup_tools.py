"""Backup, restore and safe update (standard library only; run from the project folder).

    python backup.py                       zip master_data/, data/ and the CAD storage folder into backups/dtc-backup-<time>.zip
    python backup.py --restore latest      put a backup back (a safety backup of what is there now is made first)
    python backup.py --restore FILE --only data,storage
    python update.py                       backup, then git pull; master_data/ edited by you is never overwritten silently
    python update.py --keep-mine | --take-new     what to do when you AND the new version both changed master_data/

Project data lives in data/ (SQLite) and the storage folder; with PostgreSQL (server mode) use pg_dump for the database.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUPS = "backups"
PARTS = ("master_data", "data", "storage")


class BackupError(Exception):
    pass


def storage_dir(root: Path = ROOT) -> Path:
    """The CAD storage folder: Register settings → storage_folder / DTC_STORAGE_FOLDER, else root/storage."""
    try:
        sys.path.insert(0, str(root))
        from backend.app import register_setup
        p = register_setup.storage_root()
        return p if p.is_absolute() else root / p
    except Exception:
        return root / "storage"


def locations(root: Path = ROOT) -> dict[str, Path]:
    """Where the three parts live. The Windows kit (DTC_Start.bat) keeps them outside the app folder through
    COSTING_DB_PATH / MASTER_DATA_PATH, DATABASE_URL (sqlite) and DTC_STORAGE_FOLDER."""
    md = os.environ.get("COSTING_DB_PATH") or os.environ.get("MASTER_DATA_PATH")
    url = os.environ.get("DATABASE_URL", "")
    return {"master_data": Path(md).parent if md else root / "master_data",
            "data": Path(url.removeprefix("sqlite:///")).parent if url.startswith("sqlite:///") else root / "data",
            "storage": storage_dir(root)}


def backups_dir(root: Path = ROOT) -> Path:
    return Path(os.environ["DTC_BACKUP_FOLDER"]) if os.environ.get("DTC_BACKUP_FOLDER") else root / BACKUPS


def make_backup(root: Path = ROOT, label: str = "dtc-backup") -> Path:
    out_dir = backups_dir(root)
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    manifest = {"created": datetime.now().isoformat(timespec="seconds"), "parts": {}}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for part, folder in locations(root).items():
            n = 0
            if folder.exists():
                for f in sorted(folder.rglob("*")):
                    if f.is_file() and out_dir.resolve() not in f.resolve().parents:      # never zip the backups themselves
                        z.write(f, f"{part}/{f.relative_to(folder).as_posix()}")
                        n += 1
            manifest["parts"][part] = {"files": n, "from": str(folder)}
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return target


def latest(root: Path = ROOT) -> Path:
    files = sorted(backups_dir(root).glob("*.zip"), key=lambda f: f.stat().st_mtime) if backups_dir(root).exists() else []
    if not files:
        raise BackupError("There is no backup in the backups folder yet. Run: python backup.py")
    return files[-1]


def restore(archive: Path, root: Path = ROOT, only: tuple[str, ...] = PARTS) -> dict:
    """Put (part of) a backup back. What is there now is zipped first as dtc-before-restore-*.zip."""
    bad = [p for p in only if p not in PARTS]
    if bad:
        raise BackupError(f"--only takes {', '.join(PARTS)} (got '{bad[0]}').")
    if not archive.exists():
        raise BackupError(f"Backup file not found: {archive}")
    safety = make_backup(root, "dtc-before-restore")
    loc = locations(root)
    done = {}
    with zipfile.ZipFile(archive) as z:
        for part in only:
            names = [n for n in z.namelist() if n.startswith(part + "/") and not n.endswith("/")]
            if not names:
                done[part] = 0
                continue
            folder = loc[part].resolve()
            if folder.exists():
                shutil.rmtree(folder)
            for n in names:
                dest = (folder / n[len(part) + 1:]).resolve()
                if folder not in dest.parents:                       # never write outside the target folder
                    raise BackupError(f"The backup contains an unsafe path: {n}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
            done[part] = len(names)
    return {"restored": done, "safety_backup": str(safety)}


# ---------- update ----------

def _git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise BackupError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.rstrip("\n")


def update(root: Path = ROOT, mode: str = "ask") -> dict:
    """Backup, then pull. mode: ask (stop if both sides changed master_data/), keep-mine, take-new."""
    if not (root / ".git").exists():
        raise BackupError("This folder is not a git clone (it came from a ZIP). On Windows use DTC_Update.bat from the update kit "
                          "(README: Install and update on Windows): it backs up, installs the new ZIP and merges your master data.")
    backup = make_backup(root, "dtc-before-update")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    _git(root, "fetch", "origin", branch)
    mine = bool(_git(root, "status", "--porcelain", "--", "master_data").strip())
    theirs = bool(_git(root, "diff", "--name-only", "HEAD", f"origin/{branch}", "--", "master_data").strip())
    other = [l for l in _git(root, "status", "--porcelain").splitlines() if not l[3:].startswith(("master_data", BACKUPS))]
    if other:
        raise BackupError("Other files in this folder were changed (" + ", ".join(l[3:] for l in other[:5]) + "). Commit or undo them first; your backup is " + str(backup))
    keep = None
    if mine and theirs:
        if mode == "ask":
            raise BackupError("You changed master_data/ AND the new version changes it too (new example rows, formulas or machines). Nothing was changed. "
                              f"Your backup: {backup}. Choose: --keep-mine (keep your master data; new example rows will be missing) or --take-new "
                              "(use the new master data; your own edits stay only in the backup). Best: send me the backup and I merge the new rows into your file.")
        if mode == "keep-mine":
            keep = {f: f.read_bytes() for f in (root / "master_data").rglob("*") if f.is_file()}
        _git(root, "checkout", "--", "master_data")                 # the pull may now take the new files
    _git(root, "pull", "--ff-only", "origin", branch)
    for f, data in (keep or {}).items():
        f.write_bytes(data)
    state = ("kept yours" if keep else "new version (yours is in the backup)" if mine and theirs else "kept yours" if mine else "unchanged by you")
    return {"backup": str(backup), "master_data": state, "new_master_data_in_update": theirs,
            "next": "pip install -r requirements.txt, then restart the app"}


def main(argv=None, root: Path = ROOT, prog: str = "backup") -> int:
    ap = argparse.ArgumentParser(prog=prog)
    if prog == "update":
        g = ap.add_mutually_exclusive_group()
        g.add_argument("--keep-mine", action="store_true")
        g.add_argument("--take-new", action="store_true")
    else:
        ap.add_argument("--restore", metavar="FILE|latest")
        ap.add_argument("--only", default=",".join(PARTS), help="comma list of master_data,data,storage")
    a = ap.parse_args(argv)
    try:
        if prog == "update":
            res = update(root, "keep-mine" if a.keep_mine else "take-new" if a.take_new else "ask")
            print(json.dumps(res, indent=2))
        elif a.restore:
            archive = latest(root) if a.restore == "latest" else Path(a.restore)
            print(json.dumps(restore(archive, root, tuple(x.strip() for x in a.only.split(",") if x.strip())), indent=2))
        else:
            p = make_backup(root)
            print(f"Backup written: {p}  ({p.stat().st_size / 1e6:.1f} MB). Keep a copy outside this folder.")
    except BackupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
