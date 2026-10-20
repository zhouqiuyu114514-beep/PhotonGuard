"""Reusable result tables derived only from saved numerical records."""
from __future__ import annotations
import csv
import io
import json
import math
from ..core import digest


def metric_source(candidate, domain):
    goal=candidate.get('goal') or {}
    if goal.get('source'):return goal['source']
    engine=candidate.get('engine',{})
    engine=engine.get('name','') if isinstance(engine,dict) else str(engine)
    metric=goal.get('metric','')
    if domain=='film':kind,label='TMM_SAMPLE','TMM实际采样'
    elif domain=='gaussian':kind,label='GAUSSIAN_Q_ABCD','高斯q参数与ABCD计算'
    elif metric in ('fringe_period_mm','first_zero_mm'):kind,label='ANALYTIC_GEOMETRY','理想几何公式；另有二维场数值校准'
    else:kind,label='FFT_CENTER_FIELD','二维场中心光强与同几何零相位基准之比'
    return {'kind':kind,'label':label,'engine':engine,'legacy_display_inference':True}


def table_records(state):
    result=state.get('result') or {};ranking=result.get('ranking',[])
    records=[]
    for c in result.get('candidates',[]):
        g=c.get('goal') or {};v=c.get('verification') or {};mg=v.get('goal_meep') or {}
        source=metric_source(c,state['domain'])
        records.append({'candidate_id':c['id'],'rank':ranking.index(c['id'])+1 if c['id'] in ranking else None,
            'changes':c.get('changes',{}),'status':c.get('status'),'numeric_checks_passed':c.get('all_checks_passed'),
            'metric':g.get('metric'),'value':g.get('value'),'unit':g.get('unit'),
            'source_kind':source['kind'],'source_label':source['label'],'engine':source.get('engine'),
            'operator':g.get('operator'),'target':g.get('target'),'goal_met':g.get('met'),
            'meep_value':mg.get('value'),'meep_metric':mg.get('metric'),
            'meep_numerical_status':v.get('numerical_status'),'meep_goal_met':mg.get('met')})
    return records


def _csv(headers, rows):
    def cell(v):
        if v is None:return ''
        if isinstance(v,(dict,list)):v=json.dumps(v,ensure_ascii=False,sort_keys=True)
        # Prevent formulas in names/free text when a downloaded table is opened.
        if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')):return "'"+v
        return v
    out=io.StringIO(newline='');writer=csv.writer(out);writer.writerow(headers)
    for row in rows:writer.writerow([cell(v) for v in row])
    return out.getvalue().encode('utf-8-sig')


TABLE_FIELDS=('candidate_id','rank','changes','status','numeric_checks_passed','metric','value','unit',
              'source_kind','source_label','engine','operator','target','goal_met',
              'meep_value','meep_metric','meep_numerical_status','meep_goal_met')


def comparison_csv(state):
    return _csv(TABLE_FIELDS,([r[k] for k in TABLE_FIELDS] for r in table_records(state)))


def curve_csv(state):
    rows=[]
    for c in (state.get('result') or {}).get('candidates',[]):
        d=c.get('data') or {}
        for series in d.get('series',[]):
            for x,y in zip(d.get('x',[]),series.get('y',[])):
                rows.append((c['id'],series.get('label',''),d.get('x_label',''),x,d.get('y_label',''),y))
    return _csv(('candidate_id','series','x_label','x','y_label','y'),rows)


def report_record(state):
    result=state.get('result') or {}
    return {'schema_version':1,'case_id':state['id'],'domain':state['domain'],'goal':(state.get('plan') or {}).get('goal'),
            'assumptions':(state.get('plan') or {}).get('assumptions',[]),
            'winner_id':result.get('winner_id'),'candidates':table_records(state),
            'resources':result.get('resources',{}),'limitations':result.get('limitations',[]),
            'numeric_source':'Saved execution/result.json; no model-generated numbers',
            'scope':'Finite candidates and specified ideal model; numerical checks and design goals are separate.',
            'parent_comparison':state.get('parent_comparison')}


def compare_versions(parent, child):
    """Pair only identical computed configurations and the same metric/plane."""
    pg=(parent.get('plan') or {}).get('goal') or {};cg=(child.get('plan') or {}).get('goal') or {}
    if not parent.get('result'):return {'status':'PARENT_HAS_NO_RESULT','rows':[]}
    compatible=(parent['domain']==child['domain'] and pg.get('metric')==cg.get('metric') and pg.get('wavelength_um')==cg.get('wavelength_um'))
    if not compatible:return {'status':'DIFFERENT_METRIC_OR_WAVELENGTH','rows':[]}
    old={digest(c.get('parameters')):c for c in parent['result'].get('candidates',[])}
    rows=[]
    for c in child['result'].get('candidates',[]):
        previous=old.get(digest(c.get('parameters')))
        if not previous or not c.get('goal') or not previous.get('goal'):continue
        before,after=previous['goal'],c['goal']
        if before.get('unit')!=after.get('unit'):continue
        rows.append({'candidate_id':c['id'],'previous_candidate_id':previous['id'],
                     'previous_value':before['value'],'value':after['value'],'unit':after['unit'],
                     'difference':after['value']-before['value'],
                     'previous_goal_met':before['met'],'goal_met':after['met'],
                     'both_numeric_checks_passed':previous.get('all_checks_passed') is True and c.get('all_checks_passed') is True})
    return {'status':'SAME_CONFIGURATIONS_AND_METRIC','parent_id':parent['id'],'previous_goal':pg,'goal':cg,'rows':rows}


def result_brief(record, parent=None):
    """Read-only explanation of this saved finite experiment; never invokes AI/tools."""
    rows=table_records(record);goal=(record.get('spec') or {}).get('goal') or {}
    valid=[r for r in rows if r['numeric_checks_passed'] is True and isinstance(r['value'],(int,float)) and math.isfinite(r['value'])]
    best=min(valid,key=lambda r:r['rank'] if r['rank'] is not None else float('inf')) if valid else None
    fmt=lambda n:format(n,'.7g') if isinstance(n,(int,float)) else str(n)
    unit=(best or next(iter(rows),{})).get('unit') or goal.get('unit','')
    unit={'um':'μm'}.get(unit,unit);op=goal.get('operator');target=goal.get('target');tol=goal.get('tolerance',0)
    label={'screen_radius_um':'屏幕光斑半径','fringe_period_mm':'条纹周期','first_zero_mm':'第一暗纹位置','central_intensity_ratio':'中心强度比','reflectance':'反射率','transmittance':'透射率'}.get(goal.get('metric'),goal.get('metric','目标指标'))
    goal_text=label+' '+({'near':f'{fmt(target)} ± {fmt(tol)}','<=':f'≤ {fmt(target)}','>=':f'≥ {fmt(target)}','minimize':'在目录中取最小值','maximize':'在目录中取最大值'}.get(op,'待核对'))+' '+unit
    met=sum(r['goal_met'] is True for r in valid);gap=None;deviation=None
    if best and isinstance(target,(int,float)):
        deviation=abs(best['value']-target)
        if op=='near':gap=max(0,deviation-tol)
        elif op=='<=':gap=max(0,best['value']-target)
        elif op=='>=':gap=max(0,target-best['value'])
    changes={'slit_separation_um':('缝距','μm'),'focal_length_mm':('焦距','mm'),'thickness_nm':('厚度','nm'),'relative_phase_rad':('相对相位','rad')}
    choice='、'.join((changes.get(k,(k,''))[0]+' '+fmt(v)+' '+changes.get(k,(k,''))[1]).strip() for k,v in (best or {}).get('changes',{}).items())
    selected=(choice or (best or {}).get('candidate_id','暂无可确认候选'))
    value=(fmt(best['value'])+' '+unit) if best else '无可确认数值'
    headline=(f'{selected} 是本目录内的优选，{label}为 {value}。' if op in ('minimize','maximize') else f'{len(rows)} 个候选中，{met} 个达到目标；{selected} 最接近，实际值 {value}。') if best else '暂无通过数值检查的有效候选，请查看运行与检查记录。'
    scope='结论限于本次候选和指定理想模型，不代表所有方案的可行性。'
    why=(f'依据已保存的候选排名，{selected} 为第 {best["rank"]} 名；{label}为 {value}。指标来源：{best["source_label"]}。' if best else headline)
    unmet=(f'目录内已有 {met} 个候选达到目标。' if met else f'本目录尚无达到目标的候选。最佳已测值为 {value}，目标是{goal_text}。'+(f'距判据边界还差 {fmt(gap)} {unit}。' if gap is not None else ''))+' '+scope
    receipt=record.get('command_receipt') or {};action=(receipt.get('command') or {}).get('action')
    operation='restore' if action=='restore' else 'rescore' if record.get('reuse') else 'saved_computation'
    resources=(record.get('result') or {}).get('resources',{})
    calculation=('当前恢复到已保存的精确版本；本次恢复没有重新求解。' if operation=='restore' else '本版复用已有实际采样，只重新判断目标；新增求解为 0，物理数值没有改善。' if operation=='rescore' else '本版来自已保存的实际计算；查看、解释或导出不会重新求解。')
    comparison=None
    if parent and parent.get('result'):
        same_samples=(parent.get('plan') or {}).get('goal_sampling_points')==(record.get('plan') or {}).get('goal_sampling_points')
        comparison=compare_versions(parent,record) if same_samples else {'status':'DIFFERENT_SAMPLING','rows':[]}
    changed=('与来源版的同参数、同采样、同指标候选可直接比较；只改判据不会改善物理结果。' if comparison and comparison.get('rows') else '没有可直接配对的来源结果；不把不同参数或采样的数值作同条件增减比较。')
    if parent:
        previous=(parent.get('spec') or {}).get('goal') or {}
        edits=[f'{key}：{fmt(previous.get(key))} → {fmt(value)}' for key,value in goal.items() if previous.get(key)!=value]
        if edits:changed='本版目标变化：'+'；'.join(edits)+'。'+changed
    if operation=='restore':changed='已恢复原目标 '+goal_text+' 与对应的实际结果；后续草稿和其他版本仍保留。'
    next_text='可以保持物理条件重评目标、恢复已保存版本、导出证据，或明确另建探索。改变目录或物理条件须核对新计划并批准；修改目标阈值不等于改善光学性能。'
    return {'schema_version':1,'record_id':record['id'],'result_sha256':digest(record['result']) if record.get('result') else None,'goal':goal,'goal_text':goal_text,'headline':headline,'best':best,'best_label':selected,'candidate_count':len(rows),'valid_count':len(valid),'met_count':met,'unit':unit,'absolute_deviation':deviation,'unmet_gap':gap,'operation':operation,'resources':resources,'comparison':comparison,'fixed_conditions':(record.get('spec') or {}).get('known_parameters',{}),'scope':scope,
        'answers':{'why_selected':why,'why_not_met':unmet,'what_changed':changed,'new_calculation':calculation,'next_step':next_text},'next_actions':['revise_goal','restore_result','explore_case','export'],'basis':'程序从当前保存的实际候选生成；不是新的模型回答或新求解'}
