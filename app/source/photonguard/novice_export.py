"""Export only hash-verified saved solver evidence; no execution during export."""
import io,json,zipfile
from .core import load
from .workflow import WorkflowError
from .runner import verify_evidence

def bundle(store,state,run_id):
    root=store.case_dir(state['id'])/'artifacts'/run_id
    if not verify_evidence(root):raise WorkflowError('运行证据校验失败',409)
    manifest=load(root/'manifest.json');names=list(manifest['files'])+['manifest.json']
    if sum((root/n).stat().st_size for n in names)>128*1024*1024:raise WorkflowError('结果包超过导出上限',413)
    receipt={'kind':'SAVED_REAL_SOLVER_EVIDENCE','run_id':run_id,'case_id':state['id'],
        'template_id':state.get('novice',{}).get('template_id'),'template_source':state.get('novice',{}).get('template_source'),
        'actor_type':state.get('actor_type','UNCLASSIFIED'),'original_script_fixed':False,
        'exported_launcher_status':'NOT_EXECUTED','new_solver_calls':0,'design_goal':'NOT_EVALUATED'}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name in names:z.writestr('evidence/'+name,(root/name).read_bytes())
        for src,dst in [('task.original.json','task.json'),('candidate.original.json','candidate.json'),('task.lock.json','task.lock.json')]:z.writestr(dst,(root/src).read_bytes())
        z.writestr('export.json',json.dumps(receipt,ensure_ascii=False,indent=2))
        z.writestr('README_ZH.txt','这是保存的实际运行证据，含光谱CSV、原始数据、报告、参数与运行环境记录。导出本身不产生新计算。\n复跑需要安装匹配的PhotonGuard及Meep环境，并明确执行以下命令：\npython -m photonguard run task.json candidate.json --lock task.lock.json --out rerun-evidence\n该命令尚未执行；执行后最多8次FDTD，不调用模型。原导入Python脚本未被修改。\n数值PASS仅限已测样点与设置，不代表设计目标已实现。\n')
    return buffer.getvalue()
