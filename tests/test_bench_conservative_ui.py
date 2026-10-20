"""Separate-engine UI never turns a stale or invalid result into acceptance."""
import json
from pathlib import Path
import zipfile
import io
import pytest
from streamlit.testing.v1 import AppTest
from monsoon.service import ROOT


@pytest.fixture
def app(tmp_path,monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR",str(tmp_path/"interactive"))
    monkeypatch.setenv("MONSOON_CACHE_DIR",str(ROOT/"var/hydraulic_runs"))
    app=AppTest.from_file(str(ROOT/"app.py"),default_timeout=180).run()
    app.sidebar.checkbox(key="research_tools_enabled").check().run()
    app.sidebar.radio[0].set_value("Validation").run()
    app.radio(key="validation_area").set_value("Conservative bench").run()
    assert not app.exception,[e.value for e in app.exception]
    return app


def test_blank_input_does_not_run_and_discloses_separate_engine(app):
    assert app.radio(key="fv_source").value == "Supplied files"
    assert app.button(key="fv_run").disabled and app.button(key="fv_check").disabled
    assert all(not app.text_area(key="fv_input_"+k).value for k in ("site","model","run"))
    assert any("different numerical method" in x.value for x in app.info)


def test_malformed_input_visible_no_water_metrics(app):
    for k in ("site","model","run"):
        app.text_area(key="fv_input_"+k).set_value("{broken")
    app.run()
    app.button(key="fv_check").click().run()
    assert not app.exception
    assert app.error and not app.metric
    assert not app.session_state["fv_contract"]["report"]["valid"]


def test_sealed_result_export_tamper_and_stale_controls(app):
    from monsoon.bench_conservative_ui import synthetic_inputs,evidence_bundle
    from monsoon.service import data_root
    s,m,r=synthetic_inputs("Seven-litre pulse")
    r["duration_s"]=2
    r["inflows"][0]["points"]=[{"elapsed_s":t,"value_m3_s":0} for t in (0,2)]
    r["receiving_stages"][0]["points"]=[{"elapsed_s":t,"stage_m":0} for t in (0,2)]
    for k,v in zip(("site","model","run"),(s,m,r)):
        app.text_area(key="fv_input_"+k).set_value(json.dumps(v))
    app.text_input(key="fv_phases").set_value("1")
    app.run()
    app.button(key="fv_run").click().run()
    assert not app.exception,[e.value for e in app.exception]
    assert not app.error,[e.value for e in app.error]
    saved=app.session_state["fv_result"]
    result=saved["report"]
    assert result["valid"]
    bundle=evidence_bundle(result,saved["manifest_sha256"],data_root()/"conservative_bench_runs")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == set(result["files"])|{"result.json","manifest.json"}
        assert archive.testzip() is None
    path=Path(result["artifact_directory"])/"primary/worker.log"
    original=path.read_bytes()
    path.write_bytes(b"changed after display")
    app.run()
    assert any("cannot be used" in e.value for e in app.error)
    assert not any("passed the fixed" in e.value for e in app.success)
    path.write_bytes(original)
    app.text_input(key="fv_phases").set_value("").run()
    assert any("Inputs changed" in w.value for w in app.warning)
    assert not any("passed the fixed" in e.value for e in app.success)


def test_failed_attempt_clears_previous_success(app,monkeypatch):
    from monsoon import bench_conservative
    app.radio(key="fv_source").set_value("Synthetic example").run()
    app.session_state["fv_result"]={"signature":"old","report":{"valid":True}}
    def failure(*a,**k):
        raise ValueError("Deliberate worker failure")
    monkeypatch.setattr(bench_conservative,"run_conservative_bench",failure)
    app.button(key="fv_run").click().run()
    assert not app.exception
    assert "fv_result" not in app.session_state
    assert any("Deliberate worker failure" in x.value for x in app.error)
