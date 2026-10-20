"""Small, explicit goal/data/teaching router, not a new workflow engine."""
import re
from ..workflow import WorkflowError
from . import inverse_models as m


def route(text,mode=None):
    if mode not in (None,'forward','inverse'):raise WorkflowError('请选择比较已知参数或从观测反推')
    inverse=bool(re.search(r'反演|反推|拟合|CSV|csv|已有数据|测量数据|观测数据|补测|补采|未知.{0,8}(?:缝宽|膜厚|束腰)',text))
    forward=bool(re.search(r'已知参数|正向|比较.{0,8}(?:镜片|透镜|焦距|设计)|设计目标',text))
    choice=mode or ('inverse' if inverse and not forward else 'forward' if forward and not inverse else None)
    found=[model for pattern,model in ((r'束腰|高斯|光束',m.GAUSSIAN),(r'薄膜|膜厚|反射率',m.FILM),(r'双缝|缝宽|缝距|干涉',m.SLIT)) if re.search(pattern,text)]
    return {'mode':choice,'model':found[0] if len(found)==1 else None,'source':'PROGRAM_ROUTING_NOT_AI',
            'reason':'根据明确的任务词判断；没有判断参数值或补充物理事实。'}


def start(store,data):
    from .observation_group import create
    from ..workflow_model import wire
    allowed={'text','mode','model','teaching','csv_text','source_kind','source_name','license','position_unit','diameter_conversion'}
    if not isinstance(data,dict) or set(data)-allowed:raise WorkflowError('开始任务的字段无效')
    text=data.get('text','')
    if not isinstance(text,str) or len(text)>6000 or wire.credential_risk(text):raise WorkflowError('请填写不含密钥的目标（最多6000字）')
    if 'teaching' in data and type(data['teaching']) is not bool:raise WorkflowError('教学模式需明确选择')
    if data.get('teaching'):
        if data.get('model') not in m.MODELS or data.get('csv_text') is not None:raise WorkflowError('请明确选择教学任务；真实数据不能自动替换为教学对象')
        s=create(store,{'model':data['model'],'teaching':True});decision={'mode':'inverse','model':data['model'],'source':'EXPLICIT_TEACHING_SELECTION'}
    else:
        decision=route(text,data.get('mode'))
        if data.get('csv_text') is not None:
            if data.get('mode')=='forward':raise WorkflowError('数据反向分析与正向比较分开开始')
            decision['mode']='inverse'
        if decision['mode'] is None:
            return {'status':'NEEDS_INTENT','question':'这次是比较已知参数的方案，还是从已有观测反推未知参数？','text':text,'route':decision}
        if decision['mode']=='inverse':
            model=data.get('model') or decision['model']
            if data.get('csv_text') is None:return {'status':'NEEDS_DATA','text':text,'route':decision,'model':model,'question':'导入已有观测；未知物理条件会留待核对。'}
            if model not in m.MODELS:raise WorkflowError('请明确数据对应的光学场景')
            s=create(store,{k:v for k,v in data.items() if k in {'csv_text','source_kind','source_name','license','position_unit','diameter_conversion'}}|{'model':model})
        else:s=store.create({'kind':'specified','text':text})
    s['task_goal_text']=text;s['task_entry']={'route':decision,'teaching_explicit':data.get('teaching') is True}
    if text:s['text']=text
    store.save(s);return {'status':'CREATED','case':store.public_record(s),'route':decision,'model_calls':0}
