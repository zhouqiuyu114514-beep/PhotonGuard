'use strict';
window.PhotonGuardRepair = (() => {
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const detail=(title,child)=>{const d=el('details');d.append(el('summary',title),child);return d;};
  const json=v=>el('pre',JSON.stringify(v,null,2));
  const button=(label,fn)=>{const b=el('button',label,'button');b.type='button';b.onclick=fn;return b;};
  const link=(label,path)=>{const a=el('a',label,'button secondary');a.href=path;a.target='_blank';a.rel='noopener';return a;};
  const labels={'numerics.resolution':'空间网格精度（每微米格点）','numerics.after_sources':'脉冲结束后的计算时长','workflow.reference_amplitude':'参考计算的光源幅度','workflow.subtract_incident':'反射测量扣除入射场'};
  const fields={spatial_dimension:'空间维度',incidence_angle:'入射角',relative_permeability:'相对磁导率',lossless:'无损介质',isotropic:'各向同性',nondispersive:'无色散',layer_count:'膜层数量',incident_index:'入射介质折射率',film_index:'膜层折射率',exit_index:'出射介质折射率',film_thickness:'膜厚',wavelength_min:'最短真空波长',wavelength_max:'最长真空波长',wavelength_samples:'等波长采样点数'};
  const human=key=>labels[key]||fields[key]||(key.match(/^layer_(\d+)_(n|thickness_um)$/)?`第${key.split('_')[1]}层${key.endsWith('_n')?'折射率':'厚度'}`:key);
  function create(s,h){
    const host=el('section',null,'three-step-workspace');
    host.append(el('h1',s.novice?'薄膜计算与检查结果':'确认需求 → 查看建议 → 一次批准复验'),el('p',s.label,'lead'));
    const phase=s.pipeline?.status;
    const busy=['CHECKING','DIAGNOSING','REVERIFYING'].includes(phase);
    const initialComplete=!s.repair_result&&!s.diagnosis&&s.pipeline?.phase==='initial'&&['RESULT','NO_PATCH'].includes(phase)&&s.job?.status==='completed'&&s.runs?.length;
    const initialStatus=initialComplete?s.runs[s.runs.length-1].status:null;
    const step=!s.approval?1:phase==='AWAITING_APPROVAL'?2:s.repair_result||initialComplete?3:2;
    const names=s.novice?['确认摘要','计算与检查','查看曲线和结果']:['确认需求','查看问题和修复建议','批准修复并查看复验结果'];
    const steps=el('div',null,'simple-steps');names.forEach((t,i)=>steps.append(el('span',`${i+1} · ${t}`,step===i+1?'current':'')));host.append(steps);
    if(s.development_confirmation)host.append(el('p','模拟操作记录，不属于真人确认。','info-box warning'));
    if(s.paused_reason){
      host.append(el('h2','资料暂缺，已保存'),el('p',s.paused_reason,'info-box warning'));
      const result=s.intake?.result,answer=result?.normalized_response;
      const missing=el('ul');Object.entries(answer?.fields||{}).filter(([,v])=>v.status!=='proposed').forEach(([k,v])=>missing.append(el('li',`${human(k)}：${v.status==='conflict'?'来源冲突':'尚缺独立依据'}`)));
      if(!s.repair_trial?.options?.mapping_source&&!s.mapping_review?.options?.mapping_source)missing.append(el('li','尺度（1单位=1微米）、线性介质、Ex场方向的独立说明'));
      host.append(el('h3','继续前需要核对'),missing);
      (answer?.questions||[]).forEach(q=>host.append(el('p',q.text,'info-box warning')));
      (result?.scope_problems||[]).forEach(q=>host.append(el('p',q,'info-box warning')));
      const source=detail('查看已保存的独立需求原文与出处',el('pre',s.intake?.source_text||'尚未保存原文'));source.open=true;host.append(source);
      if(answer)host.append(detail('逐项参数与来源记录',json(answer.fields)));
      if(s.mapping_draft)host.append(detail('已保存的补充资料',json(s.mapping_draft)));
      host.append(el('p','可以先查看或补充资料；恢复编辑不会确认资料齐备、启动求解或调用模型。'),button('查看 / 补充资料（恢复编辑）',()=>h.mutate('resume')));return host;
    }
    if(!s.approval){
      const card=el('section',null,'card');card.append(el('h2','确认已有资料，后台完成检查'));
      const intake=s.intake,result=intake?.result,answer=result?.normalized_response;
      const original=el('textarea');original.rows=8;original.value=intake?.source_text||'';original.setAttribute('aria-label','独立需求原文');
      const empty=!intake?.source_text?.trim();
      const editor=detail(empty?'填写独立需求':'修改独立需求（保存后重新核对）',original);editor.open=empty;
      const save=button(empty?'保存并整理需求':'保存并整理修改',async()=>{if(await h.mutate('intake-save',{text:original.value}))await h.mutate('intake-review',{mode:'mock'});});
      save.disabled=!original.value.trim();original.oninput=()=>save.disabled=!original.value.trim();editor.append(save);card.append(editor);
      if(empty)queueMicrotask(()=>{if(original.isConnected)original.focus();});
      if(!answer){card.append(el('p','尚无可确认的参数草稿。请先保存独立需求，缺项保留未知，不从脚本反推。','info-box warning'));card.append(button('资料暂缺，保存暂停',()=>h.mutate('pause',{reason:'独立需求尚未完整；保存已有资料，未知不猜。'})));host.append(card);return host;}
      card.append(el('p',result.mode==='REAL_MODEL'?'需求整理来自已有真实AI输出，本轮不重复调用。':intake.kind==='film_stack_task_v2'?'这份有序层列表来自独立资料，离线校验后确认。':'这份需求由离线规则整理，请核对出处和缺项。'));
      const table=el('table');const head=el('tr');['参数','值与单位','原文与出处'].forEach(v=>head.append(el('th',v)));table.append(head);
      Object.entries(answer.fields).forEach(([key,f])=>{const row=el('tr',null,f.status==='proposed'?'':'unresolved-field');row.append(el('td',human(key)),el('td',f.status==='proposed'?`${f.value} ${f.unit||''}`:`${f.status}：不能猜或选边`),el('td',f.evidence.map(r=>`${r.document} 第${r.line}行：${r.quote}`).join('\n')||'缺少独立依据；请找任务书或询问需求提出者'));table.append(row);});
      const columns=el('div',null,'requirement-columns');columns.append(detail('独立需求原文',el('pre',intake.source_text)),detail('逐项核对参数、单位和出处',table));card.append(columns);
      let options=s.repair_trial?.options;
      const mappingInputs={};
      if(!options){
        const form=el('div');form.append(el('p','需要任务书确认：1个Meep单位为1微米、线性介质、正入射Ex。没有这些依据请暂停；不从脚本猜。'));
        const notes={mapping_source:'上述尺度、线性和场方向的独立出处',background:'这项仿真的背景',goal:'任务书希望得到什么结果',role:'你在任务中的职责'};
        Object.entries(notes).forEach(([key,text])=>{const input=el('textarea');input.rows=2;input.maxLength=4000;input.value=s.mapping_draft?.[key]||'';input.setAttribute('aria-label',text);mappingInputs[key]=input;form.append(el('label',text),input);});card.append(form);
      }
      card.append(el('p',s.repair_trial?.options?.mapping_source||s.trial_material?.mapping_source||'缺少尺度、线性或场方向的独立说明；请保存暂停。','info-box'));
      card.append(el('p',intake.kind==='film_stack_task_v2'?`任务摘要：${answer.fields.layer_count?.value??'未知'}层，按+z从入射侧到出射侧保持原层序；每层厚度以微米列出。波长${answer.fields.wavelength_min?.value??'未知'}–${answer.fields.wavelength_max?.value??'未知'} nm。`:`任务摘要：膜折射率 ${answer.fields.film_index?.value??'未知'}；膜厚 ${answer.fields.film_thickness?.value??'未知'} nm；波长 ${answer.fields.wavelength_min?.value??'未知'}–${answer.fields.wavelength_max?.value??'未知'} nm，${answer.fields.wavelength_samples?.value??'未知'} 个等波长点。`));
      card.append(el('p','保留等波长要求：每个点直接DFT求解，插值0点。确认只锁定需求，不代表脚本正确。'));
      const source=el('textarea');source.rows=12;source.value=s.repair_trial?.source||s.source_text||'';source.maxLength=131072;source.id='repair-script';
      const file=el('input');file.type='file';file.accept='.py';file.onchange=async()=>{const f=file.files[0];if(f&&f.size<=131072)source.value=await f.text();};
      const script=el('div');script.append(el('p','可用提供的待检脚本，或选择自己的支持范围内脚本。仅做AST只读解析，不执行上传Python。'),file,source);card.append(detail('待检脚本（解析和检查由后台完成）',script));
      const mode=el('select');(h.service?.live_enabled?[['live','AI 问题分析'],['rules','规则诊断']]:[['rules','规则诊断（模型不可用）']]).forEach(([v,t])=>{const o=el('option',t);o.value=v;o.disabled=v==='live'&&!h.service?.live_enabled;mode.append(o);});mode.value=s.repair_trial?.mode||'rules';if(mode.selectedIndex<0||(mode.value==='live'&&!h.service?.live_enabled))mode.value='rules';card.append(el('label','诊断方式（两者使用相同界面与复验）'),mode);
      card.append(el('p','初次检查：4组参考/目标配对，共最多8次FDTD；单配对65秒、内存1536MiB。'+(h.service?.live_enabled?' AI模式最多1次模型请求；只发送锁定数值、源码位置与检查指标。':' 当前为规则服务：模型不可用，新增模型调用0。'),'quiet-note'));
      const consent=el('input');consent.type='checkbox';consent.id='one-task-consent';const label=el('label',null,'check-approval');label.append(consent,el('span','我已核对需求与补充依据，确认锁定任务并开始限定检查。'+(h.service?.live_enabled?'选择AI时同意发送上述有限诊断数据。':'本次使用规则诊断。')));
      const start=button('确认需求并开始检查',()=>{const supplied=options||{units_um:1,linear:true,field_component:'Ex',accept_sampling:true,accept_decimal_projection:true,...Object.fromEntries(Object.entries(mappingInputs).map(([k,v])=>[k,v.value]))};return h.mutate('start-review',{approve:consent.checked,accept_initial_checks:consent.checked,diagnostic_mode:mode.value,approve_diagnostic_data:consent.checked&&mode.value==='live',result_sha256:intake.result_sha256,options:supplied,source:source.value});});start.disabled=true;const readiness=()=>start.disabled=!consent.checked||!result.confirmable||(!options&&Object.values(mappingInputs).some(v=>v.value.trim().length<3));consent.onchange=readiness;Object.values(mappingInputs).forEach(v=>v.oninput=readiness);
      card.append(label,start,button('资料暂缺，保存暂停',()=>h.mutate('pause',{reason:'需求或映射依据暂缺；不猜参数。'})));answer.questions.forEach(q=>card.append(el('p',q.text,'info-box warning')));result.scope_problems.forEach(q=>card.append(el('p',q,'info-box warning')));host.append(card);
    }else if(busy){host.append(el('section',s.pipeline.message,'card'),el('p','后台自动处理当前已授权步骤。页面可重新读取状态；重复点击不会派发新请求或启动另一轮。','quiet-note'));}
    else if(phase==='AWAITING_APPROVAL'){
      const card=s.repair_card,section=el('section',null,'card repair-approval-card');section.append(el('h2',s.diagnostic_mode==='live'?'真实AI提出的修复':'规则提出的修复'),el('p',card.why));
      section.append(el('p',`修改合法性：${card.patch_policy_valid?'已核验':'见证据'}；实际复验：尚未运行；解释审计：${card.explanation_audit_status||'旧版本未核验'}。`,'quiet-note'));
      const explanationWarning=['UNSUPPORTED','UNVERIFIED_LEGACY_TEXT'].includes(card.explanation_audit_status);
      if(explanationWarning)section.append(el('p','原模型说明含未支持或尚未核验的断言。当前展示的是系统依据证据渲染的事实；不能把合法补丁当作模型解释正确。请连同下方审计记录一起决定是否批准。','info-box warning'),detail('模型说明审计与原返回',json({audit:card.explanation_audit,diagnosis:s.diagnosis})));
      card.changes.forEach(c=>section.append(el('p',`${human(c.path.join('.'))}：${c.old} → ${c.new}；原脚本位置：${[...new Set(c.source_locations.map(x=>`第${x.line}行`))].join('、')||'见解析证据'}`,'change-highlight')));
      card.issues.forEach(i=>section.append(el('p',`${human(i.location_key)}：${i.reason}`),el('small',`依据：${i.evidence_ids.join('、')}`)));
      section.append(el('p',card.scope,'info-box'),el('p','批准后只应用这份修改并自动完成四组参考/目标配对，最多8次FDTD；单配对65秒，内存1536MiB，不增加模型请求。出现新修改不会沿用这次批准。'));
      const consent=el('input');consent.type='checkbox';consent.id='one-repair-consent';const label=el('label',null,'check-approval');label.append(consent,el('span','我已读过这份具体修改，批准应用并按上述上限完成复验。'));
      const approve=button('批准这份修复并自动复验',()=>h.mutate('approve-repair',{approve:consent.checked,acknowledge_explanation_warning:explanationWarning&&consent.checked,card_sha256:s.repair_card_sha256}));approve.disabled=true;consent.onchange=()=>approve.disabled=!consent.checked;section.append(label,approve);host.append(section);
    }else if(initialComplete){
      const card=el('section',null,'card');
      const titles={PASS:'初次计算已通过限定数值检查',INCONCLUSIVE:'检查已结束，证据不足以判断通过',UNSUPPORTED:'当前输入超出支持范围'};
      card.append(el('h2',titles[initialStatus]||'检查结果已保存'),el('p',initialStatus==='PASS'?'可以查看下方真实曲线并下载结果。本次无需修复。':'请展开完整报告查看未决项与范围说明，当前结果不能当作通过。'),el('p','结论仅适用于这份任务、采样点和固定容差；器件设计目标尚未验证。','quiet-note'));host.append(card);
    }else if(s.repair_result){
      const card=el('section',null,'card');card.append(el('h2',s.repair_result.status==='PASS'?'这份修正版通过了限定检查':'复验没有通过，原因和证据已保留'),el('p','已修规范化配方；原始Python脚本保持不变。PASS仅适用于这次任务、采样点和固定容差。'));
      card.append(el('p',`修改合法性、实际复验和模型说明分别记录。解释审计：${s.repair_result.explanation_audit_status||s.historical_explanation_audit?.status||'历史版本未核验'}；复验PASS不能替代解释核验。`,'quiet-note'));
      if(s.historical_explanation_audit?.status==='UNSUPPORTED')card.append(el('p','旧版本原模型说明中检出了缺乏依据的断言。原返回和复验结果均保留；说明错误不会被最终PASS掩盖。','info-box warning'),detail('旧说明的只读审计（不改原记录）',json(s.historical_explanation_audit)));
      const last=s.runs?.[s.runs.length-1];const metrics=(last?.checks||[]).filter(c=>['base_independent_tmm','grid_sensitivity','time_sensitivity','pml_sensitivity'].includes(c.id));
      const titles={base_independent_tmm:'与独立理论参考的最大光谱误差',grid_sensitivity:'提高网格精度后的光谱变化',time_sensitivity:'延长计算后的光谱变化',pml_sensitivity:'增厚吸收边界后的光谱变化'};
      metrics.forEach(c=>card.append(el('p',`${titles[c.id]}：${Number(c.metrics.max_absolute_error??c.metrics.max_absolute_change).toPrecision(4)}，本次阈值 ${c.metrics.tolerance}，${c.status}。`)));
      card.append(el('p','这些结果只验证本次离散波长和测试设置，不证明任意精度下都收敛。'));
      card.append(link('下载已复验的可用配方',`/api/cases/${s.id}/repaired-recipe`));host.append(card);
    }else if(s.pipeline){host.append(el('section',s.pipeline.message,'card'),el('p',s.diagnosis?.reason||s.job?.error||'没有得到可安全批准的修改；原因和原始记录已保留。','info-box warning'));if(phase==='FAILED'&&s.pipeline.phase==='initial'&&s.job?.status==='failed')host.append(button('保留失败，明确重试初次检查',()=>h.mutate('retry-check',{approve:true})));}
    if(s.diagnosis?.status==='REJECTED'&&s.diagnosis.explanation_audit){
      const audit=s.diagnosis.explanation_audit,kept=el('div');
      kept.append(el('p',`已独立核验的说明 ${audit.accepted?.length||0} 条；未通过 ${audit.findings?.length||0} 条。建议整体仍被拒绝，没有可批准的修复。`,'quiet-note'));
      (audit.rendered||[]).forEach(line=>kept.append(el('p',line)));
      kept.append(detail('拒绝原因与说明审计记录',json({rejection_code:s.diagnosis.rejection_code,audit})));
      host.append(detail('被拒绝建议中已核验的说明部分',kept));
    }
    if(phase==='FAILED'&&s.pipeline?.phase==='initial'&&s.diagnostic_mode==='rules'&&s.job?.status==='completed'&&s.runs?.length)host.append(button('恢复已完成证据的规则审阅（不重复求解）',()=>h.mutate('resume-rule-review')));
    if(s.runs?.length){
      const last=s.runs[s.runs.length-1],dimensions=el('section',null,'card');
      dimensions.append(el('h2','这次结果能说明什么'),el('p',`计算执行：${s.job?.status==='completed'?'已完成':'查看运行记录'}；数值检查：${last.status}；设计目标：NOT_EVALUATED（本入口未验证器件设计目标）；证据来源：保存实跑。${s.actor_type==='SIMULATED'?'操作主体：SIMULATED。':''}`),link('下载结果、数据与复跑配置',`/api/cases/${s.id}/runs/${last.run_id}/bundle`));host.append(dimensions);
      const section=el('section',null,'card');section.append(el('h2','实际结果与曲线（无插值）'));const charts=el('div',null,'before-after-charts');
      [s.runs[0],...(s.runs.length>1?[s.runs[s.runs.length-1]]:[])].forEach((run,i)=>{const panel=el('section');panel.append(el('h3',`${s.runs.length===1?'初次计算':i===0?'修复前':'复验后'} · ${run.status}`));const chart=el('div');panel.append(chart,link('展开完整证据报告',run.report_url));charts.append(panel);queueMicrotask(async()=>{try{const data=await h.api(run.spectrum_url);if(chart.isConnected)chart.replaceChildren(h.chart(data.spectrum||[]));}catch(e){if(chart.isConnected)chart.textContent='曲线读取失败，请重新读取；没有生成替代数据。';}});});section.append(charts);host.append(section);
    }
    if(!busy&&s.approval)host.append(button('返回需求，保存为新任务版本',()=>h.mutate('derive-version',{reason:'用户从三步流程返回修改需求；保留原锁定任务与证据。'})));
    host.append(detail('原始记录、检查依据与版本',json({intake:s.intake,mapping:s.mapping_review,parse:s.import_preview,diagnosis:s.diagnosis,repair_card:s.repair_card,permit:s.repair_permit,job:s.job,runs:s.runs})));
    return host;
  }
  return {create};
})();
