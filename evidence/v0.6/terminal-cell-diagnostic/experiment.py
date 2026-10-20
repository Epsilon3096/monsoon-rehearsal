"""One predeclared, isolated terminal-cell diagnostic. No release modifications."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1] / "outputs" / "monsoon-rehearsal"
ORIGINAL = PROJECT / "evidence/v0.6/native-phase-review/primary/model.inp"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def now():
    return datetime.now(timezone.utc).isoformat()


def runtime():
    distribution = importlib.metadata.distribution("swmm-toolkit")
    names = [str(name) for name in distribution.files if str(name).endswith((".pyd", ".dll")) or
             str(name).replace("\\", "/") in {"swmm/toolkit/solver.py", "swmm/toolkit/shared_enum.py"}]
    return {"toolkit_version": distribution.version,
            "file_sha256": {name: sha(Path(distribution.locate_file(name))) for name in sorted(names)}}


def prepare():
    original = ORIGINAL.read_bytes()
    source_text = original.decode("utf-8")
    matrix = []
    for divisions in (1, 2, 4):
        folder = ROOT / f"segments-{divisions}"
        folder.mkdir(exist_ok=False)
        ids = ["S"] + [f"D{divisions}_{i}" for i in range(1, divisions)] + ["O"]
        links = ["L2"] if divisions == 1 else [f"L2_{i}" for i in range(1, divisions + 1)]
        junctions = [{"id": ids[i], "invert_m": .02 * (1 - i / divisions), "max_depth_m": .25,
                      "initial_depth_m": 0, "surcharge_depth_m": 0, "ponded_area_m2": 0,
                      "declared_physical_storage_m3": 0} for i in range(1, divisions)]
        if divisions == 1:
            payload = original
        else:
            section, lines = None, []
            for line in source_text.splitlines():
                if line.startswith("["):
                    section = line.strip()
                    if section == "[STORAGE]":
                        lines += ["[JUNCTIONS]"] + [f"{r['id']} {r['invert_m']:.12g} 0.25 0 0 0" for r in junctions]
                if line.split()[:1] == ["L2"]:
                    if section == "[CONDUITS]":
                        lines += [f"{links[i]} {ids[i]} {ids[i+1]} {0.8/divisions:.12g} 0.012 0 0 0 0" for i in range(divisions)]
                    elif section == "[XSECTIONS]":
                        lines += [f"{name} RECT_OPEN 0.25 0.08 0 0 1" for name in links]
                    elif section == "[LOSSES]":
                        lines += [f"{name} 0 0 0 NO 0" for name in links]
                    else:
                        raise ValueError("Unexpected original L2 row")
                else:
                    lines.append(line)
            payload = ("\n".join(lines) + "\n").encode("utf-8")
        (folder / "model.inp").write_bytes(payload)
        case = {"case_id": folder.name, "subdivisions": divisions, "node_ids": ["A", "S", "O"] + ids[1:-1],
                "link_ids": ["L1"] + links, "terminal_link_id": links[-1],
                "link_connections": {"L1": ["A", "S"], **{name: [ids[i], ids[i+1]] for i, name in enumerate(links)}},
                "new_junctions": junctions, "terminal_element_length_m": .8 / divisions,
                "terminal_half_cell_area_m2": .08 * .8 / (2 * divisions),
                "predicted_plateau_residual_m3": -.08 * .8 * .06 / (2 * divisions),
                "input_sha256": hashlib.sha256(payload).hexdigest()}
        save(folder / "case.json", case)
        matrix.append(case)
    freeze = json.loads((PROJECT / "evidence/v0.6/release-test-freeze.json").read_bytes())
    protected = {name: sha(PROJECT / name) for name in freeze["files"]}
    assert protected == freeze["files"], "Release files differ from its active freeze before diagnostic."
    identity = runtime()
    assert identity["toolkit_version"] == "0.17.0"
    protocol = {"schema_version": "monsoon.terminal-cell-diagnostic/1", "created_at": now(),
        "evidence_kind": "synthetic_diagnostic", "purpose": "One predeclared spatial-refinement family; hypothesis discrimination only.",
        "original_input": str(ORIGINAL), "original_input_sha256": sha(ORIGINAL), "matrix": matrix,
        "controls": {"total_terminal_channel_length_m": .8, "width_m": .08, "depth_m": .25,
                     "upstream_invert_m": .02, "outfall_invert_m": 0, "manning_n": .012,
                     "all_losses": 0, "routing_step_s": .01, "report_step_s": 1, "duration_s": 120,
                     "minimum_surface_area_literal": "1e-06", "head_tolerance_literal": "1e-06", "max_trials": 100,
                     "receiving_stage_knots": [[0,0],[20,.06],[50,.06],[90,0],[120,0]], "external_inflow": "identically zero",
                     "unchanged": "All original options, A/S storage, L1 geometry, forcing, reporting and losses; N=1 input bytes exact."},
        "discretization_changes": "N=2 and N=4 insert zero-physical-volume junctions, splitting the same bed profile and total reach length. Their additional nodal continuity equations and unchanged minimum numerical area floor can alter the numerical solution. No reservoir or physical storage is added; actual junction volumes and link-contributed areas are retained.",
        "native_output_limits": "Per-step flow classification is not exposed by this toolkit getter. Retain per-step link Froude/depth/end surface areas and the native report's aggregate flow-class statistics; do not invent exact per-step class labels.",
        "unaltered_numerical_criteria": {"every_endpoint_tolerance_m3": "max(1e-6,0.01*(initial_storage+gross_external_inflow+gross_receiving_backflow))", "warnings_or_internal_nonconvergence": "unresolved", "no_qualification_override": True},
        "predeclared_hypothesis_support_rule": {"baseline_R50_match_absolute_m3": 1e-9,
            "reference_R50_m3": -.0019144499220922406,
            "all_cases_complete_warning_free_and_nonconverged_count_zero": True,
            "each_R50_negative_and_within_relative_prediction": .05,
            "predictions_m3": [-.00192,-.00096,-.00048],
            "note": "5% is a predeclared mechanism-discrimination band, NEVER a conservation qualification tolerance. Each original acceptance budget remains unchanged and is separately reported. If cases fail these support conditions, report that result without retuning."},
        "no_retries": "Each of three cases executes once. All successes, errors and artifacts retained. No revised inputs, adjusted criteria or additional cases.",
        "runtime": identity, "release_file_sha256_before": protected,
        "diagnostic_source_sha256": {name: sha(ROOT / name) for name in ("experiment.py", "worker.py")},
        "physical_validation_established": False, "operational_activation_allowed": False}
    save(ROOT / "protocol.json", protocol)
    print(json.dumps({"status":"prepared_no_native_runs", "protocol_sha256":sha(ROOT/'protocol.json'),
                      "matrix":[{k:r[k] for k in ('case_id','input_sha256','predicted_plateau_residual_m3')} for r in matrix]},indent=2))


def execute():
    protocol = json.loads((ROOT / "protocol.json").read_bytes())
    assert runtime() == protocol["runtime"]
    assert all(sha(ROOT/name)==h for name,h in protocol["diagnostic_source_sha256"].items())
    assert all(sha(PROJECT/name)==h for name,h in protocol["release_file_sha256_before"].items())
    save(ROOT / "execution-start.json", {"started_at":now(),"protocol_sha256":sha(ROOT/'protocol.json')})
    summaries=[]
    for case in protocol["matrix"]:
        folder=ROOT/case["case_id"]
        assert sha(folder/'model.inp')==case['input_sha256']
        save(folder/'attempt-start.json',{'started_at':now(),'protocol_sha256':sha(ROOT/'protocol.json'),'case':case['case_id']})
        try:
            call=subprocess.run([sys.executable,str(ROOT/'worker.py'),str(folder)],capture_output=True,text=True,timeout=90,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            (folder/'worker.log').write_text(call.stdout+call.stderr,encoding='utf-8')
            entry=json.loads((folder/'result.json').read_bytes()) if (folder/'result.json').is_file() else {'status':'worker_failed','exit_code':call.returncode}
        except Exception as exc:
            entry={'status':'execution_failed','error':f'{type(exc).__name__}: {exc}'}
            (folder/'worker.log').write_text(str(entry),encoding='utf-8')
        summaries.append({'case_id':case['case_id'],**entry})
        print(json.dumps({'case_id':case['case_id'],'status':entry['status'],'R50_m3':entry.get('R50_m3'),'conservation_passed':entry.get('conservation_passed')}),flush=True)
    unchanged={name:sha(PROJECT/name)==h for name,h in protocol['release_file_sha256_before'].items()}
    support=(all(e.get('status')=='completed' and not e.get('warnings') and not any(e.get('nonconverged_count',{}).values()) for e in summaries)
             and abs(summaries[0].get('R50_m3',1)-protocol['predeclared_hypothesis_support_rule']['reference_R50_m3'])<=1e-9
             and all(e.get('R50_m3',1)<0 and abs(e['R50_m3']-case['predicted_plateau_residual_m3'])<=.05*abs(case['predicted_plateau_residual_m3']) for e,case in zip(summaries,protocol['matrix'])))
    result={'schema_version':'monsoon.terminal-cell-diagnostic-summary/1','finished_at':now(),'protocol_sha256':sha(ROOT/'protocol.json'),
            'predeclared_support_rule_met':support,'cases':summaries,'release_files_unchanged':all(unchanged.values()),
            'changed_release_files':[name for name,okay in unchanged.items() if not okay],
            'runtime_unchanged':runtime()==protocol['runtime'],'original_input_unchanged':sha(ORIGINAL)==protocol['original_input_sha256'],
            'interpretation':'Support for a candidate discrete boundary accounting mechanism is not physical validation or numerical qualification. All original rejection criteria remain unchanged.',
            'physical_validation_established':False,'operational_activation_allowed':False}
    save(ROOT/'summary.json',result)
    inventory={p.relative_to(ROOT).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in ROOT.rglob('*') if p.is_file()}
    save(ROOT/'manifest.json',{'files':inventory,'total_payload_bytes':sum(v['bytes'] for v in inventory.values()),'physical_validation_established':False})
    print(json.dumps({'predeclared_support_rule_met':support,'release_files_unchanged':result['release_files_unchanged'],'files':len(inventory)+1}),flush=True)


if __name__=='__main__':
    {'prepare':prepare,'execute':execute}[sys.argv[1]]()
