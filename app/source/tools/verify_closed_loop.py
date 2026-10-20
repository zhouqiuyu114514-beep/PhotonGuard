"""Explicitly marked development approval simulation using archived real AI."""
import argparse
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photonguard.workflow import WorkflowStore,write_once
from photonguard.core import digest,load
from photonguard.runner import verify_evidence

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate-human-confirmation',action='store_true',required=True)
    parser.add_argument('--archive-root',type=Path,default=Path('/home/zhou/projects/PhotonGuard-development'))
    args=parser.parse_args()
    archive=args.archive_root
    mapping=load(archive/'local-validation/development-phase-20cny/gui-cases.json')['cases']
    parent=load(archive/'workspace-data'/mapping['complete-A1']/'state.json')
    assert parent['intake']['result']['mode']=='REAL_MODEL'
    assert parent['intake']['result']['origin_verified'] is True
    assert parent['intake']['status']=='REVIEW' and not parent['approval']
    ident=uuid.uuid4().hex
    out=ROOT/'local-validation'/('closed-loop-'+ident[:8])
    out.mkdir(parents=True,exist_ok=False)
    store=WorkflowStore(out/'workflow-data',allow_workers=True)
    trace=[]
    try:
        state=store.create('own');ident=state['id']
        raw=store._load(ident)
        raw.update(label='开发验证 · 模拟确认 · 等波长单膜',
            intake=copy.deepcopy(parent['intake']),
            development_confirmation={'mode':'SIMULATED_HUMAN_APPROVAL_DEVELOPMENT_ONLY','real_user_confirmation':False},
            reused_ai={'source_case_id':parent['id'],'source_state_sha256':digest(parent),
                'new_model_calls':0,'source_commit':'85181a33d46f2ba5610380f4e265f7c705af8c2c'})
        store._snapshot(raw,'archived-ai-reuse',raw['reused_ai']);store._save(raw);state=store.get(ident)
        def action(kind,**data):
            nonlocal state
            state=store.action(ident,{'type':kind,'expected_revision':state['revision'],**data})
            trace.append({'action':kind,'revision':state['revision'],'stage':state['stage'],
                'simulated_human_confirmation':kind in ('intake-confirm','map-task','confirm','apply','run')})
            return state
        action('intake-confirm',approve=True,result_sha256=state['intake']['result_sha256'])
        options={'units_um':1,'linear':True,'field_component':'Ex','accept_sampling':True,'accept_decimal_projection':True,
            'mapping_source':'独立合成任务卡CL-v1：1Meep单位=1微米，线性介质，正入射Ex；未从待检脚本推定。',
            'background':'单膜光谱课程合成练习','goal':'检查脚本材料是否符合独立设计需求并重验R/T','role':'开发测试模拟的参数审阅者'}
        action('map-task',options=options)
        source=(ROOT/'examples/script_import/wavelength35_index_mismatch.py').read_text()
        action('import',name='wavelength35_index_mismatch.py',source=source)
        assert not state['readiness']['provenance_problem'],state['readiness']
        action('confirm',approve=True)
        def run_and_wait():
            nonlocal state
            action('run')
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                time.sleep(.3);state=store.get(ident)
                if state['job']['status']!='running':break
            assert state['job']['status']=='completed',state['job']
            run_id=state['runs'][-1]['run_id']
            path=store.case_dir(ident)/'artifacts'/run_id
            assert verify_evidence(path)
            return load(path/'report.json'),path
        before,before_path=run_and_wait()
        assert before['status']=='FAIL',before['status']
        action('propose')
        assert state['proposal']['changes']==[{'path':['layers',0,'material_value'],'old':1.4,'new':1.7}]
        patch=copy.deepcopy(state['proposal']);action('apply',approve=True)
        after,after_path=run_and_wait()
        assert after['status']=='PASS',[(c['id'],c['status']) for c in after['checks']]
        assert after['resource_usage']['fdtd_runs']==8
        assert after['sampling']['actual_solver_point_count']==35
        assert after['sampling']['interpolated_point_count']==0
        summary={'schema_version':1,'at_utc':datetime.now(timezone.utc).isoformat(),
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'development_only':True,'real_user_confirmed':False,'approval_mode':'SIMULATED_HUMAN_APPROVAL_DEVELOPMENT_ONLY',
            'new_model_calls':0,'reused_real_ai_case':parent['id'],'case_id':ident,
            'source_sha256':state['candidate']['origin']['script_import']['source_sha256'],
            'trace':trace,'repair':patch['changes'],'before':{'status':before['status'],'path':str(before_path)},
            'after':{'status':after['status'],'path':str(after_path)},'sampling':after['sampling'],
            'checks':after['checks'],'evidence_verified':True,
            'fdtd_runs':before['resource_usage']['fdtd_runs']+after['resource_usage']['fdtd_runs']}
        write_once(out/'CLOSED_LOOP_RESULT.json',summary)
        print(json.dumps({'output':str(out),'before':before['status'],'after':after['status'],
            'actual_points':35,'interpolation_points':0,'new_model_calls':0,'approval_mode':summary['approval_mode']},ensure_ascii=False),flush=True)
    finally:store.close()

if __name__=='__main__':main()
