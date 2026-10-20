"""Bounded, isolated bench research models; never activates the reference case.

The supplied files describe a model, not verified geometry or permission. Every
run is a fresh fixed-geometry, nominally dry simulation in a private process.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

from .site_data import _Checks, canonical_json, content_sha256, parse_json, validate_site_package

MODEL_SCHEMA = "monsoon.bench-model/1"
RUN_SCHEMA = "monsoon.bench-run/1"
ADAPTER_VERSION = "1.0.0"
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
LIMITATIONS = [
    "Research simulation only: supplied survey, source references and approval claims are not independently verified.",
    "Only fixed geometry with a nominally dry, zero-flow start is supported; wet resets, hotstarts and measured equilibration are unsupported.",
    "All internal nodes are explicit free-surface storage compartments. All conduit and node water is included in total storage.",
    "Node spill leaves to declared absorbing collectors; lateral open-channel overtopping, surface transfer and re-entry are unsupported.",
    "Zero evaporation, seepage and leakage are explicit model assumptions, not measured findings.",
    "A numerically acceptable synthetic run does not establish physical validation or operational authority.",
]
CLAIMS = {"operational_activation_allowed": False, "physical_validation_established": False,
          "engineering_approval_established": False}


def _report():
    return {"schema_version": MODEL_SCHEMA, "valid": False, "status": "invalid_contract",
            "site_package_sha256": None, "model_sha256": None, "run_sha256": None,
            "errors": [], "warnings": [], "limitations": list(LIMITATIONS), **CLAIMS}


def _number(c, value, path, lo, hi, integer=False):
    if not c.number(value, path):
        return False
    if not lo <= value <= hi or (integer and value != int(value)):
        c.error(path, "outside_bench_envelope", f"Expected {'integer ' if integer else ''}number in [{lo}, {hi}].")
        return False
    return True


def _rows(c, value, path, key, expected):
    result = {}
    for i, row in enumerate(c.array(value, path)):
        p = f"{path}[{i}]"
        if not isinstance(row, dict):
            c.error(p, "object_required", "Expected a record.")
            continue
        ident = row.get(key)
        if not isinstance(ident, str) or ident not in expected:
            c.error(p + "." + key, "unknown_asset", "Reference an exact matching site asset.")
        elif ident in result:
            c.error(p + "." + key, "duplicate_id", "Asset occurs more than once.")
        else:
            result[ident] = row
    if set(result) != set(expected):
        c.error(path, "incomplete_inventory", "Records must cover exactly: " + ", ".join(sorted(expected)))
    return result


def _validate(site, model, run=None, *, _refinement=False):
    report, c = _report(), _Checks()
    try:
        s, m = parse_json(site), parse_json(model)
        r = parse_json(run) if run is not None else None
        report.update(site_package_sha256=content_sha256(s), model_sha256=content_sha256(m),
                      run_sha256=content_sha256(r) if r is not None else None)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        c.error("$", "invalid_json", str(exc))
        report["errors"] = c.errors
        return report, None
    sr = validate_site_package(s)
    if not sr["valid"]:
        report["errors"] = [{"path": "$.site", "code": "invalid_site", "message": "Matching site-v1 must validate before model adaptation."}] + sr["errors"]
        return report, None
    nodes, links = {n["id"]: n for n in s["nodes"]}, {l["id"]: l for l in s["links"]}
    internal = {k for k, v in nodes.items() if v["kind"] != "outfall"}
    junctions = {k for k, v in nodes.items() if v["kind"] == "junction"}
    outfalls = set(nodes) - internal
    sources = {v["id"]: v for v in s["sources"]}
    if len(nodes) > 20 or len(links) > 30:
        c.error("$.site", "size_limit", "This bounded adapter permits at most 20 nodes and 30 links.")
    for label, ids in (("nodes", nodes), ("links", links)):
        if len({k.casefold() for k in ids}) != len(ids):
            c.error("$.site." + label, "case_ambiguous_id", "SWMM identifiers must also be unique ignoring case.")
    if set(s["boundaries"]["spill_node_ids"]) != internal:
        c.error("$.site.boundaries.spill_node_ids", "incomplete_spill_inventory", "Every internal node requires an explicitly surveyed spill boundary in this adapter.")
    if not set(s["boundaries"]["inflow_node_ids"]) <= internal:
        c.error("$.site.boundaries.inflow_node_ids", "outfall_inflow", "External inflows must enter internal compartments.")
    for oid in outfalls:
        _number(c, nodes[oid]["invert_m"], "$.site.nodes." + oid + ".invert_m", -10000, 10000)
        _number(c, nodes[oid]["ground_m"] - nodes[oid]["invert_m"], "$.site.nodes." + oid + ".depth_m", 0.001, 5)
        incident = [l for l in links.values() if oid in (l["from_node"], l["to_node"])]
        if len(incident) != 1 or incident[0]["to_node"] != oid:
            c.error("$.site.nodes." + oid, "terminal_outfall_required", "Each outfall must terminate exactly one incoming conduit and have no outgoing link.")
    c.obj(m, "$.model", {"schema_version", "model_id", "site_package_sha256", "evidence_kind", "completed_job_ids", "junction_storage", "link_parameters", "overflow", "losses", "numerics", "notes"})
    c.choice(m.get("schema_version"), {MODEL_SCHEMA}, "$.model.schema_version")
    c.ident(m.get("model_id"), "$.model.model_id")
    c.text(m.get("notes"), "$.model.notes")
    expected_kind = "synthetic_fixture" if s["evidence_kind"] == "synthetic_fixture" else "supplied_bench_model"
    c.choice(m.get("evidence_kind"), {expected_kind}, "$.model.evidence_kind")
    if m.get("site_package_sha256") != report["site_package_sha256"]:
        c.error("$.model.site_package_sha256", "site_hash_mismatch", "Bind the exact canonical site package hash.")

    def source(value, path):
        if not isinstance(value, str) or value not in sources:
            c.error(path, "source_required", "Reference a supplied site source; no evidence is inferred.")

    completed = c.array(m.get("completed_job_ids"), "$.model.completed_job_ids")
    jobs = {j["id"]: j for j in s["jobs"]}
    selected = {j for j in completed if isinstance(j, str) and j in jobs}
    if len(selected) != len(completed):
        c.error("$.model.completed_job_ids", "invalid_jobs", "Completed jobs must be distinct known IDs.")
    for j in selected:
        if not set(jobs[j]["prerequisites"]) <= selected:
            c.error("$.model.completed_job_ids", "missing_prerequisite", "A completed job is missing a prerequisite.")
    effective_links = parse_json({"links": list(links.values())})["links"]
    for link in effective_links:
        for j in selected:
            if jobs[j]["asset_id"] == link["id"]:
                link["cross_section"] = jobs[j]["after_cross_section"]
    supplemental = _rows(c, m.get("junction_storage"), "$.model.junction_storage", "node_id", junctions)
    curves = {}
    for nid in sorted(internal):
        n = nodes[nid]
        _number(c, n["invert_m"], f"$.site.nodes.{nid}.invert_m", -10000, 10000)
        _number(c, n["ground_m"] - n["invert_m"], f"$.site.nodes.{nid}.depth_m", 0.001, 5)
        if nid in junctions:
            record = supplemental.get(nid, {})
            c.obj(record, "$.model.junction_storage." + nid, {"node_id", "stage_area", "source_id"})
            source(record.get("source_id"), "$.model.junction_storage." + nid + ".source_id")
            curve = c.array(record.get("stage_area"), "$.model.junction_storage." + nid + ".stage_area", 2)
        else:
            curve = n["storage_stage_area"]
        if len(curve) > 100:
            c.error("$.model.junction_storage", "curve_limit", "At most 100 storage curve points per node.")
        prev = None
        good_curve = []
        for i, point in enumerate(curve):
            p = f"$.storage_geometry.{nid}[{i}]"
            point = c.obj(point, p, {"stage_m", "area_m2"})
            valid = _number(c, point.get("stage_m"), p + ".stage_m", n["invert_m"], n["ground_m"])
            area_ok = _number(c, point.get("area_m2"), p + ".area_m2", 1e-8, 100)
            if valid:
                if prev is not None and point["stage_m"] <= prev:
                    c.error(p, "curve_order", "Storage stage must increase strictly.")
                prev = point["stage_m"]
                if area_ok:
                    good_curve.append(point)
        if not good_curve or good_curve[0]["stage_m"] != n["invert_m"] or good_curve[-1]["stage_m"] != n["ground_m"]:
            c.error("$.storage_geometry." + nid, "curve_extent", "Curve must span exactly invert through overflow elevation; no extrapolation.")
        curves[nid] = good_curve
    params = _rows(c, m.get("link_parameters"), "$.model.link_parameters", "link_id", links)
    for lid, p in params.items():
        path = "$.model.link_parameters." + lid
        c.obj(p, path, {"link_id", "roughness_n", "entrance_loss_coefficient", "exit_loss_coefficient", "average_loss_coefficient", "source_id"})
        _number(c, p.get("roughness_n"), path + ".roughness_n", 0.005, 0.2)
        for field in ("entrance_loss_coefficient", "exit_loss_coefficient", "average_loss_coefficient"):
            _number(c, p.get(field), path + "." + field, 0, 100)
        source(p.get("source_id"), path + ".source_id")
    for link in effective_links:
        p = "$.site.links." + link["id"]
        _number(c, link["length_m"], p + ".length_m", 0.01, 100)
        for key, value in link["cross_section"].items():
            if key != "shape":
                _number(c, value, p + ".cross_section." + key, 0 if "slope" in key else 0.0001, 10 if "slope" in key else 5)
        for field in ("inlet_invert_m", "outlet_invert_m"):
            _number(c, link[field], p + "." + field, -10000, 10000)
    spill = _rows(c, m.get("overflow"), "$.model.overflow", "node_id", internal)
    for nid, row in spill.items():
        c.obj(row, "$.model.overflow." + nid, {"node_id", "destination", "source_id"})
        c.choice(row.get("destination"), {"external_absorbing_collector"}, "$.model.overflow." + nid + ".destination")
        source(row.get("source_id"), "$.model.overflow." + nid + ".source_id")
    losses = c.obj(m.get("losses"), "$.model.losses", {"evaporation", "seepage", "leakage", "source_id"})
    for name in ("evaporation", "seepage", "leakage"):
        c.choice(losses.get(name), {"excluded_zero"}, "$.model.losses." + name)
    source(losses.get("source_id"), "$.model.losses.source_id")
    num = c.obj(m.get("numerics"), "$.model.numerics", {"routing_step_s", "report_step_s", "head_tolerance_m", "minimum_surface_area_m2", "initial_numerical_storage_tolerance_m3", "max_trials", "inertial_damping", "normal_flow_limited"})
    step_ok = _number(c, num.get("routing_step_s"), "$.model.numerics.routing_step_s", 0.005 if _refinement else 0.01, 1)
    report_ok = _number(c, num.get("report_step_s"), "$.model.numerics.report_step_s", 1, 60, True)
    _number(c, num.get("head_tolerance_m"), "$.model.numerics.head_tolerance_m", 1e-8, 0.001)
    area_ok = _number(c, num.get("minimum_surface_area_m2"), "$.model.numerics.minimum_surface_area_m2", 1e-8, 1)
    _number(c, num.get("initial_numerical_storage_tolerance_m3"), "$.model.numerics.initial_numerical_storage_tolerance_m3", 1e-9, 1e-4)
    _number(c, num.get("max_trials"), "$.model.numerics.max_trials", 4, 100, True)
    c.choice(num.get("inertial_damping"), {"NONE"}, "$.model.numerics.inertial_damping")
    c.choice(num.get("normal_flow_limited"), {"BOTH"}, "$.model.numerics.normal_flow_limited")
    if step_ok and report_ok and not math.isclose(num["report_step_s"] / num["routing_step_s"], round(num["report_step_s"] / num["routing_step_s"]), abs_tol=1e-8):
        c.error("$.model.numerics", "unaligned_steps", "Reporting interval must be an exact multiple of the fixed routing step.")
    all_areas = [p["area_m2"] for curve in curves.values() for p in curve]
    if area_ok and all_areas and num["minimum_surface_area_m2"] > min(all_areas):
        c.error("$.model.numerics.minimum_surface_area_m2", "oversized_numerical_area", "Numerical minimum area cannot exceed the smallest supplied compartment area.")
    if r is not None:
        c.obj(r, "$.run", {"schema_version", "run_id", "model_sha256", "duration_s", "initial_conditions", "inflows", "receiving_stages", "notes"})
        c.choice(r.get("schema_version"), {RUN_SCHEMA}, "$.run.schema_version")
        c.ident(r.get("run_id"), "$.run.run_id")
        c.text(r.get("notes"), "$.run.notes")
        if r.get("model_sha256") != report["model_sha256"]:
            c.error("$.run.model_sha256", "model_hash_mismatch", "Bind the exact canonical model hash.")
        duration_ok = _number(c, r.get("duration_s"), "$.run.duration_s", 1, 3600, True)
        if duration_ok and step_ok and r["duration_s"] / num["routing_step_s"] > (100000 if _refinement else 50000):
            c.error("$.run.duration_s", "routing_budget", "At most 50000 primary steps and 100000 automatic half-step verification steps.")
        if duration_ok and report_ok and (r["duration_s"] % num["report_step_s"] or r["duration_s"] / num["report_step_s"] + 1 > 10000):
            c.error("$.run.duration_s", "report_grid", "Horizon must end on the reporting grid with at most 10000 samples.")
        if duration_ok and report_ok and (r["duration_s"] / num["report_step_s"] + 1) * (len(nodes) + len(links)) > 30000:
            c.error("$.run.duration_s", "output_budget", "At most 30000 combined node/link reporting records per bounded pair output.")
        initial = c.obj(r.get("initial_conditions"), "$.run.initial_conditions", {"kind", "source_id"})
        c.choice(initial.get("kind"), {"dry_zero_flow"}, "$.run.initial_conditions.kind")
        source(initial.get("source_id"), "$.run.initial_conditions.source_id")
        for collection, expected, field in (("inflows", set(s["boundaries"]["inflow_node_ids"]), "value_m3_s"), ("receiving_stages", outfalls, "stage_m")):
            rows = _rows(c, r.get(collection), "$.run." + collection, "node_id", expected)
            for nid, row in rows.items():
                p = "$.run." + collection + "." + nid
                c.obj(row, p, {"node_id", "points"})
                points = c.array(row.get("points"), p + ".points", 2)
                if len(points) > 1000:
                    c.error(p, "series_limit", "At most 1000 prescribed boundary points.")
                previous, valid_points = None, []
                for i, point in enumerate(points):
                    q = f"{p}.points[{i}]"
                    point = c.obj(point, q, {"elapsed_s", field})
                    time_ok = _number(c, point.get("elapsed_s"), q + ".elapsed_s", 0, 3600, True)
                    value_ok = _number(c, point.get(field), q + "." + field, 0 if collection == "inflows" else nodes[nid]["invert_m"] - 5, 0.1 if collection == "inflows" else nodes[nid]["ground_m"])
                    if time_ok:
                        if previous is not None and point["elapsed_s"] <= previous:
                            c.error(q, "time_order", "Boundary times must increase strictly.")
                        previous = point["elapsed_s"]
                    if time_ok and value_ok:
                        valid_points.append(point)
                if not valid_points or valid_points[0]["elapsed_s"] != 0 or not duration_ok or valid_points[-1]["elapsed_s"] != r["duration_s"]:
                    c.error(p, "boundary_coverage", "Series must span exactly zero through the run horizon; no filling or extrapolation.")
                if valid_points and ((collection == "inflows" and valid_points[0][field] != 0) or (collection == "receiving_stages" and valid_points[0][field] > nodes[nid]["invert_m"])):
                    c.error(p, "wet_initial_boundary", "Dry start requires zero initial inflow and receiving stage at or below outfall invert.")
    report.update(valid=not c.errors, status="research_contract_valid" if not c.errors else "invalid_contract", errors=c.errors, warnings=c.warnings,
                  evidence_kind=expected_kind, counts={"nodes": len(nodes), "links": len(links), "storage_compartments": len(internal)})
    return report, {"site": s, "model": m, "run": r, "curves": curves, "effective_links": effective_links} if not c.errors else None


def validate_bench_model(site, model):
    return _validate(site, model)[0]


def validate_bench_run(site, model, run):
    return _validate(site, model, run)[0]


def _clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _input(snapshot):
    s, m, r = (snapshot[k] for k in ("site", "model", "run"))
    num = m["numerics"]
    lines = ["[TITLE]", "Monsoon isolated bench research model; supplied data are unverified.", "[OPTIONS]",
             "FLOW_UNITS CMS", "FLOW_ROUTING DYNWAVE", "START_DATE 01/01/2000", "START_TIME 00:00:00",
             "REPORT_START_DATE 01/01/2000", "REPORT_START_TIME 00:00:00", "END_DATE 01/01/2000", f"END_TIME {_clock(r['duration_s'])}",
             f"REPORT_STEP {_clock(num['report_step_s'])}", "WET_STEP 00:00:01", "DRY_STEP 00:00:01", f"ROUTING_STEP {num['routing_step_s']:.12g}",
             "VARIABLE_STEP 0", "MINIMUM_STEP 0.001", "LENGTHENING_STEP 0", "ALLOW_PONDING NO", "SKIP_STEADY_STATE NO",
             "INERTIAL_DAMPING NONE", "NORMAL_FLOW_LIMITED BOTH", "SURCHARGE_METHOD EXTRAN", "THREADS 1",
             f"MIN_SURFAREA {num['minimum_surface_area_m2']:.12g}", f"HEAD_TOLERANCE {num['head_tolerance_m']:.12g}", f"MAX_TRIALS {int(num['max_trials'])}",
             "[EVAPORATION]", "CONSTANT 0", "[STORAGE]"]
    nodes = {n["id"]: n for n in s["nodes"]}
    curve_ids = {nid: f"BC{i}" for i, nid in enumerate(sorted(snapshot["curves"]))}
    for nid, curve_id in curve_ids.items():
        n = nodes[nid]
        lines.append(f"{nid} {n['invert_m']:.12g} {n['ground_m']-n['invert_m']:.12g} 0 TABULAR {curve_id} 0 0")
    lines.append("[OUTFALLS]")
    for i, row in enumerate(r["receiving_stages"]):
        n = nodes[row["node_id"]]
        lines.append(f"{n['id']} {n['invert_m']:.12g} TIMESERIES BS{i} NO")
    lines.append("[CONDUITS]")
    params = {p["link_id"]: p for p in m["link_parameters"]}
    for link in snapshot["effective_links"]:
        a, b = nodes[link["from_node"]], nodes[link["to_node"]]
        lines.append(f"{link['id']} {a['id']} {b['id']} {link['length_m']:.12g} {params[link['id']]['roughness_n']:.12g} {link['inlet_invert_m']-a['invert_m']:.12g} {link['outlet_invert_m']-b['invert_m']:.12g} 0 0")
    lines.append("[XSECTIONS]")
    for link in snapshot["effective_links"]:
        x = link["cross_section"]
        if x["shape"] == "open_rectangle":
            shape, dims = "RECT_OPEN", [x["height_m"], x["width_m"], 0, 0]
        elif x["shape"] == "circular":
            shape, dims = "CIRCULAR", [x["diameter_m"], 0, 0, 0]
        else:
            shape, dims = "TRAPEZOIDAL", [x["height_m"], x["bottom_width_m"], x["left_slope_h_per_v"], x["right_slope_h_per_v"]]
        lines.append(f"{link['id']} {shape} " + " ".join(f"{v:.12g}" for v in dims) + " 1")
    lines.append("[LOSSES]")
    for lid, p in params.items():
        lines.append(f"{lid} {p['entrance_loss_coefficient']:.12g} {p['exit_loss_coefficient']:.12g} {p['average_loss_coefficient']:.12g} NO 0")
    lines.append("[CURVES]")
    for nid, curve in snapshot["curves"].items():
        for i, point in enumerate(curve):
            kind = " STORAGE" if i == 0 else ""
            lines.append(f"{curve_ids[nid]}{kind} {point['stage_m']-nodes[nid]['invert_m']:.12g} {point['area_m2']:.12g}")
    lines.append("[INFLOWS]")
    for i, row in enumerate(r["inflows"]):
        lines.append(f"{row['node_id']} FLOW BI{i} FLOW 1 1 0")
    lines.append("[TIMESERIES]")
    for collection, prefix, key in ((r["inflows"], "BI", "value_m3_s"), (r["receiving_stages"], "BS", "stage_m")):
        for i, row in enumerate(collection):
            for point in row["points"]:
                lines.append(f"{prefix}{i} {_clock(point['elapsed_s'])} {point[key]:.12g}")
    lines.extend(["[REPORT]", "INPUT YES", "CONTINUITY YES", "FLOWSTATS YES", "NODES ALL", "LINKS ALL"])
    return "\n".join(lines) + "\n"


def build_bench_input(site, model, run):
    report, snapshot = _validate(site, model, run)
    if not report["valid"]:
        raise ValueError(canonical_json(report["errors"]))
    return _input(snapshot)


def bench_engine_identity():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
        raise ValueError("Bench adapter source changed after import; restart the process before execution/freeze.")
    from swmm.toolkit import solver
    dist = importlib.metadata.distribution("swmm-toolkit")
    binaries = {str(p): hashlib.sha256(Path(dist.locate_file(p)).read_bytes()).hexdigest()
                for p in dist.files or [] if str(p).lower().endswith((".dll", ".pyd", ".so", ".dylib", "solver.py", "shared_enum.py")) or ".so." in str(p).lower()}
    parent = Path(__file__).resolve().parent
    sources = {name: hashlib.sha256((parent / name).read_bytes()).hexdigest() for name in ("bench_model.py", "_bench_worker.py", "site_data.py")}
    return {"adapter_version": ADAPTER_VERSION, "engine_version": solver.swmm_version_info(), "engine_version_int": solver.swmm_get_version(),
            "toolkit_version": importlib.metadata.version("swmm-toolkit"), "runtime_file_sha256": binaries, "source_sha256": sources,
            "routing": "DYNWAVE", "units": "CMS / m / m3"}


def _run_attempt(site, model, run, output_dir, *, _refinement=False):
    report, snapshot = _validate(site, model, run, _refinement=_refinement)
    result = {**report, "valid": False, "status": "invalid_contract", "timeseries": [], "diagnostics": {}, "files": {}}
    if not report["valid"]:
        return result
    try:
        identity = bench_engine_identity()
        if identity["engine_version_int"] != 52004 or identity["toolkit_version"] != "0.17.0":
            raise ValueError("This adapter is verified only for SWMM 5.2.4 / swmm-toolkit 0.17.0; review a new version before use.")
        inp = _input(snapshot)
        fingerprint = {"site_sha256": report["site_package_sha256"], "model_sha256": report["model_sha256"], "run_sha256": report["run_sha256"], "engine": identity,
                       "derived_geometry_sha256": content_sha256({"curves": snapshot["curves"], "effective_links": snapshot["effective_links"]}),
                       "input_sha256": hashlib.sha256(inp.encode("utf-8")).hexdigest()}
        run_hash = content_sha256(fingerprint)
        folder = Path(output_dir).resolve()
        folder.mkdir(parents=True, exist_ok=False)
        request = {**snapshot, "fingerprint": fingerprint, "simulation_sha256": run_hash}
        (folder / "model.inp").write_text(inp, encoding="utf-8", newline="\n")
        (folder / "request.json").write_text(canonical_json(request) + "\n", encoding="utf-8", newline="\n")
    except Exception as exc:
        result.update(status="failed", errors=[{"path": "$", "code": "preparation_failed", "message": f"{type(exc).__name__}: {exc}"}])
        return result
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).with_name("_bench_worker.py")), str(folder)], cwd=folder,
                              capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        (folder / "worker.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if proc.returncode != 0 or not (folder / "worker-result.json").is_file():
            raise RuntimeError(f"Worker exited {proc.returncode}; see retained worker log.")
        worker = parse_json((folder / "worker-result.json").read_bytes())
        result.update(worker)
    except Exception as exc:
        if not (folder / "worker.log").exists():
            (folder / "worker.log").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        result.update(status="failed", valid=False, errors=[{"path": "$", "code": "worker_failed", "message": f"{type(exc).__name__}: {exc}"}])
    result.update(**CLAIMS, simulation_sha256=run_hash, engine=identity, engine_identity=identity, fingerprint=fingerprint)
    result["files"] = {p.name: str(p) for p in folder.iterdir() if p.is_file()}
    result["files"].update({"result.json": str(folder / "result.json"), "manifest.json": str(folder / "manifest.json")})
    (folder / "result.json").write_text(canonical_json(result) + "\n", encoding="utf-8", newline="\n")
    manifest = {"schema_version": "monsoon.bench-run-evidence/1", "fingerprint": fingerprint, "simulation_sha256": run_hash,
                "status": result["status"], "file_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}}
    (folder / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
    return result


def _step_comparison(base, half, site):
    check = {"status": "unresolved", "passed": False, "relative_tolerance": 0.02,
             "absolute_tolerances": {"stage_m": 0.0001, "flow_m3_s": 1e-7, "volume_m3": 1e-6},
             "metrics": [], "errors": [], "interpretation": "Project numerical adequacy check only, not physical validation; all limits were fixed in adapter source before this pair ran."}
    if not base["valid"] or not half["valid"]:
        check["errors"].append("Both primary and refined runs must pass every numerical and represented-pathway check.")
        return check
    a, b = base["timeseries"], half["timeseries"]
    if [r["elapsed_s"] for r in a] != [r["elapsed_s"] for r in b]:
        check["errors"].append("Reporting grids differ; no interpolation or dropped samples is allowed.")
        return check

    def metric(name, values_a, values_b, absolute, offset=0):
        difference = max(abs(x - y) for x, y in zip(values_a, values_b))
        scale = max(abs(x - offset) for x in values_a + values_b)
        tolerance = max(absolute, 0.02 * scale)
        check["metrics"].append({"metric": name, "maximum_absolute_difference": difference, "tolerance": tolerance, "passed": difference <= tolerance})

    for node in site["nodes"]:
        nid = node["id"]
        metric("stage_m:" + nid, [r["stage_m"][nid] for r in a], [r["stage_m"][nid] for r in b], 0.0001, node["invert_m"])
        metric("peak_stage_m:" + nid, [base["diagnostics"]["maximum_stage_m"][nid]], [half["diagnostics"]["maximum_stage_m"][nid]], 0.0001, node["invert_m"])
    for link in site["links"]:
        lid = link["id"]
        metric("link_flow_m3_s:" + lid, [r["link_flow_m3_s"][lid] for r in a], [r["link_flow_m3_s"][lid] for r in b], 1e-7)
    metric("storage_m3:SYSTEM", [r["storage_m3"] for r in a], [r["storage_m3"] for r in b], 1e-6)
    for quantity in ("outflow_m3_s", "spill_m3_s"):
        for location in a[0][quantity]:
            metric(quantity + ":" + location, [r[quantity][location] for r in a], [r[quantity][location] for r in b], 1e-7)
    for quantity in ("spill_by_node_m3", "discharge_by_outfall_m3", "backflow_by_outfall_m3"):
        for location, value in base["diagnostics"][quantity].items():
            metric(quantity + ":" + location, [value], [half["diagnostics"][quantity][location]], 1e-6)
    check["passed"] = all(m["passed"] for m in check["metrics"])
    check["status"] = "passed" if check["passed"] else "unresolved"
    return check


def run_bench_model(site, model, run, output_dir):
    """Run one primary/half-step pair in an immutable private research folder.

    Input dictionaries are snapshotted before validation. No cache, fitting,
    operational activation, or caller-supplied runner is accepted.
    """
    report, snapshot = _validate(site, model, run)
    if not report["valid"]:
        return {**report, "timeseries": [], "diagnostics": {}, "files": {}}
    folder = None
    try:
        identity = bench_engine_identity()
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="bench-pair-", dir=root))
        s, m, r = (snapshot[k] for k in ("site", "model", "run"))
        refined_model = parse_json(m)
        refined_model["numerics"]["routing_step_s"] /= 2
        refined_run = parse_json(r)
        refined_run["model_sha256"] = content_sha256(refined_model)
        primary = _run_attempt(s, m, r, folder / "base")
        refined = _run_attempt(s, refined_model, refined_run, folder / "half", _refinement=True)
        comparison = _step_comparison(primary, refined, s)
        comparison.update(primary_routing_step_s=m["numerics"]["routing_step_s"], refined_routing_step_s=refined_model["numerics"]["routing_step_s"],
                          primary_status=primary["status"], refined_status=refined["status"], refined_model_sha256=content_sha256(refined_model),
                          refined_run_sha256=content_sha256(refined_run), refined_errors=refined["errors"],
                          perturbation="Only routing_step_s is halved; run.model_sha256 is rebound to that explicitly recorded numerical perturbation.")
        if primary.get("engine_identity") != identity or refined.get("engine_identity") != identity:
            comparison.update(passed=False, status="unresolved")
            comparison["errors"].append("Engine/source identity changed across the verification pair.")
        pair_fingerprint = {"primary": primary.get("fingerprint"), "refined": refined.get("fingerprint"), "verification": "automatic_fixed_step_halving/1"}
        result = {**primary, "valid": comparison["passed"], "status": "succeeded" if comparison["passed"] else "numerically_unresolved",
                  "step_halving": comparison, "simulation_sha256": content_sha256(pair_fingerprint), "fingerprint": pair_fingerprint,
                  "files": {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}, **CLAIMS}
        if not comparison["passed"]:
            result["errors"] = primary["errors"] + [{"path": "$.step_halving", "code": "step_halving_unresolved", "message": "Primary/refined numerical checks or common-grid agreement did not pass; both attempts are retained."}]
        result["files"].update({"result.json": str(folder / "result.json"), "manifest.json": str(folder / "manifest.json")})
        (folder / "result.json").write_text(canonical_json(result) + "\n", encoding="utf-8", newline="\n")
        manifest = {"schema_version": "monsoon.bench-pair-evidence/1", "fingerprint": pair_fingerprint, "simulation_sha256": result["simulation_sha256"],
                    "status": result["status"], "file_sha256": {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}}
        (folder / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
        return result
    except Exception as exc:
        failed = {**report, "valid": False, "status": "failed", "timeseries": [], "diagnostics": {}, "files": {},
                  "errors": [{"path": "$", "code": "pair_failed", "message": f"{type(exc).__name__}: {exc}"}]}
        if folder is not None:
            failed["files"] = {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}
            failed["retained_attempt_directory"] = str(folder)
        return failed


def verify_bench_result(result):
    """Check local paired evidence integrity and the currently loaded engine.

    This verifies consistency of local bytes, not authenticity of supplied data,
    physical validation, or approval. No external reference is fetched.
    """
    report = {"valid": False, "errors": [], "status": "integrity_unresolved", **CLAIMS}
    try:
        value = parse_json(result)
        paths = value.get("files")
        if not isinstance(paths, dict) or not 2 <= len(paths) <= 24 or not isinstance(paths.get("result.json"), str):
            raise ValueError("Expected a complete paired artifact map (at most24 files).")
        root = Path(paths["result.json"]).resolve().parent
        actual = {}
        for p in root.rglob("*"):
            if p.is_symlink():
                raise ValueError("Evidence folders cannot contain symbolic links.")
            if p.is_file():
                actual[p.relative_to(root).as_posix()] = p
        if set(paths) != set(actual):
            raise ValueError("Artifact map does not equal the complete retained folder inventory.")
        for name, declared in paths.items():
            relative = PurePosixPath(name)
            if (not isinstance(declared, str) or relative.is_absolute() or ".." in relative.parts or
                    "\\" in name or ":" in name or str(relative) != name or
                    Path(declared).resolve() != (root / name).resolve() or not (root / name).resolve().is_relative_to(root)):
                raise ValueError("Unsafe or mismatched evidence path: " + name)
        stored = parse_json((root / "result.json").read_bytes())
        if canonical_json(stored) != canonical_json(value):
            raise ValueError("Returned/cached result differs from its immutable stored result.")
        manifest = parse_json((root / "manifest.json").read_bytes())
        if manifest.get("schema_version") != "monsoon.bench-pair-evidence/1":
            raise ValueError("Expected the paired-run manifest schema.")
        expected_files = {name for name in actual if name != "manifest.json"}
        checksums = manifest.get("file_sha256")
        if not isinstance(checksums, dict) or set(checksums) != expected_files:
            raise ValueError("Manifest is incomplete or contains extra files.")
        if any(hashlib.sha256(actual[name].read_bytes()).hexdigest() != digest for name, digest in checksums.items()):
            raise ValueError("At least one retained artifact checksum changed.")
        for key in ("fingerprint", "simulation_sha256", "status"):
            if manifest.get(key) != value.get(key):
                raise ValueError("Manifest/result identity mismatch: " + key)
        if content_sha256(value["fingerprint"]) != value.get("simulation_sha256"):
            raise ValueError("Pair fingerprint does not match its hash.")
        identity = bench_engine_identity()
        if value.get("engine_identity") != identity or value.get("engine") != identity:
            raise ValueError("Result engine/source identity differs from the currently loaded adapter/runtime.")
        for prefix, key in (("base", "primary"), ("half", "refined")):
            child = parse_json((root / prefix / "result.json").read_bytes())
            if child.get("fingerprint") != value["fingerprint"].get(key) or child.get("engine_identity") != identity:
                raise ValueError("Child attempt fingerprint does not match the pair.")
        if value.get("valid") is True and not (value.get("step_halving", {}).get("passed") is True):
            raise ValueError("Successful result lacks a passing step verification.")
        report.update(valid=True, status="local_artifact_integrity_verified")
    except Exception as exc:
        report["errors"] = [{"path": "$.files", "code": "artifact_integrity", "message": f"{type(exc).__name__}: {exc}"}]
    return report
