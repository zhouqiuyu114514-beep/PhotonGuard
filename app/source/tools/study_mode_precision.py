"""Owned, bounded public-synthetic precision study; zero model calls, no replay.

First produce a frozen plan with --plan. Codex may review/approve that exact plan
under the owner's development delegation. This does not approve a user's task
or reuse the completed product repair card. --execute never resumes old work.
"""
from pathlib import Path
import argparse,copy,fcntl,hashlib,json,math,shutil,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from photonguard.core import load,digest
from photonguard.approved_gui import source_manifest
from photonguard.workflow import write_once,now
from photonguard.runner import verify_evidence
from photonguard.mode_precision import STUDY_POLICY,build_study_plan,verify_study_plan,verify_study_origin,sensitivity_accounting
from photonguard.mode_verification import cross_candidate_identity
from photonguard.mode_report import render
from photonguard.adapters import mpb_modes,qpm_phase,registry
from photonguard import mode_execution

CASE=ROOT/'local-validation/mode-ai-20261007/workspace/7cdf1105b59d4eff886c43dd5df95d34'
OUT=ROOT/'local-validation/mode-precision-study-20261007'
LEDGER=Path('/home/zhou/projects/PhotonGuard-development/local-validation/development-phase-20cny/development-budget.ledger.json')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def inspect(bundle,goal,*,original_qpm_task=None):
    modes,receipts=mpb_modes.qpm_sources(bundle)
    records=[]
    task=load(bundle/'task.json');execution=load(bundle/'execution-task.json') if (bundle/'execution-task.json').exists() else task
    for step in mpb_modes.plan_checks(execution):
        actual=load(bundle/(step['variant']+'-'+str(step['wavelength_um']))/'result.json')
        records.append({'wavelength_um':step['wavelength_um'],'variant':step['variant'],'neff':actual['selected_mode']['neff']})
    qtask={'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':task['task_id']+'-QPM',
        'requirements':copy.deepcopy(goal),'modes':modes,'provenance':{'reference':'Unchanged independent synthetic goal, explicit numerical precision study',
            'mode_task_sha256':digest(task),'confirmed_goal_sha256':digest(goal)}}
    if original_qpm_task is not None:
        if (original_qpm_task['requirements']!=goal or original_qpm_task['modes']!=modes
                or original_qpm_task['provenance']['mode_task_sha256']!=digest(task)
                or original_qpm_task['provenance']['confirmed_goal_sha256']!=digest(goal)):
            raise ValueError('Original QPM task, mode source or goal binding changed')
        qtask=original_qpm_task
    qpm=qpm_phase.evaluate(qtask,verified_mode_sources=receipts);accounting=sensitivity_accounting(records,goal)
    assert math.isclose(accounting['unchanged_verifier_phase_estimate_rad'],qpm['phase_sensitivity_estimate_rad'],rel_tol=1e-12)
    return accounting,qtask,qpm

def planning():
    assert not OUT.exists(),'Study exists: preserve it; never overwrite or auto-resume'
    state=load(CASE/'state.json');flow=state['adapter_flow'];goal=flow['qpm_goal'];task=flow['mode_task']
    assert flow['repair_count']==1 and flow['repair_result']['qpm_verification']=='INCONCLUSIVE'
    assert flow['mode_lock']['confirmation_kind']=='SIMULATED' and flow['qpm_goal_sha256']==digest(goal)
    source=source_manifest(ROOT);references=[];accounting=[];ledger_sha=sha(LEDGER)
    for name in ('initial_result','result'):
        bundle=(CASE/flow[name]['mode_bundle']).resolve();assert bundle.is_relative_to(CASE.resolve())
        assert verify_evidence(bundle)
        original_qpm_file=CASE/('reuse-qpm-task.json' if name=='initial_result' else 'qpm-task-'+flow[name]['job_id']+'.json')
        facts,_,qpm=inspect(bundle,goal,original_qpm_task=load(original_qpm_file))
        assert qpm==flow[name]['qpm_report']
        numerical=load(bundle/'execution-task.json') if (bundle/'execution-task.json').exists() else load(bundle/'task.json')
        references.append({'role':name,'mode_bundle':str(bundle),'manifest_sha256':sha(bundle/'manifest.json'),
            'base_resolution':numerical['numerics']['resolution'],'parent_case_state_sha256':sha(CASE/'state.json')})
        accounting.append({'role':name,'source_bundle':str(bundle),'manifest_sha256':sha(bundle/'manifest.json'),
            'source_commit':load(bundle/'source-binding.json')['git_commit'],'accounting':facts})
    plan=build_study_plan(task,goal,references,source);verify_study_plan(plan)
    assert shutil.disk_usage(ROOT).free>=plan['estimated_total_output_bytes']*STUDY_POLICY['minimum_free_disk_margin']
    OUT.mkdir(parents=True,exist_ok=False)
    write_once(OUT/'analysis.json',{'created_at_utc':now(),'records':accounting,'ledger_sha256':ledger_sha,
        'old_case_state_sha256':sha(CASE/'state.json'),'new_model_calls':0,'new_solver_calls':0,
        'interpretation':'Per-wavelength measured-setting sensitivity; signed cancellation cannot replace the fixed conservative verifier'})
    write_once(OUT/'plan.json',plan)
    assert sha(LEDGER)==ledger_sha
    print(json.dumps({'plan':str(OUT/'plan.json'),'approval_plan_sha256':digest(plan),
        'phase_estimate_48_rad':accounting[-1]['accounting']['unchanged_verifier_phase_estimate_rad'],
        'phase_contributions_48_rad':[{k:r[k] for k in ('wavelength_um','verifier_phase_contribution_rad')} for r in accounting[-1]['accounting']['rows']],
        'planned_resolutions':[64,80],'max_workers':12,'maximum_wall_seconds':3600,
        'estimated_output_mib':plan['estimated_total_output_bytes']/1024**2,'new_model_calls':0,'new_solver_calls':0},ensure_ascii=False,indent=2))

def execution(approved_digest):
    plan=load(OUT/'plan.json');verify_study_plan(plan)
    if type(approved_digest) is not str or digest(plan)!=approved_digest:raise ValueError('Exact reviewed plan hash required')
    if digest(source_manifest(ROOT))!=plan['source_binding_sha256']:raise ValueError('Approved source changed')
    assert sha(CASE/'state.json')==plan['baseline_references'][0]['parent_case_state_sha256']
    parent=load(CASE/'state.json')['adapter_flow']
    verify_study_origin(plan,parent['mode_task'],parent['qpm_goal'])
    for ref in plan['baseline_references']:
        bundle=Path(ref['mode_bundle']);assert verify_evidence(bundle) and sha(bundle/'manifest.json')==ref['manifest_sha256']
        assert load(bundle/'task.json')['requirements']==plan['parent_task']['requirements']
    # Check the current product workspace before independent development workers.
    from urllib.request import urlopen
    with urlopen('http://127.0.0.1:8778/api/bootstrap',timeout=5) as response:boot=json.load(response)
    for row in boot['cases']:
        with urlopen('http://127.0.0.1:8778/api/cases/'+row['id'],timeout=5) as response:state=json.load(response)
        flow=state.get('adapter_flow') or {}
        assert all((job or {}).get('status')!='running' for job in (state.get('job'),flow.get('job'),flow.get('diagnosis_job'))),'Product job active; do not compete'
    ledger_sha=sha(LEDGER);started=time.monotonic()
    with (OUT/'study.lock').open('a') as lockfile:
        fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write_once(OUT/'OWNER_DELEGATED_STUDY_APPROVAL.json',{'created_at_utc':now(),'reviewed_plan_sha256':digest(plan),
            'owner_authorization':'2026-10-07: 你直接推进就行，不用找我审批; 2026-10-07: 好，你继续推进',
            'actor':'Codex reviewed exact bounded synthetic study plan','confirmation_kind':'SIMULATED',
            'not_a_final_user_click':True,'not_a_model_approval':True,'source_commit':plan['source_binding']['git_commit'],
            'physical_requirements_sha256':plan['physical_requirements_sha256'],'qpm_goal_sha256':plan['qpm_goal_sha256'],
            'policy':STUDY_POLICY,'output_estimate_bytes':plan['estimated_total_output_bytes'],'ledger_sha256':ledger_sha,
            'completed_product_card_not_reused':True,'new_model_calls':0})
        write_once(OUT/'started.json',{'at_utc':now(),'plan_sha256':digest(plan),'automatic_resume_or_retry':False})
        previous=Path(plan['baseline_references'][-1]['mode_bundle']);results=[];stop_reason='APPROVED_NUMERICAL_MENU_EXHAUSTED'
        try:
            for item in plan['tasks']:
                if time.monotonic()-started+mpb_modes.POLICY['resource_limits']['max_total_wall_seconds']>STUDY_POLICY['maximum_total_wall_seconds']:
                    stop_reason='TOTAL_STUDY_WALL_BOUND';break
                assert sha(LEDGER)==ledger_sha,'Concurrent ledger change; retain evidence and stop study'
                size=sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
                if size+item['output_estimate']['estimated_total_output_bytes']>STUDY_POLICY['maximum_output_estimate_bytes']:
                    stop_reason='STUDY_STORAGE_BOUND';break
                if shutil.disk_usage(OUT).free<item['output_estimate']['estimated_total_output_bytes']*STUDY_POLICY['minimum_free_disk_margin']:
                    stop_reason='AVAILABLE_DISK_BOUND';break
                task=item['mode_task'];candidate=item['candidate'];folder=OUT/('resolution-'+str(task['numerics']['resolution']));folder.mkdir(exist_ok=False)
                assert digest(task['requirements'])==plan['physical_requirements_sha256'] and digest(plan['qpm_goal'])==plan['qpm_goal_sha256']
                lock=registry.lock_task(task,approve=True,confirmation_kind='SIMULATED')
                permit=mode_execution.permit(task,lock,candidate,approve=True,phase='initial')
                write_once(folder/'execution-approval.json',{'task':task,'lock':lock,'permit':permit,'candidate':candidate,
                    'qpm_goal_sha256':plan['qpm_goal_sha256'],'reviewed_study_plan_sha256':digest(plan)})
                print('Running approved separate precision seed '+str(task['numerics']['resolution'])+'; model calls 0.',flush=True)
                report,bundle=mpb_modes.run(task,lock,permit,folder/'mode-artifacts',candidate=candidate)
                record={'base_resolution':task['numerics']['resolution'],'mode_bundle':str(bundle),'mode_report':report,
                    'mode_bundle_manifest_sha256':sha(bundle/'manifest.json'),'additional_model_requests':0}
                if report['verification_status']!='PASS':
                    record['status']='INCONCLUSIVE';record['qpm_report']=None;results.append(record)
                    write_once(folder/'result.json',record);stop_reason='MODE_VERIFICATION_NOT_PASS';break
                identity=cross_candidate_identity(previous,bundle,mpb_modes.POLICY);record['cross_study_identity']=identity
                if identity['status']!='PASS':
                    record['status']='INCONCLUSIVE';record['qpm_report']=None;results.append(record)
                    write_once(folder/'result.json',record);stop_reason='MODE_IDENTITY_NOT_PASS';break
                accounting,qtask,qpm=inspect(bundle,plan['qpm_goal'])
                write_once(folder/'qpm-task.json',qtask);write_once(folder/'qpm-report.json',qpm)
                record.update(status='completed',accounting=accounting,qpm_report=qpm,
                    derived_report=str(render(bundle,qtask,qpm,folder/'report')))
                write_once(folder/'result.json',record);results.append(record);previous=bundle
                print(json.dumps({'resolution':record['base_resolution'],'phase_estimate_rad':qpm['phase_sensitivity_estimate_rad'],
                    'qpm_status':qpm['verification_status'],'design_goal':qpm['design_goal_status'],
                    'actual_solver_counts':report['solver_counts']},ensure_ascii=False),flush=True)
                if qpm['verification_status']=='PASS':stop_reason='FIXED_PRECISION_CHECK_PASSED';break
        except Exception as error:
            write_once(OUT/'interrupted.json',{'at_utc':now(),'type':type(error).__name__,
                'no_automatic_resume_or_retry':True,'completed_case_count':len(results),'evidence_retained':True})
            raise
        assert sha(CASE/'state.json')==plan['baseline_references'][0]['parent_case_state_sha256'] and sha(LEDGER)==ledger_sha
        summary={'source_commit':plan['source_binding']['git_commit'],'study_plan_sha256':digest(plan),'status':'BOUNDED_STUDY_FINISHED',
            'stop_reason':stop_reason,'confirmation_kind':'SIMULATED','results':results,
            'wall_seconds':time.monotonic()-started,'new_model_calls':0,'ledger_unchanged':True,
            'original_case_state_unchanged':True,'physical_requirements_sha256':plan['physical_requirements_sha256'],
            'qpm_goal_sha256':plan['qpm_goal_sha256'],'signed_cancellation_used_for_acceptance':False,
            'actual_solver_counts':{k:sum(r['mode_report']['solver_counts'][k] for r in results)
                for k in ('find_k_invocations','eigenproblem_solves','fdtd_runs')}}
        write_once(OUT/'summary.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan',action='store_true');mode.add_argument('--execute',action='store_true')
    parser.add_argument('--approve-plan-sha256');args=parser.parse_args()
    if args.plan:planning()
    else:execution(args.approve_plan_sha256)
