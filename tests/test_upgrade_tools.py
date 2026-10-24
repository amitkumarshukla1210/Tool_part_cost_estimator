import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from backend.app import master_data
from backend.app import upgrade_tools as up

SHIPPED = Path(__file__).resolve().parents[1] / "master_data"


def test_fingerprints_cover_the_shipped_master_data():
    # A failure here means master_data/ changed: run  python -m backend.app.upgrade_tools fingerprints  and commit shipped_rows.json
    assert up.fingerprints_of(SHIPPED) <= up.shipped()


def copy_master(tmp_path, name):
    d = tmp_path / name
    shutil.copytree(SHIPPED, d)
    return d


def q(db, sql, *args):
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql, args).fetchall()


def ex(db, *statements):
    with closing(sqlite3.connect(db)) as con:
        for s in statements:
            con.execute(*s) if isinstance(s, tuple) else con.execute(s)
        con.commit()


def test_merge_keeps_my_edits_and_brings_the_new_rows(tmp_path):
    mine, new = copy_master(tmp_path, "mine"), copy_master(tmp_path, "new")
    known = up.fingerprints_of(SHIPPED)
    mdb, ndb = mine / up.DB_FILE, new / up.DB_FILE
    m1, m2 = [r[0] for r in q(mdb, "SELECT machine_id FROM machines ORDER BY id LIMIT 2")]
    rate = q(mdb, "SELECT category, item, country FROM rates LIMIT 1")[0]
    # me: one machine edited, one approved rate of my own
    ex(mdb, ("UPDATE machines SET power_kw = 123.4, is_example = 0 WHERE machine_id = ?", (m1,)),
       ("INSERT INTO rates (category, item, country, value, month, status) VALUES (?, ?, ?, 99, '2030-01', 'approved')", rate))
    # the new version: both machines changed, a new machine, a new table, a new column, a new rate
    ex(ndb, ("UPDATE machines SET power_kw = 55 WHERE machine_id IN (?, ?)", (m1, m2)),
       "INSERT INTO machines (machine_id, name, process) VALUES ('NEW-1', 'New press', 'press')",
       "CREATE TABLE robots (id INTEGER PRIMARY KEY, code TEXT, UNIQUE (code))", "INSERT INTO robots (code) VALUES ('R1')",
       "ALTER TABLE machines ADD COLUMN shot_kg REAL", "UPDATE machines SET shot_kg = 2",
       ("INSERT INTO rates (category, item, country, value, month, status) VALUES (?, ?, ?, 7, '2031-01', 'approved')", rate),
       ("INSERT INTO rates (category, item, country, value, month, status) VALUES (?, ?, ?, 1, '2030-01', 'approved')", rate))
    rep = up.merge(mine, new, known)["costing_db.sqlite"]
    power = dict(q(mdb, "SELECT machine_id, power_kw FROM machines"))
    assert power[m1] == 123.4 and power[m2] == 55 and "NEW-1" in power                     # mine kept, untouched updated, new added
    assert q(mdb, "SELECT code FROM robots") == [("R1",)] and "machines.shot_kg" in rep["columns_added"]
    assert q(mdb, "SELECT value FROM rates WHERE month = '2030-01' AND category = ? AND item = ? AND country = ?", *rate) == [(99,)]
    assert rep["rates_added"] == 1 and q(mdb, "SELECT value FROM rates WHERE month = '2031-01'") == [(7,)]
    assert rep["kept_yours"]["machines"] == [m1] and "robots" in rep["tables_added"]
    assert "YOU changed were kept" in up.report_text({"costing_db.sqlite": rep})


def test_merge_of_the_workbook(tmp_path):
    mine, new = copy_master(tmp_path, "mine"), copy_master(tmp_path, "new")
    known = up.fingerprints_of(SHIPPED)
    d = master_data._read_workbook(mine / up.XLSX_FILE)
    p0, p1 = d["Parameters"][0], d["Parameters"][1]
    d["Parameters"][0] = {**p0, "description": "my own note"}
    master_data.write(d, mine / up.XLSX_FILE)
    n = master_data._read_workbook(new / up.XLSX_FILE)
    n["Parameters"][0] = {**p0, "description": "new text 0"}
    n["Parameters"][1] = {**p1, "description": "new text 1"}
    n["Materials"].append({"part_type": "plastic", "material": "PEEK", "density_g_cm3": 1.3, "notes": ""})
    master_data.write(n, new / up.XLSX_FILE)
    rep = up.merge(mine, new, known)["master_data.xlsx"]
    got = master_data._read_workbook(mine / up.XLSX_FILE)
    assert got["Parameters"][0]["description"] == "my own note" and got["Parameters"][1]["description"] == "new text 1"
    assert any(m["material"] == "PEEK" for m in got["Materials"]) and rep["rows_added"] == {"Materials": 1}


def test_merge_into_an_empty_folder_copies_the_new_files(tmp_path):
    new = copy_master(tmp_path, "new")
    rep = up.merge(tmp_path / "mine", new, set())
    assert (tmp_path / "mine" / up.DB_FILE).exists() and "copied" in rep[up.DB_FILE]
