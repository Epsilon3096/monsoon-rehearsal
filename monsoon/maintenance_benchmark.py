"""Separate, prospectively declared synthetic outlet-restoration benchmark.

Uses the unchanged reference SWMM builder/worker with an explicit separate case.
Never supplies audit evidence to the live reference planner or ticket service.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from .hydraulics import build_input, engine_info
from .planning import replay

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'data/benchmarks/outlet_restoration_v1.json'
SOURCE_FILES = ('monsoon/maintenance_benchmark.py', 'monsoon/hydraulics.py',
                'monsoon/_swmm_worker.py', 'monsoon/planning.py')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')

def capacity(width, depth=1.0, slope=.02, roughness=.02):
    """Manning uniform-flow capacity screening, not a dynamic-wave prediction."""
    area=width*depth
    return area*(area/(width+2*depth))**(2/3)*math.sqrt(slope)/roughness

def compare_pair(baseline, restored, nodes):
    """Require all six runs and unchanged numerical/location checks."""
    errors=[]
    for label, runs in [('baseline',baseline),('restored',restored)]:
        if len(runs)!=3:
            errors.append(f'{label}: three numerical configurations required')
            continue
        for run in runs:
            if run.get('valid') is not True or run.get('status')!='succeeded':
                errors.append(f'{label}: invalid native engine result: {run.get("errors", [])}')
        for node in nodes+['total']:
            try:
                v=[r['total_spill_m3'] if node=='total' else r['nodes'][node]['spill_m3'] for r in runs]
                if any(type(x) not in (float,int) or not math.isfinite(x) or x<0 for x in v):
                    raise ValueError('nonfinite, negative or missing spill')
                if abs(v[0]-v[1])>max(.05,.02*max(v[0],v[1])):
                    errors.append(f'{label}/{node}: routing-step disagreement')
                if abs(v[0]-v[2])>.05:
                    errors.append(f'{label}/{node}: event-horizon disagreement')
            except (KeyError,TypeError,ValueError):
                errors.append(f'{label}/{node}: missing or invalid numerical evidence')
    if errors:
        return {'status':'unresolved','errors':errors,'rows':[], 'approval_allowed':False}
    rows=[]
    for node in nodes:
        changes=[restored[i]['nodes'][node]['spill_m3']-baseline[i]['nodes'][node]['spill_m3'] for i in range(3)]
        rows.append({'node':node,'baseline_m3':baseline[0]['nodes'][node]['spill_m3'],
                     'restored_m3':restored[0]['nodes'][node]['spill_m3'],
                     'change_m3':changes[0],'half_step_change_m3':changes[1],
                     'extended_change_m3':changes[2],'limit_m3':.05,
                     'within_limit':all(d<=.05 for d in changes)})
    benefit=baseline[0]['total_spill_m3']-restored[0]['total_spill_m3']
    return {'status':'passed' if all(r['within_limit'] for r in rows) else 'failed',
            'errors':[], 'rows':rows, 'baseline_total_m3':baseline[0]['total_spill_m3'],
            'restored_total_m3':restored[0]['total_spill_m3'],'reduction_m3':benefit,
            'positive_mechanism':benefit>1 and all(r['within_limit'] for r in rows),
            'approval_allowed':False}

def execute(output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)  # retain every attempt, including failures
    protocol=json.loads(PROTOCOL.read_text(encoding='utf-8'))
    sources={p:digest(ROOT/p) for p in SOURCE_FILES}
    info=engine_info()
    freeze={'created_utc':datetime.now(timezone.utc).isoformat(),
            'protocol_sha256':digest(PROTOCOL),'source_sha256':sources,'engine':info,
            'claim':'Synthetic mechanism benchmark only; not operator validation, dispatch authority or optimizer superiority.'}
    dump(output/'freeze.json',freeze)
    dump(output/'protocol.json',protocol)
    case=protocol['case']
    manifest={}
    comparisons=[]
    settings=[(.5,180),(.25,180),(.5,360)]
    for scenario in protocol['scenarios']:
        by_state={}
        for restored in [False,True]:
            runs=[]
            for step,horizon in settings:
                name=f'{scenario["id"]}-{"restored" if restored else "blocked"}-{step}-{horizon}'
                folder=output/name; folder.mkdir()
                completed=['M1'] if restored else []
                inp=build_input(completed,scenario['hydraulic'],step,horizon,_case=case)
                (folder/'model.inp').write_text(inp,encoding='utf-8',newline='\n')
                request={'run_id':hashlib.sha256(inp.encode()).hexdigest(),'completed_jobs':completed,
                         'case':case,'hydraulic':scenario['hydraulic'],'engine':info,
                         'routing_step':step,'horizon_minutes':horizon}
                dump(folder/'request.json',request)
                proc=subprocess.run([sys.executable,str(ROOT/'monsoon/_swmm_worker.py'),str(folder)],
                                    capture_output=True,text=True,timeout=180)
                (folder/'worker.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
                if not (folder/'result.json').exists():
                    dump(folder/'result.json',{'valid':False,'status':'failed','errors':['Worker produced no result']})
                result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
                if proc.returncode:
                    result.update(valid=False,status='failed')
                runs.append(result)
                for file in folder.iterdir():
                    if file.is_file(): manifest[file.relative_to(output).as_posix()]=digest(file)
                print(name,result['status'],flush=True)
            by_state['restored' if restored else 'baseline']=runs
        compared=compare_pair(by_state['baseline'],by_state['restored'],[n['id'] for n in case['nodes']])
        comparisons.append({'id':scenario['id'],'title':scenario['title'],'purpose':scenario['purpose'],**compared})
    timings={str(limit):replay(['M1'],case['jobs'],limit,10,{'M1':35}) for limit in [120,50]}
    primary=[c for c in comparisons if c['purpose']=='declared_positive_mechanism']
    zero=next(c for c in comparisons if c['id']=='C_ZERO')
    null_ok=zero['status']=='passed' and abs(zero.get('baseline_total_m3',1))<=.05 and abs(zero.get('restored_total_m3',1))<=.05
    result={'protocol_sha256':digest(PROTOCOL),'source_sha256':sources,'comparisons':comparisons,
            'primary_mechanism_supported':all(c.get('positive_mechanism') and c['status']=='passed' for c in primary),
            'null_control_passed':null_ok,'timing':timings,
            'late_work_skipped':timings['50']['completed_jobs']==[],
            'baseline_comparison':'With one job, downstream-first and the candidate choose the identical action. No optimizer advantage.',
            'physical_validation_established':False,'operator_validation_established':False,
            'approval_allowed':False,'dispatch_allowed':False,
            'scope':'A separate synthetic mechanism benchmark. Original reference audit failures remain unchanged.'}
    dump(output/'results.json',result)
    for name in ['results.json','freeze.json','protocol.json']: manifest[name]=digest(output/name)
    dump(output/'manifest.json',{'files':manifest,'source_sha256':sources,'protocol_sha256':digest(PROTOCOL)})
    return result

def load_results(folder, expected_manifest_sha256):
    """Fail closed for missing, changed or path-escaping evidence, including raw outputs."""
    folder=Path(folder).resolve()
    try:
        if digest(folder/'manifest.json')!=expected_manifest_sha256: raise ValueError('Manifest changed')
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if manifest['protocol_sha256']!=digest(PROTOCOL): raise ValueError('Protocol changed')
        for name,h in manifest['source_sha256'].items():
            if name not in SOURCE_FILES or digest(ROOT/name)!=h: raise ValueError('Benchmark source changed')
        if set(manifest['source_sha256'])!=set(SOURCE_FILES): raise ValueError('Incomplete source binding')
        if not {'results.json','freeze.json','protocol.json'}<=manifest['files'].keys(): raise ValueError('Incomplete record')
        for name,h in manifest['files'].items():
            p=(folder/name).resolve()
            if not p.is_relative_to(folder) or digest(p)!=h: raise ValueError(f'Evidence missing or changed: {name}')
        result=json.loads((folder/'results.json').read_text(encoding='utf-8'))
        if result.get('approval_allowed') is not False or result.get('dispatch_allowed') is not False:
            raise ValueError('Benchmark cannot grant workflow authority')
        return {'status':'verified','result':result}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'status':'unavailable','errors':[str(exc)]}

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    args=parser.parse_args(); result=execute(args.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('comparisons','source_sha256','timing')},indent=2))
