"""Run one frozen C-special work package in its explicit bounded window."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('package',choices=['A','B1','B2'])
    parser.add_argument('output',type=Path);args=parser.parse_args();out=args.output.resolve()
    plan=json.loads((out/'execution-plan.json').read_text());stage=args.package
    if stage=='B2':
        previous=json.loads((out/'B1/diagnostic.json').read_text())
        q=previous['r_over_g']
        if q is None or not .139<q<=1.39:raise ValueError('ALTERNATE_GATE_CLOSED')
        if not (out/'B1/FINAL.json').exists():raise ValueError('FIRST_PROPOSAL_INCOMPLETE')
    dest=out/stage;dest.mkdir(exist_ok=True)
    if (dest/'STARTED.json').exists():raise ValueError('NO_HIDDEN_RETRY_OR_LEDGER_RESET')
    source=Path(__file__).resolve().parents[2]
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if head!=plan['source_commit'] or subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip():
        raise ValueError('FROZEN_CLEAN_SOURCE_REQUIRED')
    for entry in plan['inputs'].values():
        if sha(Path(plan['input_root'])/entry['path'])!=entry['sha256']:raise ValueError('INPUT_HASH_CHANGED')
    for entry in plan['raw_inputs'].values():
        if sha(Path(plan['input_root'])/entry['path'])!=entry['sha256']:raise ValueError('RAW_SOURCE_CHANGED')
    cap=256*1024**2 if stage=='A' else 2*1024**3;seconds=60 if stage=='A' else 900
    available=int(next(row.split()[1] for row in Path('/proc/meminfo').read_text().splitlines() if row.startswith('MemAvailable:')))*1024
    if cap>available//2:raise ValueError('MEMORY_PREFLIGHT_REJECTED')
    if stage!='A' and plan['B']['estimated_peak_bytes']>cap:raise ValueError('SIZE_ESTIMATE_REJECTED')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024**2,128*1024**2));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    signal.alarm(seconds);start=time.monotonic()
    dump(dest/'STARTED.json',{'stage':stage,'plan_sha256':sha(out/'execution-plan.json'),'source_commit':head,
                             'memory_cap_bytes':cap,'wall_cap_seconds':seconds,'started_epoch':time.time()})
    try:
        if stage=='A':
            from fractions import Fraction as F
            from .fixed_s_rank_one import verify
            from .projector_budget import bound
            from .selector_cone_bounds import conditional_cone_bounds
            from .selector_observable_bounds import sqrt_bounds
            result=verify(plan['input_root'],plan['inputs'])
            result['projector_budget']=bound()
            old=json.loads((Path(plan['input_root'])/plan['diagnostic_input']).read_text())['rows'][0]
            model=json.loads((Path(plan['input_root'])/plan['inputs']['model']['path']).read_text())
            regions=[[[value if i==j else 0 for j in range(3)] for i in range(3)] for value in (model['top_epsilon'],model['bottom_epsilon'])]
            regions.append(model['materials']['0.775']['laboratory_epsilon'])
            mean=F(old['mean_epsilon'])
            result['saved_float_inputs_conditional_only']=conditional_cone_bounds(
                [old['unweighted_Ex_fraction']]*2,[old['core_energy_fraction']]*2,[old['outer_energy_fraction']]*2,
                F(1,5),sqrt_bounds(mean)[1],epsilon_regions=regions,mean_epsilon=[mean]*2)
            dump(dest/'fixed-s-rank-one.json',result)
            counts={'new_space_assemblies':0,'spectral_proposals':0,'paid_calls':0}
        else:
            import numpy as np
            from fractions import Fraction as F
            from .shared_trace_proposal import mesh,calibrate,raw_field_interpolator,interpolate,minimize,diagnose
            model=json.loads((Path(plan['input_root'])/plan['inputs']['model']['path']).read_text());data=mesh(model,20)
            calibration=calibrate(data,model);dump(dest/'calibration.json',calibration)
            if calibration['complex_dofs']!=179200:raise ValueError('UNEXPECTED_SPACE_DIMENSION')
            if stage=='B1':
                field,mapping=raw_field_interpolator(Path(plan['input_root'])/plan['raw_inputs']['band3']['path'])
                anchor=interpolate(data,field);dump(dest/'raw-to-dof-mapping.json',mapping)
            else:
                with np.load(out/'B1/proposal.npz',allow_pickle=False) as z:anchor=z['coefficients'].copy()
                dump(dest/'raw-to-dof-mapping.json',{'alternate':'one further global residual correction in same k1/P2 space',
                     'source_proposal_sha256':sha(out/'B1/proposal.npz'),'not_higher_order_or_new_grid':True})
            np.savez_compressed(dest/'anchor-and-topology.npz',anchor=anchor,**data)
            def logger(value):print(json.dumps(value),flush=True)
            coeff,history,normalized_anchor=minimize(data,float(F(209,100)/F(.775)),anchor,
                max_outer=3,max_iterations=600,seconds=plan['B']['internal_solver_seconds'],logger=logger)
            np.savez_compressed(dest/'proposal.npz',coefficients=coeff,normalized_anchor=normalized_anchor)
            dump(dest/'krylov-history.json',history)
            diagnostic=diagnose(data,float(F(209,100)/F(.775)),coeff,model)
            dump(dest/'diagnostic.json',diagnostic);print(json.dumps(diagnostic),flush=True)
            q=diagnostic['r_over_g'];e=diagnostic['electric_norm']
            strict_eligible=q is not None and q<=.139 and e>=.7 and diagnostic['mass']>0
            if strict_eligible:
                status='FLOATING_GATE_PASSED_STRICT_INTEGRATION_REQUIRED'
            elif q is None or q>1.39:
                status='STOP_FIRST_PROPOSAL_OUTSIDE_TENFOLD_TARGET'
            else:status='FIELD_ERROR_UNCERTIFIED'
            dump(dest/'gate.json',{'status':status,'eligible_for_strict_integration':strict_eligible,
                 'C_may_start':False,'r_over_g_target':.139,'tenfold_stop':1.39,
                 'all_iterations_converged':all(row['cg_info']==0 for row in history),
                 'not_a_proof_of_space_impossibility':True})
            counts={'finite_dimensional_field_proposals':1,'floating_final_residual_integrations':1,
                'strict_local_integrations':0,'optimization_local_M_N_G_form_passes':1,
                'outer_iterations':len(history),'krylov_iterations':sum(row['iterations'] for row in history),
                'paid_calls':0,'MPB_calls':0,'Meep_calls':0}
        size=sum(p.stat().st_size for p in dest.rglob('*') if p.is_file())
        if size>128*1024**2:raise ValueError('PERSISTENT_OUTPUT_CAP')
        dump(dest/'FINAL.json',{'status':'PACKAGE_EXECUTION_FINISHED','counts':counts,'seconds':time.monotonic()-start,
             'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'output_bytes':size,'source_commit':head})
    except Exception as exc:
        dump(dest/'FAILED.json',{'type':type(exc).__name__,'message':str(exc),'seconds':time.monotonic()-start,
                               'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        raise


if __name__=='__main__':main()
