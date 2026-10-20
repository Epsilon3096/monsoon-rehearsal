"""Actual bounded-process cleanup, including a spawned descendant."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from monsoon.bench_process import run_bounded_worker


def alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL("kernel32",use_last_error=True)
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        api.OpenProcess.restype=wintypes.HANDLE
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        api.WaitForSingleObject.restype=wintypes.DWORD
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenProcess(0x00100000,False,pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle,0)==258
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False


def script(tmp_path,body):
    path=tmp_path/"private-worker.py"
    root=Path(__file__).resolve().parents[1]
    path.write_text("import sys\nsys.path.insert(0,"+repr(str(root))+")\nfrom monsoon.bench_process import join_worker_job\njoin_worker_job()\n"+body,encoding="utf-8")
    return path


def test_private_worker_success_retains_log(tmp_path):
    program=script(tmp_path,"print('contained worker completed')\n")
    code=run_bounded_worker([sys.executable,str(program)],cwd=tmp_path,timeout=10,log_path=tmp_path/"worker.log")
    assert code==0
    assert "contained worker completed" in (tmp_path/"worker.log").read_text()


def test_timeout_terminates_actual_descendant_and_reaps_launcher(tmp_path):
    program=script(tmp_path,"import subprocess,os,time,json\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,'-c',\"import os,time; from pathlib import Path; Path('actual-child-pid.txt').write_text(str(os.getpid())); time.sleep(60)\"])\nPath('pids.json').write_text(json.dumps([os.getpid(),child.pid]))\nprint('descendant started',flush=True)\ntime.sleep(60)\n")
    start=time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_worker([sys.executable,str(program)],cwd=tmp_path,timeout=1.5,log_path=tmp_path/"worker.log")
    assert time.monotonic()-start<12
    pids=json.loads((tmp_path/"pids.json").read_text())
    pids.append(int((tmp_path/"actual-child-pid.txt").read_text()))
    for _ in range(20):
        if not any(alive(pid) for pid in pids):
            break
        time.sleep(.05)
    assert not any(alive(pid) for pid in pids),pids
    assert "descendant started" in (tmp_path/"worker.log").read_text()


@pytest.mark.skipif(os.name != "nt",reason="Windows named-job fail-closed check")
def test_standalone_worker_cannot_compute_without_its_parent_job(tmp_path,monkeypatch):
    monkeypatch.delenv("MONSOON_PRIVATE_BENCH_JOB",raising=False)
    program=script(tmp_path,"raise AssertionError('computation must not start')\n")
    result=subprocess.run([sys.executable,str(program)],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0
    assert "requires its parent's private process job" in result.stderr
    assert "computation must not start" not in result.stderr
