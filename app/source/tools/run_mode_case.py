"""Owned offline mode/QPM workflow worker. No model transport, no user code."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from photonguard.core import load,digest
from photonguard.workflow import write_once
from photonguard.adapters import registry,mpb_modes,qpm_phase
from photonguard.mode_report import render
from photonguard import mode_execution
from photonguard.mode_verification import cross_candidate_identity

def run(request_file):
    request_file=Path(request_file);request=load(request_file);base=request_file.parent;receipt=base/request['receipt']
    try:
        flow=request['flow'];task=flow['mode_task'];lock=flow['mode_lock'];permit=flow['permit']
        candidate=flow.get('candidate')
        if candidate is None:registry.verify_permit(task,lock,permit)
        else:mode_execution.verify_permit(task,lock,candidate,permit)
        goal=flow['qpm_goal']
        if digest(goal)!=flow['qpm_goal_sha256']:raise ValueError('Independent QPM goal changed.')
        report,bundle=mpb_modes.run(task,lock,permit,base/'mode-artifacts',candidate=candidate)
        cross=None
        if request.get('phase')=='repair':
            before=base/flow['initial_result']['mode_bundle'];mpb_modes.qpm_sources(before)
            cross=cross_candidate_identity(before,bundle,mpb_modes.POLICY)
            write_once(base/('mode-cross-identity-'+request['job_id']+'.json'),cross)
            if cross['status']!='PASS':
                write_once(receipt,{'job_id':request['job_id'],'status':'completed','mode_bundle':str(bundle.relative_to(base)),
                    'mode_report':report,'qpm_report':None,'cross_repair_identity':cross,
                    'reason':'Mode identity changed or ambiguous after repair; QPM goal not judged.','model_requests':0});return
        if report['verification_status']!='PASS':
            write_once(receipt,{'job_id':request['job_id'],'status':'completed','mode_bundle':str(bundle.relative_to(base)),
                'mode_report':report,'qpm_report':None,'reason':'Mode verification stopped; no trusted QPM design judgment.'});return
        modes,receipts=mpb_modes.qpm_sources(bundle)
        qtask={'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':task['task_id']+'-QPM',
            'requirements':goal,'modes':modes,'provenance':{'reference':flow['qpm_source'],'mode_task_sha256':digest(task),
                'confirmed_goal_sha256':flow['qpm_goal_sha256'],'confirmation_inherited_from_explicit_workflow_consent':True}}
        qpm=qpm_phase.evaluate(qtask,verified_mode_sources=receipts)
        write_once(base/('qpm-task-'+request['job_id']+'.json'),qtask)
        write_once(base/('qpm-report-'+request['job_id']+'.json'),qpm)
        repair_context=None
        if request.get('phase')=='repair':
            from photonguard.mode_diagnosis import build_request,audit_mode_claims
            _,table,_=build_request(task,lock,flow['candidate_before_repair'],goal,flow['qpm_source'],
                base/flow['initial_result']['mode_bundle'],flow['initial_result']['qpm_report'])
            audit=audit_mode_claims(flow['diagnosis']['explanation_audit']['accepted'],table)
            if audit['status']!='VERIFIED_STRUCTURED_CLAIMS':raise ValueError('Repair explanation cannot be rebuilt.')
            repair_context={'approved_card_sha256':flow['repair_approval']['card_sha256'],
                'task_sha256':digest(task),'qpm_goal_sha256':digest(goal),'change':flow['repair_card']['change'],
                'diagnostic_mode':flow['selected_diagnostic_mode'],'diagnostic_model_requests':flow['diagnosis'].get('actual_model_calls'),
                'explanation_audit_status':audit['status'],'before_numerics':flow['candidate_before_repair']['numerics'],
                'after_numerics':candidate['numerics'],'before_phase_sensitivity_rad':(flow['initial_result'].get('qpm_report') or {}).get('phase_sensitivity_estimate_rad'),
                'after_phase_sensitivity_rad':qpm['phase_sensitivity_estimate_rad'],'cross_repair_identity':cross,
                'additional_model_requests':0,'automatic_retry':False,'confirmation_kind':lock['confirmation_kind']}
        derived=render(bundle,qtask,qpm,base/'mode-reports'/request['job_id'],repair_context=repair_context)
        write_once(receipt,{'job_id':request['job_id'],'status':'completed','mode_bundle':str(bundle.relative_to(base)),
            'mode_report':report,'qpm_report':qpm,'derived_report':str(derived.relative_to(base)),
            'qpm_goal_sha256':flow['qpm_goal_sha256'],'model_requests':0,
            'numerical_candidate_sha256':digest(candidate) if candidate else None,'cross_repair_identity':cross,
            'diagnosis_mode':'SOLVER_ONLY_NO_MODEL_TRANSPORT'})
    except Exception:
        # Worker stderr may contain owned solver errors; no credentials are inherited.
        if not receipt.exists():write_once(receipt,{'job_id':request['job_id'],'status':'failed','error':'MODE_OR_QPM_VERIFICATION_FAILED; retained logs; no automatic retry','model_requests':0})
        raise

if __name__=='__main__':run(sys.argv[1])
