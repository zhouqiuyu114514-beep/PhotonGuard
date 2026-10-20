"""Three-step local workflow; credentials in server memory only."""
import argparse
import copy
from datetime import datetime,timezone
import getpass
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photonguard.core import load
from photonguard.development_phase import PHASE
from photonguard.repair_diagnosis import RepairBroker,prepare_binding
from photonguard.repair_pipeline import ThreeStepPipeline,ACTIVE
from photonguard.workflow import make_server,write_once
from photonguard.workflow_intake import prepare,apply

DESTINATION=Path('/home/zhou/projects/PhotonGuard-development/local-validation/ai-repair-release')
TEXT='''空间维度为1D。
入射角为0 deg。
相对磁导率为1。
所有介质无损。
所有介质各向同性。
所有介质无色散。
膜层数量为1。
入射折射率为1。
膜层折射率为3.4。
出射折射率为1。
膜厚为800 nm。
真空波长下界为800 nm。
真空波长上界为1100 nm。
等波长采样点数为35。'''
OPTIONS={'units_um':1,'linear':True,'field_component':'Ex',
    'mapping_source':'独立公开合成任务卡NR-v2：1Meep单位=1微米，线性介质、正入射Ex，保留35个等波长点。',
    'accept_sampling':True,'accept_decimal_projection':True,
    'background':'公开合成单膜光谱数值检查练习','goal':'验证给定脚本的数值设置能否可靠满足独立单膜任务',
    'role':'审阅需求、批准具体修改与复验的学习者'}

def seed_trials(store):
    pointer=store.root/'repair-trials.json'
    if pointer.exists():
        value=load(pointer)
        for ident in value['cases'].values():store.get(ident)
        return value
    source=(ROOT/'examples/script_import/numerical_film_scan.py').read_text()
    cases={}
    for mode in ('live','rules'):
        state=store._load(store.create('own')['id'])
        state.update(label='三步试用 · '+('真实AI诊断' if mode=='live' else '规则诊断'),three_step=True,
            intake=apply(prepare('NR-v2',TEXT),{'type':'intake-review','mode':'mock'}),
            repair_trial={'source':source,'options':copy.deepcopy(OPTIONS),'mode':mode,'synthetic':True})
        assert state['intake']['result']['confirmable']
        store._snapshot(state,'independent-public-task-card',{'original':TEXT,'options':OPTIONS,
            'actual_intake_model_calls':0,'new_model_calls':0,'rule_output_not_sent_to_model':True})
        store._save(state);cases[mode]=state['id']
    value={'cases':cases,'same_task_and_script':True,'same_ui':True,'same_solver_and_thresholds':True,
        'new_requests':0,'task_approved':False,'first_case_url':'http://127.0.0.1:8778/#case='+cases['live']}
    write_once(pointer,value);return value

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--official-rates-verified-at')
    parser.add_argument('--rules-only',action='store_true')
    parser.add_argument('--research-stage',action='store_true',help='保留累计20元账本，增加新开发12次/5元软限')
    parser.add_argument('--mode-qpm',action='store_true',help='开启明确标识、零模型调用的MPB/QPM实验入口')
    parser.add_argument('--mode-ai',action='store_true',help='开启已有真实模态证据的受约束AI诊断；复验仍须批准')
    parser.add_argument('--data',type=Path,default=ROOT/'workspace-data')
    parser.add_argument('--binding',type=Path,default=DESTINATION)
    parser.add_argument('--port',type=int,default=8778)
    args=parser.parse_args()
    if args.prepare:
        value=prepare_binding(ROOT,PHASE,args.binding,args.official_rates_verified_at,research_stage=args.research_stage,mode_ai=args.mode_ai)
        print(json.dumps({'source_commit':value['source']['git_commit'],'budget_cny':'20',
            'carried_attempts':value['carried_attempts'],'carried_reserved_cny':value['carried_reserved_cny'],
            'financial_ledger_reset':False},ensure_ascii=False));return
    from photonguard.service_identity import identity,require_match
    service_identity=identity(ROOT,args.data,mode='RULES_ONLY' if args.rules_only else 'LIVE_REPAIR',mode_qpm=args.mode_qpm or args.mode_ai)
    # Reuse requires exact source, data and mode identity.
    try:
        with urlopen(f'http://127.0.0.1:{args.port}/api/bootstrap',timeout=1) as response:existing=json.load(response)
    except (OSError,ValueError):existing=None
    if existing is not None:
        require_match(service_identity,existing)
        print(f'Existing matching service: http://127.0.0.1:{args.port}/',flush=True);return
    broker=None;key=None
    if args.mode_ai and args.rules_only:raise ValueError('真实模态AI需要当前真实服务与明确源码/范围绑定；不能标作规则版。')
    if not args.rules_only:
        RepairBroker(ROOT,PHASE,args.binding,None)
        if not sys.stdin.isatty():raise ValueError('Hidden memory credential needs terminal')
        key=getpass.getpass('DeepSeek credential (hidden; memory only): ')
        broker=RepairBroker(ROOT,PHASE,args.binding,lambda:key)
    with make_server(args.data,port=args.port,allow_workers=True) as server:
        server.store.service_identity=service_identity
        controller=ThreeStepPipeline(server.store,broker);server.store.pipeline_controller=controller
        if args.mode_qpm or args.mode_ai:
            from photonguard.mode_pipeline import ModePipeline
            from photonguard.mode_diagnosis import ModeBroker
            server.store.mode_controller=ModePipeline(server.store,ModeBroker(broker) if args.mode_ai else None)
        # A service restart records an interruption but never repeats a request or repair.
        for item in server.store.list_cases():
            state=server.store._load(item['id'])
            if state.get('pipeline',{}).get('status') in ACTIVE:
                state['pipeline'].update(status='INTERRUPTED',message='服务曾中断；旧作业与费用保留，没有自动请求或续修。')
                server.store._save(state)
        trials=seed_trials(server.store)
        print(json.dumps({'url':f'http://127.0.0.1:{args.port}/','trial_cases':trials['cases'],
            'credential_in_process_memory_only':bool(key),'automatic_requests':False},ensure_ascii=False),flush=True)
        try:server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:pass
    key=None

if __name__=='__main__':main()
