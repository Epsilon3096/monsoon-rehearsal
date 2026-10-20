"""Additive every-routing-endpoint balance audit of exact retained v1 inputs.

The historical paired runner and its artifacts remain unchanged. This audit
replays their exact input bytes in separate processes, checks cumulative water
accounting throughout the run, and retains an independent evidence bundle.
It is a same-engine numerical check, never independent physical validation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

from . import bench_model
from .site_data import canonical_json, content_sha256, parse_json

SCHEMA_VERSION = "monsoon.bench-balance-audit/1"
AUDIT_VERSION = "1.0.0"
RULE = "every_actual_routing_endpoint_max_1mL_or_1percent_initial_plus_entered/1"
_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_CLAIMS = {"physical_validation_established": False, "operational_activation_allowed": False,
           "independent_hydraulic_validation": False, "engineering_approval_established": False}
_CHILD_NAMES = {"model.inp", "model.rpt", "model.out", "request.json", "worker.log",
                "worker-result.json", "result.json", "manifest.json"}


def bench_balance_audit_identity():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SHA256:
        raise ValueError("Balance audit source changed after import; restart before execution or freeze.")
    engine = bench_model.bench_engine_identity()
    if engine["engine_version_int"] != 52004 or engine["toolkit_version"] != "0.17.0":
        raise ValueError("Only the reviewed SWMM 5.2.4 / swmm-toolkit 0.17.0 runtime is supported.")
    return {"audit_version": AUDIT_VERSION, "rule": RULE, "engine_identity": engine,
            "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ("bench_balance_audit.py", "_bench_balance_worker.py")}}


def _empty():
    return {"schema_version": SCHEMA_VERSION, "valid": False, "status": "invalid_parent",
            "errors": [], "files": {}, "attempts": {}, "rule": RULE,
            "interpretation": "Exact-input same-engine cumulative conservation audit, not independent hydraulic or physical validation.",
            **_CLAIMS}


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(folder, result, schema):
    result["files"] = {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}
    result["files"].update({"result.json": str(folder / "result.json"), "manifest.json": str(folder / "manifest.json")})
    (folder / "result.json").write_text(canonical_json(result) + "\n", encoding="utf-8", newline="\n")
    manifest = {"schema_version": schema, "audit_sha256": result["audit_sha256"],
                "fingerprint": result["fingerprint"], "status": result["status"],
                "file_sha256": {p.relative_to(folder).as_posix(): _hash(p) for p in folder.rglob("*")
                                if p.is_file() and p != folder / "manifest.json"}}
    (folder / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")


def _attempt(parent, label, folder, identity, binding):
    folder.mkdir(parents=True, exist_ok=False)
    inp = Path(parent["files"][label + "/model.inp"]).read_bytes()
    raw_request = Path(parent["files"][label + "/request.json"]).read_bytes()
    if hashlib.sha256(inp).hexdigest() != binding[label + "/model.inp"] or hashlib.sha256(raw_request).hexdigest() != binding[label + "/request.json"]:
        raise ValueError("Parent input/request bytes changed before the audit attempt.")
    original_request = parse_json(raw_request)
    if hashlib.sha256(inp).hexdigest() != original_request["fingerprint"]["input_sha256"]:
        raise ValueError("Parent request does not bind its retained input bytes.")
    fingerprint = {"attempt": label, "parent_binding_sha256": content_sha256(binding),
                   "input_sha256": hashlib.sha256(inp).hexdigest(), "source_request_sha256": hashlib.sha256(raw_request).hexdigest(),
                   "audit_identity": identity, "rule": RULE}
    request = {"schema_version": "monsoon.bench-balance-audit-request/1", "fingerprint": fingerprint,
               "parent_request_json": raw_request.decode("utf-8")}
    (folder / "model.inp").write_bytes(inp)
    (folder / "request.json").write_text(canonical_json(request) + "\n", encoding="utf-8", newline="\n")
    result = {"schema_version": SCHEMA_VERSION, "valid": False, "status": "failed", "errors": [],
              "fingerprint": fingerprint, "audit_sha256": content_sha256(fingerprint),
              "audit_identity": identity, "diagnostics": {}, **_CLAIMS}
    try:
        process = subprocess.run([sys.executable, str(Path(__file__).with_name("_bench_balance_worker.py")), str(folder)],
                                 cwd=folder, capture_output=True, text=True, timeout=90,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        (folder / "worker.log").write_text(process.stdout + process.stderr, encoding="utf-8")
        if process.returncode or not (folder / "worker-result.json").is_file():
            raise ValueError(f"Audit worker exited {process.returncode}; inspect the retained log.")
        result.update(parse_json((folder / "worker-result.json").read_bytes()))
    except Exception as exc:
        if not (folder / "worker.log").exists():
            (folder / "worker.log").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        result.update(valid=False, status="failed", errors=[{"code": "audit_worker", "message": f"{type(exc).__name__}: {exc}"}])
    result.update(**_CLAIMS)
    _write(folder, result, "monsoon.bench-balance-audit-attempt-evidence/1")
    return result


def audit_bench_balance(result, output_dir):
    """Audit both exact retained inputs of a qualified v1 pair without altering it."""
    report, folder = _empty(), None
    try:
        parent = parse_json(result)
        if parent.get("valid") is not True or parent.get("status") != "succeeded" or parent.get("step_halving", {}).get("passed") is not True:
            raise ValueError("A qualified original paired prediction is required before this additional numerical audit.")
        integrity = bench_model.verify_bench_result(parent)
        if integrity.get("valid") is not True:
            raise ValueError("Original paired prediction failed integrity: " + canonical_json(integrity.get("errors", [])))
        identity = bench_balance_audit_identity()
        if parent["engine_identity"] != identity["engine_identity"]:
            raise ValueError("Parent engine/source differs from the current audited runtime.")
        binding = {"parent_simulation_sha256": parent["simulation_sha256"],
                   **{name: _hash(Path(parent["files"][name])) for name in
                      ("result.json", "manifest.json", "base/model.inp", "base/request.json", "half/model.inp", "half/request.json")}}
        root = Path(output_dir).resolve()
        parent_root = Path(parent["files"]["result.json"]).resolve().parent
        if root == parent_root or root.is_relative_to(parent_root):
            raise ValueError("Audit output must be outside the immutable original pair directory.")
        root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="bench-balance-audit-", dir=root))
        base = _attempt(parent, "base", folder / "base", identity, binding)
        half = _attempt(parent, "half", folder / "half", identity, binding)
        # A late source or parent-artifact change cannot turn a completed replay
        # into evidence for a different pair.
        unchanged = (bench_balance_audit_identity() == identity and bench_model.verify_bench_result(parent).get("valid") is True and
                     all(_hash(Path(parent["files"][name])) == digest for name, digest in binding.items() if name != "parent_simulation_sha256"))
        passed = base.get("valid") is True and half.get("valid") is True and unchanged
        fingerprint = {"parent_binding": binding, "audit_identity": identity, "rule": RULE,
                       "primary": base["fingerprint"], "refined": half["fingerprint"]}
        report.update(valid=passed, status="succeeded" if passed else "numerically_unresolved", audit_identity=identity,
                      parent_simulation_sha256=parent["simulation_sha256"], parent_binding=binding,
                      fingerprint=fingerprint, audit_sha256=content_sha256(fingerprint),
                      attempts={label: {k: value[k] for k in ("valid", "status", "errors", "diagnostics", "audit_sha256")}
                                for label, value in (("base", base), ("half", half))},
                      errors=[] if passed else [{"code": "cumulative_balance_unresolved", "message": "Both exact-input attempts must pass every cumulative routing-endpoint balance and retain unchanged parent/source identity."}])
        _write(folder, report, "monsoon.bench-balance-audit-pair-evidence/1")
        return report
    except Exception as exc:
        report.update(valid=False, status="failed" if folder else "invalid_parent",
                      errors=[{"code": "audit_failed", "message": f"{type(exc).__name__}: {exc}"}])
        if folder is not None:
            report["files"] = {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}
            report["retained_attempt_directory"] = str(folder)
        return report


def verify_bench_balance_audit(result, parent_result=None):
    """Verify retained bytes/current lineage; optionally bind the exact parent pair."""
    report = {"valid": False, "status": "invalid_artifact", "errors": [], **_CLAIMS}
    try:
        value = parse_json(result)
        files = value.get("files")
        if not isinstance(files, dict) or not {"result.json", "manifest.json"} <= set(files):
            raise ValueError("Complete retained audit artifact map is required.")
        root = Path(files["result.json"]).resolve().parent
        actual = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
        if set(actual) != set(files) or len(actual) > 18:
            raise ValueError("Audit artifact map differs from its bounded folder inventory.")
        sizes = [path.stat().st_size for path in actual.values()]
        if any(size > 64 * 1024 * 1024 for size in sizes) or sum(sizes) > 256 * 1024 * 1024:
            raise ValueError("Audit artifact bytes exceed the bounded evidence inventory.")
        for name, path in files.items():
            relative = PurePosixPath(name)
            if (not isinstance(path, str) or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name or str(relative) != name or
                    (root / name).is_symlink() or Path(path).resolve() != (root / name).resolve() or not Path(path).resolve().is_relative_to(root)):
                raise ValueError("Unsafe or mismatched audit artifact path: " + name)
        if parse_json((root / "result.json").read_bytes()) != value:
            raise ValueError("Audit result differs from its stored artifact.")
        manifest = parse_json((root / "manifest.json").read_bytes())
        if manifest.get("schema_version") != "monsoon.bench-balance-audit-pair-evidence/1":
            raise ValueError("Unexpected audit pair manifest schema.")
        expected = {name: _hash(path) for name, path in actual.items() if name != "manifest.json"}
        if manifest.get("file_sha256") != expected:
            raise ValueError("Audit manifest does not match all retained file bytes.")
        if any(manifest.get(key) != value.get(key) for key in ("fingerprint", "audit_sha256", "status")) or content_sha256(value["fingerprint"]) != value.get("audit_sha256"):
            raise ValueError("Audit fingerprint/manifest mismatch.")
        identity = bench_balance_audit_identity()
        if value.get("schema_version") != SCHEMA_VERSION or value.get("rule") != RULE or value["fingerprint"].get("rule") != RULE:
            raise ValueError("Unexpected audit schema or cumulative balance rule.")
        if any(value.get(key) is not False for key in _CLAIMS):
            raise ValueError("A numerical audit cannot establish physical or operational claims.")
        if value.get("audit_identity") != identity or value["fingerprint"].get("audit_identity") != identity:
            raise ValueError("Audit source/runtime identity has changed.")
        if value.get("parent_binding") != value["fingerprint"].get("parent_binding") or value.get("parent_simulation_sha256") != value["parent_binding"].get("parent_simulation_sha256"):
            raise ValueError("Audit parent binding changed.")
        for label, fingerprint_key in (("base", "primary"), ("half", "refined")):
            child = parse_json((root / label / "result.json").read_bytes())
            request = parse_json((root / label / "request.json").read_bytes())
            if child.get("fingerprint") != value["fingerprint"][fingerprint_key] or child.get("audit_identity") != identity or content_sha256(child["fingerprint"]) != child.get("audit_sha256"):
                raise ValueError("Audit child fingerprint/source mismatch.")
            child_fp = child["fingerprint"]
            if (child_fp.get("parent_binding_sha256") != content_sha256(value["parent_binding"]) or
                    child_fp.get("input_sha256") != value["parent_binding"][label + "/model.inp"] or
                    child_fp.get("source_request_sha256") != value["parent_binding"][label + "/request.json"] or
                    child_fp.get("audit_identity") != identity or child_fp.get("rule") != RULE or child_fp.get("attempt") != label):
                raise ValueError("Audit child is not bound to the exact parent input, request, and rule.")
            if any(child.get(key) is not False for key in _CLAIMS):
                raise ValueError("A child numerical audit cannot establish physical or operational claims.")
            if request["fingerprint"] != child["fingerprint"] or _hash(root / label / "model.inp") != value["parent_binding"][label + "/model.inp"]:
                raise ValueError("Audit child no longer uses the exact parent input.")
            if hashlib.sha256(request["parent_request_json"].encode("utf-8")).hexdigest() != value["parent_binding"][label + "/request.json"]:
                raise ValueError("Audit retained parent request changed.")
            summary = {k: child[k] for k in ("valid", "status", "errors", "diagnostics", "audit_sha256")}
            if value["attempts"][label] != summary:
                raise ValueError("Audit child summary differs from its retained result.")
            if value.get("valid") is True and (child.get("valid") is not True or not _CHILD_NAMES <= {p.name for p in (root / label).iterdir() if p.is_file()}):
                raise ValueError("A successful audit requires both successful complete native attempts.")
            if (root / label / "worker-result.json").is_file():
                worker = parse_json((root / label / "worker-result.json").read_bytes())
                if any(child.get(key) != worker.get(key) for key in ("valid", "status", "errors", "diagnostics", "report_samples")):
                    raise ValueError("Audit child result differs from its retained worker output.")
        if value.get("valid") is True and (value.get("status") != "succeeded" or value.get("errors")):
            raise ValueError("A successful audit must retain a consistent qualification status.")
        if parent_result is not None:
            parent = parse_json(parent_result)
            if bench_model.verify_bench_result(parent).get("valid") is not True or parent.get("simulation_sha256") != value["parent_simulation_sha256"]:
                raise ValueError("Supplied parent pair does not match this audit.")
            if any(_hash(Path(parent["files"][name])) != digest for name, digest in value["parent_binding"].items() if name != "parent_simulation_sha256"):
                raise ValueError("Supplied parent artifact bytes differ from this audit's sealed binding.")
        report.update(valid=True, status="local_artifact_integrity_verified")
    except Exception as exc:
        report["errors"] = [{"code": "artifact_integrity", "message": f"{type(exc).__name__}: {exc}"}]
    return report
