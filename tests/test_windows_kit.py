"""The Windows kit (windows/dtc_manager.py) on a fake laptop: old install -> update from a ZIP -> backup / restore -> rollback."""
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def kit(tmp_path, monkeypatch):
    base = tmp_path / "DTC"
    base.mkdir()
    shutil.copy2(REPO / "windows" / "dtc_manager.py", base / "dtc_manager.py")
    spec = importlib.util.spec_from_file_location("dtc_manager_test", base / "dtc_manager.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # no real venv / pip in the test: the venv "python" is this Python, and the smoke test is run for real
    monkeypatch.setattr(m, "venv_python", lambda: Path(sys.executable))
    monkeypatch.setattr(m, "ensure_venv", lambda: None)
    monkeypatch.setattr(m, "pip_install", lambda app: None)
    monkeypatch.setattr(m, "yes", lambda q, default=True: "Start" not in q)
    monkeypatch.setattr(m, "running", lambda p=None: False)
    return m


def release_zip(tmp_path, name="Tool_part_cost_estimator-main", change=None):
    """A GitHub-style ZIP of this working copy (code + master_data, no data/storage)."""
    src = tmp_path / "rel" / name
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, check=True).stdout.split("\n")
    for f in filter(None, files):
        if (REPO / f).is_file() and not f.startswith(("tests/", "samples/")):
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, src / f)
    if change:
        change(src)
    z = tmp_path / f"{name}.zip"
    shutil.make_archive(str(z.with_suffix("")), "zip", src.parent, name)
    shutil.rmtree(tmp_path / "rel")
    return z


def old_install(base):
    """What the laptop has today: an app folder from a ZIP with data/, storage/ and edited master data inside."""
    app = base / "Tool_part_cost_estimator-main" / "Tool_part_cost_estimator-main"
    for f in ("backend/app/main.py", "requirements.txt"):
        (app / f).parent.mkdir(parents=True, exist_ok=True)
        (app / f).write_text("old")
    shutil.copytree(REPO / "master_data", app / "master_data")
    con = sqlite3.connect(app / "master_data" / "costing_db.sqlite")
    con.execute("UPDATE countries SET notes = 'my note' WHERE code = 'IN'")
    con.commit()
    con.close()
    (app / "data").mkdir()
    (app / "data" / "projects.sqlite").write_bytes(b"my projects")
    (app / "storage" / "files" / "ab").mkdir(parents=True)
    (app / "storage" / "files" / "ab" / "abc.step").write_bytes(b"STEP")
    return app


def test_first_update_moves_data_out_installs_and_merges(kit, tmp_path):
    base = kit.BASE
    old = old_install(base)
    z = release_zip(tmp_path)
    kit.cmd_update([str(z)])
    app = base / "Tool_part_cost_estimator"
    assert kit.is_app(app) and not (base / "Tool_part_cost_estimator-main").exists()             # old folder retired to DTC_Old
    assert any(p.name.startswith(old.name) for p in (base / "DTC_Old").iterdir())
    assert (kit.DATA / "data" / "projects.sqlite").read_bytes() == b"my projects"
    assert (kit.DATA / "storage" / "files" / "ab" / "abc.step").read_bytes() == b"STEP"
    con = sqlite3.connect(kit.DATA / "master_data" / "costing_db.sqlite")
    assert con.execute("SELECT notes FROM countries WHERE code = 'IN'").fetchone()[0] == "my note"           # my edit survived
    con.close()
    names = [f.name for f in kit.backup_list()]
    assert any(n.startswith("dtc-before-migration") for n in names) and any(n.startswith("dtc-before-update") for n in names)
    assert (base / "DTC_Update.bat").exists() and (base / "dtc_settings.ini").exists()                      # kit copied itself up
    v = json.loads(kit.VERSION.read_text())
    assert v["zip"] == z.name and Path(v["previous_app"]).exists()
    env = kit.app_env()
    assert env["DATABASE_URL"].endswith("DTC_Data/data/projects.sqlite") and env["DTC_STORAGE_FOLDER"] == str(kit.DATA / "storage")


def test_next_update_backup_restore_and_rollback(kit, tmp_path):
    base = kit.BASE
    kit.cmd_update([str(release_zip(tmp_path, "v1"))])
    (kit.DATA / "data").mkdir(exist_ok=True)
    (kit.DATA / "data" / "projects.sqlite").write_bytes(b"v1 projects")

    def v2(src):
        con = sqlite3.connect(src / "master_data" / "costing_db.sqlite")
        con.execute("INSERT INTO countries (code, name, currency) VALUES ('ZZ', 'Newland', 'ZZD')")
        con.commit()
        con.close()
        (src / "VERSION2").write_text("2")
    kit.cmd_update([str(release_zip(tmp_path, "v2", v2))])
    app = base / "Tool_part_cost_estimator"
    assert (app / "VERSION2").exists() and (kit.DATA / "data" / "projects.sqlite").read_bytes() == b"v1 projects"
    con = sqlite3.connect(kit.DATA / "master_data" / "costing_db.sqlite")
    assert con.execute("SELECT name FROM countries WHERE code = 'ZZ'").fetchone() == ("Newland",)               # new row merged in
    con.close()
    log = sorted((kit.DATA / "logs").glob("update-*.txt"))[-1].read_text()
    assert "countries: 1 new row(s) added" in log

    # backup -> damage -> restore
    b = kit.backup()
    (kit.DATA / "data" / "projects.sqlite").write_bytes(b"damaged")
    kit.restore(b, ("data", "storage"))
    assert (kit.DATA / "data" / "projects.sqlite").read_bytes() == b"v1 projects"

    # rollback to v1 with the data of before the v2 update
    (kit.DATA / "data" / "projects.sqlite").write_bytes(b"after v2")
    kit.cmd_rollback([])
    assert not (app / "VERSION2").exists() and kit.is_app(app)
    assert (kit.DATA / "data" / "projects.sqlite").read_bytes() == b"v1 projects"


def test_refuses_bad_zip_and_running_app(kit, tmp_path, monkeypatch):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(kit.KitError, match="not a ZIP of this app"):
        kit.cmd_update([str(bad)])
    monkeypatch.setattr(kit, "running", lambda p=None: True)
    with pytest.raises(kit.KitError, match="app is running"):
        kit.cmd_update([])


def test_staging_cleanup_retries_permission_error(kit, tmp_path, monkeypatch):
    kit.STAGING.mkdir()
    calls = []

    def fake_rmtree(path, onexc):
        onexc(lambda target: calls.append((path, target)), path, PermissionError("access denied"))

    monkeypatch.setattr(kit.shutil, "rmtree", fake_rmtree)
    kit.clear_staging()

    assert calls == [(kit.STAGING, kit.STAGING)]


def test_staging_cleanup_explains_locked_folder(kit, monkeypatch):
    def fake_rmtree(path, onexc):
        def locked(_target):
            raise PermissionError("folder is in use")

        onexc(locked, path, PermissionError("access denied"))

    monkeypatch.setattr(kit.shutil, "rmtree", fake_rmtree)
    with pytest.raises(kit.KitError, match="Close Explorer windows or other programs"):
        kit.clear_staging()


def test_a_broken_new_version_changes_nothing(kit, tmp_path):
    kit.cmd_update([str(release_zip(tmp_path, "v1"))])
    before = (kit.DATA / "master_data" / "costing_db.sqlite").read_bytes()
    broken = release_zip(tmp_path, "broken", lambda src: (src / "backend" / "app" / "main.py").write_text("raise SystemExit('boom')\nimport nothing_here"))
    with pytest.raises(kit.KitError, match="does not start"):
        kit.cmd_update([str(broken)])
    assert not (kit.BASE / "_dtc_new").exists() and kit.is_app(kit.BASE / "Tool_part_cost_estimator")
    assert (kit.DATA / "master_data" / "costing_db.sqlite").read_bytes() == before
