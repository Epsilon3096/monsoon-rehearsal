"""Retain three explicit synthetic exact-input numerical review cases."""
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2] / "outputs" / "monsoon-rehearsal"
sys.path.insert(0, str(PROJECT))
from monsoon import bench_model as bench
from monsoon import bench_balance_audit as audit
from monsoon.site_data import canonical_json

ROOT = PROJECT / "evidence" / "v0.6" / "cumulative-balance-review"
TEMPLATES = PROJECT / "data" / "templates"


def load(name):
    return json.loads((TEMPLATES / name).read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ROOT.mkdir(parents=True, exist_ok=False)
    source = ROOT / "source"
    source.mkdir()
    identity = audit.bench_balance_audit_identity()
    for name in set(identity["source_sha256"]) | set(identity["engine_identity"]["source_sha256"]):
        (source / name).write_bytes((PROJECT / "monsoon" / name).read_bytes())
    (source / "retain_final_audit_evidence.py").write_bytes(Path(__file__).read_bytes())
    summary = {"schema_version": "monsoon.synthetic-cumulative-review/1", "evidence_kind": "synthetic_fixture",
               "physical_validation_established": False, "operational_activation_allowed": False,
               "independent_hydraulic_validation": False, "audit_identity": identity, "cases": {}}
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
        assert audit.verify_bench_balance_audit(result, parent)["valid"]
        assert original == {key: sha(Path(path)) for key, path in parent["files"].items()}
        assert result["valid"] is (name == "analytical-compartment")
        summary["cases"][name] = {"original_pair_valid": parent["valid"], "audit_valid": result["valid"],
            "audit_status": result["status"], "local_integrity_verified": True,
            "original_pair_result": Path(parent["files"]["result.json"]).relative_to(ROOT).as_posix(),
            "audit_result": Path(result["files"]["result.json"]).relative_to(ROOT).as_posix(),
            "attempts": result["attempts"]}
        print(name, "original_pair=", parent["valid"], "cumulative_audit=", result["valid"], flush=True)
    (ROOT / "summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8", newline="\n")
    records = {path.relative_to(ROOT).as_posix(): {"sha256": sha(path), "bytes": path.stat().st_size}
               for path in sorted(ROOT.rglob("*")) if path.is_file()}
    manifest = {"schema_version": "monsoon.synthetic-cumulative-review-manifest/1", "files": records,
                "physical_validation_established": False, "operational_activation_allowed": False,
                "total_payload_bytes": sum(row["bytes"] for row in records.values()), "file_count_excluding_manifest": len(records)}
    (ROOT / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
    print("retained", len(records) + 1, "files; payload", manifest["total_payload_bytes"], "bytes", flush=True)


if __name__ == "__main__":
    main()
