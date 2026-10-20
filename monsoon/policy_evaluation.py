"""Reproduce the v0.3 prespecified synthetic policy experiment.

Run --freeze only after targeted source tests, and --evaluate afterwards. The
freeze and first-start records are append-only evidence, not independent sealing.
All SWMM artefacts remain under var/ and are excluded from source packaging.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import threading
import time

from .assurance_hydraulics import checked_state
from .case import load_case
from .hydraulics import engine_info
from .observed_policy import (METHODS, ROOT, condition_development, fingerprint,
                              freeze_observed_policy, load_protocol,
                              replay_observed_policy, source_fingerprints)

OUT = ROOT / "evidence/v0.3"


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def freeze_experiment(protocol=None, output=OUT):
    protocol = load_protocol() if protocol is None else protocol
    case = load_case()
    if protocol["source_case_sha256"] != case["case_sha256"]:
        raise ValueError("The original reference case changed")
    value = {"schema_version": 1, "frozen_utc": _utc(), "protocol_sha256": protocol["protocol_sha256"],
             "source_sha256": source_fingerprints(), "engine": engine_info(),
             "statement": "Implementation, observations, development profiles, evaluation inputs, baselines, metrics and gates were recorded before the first new v0.3 SWMM policy outcomes. No externally supervised seal or independent blindness is claimed.",
             "prior_knowledge": protocol["prior_knowledge"],
             "evaluation_event_ids": [e["id"] for e in protocol["evaluation_events"]]}
    value["freeze_sha256"] = fingerprint(value)
    _write_new(Path(output) / "policy-freeze.json", value)
    return value


def validate_freeze(protocol, output=OUT):
    value = json.loads((Path(output) / "policy-freeze.json").read_text(encoding="utf-8"))
    if fingerprint({k: v for k, v in value.items() if k != "freeze_sha256"}) != value["freeze_sha256"]:
        raise ValueError("Implementation freeze record was altered")
    if value["protocol_sha256"] != protocol["protocol_sha256"] or value["source_sha256"] != source_fingerprints():
        raise ValueError("Source or protocol differs from the pre-outcome freeze")
    if value["engine"] != engine_info():
        raise ValueError("Engine differs from the pre-outcome freeze")
    return value


class CheckedCache:
    """Bound expensive numerical triplets, with one shared cache across methods."""
    def __init__(self, cache_path, maximum_pairs):
        self.cache_path, self.maximum_pairs = cache_path, maximum_pairs
        self.results, self.lock, self.requests, self.errors = {}, threading.Lock(), 0, []

    def __call__(self, state, scenario):
        key = fingerprint({"state": sorted(state), "hydraulic": scenario["hydraulic"]})
        with self.lock:
            self.requests += 1
            if key in self.results:
                return deepcopy(self.results[key])
            if len(self.results) >= self.maximum_pairs:
                raise RuntimeError("Prespecified numerical computation budget exhausted; missing evidence remains unresolved")
            # A single caller per key is used by the deterministic prewarm list.
            self.results[key] = None
        try:
            result = checked_state(state, scenario, self.cache_path)
        except Exception as exc:
            result = {"valid": False, "status": "failed", "errors": [f"{type(exc).__name__}: {exc}"]}
        with self.lock:
            self.results[key] = result
        return deepcopy(result)

    def summary(self):
        runs = [run for value in self.results.values() if value for run in value.get("assurance_numerics", {}).get("runs", [])]
        return {"callback_requests": self.requests, "distinct_state_hydraulic_pairs": len(self.results),
                "numerical_run_references": len(runs),
                "distinct_run_ids": len({r["run_id"] for r in runs if r.get("run_id")}),
                "maximum_pairs": self.maximum_pairs,
                "note": "Three numerical configurations per physical state/event are checks, not independent replicates."}


def outcome_summary(rows, tie_m3):
    by_method = {}
    for method in METHODS:
        selected = [row for row in rows if row["method"] == method]
        counts = {key: 0 for key in ("positive", "tie", "loss", "abstention", "unresolved")}
        paired = {key: 0 for key in ("positive", "tie", "loss", "unresolved")}
        for row in selected:
            if row["status"] == "unresolved" or row["total_spill_m3"] is None or row["reference_spill_m3"] is None:
                category = paired_category = "unresolved"
            elif row["status"] == "inadmissible":
                category = paired_category = "loss"
            else:
                gain = row["reference_spill_m3"] - row["total_spill_m3"]
                paired_category = "positive" if gain > tie_m3 else "loss" if gain < -tie_m3 else "tie"
                category = "abstention" if row["abstained"] and method != "no_work" else paired_category
            row["outcome_vs_no_work"] = category
            row["paired_outcome_vs_no_work"] = paired_category
            counts[category] += 1
            paired[paired_category] += 1
        by_method[method] = {"label": METHODS[method], "event_rows": len(selected), "exclusive_outcomes": counts,
                             "paired_outcomes_including_abstention_ties": paired,
                             "abstention_rows": sum(r["abstained"] for r in selected),
                             "inadmissible_rows": sum(r["status"] == "inadmissible" for r in selected),
                             "duration_overrun_rows": sum(r["duration_overrun"] for r in selected),
                             "deadline_failure_rows": sum(r["deadline_failure"] for r in selected),
                             "diagnostic_only": method == "original_queue_diagnostic"}
    comparisons = {}
    for other in ("screened_marginal", "screened_downstream", "screened_nominal", "no_work"):
        counts = {key: 0 for key in ("positive", "tie", "loss", "unresolved")}
        for chosen in (r for r in rows if r["method"] == "observed_robust"):
            baseline = next(r for r in rows if r["method"] == other and r["scenario_id"] == chosen["scenario_id"])
            if "unresolved" in (chosen["status"], baseline["status"]):
                counts["unresolved"] += 1
            elif chosen["status"] == "inadmissible":
                counts["loss"] += 1
            elif baseline["status"] == "inadmissible":
                counts["positive"] += 1
            else:
                gain = baseline["total_spill_m3"] - chosen["total_spill_m3"]
                counts["positive" if gain > tie_m3 else "loss" if gain < -tie_m3 else "tie"] += 1
        comparisons[other] = counts
    return {"by_method": by_method, "observed_robust_paired_against": comparisons,
            "category_definition": "Unresolved takes precedence; any protected-prefix harm is a loss even when total spill falls. Otherwise >0.05 m3 reduction is positive, +/-0.05 m3 is tie. Zero-dispatch operational rows are exclusive abstentions; their supported spill ties also appear in the separate paired table. No-work itself is a tie reference."}


def _markdown(report):
    lines = ["# Observation-conditioned policy experiment v0.3", "", report["claim"], "",
             f'Protocol SHA-256: `{report["protocol_sha256"]}`. Implementation freeze: `{report["freeze_sha256"]}`.', "",
             "| Method | Positive | Tie | Loss | Abstention | Unresolved | Duration overruns |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for item in report["summary"]["by_method"].values():
        c = item["exclusive_outcomes"]
        lines.append(f'| {item["label"]} | {c["positive"]} | {c["tie"]} | {c["loss"]} | {c["abstention"]} | {c["unresolved"]} | {item["duration_overrun_rows"]} |')
    lines.extend(["", report["summary"]["category_definition"], "", "## Paired comparison with competent baselines", "",
                  "| Baseline | Robust positive | Tie | Robust loss | Unresolved |", "|---|---:|---:|---:|---:|"])
    for method, c in report["summary"]["observed_robust_paired_against"].items():
        lines.append(f'| {METHODS[method]} | {c["positive"]} | {c["tie"]} | {c["loss"]} | {c["unresolved"]} |')
    lines.extend(["", "## Scope and limitations", ""] + [f"- {x}" for x in report["limitations"]])
    lines.extend(["", "The JSON report contains every event, method, completed subset, duration exception, per-node spill/depth/threshold duration, and every checked achieved prefix. Development rejection certificates and policies are in policy-development.json. Full raw numerical outputs are retained under var/policy-v3-swmm and are excluded from release archives.", ""])
    return "\n".join(lines)


def evaluate_experiment(protocol=None, output=OUT, cache_path=None):
    protocol = load_protocol() if protocol is None else protocol
    output = Path(output)
    freeze = validate_freeze(protocol, output)
    if (output / "policy-results.json").exists():
        raise FileExistsError("Recorded results are immutable; use a separately named prespecified study for further work")
    started = output / "policy-evaluation-start.json"
    if not started.exists():
        _write_new(started, {"first_started_utc": _utc(), "freeze_sha256": freeze["freeze_sha256"],
                             "statement": "This marker precedes the first new hydraulic outcome. Restart with identical frozen sources may reuse verified raw caches; it does not create a new evaluation."})
    elif json.loads(started.read_text(encoding="utf-8"))["freeze_sha256"] != freeze["freeze_sha256"]:
        raise ValueError("Started evaluation belongs to another implementation freeze")
    case, t0 = load_case(), time.perf_counter()
    cache_path = Path(cache_path or ROOT / "var/policy-v3-swmm")
    development = CheckedCache(cache_path, protocol["compute_limits"]["development_state_event_pairs"])
    scenarios_by_observation = {}
    prewarm = {}
    for observation_id, observation in protocol["observations"].items():
        try:
            scenarios = condition_development(case, observation, protocol)
        except ValueError:
            continue
        scenarios_by_observation[observation_id] = scenarios
        for scenario in scenarios:
            prewarm[fingerprint(scenario["hydraulic"])] = scenario
    print(f'Frozen study: {len(prewarm)} distinct no-work development configurations; {len(protocol["evaluation_events"])} sealed event rows.', flush=True)
    with ThreadPoolExecutor(max_workers=protocol["compute_limits"]["workers"]) as pool:
        list(pool.map(lambda scenario: development((), scenario), prewarm.values()))
    policies = {}
    for observation_id, observation in protocol["observations"].items():
        print(f'Selecting policies for observation {observation_id}; no evaluation outcomes have been read.', flush=True)
        policies[observation_id] = freeze_observed_policy(case, observation, scenarios_by_observation.get(observation_id),
                                                         development, protocol)
        print(f'{observation_id}: {policies[observation_id]["status"]}; robust queue {policies[observation_id]["policies"]["observed_robust"]["queue"]}; {len(development.results)} cumulative numerical triplets.', flush=True)
    development_report = {"freeze_sha256": freeze["freeze_sha256"], "protocol_sha256": protocol["protocol_sha256"],
                          "policies": policies, "computation": development.summary(),
                          "elapsed_seconds": time.perf_counter() - t0}
    development_path = output / "policy-development.json"
    if not development_path.exists():
        _write_new(development_path, development_report)
    else:
        saved = json.loads(development_path.read_text(encoding="utf-8"))
        if fingerprint(saved["policies"]) != fingerprint(policies):
            raise ValueError("Restarted development decisions differ from the saved freeze")
    evaluation = CheckedCache(cache_path, protocol["compute_limits"]["evaluation_state_event_pairs"])
    rows, event_reports = [], []
    # Selection above is complete before the first sealed hydraulic replay.
    for event in protocol["evaluation_events"]:
        result = replay_observed_policy(policies[event["observation_id"]], case, event, evaluation, protocol)
        event_reports.append(result)
        rows.extend(result["results"])
        print(f'Evaluated {event["id"]}: robust {result["results"][0]["status"]}; {len(evaluation.results)} numerical triplets.', flush=True)
    summary = outcome_summary(rows, case["tie_m3"])
    report = {"schema_version": 1, "completed_utc": _utc(), "protocol_sha256": protocol["protocol_sha256"],
              "freeze_sha256": freeze["freeze_sha256"], "source_sha256": freeze["source_sha256"],
              "claim": "A prespecified synthetic research comparison on the reused reference topology. It is not measured bench validation, an independent catchment test, or evidence of field/operator superiority.",
              "counts": {"designed_event_rows": len(event_reports), "distinct_hydraulic_event_configurations": len({fingerprint(e["hydraulic"]) for e in protocol["evaluation_events"]}),
                         "reused_synthetic_networks": 1, "new_measured_events": 0, "independent_catchments": 0,
                         "method_event_rows": len(rows), "statistical_sample_size": None},
              "summary": summary, "events": deepcopy(protocol["evaluation_events"]), "results": rows,
              "computation": {"development": development.summary(), "evaluation": evaluation.summary(), "elapsed_seconds": time.perf_counter() - t0},
              "limitations": protocol["limitations"]}
    _write_new(output / "policy-results.json", report)
    text_path = output / "policy-report.md"
    with text_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_markdown(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze", action="store_true")
    action.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    result = freeze_experiment() if args.freeze else evaluate_experiment()
    print(json.dumps({k: result[k] for k in ("freeze_sha256", "protocol_sha256", "summary") if k in result}, indent=2))
