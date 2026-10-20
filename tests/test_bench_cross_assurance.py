"""Independent replay admission check across a source/runtime restart boundary."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from monsoon import bench_model, bench_replay


def test_creation_lineage_change_cannot_create_unexportable_calibration(tmp_path, monkeypatch):
    """A new runtime requires a new study before any numerical work or receipt."""
    folder = Path(__file__).resolve().parents[1] / "data" / "templates"
    names = ("site", "model", "recipe", "calibration_event", "calibration_boundaries")
    values = {name: json.loads((folder / f"synthetic_bench_replay_{name}_v1.json").read_text()) for name in names}
    original = bench_replay._lineage()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Creation-lineage mismatch must fail before a native run.")

    monkeypatch.setattr(bench_model, "run_bench_model", forbidden)
    with bench_replay.BenchReplayStore(tmp_path / "cross-lineage.sqlite3") as store:
        created = store.create_study(values["site"], title="Explicit synthetic restart-boundary test")
        changed = deepcopy(original)
        changed["balance_audit_identity"]["audit_version"] = "EXPLICIT-UNIT-TEST-DIFFERENT-RUNTIME"
        monkeypatch.setattr(bench_replay, "_lineage", lambda: deepcopy(changed))
        with pytest.raises(bench_replay.BenchReplayError) as error:
            store.record_calibration_boundaries(created["study_id"], created["version"], model_spec=values["model"],
                                                recipe=values["recipe"], event=values["calibration_event"],
                                                boundaries=values["calibration_boundaries"])
        assert error.value.code == "lineage_changed"
        assert calls == []
        after = store.get(created["study_id"])
        assert after["version"] == created["version"]
        assert after["calibrations"] == []
