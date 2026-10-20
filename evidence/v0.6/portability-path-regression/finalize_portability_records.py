"""Seal native path-regression evidence and refresh explicitly reviewed pins."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

WORK = Path(__file__).resolve().parent
WORKSPACE = WORK.parents[1]
PROJECT = WORKSPACE / "outputs/monsoon-rehearsal"
EVIDENCE = PROJECT / "evidence/v0.6"
sys.path.insert(0, str(PROJECT))
from monsoon import bench_model as bench
from monsoon import bench_balance_audit as audit


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    test_root = WORK / "final-regression"
    long_root = next((test_root / "test_native_audit_keeps_comple0").rglob("bench-balance-audit-*"))
    positive = test_root / "positive-cumulative-audit0"
    parent_root = next(positive.glob("bench-pair-*"))
    short_root = next(positive.glob("bench-balance-audit-*"))
    value = json.loads((long_root / "result.json").read_bytes())
    parent = json.loads((parent_root / "result.json").read_bytes())
    short = json.loads((short_root / "result.json").read_bytes())
    assert value["valid"] and bench.verify_bench_result(parent)["valid"]
    assert audit.verify_bench_balance_audit(value, parent)["valid"]
    destination = EVIDENCE / "portability-path-regression"
    destination.mkdir(exist_ok=False)
    for name, source in (("original-parent", parent_root), ("short-audit", short_root), ("long-audit", long_root)):
        shutil.copytree(source, destination / name)
    # Preserve the deliberately overlong cwd failure as a separate transport
    # limitation; it must not be represented as native truncation evidence.
    failed_root = next((WORK / "post-fix-regression/test_native_audit_keeps_comple0").rglob("bench-balance-audit-*"))
    shutil.copytree(failed_root, destination / "overlong-cwd-unlaunched")
    observations = {}
    cwd_failures = {}
    for label in ("base", "half"):
        native = long_root / label / "model.out"
        worker = json.loads((long_root / label / "worker-result.json").read_bytes())
        short_worker = json.loads((short_root / label / "worker-result.json").read_bytes())
        observations[label] = {
            "original_working_directory": str(native.parent),
            "working_directory_characters": len(str(native.parent)),
            "original_output_path": str(native), "output_path_characters": len(str(native)),
            "output_bytes": native.stat().st_size,
            "input_bytes_equal": (long_root / label / "model.inp").read_bytes() == (parent_root / label / "model.inp").read_bytes(),
            "diagnostics_equal_to_short_path": worker["diagnostics"] == short_worker["diagnostics"],
            "report_samples_equal_to_short_path": worker["report_samples"] == short_worker["report_samples"],
            "actual_file_names": sorted(p.name for p in native.parent.iterdir())}
        assert all(observations[label][key] for key in ("input_bytes_equal", "diagnostics_equal_to_short_path", "report_samples_equal_to_short_path"))
        cwd_failures[label] = {"original_working_directory": str(failed_root / label),
                               "working_directory_characters": len(str(failed_root / label)),
                               "worker_started": (failed_root / label / "worker-result.json").exists(),
                               "retained_log": (failed_root / label / "worker.log").read_text()}
        assert not cwd_failures[label]["worker_started"] and "WinError 267" in cwd_failures[label]["retained_log"]
    summary = {"schema_version": "monsoon.native-path-portability-regression/1", "evidence_kind": "synthetic_fixture",
               "original_parent_integrity_verified": True, "long_path_audit_integrity_verified": True,
               "native_qualified": True, "expected_audit_file_count": 18, "observations": observations,
               "separate_overlong_cwd_process_launch_failure": cwd_failures,
               "archive_path_note": "Copied bundles preserve every original byte and historical absolute path. Verification above was performed at their original live locations; the archive inventory binds copied bytes without claiming relocated-path validity.",
               "physical_validation_established": False, "operational_activation_allowed": False}
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    shutil.copy2(Path(__file__), destination / "finalize_portability_records.py")
    records = {p.relative_to(destination).as_posix(): {"sha256": sha(p), "bytes": p.stat().st_size}
               for p in sorted(destination.rglob("*")) if p.is_file()}
    manifest = {"schema_version": "monsoon.native-path-portability-manifest/1", "files": records,
                "file_count_excluding_manifest": len(records), "total_payload_bytes": sum(r["bytes"] for r in records.values())}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    pins_path = EVIDENCE / "reviewed-source-sha256.json"
    original_pins = (EVIDENCE / "portability-history/reviewed-source-sha256.json").read_bytes()
    assert pins_path.read_bytes() == original_pins
    pins = json.loads(original_pins)
    pins["source_sha256"] = {name: sha(PROJECT / name) for name in pins["source_sha256"]}
    for name in ("tests/test_bench_initialization.py", "BENCH_INITIALIZATION.md"):
        pins["source_sha256"][name] = sha(PROJECT / name)
    pins["portability_addendum"] = "PORTABILITY_ADDENDUM.md"
    pins["previous_pins"] = "portability-history/reviewed-source-sha256.json"
    pins["interpretation"] += " Refreshed after the two new workers' guarded local-filename repair; prior reviewed pins and report are preserved in portability-history."
    pins_path.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"regression_payload_files": len(records), "regression_payload_bytes": manifest["total_payload_bytes"],
                      "new_source_pins_sha256": sha(pins_path), "observations": observations}, indent=2))


if __name__ == "__main__":
    main()
