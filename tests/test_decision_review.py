"""Historical explanations fail closed without invoking the hydraulic engine."""
import builtins
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from monsoon.decision_review import SOURCE_SHA256, load_decision_review


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def copied_evidence(tmp_path):
    for relative in SOURCE_SHA256:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def test_three_historical_cards_are_never_approval_or_physical_evidence():
    result = load_decision_review()
    assert result["status"] == "verified"
    assert result["errors"] == []
    assert [card["id"] for card in result["cards"]] == [
        "j4_p1_benefit", "h2_transfer_harm", "j2_j1_uncertainty"]
    assert all(source["verified"] and source["actual_sha256"] == SOURCE_SHA256[source["path"]]
               for source in result["sources"])
    for row in [result, *result["cards"]]:
        assert row["synthetic"] is True and row["historical"] is True
        assert row["approval_allowed"] is False
        assert row["dispatch_allowed"] is False
        assert row["physical_validation_established"] is False
    json.dumps(result, allow_nan=False)


def test_j4_p1_benefit_is_scoped_and_full_screen_remains_failed():
    card = load_decision_review()["cards"][0]
    assert (card["scenario_id"], card["queue"], card["completed_jobs"]) == ("P1", ["J4"], ["J4"])
    assert card["status"] == "scenario_benefit" and card["scenario_status"] == "supported"
    assert card["full_envelope_status"] == "failed"
    assert card["full_envelope_counts"] == {"passed": 12, "failed": 3, "unresolved": 0}
    metric = card["metrics"][0]
    assert metric["metric_id"] == "total_spill_m3" and metric["location_id"] == "network"
    assert metric["baseline_value"] == 54.77585487771761
    assert metric["action_value"] == 0.5384892486539424
    assert metric["difference"] == pytest.approx(-54.23736562906367)
    assert card["source_records"][1]["run_id"] == "40c0df274b6c87d9e05d8b1705b8cbce48e4f99a47501c51298d37facb9c0720"


def test_h2_keeps_lower_total_and_protected_harm_with_the_actual_completed_order():
    card = load_decision_review()["cards"][1]
    assert card["scenario_id"] == "H2" and card["scenario_status"] == "inadmissible"
    assert card["queue"] == ["J4", "J1", "J3", "J2"]
    assert card["completed_order"] == ["J4", "J3"] and card["completed_jobs"] == ["J3", "J4"]
    total, node = card["metrics"]
    assert (total["baseline_value"], total["action_value"]) == (1219.608507329018, 810.7718106724424)
    assert total["difference"] < 0
    assert (node["location_id"], node["baseline_value"], node["action_value"]) == ("B2", 280.77690219892827, 810.7718106724424)
    assert node["difference"] == pytest.approx(529.9949084735141)
    assert node["tolerance_value"] == 0.05 and node["difference"] > node["tolerance_value"]
    assert card["source_records"][1]["run_id"] == "033b27be259f641007ed48f427b6724ec8bf6bb7ad8058bc63fde57066480c58"


def test_uncertainty_has_step_identity_and_separate_h1_first_prefix_harm():
    card = load_decision_review()["cards"][2]
    assert card["queue"] == ["J2", "J1"] and card["completed_jobs"] == ["J1", "J2"]
    assert card["scenario_id"] == "S_STAGE" and card["scenario_status"] == "unresolved"
    assert card["full_envelope_counts"] == {"passed": 9, "failed": 5, "unresolved": 1}
    assert card["benefit_score_m3"] is None
    check, other = card["metrics"]
    assert (check["location_id"], check["baseline_label"], check["action_label"]) == ("T", "0.5 s routing step", "0.25 s routing step")
    assert (check["baseline_value"], check["action_value"]) == (0.9015528522204758, 0.8294292463974247)
    assert check["absolute_difference"] == 0.0721236058230511
    assert check["tolerance_value"] == 0.05 and check["diagnostic_only"] is True
    assert (other["scenario_id"], other["completed_jobs"], other["location_id"]) == ("H1", ["J2"], "B2")
    assert other["difference"] == 1.918316208363585
    assert other["tolerance_value"] == 0.05
    assert card["source_records"][1]["run_ids"] == {
        "default": "c513234f457945240e9810b6c784b438f7031aadf5e653993ab99b77baf82909",
        "half_step": "4c298a9161f17653dce6761fd319750768dbbb34f81afe6928d4da4711848107"}


@pytest.mark.parametrize("relative", tuple(SOURCE_SHA256))
def test_each_missing_source_refuses_all_cards(copied_evidence, relative):
    (copied_evidence / relative).unlink()
    result = load_decision_review(copied_evidence)
    assert result["status"] == "unavailable" and result["cards"] == []
    assert any(relative in error for error in result["errors"])
    assert result["approval_allowed"] is False


@pytest.mark.parametrize("relative", tuple(SOURCE_SHA256))
def test_each_altered_source_refuses_all_cards(copied_evidence, relative):
    path = copied_evidence / relative
    record = json.loads(path.read_bytes())
    if relative.endswith("planning.json"):
        record["plans"][0]["scenario_results"][0]["total_spill_m3"] = 0
    elif relative.endswith("holdouts.json"):
        target = next(row for row in record["comparisons"] if row["method"] == "robust" and row["scenario_id"] == "H2")
        target["nodes"]["B2"]["spill_m3"] = 0
    elif relative.endswith("census.json"):
        record["counts"]["passed"] = 28
    else:
        target = next(row for row in record.values() if row["scenario_id"] == "S_STAGE" and row["completed_jobs"] == ["J1", "J2"])
        target["raw"]["assurance_numerics"]["valid"] = True
    path.write_text(json.dumps(record), encoding="utf-8")
    result = load_decision_review(copied_evidence)
    assert result["status"] == "unavailable" and result["cards"] == []
    assert any(relative in error and "checksum" in error for error in result["errors"])


def test_relocated_sources_work_and_later_byte_changes_do_not_reuse_stale_cards(copied_evidence):
    first = load_decision_review(copied_evidence)
    assert first["status"] == "verified"
    assert first["cards"] == load_decision_review()["cards"]
    path = copied_evidence / "evidence/planning.json"
    path.write_bytes(path.read_bytes() + b"\n")
    second = load_decision_review(copied_evidence)
    assert second["status"] == "unavailable" and second["cards"] == []


def test_fresh_module_and_card_loading_need_no_engine_or_application_imports(monkeypatch):
    original_import = builtins.__import__

    def only_standard_imports(name, *args, **kwargs):
        if name.split(".")[0] in {"monsoon", "swmm", "streamlit"}:
            raise AssertionError(f"Unexpected application/engine import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", only_standard_imports)
    spec = importlib.util.spec_from_file_location("isolated_decision_review", ROOT / "monsoon/decision_review.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.load_decision_review(ROOT)["status"] == "verified"
