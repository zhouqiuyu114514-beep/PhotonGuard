"""Copy archived drafts into unlocked trial tasks; no approvals or calls."""
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photonguard.core import load,digest
from photonguard.workflow import WorkflowStore,write_once
from photonguard.workflow_intake import prepare,apply

CARD={'mapping_source':'独立合成试用任务卡CL-v1：1Meep单位=1微米；线性介质、正入射Ex。原始需求保留35个等波长点，不使用插值。',
    'background':'课程中的单层薄膜光谱核对练习（公开合成资料）',
    'goal':'检查待检脚本是否符合独立设计需求并重验R/T',
    'role':'核对独立参数、批准任务与修复的学习者'}

def main():
    destination=ROOT/'local-validation/closed-loop-release'
    destination.mkdir(parents=True,exist_ok=True)
    pointer=destination/'trial-cases.json'
    source=load(ROOT/'local-validation/development-phase-20cny/gui-cases.json')['cases']
    store=WorkflowStore(ROOT/'workspace-data',allow_workers=False)
    try:
        if pointer.exists():
            value=load(pointer)
            for ident in value['cases'].values():store.get(ident)
            print(json.dumps(value,ensure_ascii=False));return
        cases={}
        for name,parent_id in source.items():
            parent=store._load(parent_id)
            assert parent['intake']['result']['origin_verified'] is True and parent['intake']['status']=='REVIEW'
            state=store._load(store.create('own')['id'])
            state.update(label='用户试用 · '+('完整需求' if name.startswith('complete') else '缺项与冲突')+' · '+name[-2:],
                intake=copy.deepcopy(parent['intake']),trial_material=copy.deepcopy(CARD),
                reused_ai={'source_case_id':parent_id,'source_state_sha256':digest(parent),'new_model_calls':0})
            state['intake']['confirmation']=None
            store._snapshot(state,'archived-real-ai-reuse',state['reused_ai']);store._save(state)
            cases[name]=state['id']
        text=store._load(source['complete-A1'])['intake']['source_text']
        for name,material in [('missing', '\n'.join(line for line in text.splitlines() if '膜厚' not in line)),
                              ('unsupported',text.replace('入射角为0 deg','入射角为15 deg'))]:
            state=store._load(store.create('own')['id'])
            state.update(label='停止场景 · '+('资料缺失' if name=='missing' else '不支持的倾斜入射')+' · 离线规则',
                intake=apply(prepare('STOP-'+name,material),{'type':'intake-review','mode':'mock'}))
            assert not state['intake']['result']['confirmable']
            store._snapshot(state,'offline-stop-fixture',{'actual_llm_calls':0,'is_real_ai':False});store._save(state)
            cases[name]=state['id']
        value={'cases':cases,'new_model_calls':0,'task_approvals':0,'solver_calls':0,
            'primary_trial_url':'http://127.0.0.1:8778/#case='+cases['complete-A1']}
        write_once(pointer,value);print(json.dumps(value,ensure_ascii=False))
    finally:store.close()

if __name__=='__main__':main()
