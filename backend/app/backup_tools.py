"""Backup, restore and safe update (standard library only; run from the project folder).

    python backup.py                       zip master_data/, data/ and the CAD storage folder into backups/dtc-backup-<time>.zip
    python backup.py --restore latest      put a backup back (a safety backup of what is there now is made first)
    python backup.py --restore FILE --only data,storage
    python update.py                       backup, then git pull; master_data/ edited by you is never overwritten silently
    python update.py --keep-mine | --take-new     what to do when you AND the new version both changed master_data/
    python upgrade.py [FILE.zip]           upgrade from a downloaded ZIP of a newer version (GitHub "Download ZIP" or releases/Vn/): backup, new code over
                                           the old, your data/, storage/ and master_data/ kept, new master-data rows added, self-test, undo on failure

Project data lives in data/ (SQLite) and the storage folder; with PostgreSQL (server mode) use pg_dump for the database.
"""

from __future__ import annotations

import argparse
import json
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
    return {"master_data": root / "master_data", "data": root / "data", "storage": storage_dir(root)}


def make_backup(root: Path = ROOT, label: str = "dtc-backup") -> Path:
    out_dir = root / BACKUPS
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    manifest = {"created": datetime.now().isoformat(timespec="seconds"), "parts": {}}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for part, folder in locations(root).items():
            n = 0
            if folder.exists():
                for f in sorted(folder.rglob("*")):
                    if f.is_file():
                        z.write(f, f"{part}/{f.relative_to(folder).as_posix()}")
                        n += 1
            manifest["parts"][part] = {"files": n, "from": str(folder)}
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return target


def latest(root: Path = ROOT) -> Path:
    files = sorted((root / BACKUPS).glob("*.zip")) if (root / BACKUPS).exists() else []
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


# ---------- list, upload and restore by name (the Backup page) ----------

def list_backups(root: Path = ROOT) -> list[dict]:
    d = root / BACKUPS
    out = []
    for f in sorted(d.glob("*.zip"), reverse=True) if d.exists() else []:
        try:
            with zipfile.ZipFile(f) as z:
                m = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
        except zipfile.BadZipFile:
            continue
        out.append({"name": f.name, "bytes": f.stat().st_size, "created": m.get("created") or datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                    "files": {k: v.get("files") for k, v in (m.get("parts") or {}).items()}})
    return out


def backup_path(name: str, root: Path = ROOT) -> Path:
    p = (root / BACKUPS / Path(name).name)
    if not p.exists() or p.suffix != ".zip":
        raise BackupError(f"Backup '{name}' not found.")
    return p


def add_upload(content: bytes, filename: str, root: Path = ROOT) -> Path:
    """Keep a backup ZIP from outside (your laptop copy) in the backups folder after checking that it is one of ours."""
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            if "manifest.json" not in names or not any(n.split("/")[0] in PARTS for n in names):
                raise BackupError("This ZIP is not a Design to Cost backup (no manifest.json, master_data/, data/ or storage/).")
    except zipfile.BadZipFile:
        raise BackupError("This file is not a ZIP.") from None
    out_dir = root / BACKUPS
    out_dir.mkdir(exist_ok=True)
    target = out_dir / (Path(filename).stem[:60].replace(" ", "_") + "-uploaded-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
    target.write_bytes(content)
    return target


# ---------- upgrade from a ZIP of a newer version ----------

NEVER_TOUCHED = ("data", "storage", BACKUPS, ".venv", "venv", ".git", "upgrades")
MANIFEST = ".installed_files.json"


def _port_busy(port: int = 8000) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _zip_layout(z: zipfile.ZipFile) -> tuple[str, str]:
    """(prefix of the project inside the ZIP, its VERSION). GitHub's Download ZIP has one top folder."""
    marker = next((n for n in z.namelist() if n.endswith("backend/app/main.py")), None)
    if not marker:
        raise BackupError("This ZIP is not a Design to Cost version (no backend/app/main.py inside).")
    prefix = marker[: -len("backend/app/main.py")]
    version = z.read(prefix + "VERSION").decode().strip() if prefix + "VERSION" in z.namelist() else ""
    if not version:
        raise BackupError("This ZIP has no VERSION file: it is not a numbered release (V0, V1 …).")
    return prefix, version


def find_zip(root: Path = ROOT) -> Path:
    """The newest ZIP in ./upgrades, else the newest Downloads ZIP that looks like this project."""
    cands = list((root / "upgrades").glob("*.zip")) if (root / "upgrades").exists() else []
    if not cands:
        dl = Path.home() / "Downloads"
        cands = [f for f in dl.glob("*.zip") if any(k in f.name.lower() for k in ("tool_part_cost_estimator", "designtocost", "design_to_cost"))] if dl.exists() else []
    if not cands:
        raise BackupError("No ZIP given and none found. Put the downloaded ZIP in the folder 'upgrades' (next to this file) or run: python upgrade.py path\\to\\file.zip")
    return max(cands, key=lambda f: f.stat().st_mtime)


def _code_files(root: Path) -> list[str]:
    out = []
    for f in root.rglob("*"):
        rel = f.relative_to(root).as_posix()
        if f.is_file() and rel.split("/")[0] not in NEVER_TOUCHED + ("master_data",) and "__pycache__" not in rel and not rel.startswith("."):
            out.append(rel)
    return out


def _restore_code(code_zip: Path, root: Path, new_files: set[str]) -> None:
    old = set()
    with zipfile.ZipFile(code_zip) as z:
        for n in z.namelist():
            old.add(n)
            dest = root / n
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(n))
    for rel in new_files - old:
        (root / rel).unlink(missing_ok=True)


def upgrade_from_zip(zip_path: Path, root: Path = ROOT, force: bool = False, ignore_running: bool = False, pip: bool = True) -> dict:
    """Put a newer version over this installation. Your data/, storage/ and master_data/ are kept; new rows are added by the migration; on any failure the
    old code and your data are put back."""
    from .version import current, number
    if not Path(zip_path).exists():
        raise BackupError(f"File not found: {zip_path}")
    if not ignore_running and _port_busy():
        raise BackupError("The tool is running (http://127.0.0.1:8000 answers). Close its window first, then run the upgrade again.")
    with zipfile.ZipFile(zip_path) as z:
        prefix, new_v = _zip_layout(z)
        old_v = current(root)
        if number(new_v) <= number(old_v) and not force:
            raise BackupError(f"This ZIP is version {new_v}; you already have {old_v}. Download the newer ZIP (or use --force to reinstall the same version).")
        safety = make_backup(root, f"dtc-before-upgrade-{old_v}-to-{new_v}")
        old_files = _code_files(root)
        code_zip = root / BACKUPS / f"dtc-code-{old_v}-before-{new_v}.zip"
        with zipfile.ZipFile(code_zip, "w", zipfile.ZIP_DEFLATED) as cz:
            for rel in old_files:
                cz.write(root / rel, rel)
        new_files: set[str] = set()
        kept_master = []
        try:
            for n in z.namelist():
                if not n.startswith(prefix) or n.endswith("/"):
                    continue
                rel = n[len(prefix):]
                top = rel.split("/")[0]
                if not rel or top in NEVER_TOUCHED or "__pycache__" in rel or rel.startswith("releases/"):
                    continue
                dest = root / rel
                if top == "master_data":
                    if dest.exists():
                        kept_master.append(rel)           # your rates, machines and formulas stay; new rows come from the migration
                        continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
                if top != "master_data":
                    new_files.add(rel)
            manifest = root / MANIFEST
            previous = set(json.loads(manifest.read_text())) if manifest.exists() else set(old_files)
            removed = sorted(f for f in previous - new_files if (root / f).exists() and f.split("/")[0] not in ("master_data",))
            for f in removed:
                (root / f).unlink(missing_ok=True)
            manifest.write_text(json.dumps(sorted(new_files)))
            steps = {}
            if pip and (root / "requirements.txt").exists():
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=root, capture_output=True, text=True)
                if r.returncode != 0:
                    raise BackupError("pip install failed: " + (r.stderr or r.stdout)[-400:])
                steps["pip"] = "requirements installed"
            r = subprocess.run([sys.executable, "-m", "backend.app.migrate"], cwd=root, capture_output=True, text=True)
            if r.returncode != 0:
                raise BackupError("The migration failed: " + (r.stderr or r.stdout)[-500:])
            steps["migrate"] = "ok"
        except Exception as exc:
            _restore_code(code_zip, root, new_files)
            restore(safety, root)
            raise BackupError(f"Upgrade to {new_v} failed and was undone (old code and data are back): {exc}") from None
    return {"from": old_v, "to": new_v, "backup": str(safety), "code_backup": str(code_zip), "files_updated": len(new_files), "files_removed": len(removed),
            "master_data_kept": kept_master, "steps": steps, "next": "Start the tool again (Start_Tool) and check one known part"}


# ---------- update ----------

def _git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise BackupError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.rstrip("\n")


def update(root: Path = ROOT, mode: str = "ask") -> dict:
    """Backup, then pull. mode: ask (stop if both sides changed master_data/), keep-mine, take-new."""
    if not (root / ".git").exists():
        raise BackupError("This folder is not a git clone (it came from a ZIP). To update: 1) python backup.py  2) unzip the new version over this folder, "
                          "3) python backup.py --restore latest --only data,storage  4) keep your master_data/ from the backup if you changed it "
                          "(python backup.py --restore latest --only master_data), or send me the backup to merge the new example rows.")
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
    if prog == "upgrade":
        ap.add_argument("zipfile", nargs="?", help="ZIP of the new version (default: newest in ./upgrades or Downloads)")
        ap.add_argument("--force", action="store_true", help="reinstall the same or an older version")
        ap.add_argument("--ignore-running", action="store_true")
    elif prog == "update":
        g = ap.add_mutually_exclusive_group()
        g.add_argument("--keep-mine", action="store_true")
        g.add_argument("--take-new", action="store_true")
    else:
        ap.add_argument("--restore", metavar="FILE|latest")
        ap.add_argument("--only", default=",".join(PARTS), help="comma list of master_data,data,storage")
    a = ap.parse_args(argv)
    try:
        if prog == "upgrade":
            res = upgrade_from_zip(Path(a.zipfile) if a.zipfile else find_zip(root), root, a.force, a.ignore_running)
            print(json.dumps(res, indent=2))
        elif prog == "update":
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
