from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from monsoon.case import load_case, get_scenario, DATA
from monsoon.hydraulics import run_state, build_input, engine_info, hydrograph_points, verify_hydraulics


@pytest.fixture(scope="module")
def hydro_cache(tmp_path_factory):
    return tmp_path_factory.mktemp("real-swmm")


def test_frozen_case_and_engine():
    case=load_case()
    freeze=json.loads((DATA.parent/"case_freeze.json").read_text())
    assert case["case_sha256"] == freeze["case_sha256"]
    assert freeze["frozen_before_planner_comparison"]
    assert engine_info()["engine_version"] == "5.2.4"
    assert engine_info()["toolkit_version"] == "0.17.0"
    assert engine_info()==engine_info()
    assert {s["phase"] for s in case["scenarios"]} == {"planning","holdout","diagnostic"}


def test_four_distinct_reversible_geometry_changes():
    h=get_scenario("P1")["hydraulic"]
    baseline=build_input([],h).splitlines()
    case=load_case()
    changed=[]
    for job in case["jobs"]:
        variant=build_input([job["id"]],h).splitlines()
        difference=[(a,b) for a,b in zip(baseline,variant) if a!=b]
        assert len(difference)==1
        assert difference[0][0].split()[0] == job["asset_id"]
        assert difference[0][0].split()[1:3] == difference[0][1].split()[1:3]
        changed.append(job["asset_id"])
    assert len(set(changed))==4
    assert next(x for x in baseline if x.startswith("STORE_OUT CIRCULAR")) == next(x for x in build_input(["J4"],h).splitlines() if x.startswith("STORE_OUT CIRCULAR"))


def test_reference_conservation_and_units(hydro_cache):
    result=run_state([],get_scenario("P1"),hydro_cache)
    assert result["valid"],result["errors"]
    d=result["diagnostics"]
    assert abs(d["continuity_error_percent"])<1
    assert d["inflow_m3"] == pytest.approx(1620.,rel=1e-6)
    assert d["spill_m3"] == pytest.approx(sum(n["spill_m3"] for n in result["nodes"].values()),abs=1e-8)
    assert d["initial_storage_m3"]+d["inflow_m3"] == pytest.approx(d["outflow_m3"]+d["spill_m3"]+d["final_storage_m3"],rel=.001)
    assert d["horizon_minutes"]==180
    assert result["timeseries"][-1]["minutes"]==180
    for n in result["nodes"].values():
        assert n["spill_m3"] == pytest.approx(n["integrated_spill_m3"],abs=.001)
        assert 0 <= n["duration_above_threshold_min"] <= 180


def test_completion_equivalence_and_duration_independent_cache(hydro_cache):
    a=run_state(["J1","J3"],get_scenario("P1"),hydro_cache)
    scenario=get_scenario("P1")
    scenario["id"]="different-label-and-durations"
    scenario["durations"]={j:1 for j in ["J1","J2","J3","J4"]}
    b=run_state(["J3","J1","J3"],scenario,hydro_cache)
    assert a["valid"] and b["valid"]
    assert a["run_id"] == b["run_id"] and b["cache_hit"]
    assert a["total_spill_m3"] == b["total_spill_m3"]
    assert b["scenario_id"] == scenario["id"]
    assert b["completed_jobs"] == ["J1","J3"]


def test_repeated_uncached_runs_are_identical(hydro_cache):
    a=run_state(["J2"],get_scenario("P1"),hydro_cache)
    b=run_state(["J2"],get_scenario("P1"),hydro_cache,force=True)
    assert a["valid"] and b["valid"]
    assert not b["cache_hit"]
    assert a["files"]["input"] != b["files"]["input"]
    assert a["nodes"]==b["nodes"]
    assert a["diagnostics"]==b["diagnostics"]


def test_zero_inflow_produces_no_spill(hydro_cache):
    r=run_state([],get_scenario("D0"),hydro_cache)
    assert r["valid"],r["errors"]
    assert r["total_spill_m3"] == 0
    assert r["diagnostics"]["inflow_m3"]==0


def test_reverse_tailwater_is_water_source(hydro_cache):
    r=run_state([],get_scenario("D1"),hydro_cache)
    assert r["valid"],r["errors"]
    d=r["diagnostics"]
    assert d["prescribed_inflow_integral_m3"]==0
    assert d["min_link_flow_cms"]["OUTLET"] < -.01
    assert d["inflow_m3"] > 0
    assert d["boundary_inflow_approx_m3"] > 0
    assert abs(d["balance_residual_percent"])<1


def test_downstream_restoration_reduces_head_in_isolated_control(hydro_cache):
    a=run_state([],get_scenario("D2"),hydro_cache)
    b=run_state(["J1"],get_scenario("D2"),hydro_cache)
    assert a["valid"] and b["valid"]
    assert b["nodes"]["J"]["max_depth_m"] < a["nodes"]["J"]["max_depth_m"]
    assert b["total_spill_m3"] <= a["total_spill_m3"]+.05


@pytest.mark.parametrize("family,area",[("triangle",22.5),("double",32.5),("plateau",45)])
def test_prescribed_hydrograph_integrals(family,area,hydro_cache):
    points=hydrograph_points(family,1.)
    assert sum((b[0]-a[0])*(a[1]+b[1])/2 for a,b in zip(points,points[1:])) == pytest.approx(area)
    scenario=get_scenario("P1")
    scenario["hydraulic"]["hydrograph"]=family
    r=run_state([],scenario,hydro_cache)
    assert r["valid"],r["errors"]
    assert r["diagnostics"]["inflow_m3"] == pytest.approx(area*60*1.2,rel=1e-5)


@pytest.mark.parametrize("change",[{"peak_a_cms":-1},{"initial_storage_depth_m":3},{"peak_b_cms":float("nan")},{"unknown_field":1},{"hydrograph":"unknown"}])
def test_invalid_inputs_have_no_score(change,hydro_cache):
    s=get_scenario("P1")
    s["hydraulic"].update(change)
    r=run_state([],s,hydro_cache)
    assert not r["valid"] and r["status"]=="invalid"
    assert r["total_spill_m3"] is None and r["errors"]


def test_corrupt_cache_is_never_trusted(hydro_cache):
    a=run_state(["J2","J3"],get_scenario("P1"),hydro_cache)
    p=Path(a["files"]["output"])
    p.write_bytes(b"corrupt binary file")
    b=run_state(["J2","J3"],get_scenario("P1"),hydro_cache)
    assert b["valid"] and not b["cache_hit"]
    assert b["files"]["output"] != a["files"]["output"]
    assert b["total_spill_m3"]==a["total_spill_m3"]


def test_direct_engine_matches_step_adapter(hydro_cache,tmp_path):
    from swmm.toolkit import output
    from swmm.toolkit.shared_enum import Time,NodeAttribute
    r=run_state([],get_scenario("P1"),hydro_cache)
    direct=tmp_path/"direct"
    code="from swmm.toolkit import solver; import sys; solver.swmm_run(sys.argv[1],sys.argv[2],sys.argv[3])"
    subprocess.run([sys.executable,"-c",code,r["files"]["input"],str(direct.with_suffix(".rpt")),str(direct.with_suffix(".out"))],check=True,capture_output=True)
    h1,h2=output.init(),output.init()
    try:
        output.open(h1,r["files"]["output"])
        output.open(h2,str(direct.with_suffix(".out")))
        periods=output.get_times(h1,Time.NUM_PERIODS)
        assert periods==180 and output.get_times(h2,Time.NUM_PERIODS)==periods
        for ni in range(8):
            for attribute in [NodeAttribute.INVERT_DEPTH,NodeAttribute.FLOODING_LOSSES]:
                a=output.get_node_series(h1,ni,attribute,0,periods-1)
                b=output.get_node_series(h2,ni,attribute,0,periods-1)
                assert a==pytest.approx(b,abs=1e-9)
    finally:
        output.close(h1)
        output.close(h2)


def test_all_frozen_states_conserve_and_converge_when_step_halved(hydro_cache):
    report=verify_hydraulics(hydro_cache,all_states=True,workers=4)
    assert report["engine_runs"]==288
    assert report["status"]=="passed",json.dumps(report["failures"],indent=2)
