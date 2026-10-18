import shutil

import pytest

from backend.app import master_data


@pytest.fixture(autouse=True)
def master_data_copy(tmp_path, monkeypatch):
    """Every test works on its own copy, so the real master data never changes."""
    copy = tmp_path / "master_data.xlsx"
    shutil.copy(master_data.DEFAULT_PATH, copy)
    monkeypatch.setenv("MASTER_DATA_PATH", str(copy))
    return copy
