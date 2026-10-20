"""UI evidence checks use isolated synthetic research workspaces."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from monsoon.service import ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "interactive"))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var/hydraulic_runs"))
    result = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    result.sidebar.checkbox(key="research_tools_enabled").check().run()
    result.sidebar.radio[0].set_value("Validation").run()
    assert not result.exception, [x.value for x in result.exception]
    return result


def test_wet_inputs_start_blank(app):
    app.radio(key="validation_area").set_value("Wet preparation").run()
    assert not app.exception, [x.value for x in app.exception]
    assert app.radio(key="wet_source").value == "Supplied files"
    assert app.button(key="wet_run").disabled
    assert app.button(key="wet_check").disabled
    assert all(not app.text_area(key="wet_input_" + k).value for k in ("site", "model", "run"))


@pytest.mark.hydraulic
def test_wet_native_result_export_and_stale_input_refusal(app):
    from monsoon.bench_initialization import verify_prepared_bench_result
    from monsoon.bench_next_ui import _bundle
    from monsoon.service import data_root
    import io
    import zipfile

    app.radio(key="validation_area").set_value("Wet preparation").run()
    app.radio(key="wet_source").set_value("Synthetic example").run()
    app.button(key="wet_run").click().run()
    assert not app.exception, [x.value for x in app.exception]
    assert not app.error, [x.value for x in app.error]
    saved = app.session_state["wet_result"]
    result = saved["report"]
    assert result["valid"], result["errors"]
    assert result["initial_state"]["storage_m3"] > 0
    archive = _bundle(result, saved["seal"], data_root() / "prepared_bench_runs", verify_prepared_bench_result)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert set(bundle.namelist()) == set(result["files"])
        assert any(name.endswith("model.out") for name in bundle.namelist())
    path = Path(next(value for key, value in result["files"].items() if key.endswith("model.inp")))
    original = path.read_bytes()
    path.write_bytes(original + b"\n; synthetic alteration after acceptance\n")
    app.run()
    assert not app.exception
    assert any("cannot be used" in item.value for item in app.error)
    assert not any("passed its numerical checks" in item.value for item in app.success)
    path.write_bytes(original)
    app.radio(key="wet_source").set_value("Supplied files").run()
    assert any("inputs changed" in item.value for item in app.warning)
    assert not any("passed its numerical checks" in item.value for item in app.success)


def test_failed_wet_attempt_clears_previous_success(app, monkeypatch):
    import monsoon.bench_initialization as preparation

    app.radio(key="validation_area").set_value("Wet preparation").run()
    app.radio(key="wet_source").set_value("Synthetic example").run()
    app.session_state["wet_result"] = {"report": {"valid": True}, "signature": "old"}

    def fail(*args, **kwargs):
        raise ValueError("Deliberate preparation test failure")

    monkeypatch.setattr(preparation, "run_prepared_bench", fail)
    app.button(key="wet_run").click().run()
    assert not app.exception
    assert "wet_result" not in app.session_state
    assert any("Deliberate preparation" in item.value for item in app.error)
    assert not any("passed its numerical checks" in item.value for item in app.success)


def test_invalid_wet_contract_never_invents_zero_water_metrics(app):
    app.radio(key="validation_area").set_value("Wet preparation").run()
    for name in ("site", "model", "run"):
        app.text_area(key="wet_input_" + name).set_value("{broken")
    app.run()
    app.button(key="wet_run").click().run()
    assert not app.exception, [x.value for x in app.exception]
    assert not any(item.label == "Water at test start" for item in app.metric)
    assert not any("passed its numerical checks" in item.value for item in app.success)


def test_replay_inputs_start_blank(app):
    app.radio(key="validation_area").set_value("Boundary replay").run()
    assert not app.exception, [x.value for x in app.exception]
    assert app.radio(key="replay_activity").value == "Study workspace"
    assert app.button(key="replay_create").disabled
    assert not app.text_area(key="replay_site").value
    assert not app.text_input(key="replay_title").value


@pytest.mark.hydraulic
@pytest.mark.parametrize("missing", [False, True])
def test_boundary_receipts_responses_and_freeze_in_ui(app, missing):
    import io
    import json
    import zipfile
    from monsoon.bench_next_demo import replay_inputs, circular_responses
    from monsoon.bench_replay import BenchReplayStore
    from monsoon.service import data_root

    inputs = replay_inputs()
    app.radio(key="validation_area").set_value("Boundary replay").run()
    app.text_input(key="replay_title").set_value("Synthetic separated-input UI test")
    app.text_area(key="replay_site").set_value(json.dumps(inputs["site"])).run()
    app.button(key="replay_create").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    for key, value in (("model", inputs["model"]), ("recipe", inputs["recipe"]),
                       ("event", inputs["calibration_event"]), ("boundaries", inputs["calibration_boundaries"])):
        app.text_area(key="replay_cal_" + key).set_value(json.dumps(value))
    app.run()
    app.button(key="replay_cal_record").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    with BenchReplayStore(data_root() / "bench_replay.sqlite3") as store:
        state = store.get(store.list_studies()[0]["study_id"])
    receipt = state["calibrations"][0]
    assert receipt["prediction_seal_sha256"] and receipt["response_status"] == "pending"
    observations = circular_responses(receipt, inputs["calibration_boundaries"], multiplier=1)
    app.text_area(key="replay_responses").set_value(json.dumps(observations)).run()
    app.button(key="replay_record_responses").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    app.text_area(key="replay_future_plan").set_value(json.dumps({"events": [inputs["validation_event"]]}))
    app.text_area(key="replay_freeze_rationale").set_value("Circular synthetic UI test, no actual measurement or parameter fit.")
    app.run()
    app.button(key="replay_freeze").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    assert not any(b.key == "replay_cal_record" for b in app.button)
    app.text_area(key="replay_val_boundaries").set_value(json.dumps(inputs["validation_boundaries"])).run()
    app.button(key="replay_val_record").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    with BenchReplayStore(data_root() / "bench_replay.sqlite3") as store:
        state = store.get(state["study_id"])
    receipt = state["validations"][0]
    observations = circular_responses(receipt, inputs["validation_boundaries"], multiplier=10)
    if missing:
        observations["samples"][0]["observed"][inputs["recipe"]["response_series"][0]["id"]] = None
    app.text_area(key="replay_responses").set_value(json.dumps(observations)).run()
    app.button(key="replay_record_responses").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    with BenchReplayStore(data_root() / "bench_replay.sqlite3") as store:
        state = store.get(state["study_id"])
        assert store.verify(state["study_id"])["valid"]
        assert state["status"] == "withheld_records_complete"
        assert state["validations"][0]["comparison"]["status"] == ("unresolved" if missing else "resolved_errors")
        assert state["physical_validation_established"] is False
        assert state["operational_activation_allowed"] is False
    if missing:
        assert any("attempt remains unresolved" in item.value for item in app.warning)
    app.button(key="replay_prepare_export").click().run()
    assert not app.exception and not app.error, [x.value for x in app.error]
    saved = app.session_state["replay_export"]
    assert saved["study_id"] == state["study_id"]
    assert saved["head_sha256"] == state["head_sha256"]
    with BenchReplayStore(data_root() / "bench_replay.sqlite3") as store:
        expected = store.export_evidence(state["study_id"])
    # ZIP creation timestamps may differ; every evidence name and byte must match.
    with zipfile.ZipFile(io.BytesIO(saved["bytes"])) as actual_zip, zipfile.ZipFile(io.BytesIO(expected)) as expected_zip:
        assert actual_zip.testzip() is None
        assert actual_zip.namelist() == expected_zip.namelist()
        assert all(actual_zip.read(name) == expected_zip.read(name) for name in expected_zip.namelist())


def test_failed_replay_exercise_clears_previous_success(app, monkeypatch):
    import monsoon.bench_next_demo as demo

    app.radio(key="validation_area").set_value("Boundary replay").run()
    app.radio(key="replay_activity").set_value("Software exercise").run()
    app.session_state["replay_exercise_result"] = {"status": "passed", "folder": "not-a-real-folder"}

    def fail(*args, **kwargs):
        raise ValueError("Deliberate replay test failure")

    monkeypatch.setattr(demo, "run_replay_exercise", fail)
    app.button(key="replay_exercise_run").click().run()
    assert not app.exception
    assert "replay_exercise_result" not in app.session_state
    assert any("Deliberate replay test failure" in item.value for item in app.error)
    assert not any("declared error arithmetic passed" in item.value for item in app.success)
