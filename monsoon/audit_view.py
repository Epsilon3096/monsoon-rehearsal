"""Read-only display data; never executes hydraulics or grants approval."""
import hashlib
import json
import math
from pathlib import Path


def bound_trace(audit, run_id):
    """Load only a result whose exact bytes and run identity the audit binds."""
    if not isinstance(run_id, str) or not run_id:
        return None
    for evidence in audit.get("hydraulic_evidence", {}).values():
        for record in evidence.get("raw_provenance", []):
            if record.get("run_id") != run_id:
                continue
            path = record.get("files", {}).get("result")
            expected = record.get("result_file_sha256")
            if not path or not expected:
                continue
            try:
                raw = Path(path).read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    continue
                result = json.loads(raw)
                if result.get("run_id") == run_id and isinstance(result.get("timeseries"), list):
                    return result
            except (OSError, ValueError, TypeError):
                continue
    return None


def spill_values(result, reference=None, *, change=False):
    """Missing/nonfinite metrics stay unknown, including a missing reference."""
    values = {}
    for node, metrics in result.get("nodes", {}).items():
        value = metrics.get("spill_m3")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            values[node] = None
            continue
        if change:
            baseline = (reference or {}).get("nodes", {}).get(node, {}).get("spill_m3")
            if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or not math.isfinite(baseline):
                values[node] = None
                continue
            value -= baseline
        values[node] = value
    return values
