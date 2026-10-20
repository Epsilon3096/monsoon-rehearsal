"""Real SWMM dynamic-wave runs in private child processes with physical-state caching."""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .case import load_case

MODEL_ADAPTER_VERSION = "1.0.1"


def engine_info() -> dict:
    from swmm.toolkit import solver
    distribution = importlib.metadata.distribution("swmm-toolkit")
    # Version labels alone cannot distinguish locally rebuilt native engines.
    runtime_files = {str(p): hashlib.sha256(Path(distribution.locate_file(p)).read_bytes()).hexdigest()
                     for p in distribution.files or []
                     if str(p).lower().endswith((".dll", ".pyd", ".so", ".dylib", "solver.py", "shared_enum.py"))
                     or ".so." in str(p).lower()}
    return {"engine": "EPA SWMM / Open Water Analytics toolkit", "engine_version": solver.swmm_version_info(),
            "engine_version_int": solver.swmm_get_version(), "toolkit_version": importlib.metadata.version("swmm-toolkit"),
            "adapter_version": MODEL_ADAPTER_VERSION, "routing": "DYNWAVE", "units": "CMS / metres / m3",
            "default_routing_step_s": 0.5,
            "runtime_file_sha256": runtime_files,
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name("_swmm_worker.py").read_bytes()).hexdigest()}


def _hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def hydrograph_points(kind: str, peak: float) -> list[tuple[float, float]]:
    shapes = {"triangle": [(0, 0), (5, 0), (20, 1), (50, 0), (180, 0)],
              "double": [(0, 0), (5, 0), (18, 1), (35, .1), (48, .8), (75, 0), (180, 0)],
              "plateau": [(0, 0), (5, 0), (15, 1), (45, 1), (65, 0), (180, 0)]}
    if kind not in shapes:
        raise ValueError(f"Unsupported hydrograph family: {kind}")
    return [(minute, value * peak) for minute, value in shapes[kind]]


def build_input(completed_jobs, hydraulic: dict, routing_step=0.5, horizon_minutes=180, *, _case=None) -> str:
    case = load_case() if _case is None else _case
    storage_nodes = [n for n in case["nodes"] if n["kind"] == "storage"]
    outfall_nodes = [n for n in case["nodes"] if n["kind"] == "outfall"]
    if len(storage_nodes) != 1 or len(outfall_nodes) != 1:
        raise ValueError("The reference adapter requires one storage and one outfall")
    storage_node, outfall_node = storage_nodes[0], outfall_nodes[0]
    jobs = set(completed_jobs) | set(hydraulic.get("pre_restored_jobs", []))
    if not jobs <= {j["id"] for j in case["jobs"]}:
        raise ValueError("Unknown completed job ID")
    required = {"peak_a_cms", "peak_b_cms", "hydrograph", "tailwater_m", "initial_storage_depth_m", "roughness_multiplier", "restriction_multiplier"}
    if not required <= hydraulic.keys():
        raise ValueError("Missing hydraulic forcing or condition parameters")
    if set(hydraulic) - required - {"pre_restored_jobs"}:
        raise ValueError("Unknown hydraulic parameter; refusing to ignore supplied state")
    numeric = [hydraulic[k] for k in required if k != "hydrograph"] + [routing_step, horizon_minutes]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in numeric):
        raise ValueError("Hydraulic numeric inputs must be finite numbers")
    if min(hydraulic["peak_a_cms"], hydraulic["peak_b_cms"]) < 0:
        raise ValueError("Prescribed hydrograph peaks must be nonnegative")
    if not 0 <= hydraulic["initial_storage_depth_m"] <= storage_node["max_depth_m"]:
        raise ValueError("Initial storage depth is outside represented geometry")
    if not .05 <= routing_step <= 10 or not 180 <= horizon_minutes <= 1440:
        raise ValueError("Supported routing step is 0.05–10 s and horizon 180–1440 min")
    if not .5 <= hydraulic["roughness_multiplier"] <= 2 or not .25 <= hydraulic["restriction_multiplier"] <= 1:
        raise ValueError("Condition multipliers are outside the supported test envelope")
    if not 98 <= hydraulic["tailwater_m"] <= 103:
        raise ValueError("Tailwater is outside the declared reference envelope")
    end_seconds = int(horizon_minutes * 60)
    end_day = "01/02/2026" if end_seconds == 86400 else "01/01/2026"
    end_time = "00:00:00" if end_seconds == 86400 else f"{end_seconds//3600:02d}:{end_seconds%3600//60:02d}:{end_seconds%60:02d}"
    lines = ["[TITLE]", "Monsoon Rehearsal synthetic reference: collector-boundary drainage spill, not property inundation.",
             "[OPTIONS]", "FLOW_UNITS CMS", "FLOW_ROUTING DYNWAVE", "START_DATE 01/01/2026", "START_TIME 00:00:00",
             "REPORT_START_DATE 01/01/2026", "REPORT_START_TIME 00:00:00", f"END_DATE {end_day}", f"END_TIME {end_time}",
             "REPORT_STEP 00:01:00", "WET_STEP 00:01:00", "DRY_STEP 00:01:00", f"ROUTING_STEP {routing_step:.6f}",
             "ALLOW_PONDING NO", "INERTIAL_DAMPING PARTIAL", "NORMAL_FLOW_LIMITED BOTH", "FORCE_MAIN_EQUATION H-W",
             "VARIABLE_STEP 0", "MINIMUM_STEP 0.05", "LENGTHENING_STEP 0", "MIN_SURFAREA 1.167", "MAX_TRIALS 12",
             "HEAD_TOLERANCE 0.0001", "THREADS 1", "[JUNCTIONS]"]
    for n in case["nodes"]:
        if n["kind"] == "junction":
            lines.append(f'{n["id"]} {n["invert_m"]} {n["max_depth_m"]} 0 0 0')
    lines.extend(["[OUTFALLS]", f'{outfall_node["id"]} {outfall_node["invert_m"]} FIXED {hydraulic["tailwater_m"]} NO', "[STORAGE]",
                  f'{storage_node["id"]} {storage_node["invert_m"]} {storage_node["max_depth_m"]} {hydraulic["initial_storage_depth_m"]} FUNCTIONAL 0 0 {case["storage_area_m2"]} 0 0', "[CONDUITS]"])
    for l in case["links"]:
        lines.append(f'{l["id"]} {l["from_node"]} {l["to_node"]} {l["length_m"]} {l["roughness_n"]*hydraulic["roughness_multiplier"]:.6f} 0 0 0 0')
    lines.append("[XSECTIONS]")
    for l in case["links"]:
        width = l["restored_width_m"] if l["job_id"] in jobs or not l["job_id"] else l["blocked_width_m"] * hydraulic["restriction_multiplier"]
        lines.append(f'{l["id"]} {l["shape"]} {l["depth_m"]} {width:.6f} 0 0 1')
    lines.extend(["[INFLOWS]", "A1 FLOW A_FLOW FLOW 1.0 1.0", "B1 FLOW B_FLOW FLOW 1.0 1.0", "[TIMESERIES]"])
    for name, peak in [("A_FLOW", hydraulic["peak_a_cms"]), ("B_FLOW", hydraulic["peak_b_cms"])]:
        for minute, value in hydrograph_points(hydraulic["hydrograph"], peak):
            lines.append(f"{name} {int(minute)//60:02d}:{int(minute)%60:02d} {value:.9f}")
    lines.extend(["[REPORT]", "INPUT NO", "CONTINUITY YES", "FLOWSTATS YES", "NODES ALL", "LINKS ALL", "[COORDINATES]"])
    for n in case["nodes"]:
        lines.append(f'{n["id"]} {n["x"]*100} {n["y"]*100}')
    return "\n".join(lines) + "\n"


def _publish_cache_index(cached: Path, serial: str) -> bool:
    """Publish a derived hint without making a sealed run depend on Windows locks.

    Readers still verify the private attempt and its evidence. Another reader or
    publisher can briefly prevent replacement on Windows, so allow five tries
    with at most 150 ms of backoff. Other I/O errors remain errors.
    """
    temp = cached.with_name(f"result-{os.getpid()}-{time.time_ns()}.tmp")
    try:
        temp.write_text(serial, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temp, cached)
                return True
            except OSError as exc:
                if getattr(exc, "winerror", None) not in (32, 33):
                    raise
                if attempt < 4:
                    time.sleep(.01 * 2**attempt)
        return False
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError as exc:
            # An externally locked temporary file is ignored by cache readers.
            # Never delete the shared target or change the immutable evidence.
            if getattr(exc, "winerror", None) not in (32, 33):
                raise


def run_state(completed_jobs, scenario, cache_dir, routing_step=0.5, horizon_minutes=180, force=False) -> dict:
    completed = sorted(set(completed_jobs))
    scenario_id = scenario.get("id", "unnamed")
    try:
        case = load_case()
        inp = build_input(completed, scenario["hydraulic"], routing_step, horizon_minutes, _case=case)
        info = engine_info()
    except Exception as exc:
        return {"run_id": None, "status": "invalid", "valid": False, "completed_jobs": completed, "scenario_id": scenario_id,
                "engine_version": None, "total_spill_m3": None, "nodes": {}, "diagnostics": {}, "files": {},
                "timeseries": [], "cache_hit": False, "errors": [str(exc)]}
    request = {"input_sha256": hashlib.sha256(inp.encode()).hexdigest(), "engine": info,
               # Derived thresholds, node definitions and interpretation are part of
               # the cached result even when they leave the SWMM input unchanged.
               "case_snapshot_sha256": _hash(case),
               "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name("_swmm_worker.py").read_bytes()).hexdigest()}
    run_id = _hash(request)
    base = Path(cache_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    final = base / run_id
    cached = final / "result.json"
    if cached.exists() and not force:
        try:
            result = json.loads(cached.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or not isinstance(result.get("files"), dict):
                raise ValueError("Malformed cache result")
            names = {"input": "model.inp", "report": "model.rpt", "output": "model.out",
                     "manifest": "manifest.json", "result": "result.json", "log": "worker.log"}
            if any(not isinstance(result["files"].get(key), str) for key in names):
                raise ValueError("Malformed cache file paths")
            attempt = Path(result["files"]["manifest"]).resolve().parent
            files_ok = (attempt.parent == base and
                        all(Path(result["files"][key]).resolve() == attempt/name and (attempt/name).is_file()
                            for key, name in names.items()))
            manifest = json.loads((attempt/"manifest.json").read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("file_sha256"), dict):
                raise ValueError("Malformed cache manifest")
            checksums = manifest["file_sha256"]
            required_raw = {"model.inp", "model.rpt", "model.out", "request.json", "worker.log"}
            if not required_raw <= checksums.keys() or any(Path(name).name != name for name in checksums):
                raise ValueError("Incomplete cache evidence hashes")
            hash_ok = hashlib.sha256(Path(result["files"]["input"]).read_bytes()).hexdigest() == request["input_sha256"]
            raw_ok = all(hashlib.sha256((attempt/name).read_bytes()).hexdigest() == checksum
                         for name,checksum in checksums.items())
            saved_result = json.loads((attempt/"result.json").read_text(encoding="utf-8"))
            result_ok = _hash(result) == _hash(saved_result) == manifest.get("result_sha256")
            if (files_ok and hash_ok and raw_ok and result_ok and result.get("run_id") == run_id
                    and manifest.get("request_fingerprint") == request):
                result.update(cache_hit=True, scenario_id=scenario_id, completed_jobs=completed)
                return result
        except (OSError, ValueError, KeyError, TypeError):
            pass
    folder = Path(tempfile.mkdtemp(prefix=f"{run_id[:12]}-", dir=base))
    (folder / "model.inp").write_text(inp, encoding="utf-8", newline="\n")
    worker_request = {"run_id": run_id, "completed_jobs": completed, "scenario_id": scenario_id, "engine": info,
                      "routing_step": routing_step, "horizon_minutes": horizon_minutes, "hydraulic": scenario["hydraulic"],
                      "case": case, "request_fingerprint": request}
    (folder / "request.json").write_text(json.dumps(worker_request, indent=2), encoding="utf-8")
    started = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).with_name("_swmm_worker.py")), str(folder)],
                              cwd=folder, capture_output=True, text=True, timeout=120,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        (folder / "worker.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if not (folder / "result.json").exists():
            raise RuntimeError(f"SWMM worker exited {proc.returncode}: {proc.stderr[-1200:]}")
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    except Exception as exc:
        result = {"run_id": run_id, "status": "failed", "valid": False, "engine_version": info["engine_version"],
                  "total_spill_m3": None, "nodes": {}, "diagnostics": {}, "timeseries": [], "errors": [str(exc)]}
    result.update(completed_jobs=completed, scenario_id=scenario_id, cache_hit=False, elapsed_seconds=time.perf_counter()-started)
    # Private immutable attempt folders preserve logs on retries; the hash index is only a small result pointer.
    result["files"] = {"input": str(folder/"model.inp"), "report": str(folder/"model.rpt"), "output": str(folder/"model.out"),
                       "manifest": str(folder/"manifest.json"), "result": str(folder/"result.json"), "log": str(folder/"worker.log")}
    manifest = {**worker_request, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "status": result["status"], "files": result["files"], "result_sha256": _hash(result),
                "file_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file() and p.name != "result.json"}}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    serial = json.dumps(result, indent=2, allow_nan=False)
    (folder / "result.json").write_text(serial, encoding="utf-8")
    final.mkdir(exist_ok=True)
    _publish_cache_index(cached, serial)
    return copy.deepcopy(result)


def verify_hydraulics(cache_dir, *, all_states=True, workers=4, routing_step=0.5) -> dict:
    """Exhaustive synthetic QA, including step-halving without looking at plan rankings."""
    from concurrent.futures import ThreadPoolExecutor
    from itertools import combinations, product
    case = load_case()
    ids = [j["id"] for j in case["jobs"]]
    states = [list(s) for n in range(len(ids)+1) for s in combinations(ids,n)] if all_states else [[],ids]
    tasks = list(product(case["scenarios"],states))
    def check(item):
        scenario, state = item
        a = run_state(state,scenario,cache_dir,routing_step=routing_step)
        b = run_state(state,scenario,cache_dir,routing_step=routing_step/2)
        errors = [f"{step}: {message}" for step,r in [(routing_step,a),(routing_step/2,b)] for message in r["errors"]]
        deltas={}
        node_spills = {}
        if a["valid"] and b["valid"]:
            for nid in case["protected_nodes"]:
                av,bv=a["nodes"][nid]["spill_m3"],b["nodes"][nid]["spill_m3"]
                delta=abs(av-bv)
                tolerance=max(.05,.02*max(abs(av),abs(bv)))
                depth_delta = abs(a["nodes"][nid]["max_depth_m"]-b["nodes"][nid]["max_depth_m"])
                duration_delta = abs(a["nodes"][nid]["duration_above_threshold_min"]-b["nodes"][nid]["duration_above_threshold_min"])
                deltas[nid]={"absolute_m3":delta,"tolerance_m3":tolerance,
                             "peak_depth_delta_m":depth_delta,"threshold_duration_delta_min":duration_delta}
                node_spills[nid] = {"default": av, "half_step": bv}
                if delta>tolerance:
                    errors.append(f"{nid} spill changes {delta:.6g} m3 under step halving; tolerance {tolerance:.6g} m3")
            delta=abs(a["total_spill_m3"]-b["total_spill_m3"])
            if delta>max(.05,.02*max(a["total_spill_m3"],b["total_spill_m3"])):
                errors.append("Total spill fails step-halving tolerance")
        return {"scenario_id":scenario["id"],"phase":scenario["phase"],"completed_jobs":state,
                "valid":a["valid"] and b["valid"] and not errors,"errors":errors,"run_id":a["run_id"],"half_step_run_id":b["run_id"],
                "spill_m3":a["total_spill_m3"],"half_step_spill_m3":b["total_spill_m3"],
                "continuity_error_percent":a["diagnostics"].get("continuity_error_percent"),
                "half_step_continuity_error_percent":b["diagnostics"].get("continuity_error_percent"),
                "per_node_step_delta":deltas,"per_node_spill_m3":node_spills}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows=list(pool.map(check,tasks))
    # A relative spill tolerance alone need not preserve the much narrower
    # per-location no-worsening test used by the planner.
    references = {r["scenario_id"]: r for r in rows if not r["completed_jobs"]}
    for row in rows:
        reference = references[row["scenario_id"]]
        if row["valid"] and reference["valid"]:
            admissible = {step: all(row["per_node_spill_m3"][nid][step] <=
                                  reference["per_node_spill_m3"][nid][step]+case["epsilon_m3"]
                                  for nid in case["protected_nodes"])
                          for step in ("default", "half_step")}
            row["no_worsening_by_step"] = admissible
            if admissible["default"] != admissible["half_step"]:
                row["errors"].append("Protected-location no-worsening decision changes under step halving")
                row["valid"] = False
    return {"status":"passed" if all(r["valid"] for r in rows) else "failed", "engine":engine_info(),
            "case_sha256":case["case_sha256"], "state_scenario_pairs":len(rows),"engine_runs":2*len(rows),
            "routing_step_s":routing_step,"halved_routing_step_s":routing_step/2,
            "spill_step_halving_relative_tolerance":.02,"spill_step_halving_absolute_tolerance_m3":.05,
            "no_worsening_tolerance_m3":case["epsilon_m3"],
            "rows":rows,"failures":[r for r in rows if not r["valid"]]}


def verify_hydraulic_horizon(cache_dir, *, all_states=True, workers=4, routing_step=0.5,
                            extended_horizon_minutes=360) -> dict:
    """Check recession adequacy, retaining horizon-sensitive boundary controls."""
    from concurrent.futures import ThreadPoolExecutor
    from itertools import combinations, product
    if not 180 < extended_horizon_minutes <= 1440:
        raise ValueError("Extended horizon must exceed 180 and be at most 1440 minutes")
    case = load_case()
    ids = [j["id"] for j in case["jobs"]]
    states = [list(s) for n in range(len(ids)+1) for s in combinations(ids,n)] if all_states else [[],ids]

    def check(item):
        scenario, state = item
        short = run_state(state, scenario, cache_dir, routing_step=routing_step)
        long = run_state(state, scenario, cache_dir, routing_step=routing_step,
                         horizon_minutes=extended_horizon_minutes)
        errors = [f"{horizon} minutes: {message}"
                  for horizon, run in [(180,short),(extended_horizon_minutes,long)] for message in run["errors"]]
        valid = short["valid"] and long["valid"]
        deltas = ({nid: long["nodes"][nid]["spill_m3"]-short["nodes"][nid]["spill_m3"]
                   for nid in case["protected_nodes"]} if valid else {})
        stable = valid and all(abs(delta) <= .05 for delta in deltas.values())
        required = scenario["phase"] in ("planning", "holdout")
        if required and valid and not stable:
            errors.append("Planning/holdout event spill is not complete by 180 minutes")
        return {"scenario_id":scenario["id"], "phase":scenario["phase"], "completed_jobs":state,
                "valid":valid and not errors, "errors":errors,
                "horizon_stable":stable, "required_for_event_adequacy":required,
                "run_id":short["run_id"], "extended_run_id":long["run_id"],
                "spill_m3":short["total_spill_m3"], "extended_spill_m3":long["total_spill_m3"],
                "per_node_additional_spill_m3":deltas,
                "final_storage_m3":short["diagnostics"].get("final_storage_m3"),
                "extended_final_storage_m3":long["diagnostics"].get("final_storage_m3"),
                "note":("Diagnostic boundary control remains horizon-sensitive; use only its explicitly timed spill, "
                         "not a complete-event loss." if valid and not stable and not required else None)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(check, product(case["scenarios"],states)))
    return {"status":"passed" if all(r["valid"] for r in rows) else "failed",
            "scope":"Event spill adequacy for planning and holdout cases; boundary diagnostics are reported separately.",
            "engine":engine_info(), "case_sha256":case["case_sha256"],
            "routing_step_s":routing_step, "horizon_minutes":180,
            "extended_horizon_minutes":extended_horizon_minutes,
            "absolute_spill_tolerance_m3":.05, "state_scenario_pairs":len(rows), "engine_runs":2*len(rows),
            "rows":rows, "failures":[r for r in rows if not r["valid"]],
            "horizon_sensitive_diagnostics":[r for r in rows if not r["required_for_event_adequacy"] and not r["horizon_stable"]]}
