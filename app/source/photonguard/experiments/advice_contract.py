"""One public JSON contract and its deliberately small, dependency-free validator.

The validator implements only the JSON Schema keywords used below; it never
repairs a model response. The host owns all request/version bindings.
"""
import copy
import math
from .research_actions import TYPES


def obj(properties):
    return {'type':'object','additionalProperties':False,'required':list(properties),'properties':properties}


def text(maximum=500,minimum=0):return {'type':'string','minLength':minimum,'maxLength':maximum}
def array(item,maximum,**kw):return {'type':'array','maxItems':maximum,'items':item,**kw}

UPDATE=obj({'id':text(32,1),'field':text(100,1),
    'value':{'oneOf':[{'type':'number'},text(100),{'type':'boolean'},array({'type':['number','string']},64)]},
    'quote':text(1000,1),'correction':{'type':'boolean'}})
SUGGESTION=obj({'kind':{'enum':list(TYPES)},'reason':text(500,1),
    'evidence_refs':array(text(32,1),8,uniqueItems=True),
    'fields':array(text(100,1),8,uniqueItems=True),
    'proposal_id':{'type':['string','null'],'maxLength':100},
    'depends_on':array(text(32,1),20,uniqueItems=True)})
SUGGESTION['properties']['id']=text(32,1)  # optional for saved v2-compatible replies
SCHEMA={'$schema':'https://json-schema.org/draft/2020-12/schema',
    '$id':'urn:photonguard:research-advice:v3',**obj({'updates':array(UPDATE,20),
    'focus':{'enum':['overview','parameters','residuals','limitations','measurement','forward']},
    'suggestions':array(SUGGESTION,4)})}
SCHEMA['properties']['primary_suggestion_id']={'type':['string','null'],'maxLength':32}


def check(schema,value,path='$',*,envelope=False):
    if 'oneOf' in schema:
        passed=0
        for branch in schema['oneOf']:
            try:check(branch,value,path);passed+=1
            except ValueError:pass
        if passed!=1:raise ValueError(path+': 值类型不符')
        return
    if 'enum' in schema and value not in schema['enum']:raise ValueError(path+': 不支持的选项')
    kinds=schema.get('type',[]);kinds=[kinds] if isinstance(kinds,str) else kinds
    matches={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),
        'number':type(value) in (int,float) and math.isfinite(value),'boolean':type(value) is bool,'null':value is None}
    if kinds and not any(matches.get(k,False) for k in kinds):raise ValueError(path+': 类型不符')
    if isinstance(value,str) and not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',100000):raise ValueError(path+': 文本长度无效')
    if isinstance(value,dict):
        props=schema['properties']
        if set(schema['required'])-set(value) or schema.get('additionalProperties') is False and set(value)-set(props):raise ValueError(path+': 缺少字段或带有额外字段')
        for k,v in value.items():check(props[k],v,path+'.'+k,envelope=envelope)
    if isinstance(value,list):
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',100000):raise ValueError(path+': 条目数量无效')
        if schema.get('uniqueItems') and any(v in value[:i] for i,v in enumerate(value)):raise ValueError(path+': 条目重复')
        if not envelope:
            for i,v in enumerate(value):check(schema['items'],v,path+f'[{i}]')


def fixture(kind='explain',evidence='E0',proposal=None):
    answer={'updates':[],'focus':'overview','primary_suggestion_id':'S_'+kind,'suggestions':[{'id':'S_'+kind,'kind':kind,
        'reason':'根据已保存资料核对下一步；这只是建议，尚未执行。',
        'evidence_refs':[evidence],'fields':[],'proposal_id':proposal,'depends_on':[]}]}
    check(SCHEMA,answer);return copy.deepcopy(answer)


def public_contract():
    """Prompt, offline examples and receiver refer to these exact objects."""
    return {'schema':copy.deepcopy(SCHEMA),'valid_example':fixture(),
        'action_meanings':dict(zip(TYPES,('询问缺少条件','生成有限方案比较','选择已保存基础方案',
        '查看当前观测条件','请求独立参照和暗场资料','准备拟合计划','选择已有计划安排补采',
        '解释已有证据','结束当前分支')))}
