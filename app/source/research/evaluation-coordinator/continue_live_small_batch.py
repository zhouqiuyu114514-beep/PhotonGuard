"""Manual coordinator continuation of undispatched turns under the SAME ledger.

Original returns/stops stay immutable. No new approval, reset, replacement model
answer, new case, automatic clarification or restart of the first paid turn.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from datetime import datetime,timezone
import fcntl
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

import live_transport as transport
import run_live_small_batch as original
from batch_ledger import SemanticBatchLedger
from photonguard.backend import ApprovedRates,BackendAuthorization
from photonguard.cny_budget import CnyApproval

ROOT=original.ROOT


from semantic_protocol import candidate_contents


def validate_continuation(plan,amendment,session):
    if session!=ROOT/'local-validation/semantic-live-small-20261006':raise ValueError('same approved session required')
    if original.sha(session/'plan.json')!=amendment['original_plan_sha256']:raise ValueError('original plan changed')
    if amendment['reference']!=plan['authorization']['reference']:raise ValueError('new reference forbidden')
    if plan['authorization']['max_calls']!=12 or plan['authorization']['total_budget_cny']!='5':raise ValueError('budget changed')
    if amendment['max_request_bytes']!=120000 or amendment['input_token_reservation']!=transport.INPUT_BOUND:
        raise ValueError('unfrozen wire bound')
    if transport.MAX_REQUEST_BYTES+1024>transport.INPUT_BOUND:raise ValueError('token bound inadequate')
    for rel,h in amendment['runner_sha256'].items():
        if original.sha(ROOT/rel)!=h:raise ValueError('continuation source changed')
    for rel,h in plan['common_tool_sha256'].items():
        if original.sha(session/'common-tools'/rel)!=h:raise ValueError('public rules changed')
    for rel,h in amendment['original_phase_files_sha256'].items():
        if original.sha(session/rel)!=h:raise ValueError('original phase evidence changed')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(plan['checked_at'].replace('Z','+00:00'))).total_seconds()
    if not 0<=age<=86400:raise ValueError('price approval stale')
    private=Path(plan['coordinator_root'])
    if original.sha(private/'evaluator/evaluate.py')!=plan['evaluator_sha256']:raise ValueError('scorer changed')
    manifest=json.loads((private/'SEMANTIC_FREEZE_MANIFEST.json').read_text())
    if original.sha(private/'SEMANTIC_FREEZE_MANIFEST.json')!=plan['semantic_manifest_sha256']:raise ValueError('semantic manifest changed')
    for row in manifest['files']:
        if original.sha(private/row['path'])!=row['sha256']:raise ValueError('coordinator asset changed')
    for slot in plan['slots']:
        visible=session/'visible'/slot['slot_id']
        if original.sha(visible/'view.json')!=slot['visible_file_sha256'] or original.sha(visible/'trusted.json')!=slot['trusted_file_sha256']:
            raise ValueError('original released input changed')
        original.adapter.validate_view(original.adapter.read(visible/'view.json'),slot['expected_input_sha256'])
        request=json.loads((session/'observations'/slot['slot_id']/'turn-02/request.json').read_text())
        body=json.dumps(request,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode()
        if len(body)>transport.MAX_REQUEST_BYTES or transport.credential_risk(request):raise ValueError('continuation preflight failed')
    proof=json.loads((session/'isolation-proof.json').read_text())
    if not proof['all_checks_passed'] or original.sha(session/'isolation-proof.json')!=plan['isolation_proof_sha256']:
        raise ValueError('isolation proof changed')
    return private


def execute_remaining(plan,session,key,ledger,private):
    import importlib.util
    spec=importlib.util.spec_from_file_location('continuation_frozen_evaluator',private/'evaluator/evaluate.py')
    evaluator=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluator)
    rows=[];stop_all=False
    for slot in plan['slots']:
        path=session/'continuation'/slot['slot_id'];path.mkdir(parents=True,exist_ok=False)
        view=original.adapter.read(session/'visible'/slot['slot_id']/'view.json')
        request=json.loads((session/'observations'/slot['slot_id']/'turn-02/request.json').read_text())
        original.write(path/'task.json',{'provenance':'OBSERVED_MODEL','slot_id':slot['slot_id'],
            'continuing_undispatched_turn':2,'original_paid_first_turn_preserved':True,
            'original_tool_commentary_is_not_a_final_candidate':True,'r0_observed':False})
        candidates=[];final=None;audits=[];status='NO_FINAL_CANDIDATE'
        if stop_all:status='STOPPED_BY_SHARED_BUDGET_OR_SAFETY'
        else:
            for number in (2,3):
                if number==3:
                    request['messages'].append({'role':'user','content':'This is the last permitted API turn. Return your pending-review JSON now, preserving unresolved items; do not request more tools or assume any new clarification.'})
                    request['tool_choice']='none'
                turn=path/('turn-%02d'%number);turn.mkdir()
                original.write(turn/'dispatch-intent.json',{'slot_id':slot['slot_id'],'original_turn_number':number,
                    'new_authorization':False,'counts_in_task_denominator':True})
                original.write(turn/'request.json',request)
                try:result=transport.complete(request,key,ledger)
                except (ValueError,OSError):
                    original.write(turn/'audit.json',{'status':'PREFLIGHT_OR_BUDGET_STOP','live_dispatch':False,
                        'response':None,'response_storage':'OMITTED_UNTRUSTED_HTTP_BODY'})
                    status='PREFLIGHT_OR_BUDGET_STOP';break
                audit=result['audit'];original.write(turn/'audit.json',audit);audits.append(audit)
                message=result['assistant']
                if message is None:
                    status=audit['status']
                    if status=='SAFETY_STOP' or ledger.snapshot()['halted']:stop_all=True
                    break
                original.write(turn/'raw-assistant.json',message)
                for i,(origin,raw) in enumerate(candidate_contents(message),1):
                    target=turn/('candidate-%02d'%i)
                    original.score_original(target,raw,view,slot['expected_input_sha256'],evaluator,private,origin=origin,key=key)
                    candidates.append(str(target.relative_to(session)))
                    if origin=='ASSISTANT_FINAL_CONTENT':final=str(target.relative_to(session))
                if len(candidates)>3:status='SUBMISSION_BUDGET_STOP';final=None;break
                if not message.get('tool_calls'):
                    status='FINAL_RETURNED' if final is not None else 'EMPTY_RETURN';break
                if number==3 or audit['status']!='ASSISTANT_RETURNED' or ledger.snapshot()['halted']:
                    status='INCOMPLETE_TOOL_RETURN';break
                request['messages'].append(message)
                for i,call in enumerate(message['tool_calls'],1):
                    feedback=original.run_tool(plan,session,slot,call)
                    original.write(turn/('tool-feedback-%02d.json'%i),feedback)
                    request['messages'].append({'role':'tool','tool_call_id':call['id'],
                        'content':json.dumps(feedback,ensure_ascii=False)})
        row={'slot_id':slot['slot_id'],'arm':slot['arm'],'case_id':slot['case_id'],'status':status,
             'candidate_submissions':candidates,'final_candidate':final,'new_dispatched_requests':sum(a['live_dispatch'] for a in audits),
             'original_first_turn_counted':True,'human_active_seconds':None,'r0_observed':False}
        original.write(path/'result.json',row);rows.append(row)
        print(slot['slot_id']+': '+status,flush=True)
        if ledger.snapshot()['halted']:stop_all=True
    original.write(session/'continuation-summary.json',{'provenance':'OBSERVED_MODEL','tasks':rows,
        'planned_task_denominator':4,'original_failure_phase_retained':True,'budget':ledger.snapshot(),
        'original_summary_replaced':False,'r0_observed':False,'human_cost_observed':False,
        'three_arm_comparison':'NOT_AVAILABLE','ai_gain':'NOT_ESTABLISHED','model_contexts_restarted':False})


def main():
    session=ROOT/'local-validation/semantic-live-small-20261006'
    if not sys.stdin.isatty() or not sys.stderr.isatty():raise ValueError('interactive hidden-key input required')
    plan=json.loads((session/'plan.json').read_text());amendment=json.loads((session/'continuation-amendment.json').read_text())
    if original.sha(session/'continuation-amendment.json')!=(session/'continuation-amendment.sha256').read_text().split()[0]:
        raise ValueError('continuation amendment changed')
    private=validate_continuation(plan,amendment,session)
    lock=os.open(session/'runner.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (session/'continuation-started.json').exists() or (session/'continuation-summary.json').exists():
        raise ValueError('continuation already started; no restart')
    auth=BackendAuthorization(True,plan['authorization']['reference'],'deepseek-flash','0.75',12,
        ApprovedRates('0.3','1.2',plan['checked_at'],'https://api-docs.deepseek.com/quick_start/pricing/'))
    cny=CnyApproval('5','2','8',plan['checked_at'],'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
    ledger=SemanticBatchLedger(auth,session/'new-semantic-budget.ledger.json',cny)
    state=ledger.snapshot()
    if state['attempts']!=4 or state['live_provider_attempts']!=4 or state['halted']:
        raise ValueError('unexpected consumed state; never reset')
    print('Continue undispatched turns only. SAME CNY 5 approval, total max 12 calls, 4 already consumed.')
    print('No new ledger, first-turn rerun, model-context restart or automatic clarification.',flush=True)
    warnings.simplefilter('error',getpass.GetPassWarning)
    key=getpass.getpass('DeepSeek API key (hidden): ')
    if not key or not key.isascii() or any(ord(c)<=32 or ord(c)>=127 for c in key):raise ValueError('invalid key')
    original.write(session/'continuation-started.json',{'started_utc':datetime.now(timezone.utc).isoformat(),
        'key_storage':'MEMORY_ONLY','budget_before':state,'amendment_sha256':original.sha(session/'continuation-amendment.json')})
    authenticated=original.authentication(key,'deepseek-flash')
    original.write(session/'continuation-authentication.json',{'authenticated':authenticated,'new_paid_generations':0})
    if not authenticated:
        original.write(session/'continuation-summary.json',{'status':'AUTHENTICATION_FAILED','additional_paid_dispatches':0})
        print('Authentication failed; no new paid generation.');return
    execute_remaining(plan,session,key,ledger,private)
    key=None;print('Continuation finished; all original and new failures preserved.',flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        print('STOPPED: inspect coordinator status; reservations kept, no automatic retry.',flush=True)
        raise SystemExit(3) from None
