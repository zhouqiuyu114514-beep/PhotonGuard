"""One-shot second-machine acceptance; never calls an AI provider.

Fixtures are supplied in the release packet, not manufactured by this script.
Running this entry point executes at most eight new FDTD runs. Do not run it
in the exhausted small-certificate assembly window.
"""
import argparse,csv,json,math,platform,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photonguard.runner import run_case,verify_evidence
from photonguard.checks import static_checks

def compare_spectra(baseline,new,tolerance=1e-6):
    def rows(path):
        with Path(path).open() as f:return [{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]
    a,b=rows(baseline),rows(new)
    if not a or len(a)!=len(b):raise ValueError('SPECTRUM_GRID_MISMATCH')
    worst=0.0
    for x,y in zip(a,b):
        if any(not math.isfinite(v) for v in (*x.values(),*y.values())):raise ValueError('NONFINITE_SPECTRUM')
        if x['frequency']!=y['frequency'] or x['wavelength_um']!=y['wavelength_um']:raise ValueError('SPECTRUM_GRID_MISMATCH')
        worst=max(worst,abs(x['R']-y['R']),abs(x['T']-y['T']))
    return {'max_absolute_RT_difference':worst,'frozen_tolerance':tolerance,'passed':worst<=tolerance,'interpolation':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    receipt={'status':'STARTED','platform':platform.platform(),'python':sys.version,'actual_human_trial':False,'manual_install_fixes':None,'new_API_calls':0,'max_fdtd_runs':8,'bootstrap_smoke_count_separate':1}
    def save(): (a.out/'acceptance.json').write_text(json.dumps(receipt,indent=2))
    save();started=time.monotonic()
    try:
        base=a.fixtures/'thinfilm-pass';bad=a.fixtures/'thinfilm-refusal'
        if not verify_evidence(base):raise ValueError('BASELINE_EVIDENCE_INVALID')
        # Precheck the deliberate material mismatch before spending any solver budget.
        checks=static_checks(json.loads((bad/'task.json').read_text()),json.loads((bad/'candidate.json').read_text()))
        if not any(x['id']=='task_parameters' and x['status']=='FAIL' for x in checks):raise ValueError('REFUSAL_FIXTURE_INVALID')
        fail,folder=run_case(bad/'task.json',bad/'candidate.json',bad/'task.lock.json',a.out/'refusal',max_fdtd_runs=0)
        receipt['refusal']={'status':fail['status'],'fdtd_runs':fail['resource_usage']['fdtd_runs'],'evidence':str(folder)};save()
        if fail['status']!='FAIL' or fail['resource_usage']['fdtd_runs']!=0:raise ValueError('REFUSAL_CHANGED')
        report,folder=run_case(base/'task.original.json',base/'candidate.original.json',base/'task.lock.json',a.out/'pass',max_fdtd_runs=8)
        receipt['thinfilm']={'status':report['status'],'fdtd_runs':report['resource_usage']['fdtd_runs'],'evidence':str(folder)};save()
        old=json.loads((base/'report.json').read_text())
        if report['status']!='PASS' or any(report[k]!=old[k] for k in ('task_hash','candidate_hash','policy_hash')):raise ValueError('PASS_OR_INPUT_BINDING_CHANGED')
        comparison=compare_spectra(base/'spectrum.csv',folder/'spectrum.csv');receipt['comparison']=comparison;save()
        if not comparison['passed']:raise ValueError('CROSS_MACHINE_TOLERANCE_EXCEEDED')
        receipt['LN_read_only']=json.loads((a.fixtures/'LN-status.json').read_text())
        receipt['status']='PASS'
    except BaseException as exc:
        receipt.update(status='STOPPED_NO_RETRY',reason=str(exc));raise
    finally:
        receipt['elapsed_seconds']=time.monotonic()-started;save()
    print(json.dumps(receipt));return 0

if __name__=='__main__':raise SystemExit(main())
