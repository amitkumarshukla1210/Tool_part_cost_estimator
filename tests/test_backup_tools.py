import subprocess
import zipfile

import pytest

from backend.app import backup_tools as bt


def git(path, *args):
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


def make_root(tmp_path):
    root = tmp_path / "app"
    (root / "master_data").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "storage" / "ab").mkdir(parents=True)
    (root / "master_data" / "rates.txt").write_text("mine v1")
    (root / "data" / "projects.sqlite").write_bytes(b"projects")
    (root / "storage" / "ab" / "part.step").write_bytes(b"STEP")
    return root


def test_backup_and_restore_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("DTC_STORAGE_FOLDER", raising=False)
    root = make_root(tmp_path)
    monkeypatch.setattr(bt, "storage_dir", lambda r=root: root / "storage")
    z = bt.make_backup(root)
    names = zipfile.ZipFile(z).namelist()
    assert {"master_data/rates.txt", "data/projects.sqlite", "storage/ab/part.step", "manifest.json"} <= set(names)
    (root / "data" / "projects.sqlite").write_bytes(b"damaged")
    (root / "master_data" / "rates.txt").write_text("changed")
    res = bt.restore(z, root, only=("data", "storage"))
    assert (root / "data" / "projects.sqlite").read_bytes() == b"projects" and (root / "master_data" / "rates.txt").read_text() == "changed"   # --only data,storage
    assert res["restored"]["data"] == 1 and zipfile.is_zipfile(res["safety_backup"])
    bt.restore(bt.latest(root), root)
    assert (root / "master_data" / "rates.txt").read_text() in ("mine v1", "changed")                                                          # latest = the safety backup
    with pytest.raises(bt.BackupError, match="--only takes"):
        bt.restore(z, root, only=("everything",))


def test_restore_refuses_paths_outside_the_folder(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.setattr(bt, "storage_dir", lambda r=root: root / "storage")
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("data/../../escaped.txt", "x")
    with pytest.raises(bt.BackupError, match="unsafe path"):
        bt.restore(evil, root, only=("data",))
    assert not (tmp_path / "escaped.txt").exists()


def test_cli_messages(tmp_path, capsys, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.setattr(bt, "storage_dir", lambda r=root: root / "storage")
    assert bt.main([], root, "backup") == 0 and "Backup written" in capsys.readouterr().out
    assert bt.main(["--restore", "nope.zip"], root, "backup") == 1 and "not found" in capsys.readouterr().err
    assert bt.main([], root, "update") == 1 and "not a git clone" in capsys.readouterr().err


def upstream_and_clone(tmp_path):
    up = tmp_path / "up"
    up.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(up)], check=True)
    (up / "master_data").mkdir()
    (up / "master_data" / "rates.txt").write_text("base")
    (up / "code.py").write_text("v1")
    (up / ".gitignore").write_text("data/\nstorage/\nbackups/\n")          # as in the real project
    git(up, "add", "-A")
    git(up, "commit", "-qm", "v1")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(up), str(clone)], check=True)
    (clone / "data").mkdir()
    (clone / "data" / "projects.sqlite").write_bytes(b"mine")
    return up, clone


def release(up, md=None):
    (up / "code.py").write_text("v2")
    if md:
        (up / "master_data" / "rates.txt").write_text(md)
    git(up, "add", "-A")
    git(up, "commit", "-qm", "v2")


def test_update_keeps_my_master_data_when_the_release_leaves_it_alone(tmp_path, monkeypatch):
    up, clone = upstream_and_clone(tmp_path)
    monkeypatch.setattr(bt, "storage_dir", lambda r=clone: clone / "storage")
    (clone / "master_data" / "rates.txt").write_text("my real rates")
    release(up)
    res = bt.update(clone)
    assert (clone / "code.py").read_text() == "v2" and (clone / "master_data" / "rates.txt").read_text() == "my real rates"
    assert res["master_data"] == "kept yours" and zipfile.is_zipfile(res["backup"])


def test_update_stops_when_both_sides_changed_master_data_then_follows_the_choice(tmp_path, monkeypatch):
    up, clone = upstream_and_clone(tmp_path)
    monkeypatch.setattr(bt, "storage_dir", lambda r=clone: clone / "storage")
    (clone / "master_data" / "rates.txt").write_text("my real rates")
    release(up, md="new example rows")
    with pytest.raises(bt.BackupError, match="AND the new version"):
        bt.update(clone)
    assert (clone / "code.py").read_text() == "v1" and (clone / "master_data" / "rates.txt").read_text() == "my real rates"      # nothing was touched
    res = bt.update(clone, "keep-mine")
    assert (clone / "code.py").read_text() == "v2" and (clone / "master_data" / "rates.txt").read_text() == "my real rates" and res["master_data"] == "kept yours"
    (tmp_path / "second").mkdir()
    up2, clone2 = upstream_and_clone(tmp_path / "second")
    monkeypatch.setattr(bt, "storage_dir", lambda r=clone2: clone2 / "storage")
    (clone2 / "master_data" / "rates.txt").write_text("my real rates")
    release(up2, md="new example rows")
    res = bt.update(clone2, "take-new")
    assert (clone2 / "master_data" / "rates.txt").read_text() == "new example rows" and "backup" in res["master_data"]
    z = zipfile.ZipFile(res["backup"])
    assert z.read("master_data/rates.txt") == b"my real rates"                                                                      # yours is in the backup


def test_update_refuses_when_other_files_were_edited(tmp_path, monkeypatch):
    up, clone = upstream_and_clone(tmp_path)
    monkeypatch.setattr(bt, "storage_dir", lambda r=clone: clone / "storage")
    (clone / "code.py").write_text("edited by hand")
    with pytest.raises(bt.BackupError, match="Other files"):
        bt.update(clone)
