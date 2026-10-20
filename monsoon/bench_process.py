"""Bounded private workers, including Windows virtual-environment descendants.

The Windows worker joins a named kill-on-close job before numerical imports.
This closes the race where a venv launcher starts its real interpreter before
the parent can associate it with a job. No job handle is inherited or retained
by the worker. POSIX uses a separate process group. No unrelated process is
enumerated, signalled or terminated.
"""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import uuid

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


def run_bounded_worker(command, *, cwd, timeout, log_path):
    """Run only a cooperating private worker and reap its whole process family."""
    environment=dict(os.environ)
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
