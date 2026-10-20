"""Additive current-source evidence after the native local-filename repair."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

WORKSPACE = Path(__file__).resolve().parents[2]
PROJECT = WORKSPACE / "outputs/monsoon-rehearsal"
sys.path.insert(0, str(PROJECT))
from monsoon import bench_model as bench
from monsoon import bench_balance_audit as audit
from monsoon.site_data import canonical_json

EVIDENCE = PROJECT / "evidence/v0.6"
ROOT = EVIDENCE / "portability-balance-review"
HISTORY = EVIDENCE / "portability-history"
TEMPLATES = PROJECT / "data/templates"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    return json.loads((TEMPLATES / name).read_bytes())


def seal(folder, schema):
    records = {path.relative_to(folder).as_posix(): {"sha256": sha(path), "bytes": path.stat().st_size}
               for path in sorted(folder.rglob("*")) if path.is_file()}
    manifest = {"schema_version": schema, "files": records,
                "physical_validation_established": False, "operational_activation_allowed": False,
                "total_payload_bytes": sum(row["bytes"] for row in records.values()),
                "file_count_excluding_manifest": len(records)}
    (folder / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main():
    HISTORY.mkdir(parents=True, exist_ok=False)
    for name in ("REVIEW.md", "reviewed-source-sha256.json", "audit-tests.xml"):
        shutil.copy2(EVIDENCE / name, HISTORY / name)
    shutil.copytree(Path(__file__).resolve().parent / "pre-fix", HISTORY / "package-audit-failure")
    history_manifest = seal(HISTORY, "monsoon.portability-history/1")
    ROOT.mkdir(exist_ok=False)
    source = ROOT / "source"
    source.mkdir()
    identity = audit.bench_balance_audit_identity()
    for name in set(identity["source_sha256"]) | set(identity["engine_identity"]["source_sha256"]):
        shutil.copy2(PROJECT / "monsoon" / name, source / name)
    shutil.copy2(Path(__file__), source / Path(__file__).name)
    shutil.copy2(PROJECT / "tests/test_bench_balance_audit.py", source / "test_bench_balance_audit.py")
    shutil.copy2(Path(__file__).resolve().parent / "final-regression.xml", ROOT / "audit-tests.xml")
    summary = {"schema_version": "monsoon.synthetic-cumulative-review/1", "evidence_kind": "synthetic_fixture",
               "physical_validation_established": False, "operational_activation_allowed": False,
               "independent_hydraulic_validation": False, "audit_identity": identity,
               "change": "Only native audit filename handling changed: use short local names in the checked isolated working folder. Original input bytes, routing settings and numerical criteria are unchanged.",
               "previous_evidence": "../cumulative-balance-review/summary.json", "cases": {}}
    for name in ("original-pulse", "rapid-tailwater", "analytical-compartment"):
        if name == "analytical-compartment":
            site, model = [load(f"synthetic_bench_prepared_{part}_v2.json") for part in ("site", "model")]
            spec = load("synthetic_bench_prepared_run_v1.json")["continuous_run"]
        else:
            site, model, spec = [load(f"synthetic_bench_{part}_v1.json") for part in ("site", "model", "run")]
            if name == "rapid-tailwater":
                spec.update(run_id="SYNTHETIC-REVIEW-TAILWATER", notes="Invented rapid tailwater cycle for independent numerical conservation review; no measured observations.")
                spec["inflows"][0]["points"] = [{"elapsed_s": 0, "value_m3_s": 0}, {"elapsed_s": 120, "value_m3_s": 0}]
                spec["receiving_stages"][0]["points"] = [{"elapsed_s": t, "stage_m": h} for t, h in ((0, 0), (20, .06), (50, .06), (90, 0), (120, 0))]
        directory = ROOT / name
        directory.mkdir()
        parent = bench.run_bench_model(site, model, spec, directory)
        assert parent["valid"], parent["errors"]
        original = {key: sha(Path(path)) for key, path in parent["files"].items()}
        result = audit.audit_bench_balance(parent, directory)
        verification = audit.verify_bench_balance_audit(result, parent)
        assert verification["valid"], verification["errors"]
        assert original == {key: sha(Path(path)) for key, path in parent["files"].items()}
        assert result["valid"] is (name == "analytical-compartment")
        previous_summary = json.loads((EVIDENCE / "cumulative-balance-review/summary.json").read_bytes())
        previous_result = json.loads((EVIDENCE / "cumulative-balance-review" / previous_summary["cases"][name]["audit_result"]).read_bytes())
        exact = {}
        for label in ("base", "half"):
            # Locate the prior retained artifact relative to its sealed evidence,
            # rather than relying on the literal absolute paths in its result.
            old_folder = (EVIDENCE / "cumulative-balance-review" / previous_summary["cases"][name]["audit_result"]).parent
            old_worker = json.loads((old_folder / label / "worker-result.json").read_bytes())
            new_worker = json.loads(Path(result["files"][label + "/worker-result.json"]).read_bytes())
            exact[label] = {
                "input_bytes_equal": Path(result["files"][label + "/model.inp"]).read_bytes() == (old_folder / label / "model.inp").read_bytes(),
                "diagnostics_equal": new_worker["diagnostics"] == old_worker["diagnostics"],
                "report_samples_equal": new_worker["report_samples"] == old_worker["report_samples"],
                "qualification_equal": new_worker["valid"] == old_worker["valid"],
            }
            assert all(exact[label].values()), exact
        summary["cases"][name] = {"original_pair_valid": parent["valid"], "audit_valid": result["valid"],
            "audit_status": result["status"], "local_integrity_verified": True,
            "original_pair_result": Path(parent["files"]["result.json"]).relative_to(ROOT).as_posix(),
            "audit_result": Path(result["files"]["result.json"]).relative_to(ROOT).as_posix(),
            "numerical_comparison_to_pre_portability_evidence": exact, "attempts": result["attempts"]}
        print(name, "original_pair=", parent["valid"], "cumulative_audit=", result["valid"], "all numeric records unchanged", flush=True)
    (ROOT / "summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8", newline="\n")
    manifest = seal(ROOT, "monsoon.synthetic-cumulative-review-manifest/1")
    print(json.dumps({"current_evidence": str(ROOT), "files_excluding_manifest": manifest["file_count_excluding_manifest"],
                      "payload_bytes": manifest["total_payload_bytes"], "history_files_excluding_manifest": history_manifest["file_count_excluding_manifest"]}), flush=True)


if __name__ == "__main__":
    main()
