"""Additive fixed-geometry, continuous dry-to-wet bench preparation.

The event starts inside one uninterrupted SWMM run. No engine state, geometry,
or water is replaced at that boundary. Numerical stationarity is not measured
equilibration, and all physical/operational claims remain false.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

from . import bench_model as dry
from .site_data import _Checks, canonical_json, content_sha256, parse_json

PREPARED_RUN_SCHEMA = "monsoon.bench-prepared-run/1"
RESULT_SCHEMA = "monsoon.bench-prepared-result/1"
ADAPTER_VERSION = "1.0.0"
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CLAIMS = {**dry.CLAIMS, "physical_equilibration_established": False}
LIMITATIONS = [
    "Fixed geometry and complete contiguous forcing history from a declared nominal-dry state only; no wet reset, hotstart, or geometry stitching.",
    "A finite simulated preparation history does not establish a measured initial condition or physical equilibration.",
    "A passing stationarity window is bounded numerical evidence only; later drift or physical steadiness is not established.",
    "All node and conduit water is retained. Overflow leaves declared absorbing collectors; other escape paths remain unsupported.",
    "Zero evaporation, seepage and leakage remain explicit unverified assumptions. No physical validation or operational authority is established.",
]


def _empty():
    return {"schema_version": RESULT_SCHEMA, "valid": False, "status": "invalid_contract",
            "errors": [], "warnings": [], "limitations": list(LIMITATIONS),
            "timeseries": [], "full_timeseries": [], "diagnostics": {}, "files": {}, **CLAIMS}


def _prescribed_at(points, field, t):
    for a, b in zip(points, points[1:]):
        if a["elapsed_s"] <= t <= b["elapsed_s"]:
            f = (t - a["elapsed_s"]) / (b["elapsed_s"] - a["elapsed_s"])
            return a[field] + f * (b[field] - a[field])
    raise ValueError("Requested forcing time lies outside the declared contiguous history.")


def _validate(site, model, prepared_run, *, _refinement=False):
    result, c = _empty(), _Checks()
    try:
        p = parse_json(prepared_run)
        result["prepared_run_sha256"] = content_sha256(p)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        c.error("$.prepared_run", "invalid_json", str(exc))
        result["errors"] = c.errors
        return result, None
    c.obj(p, "$.prepared_run", {"schema_version", "prepared_run_id", "evidence_kind", "continuous_run", "event_start_s", "preparation", "notes"})
    c.choice(p.get("schema_version"), {PREPARED_RUN_SCHEMA}, "$.prepared_run.schema_version")
    c.ident(p.get("prepared_run_id"), "$.prepared_run.prepared_run_id")
    c.text(p.get("notes"), "$.prepared_run.notes")
    # Reuse the unchanged v1 restrictions over the ENTIRE preparation+event horizon.
    base, snapshot = dry._validate(site, model, p.get("continuous_run"), _refinement=_refinement)
    result.update({k: base.get(k) for k in ("site_package_sha256", "model_sha256", "run_sha256", "evidence_kind", "counts")})
    if p.get("continuous_run") is None:
        c.error("$.prepared_run.continuous_run", "continuous_run_required", "A complete bench-run/1 history is required.")
    if not base["valid"] or snapshot is None or snapshot.get("run") is None:
        result["errors"] = c.errors + base["errors"]
        return result, None
    s, m, run = (snapshot[k] for k in ("site", "model", "run"))
    c.choice(p.get("evidence_kind"), {m["evidence_kind"]}, "$.prepared_run.evidence_kind")
    event_ok = dry._number(c, p.get("event_start_s"), "$.prepared_run.event_start_s", 1, run["duration_s"] - 1, True)
    report_step = m["numerics"]["report_step_s"]
    if (run["duration_s"] // report_step + 1) * (len(s["nodes"]) + len(s["links"])) > 10000:
        c.error("$.prepared_run.continuous_run.duration_s", "prepared_output_budget", "Expanded full-state preparation evidence permits at most 10000 combined node/link reporting records across the whole history.")
    if event_ok and p["event_start_s"] % report_step:
        c.error("$.prepared_run.event_start_s", "event_report_grid", "Preparation must end exactly on the reporting and routing grids.")
    prep = c.obj(p.get("preparation"), "$.prepared_run.preparation", {"kind", "source_id", "equilibrium"})
    c.choice(prep.get("kind"), {"continuous_dry_start"}, "$.prepared_run.preparation.kind")
    source_id = prep.get("source_id")
    if not isinstance(source_id, str) or source_id not in {x["id"] for x in s["sources"]}:
        c.error("$.prepared_run.preparation.source_id", "source_required", "Reference a supplied site source for the preparation assumption.")
    eq = prep.get("equilibrium")
    eq = eq if isinstance(eq, dict) else c.obj(eq, "$.prepared_run.preparation.equilibrium", {"kind"})
    kind = eq.get("kind")
    c.choice(kind, {"not_claimed", "required_constant_forcing"}, "$.prepared_run.preparation.equilibrium.kind")
    if kind == "not_claimed":
        c.obj(eq, "$.prepared_run.preparation.equilibrium", {"kind"})
    elif kind == "required_constant_forcing":
        q = "$.prepared_run.preparation.equilibrium"
        c.obj(eq, q, {"kind", "window_s", "stage_range_tolerance_m", "storage_range_tolerance_m3", "flow_range_tolerance_m3_s"})
        # Fixed caps prevent a permissive recipe from converting an arbitrary wet transient to equilibrium.
        window_ok = dry._number(c, eq.get("window_s"), q + ".window_s", max(10, 2 * report_step), p["event_start_s"] if event_ok else 3600, True)
        dry._number(c, eq.get("stage_range_tolerance_m"), q + ".stage_range_tolerance_m", 1e-8, 1e-4)
        dry._number(c, eq.get("storage_range_tolerance_m3"), q + ".storage_range_tolerance_m3", 1e-10, 1e-6)
        dry._number(c, eq.get("flow_range_tolerance_m3_s"), q + ".flow_range_tolerance_m3_s", 1e-12, 1e-7)
        if window_ok and eq["window_s"] % report_step:
            c.error(q + ".window_s", "equilibrium_report_grid", "The complete stationarity window must align to the reporting grid.")
        if event_ok and window_ok:
            start, end = p["event_start_s"] - eq["window_s"], p["event_start_s"]
            for collection, field in (("inflows", "value_m3_s"), ("receiving_stages", "stage_m")):
                for row in run[collection]:
                    values = [_prescribed_at(row["points"], field, t) for t in (start, end)]
                    values += [v[field] for v in row["points"] if start < v["elapsed_s"] < end]
                    if max(values) != min(values):
                        c.error(q, "nonconstant_equilibrium_forcing", "Every prescribed boundary must be constant throughout the full stationarity window, including its endpoints.")
    result.update(valid=not c.errors, status="research_contract_valid" if not c.errors else "invalid_contract", errors=c.errors,
                  event_start_s=p.get("event_start_s"), evaluation_duration_s=run["duration_s"] - p["event_start_s"] if event_ok else None)
    return result, {**snapshot, "prepared_run": p} if not c.errors else None


def validate_prepared_bench_run(site, model, prepared_run):
    """Validate the complete history and recipe without running the engine."""
    return _validate(site, model, prepared_run)[0]


def prepared_bench_engine_identity():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
        raise ValueError("Prepared bench adapter source changed after import; restart before execution/freeze.")
    identity = dry.bench_engine_identity()
    identity["base_adapter_version"] = identity.pop("adapter_version")
    identity["prepared_adapter_version"] = ADAPTER_VERSION
    for name in ("bench_initialization.py", "_bench_initialization_worker.py"):
        identity["source_sha256"][name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    return identity


def _write_evidence(folder, result, schema):
    result["files"] = {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}
    result["files"].update({"result.json": str(folder / "result.json"), "manifest.json": str(folder / "manifest.json")})
    (folder / "result.json").write_text(canonical_json(result) + "\n", encoding="utf-8", newline="\n")
    manifest = {"schema_version": schema, "fingerprint": result["fingerprint"], "simulation_sha256": result["simulation_sha256"],
                "status": result["status"], "file_sha256": {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob("*") if p.is_file() and p != folder / "manifest.json"}}
    (folder / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")


def _run_attempt(site, model, prepared_run, folder, *, _refinement=False):
    report, snapshot = _validate(site, model, prepared_run, _refinement=_refinement)
    result = {**report, "valid": False}
    if not report["valid"]:
        return result
    try:
        identity = prepared_bench_engine_identity()
        if identity["engine_version_int"] != 52004 or identity["toolkit_version"] != "0.17.0":
            raise ValueError("Only the reviewed SWMM 5.2.4 / swmm-toolkit 0.17.0 runtime is supported.")
        inp = dry._input(snapshot)
        fingerprint = {"site_sha256": report["site_package_sha256"], "model_sha256": report["model_sha256"],
                       "run_sha256": report["run_sha256"], "prepared_run_sha256": report["prepared_run_sha256"], "engine": identity,
                       "derived_geometry_sha256": content_sha256({"curves": snapshot["curves"], "effective_links": snapshot["effective_links"]}),
                       "input_sha256": hashlib.sha256(inp.encode("utf-8")).hexdigest()}
        result.update(simulation_sha256=content_sha256(fingerprint), fingerprint=fingerprint, engine=identity, engine_identity=identity)
        folder.mkdir(parents=True, exist_ok=False)
        request = {**snapshot, "fingerprint": fingerprint, "simulation_sha256": result["simulation_sha256"]}
        (folder / "model.inp").write_text(inp, encoding="utf-8", newline="\n")
        (folder / "request.json").write_text(canonical_json(request) + "\n", encoding="utf-8", newline="\n")
    except Exception as exc:
        result.update(status="failed", errors=[{"path": "$", "code": "preparation_failed", "message": f"{type(exc).__name__}: {exc}"}])
        return result
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).with_name("_bench_initialization_worker.py")), str(folder)], cwd=folder,
                              capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        (folder / "worker.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if proc.returncode != 0 or not (folder / "worker-result.json").is_file():
            raise RuntimeError(f"Worker exited {proc.returncode}; inspect the retained worker log.")
        result.update(parse_json((folder / "worker-result.json").read_bytes()))
    except Exception as exc:
        if not (folder / "worker.log").exists():
            (folder / "worker.log").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        result.update(valid=False, status="failed", errors=[{"path": "$", "code": "worker_failed", "message": f"{type(exc).__name__}: {exc}"}])
    result.update(**CLAIMS)
    _write_evidence(folder, result, "monsoon.bench-prepared-attempt-evidence/1")
    return result


def _step_comparison(base, half, site):
    # The frozen v1 comparison covers every whole-history reported stage/flow,
    # actual-routing peak stage, spill and signed outfall volume.
    a = {**base, "timeseries": base.get("full_timeseries", []), "diagnostics": base.get("full_diagnostics", {})}
    b = {**half, "timeseries": half.get("full_timeseries", []), "diagnostics": half.get("full_diagnostics", {})}
    check = dry._step_comparison(a, b, site)
    if not base["valid"] or not half["valid"] or not a["timeseries"] or [r["elapsed_s"] for r in a["timeseries"]] != [r["elapsed_s"] for r in b["timeseries"]]:
        return check

    def metric(name, xs, ys, absolute, offset=0):
        delta = max(abs(x - y) for x, y in zip(xs, ys))
        tolerance = max(absolute, 0.02 * max(abs(x - offset) for x in xs + ys))
        check["metrics"].append({"metric": name, "maximum_absolute_difference": delta, "tolerance": tolerance, "passed": delta <= tolerance})

    for field, absolute in (("node_storage_m3", 1e-6), ("link_storage_m3", 1e-6), ("link_depth_m", 1e-4),
                            ("node_total_inflow_m3_s", 1e-7), ("node_total_outflow_m3_s", 1e-7), ("node_lateral_inflow_m3_s", 1e-7)):
        for ident in a["timeseries"][0][field]:
            metric(field + ":" + ident, [r[field][ident] for r in a["timeseries"]], [r[field][ident] for r in b["timeseries"]], absolute)
    for phase in ("preparation", "evaluation", "whole"):
        pa, pb = base["phase_balances"][phase], half["phase_balances"][phase]
        for field in ("initial_storage_m3", "final_storage_m3", "external_inflow_m3", "receiving_backflow_m3", "discharge_m3", "spill_m3"):
            metric(phase + ":" + field, [pa[field]], [pb[field]], 1e-6)
        for field in ("external_inflow_by_node_m3", "spill_by_node_m3", "discharge_by_outfall_m3", "backflow_by_outfall_m3"):
            for ident in pa[field]:
                metric(phase + ":" + field + ":" + ident, [pa[field][ident]], [pb[field][ident]], 1e-6)
        for node in site["nodes"]:
            metric(phase + ":peak_stage_m:" + node["id"], [pa["maximum_stage_m"][node["id"]]],
                   [pb["maximum_stage_m"][node["id"]]], 1e-4, node["invert_m"])
    # Explicit boundary state checks prevent a large later event from hiding an
    # inadequately resolved small initial wet state under a whole-run relative scale.
    for field, absolute in (("node_storage_m3", 1e-6), ("link_storage_m3", 1e-6), ("link_depth_m", 1e-4),
                            ("link_flow_m3_s", 1e-7), ("node_total_inflow_m3_s", 1e-7), ("node_total_outflow_m3_s", 1e-7),
                            ("node_lateral_inflow_m3_s", 1e-7), ("outflow_m3_s", 1e-7), ("spill_m3_s", 1e-7)):
        for ident, value in base["initial_state"][field].items():
            metric("event_initial:" + field + ":" + ident, [value], [half["initial_state"][field][ident]], absolute)
    for node in site["nodes"]:
        metric("event_initial:stage_m:" + node["id"], [base["initial_state"]["stage_m"][node["id"]]],
               [half["initial_state"]["stage_m"][node["id"]]], 1e-4, node["invert_m"])
    check["passed"] = all(m["passed"] for m in check["metrics"])
    check["status"] = "passed" if check["passed"] else "unresolved"
    return check


def run_prepared_bench(site, model, prepared_run, output_dir):
    """Run a fresh primary/half-step pair without restarting at event time zero."""
    report, snapshot = _validate(site, model, prepared_run)
    if not report["valid"]:
        return report
    folder = None
    try:
        identity = prepared_bench_engine_identity()
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="prepared-bench-pair-", dir=root))
        s, m, p = (snapshot[k] for k in ("site", "model", "prepared_run"))
        fine_model, fine_p = parse_json(m), parse_json(p)
        fine_model["numerics"]["routing_step_s"] /= 2
        fine_p["continuous_run"]["model_sha256"] = content_sha256(fine_model)
        base = _run_attempt(s, m, p, folder / "base")
        half = _run_attempt(s, fine_model, fine_p, folder / "half", _refinement=True)
        check = _step_comparison(base, half, s)
        check.update(primary_routing_step_s=m["numerics"]["routing_step_s"], refined_routing_step_s=fine_model["numerics"]["routing_step_s"],
                     primary_status=base["status"], refined_status=half["status"], refined_model_sha256=content_sha256(fine_model),
                     refined_prepared_run_sha256=content_sha256(fine_p), refined_errors=half["errors"],
                     perturbation="Only routing_step_s is halved; the continuous_run.model_sha256 binding is updated. Same fixed geometry, preparation history and event boundary.")
        if base.get("engine_identity") != identity or half.get("engine_identity") != identity:
            check.update(passed=False, status="unresolved")
            check["errors"].append("Engine/source identity changed during the pair.")
        fingerprint = {"primary": base.get("fingerprint"), "refined": half.get("fingerprint"), "verification": "continuous_preparation_fixed_step_halving/1"}
        result = {**base, "valid": check["passed"], "status": "succeeded" if check["passed"] else "numerically_unresolved",
                  "step_halving": check, "fingerprint": fingerprint, "simulation_sha256": content_sha256(fingerprint), **CLAIMS}
        if not check["passed"]:
            result["errors"] = base["errors"] + [{"path": "$.step_halving", "code": "step_halving_unresolved", "message": "Both complete histories, phase balances, requested stationarity windows, and common-grid comparisons must pass."}]
        _write_evidence(folder, result, "monsoon.bench-prepared-pair-evidence/1")
        return result
    except Exception as exc:
        failed = {**report, "valid": False, "status": "failed", "errors": [{"path": "$", "code": "pair_failed", "message": f"{type(exc).__name__}: {exc}"}]}
        if folder is not None:
            failed["files"] = {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}
            failed["retained_attempt_directory"] = str(folder)
        return failed


def verify_prepared_bench_result(result):
    """Verify local content/engine consistency; external authenticity is not inferred."""
    report = {"valid": False, "status": "invalid_artifact", "errors": [], **CLAIMS}
    try:
        value = parse_json(result)
        files = value.get("files")
        if not isinstance(files, dict) or "result.json" not in files or "manifest.json" not in files:
            raise ValueError("A complete retained artifact map is required.")
        expected = {"result.json", "manifest.json"} | {
            prefix + "/" + name
            for prefix in ("base", "half")
            for name in ("model.inp", "model.rpt", "model.out", "request.json", "worker.log",
                         "worker-result.json", "result.json", "manifest.json")
        }
        if set(files) != expected:
            raise ValueError("Prepared pair must retain exactly all 18 expected native/evidence files.")
        root = Path(files["result.json"]).resolve().parent
        actual = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
        if set(files) != set(actual):
            raise ValueError("Artifact map differs from the complete retained folder inventory.")
        for name, path in files.items():
            relative = PurePosixPath(name)
            if (not isinstance(path, str) or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name or str(relative) != name or
                    Path(path).resolve() != (root / name).resolve() or not (root / name).resolve().is_relative_to(root)):
                raise ValueError("Unsafe or mismatched evidence path: " + name)
        if canonical_json(parse_json((root / "result.json").read_bytes())) != canonical_json(value):
            raise ValueError("Stored result differs from the supplied result.")
        manifest = parse_json((root / "manifest.json").read_bytes())
        if manifest.get("schema_version") != "monsoon.bench-prepared-pair-evidence/1":
            raise ValueError("Expected the prepared-pair manifest schema.")
        checksums = manifest.get("file_sha256")
        if not isinstance(checksums, dict) or set(checksums) != set(actual) - {"manifest.json"}:
            raise ValueError("Manifest does not cover every other retained file exactly once.")
        if any(hashlib.sha256(actual[n].read_bytes()).hexdigest() != digest for n, digest in checksums.items()):
            raise ValueError("A retained artifact checksum changed.")
        for key in ("fingerprint", "simulation_sha256", "status"):
            if manifest.get(key) != value.get(key):
                raise ValueError("Manifest and result disagree: " + key)
        if content_sha256(value["fingerprint"]) != value.get("simulation_sha256"):
            raise ValueError("Pair fingerprint hash mismatch.")
        identity = prepared_bench_engine_identity()
        if value.get("engine_identity") != identity or value.get("engine") != identity:
            raise ValueError("Current source/runtime identity differs from the result.")
        for prefix, key in (("base", "primary"), ("half", "refined")):
            child = parse_json((root / prefix / "result.json").read_bytes())
            if child.get("fingerprint") != value["fingerprint"].get(key) or child.get("engine_identity") != identity:
                raise ValueError("Child identity does not match the prepared pair.")
            if content_sha256(child["fingerprint"]) != child.get("simulation_sha256"):
                raise ValueError("Child fingerprint hash mismatch.")
            request = parse_json((root / prefix / "request.json").read_bytes())
            if content_sha256(request["prepared_run"]) != child["prepared_run_sha256"]:
                raise ValueError("Child preparation contract binding differs from its request.")
        if value.get("valid") is True and value.get("step_halving", {}).get("passed") is not True:
            raise ValueError("Successful result lacks passing step verification.")
        report.update(valid=True, status="local_artifact_integrity_verified")
    except Exception as exc:
        report["errors"] = [{"path": "$.files", "code": "artifact_integrity", "message": f"{type(exc).__name__}: {exc}"}]
    return report
