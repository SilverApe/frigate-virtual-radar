"""Tests for the parts that do not need Home Assistant: geometry and slot tracking.

Run with:  python3 -m pytest tests   (or plain:  python3 tests/test_core.py)
"""
import importlib.util
import json
import math
import pathlib
import sys
import types

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "frigate_virtual_radar"
pkg = types.ModuleType("fvr")
pkg.__path__ = [str(PKG)]
sys.modules["fvr"] = pkg
for mod in ("geometry", "tracker"):
    spec = importlib.util.spec_from_file_location(f"fvr.{mod}", PKG / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"fvr.{mod}"] = m
    spec.loader.exec_module(m)

from fvr.geometry import CalibrationError, apply, foot_point, homography, parse_calibration  # noqa: E402
from fvr.tracker import VirtualRadar  # noqa: E402


def make_cal(origin=(2.0, 6.0)):
    # A known projective map, used to generate consistent point pairs.
    H = [0.004, 0.0005, 1.0, 0.0002, 0.006, 2.0, 0.00001, 0.0002, 1.0]
    img = [(300, 900), (1600, 950), (1400, 500), (500, 450)]
    pts = [{"img": list(p), "plan": list(apply(H, *p))} for p in img]
    return H, json.dumps({"camera": "camera_01", "image_size": [1920, 1080], "points": pts, "origin": list(origin)})


def test_homography_roundtrip():
    H, text = make_cal()
    cal = parse_calibration(text)
    for u, v in [(10, 1070), (960, 700), (1900, 800)]:
        a = apply(H, u, v); b = cal.to_plan(u, v)
        assert math.dist(a, b) < 1e-6


def test_least_squares_with_five_points():
    H, _ = make_cal()
    img = [(300, 900), (1600, 950), (1400, 500), (500, 450), (900, 700)]
    h = homography([(p, apply(H, *p)) for p in img])
    assert math.dist(apply(h, 1000, 1000), apply(H, 1000, 1000)) < 1e-6


def test_collinear_points_rejected():
    bad = json.dumps({"image_size": [1920, 1080], "origin": [0, 0],
                      "points": [{"img": [i * 100, i * 100], "plan": [i, i]} for i in range(4)]})
    try:
        parse_calibration(bad)
    except CalibrationError:
        return
    raise AssertionError("collinear points should fail")


def test_foot_point_pixels_and_relative():
    assert foot_point([100, 200, 300, 800], (1920, 1080)) == (200.0, 800.0)
    u, v = foot_point([0.1, 0.2, 0.1, 0.5], (1920, 1080))
    assert math.isclose(u, 0.15 * 1920) and math.isclose(v, 0.7 * 1080)


def test_radar_frame_inverts_y():
    _, text = make_cal(origin=(2.0, 6.0))
    cal = parse_calibration(text)
    assert cal.to_radar_cm(3.0, 5.0) == (100.0, 100.0)  # 1 m right, 1 m up (plan Y is down)


def ev(t, fid, label="person", box=(900, 400, 1000, 900), camera="camera_01", **kw):
    after = {"id": fid, "camera": camera, "label": label, "box": list(box), **kw}
    return {"type": t, "after": after}


def radar(min_move=5.0):
    _, text = make_cal()
    return VirtualRadar("camera_01", parse_calibration(text),
                        {"person": ({"person"}, 2), "dog": ({"dog"}, 1)}, min_move_cm=min_move)


def test_slots_fill_and_free():
    r = radar()
    assert r.handle_event(ev("new", "a"), 0) == {("person", 0)}
    assert r.handle_event(ev("new", "b", box=(100, 400, 200, 950)), 0) == {("person", 1)}
    assert r.handle_event(ev("new", "c"), 0) == set()  # no third slot
    assert r.count("person") == 2
    assert r.handle_event(ev("end", "a"), 1) == {("person", 0)}
    assert r.target("person", 0) is None and r.count("person") == 1


def test_dog_never_in_person_slots():
    r = radar()
    assert r.handle_event(ev("new", "d", label="dog"), 0) == {("dog", 0)}
    assert r.count("person") == 0 and r.count("dog") == 1


def test_other_camera_and_label_ignored():
    r = radar()
    assert r.handle_event(ev("new", "x", camera="garage"), 0) == set()
    assert r.handle_event(ev("new", "y", label="car"), 0) == set()


def test_small_moves_filtered_but_sub_label_passes():
    r = radar(min_move=50)
    r.handle_event(ev("new", "a"), 0)
    assert r.handle_event(ev("update", "a", box=(901, 400, 1001, 901)), 1) == set()
    assert r.handle_event(ev("update", "a", box=(901, 400, 1001, 901), sub_label=["Aaron", 0.9]), 2) == {("person", 0)}
    assert r.target("person", 0).sub_label == "Aaron"


def test_false_positive_and_expire():
    r = radar()
    r.handle_event(ev("new", "a"), 0)
    assert r.handle_event(ev("update", "a", false_positive=True), 1) == {("person", 0)}
    r.handle_event(ev("new", "b"), 10)
    assert r.expire(100, 60) == {("person", 0)}


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); n += 1
    print(f"{n} tests passed")
