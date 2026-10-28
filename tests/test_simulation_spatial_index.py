from collections import OrderedDict

import numpy as np

from backend.app import concept, geometry, register, simulation


def _reference_shadowed(tri, axis, cos_min, offset, max_faces):
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    cross = np.cross(b - a, c - a)
    twice = np.linalg.norm(cross, axis=1)
    area = twice / 2
    n = cross / np.where(twice > 0, twice, 1)[:, None]
    cand = np.where((np.abs(n[:, axis]) > cos_min) & (area > 0))[0]
    step = max(1, int(np.ceil(len(cand) / max_faces)))
    cand = cand[::step]
    u, v = [i for i in range(3) if i != axis]
    p0, p1, p2 = tri[:, 0], tri[:, 1], tri[:, 2]
    d = (p1[:, v] - p2[:, v]) * (p0[:, u] - p2[:, u]) + (p2[:, u] - p1[:, u]) * (p0[:, v] - p2[:, v])
    ok = np.abs(d) > 1e-12
    d = np.where(ok, d, 1.0)
    hit = np.zeros(len(tri), bool)
    for start_i in range(0, len(cand), 128):
        idx = cand[start_i:start_i + 128]
        cen = tri[idx].mean(axis=1)
        sign = np.sign(n[idx, axis])
        du, dv = cen[:, u, None] - p2[None, :, u], cen[:, v, None] - p2[None, :, v]
        l1 = ((p1[None, :, v] - p2[None, :, v]) * du + (p2[None, :, u] - p1[None, :, u]) * dv) / d[None]
        l2 = ((p2[None, :, v] - p0[None, :, v]) * du + (p0[None, :, u] - p2[None, :, u]) * dv) / d[None]
        l3 = 1 - l1 - l2
        inside = (l1 > 1e-9) & (l2 > 1e-9) & (l3 > 1e-9) & ok[None]
        depth = l1 * p0[None, :, axis] + l2 * p1[None, :, axis] + l3 * p2[None, :, axis]
        origin = (cen[:, axis] + sign * offset)[:, None]
        hit[idx] = (inside & (sign[:, None] * (depth - origin) > 0)).any(axis=1)
    return hit, area, n, step


def test_shadowed_spatial_index_matches_full_scan():
    tri = np.random.default_rng(42).normal(size=(80, 3, 3))
    for axis in range(3):
        actual = concept._shadowed(tri, axis, 0.1, 0.01, 1000)
        expected = _reference_shadowed(tri, axis, 0.1, 0.01, 1000)
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_allclose(actual[1], expected[1])
        np.testing.assert_allclose(actual[2], expected[2])
        assert actual[3] == expected[3]


def test_projected_grid_returns_local_triangle_candidates():
    rows = []
    for x in range(100):
        for y in range(100):
            x0, y0 = x / 10, y / 10
            rows.append([[x0, y0, 0], [x0 + 0.04, y0, 0], [x0, y0 + 0.04, 0]])
    tri = np.asarray(rows)
    grid = concept._projected_grid(tri, 0, 1)
    face = 5050
    point = tri[face, :, :2].mean(axis=0)

    candidates = concept._projected_candidates(grid, point)

    assert face in candidates
    assert len(candidates) < len(tri) // 100


def test_thickness_grid_finds_opposite_cube_faces():
    vertices = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=float)
    faces = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
    ])
    tri = vertices[faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals = cross / np.linalg.norm(cross, axis=1)[:, None]
    actual = simulation.thickness(tri, normals, np.arange(len(tri)), 0.01)
    np.testing.assert_allclose(actual, 1.0)


def test_part_mesh_is_loaded_once_per_unchanged_file(monkeypatch, tmp_path):
    path = tmp_path / "part.step"
    path.write_bytes(b"fixture")
    vertices = np.zeros((3, 3))
    triangles = np.array([[0, 1, 2]])
    calls = []

    monkeypatch.setattr(register, "_PART_MESH_CACHE", OrderedDict())
    monkeypatch.setattr(geometry, "load_step", lambda file_path: calls.append(file_path) or object())
    monkeypatch.setattr(geometry, "tessellate", lambda shape: (vertices.copy(), triangles.copy()))

    first = register._part_mesh(path)
    second = register._part_mesh(path)

    assert len(calls) == 1
    assert first is second
    assert not first[0].flags.writeable
    assert not first[1].flags.writeable


def test_simulation_result_is_reused_for_same_inputs(monkeypatch):
    from backend.app import register

    calls = []
    d, rev, concept_result, facts = {}, {"geometry": {"projected_area_mm2": {}}}, {}, {}
    monkeypatch.setattr(register, "_SIMULATION_CACHE_KEY", None)
    monkeypatch.setattr(register, "_SIMULATION_CACHE_VALUE", None)
    monkeypatch.setattr(register, "_simulation_key", lambda part_id: "same-inputs")
    monkeypatch.setattr(register, "_concept_inputs", lambda part_id: (d, rev, "plastic", [], [], concept_result, facts))
    monkeypatch.setattr(simulation, "run", lambda *args: calls.append(args) or {"result": True})

    first = register._simulate(1)
    second = register._simulate(1)

    assert first is second
    assert len(calls) == 1
