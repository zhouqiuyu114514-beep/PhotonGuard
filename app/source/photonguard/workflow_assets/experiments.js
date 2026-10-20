"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = String(text); if (cls) n.className = cls; return n; };
  const append = (host, ...children) => { children.filter(Boolean).forEach(n => host.append(n)); return host; };
  const card = title => append(node('section', null, 'card'), title ? node('h2', title) : null);
  const json = value => JSON.stringify(value, null, 2);
  const list = values => { const ul = node('ul', null, 'concise'); values.forEach(v => ul.append(node('li', typeof v === 'string' ? v : display(v)))); return ul; };
  const STATES = {DRAFT:'资料待整理',NEEDS_INFORMATION:'需要补充资料',PLANNED:'等待核对计划',RUNNING:'正在计算',COMPLETED:'已完成计算',FAILED:'本次未完成',NEEDS_REVIEW:'本轮整理需核对'};
  const DOMAINS = {film:'薄膜光谱',diffraction:'衍射与干涉',gaussian:'高斯光束'};
  const NAMES = {domain:'实验场景',context_kind:'资料类型',known_parameters:'已知参数',assumptions:'模型假设',locked_parameters:'保持不变',allowed_variables:'允许调整',goal:'目标',candidate_bounds:'候选范围',resource_budget:'本次计算额度',parent_task_id:'来源记录',wavelength_nm:'波长（nm）',wavelength_um:'波长（μm）',thickness_nm:'厚度（nm）',thickness_um:'厚度（μm）',focal_length_mm:'焦距（mm）',waist_radius_um:'束腰半径（μm）',screen_distance_mm:'屏幕距离（mm）',slit_width_um:'缝宽（μm）',slit_separation_um:'缝距（μm）',relative_phase_rad:'相对相位（rad）',value:'值',unit:'单位',source:'出处',status:'状态',reflection:'反射率',transmission:'透射率',R:'反射率 R',T:'透射率 T',met:'达到目标',maximum_candidates:'最多候选数',max_candidates:'最多候选数',max_model_calls:'最多 AI 请求数',max_fast_candidates:'最多快速候选数',max_fdtd_calls:'最多 FDTD 次数',max_meep_candidates:'最多 Meep 核对候选数',max_grid_size:'最大网格',max_seconds:'最长计算秒数',max_memory_mb:'内存上限（MiB）',max_output_mb:'结果上限（MiB）',max_wavelength_points:'最多波长采样点数'};
  Object.assign(NAMES,{metric:'比较指标',operator:'比较方式',target:'目标值',tolerance:'允许误差',fraction:'比例',minimize:'在候选中取最小值',maximize:'在候选中取最大值',near:'接近目标值',reflectance:'反射率',transmittance:'透射率',reflectance_min:'采样点最低反射率',reflectance_mean:'采样点平均反射率',transmittance_min:'采样点最低透射率',transmittance_mean:'采样点平均透射率',central_intensity_ratio:'中心强度比',fringe_period_mm:'条纹周期（mm）',first_zero_mm:'第一暗纹位置（mm）',screen_radius_um:'屏幕上光斑半径（μm）',new_waist_radius_um:'新束腰半径（μm）',new_waist_z_mm:'新束腰位置（mm）',waist_z_mm:'输入束腰位置（mm）',z_max_mm:'显示范围（mm）',layers:'膜层列表',n:'折射率',wavelengths_um:'实际采样波长（μm）',scan_min_um:'扫描下界（μm）',scan_max_um:'扫描上界（μm）',scan_points:'采样点数',material_n_high:'高折射率材料',material_n_low:'低折射率材料',layer_count:'膜层数',design_wavelength_um:'膜系设计波长（μm）',aperture:'孔径形式',single_slit:'单缝',double_slit:'双缝',grid_size:'网格边长',window_mm:'计算窗口（mm）',slit_height_um:'缝高（μm）',max_fast_evaluations:'最多快速计算次数',max_meep_validations:'最多独立 Meep 核对方案数',max_fdtd:'最多 FDTD 次数',worker_seconds:'最长计算秒数',worker_memory_mib:'工作内存上限（MiB）',output_mib:'结果大小上限（MiB）',RUN_COMPLETED:'计算完成',NUMERIC_CHECK_FAILED:'数值检查未通过',RUN_FAILED:'计算未完成',PASS:'通过',FAIL:'未通过'});
  Object.assign(NAMES,{'Wavelength (um)':'波长（μm）','Power fraction':'反射 / 透射比例','Distance after lens (mm)':'透镜后距离（mm）','1/e^2 intensity radius (um)':'1/e² 强度半径（μm）','Beam radius':'光斑半径','Focal-plane x (mm)':'焦平面横坐标（mm）','Focal-plane y (mm)':'焦平面纵坐标（mm）','Intensity / incident irradiance':'光强 / 入射光强','FFT center line':'数值计算中心截线','Analytic center line':'解析表达中心截线',dimensionless:'无量纲'});
  Object.assign(NAMES,{worker_seconds:'快速工具最长秒数',worker_memory_mib:'快速工具内存上限（MiB）；Meep另按既有策略'});
  let boot = null, current = null, busy = false, navigation = 0, pollTimer = null;
  const storePrefix = 'photonguard-experiments-v1:' + location.origin + ':';
  const volatile = new Map();
  function load(key) { try { const v = sessionStorage.getItem(storePrefix + key); return v ? JSON.parse(v) : volatile.get(key); } catch (_) { return volatile.get(key); } }
  function save(key, value) { volatile.set(key, value); try { sessionStorage.setItem(storePrefix + key, JSON.stringify(value)); return true; } catch (_) { return false; } }
  function clear(key) { volatile.delete(key); try { sessionStorage.removeItem(storePrefix + key); } catch (_) {} }
  const credentialLike = text => /\bsk-[a-zA-Z0-9_-]{16,}|Bearer\s+[a-zA-Z0-9_.-]{16,}/i.test(text);
  const name = key => NAMES[key] || key;
  const humanizeQuestion = value => String(value).replace(/execution\.fast_only/g,'只做快速计算').replace(/parameters\./g,'').replace(/goal\./g,'目标 ').replace(/recipe\./g,'候选 ').replace(/\b[a-z][a-z0-9_]+\b/g,key => NAMES[key] || key);
  function display(value) {
    if (value == null) return '未提供';
    if (value === true) return '是'; if (value === false) return '否';
    if (typeof value === 'number') return Number.isFinite(value) ? Number(value.toPrecision(7)).toString() : '无有效数值';
    if (typeof value === 'string') return NAMES[value] || value;
    if (Array.isArray(value)) return value.length ? value.map(display).join('；') : '无';
    if (Object.prototype.hasOwnProperty.call(value, 'value')) return display(value.value) + (value.unit ? ' ' + value.unit : '') + (value.source ? ' · 出处：' + display(value.source) : '');
    return Object.entries(value).map(([k,v]) => name(k) + '：' + display(v)).join('；');
  }
  function facts(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return node('p', display(value), 'section-note');
    const dl = node('dl', null, 'fact-grid'); Object.entries(value).forEach(([k,v]) => append(dl, node('dt', name(k)), node('dd', display(v)))); return dl;
  }
  function detail(title, value) { return append(node('details'), node('summary', title), node('pre', typeof value === 'string' ? value : json(value))); }
  function sourceReview(s) {
    const section = append(node('details'),node('summary','核对参数值、单位与原文出处'));
    const parameters = s.spec?.known_parameters || {}, sources = s.spec?.parameter_sources || {};
    if (Object.keys(parameters).length) {
      const table = node('table'); table.append(append(node('thead'),append(node('tr'),node('th','参数'),node('th','本次采用的值'),node('th','出处'))));
      const body = node('tbody'); Object.entries(parameters).forEach(([key,value]) => {
        const source = sources[key] || value?.source, quotes = source?.quotes || [source?.quote || (typeof source === 'string' ? source : '请在原始资料中核对')];
        const origin = node('td'); quotes.forEach(q => origin.append(node('p',q,'field-note')));
        body.append(append(node('tr'),node('td',name(key)),node('td',display(value) + (source?.unit ? ' ' + source.unit : '')),origin));
      });
      table.append(body); section.append(append(node('div',null,'table-scroll'),table));
    }
    append(section,detail('原始资料',s.text || ''),detail('完整参数记录',s.spec || {})); return section;
  }
  function button(label, run, cls = '', disabled = false) {
    const b = node('button', label, 'button ' + cls); b.type = 'button'; b.disabled = busy || disabled; b.addEventListener('click', () => { if (!busy && !b.disabled) run(); }); return b;
  }
  function badge(label, cls = '') { return node('span', label, 'badge ' + cls); }
  function message(id, text) { $(id).textContent = text || ''; $(id).hidden = !text; }
  function setBusy(value) {
    busy = value;
    document.querySelectorAll('button, textarea, input, select').forEach(el => {
      if (value) { el.dataset.wasDisabled = el.disabled ? '1' : '0'; el.disabled = true; }
      else if ('wasDisabled' in el.dataset) { el.disabled = el.dataset.wasDisabled === '1'; delete el.dataset.wasDisabled; }
    });
    $('content').setAttribute('aria-busy', value ? 'true' : 'false');
  }
  async function api(path, body) {
    let response;
    try { response = await fetch('/api/experiments' + path, {method:body ? 'POST' : 'GET', credentials:'same-origin', cache:'no-store', headers:body ? {'Content-Type':'application/json','X-CSRF-Token':boot.csrf} : {}, ...(body ? {body:JSON.stringify(body)} : {})}); }
    catch (_) { const e = new Error('连接中断，操作是否完成尚未确认。请先读取最新记录，不要重复发送 AI 或计算请求。'); e.uncertain = !!body; throw e; }
    let data; try { data = await response.json(); } catch (_) { const e = new Error('服务未返回可读取的记录。请先刷新状态，已有实验仍保留。'); e.uncertain = !!body; throw e; }
    if (!response.ok) { const e = new Error(typeof data.error === 'string' ? data.error : data.error?.message || data.message || '操作未完成，请检查资料后重试。'); e.httpStatus = response.status; throw e; }
    return data;
  }
  function cacheCase(s) { const i = boot.cases.findIndex(c => c.id === s.id); const brief = {id:s.id,title:s.title,domain:s.domain,status:s.status,updated_at:s.updated_at,family_id:s.family_id}; if (i < 0) boot.cases.unshift(brief); else boot.cases[i] = brief; }
  function sidebar() {
    const nav = $('case-list'); nav.replaceChildren();
    if (!boot.cases.length) nav.append(node('p', '还没有实验。完成资料整理后会保存在这里。', 'muted'));
    const groups=new Map(); [...boot.cases].sort((a,b)=>b.updated_at.localeCompare(a.updated_at)).forEach(c=>{const key=c.family_id||c.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(c);});
    const older=append(node('details'),node('summary','全部实验（'+groups.size+' 组）'));
    [...groups.values()].forEach((group,i)=>{const target=i<5?nav:older,shown=group.find(c=>c.id===current?.id)||group[0];
      const entry=c=>{const b=button(c.title||DOMAINS[c.domain]||'新实验',()=>select(c.id));b.className='case-button'+(current?.id===c.id?' active':'');b.append(node('small',(DOMAINS[c.domain]||'待识别场景')+' · '+(STATES[c.status]||c.status)));if(current?.id===c.id)b.setAttribute('aria-current','page');return b;};
      const box=node('div',null,'case-group');box.append(entry(shown));if(group.length>1){const versions=append(node('details'),node('summary','同一实验的 '+group.length+' 个版本'));group.filter(c=>c.id!==shown.id).forEach(c=>versions.append(entry(c)));box.append(versions);}target.append(box);
    });if(groups.size>5)nav.append(older);
  }
  function updateLocation(id) { history.replaceState(null, '', location.pathname + (id ? '#case=' + encodeURIComponent(id) : '')); }
  async function select(id) {
    if (busy) return; const turn = ++navigation; clearTimeout(pollTimer); message('error', ''); message('notice','');
    try { const s = await api('/cases/' + encodeURIComponent(id)); if (turn !== navigation) return; current = s; cacheCase(s); updateLocation(s.id); render(); window.scrollTo(0,0); } catch (e) { if (turn === navigation) message('error', e.message); }
  }
  function home() { if (busy) return; navigation++; clearTimeout(pollTimer); current = null; updateLocation(null); message('error',''); message('notice',''); render(); }
  async function create(body) {
    if (busy) return; setBusy(true); message('error','');
    try { const s = await api('/cases', body); current = s; cacheCase(s); if (body.kind === 'specified') clear('new-draft'); updateLocation(s.id); message('notice', body.kind === 'teaching' ? '已采用明确标注的教学资料。请核对计划后再运行。' : '资料已保存，尚未运行计算。'); }
    catch (e) { message('error', e.message); } finally { setBusy(false); render(); window.scrollTo(0,0); }
  }
  async function mutate(type, payload = {}) {
    if (busy || !current) return; const id = current.id, revision = current.revision;
    setBusy(true); message('error',''); message('notice',payload.mode === 'live' || ['explain','fit_wizard','fit_ai','inverse_ai'].includes(type) ? 'AI 正在处理，请稍候。请勿重复提交。' : '正在保存操作，请稍候。');
    save('pending:' + id, {type,revision});
    try {
      const sessionRoute=!current.estimate_origin&&(type==='explore_case'||!current.parent_context&&(['library_plan','fact_update','undo_fact'].includes(type)||type==='plan'&&current.kind!=='teaching'||type==='supplement'&&current.library_context));
      const returned = await api('/cases/' + encodeURIComponent(id) + '/action', {type,expected_revision:revision,...(sessionRoute?{session_version:2}:{}),...(['supplement','fact_update','undo_fact'].includes(type)?{event_id:crypto.randomUUID()}:{}),...payload});
      const s = returned.case || returned;
      if (!s.id) throw Object.assign(new Error('已发送操作，但未收到完整记录。请读取最新状态确认。'), {uncertain:true});
      clear('pending:' + id); if (type === 'save') clear('draft:' + id); if (type === 'revise') clear('revision:' + id); if (type === 'supplement') { clear('supplement:' + id); clear('draft:' + id); }
      current = s; cacheCase(s); updateLocation(s.id);
      if(type==='session_ai'){message('notice',s.ai_step?.text||'AI 动作已处理；实际执行状态见本页记录。');return;}
      const observationNotices={fit_wizard:'AI 整理与来源核对已记录；请核对当前条件或结果说明，没有自动计算。',fit_ai:'AI 核对已记录，没有自动计算。',fit_plan:'条件与拟合计划已保存；尚未运行计算。',fit_revise:'已另存设置版本，旧结果和累计额度保留。',fit_forward:'已创建正向核对计划，尚未计算。',choose_observation_candidate:'已按你的选择生成缩减计划；网格和累计额度不变，尚未计算。'};
      if(type.startsWith('inverse_')&&type!=='inverse_run'){message('notice',type==='inverse_task_run'?'连续任务已按批准计划接续，实际进度和结果见下方。':type==='inverse_append'?'新采集已保存，请核对新的联合计划；尚未拟合。':type==='inverse_ai'?'AI 建议已保存，请核对后确认下一步。':'操作已保存。新的计算需另行确认。');return;}
      if(observationNotices[type]){message('notice',observationNotices[type]);return;}
      message('notice', ['fact_update','undo_fact'].includes(type) ? (s.fact_state?.notice || (type==='undo_fact'?'已撤销上次资料修改。尚未运行计算。':'资料已保存，请核对当前条件。尚未运行计算。')) : type === 'restore_result' ? '已恢复已有计算结果，本次没有重新计算。其他版本仍保留。' : ['library_plan','explore_case'].includes(type) ? (s.status === 'PLANNED' ? '已生成案例探索计划，尚未计算。请核对参数与候选。' : '资料已保留，请补充下面列出的信息。尚未计算。') : ['revise','revise_goal'].includes(type) ? '修改已另存为新版本，原始结果保留。相同计算条件会复用旧数值；需要计算时请核对新计划。' : type === 'supplement' ? '补充已与原资料一并保存。' + (s.status === 'PLANNED' ? '请核对新计划后再开始计算。' : '尚未运行计算。') : type === 'save' ? '资料已保存，请重新整理并核对计划。' : type === 'plan' ? '整理结果已保存。只有你批准计划后才开始计算。' : type === 'explain' ? '解释已保存，可对照下面的实际计算记录。' : '已提交已批准的计划。页面会自动更新运行状态。');
    } catch (e) { if (!e.uncertain) clear('pending:' + id); message('notice',''); message('error', e.message); }
    finally { try { await refreshAI(); } catch (_) {} setBusy(false); aiBadge(); render(); if (['revise','revise_goal'].includes(type)) window.scrollTo(0,0); if(type==='inverse_research_prepare'){const target=current?.research_origin?.kind==='request_calibration'?'contrast-calibration':current?.research_origin?.status==='PROPOSALS_READY'||current?.research_origin?.status==='ACQUISITION_SELECTED'?'research-plans':null;if(target)document.getElementById(target)?.scrollIntoView({block:'start'});} }
  }
  function consent(label) { const wrap = node('label', null, 'consent'), input = node('input'); input.type = 'checkbox'; wrap.append(input, node('span', label)); return {wrap,input}; }

  function aiBadge() {
    $('ai-status').textContent = boot.ai?.live_enabled ? 'AI 已连接' : boot.capabilities?.local_workers ? 'AI 未连接 · 可本地计算' : '可查看记录 · 计算未启用';
    $('ai-status').className = 'badge' + (boot.ai?.live_enabled ? ' ok' : '');
    $('ai-settings').textContent = boot.ai?.live_enabled ? 'AI 连接设置' : '连接 AI';
    $('ai-settings').disabled = busy;
  }
  async function refreshAI() {
    const latest = await api('/bootstrap'); boot.ai = latest.ai; boot.capabilities = latest.capabilities; aiBadge();
  }
  async function openAI() {
    if (busy || !boot) return;
    const dialog = $('ai-dialog'); dialog.replaceChildren();
    const title = node('h2','连接 DeepSeek'); title.id = 'ai-dialog-title';
    const status = node('p','正在读取连接状态…','section-note'); status.setAttribute('role','status');
    const close = button('返回工作台',()=>dialog.close());
    append(dialog,title,status,close); dialog.showModal();
    let binding;
    try { binding = await api('/ai/status'); }
    catch (e) { status.textContent = e.message; return; }
    if (!dialog.open) return;
    status.textContent = binding.reason;
    const form = node('form'); form.autocomplete = 'off';
    const keyLabel = node('label','API Key'); keyLabel.htmlFor = 'personal-api-key';
    const key = node('input'); key.id = 'personal-api-key'; key.type = 'password'; key.autocomplete = 'off'; key.spellcheck = false; key.maxLength = 204; key.placeholder = 'sk-…'; key.required = true;
    const limitLabel = node('label','本工作区累计 AI 请求上限（可自行调整）'); limitLabel.htmlFor = 'personal-ai-limit';
    const limit = node('input'); limit.id = 'personal-ai-limit'; limit.type = 'number'; limit.min = '1'; limit.step = '1'; limit.value = String(binding.request_limit); limit.required = true;
    const quotaHelp = node('p','默认20次，可按需提高到200、1000或更多次；这是累计请求上限，不是追加次数。一次操作可能包含多次请求。','field-note');
    limitLabel.append(quotaHelp);
    const approve = consent('使用我自己的账户，了解后续 AI 请求由 DeepSeek 按实时价格计费。');
    const recover = consent('我已核对上次请求；保留其次数和可能费用，恢复后只发起新的请求。');
    recover.wrap.hidden = !binding.needs_recovery;
    const submit = node('button','验证并连接','button primary'); submit.type = 'submit'; submit.disabled = true;
    const disconnect = button('断开 AI 连接',()=>change('/ai/disconnect',{}));
    disconnect.disabled = !(binding.connected || boot.ai?.live_enabled);
    const official = node('a','前往 DeepSeek 创建 API Key ↗'); official.href = 'https://platform.deepseek.com/api_keys'; official.target = '_blank'; official.rel = 'noopener noreferrer';
    const update = () => { submit.disabled = busy || !key.value.trim() || !approve.input.checked || !limit.validity.valid || !Number.isSafeInteger(Number(limit.value)) || Number(limit.value) <= binding.requests_used || binding.needs_recovery && !recover.input.checked; };
    [key,limit,approve.input,recover.input].forEach(el=>el.addEventListener('input',update));
    const redraw = () => {
      const drafts = [...$('content').querySelectorAll('textarea')].map(el=>el.value);
      render(); [...$('content').querySelectorAll('textarea')].forEach((el,i)=>{if(drafts[i]!==undefined){el.value=drafts[i];el.dispatchEvent(new Event('input'));}});
    };
    async function change(path, body) {
      key.value = ''; setBusy(true); status.textContent = path.endsWith('/connect') ? '正在验证账户与模型；不会生成内容。' : '正在断开连接…';
      try {
        const result = await api(path,body); body.api_key = undefined;
        await refreshAI(); status.textContent = path.endsWith('/disconnect') ? '已断开，实验仍可本地查看和计算。' : '连接成功。返回工作台，勾选发送资料后即可使用 AI。';
        binding = result; recover.wrap.hidden = !binding.needs_recovery;
      } catch (e) {
        body.api_key = undefined; status.textContent = e.message;
        try { await refreshAI(); binding = await api('/ai/status'); } catch (_) {}
      } finally {
        setBusy(false); redraw(); aiBadge(); update(); disconnect.disabled = !(binding.connected || boot.ai?.live_enabled);
      }
    }
    form.addEventListener('submit',event=>{event.preventDefault();if(!submit.disabled)change('/ai/connect',{api_key:key.value.trim(),request_limit:Number(limit.value),approve:approve.input.checked,resume:recover.input.checked});});
    dialog.oncancel = event=>{if(busy)event.preventDefault();};
    dialog.addEventListener('close',()=>{key.value='';dialog.replaceChildren();},{once:true});
    append(form,node('p','填入 API Key，验证连接后返回实验。发送资料前会请你确认。','field-note'),
      node('p','key 只交给本机服务，并用于连接 DeepSeek 官方接口；不写入项目文件或浏览器存储。重启服务后需重新填写。同一本机工作区的页面共用此连接。','field-note'),
      official,keyLabel,key,limitLabel,limit,
      node('p','本工作区已发送 '+binding.requests_used+' 次，剩余 '+binding.requests_remaining+' 次。断开、换 key 或重启不会清零；需要更多时可明确提高上限。请求次数上限不代表费用上限，实际费用以 DeepSeek 账户记录为准。','field-note'),
      approve.wrap,recover.wrap,append(node('div',null,'actions'),submit,disconnect));
    dialog.replaceChildren(title,status,form,node('p','验证只查询模型与账户状态，不发起生成。实验内容在你同意后才发送；计算计划仍需另行批准。','field-note'),close);
    key.focus();
  }

  Object.assign(NAMES,{'execution.fast_only':'只做快速计算',wavelengths_um:'计算波长目录（μm）',film_n:'膜层折射率',min:'下限',max:'上限',values:'目录'});
  async function createLibrary(body) {
    if(busy)return; setBusy(true);message('error','');
    try { current=await api('/library/create',{...body,session_version:2});cacheCase(current);updateLocation(current.id);message('notice','案例已改编为新计划，尚未计算。请核对参数和候选后运行。'); }
    catch(e){message('error',e.message);} finally {setBusy(false);render();}
  }
  function renderLibrary(host) {
    const section=card('案例库');section.id='case-library';
    append(section,node('p','选教学参数直接练习，或换成自己的资料。每次改编都会生成新计划，结果由实际计算产生。','section-note'));
    const search=node('input');search.type='search';search.placeholder='搜索：条纹太密、膜厚、焦距、中心变暗…';search.setAttribute('aria-label','搜索本地案例');
    const filter=node('select');filter.setAttribute('aria-label','案例场景');
    [['','全部场景'],...Object.entries(DOMAINS)].forEach(([v,t])=>{const o=node('option',t);o.value=v;filter.append(o);});
    const grid=node('div',null,'teaching-grid');
    function draw(){grid.replaceChildren();const q=search.value.trim().toLowerCase();
      const rows=(boot.case_library||[]).filter(c=>(!filter.value||c.domain===filter.value)&&(!q||[c.title,c.id,c.scope,...c.tags].join(' ').toLowerCase().includes(q)));
      rows.forEach(c=>{const box=node('article',null,'teaching-card');box.dataset.caseId=c.id;
        append(box,badge(c.id+' · '+DOMAINS[c.domain]),node('h3',c.title),node('p',c.scope),
          button('运行教学示例',()=>showCaseForm(c.id,'teaching'),'small'),button('改成我的参数',()=>showCaseForm(c.id,'specified'),'small'),button('用教学参数探索目标',()=>showCaseForm(c.id,'teaching'),'small subtle'));
        if(c.preview?.id)append(box,node('p','已有计算预览；改参数不会更新旧图。','field-note'),button('查看已有计算预览',()=>select(c.preview.id),'small subtle'));
        else box.append(node('p','尚无已计算预览；采用后会实际运行。','field-note'));
        grid.append(box);
      });if(!rows.length)grid.append(node('p','没有匹配案例。可以用自己的资料让 AI 检索兼容案例，超出模型范围会明确说明。'));
    }
    search.addEventListener('input',draw);filter.addEventListener('change',draw);append(section,append(node('div',null,'actions'),search,filter),grid);host.append(section);draw();
  }
  function showCaseForm(id,mode,parent=null,recovery=null) {
    const c=boot.case_library.find(x=>x.id===id);if(!c)return;
    $('library-editor')?.remove();const section=card((parent?'继续探索：':mode==='teaching'?'使用教学参数：':'填写我的参数：')+c.title);section.id='library-editor';
    append(section,node('p',c.scope,'section-note'),node('p',recovery?'直接补全当前计划；请核对目标和候选。来源版本的物理条件保持不变，继续使用本次探索剩余额度，不自动开始计算。':parent?'以当前已选候选为起点，其他物理条件保持不变。新增候选另存探索分支；同配方细化共享计算额度，最多两阶段。':mode==='teaching'?'下列数值是教学示例，可以修改；不会标为实测资料。':'真实参数留空时会要求补充，不套用教学值。数值网格等计算设置另行列明。','field-note'));
    const inputMap={};const physical=node('div',null,'recipe-fields');
    const selected=parent?.result?.candidates?.find(x=>x.id===parent.result.winner_id);
    const inherited=parent?{...parent.spec.known_parameters,...(selected?.changes||{})}:{};
    function field(key,value,label=name(key),readonly=false){const wrap=node('label',null,'input-label');const input=node('input');input.type='number';input.step='any';input.value=value??'';input.dataset.parameter=key;input.setAttribute('aria-label',label);input.readOnly=readonly;append(wrap,node('span',label),input);physical.append(wrap);inputMap[key]=input;return input;}
    c.required_parameters.forEach(key=>field(key,parent?inherited[key]:mode==='teaching'?c.teaching.parameters[key]:'',name(key),!!parent));
    Object.entries(c.numeric_defaults).forEach(([key,value])=>field(key,parent?(inherited[key]??value):value,name(key)+'（计算设置）',!!parent));
    section.append(physical);
    const g={...(parent?.spec.goal?.metric===c.teaching.goal.metric?parent.spec.goal:c.teaching.goal)};
    const goals=node('div',null,'recipe-fields'),operator=node('select');operator.setAttribute('aria-label','案例目标比较方式');
    ['<=','>=','near','minimize','maximize'].forEach(v=>{const o=node('option',name(v));o.value=v;operator.append(o);});operator.value=g.operator;
    append(goals,node('label','目标：'+name(g.metric)),operator);
    function goalField(key,value,label){const wrap=node('label',null,'input-label'),i=node('input');i.type='number';i.step='any';i.value=value??'';i.setAttribute('aria-label',label);append(wrap,node('span',label),i);goals.append(wrap);return i;}
    const target=goalField('target',g.target,'目标值'),tolerance=goalField('tolerance',g.tolerance??.01,'接近目标的允许误差');
    const wavelength=c.domain==='film'?goalField('wavelength_um',g.wavelength_um??.633,'目标波长（μm）'):null;
    const updateGoal=()=>{target.disabled=['minimize','maximize'].includes(operator.value);tolerance.disabled=operator.value!=='near';};operator.addEventListener('change',updateGoal);updateGoal();section.append(goals);
    let values=null,lo=null,hi=null;
    if(c.recipe.method==='fringe_target'){
      const limits=node('div',null,'recipe-fields');
      for(const [key,label] of [['min','允许缝距下限（μm）'],['max','允许缝距上限（μm）']]){const wrap=node('label',null,'input-label'),i=node('input');i.type='number';i.step='any';i.setAttribute('aria-label',label);i.value=(parent?.library_origin?.request?.bounds?.[key]??(mode==='teaching'?c.teaching.bounds[key]:''));append(wrap,node('span',label),i);limits.append(wrap);if(key==='min')lo=i;else hi=i;}section.append(limits);
    }else if(!['single','phase'].includes(c.recipe.method)){
      const label=node('label','允许的有限候选（逗号分隔；单位见参数名）','input-label');values=node('input');values.setAttribute('aria-label','允许的有限候选');let prior=parent?.spec.allowed_variables?.[c.recipe.variable];if(c.recipe.variable==='layers'&&prior)prior=prior.map(v=>v[0].thickness_um);values.value=(prior??(mode==='teaching'?c.teaching.values:[])).join(', ');append(section,label,values);
    }else if(c.recipe.method==='phase')section.append(node('p','相位配方比较 0、π/2、π；保持已选几何与入射条件不变。','field-note'));
    const note=node('p','','message error');section.append(note);
    const send=button(recovery?'保存参数并恢复当前计划':parent?'建立新探索分支并核对计划':'生成有限候选计划',async()=>{
      try{
        const parameters={};if(!parent)Object.entries(inputMap).forEach(([k,i])=>{if(i.value.trim())parameters[k]=Number(i.value);});
        const goal={metric:g.metric,operator:operator.value};if(!target.disabled){if(!target.value.trim())throw Error('请填写目标值');goal.target=Number(target.value);}if(!tolerance.disabled)goal.tolerance=Number(tolerance.value);if(wavelength)goal.wavelength_um=Number(wavelength.value);
        const request={case_id:id,parameters,goal};if(values)request.values=values.value.split(/[,，、\s]+/).filter(Boolean).map(Number);if(lo){if(!lo.value.trim()||!hi.value.trim())throw Error('请填写允许缝距范围');request.bounds={min:Number(lo.value),max:Number(hi.value)};}
        if(recovery)await mutate('library_plan',{request});else if(parent)await mutate('explore_case',{request,new_exploration:true});else await createLibrary({case_id:id,mode,request});
      }catch(e){note.textContent=e.message;}
    },'primary');section.append(send);$('content').append(section);section.scrollIntoView({block:'start',behavior:'smooth'});
  }
  function renderCaseExploration(host,s,pending){
    const section=card('从这个结果继续探索'),choice=node('select');choice.setAttribute('aria-label','下一步实验案例');
    section.id='case-exploration';
    (boot.case_library||[]).filter(c=>c.domain===s.domain).forEach(c=>{const o=node('option',c.id+' · '+c.title);o.value=c.id;choice.append(o);});choice.value=s.library_origin?.case_id||choice.value;
    append(section,node('p','使用当前最佳候选的实际参数作为起点。新目标产生新计划，旧图和旧结果保留。','section-note'),choice,button('设置目标与候选范围',()=>showCaseForm(choice.value,'specified',s),'',pending));
    const text=node('textarea');text.rows=3;text.setAttribute('aria-label','下一步探索要求');text.placeholder='例如：目标改成0.90 mm，允许缝距120–220 μm，其余保持；或者保持选好的几何，把中心变暗。';
    const permit=consent('允许真实 AI 根据已选计算记录与本次要求规划新探索，使用现有额度。');
    const live=button('让 AI 规划下一步',()=>mutate('explore_case',{mode:'live',approve_data:true,new_exploration:true,case_id:choice.value,text:text.value}),'',true);
    const update=()=>{live.disabled=busy||pending||!boot.ai?.live_enabled||!permit.input.checked||!text.value.trim()||credentialLike(text.value);};text.addEventListener('input',update);permit.input.addEventListener('change',update);
    append(section,text,permit.wrap,live);if(s.parent_id)section.append(button('取消后续修改，恢复来源结果',()=>mutate('restore_result',{target_id:s.parent_id}),'small subtle',pending));host.append(section);
  }

  Object.assign(NAMES,{rows:'观测行数',position_unit:'坐标单位',measurement_plane:'测量平面',FOURIER_FOCAL_PLANE:'理想透镜傅里叶焦平面',NEAR_FIELD:'近场（当前不适用）',slit_separation_um:'缝距（μm）',center_shift_mm:'中心偏移（mm）',amplitude:'正幅度',background:'背景',training:'训练点',holdout:'预先留出点',count:'点数',rmse:'均方根残差',median_absolute_residual:'残差绝对值中位数'});
  function renderMissions(host) {
    if(!boot.missions?.length)return;
    const section=card('沿一条任务链继续实验'),grid=node('div',null,'teaching-grid');
    boot.missions.forEach(m=>{const box=node('article',null,'teaching-card');append(box,node('h3',m.title),node('p',m.description));
      m.cases.forEach(id=>{const item=boot.case_library.find(c=>c.id===id);if(item)box.append(button(id+' · '+item.title,()=>createLibrary({case_id:id,mode:'teaching',session_version:2}),'small'));});
      if(m.data_step)box.append(button('分析一段干涉数据',()=>$('observation-import').scrollIntoView({block:'start'}),'small'));grid.append(box);});
    append(section,node('p','任务链引用原案例，点击会创建需要核对的新实验；不自动计算。','field-note'),grid);host.append(section);
  }
  async function createObservation(body) {
    if(busy)return;setBusy(true);message('error','');
    try {const s=await api('/observations',body);current=s;cacheCase(s);updateLocation(s.id);message('notice','原始数据已保留。请核对单位、固定条件与拟合范围；尚未计算。');}
    catch(e){message('error',e.message);}finally{setBusy(false);render();window.scrollTo(0,0);}
  }
  function renderObservationImport(host) {
    const box=card('分析一段干涉数据');box.id='observation-import';
    append(box,node('p','首版只支持相位为 0 的理想透镜焦平面双缝中心截线。已知波长、焦距和缝宽，估计缝距及观测偏移、幅度、背景。','section-note'));
    if(!boot.capabilities?.analysis)box.append(node('p','本环境未安装可选 SciPy，仍可导入与核对数据；原有实验不受影响。安装方法见 README。','inline-notice'));
    const sampleBox=node('div',null,'actions');(boot.data_samples||[]).forEach(item=>sampleBox.append(button(item.title,()=>createObservation({sample_id:item.id}),'small')));
    append(box,node('h3','没有数据，先试显著标注的合成样例'),sampleBox);
    const own=append(node('details'),node('summary','导入自己的 CSV（最多 2 MiB、20–5000 行）'));
    const file=node('input');file.type='file';file.accept='.csv,text/csv';file.setAttribute('aria-label','选择观测 CSV');
    const source=node('input');source.type='text';source.maxLength=300;source.placeholder='数据来自哪里，例如：本次实验的相机中心截线';source.setAttribute('aria-label','数据来源说明');
    const kind=node('select');kind.setAttribute('aria-label','数据来源类型');[['USER_PROVIDED','自己的数据（来源由用户声明）'],['LICENSED_PUBLIC','有许可的公开数据'],['SYNTHETIC_TEACHING','自己的合成教学数据']].forEach(([v,t])=>{const o=node('option',t);o.value=v;kind.append(o);});
    const unit=node('select');unit.setAttribute('aria-label','位置单位');[['','按列名；无明确单位则暂停'],['mm','毫米 mm'],['um','微米 μm'],['m','米 m'],['pixel','像素 pixel（不能直接估计物理缝距）']].forEach(([v,t])=>{const o=node('option',t);o.value=v;unit.append(o);});
    const license=node('input');license.placeholder='公开数据的许可名称或授权说明';license.setAttribute('aria-label','数据许可');license.hidden=true;
    const preview=node('pre','尚未选择文件。','input-preview');let text='';
    const upload=button('保留原始数据，进入核对',()=>createObservation({csv_text:text,source_kind:kind.value,source_name:source.value,position_unit:unit.value||null,license:license.value}),'primary',true);
    const update=()=>{license.hidden=kind.value!=='LICENSED_PUBLIC';upload.disabled=busy||!text||!source.value.trim()||kind.value==='LICENSED_PUBLIC'&&!license.value.trim();};
    file.addEventListener('change',async()=>{text='';update();const f=file.files?.[0];if(!f)return;if(f.size>2*1024*1024){preview.textContent='文件超过 2 MiB，未上传。';return;}try{text=new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer());preview.textContent=text.split(/\r?\n/).slice(0,7).join('\n');}catch(_){preview.textContent='需要 UTF-8 编码的 CSV。';}update();});
    [source,kind,license].forEach(el=>el.addEventListener('input',update));
    append(own,node('p','两列：position_mm / position_um / position_m / pixel / position，以及 intensity_relative。不会静默删行、删异常点或执行公式。pixel 需要真实刻度，不能通过改单位标签变成物理测量。','field-note'),file,preview,kind,source,license,unit,upload);box.append(own);host.append(box);
  }
  function renderObservation(host,s,pending) {
    const v=s.experiment_record,r=s.fit_result;
    append(host,node('p','数据 → 模型估计 → 正向核对 → 新目标','eyebrow'),node('h1',s.title),badge(STATES[s.status]||s.status),node('p',v.scope,'section-note'));
    if(s.error)host.append(node('p',s.error,'message error'));
    const origin=card('这份数据来自哪里');append(origin,node('p',v.dataset.source_kind==='SYNTHETIC_TEACHING'?'合成教学数据，不是真实仪器测量。':'用户声明的数据来源：'+v.dataset.source_name,'inline-notice'),facts({rows:v.dataset.rows,position_unit:v.dataset.position_unit||'缺少刻度',source:v.dataset.source_name}),detail('数据预览与来源记录',v.dataset));host.append(origin);
    if(s.questions?.length)host.append(append(card('这些条件需要先核对'),list(s.questions.map(humanizeQuestion))));
    if(s.parent_id)host.append(button('查看上一版设置与结果',()=>select(s.parent_id),'small'));
    if(s.status==='RUNNING'){host.append(node('p','正在执行已批准的有限拟合；不自动重试。','inline-notice'));schedulePoll(s.id);return;}
    const ai=card(r?'问问这次数据与结果':'用一句话补充已知条件'),question=node('textarea');question.rows=2;question.maxLength=6000;question.placeholder=r?'例如：为什么这些残差点仍然保留？这次估计有什么限制？':'例如：双缝透镜焦平面，波长633nm，焦距200mm，两缝等宽20μm且同相，位置是毫米，缝距90到270微米。其余拟合设置请给建议。';question.setAttribute('aria-label','数据分析问题');
    const permit=consent('同意把问题、数据摘要、已填条件和拟合摘要发送给已连接的 AI（不发送完整 CSV）。');const send=button(r?'解释本次结果 / 整理修改':'整理条件并建议数值配置',()=>mutate('fit_wizard',{text:question.value,approve_data:true}),'',true);
    const update=()=>send.disabled=busy||pending||!boot.ai?.live_enabled||!permit.input.checked||!question.value.trim()||credentialLike(question.value);question.addEventListener('input',update);permit.input.addEventListener('change',update);append(ai,question,permit.wrap,send);if(s.fit_ai_guidance)append(ai,node('p',s.fit_ai_guidance.text,'inline-notice'),detail('解释依据',s.fit_ai_guidance));if(!r)host.append(ai);
    if(s.fit_settings?.fixed)host.append(append(card('当前实验条件与数值建议'),facts(s.fit_settings.fixed),node('p',s.numerical_recipe?'中心、幅度、背景和残差尺度中的建议项来自预先规定的训练点配方，不是测量事实；已有用户范围不会扩大。':'来源以已选教学资料、上传元数据或已确认输入为准。','field-note'),detail('逐项来源与可估范围',{sources:v.field_sources,bounds:s.fit_settings.bounds,loss:s.fit_settings.loss,f_scale:s.fit_settings.f_scale,recipe:s.numerical_recipe})));
    if(!s.fit_approved_sha256&&!r) {
      const panel=card('审核拟合草稿'),form=append(node('details'),node('summary','高级编辑：物理条件和数值设置')),cfg=s.fit_settings||{},fixed=cfg.fixed||{},fields={},bounds={};
      const addNumber=(key,label,value,parent=form)=>{const wrap=node('label',label),input=node('input');input.type='number';input.step='any';input.value=value??'';input.setAttribute('aria-label',label);input.disabled=pending;wrap.append(input);parent.append(wrap);return input;};
      [['wavelength_nm','波长（nm）'],['focal_length_mm','透镜焦距（mm）'],['slit_width_um','已知缝宽（μm）'],['relative_phase_rad','已知相对相位（rad；仅支持 0）']].forEach(([key,label])=>fields[key]=addNumber(key,label,fixed[key]));
      const plane=node('select');plane.setAttribute('aria-label','测量平面');[['','请选择测量平面'],['FOURIER_FOCAL_PLANE','理想透镜傅里叶焦平面'],['NEAR_FIELD','自由传播近场（当前模型不适用）']].forEach(([value,text])=>{const option=node('option',text);option.value=value;plane.append(option);});plane.value=fixed.measurement_plane||'';plane.disabled=pending;form.append(plane);
      form.append(node('h3','只估计以下四项；上下界须明确'));
      [['slit_separation_um','缝距（μm）'],['center_shift_mm','中心偏移（mm）'],['amplitude','正幅度'],['background','背景']].forEach(([key,label])=>{const row=node('div',null,'two-columns');bounds[key]=[addNumber(key+'min',label+'下界',cfg.bounds?.[key]?.[0],row),addNumber(key+'max',label+'上界',cfg.bounds?.[key]?.[1],row)];form.append(row);});
      const loss=node('select');loss.setAttribute('aria-label','拟合损失');['soft_l1','linear'].forEach(val=>{const opt=node('option',val==='soft_l1'?'soft_l1：降低异常点影响，保留所有原始点':'linear：普通平方残差');opt.value=val;loss.append(opt);});loss.value=cfg.loss||'soft_l1';loss.disabled=pending;form.append(loss);const scale=addNumber('f_scale','残差尺度 f_scale',cfg.f_scale??.01);
      const gather=()=>({fixed:{...Object.fromEntries(Object.entries(fields).map(([k,input])=>[k,input.value.trim()===''?null:Number(input.value)])),measurement_plane:plane.value||null},bounds:Object.fromEntries(Object.entries(bounds).map(([k,inputs])=>[k,inputs.map(input=>input.value.trim()===''?null:Number(input.value))])),loss:loss.value,f_scale:scale.value.trim()===''?null:Number(scale.value)});
      const review=button('保存条件，检查拟合计划',()=>mutate('fit_plan',{settings:gather()}),'primary',pending);
      append(form,node('p','最多 9 个起点、每起点 max_nfev 200、实际残差调用总计最多 12000；60 秒、1 GiB、输出 32 MiB。同一数据任务最多批准 3 次拟合。每五个原始点预先留出一个，留出数据不用于选起点。','field-note'),review);
      panel.append(form);
      if(s.fit_plan){const consentRun=consent('我已核对原始数据、单位、模型、四项范围与预算，批准这次拟合。');const run=button('运行这份有限拟合',()=>mutate('fit_run',{approve:true,plan_sha256:s.fit_plan.sha256}),'primary',true);
        const dirty=()=>JSON.stringify(gather())!==JSON.stringify({fixed:cfg.fixed,bounds:cfg.bounds,loss:cfg.loss,f_scale:cfg.f_scale});
        const update=()=>run.disabled=busy||pending||!boot.capabilities?.analysis||!boot.capabilities?.local_workers||!consentRun.input.checked||dirty();
        [...Object.values(fields),...Object.values(bounds).flat(),plane,loss,scale,consentRun.input].forEach(input=>input.addEventListener('input',update));append(panel,node('p','草稿已经通过范围检查；运行前请核对上面的物理条件和逐项数值建议。','field-note'),consentRun.wrap,run,detail('已冻结的拟合计划',s.fit_plan));}
      host.append(panel);
    }
    if(r){
      const result=card(r.usable_for_forward?'已得到模型估计，请核对残差':'拟合已记录，当前不接受唯一参数结论');result.id='fit-result';result.append(node('p',v.explanation,'inline-notice'));
      const warn={BOUNDARY_HIT:'估计碰到参数边界',INSUFFICIENT_INFORMATION:'数据覆盖或参数可辨识性不足',MULTIPLE_COMPARABLE_SOLUTIONS:'存在多个相近质量的不同解',POSSIBLE_MODEL_MISMATCH:'残差提示噪声较大或模型可能失配',RESOURCE_STOP:'资源上限停止，起点搜索不完整'};
      if(r.estimated_parameters)append(result,facts(r.estimated_parameters),node('p','上面四项为模型估计；中心偏移、幅度、背景是观测模型的干扰参数，不是新增器件参数。','field-note'));
      if(r.warnings.length)result.append(list(r.warnings.map(k=>warn[k]||k)));
      if(r.data){append(result,plot(r.data),node('h3','原始残差：观测 − 预测'),plot({x:r.data.x,x_label:'位置（mm）',y_label:'残差',series:[{label:'原始残差，含异常点',y:r.data.residual,points:true}]}),node('h3','训练与留出指标（分别记录）'),facts(r.metrics));}
      append(result,detail('全部起点、成功与失败',r.starts),detail('边界、多解与局部可辨识性诊断',r.diagnostics||{}),detail('实际资源记录',r.resources));host.append(result);
      if(r.usable_for_forward){const next=card('采用估计，另建正向核对');
        if(s.forward_children?.length)next.append(button('打开已有正向任务',()=>select(s.forward_children[0]),'primary'));
        else {const geometry={};[['slit_height_um','明确的缝高（μm）',100],['grid_size','FFT 网格（256 或 512）',256],['window_mm','孔径面窗口（mm）',.4]].forEach(([k,label,value])=>{const input=node('input');input.type='number';input.step='any';input.value=value;input.setAttribute('aria-label',label);geometry[k]=input;append(next,node('label',label),input);});
          const accepted=consent('我确认采用模型估计作输入，并核对以上二维补充条件；这些值不是从一维数据识别得到的。');const forward=button('创建正向核对计划（尚不计算）',()=>mutate('fit_forward',{approve_estimate:true,geometry:Object.fromEntries(Object.entries(geometry).map(([k,v])=>[k,Number(v.value)]))}),'primary',true);accepted.input.addEventListener('change',()=>forward.disabled=busy||pending||!accepted.input.checked);append(next,node('p','显示的缝高和网格为待确认建议值。正向 FFT 和解析模型使用实际 FFT 坐标；不会把绘图插值当作新的观测。正向完成后可使用原 D02 入口探索新的条纹目标。','field-note'),accepted.wrap,forward);}
        host.append(next);}
    }
    if(r)host.append(ai);
    const actions=card('保存、复核和继续');append(actions,button('另存一版拟合设置',()=>mutate('fit_revise',{}),'small',pending));
    if(s.fit_progress)actions.append(detail('中断前的实际进度',s.fit_progress));
    const link=(label,suffix)=>{const a=node('a',label,'button small');a.href='/api/experiments/cases/'+s.id+suffix;return a;};append(actions,link('导出此版本数据与证据','/export'),link('导出这条数据任务链','/family-export'),link('打开只读拟合摘要','/summary'));if(r?.data)actions.append(link('下载原坐标残差 CSV','/table'));host.append(actions);
  }
  const INV_SLIT='double_slit_width_spacing_v1', INV_GAUSS='gaussian_caustic_m2fixed1_v1';
  Object.assign(NAMES,{source_kind:'数据类别',wavelengths_nm:'波长（nm）',reflectance:'反射率',finite_intervals:'有限搜索区间数',period_nm_at_first_wavelength:'首个波长的厚度周期（nm）',local_scales:'参数预测尺度（非置信区间）',prediction_scale:'区间预测尺度',dominated:'存在各方面不差的替代方案',points:'新增观测数',score:'候选预测差异',thickness_nm:'厚度（nm）',cost:'拟合代价',observed:'实际观测',predicted:'代表候选预测',residual:'残差'});
  const INV_LABELS={wavelength_nm:'波长（nm）',focal_length_mm:'焦距（mm）',relative_phase_rad:'已知相位（rad）',measurement_plane:'测量平面',m2:'固定 M²',propagation:'传播条件',slit_width_um:'缝宽（μm）',slit_separation_um:'缝距（μm）',center_shift_mm:'中心偏移（mm）',amplitude:'幅度',background:'背景',waist_radius_um:'束腰半径（μm）',waist_z_mm:'束腰全局位置（mm）'};
  function invNumber(host,label,value){const wrap=node('label',label),input=node('input');input.type='number';input.step='any';input.value=value??'';input.setAttribute('aria-label',label);wrap.append(input);host.append(wrap);return input;}
  function invSelect(host,label,options,value){const wrap=node('label',label),input=node('select');input.setAttribute('aria-label',label);options.forEach(([v,t])=>{const o=node('option',t);o.value=v;input.append(o);});input.value=value??options[0][0];wrap.append(input);host.append(wrap);return input;}
  const invValue=input=>input.value.trim()===''?null:Number(input.value);
  async function createInverse(body){if(busy)return;setBusy(true);message('error','');try{current=await api('/inverse',body);cacheCase(current);updateLocation(current.id);message('notice','数据已保留，尚未拟合。教学对象与实际数据分别标注。');}catch(e){message('error',e.message);}finally{setBusy(false);render();}}
  function inverseUpload(host,submit){
    const file=node('input');file.type='file';file.accept='.csv';file.setAttribute('aria-label','反向分析 CSV');const preview=node('pre','请选择 CSV。','input-preview');let text='';
    const source=node('input');source.placeholder='来源说明';source.setAttribute('aria-label','反向数据来源');
    const kind=invSelect(host,'数据来源',[['USER_PROVIDED','自己的数据'],['LICENSED_PUBLIC','有许可的公开数据'],['SYNTHETIC_TEACHING','合成教学数据']],'USER_PROVIDED');
    const license=node('input');license.placeholder='公开资料需填写许可';license.setAttribute('aria-label','反向数据许可');
    const diameter=consent('若列名为 diameter_1e2_um，我确认这是 1/e² 强度直径，批准半径和标准差同时除以 2。');
    const approve=consent('明确导入这份原始数据；若为补采，它将成为新联合拟合的资料。');
    const go=button('导入原始 CSV',()=>submit({csv_text:text,source_kind:kind.value,source_name:source.value,license:license.value,diameter_conversion:diameter.input.checked,approve:true}),'primary',true);
    const update=()=>go.disabled=busy||!text||!source.value.trim()||!approve.input.checked||kind.value==='LICENSED_PUBLIC'&&!license.value.trim();
    file.addEventListener('change',async()=>{text='';update();const f=file.files?.[0];if(!f)return;if(f.size>2*1024*1024){preview.textContent='文件超过 2 MiB';return;}try{text=new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer());preview.textContent=text.split(/\r?\n/).slice(0,7).join('\n');}catch(_){preview.textContent='请使用 UTF-8 CSV';}update();});
    [source,kind,license,approve.input].forEach(el=>el.addEventListener('input',update));append(host,file,preview,source,license,diameter.wrap,approve.wrap,go);
  }
  function renderInverseImport(host){
    const box=card('从数据反推，再决定补测哪里');box.id='inverse-import';append(box,node('p','双缝：同时估计缝宽与间距，查看候选，再比较补采。高斯：由纵向扫描估计束腰，接回透镜目录。都仅限明确声明的理想模型。'));
    if(!boot.capabilities?.analysis)box.append(node('p','可选 SciPy 未安装：可保存和核对数据，拟合暂停；旧正向入口保留。','inline-notice'));
    append(box,button('教学模拟 · 未知缝宽与缝距',()=>createInverse({model:INV_SLIT,teaching:true}),'primary'),button('教学模拟 · 高斯束腰',()=>createInverse({model:INV_GAUSS,teaching:true})),node('p','教学按钮创建预先冻结的独立对象。补采不会从当前最佳拟合值生成；不控制真实仪器。','field-note'));
    box.append(button('教学模拟 · 单层膜厚度与补测波长',()=>createInverse({model:'single_film_known_index_v1',teaching:true}),'primary'));
    box.append(node('p','单层膜仅接受 wavelength_nm,reflectance_calibrated：已知折射率、法向入射、无损、已校准反射率。'));
    const own=append(node('details'),node('summary','导入自己的反向分析数据'));const model=invSelect(own,'反向分析模型',[[INV_SLIT,'未知缝宽与缝距'],[INV_GAUSS,'高斯束腰（M²=1）'],['single_film_known_index_v1','已知折射率单层膜厚度']],INV_SLIT);
    own.append(node('p','双缝：position_mm,intensity_relative（也接受明确的 um/m 坐标）。高斯：z_mm,radius_1e2_um，可选 radius_sd_um。未知宽度定义、FWHM 和像素刻度须先核对。'));
    inverseUpload(own,data=>{const {approve,...rest}=data;createInverse({model:model.value,...rest});});box.append(own);host.append(box);
  }
  function renderCalibration(host,s,pending){
    if(s.inverse_settings.model!==INV_SLIT)return;
    const panel=append(node('details'),node('summary','小型校准：这一个频率的对比度保留了多少？'));
    panel.id='contrast-calibration';panel.open=!!s.calibration_draft||!!s.contrast_calibration||s.research_origin?.kind==='request_calibration';
    append(panel,node('p','已知正弦参照加一份独立暗场，可估计该频率的对比传递。它不能还原完整模糊核，也不能认证缝宽。'),button('载入单频校准教学案例',()=>mutate('inverse_calibration_example',{}),'small',pending));
    const file=node('input');file.type='file';file.accept='.json,application/json';file.setAttribute('aria-label','导入单频参照与暗场 JSON');
    let inputs=s.calibration_draft?.inputs||null;const preview=node('pre',inputs?JSON.stringify({frequency_per_mm:inputs.frequency_per_mm,input_contrast:inputs.input_contrast,reference:inputs.reference,dark:inputs.dark},null,2):'可载入教学案例，或导入包含参照与独立暗场的 JSON 资料。','data-preview');
    const approve=consent('我已核对已知频率、输入对比度、线性/未饱和声明，以及参照与独立暗场使用相同配置；批准本次小型计算。');
    const go=button('估计该频率的对比传递',()=>mutate('inverse_calibration_run',{inputs,approve:true}),'',true);
    const update=()=>go.disabled=busy||pending||!inputs||!approve.input.checked;
    file.addEventListener('change',async()=>{inputs=null;approve.input.checked=false;update();try{const f=file.files?.[0];if(!f)return;if(f.size>65536)throw Error('校准资料需小于 64 KiB');inputs=JSON.parse(await f.text());preview.textContent=JSON.stringify(inputs,null,2);}catch(e){preview.textContent='未读取：'+e.message;}update();});approve.input.addEventListener('input',update);
    append(panel,file,preview,approve.wrap,go,node('p','每个研究任务最多两次校准计算，原拟合与补采额度继续累计。','field-note'));
    if(s.calibration_draft?.lesson){const l=s.calibration_draft.lesson;append(panel,node('p',l.explanation),detail('教学核对：没有暗场时的等价解释与两个不同核',l));}
    if(s.calibration_attempt?.status==='REJECTED')panel.append(node('p','这份资料暂不支持校准：'+s.calibration_attempt.reason,'inline-notice'));
    if(s.contrast_calibration){const c=s.contrast_calibration;append(panel,node('h3','已保存的单频校准结果'),node('p','频率 '+display(c.frequency_per_mm)+' /mm；估计对比传递 '+display(c.estimated_contrast_transfer)+'。'),node('p',c.scope,'field-note'),detail('输入来源与计算检查',c));}
    host.append(panel);
  }
  function renderResearchAssistant(host,s,pending){
    const task=s.experiment_record.task_summary,advice=task.advice,box=card('主要下一步');box.id='task-next-step';
    box.append(node('p',advice.message,'field-note'));
    const show=a=>{const c=append(node('article'),node('h3',a.label),node('p',a.reason),node('p','预计得到：'+a.product+'。'+a.next_confirmation,'field-note'));
      if(a.needs.length)c.append(list(a.needs));c.append(button(['compare_acquisition','refit','choose_baseline','propose_followup'].includes(a.kind)?'按这个建议准备计划':'核对这个步骤',()=>mutate('inverse_research_prepare',{suggestion_sha256:advice.suggestion_sha256,action_id:a.id}),'primary',pending||!a.ready));return c;};
    if(advice.primary)box.append(show(advice.primary));else box.append(node('p',s.measurement_plan?'已有方案比较可直接核对；也可以让 AI 选择一个具体方案。':s.inverse_result?'已有分析结果。可告诉 AI 你在意什么、还能测多少，再决定下一步。':'先核对条件并分析已有数据。'));
    if(advice.blocked_primary){const blocked=advice.blocked_primary,options=append(node('section'),node('h3','这项主建议当前不能准备'),node('p',blocked.reason));options.id='feasible-proposal-options';
      append(options,list([...(blocked.measurements||[]),...(blocked.declared_limits||[])].map(v=>v.label+'：'+display(v.value)+' '+v.unit)),node('p',advice.feasible_alternatives_note,'inline-notice'));
      (advice.feasible_alternatives||[]).forEach(p=>{const row=append(node('article'),node('h4',p.label+' · 程序列出的可行备选'),node('p',p.note||''));
        row.append(detail('当前计划中的范围与成本',{range_mm:p.range_mm,wavelengths_nm:p.wavelengths_nm,cost:p.cost}));options.append(row);});
      if(advice.feasible_alternatives?.length)options.append(button('查看方案位置与核对入口',()=>{const plans=document.getElementById('available-observations')||document.getElementById('inverse-advanced');if(plans){plans.open=true;plans.scrollIntoView({block:'start'});}},'small'));
      box.append(options);}
    if(advice.alternatives.length){const alt=append(node('details'),node('summary','其他可选步骤（不作最优排名）'));advice.alternatives.forEach(a=>alt.append(show(a)));box.append(alt);}
    const askBox=append(node('details'),node('summary','告诉 AI 新要求 / 解释本次变化'));askBox.open=!advice.primary;
    const q=node('textarea');q.rows=2;q.maxLength=6000;q.placeholder='例如：只把目标改为兼顾两项；保持物理条件。或解释这次补采前后有什么变化。';q.setAttribute('aria-label','反向分析问题');if(!s.inverse_ai)q.value=s.task_goal_text||'';
    const permit=consent('同意将问题、已知条件与结果摘要发送给 AI，不发送完整 CSV 文件。'),ask=button('整理 / 建议下一步',()=>mutate('inverse_ai',{text:q.value,approve_data:true}),'',true);
    const check=()=>ask.disabled=busy||pending||!permit.input.checked||!q.value.trim()||!boot.ai?.live_enabled||credentialLike(q.value);q.addEventListener('input',check);permit.input.addEventListener('input',check);append(askBox,q,permit.wrap,ask,button('查看本地操作指引',()=>mutate('inverse_research_suggest',{text:q.value}),'small',pending));
    if(!boot.ai?.live_enabled)askBox.append(node('p','实时 AI 未连接，仍可使用本地计划与计算。','field-note'));box.append(askBox);
    if(s.inverse_ai){const r=s.inverse_ai,labels={ALL_VALID:'本次条件和建议均通过核对',PARTIAL_VALID:'本次回复部分可用',FACT_PATCH_REJECTED:'条件更新未通过，需重新核对',PROTOCOL_INVALID:'回复格式未通过，未执行'};box.append(node('p',labels[r.validation_status]||'本次回复已保存','inline-notice'));if(r.patch_error)box.append(node('p',r.patch_error));}
    box.append(detail('建议详情与处理记录',{advice:s.research_actions,receipt:s.inverse_ai,prepared:s.research_origin}));host.append(box);
  }
  function renderTaskPlan(host,s,pending){
    const t=s.experiment_record.task_summary;
    if(t.pause_reason&&t.pause_reason!==s.error)host.append(append(card('这一分支已暂停'),node('p',t.pause_reason)));
    if(s.inverse_failure_type==='SolverBusyError'){const recover=card('沿用已有资料继续');append(recover,node('p','等待其他计算结束后，另存当前数据和条件，再核对原方案并批准计算。原失败记录保留。'),button('沿用数据另存核对',()=>mutate('inverse_revise'),'small',pending));host.append(recover);}
    if(t.task_plan_current){const p=s.task_plan,item=p.selected_proposal,box=card('核对连续任务计划');box.id='continuous-task-plan';
      append(box,node('p','选定：'+(item.wavelengths_nm?item.wavelengths_nm.join('、')+' nm':item.id==='baseline'?'基础扫描方案':item.label||item.id)),list(p.steps.map(x=>x.label)),node('p','本计划共使用 1 次教学补采、1 次联合拟合；不调用 AI。完成后停止。','inline-notice'),detail('具体采样位置、条件与累计资源',{positions_mm:item.prediction_x_mm,wavelengths_nm:item.wavelengths_nm,new_data_conditions:p.new_entry,resources:p.resources,stop_conditions:p.stop_conditions}));
      const permit=consent('我已核对上述具体方案、采集条件、全部步骤及累计资源，批准这份连续任务计划。'),go=button('执行补采并继续联合分析',()=>mutate('inverse_task_run',{approve:true,plan_sha256:p.sha256}),'primary',true);permit.input.addEventListener('input',()=>go.disabled=busy||pending||!permit.input.checked||!boot.capabilities?.analysis);append(box,permit.wrap,go);host.append(box);
    }else if(s.measurement_plan&&s.inverse_result&&!s.task_execution?.started){const p=s.measurement_plan,box=append(node('details',null,'card'),node('summary','已有观测方案：核对或手动选择'));box.id='available-observations';box.append(node('p','以下方案由程序计算并列出。你也可以手动选择；选择来源会保存在记录中。'));p.plans.forEach(item=>{const row=append(node('article',null,'card'),node('h3',item.wavelengths_nm?item.wavelengths_nm.join('、')+' nm':item.id==='baseline'?'基础扫描方案':item.label||item.id),node('p',item.selection_reason||item.cost_note||p.score_definition));row.append(detail('具体位置与预测依据',item));if(s.teaching_object)row.append(button('为此方案准备连续计划',()=>mutate('inverse_task_prepare',{proposal_id:item.id}),'small',pending||item.execution_allowed===false));box.append(row);});host.append(box);}
    if(!s.inverse_result&&!s.inverse_approved_sha256){
      if(s.inverse_plan){const p=s.inverse_plan,box=card('开始已有数据分析');append(box,node('p','按已核对条件运行一次有限拟合，完成后显示结果。不会自动调用 AI。'),detail('本次计划与固定上限',t.numerical_plan));const permit=consent('批准这一份已核对的有限分析计划。'),go=button('运行已有数据分析',()=>mutate('inverse_run',{approve:true,plan_sha256:p.sha256}),'primary',true);permit.input.addEventListener('input',()=>go.disabled=busy||pending||!permit.input.checked||!boot.capabilities?.analysis);append(box,permit.wrap,go);host.append(box);}
      else if(s.teaching_object){const box=card('一次核对已有教学条件');append(box,node('p','以下条件来自你选择的教学任务。这里直接沿用已列明的值；需修改时打开下方条件表单。'),facts(s.inverse_settings.fixed),detail('允许估计的范围与每组尺度',{ranges:s.inverse_settings.bounds,groups:s.groups.map(g=>({conditions:g.conditions,scale:g.scale,scale_source:g.scale_source,observation:g.observation}))}));const permit=consent('确认这些教学条件、估计范围与数据尺度，准备已有数据的分析计划。'),go=button('沿用这些条件准备分析',()=>mutate('inverse_task_initial_plan',{confirm_conditions:true}),'primary',true);permit.input.addEventListener('input',()=>go.disabled=busy||pending||!permit.input.checked);append(box,permit.wrap,go);host.append(box);}
    }
    if(t.receipt?.started)host.append(append(card('连续任务进度'),list((t.receipt.steps||[]).map(v=>({acquire:'补采',review:'纳入新资料',fit:'联合拟合',receipt:'保存结果'}[v.id]||v.id)+'：'+(v.status==='COMPLETED'?'已完成':v.status))),detail('步骤执行记录',t.receipt)));
  }
  function renderInverse(host,s,pending){
    const t=s.experiment_record.task_summary;append(host,node('p',t.source_label+' · '+t.state_label,'eyebrow'),node('h1',s.title));
    const result=card();result.id='inverse-task-result';append(result,node('p','目标：'+t.goal,'section-note'),node('h2',t.headline));
    if(t.chart)result.append(plot(t.chart));append(result,node('p',t.change,'inline-notice'),list(t.warnings),node('p',t.scope,'field-note'));host.append(result);
    if(s.error)host.append(node('p',s.error,'message error'));
    if(s.status==='RUNNING'){host.append(append(card('正在执行已批准的步骤'),node('p','完成后会自动显示新版本；不自动重试，也不请求 AI。')));schedulePoll(s.id);return;}
    renderResearchAssistant(host,s,pending);renderTaskPlan(host,s,pending);
    const saveBox=card('带走结果，或继续修改');saveBox.append(node('p','可以调整研究目标、允许的补采条件，或另存版本更正物理条件。已确认条件会沿用。','field-note'));[['导出结果摘要','summary'],['导出完整任务','family-export']].forEach(([label,suffix])=>{const a=node('a',label,'button small');a.href='/api/experiments/cases/'+s.id+'/'+suffix;a.download='';saveBox.append(a);});if(s.parent_id)saveBox.append(button('查看上一版',()=>select(s.parent_id),'small'));saveBox.append(detail('当前已确认条件',t.confirmed_conditions));host.append(saveBox);
    const more=append(node('details',null,'card'),node('summary','原始资料、条件表单、完整比较与高级工具'));more.id='inverse-advanced';more.open=!s.teaching_object&&!s.inverse_result&&!s.inverse_plan;renderInverseDetails(more,s,pending);renderCalibration(more,s,pending);host.append(more);
    let edited=false;more.addEventListener('input',e=>{if(e.target.type==='checkbox'||edited)return;edited=true;const plan=host.querySelector('#continuous-task-plan');if(plan){plan.querySelectorAll('input').forEach(el=>{el.checked=false;el.disabled=true;});plan.querySelectorAll('button').forEach(el=>el.disabled=true);plan.append(node('p','下方条件已修改；请先保存并重新核对计划，旧批准已取消。','inline-notice'));}});
  }
  function observationControls(host,g,j,slit){
    const current=g.observation||{kind:'UNKNOWN'},options=[['UNKNOWN','尚未核验'],['POINT_SAMPLE','声明为点采样'],['AVERAGING_UNKNOWN','存在像素/窗口平均，核未知']];if(slit)options.push(['CALIBRATED_INTENSITY_AVERAGE','使用已校准强度平均核']);
    const kind=invSelect(host,`采集 ${j+1} 观测方式`,options,current.kind),box=append(node('details'),node('summary','校准核：物理偏移和归一权重'));
    const offsets=node('input'),weights=node('input'),reference=node('input');offsets.value=(current.kernel?.offsets_mm||[]).join(',');weights.value=(current.kernel?.weights||[]).join(',');reference.value=current.kernel?.reference||'';offsets.placeholder='物理偏移 mm，例如 -0.02,0,0.02';weights.placeholder='非负权重，例如 0.25,0.5,0.25，总和需为1';reference.placeholder='明确的校准记录或用户输入来源';[offsets,weights,reference].forEach((el,i)=>{el.setAttribute('aria-label',`采集 ${j+1} `+['核偏移（mm）','核权重','校准参考'][i]);box.append(append(node('label',['物理偏移（mm，逗号分隔）','对应积分权重（合计 1）','校准资料或来源说明'][i],'observation-kernel-field'),el));});box.append(node('p','只接受已知强度平均核，不能由低残差认定模糊或任意相干像差。'));host.append(box);const toggle=()=>box.hidden=kind.value!=='CALIBRATED_INTENSITY_AVERAGE';kind.addEventListener('change',toggle);toggle();
    return ()=>kind.value==='CALIBRATED_INTENSITY_AVERAGE'?{kind:kind.value,kernel:{offsets_mm:offsets.value.trim()?offsets.value.split(',').map(Number):[],weights:weights.value.trim()?weights.value.split(',').map(Number):[],source:current.kernel?.source||'USER_DECLARED',reference:reference.value}}:{kind:kind.value};
  }
  function renderFilmInverse(host,s,pending){
    const cfg=s.inverse_settings,r=s.inverse_result,v=s.experiment_record;
    append(host,node('p','反射率 → 厚度候选 → 补测波长 → 联合分析','eyebrow'),node('h1',s.title),badge(STATES[s.status]||s.status),node('p',v.explanation));
    if(s.parent_id)host.append(button('查看上一版',()=>select(s.parent_id),'small'));
    if(s.error)host.append(node('p',s.error,'message error'));
    const source=card('原始反射率与适用条件');s.groups.forEach((g,j)=>append(source,node('h3','采集 '+(j+1)),facts({source:g.dataset.source_name,source_kind:g.dataset.source_kind,wavelengths_nm:g.dataset.x_nm,reflectance:g.dataset.reflectance}),node('p','不把任意亮度当反射率，不把 T=1-R 当独立证据。')));source.append(detail('累计任务额度',v.ledger));host.append(source);
    if(s.status==='RUNNING'){host.append(node('p','正在计算有限厚度候选；不自动重试。'));schedulePoll(s.id);return;}
    if(!r&&!s.inverse_approved_sha256){
      const form=card('核对已知条件与有限厚度范围'),fields={};[['film_index','薄膜实折射率'],['incident_index','入射介质实折射率'],['substrate_index','基底实折射率']].forEach(([k,label])=>fields[k]=invNumber(form,label,cfg.fixed[k]));
      const lo=invNumber(form,'厚度下界（nm）',cfg.bounds.thickness_nm?.[0]),hi=invNumber(form,'厚度上界（nm，跨度最多1000）',cfg.bounds.thickness_nm?.[1]);
      const approvals=s.groups.map((g,j)=>{const scale=invNumber(form,'采集 '+(j+1)+' 反射率残差尺度',g.scale),source=invSelect(form,'采集 '+(j+1)+' 尺度来源',[['DECLARED_NUMERICAL_SCALE','数值尺度（非仪器精度）'],['KNOWN_MEASUREMENT_SD','已知测量标准差']],g.scale_source),approve=consent('核对采集 '+(j+1)+'：已校准反射率、法向入射、无损单层、以上折射率及层序 入射介质/膜/基底');approve.input.checked=g.approved;form.append(approve.wrap);return {scale,source,approve};});
      const corrections=consent('如修改已有固定事实，明确作为更正保存');form.append(corrections.wrap);
      const gather=()=>{const fixed={...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,invValue(v)])),incidence_deg:0,lossless:true,layer_order:'incident/film/substrate',calibrated_reflectance:true};return {settings:{...cfg,fixed,bounds:{thickness_nm:[invValue(lo),invValue(hi)]}},entries:approvals.map(a=>({conditions:fixed,scale:invValue(a.scale),scale_source:a.source.value,approved:a.approve.input.checked})),approve_corrections:corrections.input.checked};};
      form.append(button('保存并核对厚度计划',()=>mutate('inverse_plan',gather()),'primary',pending));host.append(form);
      if(s.inverse_plan){const saved=JSON.stringify(gather()),consentRun=consent('批准有限厚度搜索；保留多个模式与失败点，不证明唯一');const go=button('运行厚度分析',()=>mutate('inverse_run',{approve:true,plan_sha256:s.inverse_plan.sha256}),'primary',true);const update=()=>go.disabled=busy||pending||!consentRun.input.checked||saved!==JSON.stringify(gather())||!boot.capabilities?.analysis||!boot.capabilities?.tmm;form.querySelectorAll('input,select').forEach(el=>el.addEventListener('input',update));consentRun.input.addEventListener('input',update);host.append(append(card('执行确认'),detail('固定资源计划',s.inverse_plan),consentRun.wrap,go));}
    }
    if(r){const result=card('保留的厚度模式');append(result,node('p','单波长存在周期和对称分支；最佳点不能替代全部候选。'),facts(r.diagnostics),list(r.warnings),list((r.modes||[]).map(mode=>'候选厚度 '+mode.parameters.thickness_nm.toFixed(4)+' nm；拟合代价 '+mode.cost.toPrecision(4))),detail('候选厚度与代价',r.modes),detail('全部有限区间与失败',r.starts));r.data.forEach((d,i)=>{result.append(node('h3','采集 '+(i+1)));if(d.x.length===1)result.append(facts({wavelengths_nm:d.x[0],observed:d.observed[0],predicted:d.predicted[0],residual:d.residual[0]}));else result.append(plot({x:d.x,x_label:'波长（nm）',y_label:'已校准反射率',series:[{label:'实际观测',y:d.observed,points:true},{label:'代表候选预测',y:d.predicted,points:true}]}));});host.append(result);
      const panel=card('安排一次补测波长'),wl=node('input');wl.value=(s.acquisition_constraints?.wavelengths_nm||[500,550,600,650,700,750,800,850,900]).join(',');wl.disabled=!!s.acquisition_constraints?.wavelengths_nm;wl.setAttribute('aria-label','可用补测波长（nm，逗号分隔）');append(panel,node('p','填写仪器实际可用的 2–9 个波长，比较保留厚度候选的预测差异。'),wl,button('比较补测波长',()=>mutate('inverse_measurement_plan',{constraints:{wavelengths_nm:wl.value.split(',').map(x=>Number(x.trim()))}}),'',pending));
      if(s.measurement_plan){const mp=s.measurement_plan;let filmDirty=false;const filmButtons=[];wl.addEventListener('input',()=>{filmDirty=true;approve.input.checked=false;filmButtons.forEach(b=>b.disabled=true);});append(panel,node('p',mp.score_definition),list(mp.limitations));const approve=consent('批准独立冻结教学对象在选定波长补测；不是仪器实测');if(s.teaching_object)panel.append(approve.wrap);mp.plans.forEach(p=>{const c=append(node('article',null,'card'),node('h3',(p.id===mp.recommended_id?'建议 · ':'')+p.wavelengths_nm[0]+' nm'),facts({score:p.score,predicted_reflectance:p.prediction_envelope}));if(s.teaching_object){const go=button('教学补测这个波长',()=>mutate('inverse_append',{teaching:true,approve:true,proposal_id:p.id,proposal_sha256:mp.sha256}),'',true);filmButtons.push(go);approve.input.addEventListener('input',()=>go.disabled=busy||pending||filmDirty||!approve.input.checked||s.groups.length>=3);c.append(go);}panel.append(c);});}
      if(s.groups.length<3){const upload=append(node('details'),node('summary','上传实际补测的已校准反射率'));inverseUpload(upload,data=>mutate('inverse_append',{...data,proposal_id:s.measurement_plan?.recommended_id,proposal_sha256:s.measurement_plan?.sha256}));panel.append(upload);}host.append(panel);
      if(s.acquisition_expectation)host.append(append(card('补测前预期与实际结果'),detail('分开呈现',v.acquisition_comparison)));
    }
    const actions=card('保存和继续');actions.append(button('另存设置版本',()=>mutate('inverse_revise'),'small',pending));[['导出此版本','export'],['导出完整研究任务链','family-export'],['只读摘要','summary']].forEach(([label,suffix])=>{const a=node('a',label,'button small');a.href='/api/experiments/cases/'+s.id+'/'+suffix;actions.append(a);});host.append(actions);
  }
  function renderInverseDetails(host,s,pending){
    if(s.inverse_settings.model==='single_film_known_index_v1'){renderFilmInverse(host,s,pending);return;}
    const cfg=s.inverse_settings,v=s.experiment_record,r=s.inverse_result,slit=cfg.model===INV_SLIT;
    append(host,node('p','原始数据 → 候选证据 → 补采 → 联合分析','eyebrow'),node('h1',s.title),badge(STATES[s.status]||s.status),node('p',v.scope,'section-note'));
    if(s.parent_id)host.append(button('查看上一版',()=>select(s.parent_id),'small'));
    if(s.error)host.append(node('p',s.error,'message error'));
    if(s.questions?.length)host.append(list(s.questions));
    const sources=card('数据与参数角色');v.datasets.forEach((ds,j)=>append(sources,node('h3','采集 '+(j+1)),node('p',ds.source_kind==='SYNTHETIC_TEACHING'?'合成教学数据；不是仪器测量。':ds.source_name),facts({rows:ds.rows,range_mm:ds.range_mm,source:ds.source_kind}),detail('原始数据、来源与独立条件',ds)));
    sources.append(detail('共享累计额度（新版本与新 CSV 不清零）',v.ledger));host.append(sources);
    if(s.status==='RUNNING'){host.append(node('p','正在执行已批准的有限计算；保留失败点和进度，不自动重试。','inline-notice'));schedulePoll(s.id);return;}
    if(!s.inverse_approved_sha256&&!r){
      const panel=card('核对已知条件与允许估计的量'),fields={},roles={},bounds={},values={},entryInputs=[];
      const physical=slit?['wavelength_nm','focal_length_mm','relative_phase_rad','measurement_plane']:['wavelength_nm','m2','propagation'];
      const physicalInput=(container,k,value,label)=>k==='measurement_plane'?invSelect(container,label,[['','请选择'],['FOURIER_FOCAL_PLANE','理想透镜傅里叶焦平面']],value):k==='propagation'?invSelect(container,label,[['','请选择'],['FREE_SPACE','自由传播，无途中透镜/截光/像差']],value):invNumber(container,label,value);
      physical.forEach(k=>fields[k]=physicalInput(panel,k,cfg.fixed[k],INV_LABELS[k]));
      if(slit)panel.append(button('为缺少的中心、幅度、背景提供数值建议',()=>mutate('inverse_recipe'),'small',pending));
      const params=slit?['slit_width_um','slit_separation_um','center_shift_mm','amplitude','background']:['waist_radius_um','waist_z_mm'];
      params.forEach(k=>{const row=append(node('div',null,'card'),node('h3',INV_LABELS[k]));roles[k]=invSelect(row,INV_LABELS[k]+'角色',[['bounds','待估：使用明确范围'],['fixed','已知：固定值']],Object.hasOwn(cfg.fixed,k)?'fixed':'bounds');values[k]=invNumber(row,INV_LABELS[k]+'已知值',cfg.fixed[k]);bounds[k]=[invNumber(row,INV_LABELS[k]+'下界',cfg.bounds[k]?.[0]),invNumber(row,INV_LABELS[k]+'上界',cfg.bounds[k]?.[1])];const toggle=()=>{values[k].parentElement.hidden=roles[k].value!=='fixed';bounds[k].forEach(el=>el.parentElement.hidden=roles[k].value!=='bounds');};roles[k].addEventListener('change',toggle);toggle();panel.append(row);});
      const advanced=append(node('details'),node('summary','损失、权重、观测方式与坐标配准'));
      const weighting=invSelect(advanced,'数据组与点数的统计含义',[['EQUAL_DATASET_TRAINING_COUNT','默认：各组平均误差等权'],['equal_dataset_mse','各组平均误差等权'],['declared_independent_noise','使用已确认的逐点噪声']],cfg.weighting);
      const futureSigma=invNumber(advanced,'未来补采声明的噪声标准差',cfg.future_noise?.sigma),futureRef=node('input');futureRef.placeholder='未来噪声与独立性的依据（不填则不假定）';futureRef.value=cfg.future_noise?.reference||'';futureRef.setAttribute('aria-label','未来噪声依据');advanced.append(futureRef);
      const futureIndependent=consent('我明确声明未来补采采用上方噪声标准差，并假设各点噪声独立。');futureIndependent.input.checked=cfg.future_noise?.independent===true;advanced.append(futureIndependent.wrap);
      const loss=invSelect(advanced,'损失',[['linear','普通平方残差'],['soft_l1','soft_l1（保留异常点）']],cfg.loss),fscale=invNumber(advanced,'损失尺度 f_scale',cfg.f_scale);
      const registration=invSelect(advanced,'坐标配准',[['SHARED_REGISTERED','各次采集已明确配准，共享中心'],['INDEPENDENT','独立采集，分别估计中心']],cfg.registration);
      const weightingNote=node('p','','field-note');advanced.append(weightingNote);const explainWeighting=()=>{weightingNote.textContent=weighting.value==='declared_independent_noise'?'仅在明确声明噪声标准差与独立性后，残差逐点除以标准差；不再除以点数平方根。soft_l1 尺度使用标准化噪声单位，局部预测仍不是置信区间。':'各组残差除以各自声明尺度和训练点数平方根，采用等数据组权重。数值尺度不是测量精度。高斯 CSV 如含已知标准差，逐点使用该标准差。';};weighting.addEventListener('change',explainWeighting);explainWeighting();
      s.groups.forEach((g,j)=>{const entry=append(node('fieldset'),node('legend','采集 '+(j+1)+'：独立核对'));const f={};physical.forEach(k=>f[k]=physicalInput(entry,k,g.conditions[k]??cfg.fixed[k],`采集 ${j+1} `+INV_LABELS[k]));const scale=invNumber(entry,`采集 ${j+1} 残差尺度`,g.scale);const source=invSelect(entry,`采集 ${j+1} 尺度来源`,[['DECLARED_NUMERICAL_SCALE','声明的数值尺度'],['KNOWN_MEASUREMENT_SD','已知测量标准差']],g.scale_source);const observation=observationControls(entry,g,j,slit),independent=consent('我明确声明这些点具有所给标准差，噪声相互独立；这不是复制同一份数据');independent.input.checked=g.noise?.independent===true;const reference=node('input'),acquisition=node('input');reference.placeholder='噪声标准差与独立性的依据';reference.value=g.noise?.reference||'';reference.setAttribute('aria-label',`采集 ${j+1} 噪声依据`);acquisition.value=g.noise?.acquisition_id||s.inverse_root+':'+g.raw_file;acquisition.setAttribute('aria-label',`采集 ${j+1} 稳定观测编号`);append(entry,independent.wrap,reference,acquisition);const approved=consent('我核对这份采集的物理条件、权重及坐标关系，同意纳入拟合');approved.input.checked=g.approved===true;entry.append(approved.wrap);entryInputs.push({f,scale,source,approved,observation,independent,reference,acquisition,g});advanced.append(entry);});panel.append(advanced);advanced.open=true;
      const corrections=consent('如修改已有固定事实，我明确确认这是更正；历史版本仍保留。');panel.append(corrections.wrap);
      const readFixed=inputs=>Object.fromEntries(Object.entries(inputs).map(([k,el])=>[k,['measurement_plane','propagation'].includes(k)?el.value:invValue(el)]));
      const gather=()=>{const fixed=readFixed(fields),b={};params.forEach(k=>{if(roles[k].value==='fixed')fixed[k]=invValue(values[k]);else b[k]=bounds[k].map(invValue);});const settings={...cfg,fixed,bounds:b,loss:loss.value,f_scale:invValue(fscale),registration:registration.value,weighting:weighting.value};if(weighting.value!=='EQUAL_DATASET_TRAINING_COUNT')settings.f_scale_units=weighting.value==='declared_independent_noise'?'STANDARDIZED_NOISE_SD':'SCALE_NORMALIZED_GROUP_RMS';else delete settings.f_scale_units;if(weighting.value==='declared_independent_noise'&&futureRef.value.trim())settings.future_noise={sigma:invValue(futureSigma),independent:futureIndependent.input.checked,source:'USER_DECLARED',reference:futureRef.value};else delete settings.future_noise;return {settings,entries:entryInputs.map(e=>{const entry={conditions:readFixed(e.f),scale:invValue(e.scale),scale_source:e.source.value,approved:e.approved.input.checked,observation:e.observation()};if(weighting.value==='declared_independent_noise')entry.noise={sigma:e.g.dataset.sd_um||invValue(e.scale),independent:e.independent.input.checked,source:'USER_DECLARED',reference:e.reference.value,acquisition_id:e.acquisition.value};return entry;}),approve_corrections:corrections.input.checked};};
      const planNote=node('p','','field-note'),savePlan=button('保存并核对反演计划',()=>mutate('inverse_plan',gather()),'primary',pending);append(panel,planNote,savePlan);
      const checkPlanInputs=()=>{let reason='';for(const e of entryInputs){const observation=e.observation();if(observation.kind==='CALIBRATED_INTENSITY_AVERAGE'){const k=observation.kernel;if(!k.reference.trim()||!k.offsets_mm.length||k.offsets_mm.length>65||k.offsets_mm.length!==k.weights.length||k.offsets_mm.some((x,i)=>!Number.isFinite(x)||i>0&&x<=k.offsets_mm[i-1])||k.weights.some(x=>!Number.isFinite(x)||x<0)||Math.abs(k.weights.reduce((a,b)=>a+b,0)-1)>1e-12)reason='请补齐已校准核的递增物理偏移、非负归一权重和来源。';}if(weighting.value==='declared_independent_noise'&&(!e.independent.input.checked||e.source.value!=='KNOWN_MEASUREMENT_SD'||!e.reference.value.trim()||!e.acquisition.value.trim()))reason='独立噪声模式需要逐份声明已知标准差、噪声依据、稳定观测编号，并明确勾选独立性。';}if(weighting.value==='declared_independent_noise'&&futureRef.value.trim()&&(!futureIndependent.input.checked||!(invValue(futureSigma)>0)))reason='填写未来噪声依据后，还需声明正的标准差并勾选未来各点独立性。';planNote.textContent=reason;savePlan.disabled=busy||pending||!!reason;};panel.querySelectorAll('input,select').forEach(el=>{el.addEventListener('input',checkPlanInputs);el.addEventListener('change',checkPlanInputs);});checkPlanInputs();
      const saved=JSON.stringify(gather());host.append(panel);
      if(s.inverse_plan){const approve=consent('我核对本次参数、各组数据与资源上限，批准计算。');const go=button('运行有限反演',()=>mutate('inverse_run',{approve:true,plan_sha256:s.inverse_plan.sha256}),'primary',true);const check=()=>go.disabled=busy||pending||!boot.capabilities?.analysis||!boot.capabilities?.local_workers||!approve.input.checked||saved!==JSON.stringify(gather());panel.querySelectorAll('input,select').forEach(el=>el.addEventListener('input',check));approve.input.addEventListener('input',check);append(host,append(card('执行确认'),detail('本次计划',s.inverse_plan),approve.wrap,go));}
    }else if(s.status==='PLANNED'&&s.inverse_plan?.operation==='profile'){
      const p=card('参数证据曲线计划'),approve=consent('批准这个有限网格与每点两次局部搜索；它不产生严格置信区间。');const go=button('计算参数证据曲线',()=>mutate('inverse_run',{approve:true,plan_sha256:s.inverse_plan.sha256}),'primary',true);approve.input.addEventListener('input',()=>go.disabled=busy||pending||!approve.input.checked||!boot.capabilities?.analysis||!boot.capabilities?.local_workers);append(p,facts(s.inverse_plan.profile),facts(s.inverse_plan.budget),approve.wrap,go);host.append(p);
    }
    if(r){const result=card(v.can_adopt?'拟合结果与检查':'当前仍需核对或补采');result.id='inverse-result';append(result,node('p',v.explanation,'inline-notice'),facts(r.estimated_parameters||{}));(r.data||[]).forEach((d,i)=>{append(result,node('h3','采集 '+(i+1)+'：原始坐标预测与残差'),plot({x:d.x,x_label:slit?'位置（mm）':'纵向 z（mm）',y_label:slit?'相对强度':'1/e² 半径（μm）',series:[{label:'原始数据',y:d.observed,points:true},{label:'拟合预测',y:d.predicted}]}),plot({x:d.x,x_label:'坐标（mm）',y_label:'原始残差',series:[{label:'残差',y:d.residual,points:true}]}));});append(result,detail('全部起点与失败',r.starts),detail('数值检查与计算用量',{diagnostics:r.diagnostics,resources:r.resources}));host.append(result);
      const profile=card('查看参数证据曲线');append(profile,node('p','在有限范围固定一个参数，再拟合其他量。分离片段不会连成一个区间；失败点不是排除证据。只有一个格点，也不等于零误差。'));
      Object.entries(s.inverse_profiles||{}).forEach(([k,p])=>{const valid=p.rows.filter(row=>row.success);append(profile,node('h3',INV_LABELS[k]),node('p',p.note),facts({components:p.components,grid_spacing:p.grid_spacing,warnings:p.warnings}),plot({x:valid.map(r=>r.value),x_label:INV_LABELS[k],y_label:'相对局部代价',series:[{label:'有限网格代价（只显示已完成点）',y:valid.map(r=>r.relative_cost),points:true}]}),detail('所有格点与失败证据',p.rows));});
      const grid=invNumber(profile,'预先指定粗网格点数（3–21）',21);(slit?['slit_width_um','slit_separation_um']:['waist_radius_um','waist_z_mm']).filter(k=>cfg.bounds[k]).forEach(k=>profile.append(button('规划 '+INV_LABELS[k]+' 证据曲线',()=>mutate('inverse_profile_plan',{parameter:k,grid_points:invValue(grid)}),'small',pending||s.status==='PLANNED')));host.append(profile);
      {
        const plans=card('按研究目标安排下一次观测'),draft=s.acquisition_constraints||{},pref=s.decision_preferences||{};const policy=invSelect(plans,'如何选择下一步',[['BASELINE_FIRST','基础方案优先'],['CONDITIONAL_EXPLORATION','有足够依据时允许条件探索']],pref.mode||'BASELINE_FIRST');const baselinePositions=node('input');baselinePositions.placeholder='可选：已有方案的全部位置（mm，逗号分隔，点数须匹配）';baselinePositions.setAttribute('aria-label','已有基础方案的位置');plans.append(baselinePositions);
        plans.id='research-plans';const goal=invSelect(plans,'这次优先解决什么',slit?[['balanced','平衡缝宽与缝距'],['width','优先缝宽'],['separation','优先缝距'],['prediction','指定区间的预测']]:[['balanced','平衡半径与位置'],['waist_radius','优先束腰半径'],['waist_position','优先束腰位置'],['prediction','指定区间的预测']],s.research_goal?.target||s.measurement_plan?.research_goal?.target||'balanced');
        const protection=invSelect(plans,'同时不希望牺牲哪一项',slit?[['','暂不指定'],['slit_width_um','缝宽'],['slit_separation_um','缝距']]:[['','暂不指定'],['waist_radius_um','束腰半径'],['waist_z_mm','束腰位置']],Object.keys(pref.protected_scale_increase||{})[0]||'');
        const protectedIncrease=invNumber(plans,'受保护项允许的预测尺度增加量（所选参数单位）',Object.values(pref.protected_scale_increase||{})[0]??0),travel=invNumber(plans,'最大移动行程（mm，可留空）',pref.max_travel_mm??'');
        const tradeoff=append(node('details'),node('summary','目标尺度与成本设置'));plans.append(tradeoff);
        const scaleKeys=slit?['slit_width_um','slit_separation_um']:['waist_radius_um','waist_z_mm'],scaleDefaults=slit?[.5,.1]:[5,2],scales={};scaleKeys.forEach((k,i)=>scales[k]=invNumber(tradeoff,(INV_LABELS[k]||k)+'目标尺度',pref.target_scales?.[k]??scaleDefaults[i]));
        scales.prediction=invNumber(tradeoff,'预测目标尺度（选择区间预测时填写）',pref.target_scales?.prediction??'');const gain=invNumber(tradeoff,'最小归一化净收益门槛',pref.minimum_proxy_gain??.05),travelCost=invNumber(tradeoff,'每增加 1 mm 移动的成本系数',pref.extra_travel_penalty_per_mm??0),segmentCost=invNumber(tradeoff,'每增加一个分段的成本系数',pref.extra_segment_penalty??0);
        tradeoff.append(node('p','初始数值是公开策略默认值。保护的是有限假设下的预测尺度，不保证真实误差不增加；没有独立噪声依据时保留基础方案。','field-note'));
        const readPreferences=()=>({version:'finite-tradeoff-v1',source:'USER_FORM',mode:policy.value,target_scales:Object.fromEntries(Object.entries(scales).filter(([k,v])=>v.value.trim()!=='').map(([k,v])=>[k,invValue(v)])),protected_scale_increase:protection.value?{[protection.value]:invValue(protectedIncrease)}:{},max_travel_mm:travel.value.trim()===''?null:invValue(travel),max_points:invValue(points),minimum_proxy_gain:invValue(gain),extra_travel_penalty_per_mm:invValue(travelCost),extra_segment_penalty:invValue(segmentCost)});
        plans.append(node('p',s.research_goal?.source==='USER_TEXT'?'目标来自本轮用户原话；可在下方调整。':'未明确选择时采用公开的平衡目标；预测尺度不是置信区间。','field-note'));
        const predictionLeft=invNumber(plans,'预测目标区间左端（mm）',slit?-2:-60),predictionRight=invNumber(plans,'预测目标区间右端（mm）',slit?2:140);
        const togglePrediction=()=>{predictionLeft.parentElement.hidden=predictionRight.parentElement.hidden=goal.value!=='prediction';};goal.addEventListener('change',togglePrediction);togglePrediction();
        const cap=invNumber(plans,'允许的最大绝对位置（mm）',draft.max_abs_x_mm??(slit?5:200)),points=invNumber(plans,slit?'每个方案新增点数（20–201）':'新增纵向位置数（3–201）',draft.points??(slit?81:5)),step=invNumber(plans,'最小步距（mm）',draft.min_step_mm??(slit?.001:1)),uncertainty=invNumber(plans,'独立中心配准不确定性（mm）',draft.registration_uncertainty_mm??(cfg.registration==='INDEPENDENT'?.1:0));
        const extension=consent('允许扩展原坐标范围'),stable=consent('这一次扫描内条件稳定，分段采样仍使用同一曝光与配准');extension.input.checked=!!draft.allow_extension;stable.input.checked=!!draft.stable_exposure_background;let acquisitionDirty=false;const acquisitionButtons=[];let sampleApproval=null;const dirtyNote=node('p','','inline-notice');plans.append(dirtyNote);[policy,protection,protectedIncrease,travel,gain,travelCost,segmentCost,...Object.values(scales),baselinePositions,goal,predictionLeft,predictionRight,cap,points,step,uncertainty,extension.input,stable.input].forEach(el=>el.addEventListener('input',()=>{acquisitionDirty=true;if(sampleApproval)sampleApproval.checked=false;acquisitionButtons.forEach(b=>b.disabled=true);dirtyNote.textContent='补采条件已修改，请重新比较后再批准。';}));let goalChanged=false;goal.addEventListener('change',()=>goalChanged=true);
        append(plans,extension.wrap,stable.wrap,button('比较有限补采方案',()=>mutate('inverse_measurement_plan',{decision_preferences:readPreferences(),baseline:baselinePositions.value.trim()?{source:'USER_SPECIFIED',label:'用户已有方案',positions_mm:baselinePositions.value.split(',').map(Number)}:null,research_goal:{target:goal.value,source:goalChanged?'USER_FORM':s.research_goal?.source||'DEFAULT_BALANCED',tolerances:s.research_goal?.tolerances||{},prediction_region_mm:goal.value==='prediction'?[invValue(predictionLeft),invValue(predictionRight)]:null},constraints:{max_abs_x_mm:invValue(cap),points:invValue(points),min_step_mm:invValue(step),registration_uncertainty_mm:invValue(uncertainty),allow_extension:extension.input.checked,stable_exposure_background:stable.input.checked}}),'',pending));
        if(s.measurement_plan){const mp=s.measurement_plan;if(mp.selection_reason)append(plans,node('p',mp.selection_reason,'inline-notice'),detail('基础方案的来源与可执行性',mp.baseline_catalog),detail('公开假设下的稳定性（不是新实测）',mp.stability),detail('归一化尺度与选择规则',{normalization:mp.normalization,policy:mp.decision_policy}));append(plans,node('p',mp.score_definition),node('p','建议性质：'+({BASELINE_CONSERVATIVE:'保守采用基础方案',FIXED_BASELINE_NOT_ADAPTIVE:'固定基线，未作自适应排名',LOCAL_ONLY:'仅局部灵敏度建议',FINITE_CANDIDATE_GOAL_HEURISTIC:'有限候选的目标建议'}[mp.recommendation_kind]||mp.recommendation_kind)+'；目标：'+({width:'优先缝宽',separation:'优先缝距',balanced:'平衡',prediction:'指定区间预测',waist_radius:'优先束腰半径',waist_position:'优先束腰位置'}[mp.research_goal?.target]||'未声明')),list(mp.limitations));
          if(mp.candidate_evidence?.refinement_eligible&&!v.ledger?.refinements_reserved){const key=Object.keys(s.inverse_profiles||{})[0];if(key)plans.append(button('规划一次有限局部加密（沿用累计额度）',()=>mutate('inverse_profile_plan',{parameter:key,refinement:true}),'small',pending));}
          const consentSample=consent('批准从独立冻结的教学对象补采；这不是操作真实仪器，也不是真人验证。');sampleApproval=consentSample.input;if(s.teaching_object)plans.append(consentSample.wrap);
          mp.plans.forEach(p=>{const names={baseline:p.label||'基础方案',repeat:'原范围重复',medium:'适度扩展',wide:'更宽范围',mixed60:'中央 60%＋两侧',mixed40:'中央 40%＋两侧',mixed80:'中央 80%＋两侧'};const c=append(node('article',null,'card'),node('h3',(p.id===mp.recommended_id?'建议 · ':'')+(names[p.id]||p.id)),facts({range_mm:p.range_mm,points:p.points,local_scales:p.local_scales,prediction_scale:p.prediction_scale,dominated:p.dominated}),node('p',p.selection_reason||''),node('p',p.cost_note||''),list(p.risks||[]),detail('采样风险说明',p.sampling_risk||{}),detail('具体位置、成本与候选分歧',{positions_mm:p.prediction_x_mm,cost:p.cost,disagreement:p.score}));
            if(mp.tradeoff_decision)c.append(detail('保护项、净收益与各假设尺度',{comparison:mp.tradeoff_decision.audit?.find(a=>a.id===p.id),scales:p.tradeoff_scales?.scales_by_scenario}));if(s.research_origin?.proposal_id===p.id&&s.research_origin?.plan_sha256===mp.sha256)c.append(node('p','这是本次 AI 建议并已核对的具体方案。','inline-notice'));
            if(s.teaching_object){const go=button('教学补采此方案',()=>mutate('inverse_append',{teaching:true,approve:true,proposal_id:p.id,proposal_sha256:mp.sha256}),'',true);acquisitionButtons.push(go);consentSample.input.addEventListener('input',()=>go.disabled=busy||pending||acquisitionDirty||!consentSample.input.checked||s.groups.length>=3||p.execution_allowed===false);c.append(go);}plans.append(c);});
        }
        if(s.groups.length<3){const upload=append(node('details'),node('summary','加入新采集的 CSV（每次条件另行核对）'));inverseUpload(upload,data=>mutate('inverse_append',{...data,proposal_id:acquisitionDirty?null:s.measurement_plan?.recommended_id,proposal_sha256:acquisitionDirty?null:s.measurement_plan?.sha256}));plans.append(upload);}host.append(plans);
        if(s.acquisition_expectation)host.append(append(card('补采前的预期与补采后的结果'),node('p','分别保留原建议与新估计。实测没有真值时，参数变化不能当作误差降低。'),detail('预期与实际',v.acquisition_comparison)));
      }
      if(v.can_adopt){const forward=card('采用模型估计，接回正向比较');if(s.forward_children?.length)forward.append(button('打开已有正向计划',()=>select(s.forward_children[0]),'primary'));else{const fields={};(slit?[['slit_height_um','缝高（μm，需另行确认）',100],['grid_size','FFT 网格',256],['window_mm','孔径窗口（mm）',.6]]:[['lens_z_mm','透镜全局位置（mm）',180],['screen_distance_mm','屏幕相对透镜距离（mm）',100],['z_max_mm','绘图传播范围（mm）',200],['target_radius_um','目标半径上限（μm）',300],['f1','候选焦距一（mm）',75],['f2','候选焦距二（mm）',100],['f3','候选焦距三（mm）',150]]).forEach(([k,label,value])=>fields[k]=invNumber(forward,label,value));const accept=consent('确认采用模型估计，并核对以上补充条件和目标；显示值是待确认建议。');const go=button('创建正向比较计划',()=>{const geometry=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,invValue(v)]));if(!slit){geometry.focal_lengths_mm=[geometry.f1,geometry.f2,geometry.f3];delete geometry.f1;delete geometry.f2;delete geometry.f3;}mutate('inverse_forward',{approve_estimate:true,geometry});},'primary',true);accept.input.addEventListener('input',()=>go.disabled=busy||pending||!accept.input.checked);append(forward,accept.wrap,go);}host.append(forward);}
    }
    if(v.comparison_origin||s.comparison_origin)host.append(append(card('补采前的候选证据'),node('p','两版数据量不同；候选显示范围可比较，但局部代价不是独立验证分数。'),detail('旧版记录与离散候选',v.comparison_origin||s.comparison_origin)));
    const actions=card('保存和继续');actions.append(button('另存设置版本',()=>mutate('inverse_revise'),'small',pending));[['导出此版本','export'],['导出完整研究任务链','family-export'],['只读摘要','summary']].forEach(([label,suffix])=>{const a=node('a',label,'button small');a.href='/api/experiments/cases/'+s.id+'/'+suffix;actions.append(a);});if(s.inverse_progress)actions.append(detail('中断前进度',s.inverse_progress));host.append(actions);
  }
  async function startTask(body,feedback){
    if(busy)return;setBusy(true);message('error','');
    try{const out=await api('/task-start',body);setBusy(false);if(out.status==='CREATED'){current=out.case;cacheCase(current);updateLocation(current.id);render();}else feedback(out);}
    catch(e){message('error',e.message);}finally{setBusy(false);}
  }
  function taskDataForm(host,text,model){
    const box=card('导入已有观测'),choice=invSelect(box,'数据对应的任务',[[INV_GAUSS,'高斯：估计束腰'],['single_film_known_index_v1','薄膜：区分厚度候选'],[INV_SLIT,'双缝：估计缝宽与缝距']],model||INV_GAUSS);
    append(box,node('p','高斯：z_mm,radius_1e2_um；薄膜：wavelength_nm,reflectance_calibrated；双缝：position_mm,intensity_relative。导入后核对已知物理条件，未知值不会自动填成教学参数。','field-note'));
    inverseUpload(box,({approve,...data})=>startTask({text,mode:'inverse',model:choice.value,...data},()=>{}));host.replaceChildren(box);
  }
  const SUCCESS_EXAMPLE = "薄膜任务，目标850 nm反射率不低于75%。设计波长也是850 nm，高低折射率材料分别为2.2和1.46。四分之一波光学厚度，高低层交替从高层开始，总层数目录2、4、6、8。实际计算波长700、850、950 nm，正入射、两侧空气、无损无色散。只做快速计算，不做Meep。先出计划，等我确认才算。";
  function renderHome() {
    const host=$('content');append(host,node('p','PHOTONGUARD · AI 光学实验工作台','eyebrow'),node('h1','你想完成什么实验任务？'),node('p','从一个目标、一份观测，或一个教学实验开始。AI 帮你整理条件、选择下一步；你核对计划后，工具实际执行并保留结果。','lead'));
    const box=card(),label=node('label','你想研究什么？','input-label'),q=node('textarea');label.htmlFor='new-material';q.id='new-material';q.maxLength=6000;q.rows=3;q.placeholder='例如：我有高斯光束的扫描数据，只有5次补测机会，希望先弄清束腰位置。';q.value=load('new-draft')?.text||'';
    const branch=node('div'),hint=node('p','先整理任务，不会自动调用 AI 或启动计算。','field-note');
    const feedback=out=>{branch.replaceChildren();if(out.status==='NEEDS_INTENT')append(branch,node('p',out.question,'inline-notice'),button('比较已知参数的方案',()=>startTask({text:q.value,mode:'forward'},feedback),'small'),button('从已有观测反推参数',()=>startTask({text:q.value,mode:'inverse'},feedback),'small'));else if(out.status==='NEEDS_DATA')taskDataForm(branch,q.value,out.model);};
    const begin=button('开始这个任务',()=>startTask({text:q.value},feedback),'primary',!q.value.trim());
    q.addEventListener('input',()=>{const bad=credentialLike(q.value);begin.disabled=busy||!q.value.trim()||bad;if(bad){clear('new-draft');hint.textContent='检测到疑似密钥，请移除后再保存。';}else{save('new-draft',{text:q.value});hint.textContent='先整理任务，不会自动调用 AI 或启动计算。';}});
    const example=card('从一个达标设计开始 · 850 nm 薄膜');
    append(example,node('p','自然语言输入 → AI整理条件 → 四候选比较 → 找到达标方案。','lead'),node('p','比较2、4、6、8层，目标反射率至少75%。已有保存案例中，8层达到86.02%；新任务按实际计算结果判断。','field-note'),button('填入这组示例条件',()=>{q.value=SUCCESS_EXAMPLE;q.dispatchEvent(new Event('input'));q.focus();},'small'));

    append(box,label,q,hint,append(node('div',null,'actions'),begin,button('导入数据',()=>taskDataForm(branch,q.value),''),button('没有数据，体验教学任务',()=>{const teaching=card('选择一个教学任务');append(teaching,node('p','采用公开教学条件和独立冻结的模拟对象；不是仪器观测。条件在分析前集中核对。'),button('高斯 · 安排5次补测',()=>startTask({text:q.value.trim()||'高斯教学：已有数据，只有5次测量机会，束腰位置优先',model:INV_GAUSS,teaching:true},feedback),'small'),button('薄膜 · 选择补测波长',()=>startTask({text:q.value.trim()||'薄膜教学：只有633、660、780 nm三个可用波长，区分厚度候选',model:'single_film_known_index_v1',teaching:true},feedback),'small'),button('双缝 · 修改观测约束',()=>startTask({text:q.value.trim()||'双缝教学：缝宽优先，保护缝距，补采71个点，最大行程4 mm',model:INV_SLIT,teaching:true},feedback),'small'));branch.replaceChildren(teaching);},'')),branch);host.append(box,example);
    append(host,node('p',boot.ai?.live_enabled?'AI 已连接。发送资料前，请核对本次内容。':'可以先导入数据并完成本地分析；需要 AI 建议时，连接自己的 API Key 即可。','inline-notice'));
    const library=append(node('details',null,'card'),node('summary','浏览案例库与更多分析工具'));renderLibrary(library);renderMissions(library);renderInverseImport(library);renderObservationImport(library);
    const legacy=card('正向仿真示例');boot.templates.forEach(t=>legacy.append(button(t.title,()=>create({kind:'teaching',template_id:t.id}),'small')));library.append(legacy);host.append(library);
    const capabilities=append(node('details',null,'card'),node('summary','运行环境与使用说明'));capabilities.append(list(['基础计算：'+(boot.capabilities?.local_workers?'已启用':'未启用'),'反向分析：'+(boot.capabilities?.analysis?'SciPy 已就绪':'需安装 SciPy；仍可查看记录'),'安装与使用说明见 README；批量复用示例见 examples。']));host.append(capabilities);
  }
  function steps(status) { const active = ['DRAFT','NEEDS_INFORMATION'].includes(status) ? 0 : status === 'PLANNED' ? 1 : 2; const ol = node('ol',null,'steps'); ['整理资料','核对计划','计算与比较'].forEach((text,i) => append(ol,append(node('li',null,i === active ? 'current' : i < active ? 'done' : ''),node('span',String(i+1),'step-number'),node('span',text)))); return ol; }
  function pendingPanel(s) {
    const pending = load('pending:' + s.id); if (!pending) return null;
    if (s.revision > pending.revision) { clear('pending:' + s.id); return null; }
    const panel = node('div',null,'inline-notice warning');
    append(panel,node('p','上一次操作的完成状态尚未确认。为避免重复收费或计算，本页暂不重发。请先读取最新记录。'),button('刷新记录',() => select(s.id),'small'));
    return panel;
  }
  function renderCase() {
    const s = current, host = $('content'), pending = pendingPanel(s);
    if(s.kind==='inverse'){renderInverse(host,s,!!pending);if(pending)host.prepend(pending);return;}
    if(s.kind==='observation'){renderObservation(host,s,!!pending);if(pending)host.prepend(pending);return;}
    if(s.estimate_origin)append(host,append(card('来自数据的模型估计'),node('p','此任务继承数据分析的模型条件，缝距估计不等于实测值。原始数据、残差和估计仍保留在来源版本。'),button('查看数据与拟合来源',()=>select(s.estimate_origin.record_id),'small'),detail('来源与坐标说明',s.estimate_origin)));
    if(s.budget_preview){const b=s.budget_preview,box=card('计算前的共享预算');append(box,node('p','本计划 '+b.requested_candidates+' 个候选，需 '+b.required_fft_calls+' 次 FFT；共享预算最多容纳 '+b.allowed_candidates+' 个候选，剩余 '+b.remaining_fft_calls+' 次 FFT。预计输出 '+(b.estimated_output_bytes/1048576).toFixed(1)+' MiB，剩余 '+(b.remaining_output_bytes/1048576).toFixed(1)+' MiB。'),node('p',b.note,'field-note'));
      if(s.candidate_choice){const c=s.candidate_choice;box.append(node('p','原计划尚未执行。请明确选择一个原候选，生成缩减计划后还需单独批准计算。'));c.values.forEach(value=>box.append(button('选择 '+value+' μm 并重新核对',()=>mutate('choose_observation_candidate',{slit_separation_um:value,choice_sha256:c.sha256,approve_selection:true}),'small',!!pending)));}host.append(box);}
    if(s.status==='COMPLETED'&&s.result&&s.experiment_record?.brief){
      append(host,node('p','已保存的实际运行 · '+DOMAINS[s.domain],'eyebrow'),append(node('div',null,'card-header'),node('h1',s.title),badge('结果已保存','ok')),pending);
      renderResultBrief(host,s,!!pending);renderResult(host,s,!!pending,true);renderContinue(host,s,!!pending);
      const history=append(node('details',null,'card'),node('summary','参数来源、版本经过与运行依据'));renderExperimentRecord(history,s,!!pending);history.append(sourceReview(s));if(s.plan)renderPlan(history,s,!!pending);host.append(history);
      const advanced=append(node('details',null,'card'),node('summary','高级修改与已有表单'));advanced.id='advanced-actions';renderRevision(advanced,s,!!pending);renderCaseExploration(advanced,s,!!pending);host.append(advanced);return;
    }
    append(host,node('p',DOMAINS[s.domain] || '待整理的光学实验','eyebrow'),append(node('div',null,'card-header'),node('h1',s.title || '整理实验资料'),badge(STATES[s.status] || s.status,s.status === 'COMPLETED' ? 'ok' : s.status === 'FAILED' ? 'fail' : '')),
      node('p',(s.spec?.context_kind === 'teaching' || s.kind === 'teaching' ? '教学练习 · 参数来自所选示例。' : '已有资料 · 未知值保留为未知。') + ' 记录 ' + s.id + ' · 版本 ' + s.revision,'section-note'),steps(s.status),pending);
    if (s.status !== 'RUNNING' && !pending) host.append(button('读取最新记录',() => select(s.id),'small subtle'));
    if (s.parent_id || s.spec?.parent_task_id) append(host,append(node('div',null,'inline-notice'),node('span','这份计划来自之前的实验，旧记录仍保留。'),button('查看来源实验',() => select(s.parent_id || s.spec.parent_task_id),'small subtle')));
    if (s.status === 'RUNNING') {const running=card('正在执行已批准的计划');append(running,node('p','尚无本轮完成结果。页面会按实际状态更新，不会自动重发任务。'),button('读取最新进度',()=>select(s.id),'small'));host.append(running);schedulePoll(s.id);}
    if(s.status==='FAILED')append(host,card('本轮未完成；此前有效结果仍保留'));
    if(s.fact_state?.questions?.length)append(host,append(card('先确认这些条件'),list(s.fact_state.questions.map(q=>humanizeQuestion(q.text)))));
    renderSessionFacts(host,s,!!pending);
    renderExperimentRecord(host,s,!!pending);
    if (s.error) host.append(node('div',typeof s.error === 'string' ? s.error : display(s.error),'message error'));
    if (['DRAFT','NEEDS_INFORMATION','NEEDS_REVIEW','PLANNED'].includes(s.status)) renderEditor(host,s,!!pending);
    else host.append(sourceReview(s));
    if (s.questions?.length) renderQuestions(host,s,!!pending);
    if (s.plan) renderPlan(host,s,!!pending);
    if (s.status === 'RUNNING') { const run = card(); append(run,append(node('h2'),node('span',null,'running-dot'),node('span','已按批准的计划开始计算')),node('p','页面会自动更新。每个结果都保留实际候选、使用的引擎和核对记录；未达到目标也会如实保存。','section-note'),button('读取最新进度',() => select(s.id),'small')); host.append(run); schedulePoll(s.id); }
    if(s.library_origin){const provenance=card('案例来源与候选依据');append(provenance,node('p',s.library_origin.case_id+' · 版本 '+s.library_origin.case_version+'；'+(s.result?'本版本已有实际计算记录。':'当前仅生成候选，尚未计算。'),'section-note'),detail('查看解析提议与来源（不是场计算结果）',s.library_origin.proposal));host.append(provenance);}
    if (s.result) {renderResult(host,s,!!pending);renderCaseExploration(host,s,!!pending);}
    if (['COMPLETED','FAILED'].includes(s.status)) renderRevision(host,s,!!pending);
  }
  function renderSessionFacts(host,s,pending) {
    if(s.session_issue)host.append(append(card('本轮需要核对'),node('p',s.session_issue.text),detail('问题类别',s.session_issue)));
    const f=s.fact_state;if(!f)return;
    const box=card('本轮资料与下一步');box.id='session-facts';
    if(f.notice)box.append(node('p',f.notice,'inline-notice'));
    const latest=f.events.filter(e=>e.changes?.length).at(-1),changed=new Set((latest?.changes||[]).map(c=>c.field));
    const explicitWaves=f.facts['parameters.wavelengths_um']?.status==='resolved';
    const rows=Object.entries(f.facts).filter(([k,v])=>v.status==='resolved'&&!(explicitWaves&&v.source_kind==='numeric_default'&&['parameters.scan_min_um','parameters.scan_max_um','parameters.scan_points'].includes(k)));
    const label=([k,v])=>humanizeQuestion(k.replace(/^parameters\./,'').replace(/^goal\./,'目标 ').replace(/^recipe\./,'候选 '))+'：'+(typeof v.value==='boolean'?(v.value?'是':'否'):display(v.value))+(v.locked?'（来源条件锁定）':'');
    const conditions=append(node('details'),node('summary','已确认条件与沿用参数'),node('h3','本轮新增或确认'),list(rows.filter(([k,v])=>changed.has(k)).map(label)),node('h3','沿用的条件'),list(rows.filter(([k,v])=>!changed.has(k)).map(label)));box.append(conditions);
    append(box,node('p',f.questions.length?'待确认：'+f.questions.map(q=>humanizeQuestion(q.text)).join('；'):s.result?'已知条件齐备，本版结果已保存。':'已知条件齐备。请核对计划。'),node('p',s.reuse?'本版仅重判目标，新增计算为零。':s.result?'本版已有 '+s.result.candidates.length+' 个候选的实际记录；查看和解释不会重新求解。':s.plan?'将比较 '+s.plan.candidates.length+' 个候选；批准后才计算。':'补齐资料后再生成计算计划。','field-note'));
    if(!s.result&&!s.approved_plan_sha256){
      const text=node('textarea');text.rows=2;text.setAttribute('aria-label','只补充或更正一个条件');text.placeholder='例如：更正波长为780 nm；或回答当前唯一缺项。';
      const save=button('保存这句并更新计划',()=>mutate('fact_update',{text:text.value}),'primary',true);
      text.addEventListener('input',()=>save.disabled=pending||!text.value.trim()||credentialLike(text.value));
      append(box,text,save,button('撤销上次资料修改',()=>mutate('undo_fact'),'',pending||!f.events.some(e=>e.changes?.length)));
      for(const q of f.questions.filter(q=>['POSITION_DIRECTION_CONFLICT','UNCONFIRMED_VALUE','CONDITIONAL_PROPOSAL'].includes(q.kind)&&q.fields.length===1)){
        const field=q.fields[0], input=node('input');input.type='number';input.step='any';input.setAttribute('aria-label','确认 '+humanizeQuestion(field));
        const confirm=button('确认这个条件',()=>{const [group,key]=field.split('.');const request=group==='recipe'?{bounds:{[key]:Number(input.value)}}:{[group]:{[key]:Number(input.value)}};return mutate('fact_update',{text:'用户确认单个条件',request});},'',true);
        input.addEventListener('input',()=>confirm.disabled=pending||input.value===''||!Number.isFinite(Number(input.value)));
        append(box,node('p',humanizeQuestion(q.text)),node('label',humanizeQuestion(field)),input,confirm);
      }
    }
    append(box,detail('展开原文出处与版本事件',f));host.append(box);
  }
  function renderExperimentRecord(host,s,pending) {
    const v=s.experiment_record;if(!v)return;
    const box=card('连续实验记录');box.id='experiment-record';
    append(box,node('p',v.text),node('p','当前版本：'+v.record_id+' · '+v.status,'field-note'));
    if(v.draft_context&&v.result_context)append(box,node('h3','当前草稿条件'),detail('草稿目标与条件',v.draft_context),node('h3','此前实际结果的条件'),detail('结果版本与条件',v.result_context));
    else if(v.goal)box.append(node('p','当前目标：'+humanizeQuestion(v.goal.metric)+' '+v.goal.operator+' '+display(v.goal.target)+(v.goal.tolerance!=null?'；容差 '+v.goal.tolerance:'')));
    if(v.changes?.length)append(box,node('h3','本版资料变化'),list(v.changes.map(c=>humanizeQuestion(c.field)+'：'+display(c.before)+' → '+display(c.after))));
    box.append(detail('沿用条件',v.retained_facts));
    if(v.draft_context&&v.candidates?.length)append(box,node('h3','此前实际候选与依据'),list(v.candidates.map(c=>c.candidate_id+'：'+display(c.value)+' '+(c.unit||'')+'；'+c.source_label)));
    if(v.history?.length)append(box,node('h3','本次实验经过'),list(v.history.map(e=>({ask:'询问资料',compute:'启动实际计算',rescore:'复用数值重评',restore:'恢复已有版本',explain:'解释结果',stop:'停止当前要求'}[e.action]||'动作未识别')+' · '+(e.status==='ACCEPTED'?'已接受':'未执行')+(e.reused?'；新增求解 0':'')+' · '+e.record_id)));
    if(s.result){const link=node('a','导出连续实验记录','button');link.href='/api/experiments/cases/'+encodeURIComponent(s.id)+'/export';link.setAttribute('download','');box.append(link);}
    if(s.fact_state&&s.status!=='RUNNING'&&s.status!=='COMPLETED'){
      if(s.ai_step)box.append(node('p',s.ai_step.text,'inline-notice'));
      const input=node('textarea');input.rows=2;input.setAttribute('aria-label','与AI继续这个实验');input.placeholder='例如：只把容差改为0.01 mm；或恢复最初实际计算的版本。';
      const approval=consent('允许将本轮公开实验资料发给真实 AI；新计算仍需核对计划后批准。');
      const send=button('让AI处理下一步',()=>mutate('session_ai',{text:input.value,approve_data:true}),'primary',true);
      const update=()=>send.disabled=pending||!boot.ai?.live_enabled||!approval.input.checked||!input.value.trim()||credentialLike(input.value);
      input.addEventListener('input',update);approval.input.addEventListener('change',update);append(box,input,approval.wrap,send);
    }
    host.append(box);
  }
  function renderResultBrief(host,s,pending){
    const b=s.experiment_record.brief,box=card();box.id='result-brief';
    append(box,node('p','目标 · '+b.goal_text,'section-note'),node('h2',b.headline),node('p',b.scope,'field-note'));
    const go=button('继续这个实验',()=>{document.querySelector('#continue-experiment')?.scrollIntoView({block:'start'});document.querySelector('#continue-input')?.focus();},'primary',pending);
    const summary=node('a','带走只读摘要','button');summary.href='/api/experiments/cases/'+s.id+'/summary';summary.download='PhotonGuard-'+s.id+'.html';append(box,append(node('div',null,'actions'),go,summary));host.append(box);
  }
  function renderContinue(host,s,pending){
    const b=s.experiment_record.brief,box=card('继续这个实验');box.id='continue-experiment';
    const focus=append(node('div',null,'actions')),answer=node('p',b.answers.why_selected,'inline-notice');answer.id='result-answer';answer.setAttribute('aria-live','polite');
    Object.entries({why_selected:'为什么选择它',why_not_met:'为什么未达标',what_changed:'这次改了什么',new_calculation:'有没有重新计算',next_step:'下一步能做什么'}).forEach(([key,label])=>focus.append(button(label,()=>answer.textContent=b.answers[key],'small')));
    append(box,focus,answer,node('p',b.basis+'；下列操作均调用现有工作流程。','field-note'));
    const reveal=selector=>{const panel=$('advanced-actions');panel.open=true;const target=document.querySelector(selector)||panel;target.scrollIntoView({block:'start'});};
    const actions=append(node('div',null,'actions'),button('保持条件，重评目标',()=>reveal('#goal-metric'),'small',pending),button('明确另建探索',()=>reveal('#case-exploration'),'small',pending));
    const versions=s.experiment_record.available_versions||[];
    if(versions.length>1){const select=node('select');select.setAttribute('aria-label','选择要恢复的版本');versions.forEach(v=>{const o=node('option',v.id.slice(0,8)+' · '+display(v.goal));o.value=v.id;select.append(o);});select.value=s.id;append(actions,select,button('恢复所选已有版本',()=>mutate('restore_result',{target_id:select.value}),'small',pending));}
    const exp=node('a','导出完整证据','button small');exp.href='/api/experiments/cases/'+s.id+'/export';exp.download='';append(actions,exp);box.append(actions);
    if(s.fact_state){
      const input=node('textarea');input.id='continue-input';input.rows=2;input.setAttribute('aria-label','与AI继续这个实验');input.placeholder='例如：只把容差更正为0.01 mm；或解释当前结果。';
      const approval=consent('允许把本轮公开资料发给真实 AI；新计算仍须核对和批准。');
      const send=button('让AI处理下一步',()=>mutate('session_ai',{text:input.value,approve_data:true}),'primary',true);
      const update=()=>send.disabled=pending||!boot.ai?.live_enabled||!approval.input.checked||!input.value.trim()||credentialLike(input.value);
      input.addEventListener('input',update);approval.input.addEventListener('change',update);append(box,input,approval.wrap,send);
      if(!boot.ai?.live_enabled)box.append(node('p','实时 AI 尚未启用；可使用上面的本地说明、重评与导出。','field-note'));
      if(s.ai_step)box.append(node('p',s.ai_step.text,'inline-notice'));
    }host.append(box);
  }
  function renderEditor(host,s,pending) {
    if(s.fact_state){const input=node('textarea');input.id='case-material';input.value=s.text;input.hidden=true;input.readOnly=true;host.append(input);return;}

    const section = card('整理实验资料'), label = node('label','已保存资料','input-label'); label.htmlFor = 'case-material';
    const caseRoute=!!(s.library_context||s.library_origin)&&!s.parent_context;
    const input = node('textarea'); input.id = 'case-material'; input.rows = 7; input.maxLength = 24000; input.value = s.text || '';
    const draft = load('draft:' + s.id); let conflict = false;
    if (draft?.text && draft.text !== s.text) { input.value = draft.text; conflict = draft.baseText !== s.text; }
    const note = node('p','修改后需要先保存，再重新整理计划。','field-note');
    const store = () => { if (credentialLike(input.value)) { clear('draft:' + s.id); note.textContent = '检测到疑似密钥，请移除后再保存。'; return; } if (input.value === s.text) clear('draft:' + s.id); else save('draft:' + s.id,{text:input.value,baseText:s.text,revision:s.revision}); };
    const saved = button('保存修改',() => mutate('save',{text:input.value}));
    const local = button('用本地规则整理计划',() => mutate('plan',{mode:'rules'}),'primary');
    const aiConsent = consent('允许把已保存的资料发送给真实 AI 整理计划，使用现有授权额度；不自动运行计算。');
    const libraryAI=button('让 AI 检索案例并按目标规划',()=>mutate('library_plan',{mode:'live',approve_data:true}));
    const live = button('让真实 AI 整理计划',() => mutate('plan',{mode:'live',approve_data:true}));
    const update = () => { const dirty = input.value !== (s.text || ''), blocked = pending || conflict || credentialLike(input.value); saved.disabled = busy || blocked || !dirty || !input.value.trim(); local.disabled = busy || blocked || dirty || !input.value.trim(); live.disabled = busy || blocked || dirty || !boot.ai?.live_enabled || !aiConsent.input.checked || !input.value.trim(); aiConsent.input.disabled = pending || dirty || conflict || !boot.ai?.live_enabled; libraryAI.disabled=live.disabled; if (dirty && !credentialLike(input.value)) note.textContent = '有未保存修改。当前摘要与计划属于已保存版本；保存后才能重新整理。'; };
    input.addEventListener('input',() => { aiConsent.input.checked = false; store(); update(); document.querySelectorAll('[data-run-consent]').forEach(e => { e.checked = false; e.disabled = input.value !== s.text; }); document.querySelectorAll('[data-run-button]').forEach(e => { e.disabled = true; }); });
    aiConsent.input.addEventListener('change',update);
    append(section,label,input,note);
    if (conflict) { const conflictBox = node('div',null,'inline-notice warning'); append(conflictBox,node('p','本标签页有草稿，但已保存资料在其他页面发生了变化。先核对，避免覆盖。'),detail('查看当前已保存的资料',s.text),button('已核对，使用编辑框中的文字',() => { conflict = false; store(); conflictBox.remove(); update(); },'small'),button('使用已保存的资料',() => { conflict = false; input.value = s.text; clear('draft:' + s.id); conflictBox.remove(); update(); },'small')); section.append(conflictBox); }
    append(section,append(node('div',null,'actions'),saved,caseRoute?null:local),aiConsent.wrap,append(node('div',null,'actions'),s.parent_context?null:libraryAI,caseRoute?null:live));
    if(caseRoute)section.append(node('p','补充资料后会继续使用案例规划，并保留来源版本的参数与本次探索剩余额度。','field-note'));
    if (!boot.ai?.live_enabled) section.append(node('p','真实 AI 当前不可用：' + (boot.ai?.reason || '未配置可用服务') + '。教学卡和本地规则仍可使用。','field-note'));
    else section.append(node('p','实际请求会计入累计账本。AI 只整理参数与计划，数值来自后续计算。','field-note'));
    if (s.spec) section.append(sourceReview(s));
    input.disabled = pending; update();
    if(s.library_origin && /^(用户明确选用教学示例：|用户通过参数表提供：|用户明确新探索：)/.test(s.text || '') && !draft){
      const summary=card('已保存案例资料');append(summary,node('p','已根据所选案例和参数表生成计划。请在下面核对目标、保持不变的参数与候选，再开始计算。','section-note'));
      const raw=node('details');append(raw,node('summary','查看或修改原始记录'),section);append(summary,raw);host.append(summary);
    }else host.append(section);
  }
  function renderQuestions(host,s,pending) {
    const section = card('还需要核对这些信息');
    append(section,node('p','补充你知道的事实即可。原始资料会保留，补充内容追加在后面。','section-note'),list(s.questions.map(item => typeof item === 'string' ? humanizeQuestion(item) : item)));
    if (s.approved_plan_sha256 || s.result) { host.append(section); return; }
    if(s.library_context&&!s.parent_context){
      const choice=node('select');choice.setAttribute('aria-label','补充参数所用案例');choice.append(node('option','请选择适用案例'));
      choice.firstChild.value='';(boot.case_library||[]).filter(c=>!s.domain||c.domain===s.domain).forEach(c=>{const o=node('option',c.id+' · '+c.title);o.value=c.id;choice.append(o);});choice.value=s.library_context.case_id||'';
      const direct=button('直接填写参数表继续',async()=>{
        const selectedCase=choice.value;if(!selectedCase)return;
        setBusy(true);try{const parent=s.library_context.parent_id?await api('/cases/'+s.library_context.parent_id):null;setBusy(false);if(current?.id===s.id)showCaseForm(selectedCase,s.kind,parent,s);}catch(e){message('error',e.message);}finally{setBusy(false);}
      },'small',pending||!choice.value);
      choice.addEventListener('change',()=>{direct.disabled=pending||!choice.value;});append(section,node('p','也可以直接填写参数表恢复当前计划，无需再次调用 AI；来源条件和剩余额度仍会核对。','field-note'),choice,direct);
    }
    const label = node('label','补充缺失的参数','input-label'); label.htmlFor = 'supplement-material';
    const input = node('textarea'); input.id = 'supplement-material'; input.rows = 3; input.maxLength = 24000; input.placeholder = '例如：束腰位于透镜前40 mm，即 z=-40 mm，其余参数不变。'; input.value = load('supplement:' + s.id)?.text || '';
    const note = node('p','写明参数名称、数值和单位；不必重写已有资料。','field-note');
    const local = button(s.fact_state?'保存补充并更新计划':'只保存补充资料',() => mutate('supplement',{text:input.value,mode:'save'}),'',true);
    const permit = consent('允许把原资料与本次补充一起发送给真实 AI，继续整理计划；使用现有授权额度。');
    const live = button('补充并让 AI 继续整理',() => mutate('supplement',{text:input.value,mode:'live',approve_data:true}),'primary',true);
    const update = () => {
      const secret = credentialLike(input.value), dirty = $('case-material')?.value !== s.text;
      const disabled = busy || pending || !input.value.trim() || secret || dirty;
      local.disabled = disabled; live.disabled = disabled || !boot.ai?.live_enabled || !permit.input.checked;
      permit.input.disabled = pending || !boot.ai?.live_enabled || dirty;
      if (secret) { clear('supplement:' + s.id); note.textContent = '检测到疑似密钥，请移除后再保存。'; }
      else { save('supplement:' + s.id,{text:input.value}); note.textContent = dirty ? '上方原始资料有未保存修改，请先保存或还原，再追加补充。' : '写明参数名称、数值和单位；不必重写已有资料。'; }
    };
    input.addEventListener('input',() => { permit.input.checked = false; update(); }); permit.input.addEventListener('change',update);
    $('case-material')?.addEventListener('input',() => { permit.input.checked = false; update(); });
    input.disabled = pending; append(section,label,input,note,append(node('div',null,'actions'),local));
    if (boot.ai?.live_enabled) append(section,permit.wrap,append(node('div',null,'actions'),live)); update(); host.append(section);
  }
  function renderPlan(host,s,pending) {
    const p = s.plan, section = card(s.status === 'PLANNED' ? '开始前，核对这份计划' : '这次采用的实验计划');
    if (p.summary) section.append(node('p',p.summary,'section-note'));
    const locks = p.locked_parameters || s.spec?.locked_parameters;
    const lockValues = Array.isArray(locks) ? Object.fromEntries(locks.map(key => [key,s.spec?.known_parameters?.[key] ?? '见规范参数'])) : locks;
    append(section, facts({goal:p.goal || s.spec?.goal,locked_parameters:lockValues,allowed_variables:p.allowed_variables || s.spec?.allowed_variables,resource_budget:p.resource_budget || s.spec?.resource_budget}));
    if ((p.assumptions || s.spec?.assumptions)?.length) append(section,node('h3','模型假设'),list(p.assumptions || s.spec.assumptions));
    const candidates = p.candidates || [];
    if (candidates.length) { append(section,node('h3','本次有限候选 · ' + candidates.length + ' 个')); const table = node('table'), head = append(node('tr'),node('th','候选'),node('th','实际计算参数')); table.append(append(node('thead'),head)); const tbody = node('tbody'); candidates.forEach(c => tbody.append(append(node('tr'),node('td',c.id),node('td',display(c.parameters || c))))); append(table,tbody); section.append(append(node('div',null,'table-scroll'),table)); }
    append(section,node('p','优选仅限上述实际计算的候选。离散采样点的指标不等同于连续范围认证。','field-note'),detail('查看工具、停止条件与完整计划',p));
    if (s.status === 'PLANNED') {
      const approval = consent('我已核对资料来源、模型假设、固定条件、候选与计算额度，同意执行这份计划。'); approval.input.dataset.runConsent = 'true';
      const start = button('确认计划，开始计算',() => mutate('run',{approve:true,plan_sha256:p.sha256}),'primary',true); start.dataset.runButton = 'true';
      approval.input.disabled = pending || $('case-material')?.value !== s.text;
      approval.input.addEventListener('change',() => { start.disabled = busy || pending || !approval.input.checked || !p.sha256 || $('case-material')?.value !== s.text; });
      append(section,approval.wrap,append(node('div',null,'actions'),start));
    }
    if (['COMPLETED','FAILED'].includes(s.status)) host.append(append(node('details'),node('summary','查看已批准的计划、固定条件与全部候选'),section));
    else host.append(section);
  }
  function goalText(c) { if (c.all_checks_passed !== true) return '数值检查未通过，暂不能认定达标'; if (c.goal?.met === true) return '达到目标'; if (c.goal?.met === false) return '未达到目标'; if (c.goal?.optimization_only) return '仅比较优劣，未设达标阈值'; return '目标尚未判定'; }
  const goalClass = c => c.all_checks_passed !== true ? 'warning' : c.goal?.met === true ? 'ok' : c.goal?.met === false ? 'warning' : '';
  function checksText(checks) {
    if (checks == null) return '未提供检查记录';
    if (Array.isArray(checks)) return checks.map(c => typeof c === 'string' ? c : (c.name || c.id || '检查') + '：' + (c.passed === true || c.pass === true ? '通过' : c.passed === false || c.pass === false ? '未通过' : display(c.status || c))).join('；');
    if (typeof checks === 'object') { const values = Object.values(checks), known = values.filter(c => typeof c === 'boolean' || typeof c?.passed === 'boolean'); if (known.length) { const passed = known.filter(c => c === true || c?.passed === true).length; return passed + '/' + known.length + ' 项检查通过' + (known.length < values.length ? '，其他记录见详情' : '') + (passed < known.length ? '；请核对未通过项' : ''); } }
    return display(checks);
  }
  function renderResult(host,s,pending,compact=false) {
    const r = s.result, candidates = r.candidates || [], section = card(), header = node('div',null,'result-heading');
    append(header,node('h2','实际计算结果'),badge(s.status === 'COMPLETED' ? '计算记录已保存' : '已保留本次结果')); section.append(header);
    const assumptions = s.plan?.assumptions || s.spec?.assumptions;
    if (!compact&&assumptions?.length) append(section,node('h3','这次计算采用什么模型'),list(assumptions));
    if (!compact&&r.summary) section.append(node('p',r.summary));
    if (!compact&&s.plan?.goal) section.append(node('p','本次目标：' + display(s.plan.goal),'section-note'));
    const winner = candidates.find(c => c.id === r.winner_id);
    if (!compact&&winner) append(section,node('p','有限候选中的优选：' + winner.id,'result-big'),node('p',goalText(winner) + '。结果仅对应这次计划中的模型与已计算候选。','section-note'));
    const table = node('table'); append(table,append(node('thead'),append(node('tr'),node('th','候选 / 引擎'),node('th','目标指标'),node('th','检查与完成状态'),node('th','目标是否达成'))));
    if (s.domain === 'film') { table.querySelector('tr').append(node('th','独立 Meep 核对')); section.append(node('p','目标指标来自 TMM 快速计算。右列单独列出 Meep 数值检查，运行完成不等于检查通过。','field-note')); }
    const tbody = node('tbody');
    candidates.forEach(c => {
      const row = node('tr',null,c.id === r.winner_id ? 'chosen' : '');
      const metric = c.goal?.value != null ? display(c.goal.value) + (c.goal.unit ? ' ' + display(c.goal.unit) : '') : display(c.metrics);
      const engine = typeof c.engine === 'object' ? (c.engine.name || '记录中的引擎') + (c.engine.version ? ' ' + c.engine.version : '') : c.engine;
      const legacyOrigin = s.domain === 'film' ? 'TMM实际采样' : s.domain === 'gaussian' ? '高斯q参数与ABCD计算' : ['fringe_period_mm','first_zero_mm'].includes(c.goal?.metric) ? '理想几何公式；另有二维场数值校准' : '二维场中心光强与同几何零相位基准之比';
      const metricCell = append(node('td'),node('strong',metric),node('div',name(c.goal?.metric || '目标指标')),node('p','来源：' + (c.goal?.source?.label || legacyOrigin),'field-note'));
      if (c.goal?.source) metricCell.append(detail('指标来源记录',c.goal.source));
      append(row,append(node('td'),node('strong',c.id),c.changes && Object.keys(c.changes).length ? node('div',display(c.changes)) : null,node('div',engine || '引擎见记录','muted')),metricCell,node('td',checksText(c.checks) + (c.status ? ' · ' + display(c.status) : '')),append(node('td'),badge(goalText(c),goalClass(c))));
      if (s.domain === 'film') {
        const v = c.verification, passed = v?.numerical_status === 'NUMERICAL_PASS';
        const failed = v?.status?.includes('FAIL') || v?.numerical_status === 'NUMERICAL_FAIL';
        const label = !v ? '未执行' : passed ? '数值检查通过' : failed ? '核对未通过' : v.status === 'UNSUPPORTED_COVERAGE' ? '目标范围暂不支持复核' : v.status === 'RUN_COMPLETED' ? '计算完成，检查状态见记录' : display(v.status || '状态见记录');
        row.append(append(node('td'),badge(label,passed ? 'ok' : failed ? 'fail' : ''),
          v?.goal_meep?.value != null ? node('p','Meep：' + display(v.goal_meep.value) + ' · ' + name(v.goal_meep.metric),'field-note') : null,
          v?.goal_meep ? node('p','Meep目标：' + goalText({goal:v.goal_meep,all_checks_passed:passed}),'field-note') : null,
          v?.coverage?.kind === 'POINT_GOAL_ONLY' ? node('p','仅核对目标波长及附近采样点，不覆盖整段快速光谱。','field-note') : null,
          v ? detail('查看核对记录',v) : null));
      }
      tbody.append(row);
    });
    table.append(tbody);const candidateTable=append(node('div',null,'table-scroll'),table);if(!compact)section.append(candidateTable);
    if (s.parent_comparison?.rows?.length) {
      const pc = s.parent_comparison, box = card('与来源实验对照'), table = node('table');
      const flag = value => value === true ? '达到目标' : value === false ? '未达到目标' : '未设达标阈值';
      append(box,node('p','下面配对的方案使用相同计算参数与指标。改变判定目标不代表改变了物理结果。','section-note'));
      table.append(append(node('thead'),append(node('tr'),...['候选','原指标值','本次指标值','变化量','原目标 / 新目标'].map(h=>node('th',h)))));
      const body = node('tbody');pc.rows.forEach(row=>body.append(append(node('tr'),node('td',row.candidate_id),node('td',display(row.previous_value)),node('td',display(row.value)+' '+row.unit),node('td',display(row.difference)),node('td',row.both_numeric_checks_passed ? flag(row.previous_goal_met)+' / '+flag(row.goal_met) : '检查尚未全部通过'))));
      table.append(body);append(box,append(node('div',null,'table-scroll'),table),detail('前后目标与完整对照',pc));section.append(box);
    } else if (s.parent_comparison?.status === 'DIFFERENT_METRIC_OR_WAVELENGTH') section.append(node('p','本次指标或目标波长已变化，数值不作直接增减比较，可查看来源实验分别核对。','field-note'));
    if (!candidates.length) section.append(node('p','当前没有可展示的候选结果，请查看保存的状态与停止原因。','section-note'));
    const visible = candidates.filter(c => c.data?.x?.length || c.data?.image?.values?.length);
    if (visible.length) {
      const visualHeader = node('div',null,'result-heading'), select = node('select'); select.className = 'chart-select'; select.setAttribute('aria-label','选择要查看的候选曲线'); visible.forEach(c => { const o = node('option',c.id + (c.id === r.winner_id ? ' · 本次优选' : '')); o.value = c.id; select.append(o); }); if (visible.some(c => c.id === r.winner_id)) select.value = r.winner_id;
      const bounds = {x:[Infinity,-Infinity],y:[Infinity,-Infinity]};
      visible.forEach(c => { (c.data.x || []).filter(Number.isFinite).forEach(v => { bounds.x[0] = Math.min(bounds.x[0],v); bounds.x[1] = Math.max(bounds.x[1],v); }); (c.data.series || []).forEach(series => (series.y || []).filter(Number.isFinite).forEach(v => { bounds.y[0] = Math.min(bounds.y[0],v); bounds.y[1] = Math.max(bounds.y[1],v); })); });
      const plots = node('div',null,'visual'); const show = () => { plots.replaceChildren(); const c = visible.find(item => item.id === select.value); if (c) append(plots,plot(c.data,bounds),heatmap(c.data.image)); }; select.addEventListener('change',show); append(visualHeader,node('h3','查看实际采样'),select); append(section,visualHeader,plots); show();
    }
    if(compact){const evidence=append(node('details'),node('summary','全部候选、检查与模型限制'),candidateTable);if(visible.length>1)renderOverlay(evidence,visible,r.winner_id);append(evidence,list([...(assumptions||[]),...(r.limitations||[])]));section.append(evidence);}
    else {if (visible.length > 1) renderOverlay(section,visible,r.winner_id);if (r.limitations?.length) append(section,node('h3','这些结果的适用范围'),list(r.limitations));}
    if (r.resources) append(section,detail('查看实际计算资源与候选记录',{resources:r.resources,ranking:r.ranking,candidates:candidates.map(({data,...c}) => c)}));
    const exportLink = node('a','导出本次记录与可重跑配置','button'); exportLink.href = '/api/experiments/cases/' + encodeURIComponent(s.id) + '/export'; exportLink.setAttribute('download','');
    const tableLink = node('a','下载候选数据表','button');tableLink.href = '/api/experiments/cases/' + encodeURIComponent(s.id) + '/table';tableLink.download = 'PhotonGuard-'+s.id+'-candidates.csv';
    section.append(append(node('div',null,'actions'),exportLink,tableLink));section.append(node('p','完整记录包含候选表、实际采样曲线表和重跑配置；可直接用表格软件读取 CSV。','field-note'));host.append(section);
    if(compact)return;
    const explanation = card('读懂结果');
    if (s.explanation) append(explanation,node('p',s.explanation.text || display(s.explanation)),node('p','AI 解释请与上面的候选、目标指标和检查结果对照。','field-note'),detail('解释与实际记录的关联',s.explanation));
    const permit = consent('允许把这次已保存的实验记录发送给真实 AI，生成解释；使用现有授权额度。');
    const explain = button(s.explanation ? '重新解释本次记录' : '让真实 AI 解释这些结果',() => mutate('explain',{approve_data:true}),'',true);
    permit.input.disabled = pending || !boot.ai?.live_enabled; permit.input.addEventListener('change',() => { explain.disabled = busy || pending || !boot.ai?.live_enabled || !permit.input.checked; });
    if (boot.ai?.live_enabled && !s.explanation) append(explanation,permit.wrap,append(node('div',null,'actions'),explain)); else if (!s.explanation) explanation.append(node('p','可直接查看计算指标；连接 AI 后可获取结果解释。','section-note'));
    host.append(explanation);
  }
  function renderRevision(host,s,pending) {
    renderGoalEditor(host,s,pending);
    const section = card('在这个实验上，试一个新目标');
    append(section,node('p','写明要改变什么、保持什么。修改会建立新版本，核对并批准后才执行，原结果保留。','section-note'));
    const label = node('label','这次修改要求','input-label'); label.htmlFor = 'revision-material'; const input = node('textarea'); input.id = 'revision-material'; input.rows = 4; input.maxLength = 24000; input.placeholder = '例如：保持双缝几何与波长不变，只允许改变相对相位，把中心亮纹变暗。'; input.value = load('revision:' + s.id)?.text || '';
    const note = node('p','新的候选与资源范围仍需你核对。','field-note');
    const local = button('按本地规则创建新计划',() => mutate('revise',{text:input.value,mode:'rules'}),'primary',true);
    const permit = consent('允许把原始计划和修改要求发送给真实 AI，整理为新计划；使用现有授权额度。');
    const live = button('让真实 AI 整理修改要求',() => mutate('revise',{text:input.value,mode:'live',approve_data:true}),'',true);
    const update = () => { const secret = credentialLike(input.value), disabled = busy || pending || !input.value.trim() || secret; local.disabled = disabled; live.disabled = disabled || !boot.ai?.live_enabled || !permit.input.checked; permit.input.disabled = pending || !boot.ai?.live_enabled; if (secret) { clear('revision:' + s.id); note.textContent = '检测到疑似密钥，请移除后再发送。'; } else save('revision:' + s.id,{text:input.value}); };
    input.addEventListener('input',() => { permit.input.checked = false; update(); }); permit.input.addEventListener('change',update); input.disabled = pending;
    append(section,label,input,note,append(node('div',null,'actions'),local)); if (boot.ai?.live_enabled) append(section,permit.wrap,append(node('div',null,'actions'),live)); update(); host.append(section);
  }
  function renderGoalEditor(host,s,pending) {
    if (!s.plan) return;
    const section = card('直接设置下一个目标'), old = s.plan.goal;
    append(section,node('p','保留物理参数、候选目录和计算额度，只调整评价指标与目标。设置后另存新计划，核对再运行。','section-note'));
    const metric = node('select'),operator = node('select');
    metric.id = 'goal-metric';operator.id = 'goal-operator';
    (boot.metrics?.[s.domain] || [old.metric]).filter(m=>!(s.spec.known_parameters.aperture === 'single_slit' && m === 'fringe_period_mm')).forEach(m=>{const o=node('option',name(m));o.value=m;metric.append(o);});metric.value=old.metric;
    [['<=','不超过'],['>=','至少'],['near','接近指定值'],['minimize','在候选中取最小值'],['maximize','在候选中取最大值']].forEach(([value,label])=>{const o=node('option',label);o.value=value;operator.append(o);});operator.value=old.operator;
    const target=node('input'),tolerance=node('input'),wavelength=node('input');
    target.id='goal-target';tolerance.id='goal-tolerance';wavelength.id='goal-wavelength';
    [target,tolerance,wavelength].forEach(n=>{n.type='number';n.step='any';});target.value=old.target ?? '';tolerance.value=old.tolerance ?? '';wavelength.value=old.wavelength_um ?? '';
    const wrap=(label,input)=>{const n=node('label',label,'input-label');n.htmlFor=input.id;return append(node('div'),n,input);};
    const targetBox=wrap('目标值',target),toleranceBox=wrap('允许误差',tolerance),waveBox=wrap('实际测试的波长（μm）',wavelength),note=node('p','','field-note');
    const isPoint=()=>['reflectance','transmittance'].includes(metric.value), isOptimization=()=>['minimize','maximize'].includes(operator.value);
    const validNumber=input=>input.value.trim()!=='' && Number.isFinite(Number(input.value));
    const apply=button('保留参数，生成新目标计划',()=>{
      const g={metric:metric.value,operator:operator.value,unit:metric.value.endsWith('_um')?'um':metric.value.endsWith('_mm')?'mm':'fraction'};
      if (!isOptimization()) g.target=Number(target.value);if (operator.value==='near') g.tolerance=Number(tolerance.value);if (isPoint()) g.wavelength_um=Number(wavelength.value);
      mutate('revise_goal',{goal:g});
    },'primary',true);
    const update=()=>{
      const unit=metric.value.endsWith('_um')?'μm':metric.value.endsWith('_mm')?'mm':'比例（0–1）';
      targetBox.querySelector('label').textContent='目标值（'+unit+'）';toleranceBox.querySelector('label').textContent='允许误差（'+unit+'）';
      targetBox.hidden=isOptimization();toleranceBox.hidden=operator.value!=='near';waveBox.hidden=!isPoint();
      const valid=(isOptimization()||validNumber(target))&&(operator.value!=='near'||(validNumber(tolerance)&&Number(tolerance.value)>=0))&&(!isPoint()||(validNumber(wavelength)&&Number(wavelength.value)>0));
      apply.disabled=busy||pending||!valid;note.textContent='相同指标与采样会直接复用实际数值，仅重判目标；其他改动生成新计划，核对后再计算。';
    };
    [metric,operator,target,tolerance,wavelength].forEach(n=>{n.disabled=pending;n.addEventListener('input',update);});
    append(section,wrap('比较哪个指标',metric),wrap('希望达到什么目标',operator),targetBox,toleranceBox,waveBox,note,append(node('div',null,'actions'),apply));update();host.append(section);
  }
  function renderOverlay(host,candidates,winner) {
    const section=card('把候选曲线放在一起比较'),controls=node('div',null,'actions'),charts=node('div');
    const selected=new Set([winner || candidates[0].id,candidates.find(c=>c.id!==winner)?.id].filter(Boolean));
    const seriesChoice=node('select');seriesChoice.setAttribute('aria-label','选择叠加比较的曲线指标');
    (candidates[0].data.series || []).forEach((series,i)=>{const o=node('option',display(series.label));o.value=String(i);seriesChoice.append(o);});
    const boxes=[];
    const show=()=>{
      charts.replaceChildren();const rows=candidates.filter(c=>selected.has(c.id)),i=Number(seriesChoice.value);
      boxes.forEach(({input,id})=>{input.disabled=!selected.has(id)&&selected.size>=6;});
      if (!rows.length) { charts.append(node('p','选择至少一个候选。','field-note'));return; }
      const first=rows[0].data,series=rows.filter(c=>c.data.series?.[i]).map(c=>({...c.data.series[i],x:c.data.x,label:c.id+' · '+display(c.changes)}));
      charts.append(plot({x:rows.flatMap(c=>c.data.x),series,x_label:first.x_label,y_label:first.y_label}));
    };
    candidates.forEach(c=>{const entry=consent(c.id+' · '+display(c.changes));entry.input.checked=selected.has(c.id);entry.input.addEventListener('change',()=>{if(entry.input.checked)selected.add(c.id);else selected.delete(c.id);show();});boxes.push({input:entry.input,id:c.id});controls.append(entry.wrap);});
    seriesChoice.addEventListener('change',show);append(section,node('p','最多同时显示6个候选，使用各自实际采样坐标和共同坐标轴。','field-note'),seriesChoice,controls,charts);host.append(section);show();
  }
  function svgNode(tag, attrs = {}, text) { const e = document.createElementNS('http://www.w3.org/2000/svg',tag); Object.entries(attrs).forEach(([k,v]) => e.setAttribute(k,String(v))); if (text != null) e.textContent = String(text); return e; }
  function plot(data,bounds) {
    if (!Array.isArray(data?.x) || !Array.isArray(data.series)) return null;
    const x = data.x, series = data.series.filter(s => Array.isArray(s.y) && s.y.length === (s.x || x).length), finiteX = x.filter(Number.isFinite), finiteY = series.flatMap(s => s.y.filter(Number.isFinite)); if (finiteX.length < 1 || !finiteY.length) return node('p','这份记录没有可绘制的有效曲线。','field-note');
    let loX = bounds?.x.every(Number.isFinite) ? bounds.x[0] : Math.min(...finiteX), hiX = bounds?.x.every(Number.isFinite) ? bounds.x[1] : Math.max(...finiteX), loY = bounds?.y.every(Number.isFinite) ? bounds.y[0] : Math.min(...finiteY), hiY = bounds?.y.every(Number.isFinite) ? bounds.y[1] : Math.max(...finiteY); if (loX === hiX) hiX = loX+1; if (loY === hiY) { loY -= Math.max(1,Math.abs(loY))*.05; hiY += Math.max(1,Math.abs(hiY))*.05; }
    const width = 740,height = 330,left = 71,right = 22,top = 19,bottom = 66,pw = width-left-right,ph = height-top-bottom,tx = v => left+(v-loX)/(hiX-loX)*pw,ty = v => top+(hiY-v)/(hiY-loY)*ph;
    const wrap = node('div'), svg = svgNode('svg',{viewBox:`0 0 ${width} ${height}`,class:'plot',role:'img','aria-label':(data.x_label || '采样坐标') + '与' + (data.y_label || '计算值') + '的实际采样曲线'}); svg.append(svgNode('title',{},'实际候选采样曲线；连线仅用于阅读，不新增计算点'));
    for (let i=0;i<=4;i++) { const xv = loX+(hiX-loX)*i/4,yv = loY+(hiY-loY)*i/4; svg.append(svgNode('line',{x1:left,x2:width-right,y1:ty(yv),y2:ty(yv),class:'grid'}),svgNode('text',{x:left-9,y:ty(yv)+4,'text-anchor':'end'},Number(yv.toPrecision(4))),svgNode('text',{x:tx(xv),y:height-bottom+23,'text-anchor':'middle'},Number(xv.toPrecision(4)))); }
    svg.append(svgNode('line',{x1:left,x2:width-right,y1:height-bottom,y2:height-bottom,class:'axis'}),svgNode('line',{x1:left,x2:left,y1:top,y2:height-bottom,class:'axis'}),svgNode('text',{x:left+pw/2,y:height-12,'text-anchor':'middle'},display(data.x_label || '采样坐标（单位见记录）')),svgNode('text',{x:17,y:top+ph/2,transform:`rotate(-90 17 ${top+ph/2})`,'text-anchor':'middle'},display(data.y_label || '计算值（单位见记录）')));
    const legend = node('div',null,'plot-legend'), colors = ['#116b61','#d27832','#7162b5','#297eb0','#a84258'];
    series.forEach((s,i) => { const sx=s.x || x;let d = '',active = false; for (let j=0;j<sx.length;j++) { if (!Number.isFinite(sx[j]) || !Number.isFinite(s.y[j])) {active = false;continue;} d += (active?'L':'M')+tx(sx[j]).toFixed(3)+','+ty(s.y[j]).toFixed(3);active = true; } const color = colors[i%colors.length]; if(s.points){sx.forEach((value,j)=>{if(Number.isFinite(value)&&Number.isFinite(s.y[j]))svg.append(svgNode('circle',{cx:tx(value),cy:ty(s.y[j]),r:2,fill:color}));});}else svg.append(svgNode('path',{d,fill:'none',stroke:color,'stroke-width':2})); const item = node('span'), swatch = node('span',null,'legend-swatch'); swatch.style.background = color; item.append(swatch,node('span',display(s.label || '曲线 '+(i+1)))); legend.append(item); });
    append(wrap,svg,legend,node('p','本批候选共用曲线坐标范围。连线仅连接实际采样点，不代表额外的求解或连续范围证明。','field-note')); return wrap;
  }
  function heatmap(data) {
    if (!Array.isArray(data?.values) || !data.values.length || !Array.isArray(data.values[0])) return null;
    const height = data.values.length,width = data.values[0].length;
    if (!width || width > 1024 || height > 1024 || data.values.some(row => !Array.isArray(row) || row.length !== width)) return node('p','二维数据形状无法显示，请导出原始结果核对。','field-note');
    const wrap = node('div',null,'heatmap-wrap'), canvas = node('canvas'); canvas.width = width; canvas.height = height; canvas.setAttribute('role','img'); canvas.setAttribute('aria-label','实际计算的二维场分布；颜色范围见下方');
    const ctx = canvas.getContext('2d'); if (!ctx) return node('p','浏览器不能显示二维图，请导出原始数据。','field-note');
    const image = ctx.createImageData(width,height), min = Number.isFinite(data.vmin) ? data.vmin : 0, max = Number.isFinite(data.vmax) ? data.vmax : 1;
    const stops = [[16,25,47],[29,110,142],[56,174,139],[235,237,136]];
    for (let y=0;y<height;y++) for (let x=0;x<width;x++) { const value = data.values[y][x],t = Number.isFinite(value) ? Math.max(0,Math.min(1,(value-min)/(max-min || 1))) : 0,pos=t*3,index=Math.min(2,Math.floor(pos)),f=pos-index,offset=((height-1-y)*width+x)*4; for (let c=0;c<3;c++) image.data[offset+c]=Math.round(stops[index][c]*(1-f)+stops[index+1][c]*f);image.data[offset+3]=255; }
    ctx.putImageData(image,0,0); append(wrap,node('h3','二维分布'),canvas,node('div',null,'colorbar'),append(node('div',null,'colorbar-labels'),node('span',display(min)),node('span',display(max))),node('p',data.normalization_label || '按记录数值显示，固定色标 0–1；未按每张图单独归一化。','field-note'));
    if (data.x?.length || data.y?.length) append(wrap,node('p',display(data.x_label || '横坐标') + '：' + display(data.x?.[0]) + ' ～ ' + display(data.x?.[data.x.length-1]) + '；' + display(data.y_label || '纵坐标') + '：' + display(data.y?.[0]) + ' ～ ' + display(data.y?.[data.y.length-1]),'field-note'));
    return wrap;
  }
  function schedulePoll(id) { clearTimeout(pollTimer); pollTimer = setTimeout(async () => { if (busy || current?.id !== id || current.status !== 'RUNNING') return; const turn = navigation; try { const s = await api('/cases/' + encodeURIComponent(id)); if (current?.id !== id || navigation !== turn) return; current = s; cacheCase(s); render(); } catch (e) { if (current?.id === id) { message('error',e.message); schedulePoll(id); } } },2500); }
  function render() { clearTimeout(pollTimer); $('content').replaceChildren(); sidebar(); if (current) renderCase(); else renderHome(); }
  async function init() {
    $('new-case').addEventListener('click',home);
    $('ai-settings').onclick = openAI;
    try { boot = await api('/bootstrap'); boot.cases = boot.cases || []; boot.templates = boot.templates || []; boot.tools = boot.tools || []; $('ai-status').textContent = boot.ai?.live_enabled ? 'AI 已连接' : boot.capabilities?.local_workers ? 'AI 未连接 · 可本地计算' : '可查看记录 · 计算未启用'; $('ai-status').className = 'badge' + (boot.ai?.live_enabled ? ' ok' : ''); const id = new URLSearchParams(location.hash.slice(1)).get('case'); if (id) await select(id); else render(); }
    catch (e) { message('error',e.message); $('ai-status').textContent = '服务暂不可用'; $('content').replaceChildren(node('p','连接恢复后可重新读取。已有记录不会因为本页连接失败而丢失。','section-note'),button('重新连接',init)); }
    if (boot) aiBadge();
  }
  window.addEventListener('beforeunload',event => { const field = $('case-material'), revise = $('revision-material'); if (busy || field && field.value !== current?.text || revise?.value.trim()) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('hashchange',() => { if (!boot || busy) return; const id = new URLSearchParams(location.hash.slice(1)).get('case'); if (id && id !== current?.id) select(id); else if (!id) home(); });
  init();
})();
