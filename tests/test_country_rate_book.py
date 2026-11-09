"""Country rate book (stage 51): downloads parsed, history append-only, workbook built with sources, no invented values."""

import json
from datetime import date

import pytest
from openpyxl import load_workbook

from backend.app import country_rate_book as crb
from backend.app import costing_db

TODAY = date(2026, 11, 9)


def fred_csv(sid, months, start=100.0, step=1.0):
    rows = [f"observation_date,{sid}"]
    y, m = 2024, 11
    for i in range(months):
        rows.append(f"{y:04d}-{m:02d}-01,{start + i * step}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return "\n".join(rows).encode()


ILO = (b"DATAFLOW,REF_AREA,FREQ,MEASURE,SEX,OCU,CUR,TIME_PERIOD,OBS_VALUE,SOURCE,NOTE_INDICATOR\n"
       b"x,IND,A,EAR,SEX_T,OCU_SKILL_L2,CUR_TYPE_LCU,2024,95.5,LFS - Labour Force Survey,\n"
       b"x,IND,A,EAR,SEX_T,OCU_SKILL_L2,CUR_TYPE_USD,2024,1.15,LFS - Labour Force Survey,\n"
       b"x,IND,A,EAR,SEX_T,OCU_SKILL_L2,CUR_TYPE_USD,2025,1.20,LFS - Labour Force Survey,\n")
EURO = json.dumps({"id": ["freq", "time"], "size": [1, 2], "value": {"0": 0.17, "1": 0.165},
                   "dimension": {"time": {"category": {"index": {"2025-S2": 0, "2026-S1": 1}}}}}).encode()


def fake(url, accept=None):
    if "fred.stlouisfed.org" in url:
        sid = url.split("id=")[1].split("&")[0]
        if sid == "PTINUSDM":
            raise OSError("connection refused")              # a failing source is logged, the rest goes on
        if sid == "EXINUS":
            return fred_csv(sid, 24, 84.0, 0.5)
        if sid == "EXCHUS":
            return fred_csv(sid, 24, 7.2, 0.0)
        return fred_csv(sid, 23, 2000.0, 10.0)                # commodities: one month less (not published yet)
    if "sdmx.ilo.org" in url:
        return ILO
    if "eurostat" in url:
        return EURO
    if "worldbank" in url:
        return json.dumps([{"page": 1}, [{"date": "2024", "value": 25000.0}, {"date": "2025", "value": None}]]).encode()
    raise AssertionError(url)


def test_parsers():
    assert crb.parse_fred(b"observation_date,X\n2026-01-05,2\n2026-01-12,4\n2026-02-02,.\n") == {"2026-01": 3.0}
    assert crb.parse_eurostat(EURO) == {"2025-S2": 0.17, "2026-S1": 0.165}
    rows = crb.parse_ilo(ILO)
    assert rows[0] == {"flow": "x", "sex": "SEX_T", "area": "IND", "cls": "OCU_SKILL_L2", "cur": "CUR_TYPE_LCU", "year": "2024", "value": 95.5,
                       "source": "LFS - Labour Force Survey", "note": ""}
    assert crb.month_list("2026-10")[0] == "2024-11" and len(crb.month_list("2026-10")) == 24


def test_grade_follows_the_right_index():
    assert crb.index_for("Aluminium ADC12 / A383") == "aluminium"
    assert crb.index_for("Stainless steel SS304 sheet") == "nickel"
    assert crb.index_for("Brass CW614N (free-cutting) bar") == "copper"
    assert crb.index_for("PP homopolymer") == "ppi_resins"
    assert crb.index_for("CRCA D513 EDD (deep drawing)") == "ppi_steel"


def test_history_is_append_only_and_logs_revisions_and_failures(tmp_path):
    countries = [{"code": "IN", "currency": "INR"}, {"code": "VN", "currency": "VND"}]
    h = crb.fetch(tmp_path, countries, fake, TODAY)
    assert any("FAILED tin" in line for line in h["runs"][-1]["log"])
    assert h["series"]["aluminium"]["values"]["2024-11"] == 2000.0
    assert h["series"]["fxwb_VND"]["values"] == {"2024": 25000.0}
    assert h["ilo"]["hourly_by_skill"]["IND|OCU_SKILL_L2|CUR_TYPE_USD"]["2025"]["value"] == 1.2

    def revised(url, accept=None):
        if "PALUMUSDM" in url:
            return b"observation_date,PALUMUSDM\n2024-11-01,2001\n"
        raise OSError("offline")
    h2 = crb.fetch(tmp_path, countries, revised, TODAY)
    assert h2["series"]["aluminium"]["values"]["2026-09"] == 2220.0               # kept from the first run
    assert h2["series"]["aluminium"]["values"]["2024-11"] == 2001.0               # revised by the source ...
    assert any("revised" in line for line in h2["runs"][-1]["log"])               # ... and logged
    assert h2["series"]["copper"]["values"]                                       # failed source: history stays


def test_workbook_for_china_has_every_sheet_sources_and_no_invented_month(tmp_path):
    paths = crb.run(["CN"], tmp_path, http=fake, today=TODAY)
    wb = load_workbook(paths[0])
    assert wb.sheetnames == ["Summary", "RM_Price", "Labour", "Process_Cost", "Electricity", "Transport", "Forex", "Sources"]
    assert paths[0].name == "Country_Rates_China_2026-10.xlsx"
    rm = wb["RM_Price"]
    head = [c.value for c in rm[4]]
    assert head[2] == "Nov-24" and head[25] == "Oct-26"
    alu = next(r for r in rm.iter_rows(min_row=5) if r[0].value and str(r[0].value).startswith("Aluminium (LME"))
    assert alu[2].value == 2000.0 and alu[24].value == 2220.0 and alu[25].value is None   # Oct-26 not published: empty
    tin = next(r for r in rm.iter_rows(min_row=5) if r[0].value and str(r[0].value).startswith("Tin"))
    assert all(c.value is None for c in tin[2:26])                                         # failed source, no history
    # A2 is a formula on the Forex sheet, not a pasted number
    inr = next(r for r in rm.iter_rows(min_row=5) if r[0].value == "Aluminium" and r[1].value == "INR/kg")
    assert str(inr[2].value).startswith("=IF(ISNUMBER(C") and "Forex!" in inr[2].value
    # grade rows of the tool, EXAMPLE marked
    vals = [[c.value for c in r] for r in rm.iter_rows(min_row=5)]
    grade = next(v for v in vals if v[0] == "Aluminium ADC12 / A383")
    assert grade[28] in ("approved", "EXAMPLE") and str(grade[27]).startswith("=IFERROR(AA")
    assert "Aluminium" in grade[30]
    src = [[c.value for c in r] for r in wb["Sources"].iter_rows(min_row=4)]
    kinds = {r[1] for r in src if r[1]}
    assert {"MARKET", "APP", "GAP"} <= kinds
    assert any(r[3] == "https://fred.stlouisfed.org/series/PALUMUSDM" for r in src)
    assert any("ILOSTAT" in (r[2] or "") and r[1] == "GAP" for r in src)                   # no ILO data for China
    fx = wb["Forex"]
    assert fx["C5"].value == 84.0 and fx["C6"].value == 7.2 and "C5/C6" in fx["C7"].value


def test_workbook_for_germany_has_eurostat_and_master_data_untouched(tmp_path):
    before = costing_db.DEFAULT_PATH.read_bytes() if hasattr(costing_db, "DEFAULT_PATH") else None
    p = crb.run(["DE"], tmp_path, http=fake, today=TODAY)[0]
    el = load_workbook(p)["Electricity"]
    cells = [[c.value for c in r] for r in el.iter_rows()]
    row = next(r for r in cells if r[0] and str(r[0]).startswith("Germany: 2-20 GWh"))
    assert row[2:4] == [0.17, 0.165]
    if before is not None:
        assert costing_db.DEFAULT_PATH.read_bytes() == before


def test_offline_build_uses_saved_history(tmp_path):
    crb.fetch(tmp_path, [{"code": "IN", "currency": "INR"}], fake, TODAY)
    p = crb.run(["IN"], tmp_path, offline=True, http=lambda *a, **k: pytest.fail("no download offline"))[0]
    assert load_workbook(p)["Labour"] is not None


def test_ilo_file_import_when_the_download_is_refused(tmp_path):
    f = tmp_path / "ilo.csv"
    f.write_bytes(b"DATAFLOW,REF_AREA,FREQ,MEASURE,SEX,OCU,CUR,TIME_PERIOD,OBS_VALUE,SOURCE,NOTE_INDICATOR\n"
                  b"ILO:DF_EAR_EHRA_SEX_OCU_CUR_NB(1.0),THA,A,EAR,SEX_T,OCU_SKILL_L1,CUR_TYPE_LCU,2025,60.5,LFS,\n"
                  b"ILO:DF_EAR_EHRA_SEX_OCU_CUR_NB(1.0),THA,A,EAR,SEX_M,OCU_SKILL_L1,CUR_TYPE_LCU,2025,70.0,LFS,\n"
                  b"ILO:DF_EAR_EMTA_SEX_ECO_CUR_NB(1.0),THA,A,EAR,SEX_T,ECO_ISIC4_C,CUR_TYPE_LCU,2025,15000,LFS,\n"
                  b"ILO:DF_EAR_EMTA_SEX_ECO_CUR_NB(1.0),THA,A,EAR,SEX_T,ECO_ISIC4_A,CUR_TYPE_LCU,2025,9000,LFS,\n")

    def refused(url, accept=None):
        if "sdmx.ilo.org" in url:
            raise OSError("HTTP Error 403: Forbidden")
        return fake(url, accept)
    p = crb.run(["TH"], tmp_path, http=refused, today=TODAY, ilo_files=[f])[0]
    h = crb.load_history(tmp_path)
    assert h["ilo"]["hourly_by_skill"] == {"THA|OCU_SKILL_L1|CUR_TYPE_LCU": {"2025": {
        "value": 60.5, "source": "LFS", "note": "", "fetched": "2026-11-09"}}}            # only both sexes, used classes
    assert list(h["ilo"]["monthly_manufacturing"]) == ["THA|ECO_ISIC4_C|CUR_TYPE_LCU"]
    assert any("--ilo-file" in line for r in h["runs"] for line in r["log"])
    cells = [[c.value for c in r] for r in load_workbook(p)["Labour"].iter_rows()]
    assert 60.5 in next(r for r in cells if r[0] == "Skill level 1 - helper / elementary" and r[1] == "THB/h")


def test_rm_sheet_groups_grades_by_family_and_lists_missing_grades_for_entry(tmp_path):
    p = crb.run(["IN"], tmp_path, http=fake, today=TODAY)[0]
    ws = load_workbook(p)["RM_Price"]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    names = [r[0] for r in rows]
    b = names.index("B. Grade / RM")
    c = names.index("C. Grade (not in the tool yet)")
    assert "Aluminium - casting alloys" in names[b:c] and "Tool & mould material" in names[b:c]
    alu = names.index("Aluminium - casting alloys", b)
    assert "Aluminium ADC12 / A383" in names[alu:alu + 8]
    part_c = names[c:]
    assert "EPDM" in part_c and "AM60B" in part_c and "EN31 / 100Cr6" not in part_c
    assert "SS 316 / 316L" not in part_c and "SAE 8620" not in part_c and "20MnCr5 / 16MnCr5" not in part_c   # stage 54 grades
    assert "ADC12" not in part_c and "P20 / 1.2311" not in part_c and "SS 430" not in part_c   # already in the tool: in B
    assert "LM2" not in part_c and "ALDC2 / ADC3" not in part_c and "EN24 / 34CrNiMo6" not in part_c   # stage 53 grades
    epdm = next(r for r in ws.iter_rows(min_row=c) if r[0].value == "EPDM")
    assert all(x.value is None and x.fill.fgColor.rgb.endswith("FFFF00") for x in epdm[2:26])     # yellow, empty: no made-up price
    assert epdm[30].value.startswith("Natural rubber")
    am = next(r for r in ws.iter_rows(min_row=c) if r[0].value == "AM60B")
    assert am[30].value == "-"                                                                    # magnesium: no free index


def test_missing_ilo_file_is_reported_and_the_workbooks_are_still_built(tmp_path, capsys):
    p = crb.run(["IN"], tmp_path, http=fake, today=TODAY, ilo_files=[tmp_path / "file1.csv"])
    assert p and p[0].exists()
    log = crb.load_history(tmp_path)["runs"][-1]["log"]
    assert any("NOT FOUND" in line and "file1.csv" in line for line in log)
    crb.main(["--countries", "IN", "--out", str(tmp_path), "--offline", "--ilo-file", str(tmp_path / "nope.csv")])
    assert "NOT FOUND" in capsys.readouterr().out


def test_ilo_explorer_csv_with_labels_and_old_bulk_csv_are_read():
    labels = ("STRUCTURE,STRUCTURE_ID,ACTION,REF_AREA: Reference area,FREQ: Frequency,MEASURE: Measure,SEX: Sex,"
              "OCU: Occupation,CUR: Currency,TIME_PERIOD: Time,OBS_VALUE,SOURCE\n"
              "dataflow,ILO:DF_EAR_EHRA_SEX_OCU_CUR_NB(1.0),I,IND: India,A: Annual,EAR: Earnings,SEX_T: Total,"
              "OCU_SKILL_L2: Skill level 2,CUR_TYPE_USD: US dollars,2025: 2025,0.80,LFS\n").encode()
    r = crb.parse_ilo(labels)[0]
    assert (r["area"], r["cls"], r["cur"], r["year"], r["value"], r["sex"]) == ("IND", "OCU_SKILL_L2", "CUR_TYPE_USD", "2025", 0.8, "SEX_T")
    assert "EHRA_SEX_OCU" in r["flow"]
    bulk = (b"ref_area,source,indicator,sex,classif1,classif2,time,obs_value\n"
            b"CHN,ADM,EAR_EMTA_SEX_ECO_CUR_NB_A,SEX_T,ECO_ISIC4_C,CUR_TYPE_LCU,2022,5613\n")
    r = crb.parse_ilo(bulk)[0]
    assert (r["area"], r["cls"], r["cur"], r["year"], r["value"]) == ("CHN", "ECO_ISIC4_C", "CUR_TYPE_LCU", "2022", 5613.0)
    assert "EMTA_SEX_ECO" in r["flow"]


def test_ilo_folder_finds_the_files_with_the_names_the_ilo_gives_them(tmp_path):
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "ILO,DF_EAR_EHRA_SEX_OCU_CUR_NB+IND+CHN.A..SEX_T...csv").write_bytes(
        b"DATAFLOW,REF_AREA,FREQ,MEASURE,SEX,OCU,CUR,TIME_PERIOD,OBS_VALUE,SOURCE\n"
        b"ILO:DF_EAR_EHRA_SEX_OCU_CUR_NB(1.0),IND,A,EAR,SEX_T,OCU_SKILL_L1,CUR_TYPE_LCU,2025,50.8,LFS\n")
    (dl / "ILO,DF_EAR_EMTA_SEX_ECO_CUR_NB+IND+CHN.A..SEX_T.ECO_ISIC4_C..csv").write_bytes(
        b"DATAFLOW,REF_AREA,FREQ,MEASURE,SEX,ECO,CUR,TIME_PERIOD,OBS_VALUE,SOURCE\n"
        b"ILO:DF_EAR_EMTA_SEX_ECO_CUR_NB(1.0),CHN,A,EAR,SEX_T,ECO_ISIC4_C,CUR_TYPE_LCU,2022,5613,ADM\n")
    (dl / "holiday.csv").write_bytes(b"a,b\n1,2\n")
    out = tmp_path / "out"
    assert crb.import_ilo(out, [dl, tmp_path / "<real name 1>.csv"], TODAY) == 2
    h = crb.load_history(out)
    assert h["ilo"]["monthly_manufacturing"]["CHN|ECO_ISIC4_C|CUR_TYPE_LCU"]["2022"]["value"] == 5613.0
    log = h["runs"][-1]["log"]
    assert any("2 earnings CSV" in line for line in log) and any("NOT FOUND" in line for line in log)


def test_indicative_grade_trend_fills_24_months_from_the_index_and_is_marked(tmp_path):
    p = crb.run(["CN"], tmp_path, http=fake, today=TODAY)[0]
    ws = load_workbook(p)["RM_Price"]
    names = [r[0].value for r in ws.iter_rows()]
    b2 = names.index("B2. Indicative price, CNY/kg")
    b3 = names.index("B3. Indicative price, INR/kg")
    assert names.index("B. Grade / RM") < b2 < b3 < names.index("C. Grade (not in the tool yet)")
    row = next(r for r in ws.iter_rows(min_row=b2 + 1, max_row=b3) if r[0].value == "Aluminium ADC12 / A383")
    f = row[2].value                                                     # Nov-24
    assert f.startswith("=IFERROR(IF(AND(ISNUMBER(RM_Price!C") and "Forex!C6" in f and "$AA$" in f
    assert row[27].value == "approved rate 2026-10" or row[27].value == "EXAMPLE rate 2026-10"
    assert row[26].value == "Sep-26"                                     # base = latest month with index data
    assert row[28].value.startswith("Aluminium (LME")
    inr = next(r for r in ws.iter_rows(min_row=b3 + 1) if r[0].value == "Aluminium ADC12 / A383")
    assert "Forex!C7" in inr[2].value
    notes = [n for n in names if n and str(n).startswith("B2. INDICATIVE")]
    assert notes and "NOT a quote" in notes[0]
