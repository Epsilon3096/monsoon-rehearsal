"""Deterministic cache I/O controls; the worker is explicitly not a SWMM run."""
from hashlib import sha256
import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from monsoon import hydraulics
from monsoon.case import get_scenario


def sharing_error(code):
    error = OSError(errno.EACCES, "Injected Windows sharing/locking conflict")
    error.winerror = code
    return error


@pytest.fixture
def worker(monkeypatch):
    state = {"calls": 0, "valid": True}
    monkeypatch.setattr(hydraulics, "engine_info", lambda: {
        "engine": "CACHE I/O TEST DOUBLE; NOT SWMM EVIDENCE", "engine_version": "fixture"})

    def emit_fixture(command, **kwargs):
        state["calls"] += 1
        folder = Path(kwargs["cwd"])
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        for name in ("model.rpt", "model.out"):
            (folder / name).write_bytes(b"CACHE I/O TEST DOUBLE; NOT SWMM EVIDENCE")
        result = {"run_id": request["run_id"], "status": "succeeded" if state["valid"] else "failed",
                  "valid": state["valid"], "engine_version": "fixture",
                  "total_spill_m3": 12.75 if state["valid"] else None,
                  "nodes": {"A1": {"spill_m3": 12.75}} if state["valid"] else {},
                  "diagnostics": {"origin": "CACHE I/O TEST DOUBLE; NOT SWMM EVIDENCE"},
                  "timeseries": [], "errors": [] if state["valid"] else ["Declared test-worker failure"]}
        (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="CACHE I/O TEST DOUBLE", stderr="")

    monkeypatch.setattr(hydraulics.subprocess, "run", emit_fixture)
    return state


def assert_sealed_attempt(result):
    """Recheck saved bytes and all raw hashes independently of the cache reader."""
    files = {key: Path(value) for key, value in result["files"].items()}
    saved = json.loads(files["result"].read_bytes())
    manifest = json.loads(files["manifest"].read_bytes())
    canonical = json.dumps(saved, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert saved == result
    assert sha256(canonical).hexdigest() == manifest["result_sha256"]
    assert manifest["status"] == result["status"]
    assert manifest["run_id"] == result["run_id"]
    assert manifest["files"] == result["files"]
    assert {"model.inp", "model.rpt", "model.out", "worker.log", "request.json"} <= set(manifest["file_sha256"])
    for name, digest in manifest["file_sha256"].items():
        assert sha256((files["manifest"].parent / name).read_bytes()).hexdigest() == digest
    assert sha256(files["input"].read_bytes()).hexdigest() == manifest["request_fingerprint"]["input_sha256"]
    return {path.name: path.read_bytes() for path in files.values()}


def test_transient_sharing_retries_then_publishes_a_verified_cache_hit(tmp_path, monkeypatch, worker):
    actual_replace = hydraulics.os.replace
    calls, waits = [], []

    def replace(source, target):
        calls.append((Path(source), Path(target)))
        if len(calls) < 3:
            raise sharing_error(31 + len(calls))  # Exercise both 32 and 33.
        return actual_replace(source, target)

    monkeypatch.setattr(hydraulics.os, "replace", replace)
    monkeypatch.setattr(hydraulics.time, "sleep", waits.append)
    result = hydraulics.run_state([], get_scenario("P1"), tmp_path)
    assert len(calls) == 3 and waits == [.01, .02]
    assert len({source for source, _ in calls}) == 1
    assert result["valid"] and result["total_spill_m3"] == 12.75 and not result["cache_hit"]
    before = assert_sealed_attempt(result)
    target = tmp_path / result["run_id"] / "result.json"
    assert target.read_bytes() == Path(result["files"]["result"]).read_bytes()
    assert not list(tmp_path.rglob("*.tmp"))
    cached = hydraulics.run_state([], get_scenario("P1"), tmp_path)
    assert cached["cache_hit"] and worker["calls"] == 1
    assert cached["nodes"] == result["nodes"] and cached["total_spill_m3"] == 12.75
    assert before == {Path(path).name: Path(path).read_bytes() for path in result["files"].values()}


@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("previous_index", [False, True])
def test_exhausted_sharing_returns_exact_sealed_run_and_preserves_prior_index(
        tmp_path, monkeypatch, worker, valid, previous_index):
    prior = hydraulics.run_state([], get_scenario("P1"), tmp_path) if previous_index else None
    old_index = (tmp_path / prior["run_id"] / "result.json").read_bytes() if prior else None
    prior_bytes = assert_sealed_attempt(prior) if prior else None
    worker["valid"] = valid
    calls, waits = [], []

    def always_locked(source, target):
        calls.append((Path(source), Path(target)))
        raise sharing_error(32)

    monkeypatch.setattr(hydraulics.os, "replace", always_locked)
    monkeypatch.setattr(hydraulics.time, "sleep", waits.append)
    result = hydraulics.run_state([], get_scenario("P1"), tmp_path, force=previous_index)
    assert len(calls) == 5 and waits == [.01, .02, .04, .08]
    assert worker["calls"] == 1 + int(previous_index)
    assert result["valid"] is valid and not result["cache_hit"]
    assert_sealed_attempt(result)
    if valid:
        assert result["status"] == "succeeded" and result["total_spill_m3"] == 12.75
        assert result["nodes"]["A1"]["spill_m3"] == 12.75 and result["errors"] == []
    else:
        assert result["status"] == "failed" and result["total_spill_m3"] is None
        assert result["nodes"] == {} and result["errors"] == ["Declared test-worker failure"]
    target = tmp_path / result["run_id"] / "result.json"
    assert not list(tmp_path.rglob("*.tmp"))
    if prior:
        assert result["files"]["result"] != prior["files"]["result"]
        assert target.read_bytes() == old_index
        assert prior_bytes == {Path(path).name: Path(path).read_bytes() for path in prior["files"].values()}
    else:
        assert not target.exists()


@pytest.mark.parametrize("error", [OSError(errno.ENOSPC, "Injected disk full"),
                                   PermissionError(errno.EACCES, "Injected ordinary access denial"),
                                   sharing_error(5)])
def test_nonsharing_publication_errors_propagate_and_keep_sealed_evidence(tmp_path, monkeypatch, worker, error):
    calls, waits = [], []

    def fail(source, target):
        calls.append((source, target))
        raise error

    monkeypatch.setattr(hydraulics.os, "replace", fail)
    monkeypatch.setattr(hydraulics.time, "sleep", waits.append)
    with pytest.raises(OSError) as raised:
        hydraulics.run_state([], get_scenario("P1"), tmp_path)
    assert raised.value is error
    assert len(calls) == 1 and waits == []
    assert not list(tmp_path.rglob("*.tmp"))
    manifests = list(tmp_path.glob("*/manifest.json"))
    assert len(manifests) == 1
    result = json.loads((manifests[0].parent / "result.json").read_bytes())
    assert result["valid"] and result["total_spill_m3"] == 12.75
    assert_sealed_attempt(result)
    assert not (tmp_path / result["run_id"] / "result.json").exists()


def test_locked_temp_cleanup_does_not_delete_target_or_invalidate_run(tmp_path, monkeypatch, worker):
    prior = hydraulics.run_state([], get_scenario("P1"), tmp_path)
    target = tmp_path / prior["run_id"] / "result.json"
    old_index = target.read_bytes()
    actual_unlink = Path.unlink
    deleted = []

    def locked_replace(source, destination):
        raise sharing_error(33)

    def locked_temp(path, *args, **kwargs):
        deleted.append(path)
        if path.suffix == ".tmp":
            raise sharing_error(32)
        return actual_unlink(path, *args, **kwargs)

    monkeypatch.setattr(hydraulics.os, "replace", locked_replace)
    monkeypatch.setattr(hydraulics.time, "sleep", lambda _: None)
    monkeypatch.setattr(Path, "unlink", locked_temp)
    result = hydraulics.run_state([], get_scenario("P1"), tmp_path, force=True)
    assert result["valid"] and result["total_spill_m3"] == 12.75
    assert_sealed_attempt(result)
    assert target.read_bytes() == old_index
    assert len(deleted) == 1 and deleted[0].suffix == ".tmp" and deleted[0] != target
    assert deleted[0].read_bytes() == Path(result["files"]["result"]).read_bytes()
    assert result["files"]["result"] != prior["files"]["result"]


def test_partial_temp_write_error_is_cleaned_without_replacing_good_index(tmp_path, monkeypatch, worker):
    prior = hydraulics.run_state([], get_scenario("P1"), tmp_path)
    target = tmp_path / prior["run_id"] / "result.json"
    old_index = target.read_bytes()
    actual_write = Path.write_text
    error = OSError(errno.ENOSPC, "Injected partial index write")

    def partial_write(path, text, *args, **kwargs):
        if path.suffix == ".tmp":
            actual_write(path, text[:7], *args, **kwargs)
            raise error
        return actual_write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", partial_write)
    with pytest.raises(OSError) as raised:
        hydraulics.run_state([], get_scenario("P1"), tmp_path, force=True)
    assert raised.value is error
    assert target.read_bytes() == old_index
    assert not list(tmp_path.rglob("*.tmp"))
    assert len(list(tmp_path.glob("*/manifest.json"))) == 2
    for path in tmp_path.glob("*/manifest.json"):
        assert_sealed_attempt(json.loads((path.parent / "result.json").read_bytes()))
