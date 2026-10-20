"""The replay demonstration is circular synthetic software evidence only."""
from pathlib import Path

import pytest

from monsoon.bench_next_demo import run_replay_exercise, verify_replay_exercise


@pytest.mark.hydraulic
def test_native_separated_boundary_exercise_and_changed_evidence_refusal(tmp_path):
    result = run_replay_exercise(tmp_path)
    assert result["status"] == "passed"
    assert result["declared_error_arithmetic_verified"] is True
    assert result["physical_validation_established"] is False
    assert result["independent_hydraulic_validation"] is False
    assert result["operational_activation_allowed"] is False
    assert len(result["summary_rows"]) == 8
    expected = {("Calibration", "m"): .001, ("Calibration", "m3/s"): 1e-7,
                ("Calibration", "m3"): 1e-6, ("Withheld", "m"): .01,
                ("Withheld", "m3/s"): 1e-6, ("Withheld", "m3"): 1e-5}
    for row in result["summary_rows"]:
        assert row["Calculated RMSE"] == pytest.approx(expected[row["Partition"], row["Unit"]], abs=1e-12)
    assert verify_replay_exercise(result, tmp_path)["valid"]
    path = Path(result["study_file"])
    path.write_bytes(path.read_bytes() + b" ")
    assert not verify_replay_exercise(result, tmp_path)["valid"]
    assert not verify_replay_exercise(result, tmp_path / "different-workspace")["valid"]
