"""Small local, versioned experiment recipes. No answers or evaluation data."""
from pathlib import Path
import copy,json,re
from ..core import digest

ROOT=Path(__file__).resolve().parents[1]/'case_library'
VERSION='executable-cases-v1'

def catalog():
    rows=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(ROOT.glob('*/*.json'))]
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!=VERSION or {r.get('id'):r.get('version') for r in rows}!=manifest['cases'] or len({r.get('id') for r in rows})!=len(rows):raise ValueError('案例库版本清单不一致')
    required={'id','version','title','domain','scope','required_parameters','numeric_defaults','fixed_parameters','recipe','teaching','metrics','variables','sources','interpretation','tags'}
    if any(not required<=set(r) or r['domain'] not in ('film','diffraction','gaussian') or not isinstance(r['recipe'],dict) for r in rows):raise ValueError('案例结构无效')
    return rows

def missions():
    value=json.loads((ROOT/'missions.json').read_text(encoding='utf-8'))
    known={r['id'] for r in catalog()}
    if value.get('version')!='missions-v1' or len({m['id'] for m in value['missions']})!=len(value['missions']):raise ValueError('任务链清单无效')
    if any(set(m['cases'])-known for m in value['missions']):raise ValueError('任务链引用未知案例')
    return value['missions']

def library_digest():return digest(catalog())

def get_case(ident):
    for row in catalog():
        if row['id']==ident:return copy.deepcopy(row)
    raise ValueError('案例不存在')

def search(query='',domain=None,metric=None,variables=None):
    if not isinstance(query,str) or len(query)>24000:raise ValueError('检索文字无效')
    rows=catalog();query=query.lower()
    if domain:rows=[r for r in rows if r['domain']==domain]
    if metric:rows=[r for r in rows if metric in r['metrics']]
    if variables:rows=[r for r in rows if set(variables)<=set(r['variables'])]
    for r in rows:r['search_score']=sum(1 for term in r['tags']+[r['id'].lower(),r['title']] if term.lower() in query)
    return sorted(rows,key=lambda r:(-r['search_score'],r['id']))

def public_cases(query=''):
    patterns={'film':r'薄膜|膜系|膜厚|单膜|反射率','diffraction':r'双缝|单缝|干涉|条纹|衍射','gaussian':r'高斯|TEM00|束腰|光斑'}
    matches=[d for d,pattern in patterns.items() if re.search(pattern,query,re.I)]
    domain=matches[0] if len(matches)==1 else None
    return [{k:r[k] for k in ('id','version','title','domain','scope','required_parameters','numeric_defaults','fixed_parameters','recipe','teaching','metrics','variables','sources','interpretation')} for r in search(query,domain=domain)]

def unsupported_request(text):
    # Positive unsupported requests; explicit exclusions do not trigger this helper.
    for clause in re.split(r'[。；;,，\n]|但是|但要|而要|而用|but |instead ',text,flags=re.I):
        multiple=re.search(r'(?:同时使用|组合使用|串联|串接|使用|用)\s*(?:两|二|三|四|多|[2-9]\d*)\s*片(?:理想)?(?:薄)?透镜',clause)
        if multiple and not re.search(r'(?:不|不要|无需|禁止|不必)\s*$',clause[:multiple.start()]):
            return '当前高斯模型只支持一片理想薄透镜；多片透镜系统不能用单片模型替代。'
        for match in re.finditer(r'Fresnel|菲涅[耳尔]|牛顿环|迈克尔逊|高NA|高 NA|色散材料|吸收材料|真实镜片像差|自由空间衍射传播|三维|全矢量|\b3D\b',clause,re.I):
            prefix=clause[:match.start()]
            if re.search(r'(?:不要|不考虑|忽略|不研究|不使用|不用|无需|不是|非|without|exclude)\s*(?:(?:使用|采用|计算|研究|考虑|任何|做)\s*)?(?:自由空间\s*)?$',prefix,re.I):continue
            return '该条件超出当前三类案例的模型范围；不会用理想焦平面案例替代。'
    return None
