"""Bench UI checks use isolated local data; none create physical observations."""
from pathlib import Path
import json

import pytest
from streamlit.testing.v1 import AppTest

from monsoon.service import ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "interactive"))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var" / "hydraulic_runs"))
    result = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    result.sidebar.checkbox(key="research_tools_enabled").check().run()
    result.sidebar.radio[0].set_value("Validation").run()
    result.radio(key="validation_area").set_value("Bench model").run()
    assert not result.exception, [x.value for x in result.exception]
    return result


def test_bench_import_starts_blank_and_cannot_run_without_inputs(app):
    assert app.radio(key="bench_input_source").value == "Supplied files"
    assert app.button(key="bench_run").disabled
    assert app.button(key="bench_check").disabled
    assert all(not app.text_area(key="bench_" + key + "_json").value for key in ("site", "model", "run"))
    assert any("24-run" in item.value and "unsupported" in item.value for item in app.warning)


def test_malformed_model_check_is_visible_and_does_not_touch_reference(app):
    original = (ROOT / "data/reference_case.json").read_bytes()
    for key in ("site", "model", "run"):
        app.text_area(key="bench_" + key + "_json").set_value("{broken")
    app.run()
    app.button(key="bench_check").click().run()
    assert not app.exception
    assert not app.session_state["bench_contract_check"]["report"]["valid"]
    assert app.error
    assert original == (ROOT / "data/reference_case.json").read_bytes()


def test_real_engine_example_result_stales_when_input_source_changes(app):
    app.radio(key="bench_input_source").set_value("Synthetic example").run()
    app.button(key="bench_run").click().run()
    assert not app.exception, [x.value for x in app.exception]
    result = app.session_state["bench_run_result"]["report"]
    assert result["timeseries"]
    assert result["valid"]
    assert not result["physical_validation_established"]
    assert not result["operational_activation_allowed"]
    from monsoon.bench_ui import _run_bundle
    import io
    import zipfile
    exported = _run_bundle(result, app.session_state["bench_run_result"]["manifest_sha256"])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert set(archive.namelist()) == set(result["files"])
        assert any(name.startswith("half/") and name.endswith("model.inp") for name in archive.namelist())
    artifact = Path(next(path for name, path in result["files"].items() if name.endswith("model.inp")))
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"\n; changed after calculation\n")
    app.run()
    assert not app.exception
    assert app.error
    assert not any("passed its numerical" in w.value for w in app.success)
    artifact.write_bytes(original)
    app.radio(key="bench_input_source").set_value("Supplied files").run()
    assert not app.exception
    assert any("inputs changed" in w.value for w in app.warning)
    assert not any("passed its numerical" in w.value for w in app.success)


def test_study_store_error_is_visible(app, monkeypatch):
    import monsoon.bench_study as study

    def refuse(*args, **kwargs):
        raise ValueError("Stored study failed integrity verification")

    monkeypatch.setattr(study, "BenchStudyStore", refuse)
    app.radio(key="bench_activity").set_value("Calibration & freeze").run()
    assert not app.exception
    assert any("integrity verification" in e.value for e in app.error)


def test_failed_new_exercise_cannot_display_previous_success(app, monkeypatch):
    import monsoon.bench_demo as demo

    app.radio(key="bench_activity").set_value("Software exercise").run()
    app.session_state["bench_exercise_result"] = {"status": "passed", "folder": "nonexistent"}

    def fail(*args, **kwargs):
        raise ValueError("Synthetic attempt deliberately failed")

    monkeypatch.setattr(demo, "run_exercise", fail)
    app.button(key="bench_exercise_run").click().run()
    assert not app.exception
    assert any("deliberately failed" in e.value for e in app.error)
    assert not any("sequence and known-error" in s.value for s in app.success)
    assert "bench_exercise_result" not in app.session_state


@pytest.mark.parametrize("withheld_missing", [False, True])
def test_calibration_freeze_and_withheld_ui_preserve_synthetic_limits(app, tmp_path, withheld_missing):
    from monsoon.bench_demo import exercise_inputs, synthetic_responses
    from monsoon.bench_study import BenchStudyStore
    from monsoon.service import data_root

    site, model, events = exercise_inputs()
    calibration = synthetic_responses(site, model, events[0], tmp_path / "generator", offset_m=0.001)
    app.radio(key="bench_activity").set_value("Calibration & freeze").run()
    app.text_input(key="bench_study_title").set_value("SYNTHETIC UI workflow exercise")
    app.text_area(key="bench_study_site").set_value(json.dumps(site)).run()
    app.button(key="bench_create_study").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    for key, value in (("model", model), ("event", events[0]), ("observations", calibration)):
        app.text_area(key="bench_cal_" + key).set_value(json.dumps(value))
    app.run()
    app.button(key="bench_record_cal").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    app.text_area(key="bench_freeze_plan").set_value(json.dumps({"events": [events[1]]}))
    app.text_area(key="bench_freeze_rationale").set_value("Synthetic form test; no model fitting or physical evidence.")
    app.run()
    app.button(key="bench_freeze").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    assert not any(b.key == "bench_record_cal" for b in app.button)
    withheld = synthetic_responses(site, model, events[1], tmp_path / "generator", offset_m=0.01)
    if withheld_missing:
        withheld["samples"][0]["observed"]["SYN-STAGE-A"] = None
    app.text_area(key="bench_validation_observations").set_value(json.dumps(withheld)).run()
    app.button(key="bench_record_validation").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    with BenchStudyStore(data_root() / "bench_studies.sqlite3") as store:
        state = store.get(store.list_studies()[0]["study_id"])
        assert state["status"] == "withheld_records_complete"
        comparison = state["validations"][0]["comparison"]
        if withheld_missing:
            assert comparison["status"] == "unresolved"
            assert comparison["series"][0]["missing_count"] == 1
            assert any("retained response checks remain unresolved" in item.value for item in app.warning)
        else:
            assert comparison["series"][0]["rmse"] == pytest.approx(0.01)
        assert not state["physical_validation_established"] and not state["full_protocol_completed"]
        assert store.verify(state["study_id"])["valid"]
    assert any("does not complete" in item.value for item in app.info)
