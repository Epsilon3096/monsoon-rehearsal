"""Independent adversarial checks for derived metrics and cache recovery."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from monsoon.case import get_scenario, load_case
from monsoon import hydraulics


def test_storage_and_outfall_geometry_comes_from_case(monkeypatch):
    case = load_case()
    storage = next(n for n in case["nodes"] if n["kind"] == "storage")
    outfall = next(n for n in case["nodes"] if n["kind"] == "outfall")
    storage.update(invert_m=100.15, max_depth_m=2.5)
    outfall["invert_m"] = 99.1
    case["storage_area_m2"] = 450
    monkeypatch.setattr(hydraulics, "load_case", lambda: copy.deepcopy(case))
    condition = get_scenario("H2")["hydraulic"]
    condition["initial_storage_depth_m"] = 2.25

    generated = hydraulics.build_input([], condition).splitlines()

    assert "S 100.15 2.5 2.25 FUNCTIONAL 0 0 450 0 0" in generated
    assert "O 99.1 FIXED 100.1 NO" in generated


def test_changed_storage_area_changes_initial_water_volume(tmp_path, monkeypatch):
    scenario = get_scenario("H2")
    original = hydraulics.run_state([], scenario, tmp_path)
    assert original["valid"], original["errors"]
    case = load_case()
    case["storage_area_m2"] = 600
    monkeypatch.setattr(hydraulics, "load_case", lambda: copy.deepcopy(case))

    changed = hydraulics.run_state([], scenario, tmp_path)

    assert changed["valid"], changed["errors"]
    assert changed["diagnostics"]["initial_storage_m3"]-original["diagnostics"]["initial_storage_m3"] == pytest.approx(375, abs=1e-8)


def test_changed_threshold_does_not_reuse_derived_metrics(tmp_path, monkeypatch):
    """The engine input is identical, but the reported duration metric changed."""
    scenario = get_scenario("P1")
    original = hydraulics.run_state([], scenario, tmp_path)
    assert original["valid"], original["errors"]
    changed_case = copy.deepcopy(load_case())
    changed_case["depth_threshold_fraction"] = 0.4
    monkeypatch.setattr(hydraulics, "load_case", lambda: copy.deepcopy(changed_case))

    changed = hydraulics.run_state([], scenario, tmp_path)

    assert changed["valid"], changed["errors"]
    assert changed["nodes"]["A1"]["threshold_m"] == pytest.approx(0.4)
    assert (changed["nodes"]["A1"]["duration_above_threshold_min"]
            > original["nodes"]["A1"]["duration_above_threshold_min"])


@pytest.mark.parametrize("corrupt_value", [None, [], {"files": None}])
def test_structurally_corrupt_json_cache_recovers(tmp_path, corrupt_value):
    """Syntactically valid corrupt cache records must never crash a rehearsal."""
    scenario = get_scenario("P1")
    original = hydraulics.run_state([], scenario, tmp_path)
    assert original["valid"], original["errors"]
    pointer = tmp_path / original["run_id"] / "result.json"
    pointer.write_text(json.dumps(corrupt_value), encoding="utf-8")

    recovered = hydraulics.run_state([], scenario, tmp_path)

    assert recovered["valid"], recovered["errors"]
    assert not recovered["cache_hit"]
    assert recovered["total_spill_m3"] == original["total_spill_m3"]
    assert Path(recovered["files"]["input"]) != Path(original["files"]["input"])


def test_incomplete_manifest_cannot_hide_corrupt_engine_output(tmp_path):
    scenario = get_scenario("P1")
    original = hydraulics.run_state([], scenario, tmp_path)
    manifest_path = Path(original["files"]["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["file_sha256"]["model.out"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    Path(original["files"]["output"]).write_bytes(b"damaged native output")

    recovered = hydraulics.run_state([], scenario, tmp_path)

    assert recovered["valid"] and not recovered["cache_hit"]
    assert recovered["total_spill_m3"] == original["total_spill_m3"]


def test_saved_result_and_cached_result_must_agree(tmp_path):
    scenario = get_scenario("P1")
    original = hydraulics.run_state([], scenario, tmp_path)
    Path(original["files"]["result"]).write_text("null", encoding="utf-8")

    recovered = hydraulics.run_state([], scenario, tmp_path)

    assert recovered["valid"] and not recovered["cache_hit"]
    assert recovered["total_spill_m3"] == original["total_spill_m3"]


@pytest.mark.parametrize("scenario_id", ["P1", "P2", "P3", "P4", "H1", "H2"])
def test_event_spill_is_complete_before_extended_recession(tmp_path, scenario_id):
    """Planning/holdout storm spill must not merely be deferred beyond 3 h."""
    scenario = get_scenario(scenario_id)
    for completed in ([], ["J1", "J2", "J3", "J4"]):
        short = hydraulics.run_state(completed, scenario, tmp_path)
        long = hydraulics.run_state(completed, scenario, tmp_path, horizon_minutes=360)
        assert short["valid"] and long["valid"], (short["errors"], long["errors"])
        for node in load_case()["protected_nodes"]:
            assert long["nodes"][node]["spill_m3"] == pytest.approx(
                short["nodes"][node]["spill_m3"], abs=0.05
            )
