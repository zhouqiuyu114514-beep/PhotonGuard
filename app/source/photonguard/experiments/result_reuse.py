"""Re-score verified physical evidence without scheduling a solver."""
import copy,hashlib,json,shutil
from ..core import digest,write_json
from ..workflow import WorkflowError
from .goals import assess,rank

def dependency(plan):
    return {'domain':plan['domain'],'adapter':plan['adapter'],'candidates':plan['candidates'],
            'metric':plan['goal']['metric'],'wavelength_um':plan['goal'].get('wavelength_um') if plan['resource_budget']['max_meep_validations'] else None,
            'verification_count':plan['resource_budget']['max_meep_validations']}

def compatible(plan,old):
    from .fact_state import equal
    a,b=dependency(plan),dependency(old)
    if equal(a,b):return True
    # A point goal may read a subset of already computed TMM samples. Preserve
    # the original arrays and labels; never synthesize an interpolated sample.
    if plan['domain']!='film' or a['verification_count'] or b['verification_count'] or a['metric'] not in ('reflectance','transmittance'):return False
    a=copy.deepcopy(a);b=copy.deepcopy(b)
    if len(a['candidates'])!=len(b['candidates']):return False
    for new,prior in zip(a['candidates'],b['candidates']):
        axis=new['parameters'].pop('wavelengths_um',[]);old_axis=prior['parameters'].pop('wavelengths_um',[])
        if not axis or any(sum(abs(x-y)<=1e-12 for y in old_axis)!=1 for x in axis):return False
    return equal(a,b)

def rescore(store,parent,spec,plan):
    original=parent['result']
    if original.get('status')!='RUN_COMPLETED' or len(original.get('candidates',[]))!=len(parent['plan']['candidates']):return None
    if any('data' not in c or 'metrics' not in c for c in original['candidates']):return None
    parent=store.verified_case(parent['id'])
    from .fact_state import equal
    if parent['result']['status']!='RUN_COMPLETED' or not compatible(plan,parent['plan']):return None
    if any(c.get('all_checks_passed') is not True for c in parent['result']['candidates']):return None
    try:
        for c in parent['result']['candidates']:assess(c,spec['goal'])
    except ValueError:return None
    root=store.get(parent['exploration_root']) if parent.get('exploration_root') else None
    old=store.folder(parent['id'])/'execution'
    estimated=sum(p.stat().st_size for p in old.rglob('*') if p.is_file())+1024*1024
    if root and estimated>root['exploration_ledger']['output_limit_bytes']-root['exploration_ledger']['used_output_bytes']:
        raise WorkflowError('剩余证据空间不足；已算结果保留，不能另领额度')
    child=store.create({'kind':'specified','text':'仅修改目标条件，复用已核对的实际计算；来源结果 '+parent['id']})
    child.update(title=parent['title']+' · 目标重评分',domain=parent['domain'],kind=parent['kind'],
                 parent_id=parent['id'],family_id=parent['family_id'],spec=spec,plan=plan,status='COMPLETED',
                 parent_context={'id':parent['id'],'spec':parent['spec'],'plan_sha256':parent['plan']['sha256']})
    if parent.get('exploration_root'):child['exploration_root']=parent['exploration_root']
    if parent.get('library_origin'):child['library_origin']=copy.deepcopy(parent['library_origin'])
    if parent.get('fact_state'):
        from .dialogue_update import update
        child['fact_state']=update(copy.deepcopy(parent['fact_state']),'用户明确修改目标条件','rescore-'+child['id'],request={'goal':spec['goal']})
        child['session_version']=2
    result=copy.deepcopy(parent['result']);result['plan_sha256']=plan['sha256']
    for row in result['candidates']:
        row['goal']=assess(row,spec['goal'])
        verification=row.get('verification') or {};g=verification.get('goal_meep')
        if g and g.get('value') is not None:
            g.update(operator=spec['goal']['operator'],target=spec['goal'].get('target'))
            v=g['value'];op=g['operator'];t=g['target'];g['met']=v<=t if op=='<=' else v>=t if op=='>=' else abs(v-t)<=spec['goal']['tolerance'] if op=='near' else None
    result['ranking']=rank(result['candidates'],spec['goal']);result['winner_id']=next(iter(result['ranking']),None)
    result['reuse']={'source_id':parent['id'],'source_result_sha256':digest(parent['result']),
                     'dependency_sha256':digest(dependency(plan)),'kind':'GOAL_RESCORE','new_solver_calls':0,'verification_promoted':False,
                     'sampling_relation':'SOURCE_COVERS_REQUESTED_POINTS','actual_arrays_preserved':True,'interpolation_used':False}
    result['resources']={**result['resources'],'fast_evaluations':0,'actual_fdtd_runs':0,'fdtd_attempts_reserved':0,'cache_hits':len(result['candidates']),'model_calls':0,'output_bytes':0}
    result['elapsed_seconds']=0;result['summary']='复用已有实际数值，仅重新判定目标；没有新增物理计算或性能提升。'
    out=store.folder(child['id'])/'execution';shutil.copytree(old,out)
    write_json(out/'plan.json',plan)
    for _ in range(6):
        write_json(out/'result.json',result)
        files={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'}
        write_json(out/'manifest.json',{'schema_version':1,'plan_sha256':plan['sha256'],'files':files})
        size=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        if result['resources']['output_bytes']==size:break
        result['resources']['output_bytes']=size
    else:raise WorkflowError('复用结果空间计数未稳定')
    if root:
        ledger=root['exploration_ledger']
        if size>ledger['output_limit_bytes']-ledger['used_output_bytes']:raise WorkflowError('复用证据超过剩余空间')
        ledger['used_output_bytes']+=size;store.save(root)
    child['result']=result;child['reuse']=result['reuse'];store.save(child)
    store.event(child,'VERIFIED_RESULT_RESCORED',result['reuse']);return child
