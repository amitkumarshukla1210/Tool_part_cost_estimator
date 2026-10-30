"""Design to Cost on Windows: start, update, back up, restore and roll back (standard library only).

This file and the DTC_*.bat files live in the folder ABOVE the app (the "base folder"), never inside it:

    <base folder>\\
        Tool_part_cost_estimator\\   the app: replaced by every update (the old one is moved to DTC_Old\\)
        DTC_Data\\                   YOUR data, never replaced: master_data\\ (rates, machines, formulas),
                                    data\\ (projects, parts, costs), storage\\ (CAD files), logs\\
        DTC_Backups\\                backup ZIPs (copy them to OneDrive / a pen drive too: backup_copy_to)
        DTC_Downloads\\              new version ZIPs (downloaded here, or put one here yourself)
        DTC_Old\\                    the last app versions, for DTC_Rollback.bat
        venv\\                       the Python libraries (kept between updates, so no 200 MB download each time)
        dtc_settings.ini            port, GitHub, backup copy folder, ...

    python dtc_manager.py start      backup once a day, then run the app on http://127.0.0.1:8000
    python dtc_manager.py update     backup, new version (GitHub or a ZIP), merge master data, install
    python dtc_manager.py backup     backup now
    python dtc_manager.py restore    put a backup back (yours now is backed up first)
    python dtc_manager.py rollback   back to the version before the last update, with the data of that moment
    python dtc_manager.py reset-password [user]   new password for a user (e.g. a forgotten admin password), from this PC only
    python dtc_manager.py status     where everything is, installed version, last backup
"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "DTC_Data"
BACKUPS = BASE / "DTC_Backups"
DOWNLOADS = BASE / "DTC_Downloads"
OLD = BASE / "DTC_Old"
VENV = BASE / "venv"
STAGING = BASE / "_dtc_new"
SETTINGS = BASE / "dtc_settings.ini"
VERSION = DATA / "version.json"
MANAGED = {DATA.name, BACKUPS.name, DOWNLOADS.name, OLD.name, VENV.name, STAGING.name}
PARTS = ("master_data", "data", "storage")
KIT_FILES = ("dtc_manager.py", "DTC_Start.bat", "DTC_Update.bat", "DTC_Backup.bat", "DTC_Restore.bat", "DTC_Rollback.bat",
             "DTC_ResetPassword.bat")

DEFAULT_SETTINGS = """\
; Design to Cost: settings of the Windows kit (dtc_manager.py). Lines starting with ; are notes.
[dtc]
; the app folder next to this file
app_folder = Tool_part_cost_estimator
; the app runs on http://127.0.0.1:<port>
port = 8000
; where new versions come from
github_repo = amitkumarshukla1210/Tool_part_cost_estimator
branch = main
; only for a PRIVATE repository: a read-only GitHub token (Settings > Developer settings > Fine-grained tokens,
; this repository only, permission Contents: Read-only). Leave empty when the repository is public.
github_token =
; a second copy of every backup, e.g. C:\\Users\\<you>\\OneDrive\\DTC_Backups (empty = only DTC_Backups)
backup_copy_to =
; backups kept in DTC_Backups (older ones are deleted; the first migration backup is always kept)
keep_backups = 30
; DTC_Start.bat makes a backup when the last one is older than this many days (0 = never)
auto_backup_days = 1
; CAD storage folder (empty = DTC_Data\\storage)
storage_folder =
; the Python used to create venv\\ (empty = the one running this script); CadQuery needs 3.10 - 3.12
python =
"""


class KitError(Exception):
    pass


# ---------- small helpers ----------

def say(msg: str = "") -> None:
    print(msg, flush=True)


def ask(question: str, default: str = "") -> str:
    if not sys.stdin or not sys.stdin.isatty():
        return default
    try:
        a = input(f"{question} ").strip()
    except EOFError:
        return default
    return a or default


def yes(question: str, default: bool = True) -> bool:
    a = ask(f"{question} [{'Y/n' if default else 'y/N'}]", "y" if default else "n")
    return a.lower().startswith("y")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def cfg() -> configparser.SectionProxy:
    if not SETTINGS.exists():
        SETTINGS.write_text(DEFAULT_SETTINGS, encoding="utf-8")
    c = configparser.ConfigParser(inline_comment_prefixes=None)
    c.read_string(DEFAULT_SETTINGS)
    c.read(SETTINGS, encoding="utf-8")
    return c["dtc"]


def app_dir() -> Path:
    return BASE / (cfg().get("app_folder") or "Tool_part_cost_estimator")


def storage_dir() -> Path:
    s = cfg().get("storage_folder", "").strip()
    return Path(s) if s else DATA / "storage"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def app_env() -> dict:
    env = dict(os.environ)
    env.update({
        "COSTING_DB_PATH": str(DATA / "master_data" / "costing_db.sqlite"),
        "MASTER_DATA_PATH": str(DATA / "master_data" / "master_data.xlsx"),
        "DATABASE_URL": "sqlite:///" + (DATA / "data" / "projects.sqlite").as_posix(),
        "DTC_STORAGE_FOLDER": str(storage_dir()),
        "DTC_BACKUP_FOLDER": str(BACKUPS),
        "DTC_DATA_FOLDER": str(DATA),               # Admin page: version.json and the update reports in logs\
        "DTC_KIT_MANAGER": str(BASE / "dtc_manager.py"),
        "DTC_PORT": str(port()),
        "DTC_MODE": "server",                       # logins always on (the first start asks for the first admin)
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def port() -> int:
    return int(cfg().get("port") or 8000)


def running(p: int | None = None) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", p or port())) == 0


def need_stopped() -> None:
    if running():
        raise KitError(f"The app is running (http://127.0.0.1:{port()}). Close the DTC_Start window (or press Ctrl+C in it), then try again.")


def is_app(folder: Path) -> bool:
    return (folder / "backend" / "app" / "main.py").exists()


def read_version() -> dict:
    try:
        return json.loads(VERSION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_version(info: dict) -> None:
    VERSION.parent.mkdir(parents=True, exist_ok=True)
    VERSION.write_text(json.dumps(info, indent=2), encoding="utf-8")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
    except OSError as exc:
        raise KitError(f"Could not move {src} -> {dst}: {exc}. Close every window, Explorer view or terminal that has this folder open "
                       "(and Excel files from it), then try again.") from exc


# ---------- backup / restore (same ZIP layout as backup.py inside the app) ----------

def locations() -> dict[str, Path]:
    return {"master_data": DATA / "master_data", "data": DATA / "data", "storage": storage_dir()}


def zip_parts(target: Path, parts: dict[str, Path]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"created": datetime.now().isoformat(timespec="seconds"), "parts": {}}
    tmp = target.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for part, folder in parts.items():
            n = 0
            if folder.exists():
                for f in sorted(folder.rglob("*")):
                    if f.is_file() and not f.name.startswith(".write-test") and target.parent.resolve() not in f.resolve().parents:
                        z.write(f, f"{part}/{f.relative_to(folder).as_posix()}")
                        n += 1
            manifest["parts"][part] = {"files": n, "from": str(folder)}
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    tmp.replace(target)
    return target


def backup(label: str = "dtc-backup") -> Path:
    if not (DATA / "master_data").exists():
        raise KitError("There is no data to back up yet (DTC_Data is empty). Run DTC_Update.bat first.")
    z = zip_parts(BACKUPS / f"{label}-{stamp()}.zip", locations())
    say(f"Backup written: {z}  ({z.stat().st_size / 1e6:.1f} MB)")
    copy_to = cfg().get("backup_copy_to", "").strip()
    if copy_to:
        try:
            Path(copy_to).mkdir(parents=True, exist_ok=True)
            shutil.copy2(z, Path(copy_to) / z.name)
            say(f"Copy written:   {Path(copy_to) / z.name}")
        except OSError as exc:
            say(f"WARNING: the copy to {copy_to} failed ({exc}). The backup in DTC_Backups is fine.")
    prune_backups()
    return z


def backup_list() -> list[Path]:
    return sorted(BACKUPS.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True) if BACKUPS.exists() else []


def prune_backups() -> None:
    keep = int(cfg().get("keep_backups") or 30)
    for f in [f for f in backup_list() if not f.name.startswith("dtc-before-migration")][keep:]:
        f.unlink(missing_ok=True)


def restore(archive: Path, only: tuple[str, ...] = PARTS) -> Path | None:
    if not zipfile.is_zipfile(archive):
        raise KitError(f"Not a backup ZIP: {archive}")
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if not any(n.startswith(p + "/") for p in PARTS for n in names):
            raise KitError(f"{archive.name} holds no master_data/, data/ or storage/ folder: it is not a Design to Cost backup.")
        safety = backup("dtc-before-restore") if (DATA / "master_data").exists() else None
        loc = locations()
        for part in only:
            files = [n for n in names if n.startswith(part + "/")]
            if not files:
                continue
            folder = loc[part].resolve()
            if folder.exists():
                shutil.rmtree(folder)
            for n in files:
                dest = (folder / n[len(part) + 1:]).resolve()
                if folder not in dest.parents:
                    raise KitError(f"The backup contains an unsafe path: {n}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
            say(f"  {part}: {len(files)} file(s) restored")
    return safety


# ---------- first use: move the data out of an old app folder ----------

def find_old_apps() -> list[Path]:
    found = []
    for d in sorted(BASE.iterdir()):
        if not d.is_dir() or d.name in MANAGED:
            continue
        if is_app(d):
            found.append(d)
        else:
            found += [s for s in sorted(d.iterdir()) if s.is_dir() and is_app(s)] if os.access(d, os.R_OK) else []
    return found


def old_storage_setting(app: Path) -> str:
    import sqlite3
    db = app / "master_data" / "costing_db.sqlite"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM register_settings WHERE key = 'storage_folder'").fetchone()
        finally:
            con.close()
        return (row[0] or "storage") if row else "storage"
    except Exception:
        return "storage"


def migrate_from(app: Path) -> None:
    """Copy master_data, data, storage and backups of an old app folder into DTC_Data / DTC_Backups (the old folder is not changed)."""
    raw = old_storage_setting(app)
    storage = Path(raw) if Path(raw).is_absolute() else app / raw
    parts = {"master_data": app / "master_data", "data": app / "data", "storage": storage}
    say(f"Your data is moved out of {app} into {DATA}.")
    z = zip_parts(BACKUPS / f"dtc-before-migration-{stamp()}.zip", parts)
    say(f"  safety backup of the old folder's data: {z}")
    for part in ("master_data", "data"):
        if parts[part].exists():
            shutil.copytree(parts[part], DATA / part, dirs_exist_ok=True)
    if Path(raw).is_absolute():
        say(f"  CAD files stay in {storage} (an absolute folder in your settings); written to dtc_settings.ini")
        text = SETTINGS.read_text(encoding="utf-8")
        SETTINGS.write_text(text.replace("\nstorage_folder =\n", f"\nstorage_folder = {storage}\n"), encoding="utf-8")
    elif storage.exists():
        shutil.copytree(storage, DATA / "storage", dirs_exist_ok=True)
    for f in (app / "backups").glob("*.zip") if (app / "backups").exists() else []:
        shutil.copy2(f, BACKUPS / f.name)
    for part in PARTS:
        src = parts[part] if part != "storage" else storage
        n = sum(1 for f in src.rglob("*") if f.is_file()) if src.exists() else 0
        say(f"  {part}: {n} file(s)")
    write_version({"migrated_from": str(app)})


def ensure_data() -> Path | None:
    """DTC_Data in place; on first use take the data of the old app folder. Returns the old app folder found (to retire), if any."""
    olds = find_old_apps()
    if (DATA / "master_data" / "costing_db.sqlite").exists():
        stray = app_dir() / "data" / "projects.sqlite"
        if stray.exists():
            say(f"NOTE: {stray} exists: the app was once started without DTC_Start.bat. Your real data is in {DATA}; "
                "that file is moved to DTC_Old with the old app folder.")
        return None
    if not olds:
        say("No earlier installation found: a fresh install (the new version's example master data is used).")
        return None
    app = olds[0]
    if len(olds) > 1:
        say("More than one app folder was found:")
        for i, d in enumerate(olds, 1):
            db = d / "data" / "projects.sqlite"
            say(f"  {i} = {d}   (projects last changed {datetime.fromtimestamp(db.stat().st_mtime):%d %b %Y %H:%M})" if db.exists() else f"  {i} = {d}   (no project data)")
        a = ask(f"Which one holds your current data? [1-{len(olds)}, default 1]", "1")
        app = olds[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(olds) else olds[0]
    migrate_from(app)
    return app


# ---------- getting a new version ----------

def zip_root(z: zipfile.ZipFile) -> str | None:
    for n in z.namelist():
        if n.endswith("backend/app/main.py"):
            return n[: -len("backend/app/main.py")]
    return None


def valid_zip(p: Path) -> bool:
    try:
        with zipfile.ZipFile(p) as z:
            r = zip_root(z)
            return r is not None and f"{r}requirements.txt" in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def local_zips() -> list[Path]:
    places = [DOWNLOADS, BASE, Path.home() / "Downloads"]
    found = []
    for d in places:
        if d.exists():
            found += [f for f in d.glob("*.zip") if "tool_part_cost_estimator" in f.name.lower() or d == DOWNLOADS]
    return sorted({f.resolve() for f in found if valid_zip(f)}, key=lambda f: f.stat().st_mtime, reverse=True)


def _get(url: str, token: str, accept: str) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={"User-Agent": "dtc-manager", "Accept": accept})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return req


def latest_commit() -> dict:
    c = cfg()
    try:
        req = _get(f"https://api.github.com/repos/{c['github_repo']}/commits/{c['branch']}", c.get("github_token", "").strip(), "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        return {"commit": d["sha"][:12], "date": d["commit"]["committer"]["date"], "message": d["commit"]["message"].splitlines()[0]}
    except Exception:
        return {}


def download() -> Path:
    c = cfg()
    repo, branch, token = c["github_repo"], c["branch"], c.get("github_token", "").strip()
    url = (f"https://api.github.com/repos/{repo}/zipball/{branch}" if token else f"https://github.com/{repo}/archive/refs/heads/{branch}.zip")
    DOWNLOADS.mkdir(exist_ok=True)
    target = DOWNLOADS / f"Tool_part_cost_estimator-{branch}-{stamp()}.zip"
    say(f"Downloading {repo} ({branch}) from GitHub ...")
    errors = []
    try:
        with urllib.request.urlopen(_get(url, token, "application/vnd.github+json"), timeout=120) as r, open(target, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as exc:
        errors.append(f"Python: {exc}")
        if os.name == "nt":                                             # PowerShell uses the Windows proxy and certificate settings
            hdr = f"@{{Authorization='Bearer {token}'}}" if token else "@{}"
            ps = f"$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Headers {hdr} -Uri '{url}' -OutFile '{target}'"
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"PowerShell: {(r.stderr or r.stdout).strip()[:300]}")
    if not valid_zip(target):
        target.unlink(missing_ok=True)
        hint = ("The repository looks private: put a read-only token in dtc_settings.ini (github_token), or download the ZIP yourself."
                if any("404" in e for e in errors) else "Check the internet / proxy, or download the ZIP yourself.")
        raise KitError("Download failed. " + hint + "\n  " + "\n  ".join(errors) +
                       f"\nBy hand: open https://github.com/{repo} (logged in), Code > Download ZIP, save the ZIP into {DOWNLOADS} "
                       "(or your Downloads folder) and run DTC_Update.bat again.")
    say(f"Downloaded: {target} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


def choose_zip(arg: str | None) -> tuple[Path, dict]:
    if arg and arg != "download":
        p = Path(arg.strip('"'))
        if not valid_zip(p):
            raise KitError(f"{p} is not a ZIP of this app (it needs backend/app/main.py and requirements.txt).")
        return p, {}
    if arg == "download":
        return download(), latest_commit()
    installed = read_version()
    zips = [z for z in local_zips() if sha256(z) != installed.get("sha256")]
    say("Where does the new version come from?")
    say(f"  1 = download the newest version from GitHub ({cfg()['github_repo']}, branch {cfg()['branch']})")
    if zips:
        say(f"  2 = the ZIP {zips[0]}  ({datetime.fromtimestamp(zips[0].stat().st_mtime):%d %b %Y %H:%M})")
    say("  3 = type the full path of a ZIP")
    a = ask("Your choice [1]:", "1")
    if a == "2" and zips:
        return zips[0], {}
    if a == "3":
        return choose_zip(ask("Path of the ZIP:", "") or "download")
    return download(), latest_commit()


# ---------- python environment ----------

def preferred_python() -> str:
    """A Python CadQuery has wheels for (3.12, 3.11, 3.10) through the py launcher, else the one running this script."""
    if os.name == "nt" and shutil.which("py"):
        for v in ("3.12", "3.11", "3.10"):
            r = subprocess.run(["py", f"-{v}", "-c", "import sys; print(sys.executable)"], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
    return sys.executable


def ensure_venv() -> None:
    if venv_python().exists():
        return
    base_py = cfg().get("python", "").strip() or preferred_python()
    say(f"Creating the Python environment {VENV} with {base_py} (one time) ...")
    r = subprocess.run([base_py, "-m", "venv", str(VENV)])
    if r.returncode != 0 or not venv_python().exists():
        raise KitError("Could not create the Python environment. Install Python 3.12 from python.org (tick 'Add python.exe to PATH') "
                       "or set python = <path to python.exe> in dtc_settings.ini.")


def pip_install(app: Path) -> None:
    say("Installing / checking the libraries (first time: several minutes, CadQuery is about 200 MB) ...")
    py = str(venv_python())
    subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
    r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(app / "requirements.txt")], cwd=app)
    if r.returncode != 0:
        raise KitError("Installing the libraries failed (see the messages above). Nothing was changed: your app and data are as before. "
                       "Common causes: no internet / proxy, or a Python version CadQuery does not support (use Python 3.12; "
                       "set python = in dtc_settings.ini and delete the venv folder).")


def smoke_test(app: Path) -> None:
    r = subprocess.run([str(venv_python()), "-c", "import backend.app.main"], cwd=app, env=app_env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise KitError("The new version does not start (nothing was changed; your app and data are as before):\n"
                       + (r.stderr or r.stdout).strip()[-1500:])


# ---------- commands ----------

def cmd_backup(_args) -> None:
    backup()
    say("Keep a copy outside this laptop as well (OneDrive / pen drive): set backup_copy_to in dtc_settings.ini to do it automatically.")


def cmd_update(args) -> None:
    need_stopped()
    BACKUPS.mkdir(exist_ok=True)
    cfg()
    start_after = "--start" in args
    no_browser = "--no-browser" in args
    zip_arg = next((arg for arg in args if arg not in ("--start", "--no-browser")), None)
    old_app = ensure_data()
    v = read_version()
    if not old_app and v.get("migrated_from") and not v.get("installed") and is_app(Path(v["migrated_from"])):
        old_app = Path(v["migrated_from"])                         # data moved out earlier, the update did not finish then
    before = backup("dtc-before-update") if (DATA / "master_data").exists() else None
    src, info = choose_zip(zip_arg)

    staging = Path(tempfile.mkdtemp(prefix=f"{STAGING.name}_", dir=BASE))
    with zipfile.ZipFile(src) as z:
        root = zip_root(z)
        say(f"Unpacking {src.name} ...")
        z.extractall(staging)
    new_app = staging / root.rstrip("/") if root else staging

    try:
        ensure_venv()
        pip_install(new_app)
        smoke_test(new_app)
    except KitError:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # the swap: old app folder(s) to DTC_Old, the new one in place
    t = stamp()
    current, retired = app_dir(), []
    for d in [current] + ([old_app] if old_app and old_app.resolve() != current.resolve() else []):
        if d.exists():
            dest = OLD / f"{d.name}-{t}"
            move(d, dest)
            retired.append(dest)
            if d.parent != BASE and not any(d.parent.iterdir()):
                d.parent.rmdir()                                   # the empty outer folder of a double-unzipped ZIP
    move(new_app, current)
    shutil.rmtree(staging, ignore_errors=True)

    # master data: yours + the new version's new rows
    log_dir = DATA / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    report = ""
    if not (DATA / "master_data" / "costing_db.sqlite").exists():
        shutil.copytree(current / "master_data", DATA / "master_data", dirs_exist_ok=True)
        report = "Fresh install: the example master data of this version was copied to DTC_Data\\master_data."
    elif (current / "backend" / "app" / "upgrade_tools.py").exists():
        say("Merging the new version's master data into yours ...")
        r = subprocess.run([str(venv_python()), "-m", "backend.app.upgrade_tools", "merge", "--mine", str(DATA / "master_data"),
                            "--new", str(current / "master_data")], cwd=current, env=app_env(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise KitError("Merging the master data failed; your master data was not changed. Run DTC_Rollback.bat to go back, "
                           "and send this message:\n" + (r.stderr or r.stdout).strip()[-1500:])
        report = r.stdout.strip()
    else:
        report = "This version has no master-data merge tool: your master data was kept as it is."
    for name in KIT_FILES:                                          # the kit updates itself
        f = current / "windows" / name
        if f.exists() and (not (BASE / name).exists() or (BASE / name).read_bytes() != f.read_bytes()):
            shutil.copy2(f, BASE / name)
    for f in sorted(OLD.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[3:] if OLD.exists() else []:
        shutil.rmtree(f, ignore_errors=True)                       # keep the last 3 old versions
    release = (current / "VERSION").read_text(encoding="utf-8").strip() if (current / "VERSION").exists() else ""
    write_version({"installed": datetime.now().isoformat(timespec="seconds"), "release": release, "zip": src.name, "sha256": sha256(src),
                   **info, "previous_app": str(retired[0]) if retired else "", "backup_before_update": str(before or "")})
    log = log_dir / f"update-{t}.txt"
    log.write_text(f"Update {t} from {src}\n{json.dumps(info)}\nBackup before the update: {before}\n\n{report}\n", encoding="utf-8")
    say("")
    say(report)
    say("")
    say(f"UPDATE DONE. Report: {log}")
    if before:
        say(f"Your data before the update is in {before}. Something wrong? DTC_Rollback.bat puts the old version and that data back.")
    if start_after:
        cmd_start(["--no-browser"] if no_browser else [])
    elif yes("Start the app now?"):
        cmd_start([])


def cmd_update_wait(_args) -> None:
    deadline = time.monotonic() + 120
    while running():
        if time.monotonic() >= deadline:
            raise KitError("The app did not stop after the update request. Start DTC_Update.bat after closing it.")
        time.sleep(0.5)
    try:
        cmd_update(["download", "--start", "--no-browser"])
    except KitError:
        if is_app(app_dir()) and not running():
            say("The update did not complete; restarting the installed app.")
            cmd_start(["--no-browser"])
        raise


def cmd_start(args) -> None:
    no_browser = "--no-browser" in args
    app = app_dir()
    if not is_app(app) or not venv_python().exists() or not (DATA / "master_data").exists():
        raise KitError("The app is not installed in this folder yet: run DTC_Update.bat first.")
    url = f"http://127.0.0.1:{port()}"
    if running():
        say(f"The app is already running: opening {url}")
        if not no_browser:
            webbrowser.open(url)
        return
    days = float(cfg().get("auto_backup_days") or 0)
    last = backup_list()
    if days and (not last or datetime.fromtimestamp(last[0].stat().st_mtime) < datetime.now() - timedelta(days=days)):
        say("Daily backup ...")
        try:
            backup("dtc-auto")
        except KitError as exc:
            say(f"WARNING: {exc}")

    def open_when_ready():
        for _ in range(120):
            if running():
                webbrowser.open(url)
                return
            time.sleep(1)
    if not no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    v = read_version()
    say(f"Design to Cost {v.get('commit', '')} {v.get('installed', '')[:10]} | data: {DATA}")
    say(f"Running on {url}  -  keep this window open; close it (or press Ctrl+C) to stop the app.")
    try:
        subprocess.run([str(venv_python()), "-m", "backend.app.server_runner"],
                       cwd=app, env=app_env())
    except KeyboardInterrupt:
        pass


def cmd_restore(args) -> None:
    need_stopped()
    if args:
        archive = Path(args[0].strip('"'))
    else:
        items = backup_list()[:15]
        if not items:
            raise KitError(f"No backups in {BACKUPS}. To restore a backup from elsewhere, copy the ZIP into that folder first.")
        say("Backups (newest first):")
        for i, f in enumerate(items, 1):
            say(f"  {i:2} = {f.name}   {datetime.fromtimestamp(f.stat().st_mtime):%d %b %Y %H:%M}   {f.stat().st_size / 1e6:.1f} MB")
        a = ask("Number of the backup to put back (or the full path of a ZIP; Enter = cancel):", "")
        if not a:
            say("Cancelled.")
            return
        archive = items[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(items) else Path(a.strip('"'))
    a = ask("Restore everything (1), only projects + CAD files (2), or only master data (3)? [1]", "1")
    only = {"2": ("data", "storage"), "3": ("master_data",)}.get(a, PARTS)
    if not yes(f"Put {archive.name} back ({', '.join(only)})? What is there now is backed up first.", False):
        say("Cancelled.")
        return
    safety = restore(archive, only)
    say(f"RESTORED. What was there before is in {safety}" if safety else "RESTORED.")


def cmd_rollback(_args) -> None:
    need_stopped()
    v = read_version()
    prev, data_zip = Path(v.get("previous_app") or "-"), Path(v.get("backup_before_update") or "-")
    if not is_app(prev):
        raise KitError("There is no previous version to go back to (DTC_Old has none recorded).")
    say(f"Back to the version in {prev}")
    say(f"with the data of the moment before the update: {data_zip if data_zip.exists() else '(no backup found: data stays as it is)'}")
    say("Projects you changed AFTER the update are then in the safety backup only.")
    if not yes("Go back?", False):
        say("Cancelled.")
        return
    app = app_dir()
    if app.exists():
        move(app, OLD / f"{app.name}-rolled-back-{stamp()}")
    move(prev, app)
    if data_zip.exists():
        restore(data_zip)
    write_version({**v, "installed": datetime.now().isoformat(timespec="seconds"), "previous_app": "", "rolled_back_from": v.get("commit", v.get("zip", ""))})
    say("ROLLED BACK. Start the app with DTC_Start.bat.")


def cmd_status(_args) -> None:
    v = read_version()
    last = backup_list()
    say(f"Base folder:    {BASE}")
    say(f"App:            {app_dir()} {'(installed)' if is_app(app_dir()) else '(NOT installed)'}")
    say(f"Version:        {v.get('release') or '-'} ({v.get('commit') or v.get('zip', '-')})  installed {v.get('installed', '-')}")
    say(f"Your data:      {DATA}")
    say(f"CAD files:      {storage_dir()}")
    say(f"Backups:        {BACKUPS}  ({len(last)}; last {last[0].name if last else 'none'})")
    say(f"Backup copy to: {cfg().get('backup_copy_to') or '(not set)'}")
    say(f"Address:        http://127.0.0.1:{port()} ({'running' if running() else 'not running'})")


def cmd_reset_password(args) -> None:
    """A forgotten password (also the admin's): set a new one from this PC. Only someone at this PC can do it."""
    app = app_dir()
    if not is_app(app) or not venv_python().exists():
        raise KitError("The app is not installed in this folder yet: run DTC_Update.bat first.")
    user = args[0] if args else ask("User name whose password to reset", "admin")
    r = subprocess.run([str(venv_python()), "-m", "backend.app.server_tools", "reset-password", user], cwd=app, env=app_env())
    if r.returncode:
        raise KitError("The password was not changed.")


COMMANDS = {"reset-password": cmd_reset_password, "start": cmd_start, "update": cmd_update, "update-wait": cmd_update_wait,
            "backup": cmd_backup, "restore": cmd_restore, "rollback": cmd_rollback, "status": cmd_status}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        say(__doc__)
        return 2
    if is_app(BASE):
        say("dtc_manager.py must be in the folder ABOVE the app folder, not inside it. Copy the files of the windows folder one level up.")
        return 2
    try:
        COMMANDS[argv[0]](argv[1:])
    except KitError as exc:
        say("")
        say(f"STOPPED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
