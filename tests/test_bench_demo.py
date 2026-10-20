"""The practice runner verifies lineage and known errors, not physical truth."""
import pytest

from monsoon.bench_demo import run_exercise
from monsoon.bench_study import BenchStudyStore


@pytest.mark.hydraulic
def test_explicit_synthetic_roundtrip_reports_known_error_without_validation_claim(tmp_path):
    result = run_exercise(tmp_path)
    assert result["status"] == "passed"
    assert result["declared_error_arithmetic_verified"]
    assert not result["physical_validation_established"]
    assert not result["independent_hydraulic_validation"]
    assert not result["operational_activation_allowed"]
    assert result["withheld_comparison"]["series"][0]["rmse"] == pytest.approx(0.01)
    with BenchStudyStore(result["folder"] + "/exercise.sqlite3") as store:
        state = store.get(result["study_id"])
        assert len(state["calibrations"]) == len(state["validations"]) == 1
        assert state["calibrations"][0]["recorded_at"] <= state["freeze"]["frozen_at"] <= state["validations"][0]["recorded_at"]
        assert not state["full_protocol_completed"]
        assert all(event["window"] is None for event in state["freeze"]["validation_plan"])
