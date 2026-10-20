"""Private bounded-process entry point for the separate FV bench engine."""
from __future__ import annotations
import gzip
import json
from pathlib import Path
import sys
import warnings

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from monsoon.bench_process import join_worker_job
join_worker_job()
from monsoon.bench_conservative import conservative_identity
from monsoon.bench_fv import simulate
from monsoon.site_data import canonical_json, content_sha256, parse_json


def main():
    folder = Path(sys.argv[1]).resolve()
    request = parse_json((folder / "request.json").read_bytes())
    identity = conservative_identity()
    if identity != request["engine_identity"]:
        raise ValueError("Parent and worker source/runtime differ.")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = simulate(request["network"], **request["settings"], split_times=request["split_times"])
    if caught:
        result.update(valid=False,status="numerical_warning")
        for warning in caught:
            message=f"{warning.category.__name__}: {warning.message}"
            print(message)
            result.setdefault("errors",[]).append({"code":"numerical_warning","message":message})
    trace = result.pop("routing_trace",[])
    with (folder / "routing.jsonl.gz").open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as compressed:
            for row in trace:
                compressed.write((json.dumps(row,sort_keys=True,allow_nan=False,separators=(",",":"))+"\n").encode("utf-8"))
    result.update(engine_identity=identity,request_sha256=content_sha256(request))
    (folder / "worker-result.json").write_text(canonical_json(result)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
