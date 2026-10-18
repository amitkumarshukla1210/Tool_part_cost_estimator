import shutil

import pytest

from backend.app import master_data, mould_db


@pytest.fixture(autouse=True)
def master_data_copy(tmp_path, monkeypatch):
    """Every test works on its own copies, so the real master data never changes."""
    copy = tmp_path / "master_data.xlsx"
    shutil.copy(master_data.DEFAULT_PATH, copy)
    monkeypatch.setenv("MASTER_DATA_PATH", str(copy))
    db = tmp_path / "mould_db.sqlite"
    shutil.copy(mould_db.DEFAULT_PATH, db)
    monkeypatch.setenv("MOULD_DB_PATH", str(db))
    return copy
