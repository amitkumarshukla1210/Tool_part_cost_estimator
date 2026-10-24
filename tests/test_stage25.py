"""Stage 25: versions, ZIP upgrade without losing data, backup and restore on the Backup page, release ZIP."""
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import backup_tools as bt
from backend.app.main import app

REPO = Path(__file__).resolve().parents[1]
client = TestClient(app)


def tracked():
    return [f for f in subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
            if not f.startswith("releases/") and (REPO / f).is_file()]


def install(tmp_path, monkeypatch, version="V0"):
    root = tmp_path / "hosted"
    for f in tracked():
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / f, root / f)
    (root / "VERSION").write_text(version + "\n")
    (root / "data").mkdir()
    import sqlite3
    con = sqlite3.connect(root / "data" / "projects.sqlite")
    con.execute("CREATE TABLE my_marker (note TEXT)")
    con.execute("INSERT INTO my_marker VALUES ('MY PROJECTS')")
    con.commit()
    con.close()
    (root / "storage" / "ab").mkdir(parents=True)
    (root / "storage" / "ab" / "part.step").write_bytes(b"MY STEP")
    monkeypatch.setattr(bt, "storage_dir", lambda r=root: root / "storage")
    for k, v in {"MASTER_DATA_PATH": root / "master_data" / "master_data.xlsx", "COSTING_DB_PATH": root / "master_data" / "costing_db.sqlite",
                 "DATABASE_URL": f"sqlite:///{root / 'data' / 'projects.sqlite'}", "DTC_STORAGE_FOLDER": root / "storage"}.items():
        monkeypatch.setenv(k, str(v))
    return root


def release_zip(tmp_path, version, change=None):
    z = tmp_path / f"DesignToCost-{version}.zip"
    top = f"Tool_part_cost_estimator-main/"           # the folder GitHub's Download ZIP uses
    with zipfile.ZipFile(z, "w") as zf:
        for f in tracked():
            data = (REPO / f).read_bytes()
            if f == "VERSION":
                data = (version + "\n").encode()
            if change and f in change:
                data = change[f]
            if change and change.get(f) is None and f in change:
                continue
            zf.writestr(top + f, data)
        zf.writestr(top + "backend/app/brand_new_feature.py", "VALUE = 1\n")
        zf.writestr(top + "releases/V1/ignored.txt", "x")
    return z


def test_version_is_served_and_numbered():
    assert client.get("/api/version").json()["version"] == (REPO / "VERSION").read_text().strip()
    from backend.app import version
    assert version.number("V12") == 12 and version.number("") == 0


def test_zip_upgrade_keeps_data_and_master_data_adds_files_and_removes_old_ones(tmp_path, monkeypatch):
    root = install(tmp_path, monkeypatch)
    (root / "frontend" / "old_page_removed_in_v1.js").write_text("old")
    (root / bt.MANIFEST).write_text(json.dumps(sorted(set(bt._code_files(root)))))
    mine = root / "master_data" / "master_data.xlsx"
    mine.write_bytes(mine.read_bytes() + b"")             # your edited master data: must stay as it is
    marker = mine.read_bytes()
    z = release_zip(tmp_path, "V1")
    res = bt.upgrade_from_zip(z, root, ignore_running=True, pip=False)
    assert res["from"] == "V0" and res["to"] == "V1" and (root / "VERSION").read_text().strip() == "V1"
    assert (root / "backend" / "app" / "brand_new_feature.py").exists() and not (root / "releases").exists()
    assert not (root / "frontend" / "old_page_removed_in_v1.js").exists()
    import sqlite3
    assert sqlite3.connect(root / "data" / "projects.sqlite").execute("SELECT note FROM my_marker").fetchone()[0] == "MY PROJECTS"     # your projects are still there
    assert sqlite3.connect(root / "data" / "projects.sqlite").execute("SELECT count(*) FROM sqlite_master WHERE name='tool_designs'").fetchone()[0] == 1   # and the new tables were added
    assert (root / "storage" / "ab" / "part.step").read_bytes() == b"MY STEP"
    assert "master_data/master_data.xlsx" in res["master_data_kept"] and mine.exists()
    assert zipfile.is_zipfile(res["backup"]) and zipfile.is_zipfile(res["code_backup"]) and res["steps"]["migrate"] == "ok"
    # the same or an older version is refused
    with pytest.raises(bt.BackupError, match="already have"):
        bt.upgrade_from_zip(z, root, ignore_running=True, pip=False)


def test_failed_upgrade_is_undone(tmp_path, monkeypatch):
    root = install(tmp_path, monkeypatch)
    before = (root / "backend" / "app" / "main.py").read_bytes()
    db_before = (root / "data" / "projects.sqlite").read_bytes()
    broken = release_zip(tmp_path, "V1", {"backend/app/migrate.py": b"import sys\nsys.exit(3)\n"})
    with pytest.raises(bt.BackupError, match="undone"):
        bt.upgrade_from_zip(broken, root, ignore_running=True, pip=False)
    assert (root / "VERSION").read_text().strip() == "V0" and (root / "backend" / "app" / "main.py").read_bytes() == before
    assert not (root / "backend" / "app" / "brand_new_feature.py").exists()
    assert (root / "data" / "projects.sqlite").read_bytes() == db_before


def test_upgrade_refuses_a_running_tool_and_a_foreign_zip(tmp_path, monkeypatch):
    root = install(tmp_path, monkeypatch)
    monkeypatch.setattr(bt, "_port_busy", lambda port=8000: True)
    with pytest.raises(bt.BackupError, match="running"):
        bt.upgrade_from_zip(release_zip(tmp_path, "V1"), root, pip=False)
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("hello.txt", "x")
    with pytest.raises(bt.BackupError, match="not a Design to Cost version"):
        bt.upgrade_from_zip(junk, root, ignore_running=True, pip=False)


def test_backup_page_make_download_restore_and_upload(tmp_path, monkeypatch):
    root = tmp_path / "app"
    for part in ("master_data", "data", "storage"):
        (root / part).mkdir(parents=True)
    (root / "data" / "projects.sqlite").write_bytes(b"v1")
    monkeypatch.setattr(bt, "ROOT", root)
    monkeypatch.setattr(bt, "storage_dir", lambda r=root: root / "storage")
    r = client.post("/api/backups", json={})
    assert r.status_code == 200 and r.json()["name"].endswith(".zip")
    name = r.json()["name"]
    assert [b["name"] for b in client.get("/api/backups").json()] == [name]
    got = client.get(f"/api/backups/{name}")
    assert got.status_code == 200 and zipfile.is_zipfile(io.BytesIO(got.content))
    (root / "data" / "projects.sqlite").write_bytes(b"damaged")
    res = client.post("/api/backups/restore", json={"name": name, "only": ["data"]})
    assert res.status_code == 200 and (root / "data" / "projects.sqlite").read_bytes() == b"v1" and zipfile.is_zipfile(res.json()["safety_backup"])
    up = client.post("/api/backups/upload", files={"file": ("laptop copy.zip", got.content)})
    assert up.status_code == 200 and len(client.get("/api/backups").json()) >= 3
    assert client.post("/api/backups/upload", files={"file": ("x.zip", b"not a zip")}).status_code == 400
    assert client.get("/api/backups/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)


def test_release_zip_is_built_from_git(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_release", REPO / "scripts" / "make_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    for f in ("VERSION",):
        (tmp_path / f).write_text("V7\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    assert mod.main() == 0
    z = zipfile.ZipFile(tmp_path / "releases" / "V7" / "DesignToCost-V7.zip")
    assert "DesignToCost-V7/a.txt" in z.namelist() and "DesignToCost-V7/VERSION" in z.namelist()
    assert (tmp_path / "releases" / "LATEST").read_text().strip() == "V7"
