import hashlib
import json
from monsoon.audit_view import bound_trace, spill_values


def test_trace_requires_bound_bytes_and_exact_run_identity(tmp_path):
    path = tmp_path / "result.json"
    raw = json.dumps({"run_id": "run-a", "timeseries": [{"minutes": 1, "depth_A": .2}]}).encode()
    path.write_bytes(raw)
    record = {"run_id": "run-a", "files": {"result": str(path)}, "result_file_sha256": hashlib.sha256(raw).hexdigest()}
    audit = {"hydraulic_evidence": {"entry": {"raw_provenance": [record]}}}
    assert bound_trace(audit, "run-a")["timeseries"][0]["depth_A"] == .2
    assert bound_trace(audit, "other") is None
    path.write_bytes(raw.replace(b'0.2', b'0.9'))
    assert bound_trace(audit, "run-a") is None
    record["result_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    record["run_id"] = "other"
    assert bound_trace(audit, "other") is None
    path.unlink()
    assert bound_trace(audit, "other") is None


def test_signed_change_preserves_missing_invalid_and_distinct_baselines():
    result = {"nodes": {"A": {"spill_m3": 3.}, "B": {"spill_m3": float('nan')}, "C": {"spill_m3": 0.}, "D": {"spill_m3": True}}}
    reference = {"nodes": {"A": {"spill_m3": 5.}}}
    assert spill_values(result, reference, change=True) == {"A": -2., "B": None, "C": None, "D": None}
    assert spill_values(result) == {"A": 3., "B": None, "C": 0., "D": None}
