from copy import deepcopy

import pytest

from monsoon import assurance_hydraulics as numerical


def fake_runs(monkeypatch, *, half=None, extended=None):
    template = {"valid":True,"status":"succeeded","run_id":"base","engine_version":"test", "nodes":{"A":{"spill_m3":1.0},"O":{"spill_m3":0.0}},"total_spill_m3":1.0,"files":{}}
    runs = [deepcopy(template) for _ in range(3)]
    runs[1]["run_id"]="half"
    runs[2]["run_id"]="extended"
    if half: half(runs[1])
    if extended: extended(runs[2])
    calls=[]
    def run(*args,**kwargs):
        calls.append(kwargs)
        return runs[len(calls)-1]
    monkeypatch.setattr(numerical,"run_state",run)
    monkeypatch.setattr(numerical,"load_case",lambda:{"nodes":[{"id":"A"},{"id":"O"}]})
    return calls,runs


def test_checks_keep_original_output_and_all_raw_references(monkeypatch,tmp_path):
    calls,runs=fake_runs(monkeypatch)
    result=numerical.checked_state([],{},tmp_path)
    assert result["valid"] is True
    assert result["assurance_numerics"]["valid"] is True
    assert [c["horizon_minutes"] for c in calls] == [180,180,360]
    assert [c["routing_step"] for c in calls] == [.5,.25,.5]
    assert result["assurance_numerics"]["half_step_run_id"] == "half"
    assert "assurance_numerics" not in runs[0]


@pytest.mark.parametrize("mutation",[
    lambda r:r["nodes"]["A"].update(spill_m3=1.2),
    lambda r:r["nodes"].pop("O"),
    lambda r:r["nodes"]["A"].update(spill_m3=float("nan")),
    lambda r:r.update(valid=False),
    lambda r:r.update(engine_version="different"),
    lambda r:r.update(total_spill_m3=2),
])
def test_unresolved_halving_cannot_become_passing_evidence(monkeypatch,tmp_path,mutation):
    fake_runs(monkeypatch,half=mutation)
    result=numerical.checked_state([],{},tmp_path)
    assert result["valid"] is True  # Base run is not silently rewritten.
    assert result["assurance_numerics"]["valid"] is False
    assert result["assurance_numerics"]["errors"]


def test_late_spill_prevents_pass_even_when_step_converges(monkeypatch,tmp_path):
    fake_runs(monkeypatch,extended=lambda r:r["nodes"]["O"].update(spill_m3=.06))
    result=numerical.checked_state([],{},tmp_path)
    assert not result["assurance_numerics"]["valid"]
    assert "360 minutes" in result["assurance_numerics"]["errors"][0]
