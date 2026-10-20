"""Product navigation isolates experimental execution without hiding failures."""
import builtins

import pytest
from streamlit.testing.v1 import AppTest

from monsoon.service import ROOT


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "interactive"))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var/hydraulic_runs"))


def reject_experimental_imports(monkeypatch):
    original = builtins.__import__
    blocked = {"monsoon.bench_fv", "monsoon.bench_conservative", "monsoon.bench_conservative_ui"}

    def guarded(name, *args, **kwargs):
        if name in blocked:
            raise AssertionError("Default product view imported an experimental solver workspace")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_default_product_pages_keep_adverse_evidence_without_experimental_imports(local_data, monkeypatch):
    reject_experimental_imports(monkeypatch)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not app.exception
    assert app.sidebar.checkbox(key="research_tools_enabled").value is False
    assert app.sidebar.radio(key="workspace").options == ["Rehearse", "Work window", "Work tickets", "Evidence"]
    assert app.sidebar.radio(key="workspace").value == "Rehearse"
    for page in ("Work window", "Work tickets", "Evidence"):
        app.sidebar.radio(key="workspace").set_value(page).run()
        assert not app.exception, [e.value for e in app.exception]
    warnings = "\n".join(item.value for item in app.warning)
    assert "experimental conservative bench solver is unqualified" in warnings
    assert "mesh-accuracy check" in warnings
    assert "both fail the per-location no-worsening screen in H2" in warnings
    assert any("ties the adaptive marginal baseline" in item.value for item in app.info)
    assert any(item.label == "Unqualified custom-solver research (v0.7)" for item in app.expander)


def test_research_opt_in_and_revocation_reset_stale_workspace(local_data):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    app.sidebar.checkbox(key="research_tools_enabled").check().run()
    assert "Validation" in app.sidebar.radio(key="workspace").options
    app.sidebar.radio(key="workspace").set_value("Validation").run()
    app.radio(key="validation_area").set_value("Conservative bench").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("Experimental solver — unqualified" in item.value for item in app.warning)
    assert app.button(key="fv_run").disabled
    app.sidebar.checkbox(key="research_tools_enabled").uncheck().run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.sidebar.radio(key="workspace").value == "Rehearse"
    assert "Validation" not in app.sidebar.radio(key="workspace").options
    assert all(item.key != "fv_run" for item in app.button)
    assert all(item.key != "validation_area" for item in app.radio)


def test_direct_validation_render_rejects_stale_selection_without_opt_in(local_data, monkeypatch):
    reject_experimental_imports(monkeypatch)
    app = AppTest.from_string("from monsoon.validation_ui import render_validation\nrender_validation()")
    app.session_state["validation_area"] = "Conservative bench"
    app.session_state["research_tools_enabled"] = False
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("Research tools are off" in item.value for item in app.info)
    assert not app.radio and not app.button and not app.text_area


def test_historical_decisions_render_reasons_and_metrics_without_actions(local_data):
    from monsoon.decision_review import load_decision_review

    review = load_decision_review(ROOT)
    assert review["status"] == "verified"
    app = AppTest.from_string("from app import decision_review_panel\ndecision_review_panel()").run()
    assert not app.exception, [e.value for e in app.exception]
    text = "\n".join(item.value for item in app.markdown)
    for card in review["cards"]:
        assert card["title"] in text
        assert card["explanation"] in text
    assert len(app.dataframe) == 3
    assert all("Difference used by check" in item.value.columns for item in app.dataframe)
    numerical_row = app.dataframe[2].value.iloc[0]
    assert "0.5 s routing step" in numerical_row["Reference"]
    assert "0.25 s routing step" in numerical_row["Compared"]
    assert numerical_row["Difference used by check"] > numerical_row["Allowed difference"]
    assert any("cannot approve or dispatch work" in item.value for item in app.caption)
    assert not app.button and not app.get("download_button") and not app.text_input and not app.selectbox


def test_changed_decision_evidence_hides_cards_instead_of_reusing_them(local_data, monkeypatch):
    import monsoon.decision_review as decision_review

    monkeypatch.setattr(decision_review, "load_decision_review", lambda *_: {
        "status": "unavailable", "errors": ["Source hash changed"],
        "cards": [{"title": "STALE BENEFIT MUST NOT RENDER"}],
    })
    app = AppTest.from_string("from app import decision_review_panel\ndecision_review_panel()").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("missing or has changed" in item.value for item in app.error)
    assert all("STALE BENEFIT" not in item.value for item in app.markdown)
    assert not app.dataframe and not app.button
