"""Bounded one-shot common field correction and two endpoint integrations."""
import hashlib,json,resource,signal,subprocess,sys,time
from pathlib import Path
from fractions import Fraction as F


def main():
    out=Path(sys.argv[1]);plan=json.loads((out/'execution-plan.json').read_text())
    stage=json.loads((out/'center-stage-plan.json').read_text());dest=out/'CENTER';dest.mkdir(exist_ok=True)
    if (dest/'STARTED.json').exists():raise ValueError('NO_CENTER_REPLAY')
    source=Path(__file__).resolve().parents[2]
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if head!=stage['source_commit'] or subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip():raise ValueError('FROZEN_CLEAN_SOURCE')
    for entry in {**plan['inputs'],**stage['inputs']}.values():
        with Path(entry['path']).open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=entry['sha256']:raise ValueError('HASH_BINDING')
    if not json.loads(Path(plan['inputs']['B_certificate']['path']).read_text())['C_entry_allowed']:raise ValueError('B_ENTRY')
    for index,count in enumerate((2,3),1):
        upper=json.loads((out/('upper-'+str(index))/'result.json').read_text())
        if upper['upper_count']!=count or upper['M']!=8 or F(upper['s_exact'])!=F(plan['center_s_exact']):raise ValueError('CENTER_UPPER_COUNTS')
    lower=json.loads((out/'center-lower-counts.json').read_text())
    if any(min(r.get('row_margin_float',[0]))<=0 for r in lower['results']):raise ValueError('CENTER_LOWER_COUNTS')
    cap=2*1024**3;available=int(next(r.split()[1] for r in Path('/proc/meminfo').read_text().splitlines() if r.startswith('MemAvailable:')))*1024
    if cap>available//2:raise ValueError('MEMORY_PREFLIGHT')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(600,600));signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024**2,32*1024**2))
    def dump(name,value):(dest/name).write_text(json.dumps(value,indent=2)+'\n')
    start=time.monotonic();dump('STARTED.json',{'source_commit':head,'started_epoch':time.time(),'memory_bytes':cap,'wall_seconds':600,'center_corrections':1,'planned_continuous_form_passes':3})
    try:
        import numpy as np
        from . import higher_order_trace as high
        from .static_condensation import solve
        from .strict_high_order_field import integrate
        from .selector_observable_bounds import sqrt_bounds
        from .root_tube_arithmetic import tube_bounds
        from .projector_budget import bound
        from .selector_cone_bounds import conditional_cone_bounds
        with np.load(plan['inputs']['topology']['path'],allow_pickle=False) as z:data={k:z[k] for k in z.files if k!='anchor'}
        with np.load(plan['inputs']['initial']['path'],allow_pickle=False) as z:initial=z['coefficients']
        model=json.loads(Path(plan['inputs']['model']['path']).read_text());sc=F(plan['center_s_exact']);h=F(plan['half_width_exact'])
        phase=high.global_phase(data);raw=initial/phase
        if np.max(abs(raw.imag))>1e-14:raise ValueError('EXPECTED_REAL_REPRESENTATION')
        ids,forms=high.assemble_real_forms(data,float(sc/F(.775)))
        x,history,checkpoints=solve(ids,forms,raw.real,raw.real,iterations=10000,outer_limit=3,seconds=530,logger=lambda row:print(json.dumps(row),flush=True))
        rho=float(np.dot(x,high.apply_real(forms[1],ids,x))/np.dot(x,high.apply_real(forms[0],ids,x)))
        coeff=phase*x;np.savez_compressed(dest/'proposal.npz',coefficients=coeff);dump('history.json',history);dump('checkpoints.json',checkpoints)
        del forms,ids,raw,x
        endpoints=[];endpoint_sums=[]
        for index,s in enumerate((sc-h,sc+h)):
            # This exact binary64 number is only a residual shift. Temple uses
            # the independently enclosed true quotient N/M below.
            shift=F(float(rho+float(s-sc)*.58))
            sums,geometry=integrate(data,coeff,model,shift,s=s,logger=lambda row:print(json.dumps({'endpoint':index,**row}),flush=True))
            norm=sums['mass'];ray=sums['N']/norm
            residual2=F(sums['residual2'].hi.item())/F(norm.lo.item())
            item={'s_exact':str(s),'arbitrary_residual_shift_exact':str(shift),'true_rayleigh_interval':[str(F(ray.lo.item())),str(F(ray.hi.item()))],
                'true_rayleigh_residual2_upper':str(residual2),'residual_upper':float(sqrt_bounds(residual2)[1]),
                'residual_proof':'For normalized v, ||(T-rho_true)v||^2 = ||(T-shift)v||^2 - (rho_true-shift)^2 <= saved upper bound.',
                'integrals':{k:v.export() for k,v in sums.items()},'geometry':geometry}
            dump('endpoint-'+str(index)+'.json',item);endpoints.append(item);endpoint_sums.append(sums)
        lip=1/F(.775)  # bound original epsilon minimum is exactly one
        regions=[[[value if i==j else 0 for j in range(3)] for i in range(3)] for value in (model['top_epsilon'],model['bottom_epsilon'])]
        regions.append(model['materials']['0.775']['laboratory_epsilon'])
        if min(F(mat[i][i]) for mat in regions for i in range(3))!=1:raise ValueError('LIPSCHITZ_MATERIAL_BINDING')
        tube=tube_bounds(endpoints,sc,h,F(1283,1000),F(1299,1000),lip)
        sums=endpoint_sums[0];mass=sums['mass'];el=sums['electric'];l2=sums['electric_L2']
        electric=sqrt_bounds(F(el.lo.item())/F(mass.hi.item()))[0]
        budget=bound(F(tube['q_upper_exact']),electric)
        def ratio(num,den):
            v=num/den;return [max(F(0),F(v.lo.item())),min(F(1),F(v.hi.item()))]
        p,c,o=ratio(sums['Ex'],l2),ratio(sums['core'],el),ratio(sums['outer'],el)
        mean=el/l2;mean_bounds=[F(mean.lo.item()),F(mean.hi.item())];gamma=sqrt_bounds(mean_bounds[1])[1]
        selector=conditional_cone_bounds(p,c,o,F(budget['electric_error_upper_exact']),gamma,epsilon_regions=regions,mean_epsilon=mean_bounds)
        passed=tube['root_uniqueness_if_bound_inputs'] and selector['strict_filters_would_pass_if_inputs_certified'] and F(tube['q_upper_exact'])<=F(139,1000) and electric>=F(7,10)
        result={'status':'ROOT_TUBE_FIELD_SELECTOR_CERTIFIED_RECORD_BINDING_PENDING' if passed else 'ROOT_TUBE_UNISOLATED',
            'tube':tube,'projector_budget':budget,'selector':selector,'electric_norm_lower_exact':str(electric),
            'actual_selected_record_bound':False,'continuous_model_sha256':plan['inputs']['model']['sha256'],
            'source_worker_sha256':plan['inputs']['worker']['sha256'],'source_commit':head,'new_MPB_Meep_API_calls':0,
            'root_existence':tube['root_existence_if_bound_inputs'],'root_uniqueness':tube['root_uniqueness_if_bound_inputs'],
            'fixed_s_B_not_substituted_for_tube':True,'root_tube_certified':passed}
        dump('root-tube.json',result)
        dump('FINAL.json',{'status':result['status'],'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'center_corrections':1,'optimization_form_passes':1,'strict_endpoint_integrations':2,'continuous_form_passes':3,
            'new_MPB_Meep_API_calls':0,'output_bytes_before_receipt':sum(p.stat().st_size for p in dest.iterdir() if p.is_file())})
        print(json.dumps({'status':result['status'],'q':tube['q_upper'],'derivative_lower':tube['eigenvalue_derivative_lower']}),flush=True)
    except Exception as exc:
        dump('FAILED.json',{'type':type(exc).__name__,'error':str(exc),'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss});raise


if __name__=='__main__':main()
