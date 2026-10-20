"""Private one-shot diagnostic worker; this never qualifies a release prediction."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import traceback

from swmm.toolkit import solver
from swmm.toolkit.shared_enum import LinkResult, NodeResult


def signed_integral(q0,q1,dt):
    if q0*q1>=0:
        value=(q0+q1)*dt/2
        return max(value,0),max(-value,0)
    fraction=abs(q0)/(abs(q0)+abs(q1))
    first=q0*dt*fraction/2
    second=q1*dt*(1-fraction)/2
    return max(first,0)+max(second,0),max(-first,0)+max(-second,0)


def run(folder):
    case=json.loads((folder/'case.json').read_bytes())
    protocol=json.loads((folder.parent/'protocol.json').read_bytes())
    assert case==next(row for row in protocol['matrix'] if row['case_id']==folder.name)
    assert hashlib.sha256((folder/'model.inp').read_bytes()).hexdigest()==case['input_sha256']
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==protocol['diagnostic_source_sha256']['worker.py']
    opened=started=False
    result={'status':'failed','physical_validation_established':False,'operational_activation_allowed':False}
    try:
        assert solver.swmm_get_version()==52004
        solver.swmm_open(str(folder/'model.inp'),str(folder/'model.rpt'),str(folder/'model.out'))
        opened=True
        solver.swmm_start(True)
        started=True
        ni={name:solver.project_get_index(solver.swmm_NODE,name) for name in case['node_ids']}
        li={name:solver.project_get_index(solver.swmm_LINK,name) for name in case['link_ids']}
        added=[row['id'] for row in case['new_junctions']]
        internal=[name for name in ni if name!='O']
        fields={'stage_m':NodeResult.HEAD,'depth_m':NodeResult.DEPTH,'storage_m3':NodeResult.VOLUME,
                'inflow_m3_s':NodeResult.TOTAL_INFLOW,'outflow_m3_s':NodeResult.TOTAL_OUTFLOW,
                'lateral_m3_s':NodeResult.LATERAL_INFLOW,'spill_m3_s':NodeResult.FLOOD}
        linkfields={'flow_m3_s':LinkResult.FLOW,'depth_m':LinkResult.DEPTH,'storage_m3':LinkResult.VOLUME,
                    'us_surface_area_m2':LinkResult.US_SURFACE_AREA,'ds_surface_area_m2':LinkResult.DS_SURFACE_AREA,
                    'froude':LinkResult.FROUDE}
        def state(t):
            nodes={name:{key:solver.node_get_result(index,value.value) for key,value in fields.items()} for name,index in ni.items()}
            links={name:{key:solver.link_get_result(index,value.value) for key,value in linkfields.items()} for name,index in li.items()}
            native=solver.system_get_routing_totals()
            raw={key:getattr(native,key) for key in ('exInflow','outflow','flooding','initStorage','finalStorage','pctError')}
            outgoing=nodes['O']['outflow_m3_s']
            return {'elapsed_s':t,'nodes':nodes,'links':links,'storage_m3':sum(row['storage_m3'] for row in nodes.values())+sum(row['storage_m3'] for row in links.values()),
                    'outfall_signed_flow_m3_s':-outgoing if outgoing>0 else nodes['O']['inflow_m3_s'],
                    'external_inflow_m3_s':sum(nodes[n]['lateral_m3_s'] for n in internal),
                    'spill_m3_s':sum(nodes[n]['spill_m3_s'] for n in internal),'raw_native':raw}
        initial=previous=state(0.0)
        entering=backflow=discharge=spill=0.0
        steps=0
        violations=0
        maxclock=maxmapping=maxagreement=0.0
        max_added_storage={name:0.0 for name in added}
        numerical_floor_count={name:0 for name in added}
        samples=[]
        worst=None
        def annotate(row):
            nonlocal violations,worst,maxmapping,maxagreement
            native=row['raw_native']
            residual=initial['storage_m3']+entering+backflow-discharge-spill-row['storage_m3']
            native_residual=native['initStorage']*.02832+native['exInflow']-native['outflow']-native['flooding']-row['storage_m3']
            tolerance=max(1e-6,.01*(initial['storage_m3']+entering+backflow))
            ratio=max(abs(residual),abs(native_residual))/tolerance
            if ratio>1:violations+=1
            if worst is None or ratio>worst['ratio']:
                worst={'elapsed_s':row['elapsed_s'],'residual_m3':residual,'native_residual_m3':native_residual,'tolerance_m3':tolerance,'ratio':ratio}
            row.update(residual_m3=residual,native_residual_m3=native_residual,tolerance_m3=tolerance,
                       cumulative_external_inflow_m3=entering,cumulative_backflow_m3=backflow,cumulative_discharge_m3=discharge,
                       cumulative_spill_m3=spill,diagnostic_boundary_half_cell_change_m3=case['terminal_half_cell_area_m2']*(row['nodes']['O']['stage_m']-initial['nodes']['O']['stage_m']))
            row['diagnostic_residual_plus_half_cell_m3']=residual+row['diagnostic_boundary_half_cell_change_m3']
            maxmapping=max(maxmapping,abs(native['finalStorage']*.02832-row['storage_m3']))
            maxagreement=max(maxagreement,abs(native_residual-residual))
            for node in added:
                max_added_storage[node]=max(max_added_storage[node],row['nodes'][node]['storage_m3'])
                surface=sum(row['links'][link]['us_surface_area_m2' if connection[0]==node else 'ds_surface_area_m2'] for link,connection in case['link_connections'].items() if node in connection)
                if surface<1e-6:numerical_floor_count[node]+=1
            if any(abs(row['elapsed_s']-stamp)<1e-7 for stamp in (0,20,49.99,50,50.01,90,120)):
                samples.append(row.copy())
            return row
        with gzip.open(folder/'routing-trace.jsonl.gz','wt',encoding='utf-8',newline='\n') as trace:
            trace.write(json.dumps(annotate(initial),allow_nan=False)+'\n')
            while True:
                days=solver.swmm_step()
                steps+=1
                t=days*86400 if days>0 else 120.0
                dt=t-previous['elapsed_s']
                maxclock=max(maxclock,abs(t-steps*.01))
                assert abs(dt-.01)<1e-6 and steps<=12000 and t<=120+1e-6
                row=state(t)
                entering+=dt*(previous['external_inflow_m3_s']+row['external_inflow_m3_s'])/2
                spill+=dt*(previous['spill_m3_s']+row['spill_m3_s'])/2
                plus,minus=signed_integral(previous['outfall_signed_flow_m3_s'],row['outfall_signed_flow_m3_s'],dt)
                discharge+=plus
                backflow+=minus
                trace.write(json.dumps(annotate(row),allow_nan=False)+'\n')
                previous=row
                if days<=0:break
        nonconverged={name:solver.node_get_stats(ni[name]).nonConvergedCount for name in internal}
        solver.swmm_end()
        started=False
        solver.swmm_report()
        solver.swmm_close()
        opened=False
        warnings=[line.strip() for line in (folder/'model.rpt').read_text(errors='replace').splitlines() if 'WARNING' in line or 'ERROR' in line]
        at50=next(row for row in samples if abs(row['elapsed_s']-50)<1e-7)
        result.update(status='completed',routing_steps=steps,checked_endpoints=steps+1,R50_m3=at50['residual_m3'],
                      predicted_R50_m3=case['predicted_plateau_residual_m3'],
                      R50_prediction_relative_error=(at50['residual_m3']-case['predicted_plateau_residual_m3'])/abs(case['predicted_plateau_residual_m3']),
                      conservation_passed=not violations and not warnings and not any(nonconverged.values()),
                      violating_endpoints=violations,worst_balance=worst,maximum_clock_difference_s=maxclock,
                      maximum_native_live_storage_difference_m3=maxmapping,maximum_independent_native_residual_difference_m3=maxagreement,
                      nonconverged_count=nonconverged,warnings=warnings,max_added_junction_storage_m3=max_added_storage,
                      added_junction_minimum_area_floor_endpoint_counts=numerical_floor_count,
                      initial_storage_m3=initial['storage_m3'],final_storage_m3=previous['storage_m3'],
                      final_residual_m3=previous['residual_m3'],samples=samples,
                      per_step_flow_classification='Not exposed by toolkit; native report aggregates retained, with live end areas/depth/Froude in trace.')
    except BaseException as exc:
        result.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    finally:
        if started:
            try:solver.swmm_end()
            except Exception:pass
        if opened:
            try:solver.swmm_close()
            except Exception:pass
    with (folder/'result.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')


if __name__=='__main__':
    run(Path(sys.argv[1]))
