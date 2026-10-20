"""Marked development simulation of two user approvals, not a user trial."""
import argparse
from datetime import datetime,timezone
import getpass
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from photonguard.workflow import WorkflowStore,write_once
from photonguard.core import load,digest
from photonguard.runner import verify_evidence
from photonguard.repair_pipeline import ThreeStepPipeline,ACTIVE
from photonguard.repair_diagnosis import RepairBroker
from photonguard.development_phase import PHASE
from tools.serve_ai_repair import seed_trials

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate-human-approvals',action='store_true',required=True)
    p.add_argument('--mode',choices=['rules','live'],required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--binding',type=Path)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    broker=None;key=None
    if args.mode=='live':
        RepairBroker(ROOT,PHASE,args.binding,None)
        key=getpass.getpass('DeepSeek credential (hidden; memory only): ')
        broker=RepairBroker(ROOT,PHASE,args.binding,lambda:key)
    store=WorkflowStore(args.out/'workflow-data',allow_workers=True)
    controller=ThreeStepPipeline(store,broker);store.pipeline_controller=controller
    trials=seed_trials(store);ident=trials['cases'][args.mode];state=store._load(ident)
    state['development_confirmation']={'mode':'SIMULATED_HUMAN_APPROVAL_DEVELOPMENT_ONLY','real_user_confirmation':False}
    store._save(state);state=store.get(ident);trace=[]
    def act(kind,**data):
        nonlocal state
        state=store.action(ident,{'type':kind,'expected_revision':state['revision'],**data})
        trace.append({'type':kind,'simulation':True,'revision':state['revision']})
    def wait():
        nonlocal state
        deadline=time.monotonic()+360
        while time.monotonic()<deadline:
            time.sleep(.3);state=store.get(ident)
            if state.get('pipeline',{}).get('status') not in ACTIVE:return
        raise ValueError('Development wait deadline exceeded; no retry')
    try:
        act('start-review',approve=True,accept_initial_checks=True,diagnostic_mode=args.mode,
            approve_diagnostic_data=args.mode=='live',result_sha256=state['intake']['result_sha256'],
            options=state['repair_trial']['options'],source=state['repair_trial']['source'])
        wait();print(json.dumps({'initial_phase':state['pipeline']['status'],'diagnostic_status':state.get('diagnosis',{}).get('status'),'evidence_saved':True},ensure_ascii=False),flush=True)
        if state['pipeline']['status']=='AWAITING_APPROVAL':
            act('approve-repair',approve=True,card_sha256=state['repair_card_sha256']);wait()
        reports=[]
        for run in state['runs']:
            path=store.case_dir(ident)/'artifacts'/run['run_id']
            assert verify_evidence(path)
            report=load(path/'report.json')
            reports.append({'path':str(path),'status':report['status'],'task_hash':report['task_hash'],
                'candidate_hash':report['candidate_hash'],'policy_hash':report['policy_hash'],
                'fdtd_runs':report['resource_usage']['fdtd_runs'],'sampling':report['sampling'],
                'failed_checks':[c for c in report['checks'] if c['status']=='FAIL']})
        summary={'mode':args.mode,'real_user_approvals':False,'simulated_approvals':trace,
            'case_id':ident,'pipeline':state['pipeline'],'reports':reports,'diagnosis':state.get('diagnosis'),
            'repair_card':state.get('repair_card'),'repair_result':state.get('repair_result'),
            'unchanged_task_and_policy':len({(r['task_hash'],r['policy_hash']) for r in reports})==1,
            'ledger_after':broker.ledger.snapshot() if broker else None,'no_retry':True}
        write_once(args.out/'summary.json',summary)
        print(json.dumps({'status':state['pipeline']['status'],'before':reports[0]['status'] if reports else None,
            'after':reports[-1]['status'] if len(reports)>1 else None,'summary':str(args.out/'summary.json')},ensure_ascii=False),flush=True)
    finally:store.close();key=None
if __name__=='__main__':main()
