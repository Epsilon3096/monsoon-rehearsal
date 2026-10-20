"""Exact product regression in three isolated module shards, then SWMM verification.

No scientific test, criterion, case identity or product-profile exclusion changes.
Current collect-only output fixes complete coverage; all original 622 remain required.
The previous complete XML supplies load estimates, never an exclusion of new tests.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

W = Path(__file__).resolve().parents[1]
ROOT = W / "outputs/monsoon-rehearsal"
EV = ROOT / "evidence/v0.8.1"
REFERENCE = EV / "product-20261017-01/pytest.xml"
REFERENCE_SHA256 = "085f8096635e5db479b134bfe205ce0c470ca127667a13bc779f68d4d6cdc0e4"
EXPECTED_COUNT = 622
HEAVY = ("tests/test_app.py", "tests/test_ui_workflow_review.py", "tests/test_decision_interface.py")

# Self-contained copy of the established private-process containment helper.
_JOB_ENV="MONSOON_PRIVATE_BENCH_JOB"


def _windows_api():
    import ctypes
    from ctypes import wintypes as w
    api=ctypes.WinDLL("kernel32",use_last_error=True)
    definitions={"CreateJobObjectW":([ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
                 "OpenJobObjectW":([w.DWORD,w.BOOL,w.LPCWSTR],w.HANDLE),
                 "SetInformationJobObject":([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
                 "AssignProcessToJobObject":([w.HANDLE,w.HANDLE],w.BOOL),
                 "IsProcessInJob":([w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL),
                 "GetCurrentProcess":([],w.HANDLE),"CloseHandle":([w.HANDLE],w.BOOL),
                 "TerminateJobObject":([w.HANDLE,w.UINT],w.BOOL)}
    for name,(args,result) in definitions.items():
        method=getattr(api,name)
        method.argtypes,method.restype=args,result
    return ctypes,w,api


def join_worker_job():
    """Fail closed before computation if the private Windows job is unavailable."""
    if os.name != "nt":
        return
    c,w,api=_windows_api()
    name=os.environ.get(_JOB_ENV)
    if not name or not name.startswith("Local\\MonsoonBench-"):
        raise RuntimeError("Conservative worker requires its parent's private process job.")
    handle=api.OpenJobObjectW(0x0001|0x0004,False,name)
    if not handle:
        raise c.WinError(c.get_last_error())
    try:
        process=api.GetCurrentProcess()
        member=w.BOOL()
        if not api.IsProcessInJob(process,handle,c.byref(member)):
            raise c.WinError(c.get_last_error())
        if not member.value and not api.AssignProcessToJobObject(handle,process):
            raise c.WinError(c.get_last_error())
        if not api.IsProcessInJob(process,handle,c.byref(member)) or not member.value:
            raise RuntimeError("Private worker process containment was not established.")
    finally:
        # Parent must own the last handle, otherwise close-on-timeout cannot
        # terminate descendants while a worker keeps its own handle open.
        api.CloseHandle(handle)


def _create_job(name):
    c,w,api=_windows_api()
    class Basic(c.Structure):
        _fields_=[("PerProcessUserTimeLimit",c.c_longlong),("PerJobUserTimeLimit",c.c_longlong),
                  ("LimitFlags",w.DWORD),("MinimumWorkingSetSize",c.c_size_t),("MaximumWorkingSetSize",c.c_size_t),
                  ("ActiveProcessLimit",w.DWORD),("Affinity",c.c_size_t),("PriorityClass",w.DWORD),("SchedulingClass",w.DWORD)]
    class IO(c.Structure):
        _fields_=[(n,c.c_ulonglong) for n in ("ReadOperationCount","WriteOperationCount","OtherOperationCount",
                                            "ReadTransferCount","WriteTransferCount","OtherTransferCount")]
    class Extended(c.Structure):
        _fields_=[("BasicLimitInformation",Basic),("IoInfo",IO),("ProcessMemoryLimit",c.c_size_t),
                  ("JobMemoryLimit",c.c_size_t),("PeakProcessMemoryUsed",c.c_size_t),("PeakJobMemoryUsed",c.c_size_t)]
    handle=api.CreateJobObjectW(None,name)
    if not handle:
        raise c.WinError(c.get_last_error())
    limits=Extended()
    limits.BasicLimitInformation.LimitFlags=0x00002000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(handle,9,c.byref(limits),c.sizeof(limits)):
        error=c.get_last_error()
        api.CloseHandle(handle)
        raise c.WinError(error)
    return api,handle


def run_bounded_worker(command, *, cwd, timeout, log_path, environment):
    """Run only a cooperating private worker and reap its whole process family."""
    environment=dict(environment)
    api=handle=None
    process=None
    if os.name == "nt":
        name="Local\\MonsoonBench-"+uuid.uuid4().hex
        api,handle=_create_job(name)
        environment[_JOB_ENV]=name
    else:
        environment.pop(_JOB_ENV,None)
    try:
        with Path(log_path).open("wb") as log:
            process=subprocess.Popen(command,cwd=cwd,env=environment,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                     start_new_session=os.name != "nt")
            try:
                return process.wait(timeout=timeout)
            except BaseException:
                if os.name == "nt":
                    # Explicit termination also handles the brief self-join
                    # window before the worker closes its query handle.
                    api.TerminateJobObject(handle,1)
                    api.CloseHandle(handle)
                    handle=None
                else:
                    try:
                        os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                raise
    finally:
        if handle is not None:
            api.CloseHandle(handle)



def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def hashes():
    paths = {ROOT / name for name in ("app.py", "pytest-product.ini", "pyproject.toml", "requirements.lock.txt")}
    for directory in ("monsoon", "tests", "data"):
        paths.update(path for path in (ROOT / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def xml_cases(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    require(all(isinstance(part, str) and part for identity in identities for part in identity), "Incomplete JUnit case identity")
    require(len(identities) == len(set(identities)), "Duplicate JUnit case identity")
    suites = [root] if root.tag == "testsuite" else list(root)
    require(suites and all(suite.tag == "testsuite" and not list(suite.iter("testsuite"))[1:]
                           for suite in suites), "Unexpected nested JUnit suite structure")
    for suite in suites:
        actual = list(suite.iter("testcase"))
        expected = {"tests": len(actual), **{key: sum(case.find(tag) is not None for case in actual)
                    for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}
        require(all(int(suite.get(key, "-1")) == value for key, value in expected.items()),
                "JUnit suite totals disagree with actual case outcomes")
    return root, cases, identities


def case_module(identity, included):
    candidates = [name for name in included
                  if identity[0] == name[:-3].replace("/", ".")
                  or identity[0].startswith(name[:-3].replace("/", ".") + ".")]
    require(len(candidates) == 1, "JUnit case cannot be mapped to exactly one declared module: " + repr(identity))
    return candidates[0]


def collection_child(output, arguments):
    """Record authoritative pytest items without executing a test or fixture."""
    import pytest
    from _pytest import junitxml
    before = hashes()
    runner_before = digest(Path(__file__))
    record = {"schema": "monsoon.product-test-collection/1", "source_before": before,
              "source_freeze_sha256": digest(output.parent / "source-freeze.json"),
              "runner_sha256": runner_before, "pytest_version": pytest.__version__,
              "junitxml_sha256": digest(junitxml.__file__), "items": [],
              "deselected": 0, "collection_errors": 0, "collection_skips": 0}
    class Inventory:
        def pytest_deselected(self, items):
            record["deselected"] += len(items)
        def pytest_collectreport(self, report):
            record["collection_errors"] += int(report.failed)
            record["collection_skips"] += int(report.skipped)
        def pytest_collection_finish(self, session):
            for item in session.items:
                names = junitxml.mangle_test_address(item.nodeid)
                record["items"].append({"nodeid": item.nodeid, "module": item.nodeid.split("::", 1)[0],
                    "classname": ".".join(names[:-1]), "name": junitxml.bin_xml_escape(names[-1])})
    exit_code = int(pytest.main(arguments, plugins=[Inventory()]))
    record["items"].sort(key=lambda item: item["nodeid"])
    record["source_after"] = hashes()
    record["source_unchanged"] = before == record["source_after"]
    record["runner_unchanged"] = digest(Path(__file__)) == runner_before
    record["exit_code"] = exit_code
    save(output, record)
    return exit_code


def validate_collection(folder, included, before, runner_hash):
    record = json.loads((folder / "collection.json").read_text(encoding="utf-8"))
    require(record.get("schema") == "monsoon.product-test-collection/1"
            and type(record.get("exit_code")) is int and record["exit_code"] == 0
            and all(type(record.get(key)) is int and record[key] == 0
                    for key in ("deselected", "collection_errors", "collection_skips")), "Incomplete collection")
    require(record.get("source_before") == record.get("source_after") == before
            and record.get("source_unchanged") is True and record.get("runner_unchanged") is True
            and record.get("runner_sha256") == runner_hash
            and record.get("source_freeze_sha256") == digest(folder / "source-freeze.json"), "Collection source binding differs")
    items = record["items"]
    identities = [(item["classname"], item["name"]) for item in items]
    require(len(items) == len({item["nodeid"] for item in items}) == len(set(identities))
            and all(item["module"] in included for item in items)
            and {item["module"] for item in items} == set(included), "Incomplete or duplicate current collection")
    require(all(case_module(identity, included) == item["module"] for item, identity in zip(items, identities)),
            "Collected module/JUnit identity differs")
    return items, sorted(identities)


def partition(included, current_items):
    require(digest(REFERENCE) == REFERENCE_SHA256, "Previous complete XML changed")
    _, cases, identities = xml_cases(REFERENCE)
    require(len(cases) == EXPECTED_COUNT, "Previous complete case count changed")
    durations = {name: 0.0 for name in included}
    per_module = {name: [(item["classname"], item["name"]) for item in current_items if item["module"] == name]
                  for name in included}
    current_ids = sorted(identity for values in per_module.values() for identity in values)
    require(set(identities).issubset(current_ids), "A legacy test case disappeared from current collection")
    for case, identity in zip(cases, identities):
        name = case_module(identity, included)
        duration = float(case.get("time", "0"))
        require(math.isfinite(duration) and duration >= 0, "Invalid prior case duration")
        durations[name] += duration
    require(all(per_module.values()) and all(name in included for name in HEAVY), "Incomplete prior module inventory")
    groups = [[name] for name in HEAVY]
    totals = [durations[name] for name in HEAVY]
    for name in sorted(set(included) - set(HEAVY), key=lambda value: (-durations[value], value)):
        index = min(range(3), key=lambda value: (totals[value], value))
        groups[index].append(name)
        totals[index] += durations[name]
    shards = [{"id": f"shard-{index + 1}", "files": sorted(group),
               "expected_case_ids": sorted(identity for name in group for identity in per_module[name]),
               "prior_duration_s": totals[index], "xml": f"pytest-shard-{index + 1}.xml",
               "log": f"pytest-shard-{index + 1}.log"} for index, group in enumerate(groups)]
    require(sorted(name for shard in shards for name in shard["files"]) == included, "Shard module coverage mismatch")
    return shards, current_ids, sorted(identities)


def run_command(command, folder, log_name, environment, kind, files=None):
    record = {"kind": kind, "argv": command, "started_utc": datetime.now(timezone.utc).isoformat(),
              "returncode": None, "log": log_name}
    if files is not None:
        record["test_files"] = files
    try:
        record["returncode"] = run_bounded_worker(command, cwd=ROOT, timeout=1800,
                                                   log_path=folder / log_name, environment=environment)
    except BaseException as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["completed_utc"] = datetime.now(timezone.utc).isoformat()
    if (folder / log_name).is_file():
        record["log_sha256"] = digest(folder / log_name)
    print(f'{kind}: exit {record["returncode"]}; {folder / log_name}', flush=True)
    return record


def aggregate(folder, shards, expected_ids):
    combined = ET.Element("testsuites")
    observed = []
    shard_records = []
    for shard in shards:
        root, cases, identities = xml_cases(folder / shard["xml"])
        require(sorted(identities) == shard["expected_case_ids"], "Exact case coverage differs in " + shard["id"])
        suites = [root] if root.tag == "testsuite" else list(root)
        require(suites and all(suite.tag == "testsuite" for suite in suites), "Unexpected JUnit suite structure")
        for suite in suites:
            combined.append(deepcopy(suite))  # Preserve actual attributes, testcases, outcomes and captured output.
        observed.extend(identities)
        shard_records.append({"id": shard["id"], "xml": shard["xml"],
                              "xml_sha256": digest(folder / shard["xml"]), "case_count": len(cases)})
    require(len(observed) == len(set(observed)) and sorted(observed) == expected_ids,
            "Exact aggregate case coverage differs from complete current collection")
    ET.ElementTree(combined).write(folder / "pytest.xml", encoding="utf-8", xml_declaration=True)
    cases = list(combined.iter("testcase"))
    counts = {"tests": len(cases), **{key: sum(case.find(tag) is not None for case in cases)
              for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}
    coverage = {"status": "passed", "reference_xml_sha256": REFERENCE_SHA256,
                "original_required_case_count": EXPECTED_COUNT,
                "collection_sha256": digest(folder / "collection.json"),
                "partition_sha256": digest(folder / "test-partition.json"),
                "expected_case_count": len(expected_ids), "actual_case_count": len(cases),
                "exact_case_ids": [list(identity) for identity in sorted(observed)], "shards": shard_records,
                "aggregate_xml_sha256": digest(folder / "pytest.xml"),
                "aggregation": "Original complete suite elements copied without changing any testcase result"}
    save(folder / "test-coverage.json", coverage)
    return counts


def main():
    require(__debug__ and not os.environ.get("PYTHONOPTIMIZE"), "Optimized verification execution is forbidden")
    require(not os.environ.get("PYTEST_ADDOPTS"), "Unset PYTEST_ADDOPTS; no hidden filtering is allowed")
    require(len(sys.argv) == 2 and sys.argv[1].replace("-", "").isalnum(), "Supply one unique attempt label")
    folder = EV / sys.argv[1]
    folder.mkdir(parents=True, exist_ok=False)
    before = hashes()
    paths = sorted((ROOT / "tests").glob("test_*.py"))
    included = [path.relative_to(ROOT).as_posix() for path in paths if not path.name.startswith("test_bench")]
    excluded = [path.relative_to(ROOT).as_posix() for path in paths if path.name.startswith("test_bench")]
    require(digest(REFERENCE) == REFERENCE_SHA256, "Previous complete XML changed")
    _, _, legacy_ids = xml_cases(REFERENCE)
    require(len(legacy_ids) == EXPECTED_COUNT, "Original case count differs")
    runtime = Path(tempfile.mkdtemp(prefix=sys.argv[1] + " parallel ", dir=W / "work"))
    freeze = {"created_utc": datetime.now(timezone.utc).isoformat(), "files": before,
              "profile": "SWMM product and non-bench workflow regression; NOT full research qualification",
              "included_test_files": included, "excluded_bench_research_test_files": excluded,
              "excluded_reason": "Separate unqualified bench research; existing failures and original test bodies retained. No custom solver run or scientific acceptance is claimed.",
              "runner_sha256": digest(Path(__file__)), "execution_layout": "pytest-collected-module-shards/2",
              "maximum_parallel_pytest_processes": 3, "process_timeout_seconds": 1800,
              "collection_artifact": "collection.json", "partition_artifact": "test-partition.json",
              "coverage_reference": {"source": REFERENCE.relative_to(ROOT).as_posix(),
                  "artifact": "coverage-reference.xml", "sha256": REFERENCE_SHA256,
                  "case_count": EXPECTED_COUNT, "exact_case_ids": sorted(legacy_ids)}, "temporary_runtime": str(runtime)}
    save(folder / "source-freeze.json", freeze)
    (folder / "verification-runner.py").write_bytes(Path(__file__).read_bytes())
    (folder / "coverage-reference.xml").write_bytes(REFERENCE.read_bytes())
    result = {"scope": freeze["profile"], "attempt": folder.relative_to(ROOT).as_posix(), "commands": [],
              "passed": False, "custom_solver_qualified": False, "scheduling_advantage_established": False,
              "field_validation_established": False, "execution_layout": freeze["execution_layout"]}
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONOPTIMIZE", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        collection_args = [sys.executable, "-B", str(Path(__file__).resolve()), "--_child", "collect",
                           str(folder / "collection.json"), "-c", "pytest-product.ini", "--collect-only",
                           "-q", "-p", "no:cacheprovider", *included]
        collection_command = run_command(collection_args, folder, "collection.log", environment, "collection", included)
        result["commands"].append(collection_command)
        require(collection_command["returncode"] == 0, "Current complete pytest collection failed")
        current_items, expected_ids = validate_collection(folder, included, before, freeze["runner_sha256"])
        shards, partition_ids, _ = partition(included, current_items)
        require(partition_ids == expected_ids, "Current collection partition differs")
        save(folder / "test-partition.json", {"schema": "monsoon.product-test-partition/1",
             "source_freeze_sha256": digest(folder / "source-freeze.json"),
             "collection_sha256": digest(folder / "collection.json"), "reference_xml_sha256": REFERENCE_SHA256,
             "case_count": len(expected_ids), "exact_case_ids": expected_ids, "pytest_shards": shards})
        require(hashes() == before and digest(Path(__file__)) == freeze["runner_sha256"], "Sources changed during collection")
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = []
            for shard in shards:
                (runtime / shard["id"]).mkdir()
                private = dict(environment, MONSOON_DATA_DIR=str(runtime / shard["id"] / "workflow"),
                               MONSOON_CACHE_DIR=str(ROOT / "var/hydraulic_runs"))
                args = [sys.executable, "-B", str(Path(__file__).resolve()), "--_child", "pytest",
                        "-c", "pytest-product.ini", "-q", "-p", "no:cacheprovider",
                        "--basetemp=" + str(runtime / shard["id"] / "pytest"),
                        "--junitxml=" + str(folder / shard["xml"]), *shard["files"]]
                futures.append(pool.submit(run_command, args, folder, shard["log"], private,
                                           "pytest:" + shard["id"], shard["files"]))
            result["commands"].extend(future.result() for future in futures)
        result["tests"] = aggregate(folder, shards, expected_ids)
        result["test_coverage"] = "test-coverage.json"
        require(all(command["returncode"] == 0 for command in result["commands"]), "A pytest shard failed")
        require(all(result["tests"][key] == 0 for key in ("failures", "errors", "skipped")), "Product regression is incomplete or failed")
        require(hashes() == before and digest(Path(__file__)) == freeze["runner_sha256"], "Sources or runner changed during shards")
        verification_environment = dict(environment, MONSOON_DATA_DIR=str(runtime / "verification" / "workflow"),
                                        MONSOON_CACHE_DIR=str(ROOT / "var/hydraulic_runs"))
        args = [sys.executable, "-B", str(Path(__file__).resolve()), "--_child", "monsoon.verify",
                "--output", str(folder), "--workers", "3"]
        command = run_command(args, folder, "verification.log", verification_environment, "verification")
        result["commands"].append(command)
        require(command["returncode"] == 0, "SWMM and approval-gate verification failed")
        science = json.loads((folder / "verification.json").read_text(encoding="utf-8"))
        result["scientific_verification_status"] = science["status"]
        result["passed"] = science["status"] == "passed"
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        after = hashes()
        result["source_unchanged"] = before == after
        result["changed_sources"] = [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]
        result["runner_unchanged"] = digest(Path(__file__)) == freeze["runner_sha256"]
        result["reference_unchanged"] = digest(REFERENCE) == REFERENCE_SHA256
        result["passed"] = result["passed"] and result["source_unchanged"] and result["runner_unchanged"] and result["reference_unchanged"]
        result["completed_utc"] = datetime.now(timezone.utc).isoformat()
        result["artifact_sha256"] = {path.relative_to(folder).as_posix(): digest(path) for path in sorted(folder.rglob("*"))
                                     if path.is_file() and path != folder / "result.json"}
        save(folder / "result.json", result)
        print(json.dumps(result, indent=2, allow_nan=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--_child":
        require(__debug__, "Optimized child execution is forbidden")
        join_worker_job()
        module = sys.argv[2]
        require(module in {"collect", "pytest", "monsoon.verify"}, "Unsupported child module")
        sys.path.insert(0, str(ROOT))
        if module == "collect":
            raise SystemExit(collection_child(Path(sys.argv[3]), sys.argv[4:]))
        sys.argv = [module, *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__")
    else:
        raise SystemExit(main())
