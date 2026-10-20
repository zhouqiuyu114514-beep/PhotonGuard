"""One pure user-task projection for UI, exports and model tool receipts."""
from . import inverse_models as m,research_actions as ra


def chart_svg(chart):
    """Use the existing portable result renderer with this same saved projection."""
    from .summary_html import curve_svg
    return curve_svg(chart) if chart else ''


PARAMS={'slit_width_um':('缝宽','μm'),'slit_separation_um':('缝距','μm'),
        'waist_radius_um':('束腰半径','μm'),'waist_z_mm':('束腰位置','mm'),'thickness_nm':('膜厚','nm')}
GOALS={'balanced':'兼顾各项参数','width':'优先缝宽','separation':'优先缝距','prediction':'关注指定区间的预测',
       'waist_radius':'优先束腰半径','waist_position':'优先束腰位置'}
WARNINGS={'INSUFFICIENT_FRINGE_COVERAGE':'当前扫描覆盖的条纹不足','INSUFFICIENT_WIDTH_COVERAGE':'当前扫描没有充分覆盖缝宽包络',
          'MULTIPLE_PROFILE_CANDIDATES':'仍有多个可保留的参数候选','UNRESOLVED_PROFILE_POINTS':'部分参数检查点未完成，不能据此排除',
          'LOCAL_RANK_DEFICIENT':'当前资料不能稳定区分所有待估量','BOUNDARY_ESTIMATE':'有参数估计靠近允许范围边界',
          'NUMERICAL_SCALE_ONLY':'可计算，但尚无测量噪声依据',
          'MULTIPLE_THICKNESS_MODES':'当前数据对应多组相容膜厚',
          'SINGLE_WAVELENGTH_PERIODIC_AMBIGUITY':'单一波长下存在周期性膜厚多解'}
NEEDS={'FIT_RESULT':'先完成已有数据分析','SAVED_EXECUTABLE_PROPOSAL':'先生成可执行的观测方案',
       'OBSERVATION_REVIEW':'先在下方核对各次采集条件、估计范围与数据尺度',
       'DECLARED_ACQUISITION_CONSTRAINTS':'补充允许的观测范围与条件','ROOT_BUDGET_EXHAUSTED':'本任务对应额度已用完',
       'FACT_PATCH_REJECTED':'条件修改未通过核对','FACTS_NEED_REVIEW':'先核对新的物理条件','REGENERATE_PROPOSAL':'条件已变，请重新比较',
       'HARD_CONSTRAINT_VIOLATION':'该方案超过当前硬限制'}
PRODUCTS={'compare_acquisition':'一份包含基础扫描与有限备选的比较','choose_baseline':'已选定基础扫描的具体计划',
          'propose_followup':'选定观测位置或波长及后续步骤','refit':'一份有限拟合计划','explain':'对已保存结果的解释',
          'clarify_fact':'缺少条件的核对清单','inspect_observation':'需要核对的观测条件','request_calibration':'独立参照和暗场资料要求','stop':'保留结果并暂停当前分支'}


def advice(s):
    b=s.get('research_actions') or {}
    if not ra.current(s,b):return {'primary':None,'alternatives':[],'source':'NONE','message':'可询问 AI，或按下方程序导航继续。'}
    all_actions=b.get('actions',[]);selected=next((a for a in all_actions if a['id']==b.get('primary_action_id')),None)
    source=('MODEL_EXPLICIT_SELECTION' if b.get('source_kind')=='LIVE_AI' else 'RECORDED_MODEL_SELECTION') if selected and b.get('primary_selection_source')=='MODEL_EXPLICIT_SELECTION' else 'PROGRAM_NAVIGATION'
    if not selected:
        # A transparent navigation default, never a model ranking or optimum.
        ready=[a for a in all_actions if a['status']=='SUGGESTED_ONLY']
        selected=next((a for a in ready if a['type'] in ('compare_acquisition','propose_followup','choose_baseline','refit')),None) or next(iter(ready or all_actions),None)
    def row(a):
        return {'id':a['id'],'kind':a['type'],'label':a['label'],'reason':a['reason'],'proposal_id':a['proposal_id'],
                'product':PRODUCTS[a['type']],'needs':[NEEDS.get(k,k) for k in a['required_before_execution']],
                'ready':a['status']=='SUGGESTED_ONLY','next_confirmation':'核对具体计划与资源后，单独批准执行' if a['type'] in ('compare_acquisition','refit','choose_baseline','propose_followup') else '只读核对，不启动计算'}
    availability=ra.proposal_availability(s)
    blocked=next((p for p in availability['blocked_proposals'] if selected and p['id']==selected['proposal_id'] and selected['type'] in ('choose_baseline','propose_followup')),None)
    # Preserve the actual model choice; these are separately labelled program options.
    feasible=[{'id':p['id'],'label':p.get('label') or p['id'],'cost':p.get('cost'),
               'range_mm':p.get('range_mm'),'wavelengths_nm':p.get('wavelengths_nm'),
               'note':p.get('selection_reason') or p.get('cost_note'),'source':'PROGRAM_FEASIBILITY_LIST'}
              for p in (s.get('measurement_plan') or {}).get('plans',[]) if blocked and p['id'] in availability['currently_feasible_proposal_ids']]
    return {'primary':row(selected) if selected else None,'alternatives':[row(a) for a in all_actions if selected and a['id']!=selected['id']][:2],
            'blocked_primary':blocked,'feasible_alternatives':feasible,
            'feasible_alternatives_note':('程序按当前保存计划列出可行备选，未排序、未代替 AI 选择；仍需你核对并批准。也可停止，不必补采。' if feasible else '当前保存计划没有可行备选；可澄清条件或停止，不自动放宽限制。') if blocked else None,
            'source':source,'suggestion_sha256':b.get('sha256'),'message':{'MODEL_EXPLICIT_SELECTION':'AI 明确选择的主要下一步','RECORDED_MODEL_SELECTION':'已保存模型回复的选择；本次没有调用 AI'}.get(source,'程序按当前进度提供导航；没有将备选作优劣排名')}


def summary(s):
    from .task_flow import current
    r=s.get('inverse_result') or {};model=s['inverse_settings']['model'];source_kinds={g['dataset']['source_kind'] for g in s.get('groups',[])}
    source='教学模拟观测' if source_kinds=={'SYNTHETIC_TEACHING'} else '混合来源（含教学资料）' if 'SYNTHETIC_TEACHING' in source_kinds else '用户提供的观测资料'
    goal=GOALS.get(s.get('research_goal',{}).get('target'),'区分允许范围内的膜厚候选' if model==m.FILM else s.get('task_goal_text') or '分析已有观测，再决定下一步')
    values=[];previous=(s.get('acquisition_expectation') or {}).get('previous_estimates') or {}
    for key,(label,unit) in PARAMS.items():
        value=r.get('estimated_parameters',{}).get(key)
        if value is not None:values.append({'parameter':key,'label':label,'value':value,'unit':unit,'previous':previous.get(key),'change':value-previous[key] if key in previous else None})
    count=len(r.get('modes',[])) if model==m.FILM and r else None
    before=(s.get('comparison_origin') or {}).get('previous_mode_count')
    headline=(f'当前搜索范围保留 {count} 组厚度候选' if model==m.FILM else '；'.join(f'{v["label"]}估计 {v["value"]:.5g} {v["unit"]}' for v in values)) if r else '已有资料已保存，尚未完成分析'
    change=(f'候选数量由 {before} 变为 {count}；仅限当前搜索范围' if before is not None and count is not None else
            '；'.join(f'{v["label"]}变化 {v["change"]:+.4g} {v["unit"]}' for v in values if v['change'] is not None)) or '本版本暂无可比较的上一份结果'
    chart=None
    if model==m.FILM and r:
        modes=sorted(r.get('modes',[]),key=lambda v:v['parameters']['thickness_nm'])
        chart={'x':[v['parameters']['thickness_nm'] for v in modes],'x_label':'候选膜厚（nm）','y_label':'拟合代价',
               'series':[{'label':'当前范围保留候选','y':[v['cost'] for v in modes],'points':True}]}
    elif r.get('data'):
        d=r['data'][-1];chart={'x':d['x'],'x_label':'位置（mm）','y_label':'1/e² 半径（μm）' if model==m.GAUSSIAN else '相对强度',
            'series':[{'label':source+'（最近一次采集）','y':d['observed'],'points':True},{'label':'模型拟合','y':d['predicted']} ]}
    advice_view=advice(s);receipt=s.get('task_execution') or {};origin=s.get('research_origin') or {}
    # Legacy imported follow-ups can retain their parent's selection marker.
    received=bool(s.get('comparison_origin') and (s.get('acquisition_expectation') or {}).get('proposal_sha256')==origin.get('plan_sha256') and origin.get('plan_sha256'))
    if s['status']=='RUNNING':state,label='RUNNING','运行中'
    elif receipt.get('status')=='PAUSED' or s['status']=='FAILED':state,label='PAUSED','已暂停，保留资料'
    elif origin.get('kind')=='stop' and ra.current(s):state,label='STOPPED','已停止当前分支'
    elif current(s) or s.get('inverse_plan') and s['status']=='PLANNED':state,label='READY','计划待核对与批准'
    elif origin.get('status')=='ACQUISITION_SELECTED' and not received and not s.get('teaching_object'):state,label='WAITING_DATA','等待你上传新观测'
    elif r:state,label='RESULT','已有结果'
    else:state,label='NEEDS_INFORMATION','核对已有条件'
    return {'schema':'photonguard.user-task-view.v1','goal':goal,'original_request':s.get('task_goal_text'),'source_label':source,
        'state':state,'state_label':label,'headline':headline,'parameters':values,'mode_count':count,'previous_mode_count':before,'change':change,'chart':chart,
        'warnings':[WARNINGS.get(w,w) for w in r.get('warnings',[])],
        'scope':'结果是当前理想模型内的估计；教学不等于实测，参数变化不等于真实误差下降。',
        'advice':advice_view,'task_plan_current':current(s),'pause_reason':receipt.get('reason') or s.get('task_pause_reason') or s.get('error'),
        'editable':['研究目标与取舍','允许的补采范围和数量','新增观测资料','另存并更正物理条件'],
        'confirmed_conditions':{'fixed':s['inverse_settings']['fixed'],'estimated_ranges':s['inverse_settings']['bounds'],'constraints':s.get('acquisition_constraints'),
            'preferences':s.get('decision_preferences'),'data_groups':len(s.get('groups',[]))},
        'receipt':receipt,'numerical_plan':{k:v for k,v in (s.get('inverse_plan') or {}).items() if k in ('operation','sha256','budget')},
        'continuous_plan':{k:v for k,v in (s.get('task_plan') or {}).items() if k in ('id','sha256','operation','proposal_id','steps','resources','stop_conditions','new_entry','approval')}}
