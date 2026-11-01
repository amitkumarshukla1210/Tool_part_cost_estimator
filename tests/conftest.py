import shutil

import pytest

from backend.app import costing_db, master_data


@pytest.fixture(autouse=True)
def master_data_copy(tmp_path, monkeypatch):
    """Every test works on its own copies, so the real master data never changes."""
    copy = tmp_path / "master_data.xlsx"
    shutil.copy(master_data.DEFAULT_PATH, copy)
    monkeypatch.setenv("MASTER_DATA_PATH", str(copy))
    db = tmp_path / "costing_db.sqlite"
    shutil.copy(costing_db.DEFAULT_PATH, db)
    monkeypatch.setenv("COSTING_DB_PATH", str(db))
    # project data and CAD files of each test go to its own temporary folder
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'projects.sqlite'}")
    monkeypatch.setenv("DTC_STORAGE_FOLDER", str(tmp_path / "storage"))
    monkeypatch.setenv("DTC_BACKUP_FOLDER", str(tmp_path / "backups"))
    # logins are on by default; the tests run without them unless a test turns them on (test_server_mode)
    monkeypatch.setenv("DTC_MODE", "local")
    return copy


class Clock:
    """The date the software sees as 'today'. Frozen in the tests so they pass in any real month."""

    def __init__(self, iso: str):
        self.iso = iso

    def set(self, iso: str) -> None:
        self.iso = iso


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Freeze 'today' at 2026-10-31 (the month the example rates start). A test moves the clock with clock.set('2026-11-05')."""
    import datetime

    from backend.app import rates

    state = Clock("2026-10-31")

    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(state.iso)

    monkeypatch.setattr(rates, "date", FrozenDate)
    return state
