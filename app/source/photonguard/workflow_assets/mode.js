'use strict';
window.PhotonGuardMode=(()=>{
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const button=(text,fn)=>{const b=el('button',text,'button');b.type='button';b.onclick=fn;return b;};
  const details=(title,value)=>{const e=el('details');e.append(el('summary',title),el('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));return e;};
  function diagnosisSummary(d,mode){
    const c=d?.explanation_audit_status==='VERIFIED_STRUCTURED_CLAIMS'&&d.explanation_audit?.accepted?.find(c=>c.claim_type==='mode_interpretation');
    const actor=mode==='live'?'AI':'规则';
    if(d?.status!=='REJECTED'&&c?.conclusion==='phase_precision_insufficient')return actor+'依据已核验数据判断：当前数值差异对器件相位的影响超过精度限值。'+(d.patch?'可尝试卡片中的数值修改，不能承诺通过。':(d.independent_resource_scope_note||'本次没有提出可执行修改；原任务与验收状态保持不变。'));
    if(d?.status!=='REJECTED'&&c?.conclusion==='locked_design_not_met')return actor+'依据已核验数据判断：计算检查通过，但锁定的器件参数没有达到设计目标。制造周期、长度或目标的修改需要另立任务。';
    return d?.reason?.length<=260?d.reason:'逐项数值断言已保留在下方；建议合法性与实际复验结论分别报告。';
  }
  function create(s,h){
    const f=s.adapter_flow,host=el('section',null,'three-step-workspace');host.append(el('h1','确认需求 → 查看诊断与建议 → 批准修复并看复验'),el('p','模态与相位匹配研究：公开合成教学结构，真实AI可根据实际证据提出数值修复。器件尺寸、制造周期、目标与验收阈值均保持锁定；不会默认套用到你的真实铌酸锂器件。','info-box warning'));
    const archive=el('a','查看原合成案例的证书与新设计研究档案','button secondary');archive.href='/research-certificate';host.append(archive,el('p','研究档案仅对应其中明确绑定的原案例，不自动应用到当前任务。','quiet-note'));
    const liveEnabled=!!f.ai_service?.ai?.live_enabled;
    if(f.result)host.append(el('p','证据来源：保存实跑；此处读取已保存的MPB数据，没有因打开页面重新计算。','quiet-note'));
    function diagnosticControls(parent){
      const select=el('select');select.setAttribute('aria-label','诊断方式');
      for(const [value,label] of [['live','真实AI诊断（一次请求）'],['rules','规则诊断（相同界面与工具）']]){const option=el('option',label);option.value=value;if(value==='live')option.disabled=!liveEnabled;select.append(option);}
      select.value=liveEnabled?'live':'rules';parent.append(el('label','由谁根据证据提出建议'),select);
      const consent=el('input');consent.type='checkbox';const label=el('label',null,'check-approval');label.append(consent,el('span','选择真实AI时，同意发送锁定的合成任务、有限数值设置和已核验指标；不发送原始场数组或私有脚本。'));parent.append(label);
      if(!liveEnabled)parent.append(el('p','当前服务未开启真实模态AI或绑定已过期；可用同界面的规则诊断，程序不会把它标为AI。','quiet-note'));
      return ()=>({diagnostic_mode:select.value,approve_diagnostic_data:consent.checked});
    }
    if(s.development_confirmation)host.append(el('p','模拟操作记录，不属于真人确认。','info-box warning'));
    if(s.mode_evidence_archive?.original_case_id&&/^[a-f0-9]{32}$/.test(s.mode_evidence_archive.original_case_id)){const a=el('a','查看原始研究案例（已保存证据）','button secondary');a.href='/#case='+s.mode_evidence_archive.original_case_id;host.append(a);}
    if(s.mode_evidence_archive)host.append(el('p','历史研究记录，可查看已有结果与曲线。再次计算需要新的确认。','info-box'));
    if(f.precision_study){
      host.append(el('p','独立数值精度研究；本案没有新增AI调用，也没有重放旧修复批准。','info-box'));
      if(f.precision_study.resource_eligible_changes_count===0)host.append(el('p','本例在已测试网格下仍不足以判断设计达标，当前资源范围内没有可批准的进一步修改。可保存和查看证据；下一步需独立核查数值方法或另做有上限的研究。','info-box warning'));
      host.append(details('各档实际相位敏感度与研究资源记录',f.precision_study));
    }
    if(f.paused){host.append(el('p','资料已保存暂停；没有填补未知，也没有启动计算。请从器件任务书确认晶轴、截面和材料组成。','card'),button('恢复已保存草稿',()=>h.mutate('mode-resume')));return host;}
    if(!f.mode_lock){
      const card=el('section',null,'card');card.append(el('h2','1 · 核对独立任务与出处'),el('p',f.original_requirement_text),el('p','当前预填值均来自合成任务卡。真实器件未知值请留空并保存暂停，不能把教学假设当制造资料。'));
      const original=structuredClone(f.mode_task),goal=structuredClone(f.qpm_goal),inputs=[];
      const table=el('table');const head=el('tr');['参数','值与单位','独立出处 / 去哪里核对'].forEach(t=>head.append(el('th',t)));table.append(head);
      function number(label,unit,source,container,key){
        const input=el('input');input.type='number';input.step='any';input.value=container[key]??'';input.setAttribute('aria-label',label);inputs.push(()=>container[key]=input.value.trim()===''?null:Number(input.value));
        const row=el('tr');const value=el('td');value.append(input,el('span',' '+unit));row.append(el('td',label),value,el('td',source));table.append(row);
      }
      const r=original.requirements;
      number('总膜厚','μm',original.provenance.geometry_source,r,'film_thickness_um');number('残余平板厚','μm','同一截面说明；须小于总膜厚',r,'slab_thickness_um');number('矩形脊宽','μm','任务书/工艺截面；首版仅垂直侧壁',r,'ridge_width_um');
      r.wavelengths_um.forEach((wave,i)=>number(i===0?'基波真空波长':'倍频真空波长','μm','独立光学过程说明：SHG倍频波长为基波一半',r.wavelengths_um,i));
      number('器件长度','μm',f.qpm_source,goal,'length_um');number('已规定的极化周期','μm',f.qpm_source,goal,'poling_period_um');number('目标相位因子F下限','无量纲；不是效率',f.qpm_source,goal,'target_phase_factor_min');
      const fixed=el('tr');fixed.append(el('td','晶轴、材料、包层'),el('td','x-cut沿晶体Y传播；未掺杂同成分LN，21℃；空气/人工n=1.44'),el('td','教学任务与Zelmon1997 Table1；实际器件请查材料与晶片证书，其他组成/温度暂不支持。'));table.append(fixed);card.append(table);
      const source=el('textarea');source.value=f.qpm_source;source.rows=2;source.setAttribute('aria-label','QPM目标独立出处');card.append(el('label','QPM目标独立出处'),source);
      const collect=()=>{inputs.forEach(fn=>fn());goal.pump_wavelength_um=r.wavelengths_um[0];return{mode_task:original,qpm_goal:goal,qpm_source:source.value};};
      card.append(el('p',f.validation_message||'资料不完整可保存；确认前程序检查范围，未知不猜。','quiet-note'));
      card.append(details('固定材料模型、数值设置与完整出处',original));
      card.append(el('p','本次最多 6 次串行 MPB 计算（2波长×3设置）；每个300秒、合计1800秒，内存最多2 GiB且不超过可用内存一半。核对场身份、网格与计算域，再按已确认长度/周期计算F。选择AI后最多1次诊断请求；修复未批准前不会应用。','info-box'));
      const diagnosis=diagnosticControls(card);
      const consent=el('input');consent.type='checkbox';consent.id='mode-consent';const label=el('label',null,'check-approval');label.append(consent,el('span','我已核对这份独立合成任务、单位和来源，批准按上述资源上限求模态并检查相位响应。'));
      const start=button('确认需求并开始检查与诊断',async()=>{if(!consent.checked)return;const choice=diagnosis();if(await h.mutate('mode-save',collect()))await h.mutate('mode-confirm-run',{approve:true,accept_resources:true,...choice});});start.disabled=true;consent.onchange=()=>start.disabled=!consent.checked;
      card.append(label,start,button('保存资料，暂停等待补充',async()=>{if(await h.mutate('mode-save',collect()))await h.mutate('mode-pause');}));host.append(card);
    }else if(f.job?.status==='running'||f.diagnosis_job?.status==='running')host.append(el('section',f.diagnosis_job?.status==='running'?'2 · 正在根据真实证据生成诊断；没有自动修复或重复请求。':'后台正在执行已批准的真实MPB与模式复核；重复点击不会另开一轮。','card'));
    else if(f.result){
      const result=f.result,mode=result.mode_report,q=result.qpm_report,card=el('section',null,'card');card.append(el('h2','3 · 实际结果与边界'));
      card.append(el('p',`该模式检查：${mode?.verification_status||'没有完整证据'}；长器件相位精度：${q?.verification_status||'停止'}；设计目标：${q?.design_goal_status||'未判断'}。`,'change-highlight'));
      card.append(el('p','模式检查通过只说明已算四个候选中的场形状、求根与已测设置检查通过，不是连续真值误差认证。旧身份指标为电场无权 L2 相似度，不是 E/H 功率归一。','quiet-note'));
      if(q){
        card.append(el('p',q.design_goal_status==='NOT_MET'?'计算检查通过，但已规定的周期不满足相位响应目标。这是合法的设计结果，不是擅自改周期的理由。':q.design_goal_status==='MET'?'这份任务在已测试条件下满足归一化相位目标；F不是绝对转换效率。':'模态敏感度对器件相位影响过大或证据不足，不能判断设计达标；没有缩短长度或放宽阈值。'));
        card.append(el('p',`F=${Number(q.phase_factor_NOT_efficiency).toPrecision(6)}；已测数值设置传播到相位的敏感度估计 ${Number(q.phase_sensitivity_estimate_rad).toPrecision(4)} rad；限值0.1 rad。`));
      }else card.append(el('p','模态或工作进程检查未通过，保留失败证据；没有把缺失结果算成通过。','info-box warning'));
      if(result.derived_report){
        const a=el('a','打开完整场图、相位曲线与报告','button secondary');a.href=`/api/cases/${s.id}/mode-files/report.html`;a.target='_blank';a.rel='noopener';const action=el('p');action.append(a);card.append(action);
        const plots=el('div',null,'before-after-charts');
        for(const m of mode.mode_inputs){const panel=el('section');panel.append(el('h3',`${m.wavelength_um} μm · n_eff=${Number(m.neff).toPrecision(7)}`));const img=el('img');img.src=`/api/cases/${s.id}/mode-files/field-${m.wavelength_um}.svg`;img.alt=`${m.wavelength_um} μm实际MPB电场模平方相对峰值`;img.style.maxWidth='100%';panel.append(img,el('p','实际MPB场；图为显示抽取，不增加求解点；不是1 W功率场。','quiet-note'));plots.append(panel);}card.append(plots);
        const plot=el('img');plot.src=`/api/cases/${s.id}/mode-files/phase-factor.svg`;plot.alt='公式计算的归一化相位因子曲线，新增MPB点0';plot.style.maxWidth='100%';card.append(plot);
      }
      if(f.diagnosis){
        card.append(el('h3',`2 · ${f.selected_diagnostic_mode==='live'?'真实AI':'规则'}诊断：${f.diagnosis.status}`),el('p',diagnosisSummary(f.diagnosis,f.selected_diagnostic_mode)));
        if(f.repair_count)card.append(el('p','这份诊断使用修复前证据；当前是否通过以复验结果为准。','quiet-note'));
        if(f.diagnosis.reason!==diagnosisSummary(f.diagnosis,f.selected_diagnostic_mode))card.append(details('完整诊断断言、数值和依据',f.diagnosis.reason));
        for(const issue of f.diagnosis.issues||[])card.append(el('p','问题位置：'+(issue.location||issue.location_key)));
        card.append(el('p',`解释核验：${f.diagnosis.explanation_audit_status||'未通过或未完成'}；本任务已记录模型请求：${f.model_requests||0}。建议通过不代表实际复验通过。`,'quiet-note'));
        if(f.diagnosis.verified_explanation_only)card.append(details('被拒绝建议中已核验的说明部分（不能据此执行修改）',f.diagnosis.verified_explanation_only));
        if(f.diagnosis.status==='REJECTED'&&!f.reassessment_source_commit&&!s.mode_evidence_archive)card.append(button('重新核对已有回复（不调用 AI）',()=>h.mutate('mode-reassess')));
      }else if(!f.repair_count&&!s.mode_evidence_archive){
        const choice=diagnosticControls(card);card.append(el('p','可以直接诊断这份已完成证据，不重复求解。'));
        card.append(button('根据现有证据生成诊断',()=>h.mutate('mode-diagnose',choice())));
      }
      if(f.repair_card&&!f.repair_count){
        const repair=f.repair_card,box=el('section',null,'info-box');box.append(el('h3','一张修复卡 · 一次批准'),el('p',repair.scope));
        const name=repair.change.path.at(-1)==='resolution'?'基础网格（像素/μm）':'横向计算域（μm）';
        box.append(el('p',`${name}：${JSON.stringify(repair.change.old)} → ${JSON.stringify(repair.change.new)}`,'change-highlight'),el('p',diagnosisSummary(f.diagnosis,f.selected_diagnostic_mode)));
        box.append(details('修复依据的逐项数值与出处',repair.why));
        box.append(el('p',`批准后自动运行最多6个MPB worker、总计1800秒、内存最多2 GiB；输出保守估计不超过${Math.ceil(repair.output_estimate.estimated_total_output_bytes/1024**2)} MiB。新增模型请求0。不保证复验通过；失败也保留。`));
        const consent=el('input');consent.type='checkbox';const label=el('label',null,'check-approval');label.append(consent,el('span','我批准这一项数值修改及卡片列出的复验；不改变器件需求或阈值。'));
        const approve=button('批准这份修改并自动复验',()=>h.mutate('mode-approve-repair',{approve:true,card_sha256:f.repair_card_sha256}));approve.disabled=true;consent.onchange=()=>approve.disabled=!consent.checked;box.append(label,approve);card.append(box);
      }
      if(f.repair_result){
        const before=f.initial_result?.qpm_report;card.append(el('h3','3 · 修复复验与可用数值配方'));
        card.append(el('p',`复验状态：${f.repair_result.status}；模态${f.repair_result.mode_verification||'未形成'}；QPM可信性${f.repair_result.qpm_verification||'未形成'}；设计目标${f.repair_result.design_goal||'未判断'}。`));
        if(before&&q)card.append(el('p',`相位敏感度估计：${Number(before.phase_sensitivity_estimate_rad).toPrecision(5)} → ${Number(q.phase_sensitivity_estimate_rad).toPrecision(5)} rad；独立目标、制造周期与长度未改变。`));
        if(before&&q){const plots=el('div',null,'before-after-charts');for(const [label,route] of [['修复前 · 固定模态值的公式曲线','mode-before-files'],['修复后 · 新真实模态值的公式曲线','mode-files']]){const panel=el('section');panel.append(el('h3',label));const img=el('img');img.src=`/api/cases/${s.id}/${route}/phase-factor.svg`;img.alt=label+'；不是额外MPB扫描或效率曲线';img.style.maxWidth='100%';panel.append(img);plots.append(panel);}card.append(plots);}
        if(result.cross_repair_identity)card.append(el('p','修复前后场身份复核：'+result.cross_repair_identity.status+'；未通过时不会输出可信QPM判断。'));
        if(f.repair_result.status==='completed'){const a=el('a','下载本次数值配方及验证状态','button secondary');a.href=`/api/cases/${s.id}/mode-repaired-candidate`;a.download='mode-numerics-with-verification.json';card.append(a);}
      }
      card.append(el('p','修改制造周期或器件尺寸需另立新任务版本。AI只能提出受限建议，不能替用户确定目标或批准。','quiet-note'));host.append(card);
    }else host.append(el('section','运行没有形成完整结果；失败与批准保留，不自动重新执行。','card'));
    if(f.mode_lock&&f.job?.status!=='running'&&f.diagnosis_job?.status!=='running')host.append(button('返回修改，保存为新任务版本',()=>h.mutate('mode-new-version',{reason:'用户主动返回修改需求；旧锁、原始结果与失败保留'})));
    host.append(details('任务锁、资源批准、检查与原始运行记录（默认折叠）',f));return host;
  }
  return{create};
})();
