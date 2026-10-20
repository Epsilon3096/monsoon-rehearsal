"""Adversarial evidence and authority checks for the separate demonstration."""
from copy import deepcopy
import json
import shutil

import pytest
from streamlit.testing.v1 import AppTest

from monsoon.demo_ui import BENCHMARK, MANIFEST_SHA256
from monsoon.maintenance_benchmark import compare_pair, load_results


def runs(a, b):
    return [dict(valid=True, status="succeeded", total_spill_m3=a+b,
                 nodes={"A": {"spill_m3": a}, "B": {"spill_m3": b}}) for _ in range(3)]


def test_recorded_native_benchmark_retains_positive_null_and_unresolved_controls():
    loaded = load_results(BENCHMARK, MANIFEST_SHA256)
    assert loaded["status"] == "verified", loaded
    r = loaded["result"]
    assert r["primary_mechanism_supported"] and r["null_control_passed"] and r["late_work_skipped"]
    assert len(r["comparisons"]) == 6
    assert all(c["positive_mechanism"] for c in r["comparisons"][:4])
    assert r["comparisons"][-1]["status"] == "unresolved"
    assert any("event-horizon disagreement" in x for x in r["comparisons"][-1]["errors"])
    assert r["timing"]["120"]["completed_jobs"] == ["M1"]
    assert r["timing"]["50"]["completed_jobs"] == []
    assert r["timing"]["50"]["skipped"][0]["reason"] == "insufficient_bound_window"
    assert not any(r[k] for k in ("approval_allowed", "dispatch_allowed",
                                 "physical_validation_established", "operator_validation_established"))
    assert len(list(BENCHMARK.glob("*/result.json"))) == 36


@pytest.mark.parametrize("index", [0, 1, 2])
def test_any_configuration_location_harm_blocks_even_with_lower_total(index):
    before, after = runs(100, 0), runs(50, 0)
    after[index]["nodes"]["B"]["spill_m3"] = .06
    after[index]["total_spill_m3"] += .06
    r = compare_pair(before, after, ["A", "B"])
    # Depending on the configuration, numerical uncertainty may also stop it.
    assert r["status"] in ("unresolved", "failed")
    assert not r.get("positive_mechanism", False) and r["approval_allowed"] is False


@pytest.mark.parametrize("fault", ["invalid", "missing", "nan", "negative", "step", "horizon"])
def test_bad_numerical_evidence_is_unresolved(fault):
    before, after = runs(100, 0), runs(50, 0)
    if fault == "invalid":
        after[1]["valid"] = False
    elif fault == "missing":
        del after[1]["nodes"]["A"]
    elif fault in ("nan", "negative"):
        after[1]["nodes"]["A"]["spill_m3"] = float("nan") if fault == "nan" else -1
    else:
        after[1 if fault == "step" else 2]["nodes"]["A"]["spill_m3"] += 3
    r = compare_pair(before, after, ["A", "B"])
    assert r["status"] == "unresolved" and r["approval_allowed"] is False


def test_fewer_than_three_configurations_is_unresolved():
    assert compare_pair(runs(100, 0)[:2], runs(0, 0), ["A", "B"])["status"] == "unresolved"


@pytest.mark.parametrize("target", ["results.json", "T1-restored-0.5-180/model.out",
                                   "protocol.json", "manifest.json"])
def test_changed_evidence_fails_closed(tmp_path, target):
    copy = tmp_path / "benchmark"
    shutil.copytree(BENCHMARK, copy)
    p = copy / target
    p.write_bytes(p.read_bytes() + b"\nchanged")
    loaded = load_results(copy, MANIFEST_SHA256)
    assert loaded["status"] == "unavailable" and "result" not in loaded


def test_changed_current_source_cannot_reuse_recorded_success(monkeypatch):
    import monsoon.maintenance_benchmark as benchmark
    original = benchmark.digest
    monkeypatch.setattr(benchmark, "digest", lambda p: "changed" if str(p).endswith("planning.py") else original(p))
    assert load_results(BENCHMARK, MANIFEST_SHA256)["status"] == "unavailable"


def test_walkthrough_is_read_only_and_exposes_limits():
    app = AppTest.from_string("from monsoon.demo_ui import render_demo\nrender_demo()").run()
    assert not app.exception
    assert len(app.metric) == 3 and not app.button
    app.selectbox[0].set_value("C_BACKWATER").run()
    assert not app.exception
    assert not app.metric and any("Unresolved" in x.value for x in app.warning)
    app.radio(key="demo_step").set_value("2 · Work before rain").run()
    app.radio[1].set_value(50).run()
    assert any("Skip M1" in x.value for x in app.warning)
    app.radio(key="demo_step").set_value("3 · Catch transferred harm").run()
    assert any("STOP" in x.value for x in app.error)
    app.radio(key="demo_step").set_value("4 · Operator review").run()
    assert any("No completed operator interview" in x.value for x in app.warning)
    assert not app.button and not app.text_input and not app.text_area
    assert not app.exception


def test_changed_evidence_hides_demo_numbers(monkeypatch):
    import monsoon.demo_ui as demo
    monkeypatch.setattr(demo, "load_results", lambda *_: {"status": "unavailable", "errors": ["Changed"]})
    app = AppTest.from_string("from monsoon.demo_ui import render_demo\nrender_demo()").run()
    assert not app.exception and not app.metric and not app.dataframe
    assert any("missing or changed" in x.value for x in app.error)
