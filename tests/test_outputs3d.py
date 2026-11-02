"""Stage 45: 3D outputs - viewer page, STL of the assembly and every part, picture and STEP per part, all in the release ZIP."""

import io
import json
import re
import struct
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_drawing_data import bracket
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def stl_ok(data):
    n = struct.unpack("<I", data[80:84])[0]
    return n > 0 and len(data) == 84 + 50 * n


def test_viewer_page_has_every_part_with_its_data_and_cost():
    pid = cover("O3D1")
    r = client.get(f"/api/parts/{pid}/tool-design.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "inline" in r.headers["content-disposition"]
    data = json.loads(re.search(r"const D = (\{.*?\});\n", r.text, re.S).group(1))
    by = {p["name"]: p for p in data["parts"]}
    cav = by["Cavity insert"]
    prod = client.get(f"/api/parts/{pid}/production-data").json()["tools"][0]
    want = next(p for p in prod["parts"] if p["name"] == "Cavity insert")
    assert cav["stock"] == want["stock_mm"] and cav["inr"] == pytest.approx(want["total_inr"]) and cav["v"] and cav["t"]
    assert data["tool_cost_inr"] == pytest.approx(prod["sums"]["tool_cost_inr"]) and any(p["kind"] == "ref" for p in data["parts"])
    assert 'id="ghost"' in r.text and "p.lifts" in r.text                 # see-through selection; explode by stacking order
    made = [p for p in data["parts"] if p["kind"] == "made"]
    centre = lambda p: p["locs"][0][2] + (min(p["v"][2::3]) + max(p["v"][2::3])) / 2
    plates = {p["name"]: centre(p) for p in made}
    assert plates["Cavity insert"] != plates["A plate (cavity side)"] and plates["Core insert"] != plates["B plate (core side)"]   # own levels
    assert "getContext(\"webgl\"" in r.text and "http" not in r.text.split("<script>")[1].split("const D")[0]          # nothing from the internet


def test_stl_step_and_picture_per_part_and_assembly_stl():
    pid = cover("O3D2")
    assert stl_ok(client.get(f"/api/parts/{pid}/tool-design.stl").content)
    t = client.get(f"/api/parts/{pid}/tool-design").json()["tools"][0]
    item = next(c["no"] for c in t["components"] if c["name"] == "Core insert")
    q = {"die": t["key"]}
    assert stl_ok(client.get(f"/api/parts/{pid}/tool-design/parts/{item}.stl", params=q).content)
    assert client.get(f"/api/parts/{pid}/tool-design/parts/{item}.png", params=q).content[:4] == b"\x89PNG"
    assert b"ISO-10303" in client.get(f"/api/parts/{pid}/tool-design/parts/{item}.step", params=q).content[:200]
    assert client.get(f"/api/parts/{pid}/tool-design/parts/99.stl", params=q).status_code == 400
    assert client.get(f"/api/parts/{pid}/tool-design/parts/{item}.obj", params=q).status_code == 404


def test_release_zip_holds_stl_pictures_and_the_offline_viewer():
    pid = bracket("O3D3")
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/parts/{pid}/tool-design.zip").content))
    names = z.namelist()
    tools = {n.split("/")[0] for n in names if "/" in n}
    for t in tools:
        assert any(n.startswith(f"{t}/3D/STL/") and n.endswith("_assembly.stl") for n in names)
        assert any(n.startswith(f"{t}/3D/STL/parts/") for n in names) and any(n.startswith(f"{t}/pictures/") for n in names)
        assert any(n.startswith(f"{t}/") and n.endswith("_3D_viewer.html") for n in names)
    assert "3D_viewer.html" in z.read("README.txt").decode()
