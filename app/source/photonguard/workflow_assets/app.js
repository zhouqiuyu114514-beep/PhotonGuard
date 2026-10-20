/* Local workflow; explicit model actions only. Novice drafts use tab-local recovery. */
'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const content = $('content');
  const app = { bootstrap: null, state: null, busy: false, poll: null, selectedRun: null, spectrumCache: new Map(), viewToken: 0, disabled: new Map(), sourceDraft: '', sourceName: 'input.py', workspace: 'default', completedHere: new Set() };
  const STEP_NAMES = ['了解背景', '整理任务', '读取脚本', '确认与核对', '真实运行', '审核修改', '复验与证据'];
  const STEP_SUBS = ['先说清楚要做什么', '独立材料与参数来源', '只读 AST · 不执行上传代码', '需求与代码逐项对照', '本地 Meep + 独立参考', '明确同意后再应用', '重验曲线与原始证据'];
  const KIND_STEP = { context: 0, task: 1, import: 2, confirm: 3, run: 4, wait: 4, propose: 5, apply: 5, report: 6, unsupported: 2 };
  const STATUS = { PASS: 'PASS · 通过检查', FAIL: 'FAIL · 发现问题', INCONCLUSIVE: 'INCONCLUSIVE · 证据不足', UNSUPPORTED: 'UNSUPPORTED · 超出范围', running: '运行中', queued: '等待运行', completed: '已完成', failed: '运行失败', pending: '待运行', idle: '尚未运行' };
  const FIELD_LABELS = { background: '项目背景', goal: '这次想完成什么', role: '你负责的部分', materials: '手上已有的材料', unknowns: '还不确定的地方', parameter_source: '参数从哪里来' };
  function n(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined && text !== null) node.textContent = String(text); return node; }
  function append(parent, ...children) { children.flat(Infinity).forEach(child => { if (child !== undefined && child !== null) parent.append(child); }); return parent; }
  function p(text, cls = '') { return n('p', cls, text); }
  function pill(text, cls = '') { return n('span', `pill ${cls}`, text); }
  function button(text, fn, cls = '', disabled = false) { const b = n('button', `button ${cls}`, text); b.type = 'button'; b.disabled = disabled; if (fn) b.addEventListener('click', fn); return b; }
  function pretty(value) { return JSON.stringify(value === undefined ? null : value, null, 2); }
  function readable(value) { if (value === null || value === undefined || value === '') return '未提供'; if (typeof value === 'object') return pretty(value); return String(value); }
  function pre(value) { return n('pre', '', typeof value === 'string' ? value : pretty(value)); }
  function info(text, cls = '') { return n('div', `info-box ${cls}`, text); }
  function finite(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
  function format(value, precision = 5) { return finite(value) === null ? '—' : Number(value.toPrecision(precision)).toString(); }
  function status(value) { return pill(STATUS[value] || readable(value), /^[A-Za-z_]+$/.test(value || '') ? value : 'neutral'); }
  function announce(message, error = false) { const target = $(error ? 'error' : 'notice'); target.textContent = message; target.hidden = !message; if (error) target.scrollIntoView({ block: 'nearest', behavior: 'auto' }); }
  function clearMessages() { announce(''); announce('', true); }
  function setBusy(value) { app.busy = value; content.setAttribute('aria-busy', String(value)); if (value) { app.disabled.clear(); document.querySelectorAll('button, input, textarea, select').forEach(el => { app.disabled.set(el, el.disabled); el.disabled = true; }); } else { app.disabled.forEach((disabled, el) => { if (el.isConnected) el.disabled = disabled; }); app.disabled.clear(); } }
  function stopPolling() { if (app.poll) clearTimeout(app.poll); app.poll = null; }
  async function api(path, body) {
    const options = { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } };
    if (body !== undefined) { options.method = 'POST'; options.headers['Content-Type'] = 'application/json'; options.headers['X-CSRF-Token'] = app.bootstrap.csrf; options.body = JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); } catch (_) { const e=new Error('无法确认本次操作的响应。请恢复连接并读取最新状态；不会自动重发。');e.uncertain=body!==undefined;throw e; }
    let data; try { data = await response.json(); } catch (_) { const e=new Error(`本地服务返回了无法读取的响应（HTTP ${response.status}）。请读取最新状态。`);e.uncertain=body!==undefined;throw e; }
    if (!response.ok) { const message = typeof data.error === 'string' ? data.error : data.error?.message || data.message || `请求未完成（HTTP ${response.status}）`; const e = new Error(message); e.status = response.status; throw e; }
    return data;
  }
  function pathFor(state = app.state) { return `/api/cases/${encodeURIComponent(state.id)}`; }
  function rememberCase(state) { const entry = { id: state.id, label: state.label, stage: state.stage, demo: state.demo, created_at:state.created_at, updated_at:state.updated_at, workspace_id:state.workspace_id||'default', record_type:state.record_type||'UNCLASSIFIED' }; const index = app.bootstrap.cases.findIndex(item => item.id === state.id); if (index >= 0) app.bootstrap.cases[index] = entry; else app.bootstrap.cases.unshift(entry); renderCaseSelect(); }
  function selectHash(id) { history.replaceState(null, '', `${location.pathname}${location.search}${id ? `#case=${encodeURIComponent(id)}` : `#workspace=${encodeURIComponent(app.workspace)}`}`); }
  function idFromHash() { const match = location.hash.match(/^#case=(.+)$/); try { return match ? decodeURIComponent(match[1]) : ''; } catch (_) { return ''; } }
  async function createCase(mode) {
    if (app.busy) return; clearMessages(); setBusy(true);
    try { const state = await api('/api/cases', { mode, workspace_id:app.workspace }); app.state = state; app.selectedRun = null; app.sourceDraft = ''; app.sourceName = 'input.py'; rememberCase(state); selectHash(state.id); render(); }
    catch (e) { announce(e.message, true); }
    finally { setBusy(false); }
  }
  async function createModeDemo(){
    if(app.busy)return;clearMessages();setBusy(true);
    try{const state=await api('/api/mode-demo',{workspace_id:app.workspace});app.state=state;rememberCase(state);selectHash(state.id);render();}
    catch(e){announce(e.message,true);}finally{setBusy(false);}
  }
  async function loadCase(id, quiet = false) {
    if (!quiet && app.busy) return; stopPolling(); const token = ++app.viewToken; if (!quiet) { clearMessages(); setBusy(true); }
    try { const state = await api(`/api/cases/${encodeURIComponent(id)}`); if (token !== app.viewToken) return; if(quiet&&['running','queued'].includes(app.state?.job?.status)&&state.job?.status==='completed'&&state.runs?.length)app.completedHere.add(state.runs.at(-1).run_id); app.state = state; app.workspace=state.workspace_id||'default'; if (!quiet) { app.selectedRun = null; app.sourceDraft = ''; app.sourceName = state.import_preview?.source?.name || 'input.py'; selectHash(id); } rememberCase(state); render(); return state; }
    catch (e) { if (token === app.viewToken) { announce(e.message, true); if (quiet) schedulePoll(); } }
    finally { if (!quiet) setBusy(false); }
  }
  async function refreshNovice(){const previous=app.state;const current=await loadCase(previous.id);if(current){window.PhotonGuardNovice.settled(previous,app.bootstrap.service_identity?.data_root);render();announce('已读取最新状态；没有重发操作。请核对已返回结果，仍无新记录时可主动整理，重复旧版本由后台拒绝。');}}
  async function mutate(type, data = {}) {
    if (app.busy || !app.state) return; clearMessages(); stopPolling(); setBusy(true); const id = app.state.id; const previous=app.state;const scope=app.bootstrap.service_identity?.data_root;if(previous.novice)window.PhotonGuardNovice.begin(previous,scope,type);
    try { const state = await api(`${pathFor()}/action`, { type, ...data, expected_revision: app.state.revision }); if (app.state?.id !== id) return;if(previous.novice){window.PhotonGuardNovice.settled(previous,scope);if(['novice-material','novice-pause'].includes(type))window.PhotonGuardNovice.saved(previous,scope);} app.state = state; if (state.id !== id) { app.workspace=state.workspace_id||'default'; selectHash(state.id); app.selectedRun = null; app.sourceDraft = ""; } rememberCase(state); render(); if (type === 'context') announce(state.next_action?.kind === 'context' ? '已保存已有背景；仍有缺项。可以保留未知并暂停，不需要猜测。' : '背景已保存。下一步只整理已有材料；不需要猜测缺失参数。'); if (type === 'task') announce('任务草稿已保存；尚未视为你已确认。'); if (type === 'confirm') announce('你已明确确认并锁定这份任务。接下来查看需求与脚本的差异，再决定是否运行。'); if (type === 'apply') announce('你已批准应用这一次受限修改。修改后的规范化配方仍需要真实 Meep 重验。'); return true; }
    catch (e) {
      if(previous.novice&&e.status&&e.status<500)window.PhotonGuardNovice.settled(previous,scope);
      if(e.uncertain||(e.status===409&&/版本.*(过期|变化|更新)/.test(e.message))){
        try{app.state=await api(`/api/cases/${encodeURIComponent(id)}`);rememberCase(app.state);render();announce(e.uncertain?'响应中断，已读取最新记录。没有自动重发；请核对结果，未保存的草稿可在本页恢复。':'这份工作已在别处更新。已读取最新记录，本标签页草稿保留，请核对差异后再保存。',true);}
        catch(refreshError){render();announce(`尚未核对到最新记录；没有自动重发。请恢复连接后重新读取。${refreshError.message}`,true);}
      }else{announce(e.message,true);schedulePoll();}return false;
    }
    finally { setBusy(false); }
  }
  function schedulePoll() { stopPolling(); const s = app.state; if (!s || (!['running', 'queued'].includes(s.job?.status) && !['CHECKING','DIAGNOSING','REVERIFYING'].includes(s.pipeline?.status))) return; const id = s.id; app.poll = setTimeout(() => { app.poll = null; if (app.state?.id === id && !app.busy) loadCase(id, true); else schedulePoll(); }, 2000); }
  function goHome() { if (app.busy) return; if (!app.bootstrap) return boot(); stopPolling(); ++app.viewToken; app.state = null; app.selectedRun = null; selectHash(''); clearMessages(); render(); }
  function spaceCases(){return (app.bootstrap?.cases||[]).filter(c=>(c.workspace_id||'default')===app.workspace);}
  function capacityFull(){return spaceCases().length>=32;}
  function caseLabel(c){return `${c.id.slice(0,8)} · ${c.record_type==='SIMULATED_AI_USER'?'AI模拟':c.demo?'合成演示':'未分类'} · ${c.label||'未命名'} · ${(c.created_at||'').slice(0,10)}`;}
  function renderSpaces(){
    const select=$('workspace-select');select.replaceChildren();
    for(const w of app.bootstrap?.workspaces?.items||[{id:'default',label:'原有工作区'}]){const option=n('option','',w.label);option.value=w.id;select.append(option);}select.value=app.workspace;
    $('workspace-capacity').textContent=`${spaceCases().length}/32 个案例${capacityFull()?' · 已满，请新建或切换工作区':''}`;
    $('new-workspace').disabled=(app.bootstrap?.workspaces?.items?.length||1)>=8;
  }
  async function createWorkspace(){
    if(app.busy)return;clearMessages();setBusy(true);
    try{const result=await api('/api/workspaces',{label:$('workspace-name').value});app.bootstrap=await api('/api/bootstrap');app.workspace=result.id;app.state=null;selectHash('');$('workspace-name').value='';render();announce('已创建空工作区；原有案例和全部证据保留。');}catch(e){announce(e.message,true);}finally{setBusy(false);}
  }
  function metadataPanel(s){
    const name=n('input');name.value=s.label;name.maxLength=120;name.setAttribute('aria-label','案例显示名称');
    const kind=n('select');kind.setAttribute('aria-label','案例记录类型');for(const [v,t] of [['UNCLASSIFIED','未分类（不表示真人）'],['SIMULATED_AI_USER','AI模拟试用'],['SYNTHETIC_DEMO','合成演示']]){const o=n('option','',t);o.value=v;kind.append(o);}kind.value=s.record_type||'UNCLASSIFIED';
    return detail('案例名称与记录类型',`${s.id.slice(0,8)} · ${(s.created_at||'').slice(0,10)}`,append(n('div'),p(`工作区案例ID：${s.id}；物理任务ID：${s.task?.case_id||'未锁定'}`),name,kind,button('保存显示信息',()=>mutate('case-metadata',{label:name.value,record_type:kind.value}),'secondary small'),p('只修改显示信息；任务锁、原始报告和运行证据保持原样。')));
  }
  function renderCaseSelect() { renderSpaces(); const select = $('case-select'); select.replaceChildren(n('option', '', '选择工作记录')); select.firstChild.value = ''; for (const item of spaceCases()) { const option = n('option', '', caseLabel(item)); option.value = item.id; select.append(option); } select.value = app.state?.id || ''; }
  function renderSteps() { const s = app.state;
    if (s?.repair_trial || s?.three_step) {
      const current = s.adapter_flow?(s.adapter_flow.repair_result||s.adapter_flow.diagnosis&&!s.adapter_flow.repair_card?2:s.adapter_flow.mode_lock?1:0):!s.approval ? 0 : s.repair_result ? 2 : 1;
      const initialComplete=!s.repair_result&&!s.diagnosis&&s.pipeline?.phase==='initial'&&['RESULT','NO_PATCH'].includes(s.pipeline?.status)&&s.job?.status==='completed'&&s.runs?.length;
      const shownCurrent=initialComplete?2:current;
      const names=s.novice?['确认摘要','计算与检查','查看曲线和结果']:['确认需求','查看问题与建议','一次批准，自动复验'];
      $('steps').replaceChildren(...names.map((text,i)=>{const li=n('li',i===shownCurrent?'active':'');li.append(n('span','step-number',String(i+1)),n('span','step-text',text));return li;}));return;
    } const kind = s?.next_action?.kind; let index = KIND_STEP[kind] ?? -1; if (kind === 'paused') index = -1; if ((kind === 'run' || kind === 'wait') && s?.runs?.length) index = 6; const completed = [s?.context_reviewed && !(s?.missing || []).some(x => x.startsWith('context.')), s?.task_reviewed && !(s?.missing || []).some(x => !x.startsWith('context.')) && !s?.readiness?.task_problem, Boolean(s?.candidate && s?.import_preview?.status === 'EXTRACTED'), Boolean(s?.approval), (s?.runs || []).some(run => run.solver_kind === 'REAL_MEEP' && run.fdtd_runs > 0), (s?.candidate?.origin?.patch_round || 0) > 0, false]; $('steps').replaceChildren(...STEP_NAMES.map((name, i) => { const done = completed[i] && i !== index; const skipped = i === 5 && kind === 'report' && !completed[i]; const li = n('li', i === index ? 'active' : done ? 'done' : ''); if (i === index) li.setAttribute('aria-current', 'step'); append(li, n('span', 'step-number', done ? '✓' : skipped ? '−' : `0${i + 1}`), append(n('span', 'step-text', name), n('small', '', skipped ? '本次无已批准修改' : STEP_SUBS[i]))); return li; })); }
  function renderRuntime() { if (app.bootstrap.runtime?.workers_enabled === false) { $('runtime-badge').textContent = '仅查看记录 · 计算未启用'; return; } const available = app.bootstrap.runtime?.meep_available === true; const node = $('runtime-badge'); node.textContent = available ? '● Meep 计算可用' : '○ Meep 暂不可用'; node.className = `runtime-badge ${available ? 'available' : 'unavailable'}`; }
  function scopePanel() {
    const panel = n('section', 'scope-panel'); panel.setAttribute('aria-label', 'AI 与实验接口状态');
    const repair=app.bootstrap.repair_service;
    if(repair){
      append(panel,n('h3','',repair.live_enabled?'AI 分析已连接':'本地检查可用'),p('先确认独立需求，再查看诊断与具体修复；你批准一次后后台自动完成限定Meep复验。需求缺项或冲突时保存暂停。'));
      panel.append(info('使用已授权额度；历史请求与失败记录保留。'));
      for(const item of spaceCases().filter(c=>c.label?.startsWith('三步试用')))panel.append(button(item.label,()=>loadCase(item.id),'secondary'));
      if(app.bootstrap.mode_status?.experimental_enabled)panel.append(info(app.bootstrap.mode_status.ai?.live_enabled?'MPB模态/QPM实验：AI 分析已连接，可提出一项数值修复，批准后自动复验；规则版使用相同页面与工具。':'MPB模态/QPM实验：当前可用规则与物理检查；真实AI暂未启用。'),button('打开公开合成模态/QPM任务',createModeDemo,'secondary',capacityFull()));
      panel.append(button('新建薄膜核对任务',()=>createCase('own'),'secondary',capacityFull()));return panel;
    }
    const liveBound = app.bootstrap.intake?.adapter?.live_enabled === true;
    append(panel, append(n('div', 'disabled-feature'), button(liveBound ? 'AI 已连接' : 'AI 未连接', null, 'small', true), append(n('div'), n('h3', '', liveBound ? 'AI 资料整理' : '本地资料整理'), p(liveBound ? '此入口的 AI 仅处理已授权的教学材料，需点击后才发送。自己的数据请使用光学实验工作台。' : '此入口尚未连接 AI。你可以先保存资料并使用本地规则整理。'))));
    const batch = app.bootstrap.intake?.adapter?.batch;
    if (batch) panel.append(info(`本工作区累计 AI 请求 ${batch.requests_used ?? '未知'} 次。`));
    append(panel, append(n('div', 'experimental'), append(n('h3', '', '整理实验需求'), pill(liveBound ? '真实 AI · 受本轮额度限制' : '可先离线整理', 'neutral')), p('先录入独立需求，核对参数出处和缺项，再由你确认草稿。已授权教学资料可使用 AI，其他资料可先在本地整理。生成草稿不会批准修复或启动仿真。'), button('新建需求录入', () => createCase('own'), 'secondary',capacityFull())));
    return panel;
  }
  function renderHome() {
    $('topbar-label').textContent = '开始'; const fragment = document.createDocumentFragment();
    append(fragment, append(n('section', 'welcome-intro'), n('div', 'eyebrow', '薄膜仿真核对'), n('h1', '', '先弄清任务，再相信结果。'), p('告诉我们你想看什么。选择教学示例，或整理已有资料；核对后得到真实曲线、检查结果与可复跑配置。', 'lead')));
    const intro=n('section','card');append(intro,n('h2','','无需准备Python脚本'),p('先从有来源的练习卡开始，或粘贴自己的资料。核对任务摘要后，系统生成受支持模板并完成数值检查。'),button('开始薄膜教学示例',()=>createCase('novice-teaching'),'primary',capacityFull()),button('整理我的模型资料',()=>createCase('novice-specified'),'secondary',capacityFull()));fragment.append(intro);
    const archive=n('section','card');const archiveLink=n('a','button secondary','查看原设计证书与新设计探索');archiveLink.href='/research-certificate';append(archive,n('h2','','铌酸锂研究档案'),p('原数值报告、固定模型严格证书与三个新设计的实跑结果分别展示。打开档案不会启动计算。'),archiveLink);fragment.append(archive);
    const advanced=n('details');advanced.append(n('summary','','高级入口：检查已有Python脚本'));
    const grid = n('div', 'welcome-grid'); const demo = n('section', 'card demo-card');
    append(demo, n('div', 'card-kicker', '第一次使用 · 从完整示范开始'), append(n('div', 'demo-title-line'), n('h2', '', '一层薄膜，一次完整核对'), pill('合成教学示例', 'synthetic')), p('背景、任务说明与待检脚本都已备好。你将看到参数差异如何被发现、怎样审核修改，以及重验后的真实曲线。', 'card-copy'));
    const physics = n('div', 'mini-physics'); physics.setAttribute('aria-label', '空气中一层折射率 2、厚度 0.3 微米的薄膜示意图；不是仿真曲线');
    const wave = svg('svg', { viewBox: '0 0 500 117', class: 'wave-svg', 'aria-hidden': 'true', preserveAspectRatio: 'none' });
    wave.append(svg('path', { d: 'M0 62 Q12 38 24 62 T48 62 T72 62 T96 62 T120 62 T144 62 T168 62 T192 62 L220 62 M280 62 Q292 44 304 62 T328 62 T352 62 T376 62 T400 62 T424 62 T448 62 T472 62 T500 62', fill: 'none', stroke: '#7fa891', 'stroke-width': '1.2' }));
    append(physics, wave, n('div', 'air', '空气 · 正入射'), append(n('div', 'film', 'n = 2'), n('small', '', '0.3 μm')), n('div', 'air', '空气 · 透射')); demo.append(physics);
    const facts = n('dl', 'demo-facts'); [['波段', '1.3–1.7 μm'], ['任务材料', '独立合成说明'], ['采样', '41 个频率点']].forEach(([key, value]) => append(facts, append(n('div'), n('dt', '', key), n('dd', '', value))));
    append(demo, facts, button('开始引导演示  →', () => createCase('demo'), 'full',capacityFull()), p('示例使用合成教学资料。运行前请核对参数与计算计划。', 'quiet-note'));
    const own = n('section', 'card own-card'); append(own, n('div', 'own-icon', '＋'), n('div', 'card-kicker', '使用你自己的材料'), n('h2', '', '从手头的项目开始'), p('还没有完整参数也没关系。先描述背景与目标，知道的填上，不知道的留空。', 'card-copy')); const list = n('ul', 'material-list'); ['设计说明、老师给的任务或材料记录', '每个参数的独立出处', '当前支持范围内的 Meep Python 脚本'].forEach(text => list.append(n('li', '', text))); append(own, list, info('需要资料时，可以随时选择「资料没有 / 暂不知道」。系统会暂停，不替你猜答案。'), button('使用自己的材料  →', () => createCase('own'), 'secondary',capacityFull()));
    append(grid, demo, own); advanced.append(grid);fragment.append(advanced);
    const principles = n('section', 'principles'); [['01', '先确认意图', '任务来自独立材料，不从待检脚本倒推。'], ['02', '保留你的决定', '确认任务、批准修改都需要你明确操作。'], ['03', '只展示真实证据', '运行状态、曲线和报告均来自本地实际结果。']].forEach(([number, title, text]) => append(principles, append(n('div', 'principle'), n('span', 'principle-number', number), append(n('div'), n('strong', '', title), text)))); fragment.append(principles);
    if (spaceCases().length) { const saved = n('section', 'card'); append(saved, n('h3', '', '继续本机保存的工作')); spaceCases().slice(0, 8).forEach(item => append(saved, append(n('div', 'run-row'), append(n('div', 'run-copy'), n('strong', '', caseLabel(item)), n('small', '', `${item.demo ? '合成演示' : '自己的材料'} · ${item.stage}`)), button('继续', () => loadCase(item.id), 'secondary small')))); fragment.append(saved); }
    append(fragment, scopePanel()); content.replaceChildren(fragment);
  }
  function actionHeader(title, subtitle, icon = '↗') { return append(n('div', 'action-card-header'), n('div', 'action-icon', icon), append(n('div'), n('h2', '', title), p(subtitle))); }
  function pauseButton(beforePause) { return button('资料没有 / 暂不知道', async () => { if (beforePause && !await beforePause()) return; await mutate('pause', { reason: '资料没有/暂不知道' }); }, 'quiet'); }
  function footer(primary, allowPause = true, beforePause) { const f = n('div', 'action-footer'); append(f, primary); if (allowPause) f.append(pauseButton(beforePause)); return f; }
  function contextPanel(s) {
    const card = n('section', 'card action-card'); append(card, actionHeader('先告诉我这份工作的背景', '当前只做材料整理，不要求你推导或猜测参数', '01'), p('这一步是整理你已有的设计说明或材料记录，供后续技术核对。你不需要计算或猜测缺失参数。', 'action-detail'));
    if (s.demo) card.append(info('这里预填的是明确标记的合成背景。请读一遍，再保存进入下一步；这些内容不代表你的真实身份、项目或测量。'));
    const fields = n('div', 'field-grid'); const inputs = {}; const unknownInputs = {};
    const placeholders = { background: '例如：课程设计中的一层无损薄膜；正在复现一份已有说明', goal: '例如：核对说明与脚本是否一致，并检查反射率 / 透射率', role: '例如：我负责整理材料和复现，不确定的地方需要保留', materials: '例如：任务书第 2 页、材料记录、现有脚本；没有就留空', unknowns: '例如：厚度出处还没找到、物理单位不清楚；不要猜测', parameter_source: '例如：任务书第 2 页指定 n 与厚度，附表指定波段' };
    for (const [key, label] of Object.entries(FIELD_LABELS)) { const field = n('label', `field ${['background', 'goal'].includes(key) ? 'wide' : ''}`); const input = n('textarea'); input.rows = ['background', 'goal'].includes(key) ? 2 : 3; input.value = typeof s.context?.[key] === 'string' ? s.context[key] : ''; input.placeholder = placeholders[key]; input.maxLength = 8000; input.id = `context-${key}`; inputs[key] = input; append(field, n('span', 'field-label', label), input); if (key !== 'unknowns') { const unknown = n('input'); unknown.type = 'checkbox'; unknown.checked = (s.context_unknown_fields || []).includes(key); unknown.id = `unknown-${key}`; unknownInputs[key] = unknown; const choice = append(n('label', 'unknown-choice'), unknown, n('span', '', '暂不知道 / 资料里没有')); const wrapper = n('div', field.className); field.className = 'field'; append(wrapper, field, choice); fields.append(wrapper); } else fields.append(field); }
    const saveContext = () => { const context = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()])); const unknown_fields = Object.entries(unknownInputs).filter(([, input]) => input.checked).map(([key]) => key); return mutate('context', { context, unknown_fields }); }; append(card, fields, p('勾选「暂不知道」会明确保留缺项，即使文本框中写了部分说明也不会当作已确认。暂停时会先保存这里的文字和未知标记。', 'quiet-note'), footer(button('保存背景，整理已有任务  →', saveContext), true, saveContext)); return card;
  }
  function taskSummary(task) {
    const t = task || {}; const layerText = Array.isArray(t.layers) ? t.layers.map((l, i) => `第 ${i + 1} 层：n = ${readable(l?.n)}；厚度 ${readable(l?.thickness_um)} μm`).join('\n') : '未提供';
    const entries = [['物理假设', t.physics ? `${readable(t.physics.dimensions)} 维 · 入射角 ${readable(t.physics.angle_deg)}° · 无损 ${readable(t.physics.lossless)}` : null], ['长度单位', t.units_um == null ? null : `1 仿真单位 = ${t.units_um} μm`], ['薄膜层', layerText], ['入射 / 出射介质', t.physics ? `n = ${readable(t.physics.n_incident)} / ${readable(t.physics.n_exit)}` : null], ['波长范围', Array.isArray(t.wavelength_um) ? `${t.wavelength_um.map(readable).join(' 至 ')} μm` : null], [t.sampling ? '等波长实际DFT点数（无插值）' : '频率采样点数', t.nfreq]];
    const grid = n('dl', 'summary-grid'); entries.forEach(([key, value]) => append(grid, append(n('div', 'summary-item'), n('dt', '', key), n('dd', value == null || String(value).includes('未提供') ? 'null-value' : '', readable(value))))); return grid;
  }
  function readinessBox(s) { const problems = [...(Array.isArray(s.missing) ? s.missing : []), s.readiness?.task_problem, s.readiness?.provenance_problem].filter(Boolean); if (!problems.length) return null; const names = { 'physics.dimensions': '仿真维度', 'physics.angle_deg': '入射角', 'physics.lossless': '是否无损', 'physics.dispersive': '是否存在色散', 'physics.isotropic': '是否各向同性', 'physics.mu': '相对磁导率', 'physics.n_incident': '入射介质折射率', 'physics.n_exit': '出射介质折射率', units_um: '物理长度单位', nfreq: '采样频点数', wavelength_um: '波长范围', layers: '薄膜层信息', sources: '独立参数来源' }; const texts = [...new Set(problems.map(value => { if (typeof value !== 'string') return readable(value.reason || value); if (value.startsWith('context.')) return FIELD_LABELS[value.slice(8)] || value; const match = value.match(/^layers\.(\d+)\.(n|thickness_um)$/); return match ? `第 ${Number(match[1]) + 1} 层${match[2] === 'n' ? '折射率' : '厚度'}` : names[value] || value; }))]; const list = n('ul', 'missing-list'); texts.forEach(text => list.append(n('li', '', text))); const box = info('仍有资料缺项或验证条件未满足。你可以先填写有来源的部分，其他保留未知。', 'warning'); append(box, detail('查看缺项与停止原因', `${texts.length} 项记录`, list), p('没有资料时可以暂停。请勿从待检脚本回填任务来消除差异。')); return box; }
  async function readFile(file, limit, extension) { if (!file) return null; if (!file.name.toLowerCase().endsWith(extension)) throw new Error(`请选择 ${extension} 文件。`); if (file.size > limit) throw new Error(`文件超过 ${limit / 1024} KiB 限制，请精简后重试。`); let text; try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); } catch (_) { throw new Error('文件不是有效的 UTF-8 文本，请使用 UTF-8 编码另存后重试。'); } return text; }
  function fileControl(label, extension, limit, onRead) { const box = n('label', 'upload-control'); const input = n('input'); input.type = 'file'; input.accept = extension; input.addEventListener('change', async () => { try { clearMessages(); const file = input.files[0]; const text = await readFile(file, limit, extension); if (text !== null && input.isConnected) onRead(text, file.name); } catch (e) { announce(e.message, true); } }); append(box, n('span', '', label), input, n('small', '', `UTF-8 · 最大 ${limit / 1024} KiB`)); return box; }
  function parseTask(text) { if (new TextEncoder().encode(text).length > 64 * 1024) throw new Error('任务 JSON 超过 64 KiB 限制。'); let task; try { task = JSON.parse(text); } catch (_) { throw new Error('任务 JSON 格式无法读取。请检查引号、逗号和括号；未知参数应保留为 null。'); } if (!task || typeof task !== 'object' || Array.isArray(task)) throw new Error('任务必须是一个 JSON 对象，不能是数组或普通文字。'); return task; }
  function nativeTaskEditor(initial) {
    const node = n('div'); const formHost = n('div'); const advancedEditor = n('textarea', 'code-editor'); advancedEditor.id = 'task-editor'; advancedEditor.spellcheck = false; advancedEditor.setAttribute('aria-label', '高级待审任务 JSON');
    const modeNotice = info('正在编辑高级 JSON，保存时将使用这里的内容。中文表单暂不可编辑；可先读回表单再核对。', 'warning'); modeNotice.hidden = true;
    const fields = []; let base = {}; let advancedDirty = false; let multi = false;
    const advanced = detail('高级：查看 / 编辑原生 JSON', '可选；多层任务使用此入口', append(n('div'), p('只填写有独立来源的参数。此处不是公共 14 字段语义合同。', 'card-copy'), modeNotice, advancedEditor, button('将 JSON 读回中文表单', () => { try { setTask(parseTask(advancedEditor.value)); announce('已读回表单，尚未保存。请继续核对。'); } catch (e) { announce(e.message, true); } }, 'secondary small')));
    function collectForm() { const task = JSON.parse(JSON.stringify(base)); for (const field of fields) { if (!field.changed) continue; let value = field.input.value === '' ? null : field.type === 'boolean' ? field.input.value === 'true' : field.type === 'text' ? field.input.value.trim() : Number(field.input.value); if (field.type === 'number' && value !== null && !Number.isFinite(value)) throw new Error(`${field.label} 不是有效数值，请留空或填写已有材料中的数值。`); if (field.path[0] === 'sources') { if (!task.sources.length) task.sources.push({ kind: 'independent-user-material', reference: '', note: '' }); } let target = task; for (const key of field.path.slice(0, -1)) target = target[key]; target[field.path[field.path.length - 1]] = value; } return task; }
    function setTask(task) {
      base = JSON.parse(JSON.stringify(task)); advancedDirty = false; modeNotice.hidden = true; advancedEditor.value = pretty(base); fields.length = 0; formHost.replaceChildren(); multi = !Array.isArray(base.layers) || base.layers.length !== 1;
      if (multi) { append(formHost, info('这份任务不是单层结构。为完整保留层数与原有字段，请使用下面的高级 JSON 入口；系统不会把多层任务简化成单层。', 'warning')); advanced.open = true; return; }
      if (!base.physics || typeof base.physics !== 'object') base.physics = {}; if (!Array.isArray(base.wavelength_um)) base.wavelength_um = [null, null]; if (!Array.isArray(base.sources)) base.sources = [];
      function section(title, note) { const block = n('section', 'task-form-section'); append(block, n('h3', '', title), p(note, 'field-note')); const grid = n('div', 'field-grid'); block.append(grid); formHost.append(block); return grid; }
      function add(grid, label, path, type = 'number', options) { let value = base; for (const key of path) value = value?.[key]; const field = n('label', 'field'); let input; if (type === 'boolean' || options) { input = n('select'); const choices = options || [['true', '是'], ['false', '否']]; const unknown = n('option', '', '暂不知道 / 材料未给出'); unknown.value = ''; input.append(unknown); choices.forEach(([v, text]) => { const option = n('option', '', text); option.value = String(v); input.append(option); }); input.value = value == null ? '' : String(value); } else { input = n(type === 'text' ? 'textarea' : 'input'); if (type === 'number') { input.type = 'number'; input.step = 'any'; input.inputMode = 'decimal'; } else { input.rows = 2; input.maxLength = 8000; } input.value = value == null ? '' : String(value); input.placeholder = type === 'text' ? '没有出处就留空，不使用脚本充当来源' : '未知时留空'; } input.id = `task-${path.join('-')}`; const item = { input, path, type, label, changed: false }; fields.push(item); input.addEventListener('input', () => { item.changed = true; if (!advancedDirty) advancedEditor.value = pretty(collectForm()); }); input.addEventListener('change', () => { item.changed = true; if (!advancedDirty) advancedEditor.value = pretty(collectForm()); }); append(field, n('span', 'field-label', label), input); grid.append(field); }
      let grid = section('01 · 薄膜与采样', '只抄录已有说明。输入留空时保留 null；下面不会替你换算或补全缺失参数。');
      add(grid, '折射率 n', ['layers', 0, 'n']); add(grid, '厚度（μm）', ['layers', 0, 'thickness_um']); add(grid, '1 Meep 长度单位对应多少 μm', ['units_um']); add(grid, base.sampling ? '等波长实际DFT点数（没有插值）' : '采样频点数', ['nfreq']); add(grid, '波长下限（μm）', ['wavelength_um', 0]); add(grid, '波长上限（μm）', ['wavelength_um', 1]);
      grid = section('02 · 明确的物理假设', '这几项必须由已有说明确认。看到「当前支持」不等于你的项目自动满足；不确定就保持未知。');
      add(grid, '仿真维度', ['physics', 'dimensions'], 'number', [[1, '1D（当前支持）'], [2, '2D（超出当前范围）'], [3, '3D（超出当前范围）']]); add(grid, '入射角（°）', ['physics', 'angle_deg']); add(grid, '是否无损', ['physics', 'lossless'], 'boolean'); add(grid, '是否存在色散', ['physics', 'dispersive'], 'boolean'); add(grid, '是否各向同性', ['physics', 'isotropic'], 'boolean'); add(grid, '相对磁导率 μ', ['physics', 'mu']); add(grid, '入射介质折射率', ['physics', 'n_incident']); add(grid, '出射介质折射率', ['physics', 'n_exit']);
      grid = section('03 · 独立参数来源', '写清资料名称和页码 / 段落，以及它给出了哪些参数。现有其他来源条目会完整保留。');
      add(grid, '来源名称、页码或段落', ['sources', 0, 'reference'], 'text'); add(grid, '资料明确给出的参数或说明', ['sources', 0, 'note'], 'text');
    }
    advancedEditor.addEventListener('input', () => { advancedDirty = true; modeNotice.hidden = false; fields.forEach(field => { field.input.disabled = true; }); });
    const getTask = () => advancedDirty || multi ? parseTask(advancedEditor.value) : collectForm(); append(node, formHost, advanced); setTask(initial || {}); return { node, getTask, setTask };
  }
  function taskPanel(s) {
    const card = n('section', 'card action-card'); append(card, actionHeader('把已有说明整理成独立任务', '原生 task.json · 本步只保存待审草稿', '02'), p('先核对已有任务与独立来源。表单不会从待检脚本倒推参数，也不会替你选择物理假设。没有资料就留空，或直接暂停。', 'action-detail'), readinessBox(s));
    if (s.demo) card.append(info('SYNTHETIC 演示任务来自随附的独立合成说明，已提供完整参数。预填内容只属于这个演示，不会成为你自己的项目默认值。'));
    const editor = nativeTaskEditor(s.task);
    card.append(fileControl('也可读取已有 task.json', '.json', 64 * 1024, text => { try { editor.setTask(parseTask(text)); announce('文件已读入表单 / 高级编辑区，尚未保存。请核对内容和参数来源。'); } catch (e) { announce(e.message, true); } }));
    const saveTask = () => { try { return mutate('task', { task: editor.getTask() }); } catch (e) { announce(`草稿尚未保存。${e.message}`, true); return false; } };
    append(card, editor.node, p('当前原生合同按频率等间隔采样；波长点由真实频率换算，不宣称等波长间隔。暂停时会先保存可读取的任务草稿。', 'quiet-note'), footer(button('保存任务草稿，继续  →', saveTask), true, saveTask)); return card;
  }
  function importPanel(s, unsupported = false) {
    const card = n('section', 'card action-card'); append(card, actionHeader(unsupported ? '这份输入还不能继续验证' : '读取待检 Meep 脚本', '只读 AST 解析 · 不执行你上传的 Python', '03'), p('读取器只识别当前支持的顺序式参考 / 目标通量模板。动态调用、未知分支或超出物理范围的脚本会被拒绝。读入成功也不等于通过检查。', 'action-detail'));
    if (!unsupported && s.import_preview?.status === 'UNSUPPORTED') append(card, info('上次解析未通过：脚本尚不属于当前支持的模板，没有执行任何 Python 或仿真。请检查以下原因，或保留资料后暂停。', 'warning'), pre(s.import_preview.unresolved || [])); if (unsupported) append(card, info(s.next_action?.detail || '当前输入超出支持范围，未执行仿真。可以暂停并保留现状。', 'warning'), s.import_preview ? pre(s.import_preview) : null);
    const editor = n('textarea', 'code-editor'); editor.id = 'source-editor'; editor.spellcheck = false; editor.setAttribute('aria-label', '待检 Meep Python 脚本'); editor.value = app.sourceDraft || s.source_text || ''; editor.addEventListener('input', () => { app.sourceDraft = editor.value; });
    if (s.demo) card.append(info('这是演示自带的待检脚本，包含人为设置的参数差异。系统会保留原文与行号，后续核对的是从它提取的规范化配方。'));
    card.append(fileControl('选择 Meep 脚本', '.py', 128 * 1024, (text, name) => { editor.value = text; app.sourceDraft = text; app.sourceName = name.split(/[\\/]/).pop(); const fileNameInput = $('source-name'); if (fileNameInput) fileNameInput.value = app.sourceName; announce('脚本已读入编辑区，尚未提交 AST 解析。'); }));
    if (s.trial_material) card.append(button('载入本次试用脚本（尚未解析或执行）', async () => {
      try { const material = await api('/api/closed-loop-example'); editor.value = material.source; app.sourceDraft = material.source; app.sourceName = material.name; document.querySelector('#source-name').value = material.name; }
      catch (e) { announce(e.message, true); }
    }, 'secondary small'));
    const nameInput = n('input'); nameInput.type = 'text'; nameInput.id = 'source-name'; nameInput.value = s.demo ? 'synthetic_demo.py' : app.sourceName; nameInput.addEventListener('input', () => { app.sourceName = nameInput.value; }); append(card, append(n('label', 'field'), n('span', 'field-label', '脚本文件名（不含路径，以 .py 结尾）'), nameInput)); const saveSource = (allowEmpty = false) => { const source = editor.value; if (!source && allowEmpty) return true; if (!source.trim()) { announce('请选择或粘贴要读取的 Meep 脚本。没有脚本时可先暂停。', true); return false; } if (new TextEncoder().encode(source).length > 128 * 1024) { announce('脚本超过 128 KiB 限制；内容尚未保存，当前编辑区已保留。', true); return false; } const name = nameInput.value; if (!/^[A-Za-z0-9_\u4e00-\u9fff][A-Za-z0-9_.\-\u4e00-\u9fff]{0,100}\.py$/.test(name) || name.includes('..')) { announce('脚本尚未保存。请把文件名改为不带路径或空格的 .py 名称；当前源码编辑区已保留。', true); return false; } return mutate('import', { source, name }); }; append(card, append(n('div', 'code-caption'), n('span', '', '待检源代码'), n('span', '', '仅支持 .py · 最大 128 KiB')), editor, p('暂停前会先保存当前源码并做只读 AST 解析。解析不支持的源码也会保留原文；不会执行 Python。', 'quiet-note'), footer(button('只读解析脚本  →', () => saveSource()), true, () => saveSource(true))); return card;
  }
  function confirmPanel(s) {
    const card = n('section', 'card action-card'); append(card, actionHeader('确认：这就是要核对的任务', '锁定独立任务后，参考不会跟随脚本错误改变', '04'), p('确认表示你认可这份 JSON 对意图的描述。它不是数字签名、身份认证，也不会直接开始仿真。', 'action-detail'), taskSummary(s.task), readinessBox(s));
    append(card, detail('完整独立任务及出处', '确认前可展开核对', pre(s.task)), info('上传脚本只做只读解析。之后的 PASS / FAIL 只属于记录的规范化配方，不能代表任意原始 Python 脚本通过。'));
    const approve = n('input'); approve.type = 'checkbox'; approve.id = 'task-approval'; const run = button('确认并锁定这份任务  →', () => mutate('confirm', { approve: true }), '', true); approve.addEventListener('change', () => { run.disabled = !approve.checked; });
    append(card, append(n('label', 'check-approval'), approve, n('span', '', s.demo ? '我已阅读独立合成任务及参数来源，确认用它演示后续核对。它不代表我的真实项目。' : '我已阅读任务及独立参数来源，确认以上内容准确描述这次要核对的任务。')), footer(run)); return card;
  }
  function comparison(s) {
    if (!Array.isArray(s.comparison) || !s.comparison.length) return n('div', 'empty-state', '当前还没有需求 / 代码对照结果。系统不会以空对照宣称通过。');
    const list = n('div', 'compare-list'); for (const row of s.comparison) { const item = n('article', `compare-row ${row.match === false ? 'mismatch' : ''}`); append(item, append(n('h3', '', readable(row.field)), pill(row.match === true ? '一致' : row.match === false ? '存在差异' : '待核对', row.match === false ? 'INCONCLUSIVE' : row.match === true ? 'PASS' : 'neutral')), append(n('div', 'compare-values'), append(n('div'), n('span', '', '独立任务要求'), readable(row.required)), append(n('div'), n('span', '', '当前规范化配方'), readable(row.actual))));
      if (row.locations && (!Array.isArray(row.locations) || row.locations.length)) append(item, n('div', 'source-locations', `原始源码位置：${locationText(row.locations)}`)); if (row.source_note) append(item, p(row.source_note, 'quiet-note')); if (row.script_kind) append(item, n('div', 'source-locations', `当前配方保存形式：${readable(row.script_kind)} = ${readable(row.script_value)}`));
      if (row.consequence) append(item, p(row.consequence, 'consequence')); list.append(item);
    } return list;
  }
  function locationText(locations) { if (Array.isArray(locations)) return [...new Set(locations.map(locationText))].join('；'); if (locations && typeof locations === 'object') { const line = locations.line ?? locations.lineno ?? locations.start_line; const end = locations.end_line ?? locations.end_lineno; if (line) return `${locations.file || locations.filename || ''}${locations.file || locations.filename ? ' · ' : ''}第 ${line}${end && end !== line ? `–${end}` : ''} 行${locations.column != null ? `，列 ${locations.column}` : ''}`; return Object.entries(locations).map(([key, value]) => `${key}: ${readable(value)}`).join('；'); } return readable(locations); }
  function runPanel(s) {
    const rerun = (s.runs || []).length > 0; const card = n('section', 'card action-card'); append(card, actionHeader(rerun ? '让修改后的配方重新接受验证' : '先看差异，再启动真实运行', rerun ? '新的运行记录 · 旧证据保留' : '任务已确认 · 需求与脚本逐项比较', rerun ? '07' : '05'));
    append(card, p(rerun ? '修改已应用不等于问题已解决。现在用相同的独立任务与完整验收流程重验，生成新的结果和证据。' : '下面的差异来自独立任务与脚本解析结果。你可以先看源码位置和物理含义，再决定开始运行。', 'action-detail'), comparison(s));
    append(card, info('每次验证执行四组参考 / 目标配对：原设置、网格 ×1.5、运行时间 ×2、PML ×1.5。使用真实 Meep FDTD，并与独立 tmm 参考比较；不会执行上传 Python。'));
    const available = app.bootstrap.runtime?.meep_available === true; if (!available) card.append(info('本地服务未检测到可用 Meep。任务与脚本可以继续整理，但本次不能生成真实曲线或 PASS。请按项目说明准备运行环境后刷新。', 'warning'));
    append(card, footer(button(rerun ? '启动真实 Meep 重验  →' : '启动真实 Meep 运行  →', () => mutate('run'), '', !available)), p('没有模拟进度条。运行过程中只显示后端确认的真实状态；耗时取决于本机环境。', 'quiet-note')); return card;
  }
  function waitPanel(s) { const card = n('section', 'card action-card'); append(card, actionHeader('真实计算正在进行', '状态来自本地服务 · 每 2 秒查询一次', '↻')); const job = n('div', 'job-state'); append(job, n('div', 'running-icon'), append(n('div'), n('h3', '', STATUS[s.job?.status] || '等待后端结果'), p('正在执行真实 Meep 配对计算与验收。没有结果时不会生成曲线、提前标记通过或估算完成百分比。'))); append(card, job, p(`本次阶段：${readable(s.job?.kind)}${s.job?.run_id ? ` · 运行编号：${s.job.run_id}` : ''}`, 'quiet-note'), info('可以保留页面等待，或稍后重新打开这条本地工作记录。请让本地服务进程继续运行。')); return card; }
  function proposePanel(s) { const card = n('section', 'card action-card'); append(card, actionHeader('先读结果，再生成受限建议', '本地规则建议 · 当前参数保持不变', '06'), p('建议只针对当前运行证据。每次最多一个受限修改；你将看到具体改动，明确批准后才会应用。', 'action-detail'), latestResult(s), comparison(s), footer(button('根据本次证据生成建议  →', () => mutate('propose')))); return card; }
  function proposalSummary(s) { const box = n('div', 'proposal-summary'); const changes = s.proposal?.changes || []; if (changes.length !== 1) return info('没有可显示的单项建议，请查看原始提案。', 'warning'); const c = changes[0], path = c.path || []; let label = path.join('.'), reason = '该建议仍需你的确认，以及全量真实重验。'; if (path[0] === 'layers') { const kind = s.candidate?.layers?.[path[1]]?.material_kind; label = `第 ${path[1] + 1} 层 · ${path[2] === 'material_value' ? kind === 'epsilon' ? '介电常数 ε' : '折射率 n' : '厚度（μm）'}`; reason = path[2] === 'material_value' ? `独立任务要求 n = ${readable(s.task?.layers?.[path[1]]?.n)}。在当前非磁、无损模型中 ε = n²；此修改恢复任务材料，但不会改写原始脚本。` : '恢复独立任务要求的厚度。厚度影响相位积累和干涉峰谷的位置。'; } else { const labels = { reference_amplitude: '参考运行源振幅', subtract_incident: '扣除入射场', after_sources: '源结束后运行时间', resolution: '网格分辨率' }; label = labels[path[path.length - 1]] || label; reason = path[0] === 'numerics' ? '根据本次实际敏感性 / 参考误差证据，在固定资源预算内修改数值设置。是否有效需要重新运行检查。' : '恢复正确的参考配对 / 反射通量处理，再用完整流程验证。'; } append(box, n('h3', '', label), n('div', 'proposal-change', `${readable(c.old)} → ${readable(c.new)}`), p(reason)); return box; }
  function applyPanel(s) {
    const card = n('section', 'card action-card'); append(card, actionHeader('这一次修改，需要你明确同意', '审核建议 → 明确批准 → 再做真实重验', '06'), p('建议来自当前证据与固定规则。不要仅因它能让检查通过就接受；请核对修改是否恢复了你独立确认的物理任务或数值流程。', 'action-detail'));
    append(card, info('应用只修改受限的规范化候选配方，不覆盖原始脚本、独立任务或已有运行证据。'), proposalSummary(s), detail('完整修改建议 JSON', '保留原始字段与哈希', pre(s.proposal || {})));
    const approve = n('input'); approve.type = 'checkbox'; approve.id = 'repair-approval'; const apply = button('批准并应用这一次修改  →', () => mutate('apply', { approve: true }), '', true); approve.addEventListener('change', () => { apply.disabled = !approve.checked; });
    append(card, append(n('label', 'check-approval'), approve, n('span', '', '我已阅读具体修改，确认它符合已锁定的任务，并批准仅应用这一次建议。应用后仍需真实 Meep 重验。')), footer(apply)); return card;
  }
  function pausedPanel(s) { const card = n('section', 'card action-card'); append(card, n('div', 'pause-symbol', 'Ⅱ'), n('h2', '', '先停在这里，已有内容已保留'), p('缺少资料是可以接受的。这里不会替你补数值、猜意图，也不会为了继续而改写任务。', 'action-detail'), info(`暂停原因：${readable(s.paused_reason)}`, 'warning'), p('拿到材料，或想重新查看下一步时，再恢复这份工作。恢复本身不会执行仿真或批准修改。', 'card-copy'), footer(button('恢复这份工作  →', () => mutate('resume')), false)); return card; }
  function safeUrl(value, prefix) { if (typeof value !== 'string') return null; try { const url = new URL(value, location.href); if (url.origin !== location.origin || !url.pathname.startsWith(prefix)) return null; return url.href; } catch (_) { return null; } }
  function link(text, url, cls = 'button secondary small') { const a = n('a', cls, text); a.href = url; a.target = '_blank'; a.rel = 'noopener'; return a; }
  function latestResult(s) { const run = s.runs?.[s.runs.length - 1]; if (!run) return n('div', 'empty-state', '本次还没有完成的运行证据。'); const box = n('div'); append(box, append(n('div', 'result-topline'), n('h3', '', '最近一次运行记录'), status(run.status)), p(`${app.completedHere.has(run.run_id)?'本页面刚完成':'已保存的运行证据'} · ${run.created_at || run.run_id} · ${readable(run.solver_kind)} · FDTD 次数 ${readable(run.fdtd_runs)}`, 'quiet-note')); const url = safeUrl(run.report_url, '/reports/'); if (url) append(box, append(n('div', 'download-row'), link('查看这次完整报告 ↗', url))); return box; }
  function evidenceFiles(caseId, runId) { const host = n('div'); const box = detail('下载本次原始证据', '按运行隔离 · 只读文件', host); let loaded = false; box.addEventListener('toggle', async () => { if (!box.open || loaded) return; loaded = true; host.replaceChildren(p('正在读取允许下载的证据文件…', 'card-copy')); try { const data = await api(`/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/files`); const files = Array.isArray(data.files) ? data.files : []; host.replaceChildren(); for (const file of files) { if (typeof file.name !== 'string' || file.name.includes('..') || file.name.includes('\\') || file.name.startsWith('/')) continue; const url = `/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/files/${file.name.split('/').map(encodeURIComponent).join('/')}`; const a = link(file.name, url, 'evidence-file'); a.removeAttribute('target'); a.download = file.name.split('/').pop(); append(host, append(n('div', 'evidence-file-row'), a, n('span', '', `${readable(file.bytes)} bytes`))); } if (!host.childNodes.length) host.append(p('没有可下载的文件。', 'card-copy')); } catch (e) { host.replaceChildren(info(e.message, 'warning')); loaded = false; } }); return box; }
  function reportPanel(s) {
    const card = n('section', 'card action-card'); append(card, actionHeader(({ PASS: '结果已经留下证据', FAIL: '当前问题尚未解决', INCONCLUSIVE: '当前证据仍不足', UNSUPPORTED: '本次超出支持范围' })[(s.runs?.find(run => run.run_id === app.selectedRun) || s.runs?.[s.runs.length - 1])?.status] || '尚未形成验收结果', '曲线、报告与运行记录可以逐一核对', '07'), p(({ PASS: '这次通过了记录的离散频点、物理假设与容差检查。它不是连续全波段或真实器件性能保证。', FAIL: '这次仍有未解决的问题。请查看失败检查与原始证据，不能将当前结果当作已通过。', INCONCLUSIVE: '本次证据不足，尚不能建立通过或失败的完整结论。请查看报告中的具体限制。', UNSUPPORTED: '本次输入超出验收范围。这里保留的是边界与停止证据，不是仿真通过结论。' })[(s.runs?.find(run => run.run_id === app.selectedRun) || s.runs?.[s.runs.length - 1])?.status] || '查看每次真实运行的记录与边界；没有可靠证据时不会声明通过。', 'action-detail'));
    const runs = s.runs || []; if (!runs.length) { card.append(n('div', 'empty-state', '后端尚未提供运行记录，因此没有曲线或报告。')); return card; }
    let selected = runs.find(run => run.run_id === app.selectedRun) || runs[runs.length - 1]; app.selectedRun = selected.run_id;
    if (runs.length > 1) { const field = n('label', 'field'); const select = n('select'); select.id = 'run-select'; runs.forEach((run, index) => { const option = n('option', '', `${index === 0 ? '首次运行' : `第 ${index + 1} 次运行`} · ${STATUS[run.status] || run.status} · ${run.run_id}`); option.value = run.run_id; select.append(option); }); select.value = selected.run_id; select.addEventListener('change', () => { app.selectedRun = select.value; render(); }); append(field, n('span', 'field-label', '选择要查看的证据'), select); append(card, field); }
    append(card, append(n('div', 'result-topline'), n('h3', '', 'R / T 光谱'), status(selected.status)));
    const metrics = n('div', 'result-metrics'); [['求解器', readable(selected.solver_kind)], ['真实 FDTD 次数', readable(selected.fdtd_runs)], ['记录状态', STATUS[selected.status] || readable(selected.status)]].forEach(([key, value]) => append(metrics, append(n('div', 'result-metric'), n('span', '', key), n('strong', '', value)))); card.append(metrics); card.append(p(`${app.completedHere.has(selected.run_id)?'本页面刚完成':'已保存的运行证据'} · ${selected.created_at || selected.run_id}。这是该次运行的记录，不代表此刻重新启动了计算。`, 'quiet-note'));
    card.append(p(`计算执行：已完成；数值检查：${selected.status}；设计目标：NOT_EVALUATED；证据来源：保存实跑。`),link('下载结果、数据与复跑配置',`${pathFor(s)}/runs/${encodeURIComponent(selected.run_id)}/bundle`));
    const chartHost = n('div'); chartHost.id = 'spectrum-host'; chartHost.append(n('div', 'empty-state', '正在读取这次运行的实际光谱数据…')); card.append(chartHost);
    const downloads = n('div', 'download-row'); const url = safeUrl(selected.report_url, '/reports/'); if (url) downloads.append(link('打开完整验收报告 ↗', url)); const rawUrl = `${pathFor(s)}/runs/${encodeURIComponent(selected.run_id)}/spectrum`; downloads.append(link('实际光谱 JSON ↗', rawUrl)); append(card, downloads, evidenceFiles(s.id, selected.run_id), p('实线为 Meep 数据；虚线为独立 tmm 参考。图上仅连接返回的实际采样点，不补点、不平滑。两档设置接近只说明本次敏感性较小，并不证明渐近收敛。', 'quiet-note'));
    const caseId = s.id, runId = selected.run_id; queueMicrotask(() => loadSpectrum(caseId, runId, chartHost)); return card;
  }
  function supportColumn(s) { const aside = n('aside', 'support-column'); const help = n('section', 'card help-card'); append(help, n('div', 'help-label', 'IN THIS STEP'), n('h3', '', '你不需要先成为仿真专家')); const terms = n('dl', 'help-terms'); const entries = ['context', 'task', 'paused'].includes(s.next_action?.kind) ? [['任务', '你本来希望仿真的对象与条件，由设计说明等独立材料决定。'], ['待检脚本', '描述当前实际怎么设置仿真。它可能写错，不能反过来定义正确答案。'], ['未知项', '没有来源就留空。暂停比猜一个看似合理的数值更可靠。']] : [['n 与 ε', '在当前无损、非磁性假设下，ε = n²。例如 n = 2 对应 ε = 4。'], ['R 与 T', 'R 是反射率，T 是透射率。它们是无量纲比例，不是场的振幅。'], ['独立参考', 'tmm 从已确认任务生成参考；不会追随待检脚本的错误。']]; entries.forEach(([term, definition]) => append(terms, n('dt', '', term), n('dd', '', definition))); help.append(terms); aside.append(help);
    const bounds = n('section', 'card help-card'); append(bounds, n('div', 'help-label', 'HONEST BOUNDARIES'), n('h3', '', '这次验证覆盖什么')); const list = n('ul', 'check-list'); ['1D z 方向，Ex 正入射', '线性、无损、无色散、各向同性', '空气入射 / 出射，本轮仅单膜', '仅认可模板的只读 AST 导入'].forEach(text => list.append(n('li', '', text))); append(bounds, list, n('div', 'help-divider'), p('斜入射、吸收、色散、基底、二维波导或任意 Python 不在此范围内。超出范围会停止，不会套用结论。')); aside.append(bounds); return aside; }
  function detail(title, meta, body, open = false) { const details = n('details', 'evidence'); details.open = open; append(details, append(n('summary', '', title), n('span', 'detail-meta', meta)), append(n('div', 'details-body'), body)); return details; }
  function sourceView(source) { if (!source) return n('div', 'empty-state', '尚未提供脚本。'); const box = n('div', 'source-view'); box.setAttribute('aria-label', '带行号的原始脚本'); source.split('\n').forEach((line, index) => { const row = n('div', 'source-line'); row.id = `source-line-${index + 1}`; append(row, n('span', 'source-number', index + 1), n('span', 'source-content', line || ' ')); box.append(row); }); return box; }
  function evidence(s) { const section = n('section', 'evidence-section'); append(section, append(n('div', 'section-heading'), n('h2', '', '随时查看：材料与证据'), n('span', '', '展开查看，不会触发修改'))); const context = n('dl', 'description-list'); Object.entries(FIELD_LABELS).forEach(([key, name]) => append(context, n('dt', '', name), n('dd', '', `${readable(s.context?.[key])}${(s.context_unknown_fields || []).includes(key) ? '（已明确标记：暂不知道 / 资料里没有）' : ''}`))); append(section, detail('背景与已有材料', s.demo ? 'SYNTHETIC' : '你的记录', context), detail('独立任务 task.json', s.approval ? '含确认记录' : '待确认', append(n('div'), taskSummary(s.task), pre(s.task), s.approval ? pre(s.approval) : null)));
    append(section, detail('原始脚本与 AST 提取', '源码原文 · 解析不会执行 Python', append(n('div'), sourceView(s.source_text), s.import_preview ? append(n('div'), n('h3', '', '解析预览'), pre(s.import_preview)) : null, s.candidate ? append(n('div'), n('h3', '', '当前规范化候选配方'), pre(s.candidate)) : null)));
    if (s.comparison?.length) section.append(detail('需求 / 代码对照', '包括来源行号与物理影响', comparison(s)));
    if (s.proposal) section.append(detail('本次受限修改建议', '批准情况以服务端记录为准', pre(s.proposal)));
    if (s.runs?.length) { const rows = n('div'); s.runs.forEach((run, i) => { const row = n('div', 'run-row'); append(row, status(run.status), append(n('div', 'run-copy'), n('strong', '', run.run_id), n('small', '', `${i === 0 ? '首次运行' : `第 ${i + 1} 次运行`} · ${readable(run.solver_kind)} · ${readable(run.fdtd_runs)} 次 FDTD`))); const url = safeUrl(run.report_url, '/reports/'); if (url) row.append(link('报告 ↗', url)); rows.append(row); }); section.append(detail('全部运行记录', `${s.runs.length} 份独立证据`, rows)); }
    if (s.job?.status === 'failed') section.append(detail('本次运行错误', '未完成的运行不等于 PASS', pre(s.job.error || s.job), true)); return section; }
  function renderCase() {
    const s = app.state;
    if(s.adapter_flow){
      $('topbar-label').textContent=s.label;content.replaceChildren(metadataPanel(s),window.PhotonGuardMode.create(s,{mutate}));return;
    }
    if(s.novice&&!s.approval){
      $('topbar-label').textContent=s.label;content.replaceChildren(metadataPanel(s),window.PhotonGuardNovice.create(s,{mutate,service:app.bootstrap.repair_service,scope:app.bootstrap.service_identity?.data_root,refresh:refreshNovice,createModeDemo}));return;
    }
    if (s.repair_trial || s.three_step) {
      $('topbar-label').textContent = s.label || '三步诊断';
      content.replaceChildren(metadataPanel(s),window.PhotonGuardRepair.create(s,{api,mutate,chart:spectrumChart,service:app.bootstrap.repair_service}));
      return;
    }
    const kind = s.next_action?.kind || 'context'; $('topbar-label').textContent = s.label || '当前工作'; const fragment = document.createDocumentFragment(); const heading = n('div', 'heading-line'); append(heading, append(n('div', 'case-heading-copy'), n('div', 'eyebrow', s.demo ? 'GUIDED SYNTHETIC DEMO' : 'YOUR MATERIALS · LOCAL WORKSPACE'), n('h1', '', s.next_action?.title || '一步一步核对这份仿真'), p(s.next_action?.detail || '只做当前需要的一步。未知项可以保留，已有材料不会丢失。', 'lead')), append(n('div', 'case-meta'), pill(s.demo ? '合成教学示例' : '自己的材料', s.demo ? 'synthetic' : 'neutral'), n('span', '', `版本 ${s.revision}`), button('切换 / 新建', goHome, 'quiet small mobile-home'))); fragment.append(heading);
    if (s.job?.status === 'failed') fragment.append(info(`真实运行未完成：${readable(s.job.error)}。未生成的结果不会被视为 PASS。`, 'error'));
    const panelMap = { context: contextPanel, task: taskPanel, import: importPanel, confirm: confirmPanel, run: runPanel, wait: waitPanel, propose: proposePanel, apply: applyPanel, report: reportPanel, paused: pausedPanel, unsupported: state => { const panel = state.readiness?.task_problem ? taskPanel(state) : importPanel(state, true); if (state.readiness?.task_problem) panel.prepend(info(readable(state.readiness.task_problem.reason || state.readiness.task_problem), 'warning')); return panel; } };
    const panel = (panelMap[kind] || (state => append(n('section', 'card action-card'), n('h2', '', '等待可识别的下一步'), p(`服务端返回了未知状态：${readable(state.next_action?.kind)}。未执行任何操作。`))))(s);
    if (!s.demo && !s.approval && !s.paused_reason && s.job?.status !== 'running') {
      fragment.append(window.PhotonGuardIntake.create(s, {
        api, demo: app.bootstrap.intake?.demo || '', adapter: app.bootstrap.intake?.adapter, isCurrent: id => app.state?.id === id,
        refresh: id => loadCase(id), accept: next => { app.state = next; rememberCase(next); render(); }
      }));
    }
    if (s.approval) {
      const reason = n('input'); reason.placeholder = '例如：需求提出者更新膜厚，来源为任务书v2';
      fragment.append(append(n('section','card'),n('h3','','需求要修改？保留旧记录并建立新版本'),reason,
        button('建立新需求版本',()=>mutate('derive-version',{reason:reason.value.trim()}),'secondary small')));
    }
    fragment.prepend(metadataPanel(s));append(fragment, append(n('div', 'work-layout'), panel, supportColumn(s)), evidence(s)); content.replaceChildren(fragment);
  }
  function render() { stopPolling(); renderSteps(); renderRuntime(); renderCaseSelect(); if (app.state) renderCase(); else renderHome(); schedulePoll(); }
  function svg(tag, attributes = {}) { const node = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value)); return node; }
  function svgText(text, attributes) { const node = svg('text', attributes); node.textContent = text; return node; }
  function spectrumChart(rows) {
    const fields = ['R', 'T', 'R_reference', 'T_reference']; const points = rows.filter(row => row && finite(row.wavelength_um) !== null).slice().sort((a, b) => a.wavelength_um - b.wavelength_um); const values = points.flatMap(row => fields.map(key => finite(row[key])).filter(value => value !== null));
    if (!points.length || !values.length) return n('div', 'empty-state', '实际响应中没有可绘制的有限数值。未生成替代曲线。');
    let xmin = points[0].wavelength_um, xmax = points[points.length - 1].wavelength_um; if (xmin === xmax) { xmin -= Math.max(Math.abs(xmin) * .01, .01); xmax += Math.max(Math.abs(xmax) * .01, .01); } const ymin = Math.min(0, ...values), ymax = Math.max(1, ...values); if (!Number.isFinite(xmax - xmin) || !Number.isFinite(ymax - ymin)) return n('div', 'empty-state', '实际数值范围过大，无法安全绘图；请下载原始数据。');
    const width = 800, height = 330, left = 57, top = 32, pw = 714, ph = 238; const x = value => left + (value - xmin) / (xmax - xmin) * pw; const y = value => top + ph - (value - ymin) / (ymax - ymin) * ph;
    const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart', role: 'img', 'aria-label': '实际 Meep 反射率与透射率，以及独立 tmm 参考，横轴为波长微米，纵轴为无量纲 R 或 T' }); const title = svg('title'); title.textContent = 'R / T 光谱：实线 Meep，虚线独立 tmm 参考'; chart.append(title);
    for (let i = 0; i <= 4; i++) { const yy = top + ph * i / 4, xx = left + pw * i / 4; append(chart, svg('line', { x1: left, x2: left + pw, y1: yy, y2: yy, class: 'chart-grid' }), svgText(format(ymax - (ymax - ymin) * i / 4, 4), { x: left - 10, y: yy + 4, 'text-anchor': 'end' }), svgText(format(xmin + (xmax - xmin) * i / 4, 4), { x: xx, y: top + ph + 24, 'text-anchor': 'middle' })); }
    append(chart, svg('line', { x1: left, x2: left + pw, y1: top + ph, y2: top + ph, class: 'chart-axis' }), svgText('R / T（无量纲）', { x: left, y: 18, class: 'axis-label' }), svgText('波长 λ（μm）', { x: left + pw / 2, y: height - 9, 'text-anchor': 'middle', class: 'axis-label' }));
    for (const key of fields) { let segment = []; const flush = () => { if (segment.length > 1) chart.append(svg('polyline', { points: segment.join(' '), class: `curve ${key}` })); segment = []; }; for (const row of points) { const value = finite(row[key]); if (value === null) { flush(); continue; } const px = x(row.wavelength_um), py = y(value); segment.push(`${px},${py}`); } flush(); }
    for (const key of fields) for (const row of points) { const value = finite(row[key]); if (value === null) continue; const dot = svg('circle', { cx: x(row.wavelength_um), cy: y(value), r: key.endsWith('_reference') ? 1.4 : 2.1, class: `plot-dot ${key}` }); const t = svg('title'); t.textContent = `λ = ${row.wavelength_um} μm；${key} = ${value}；频率 = ${readable(row.frequency)}`; dot.append(t); chart.append(dot); }
    const wrapper = n('div'); wrapper.append(chart); const legend = n('div', 'chart-legend'); [['R', 'Meep · R 反射率'], ['T', 'Meep · T 透射率'], ['R_reference', 'tmm · R 参考'], ['T_reference', 'tmm · T 参考']].forEach(([key, label]) => append(legend, append(n('span'), n('i', `legend-line ${key}`), label))); append(wrapper, legend, p(`${rows.length} 条实际返回记录；${points.length} 条具有有效波长。圆点为实际DFT求解点，插值点数0；连接线仅帮助阅读。悬停可查看数值。`, 'chart-caption')); return wrapper;
  }
  function spectrumTable(rows) { const table = n('table'); const head = n('tr'); const fields = ['frequency', 'wavelength_um', 'R', 'T', 'R_reference', 'T_reference']; ['频率', '波长 μm', 'Meep R', 'Meep T', 'tmm R', 'tmm T'].forEach(label => head.append(n('th', '', label))); append(table, append(n('thead'), head)); const body = n('tbody'); rows.forEach(row => { const tr = n('tr'); fields.forEach(key => tr.append(n('td', '', finite(row?.[key]) === null ? '—' : String(row[key])))); body.append(tr); }); table.append(body); return append(n('div', 'table-scroll'), table); }
  function downloadCsv(rows, runId) { const fields = ['frequency', 'wavelength_um', 'R', 'T', 'R_reference', 'T_reference']; const csv = [fields.join(','), ...rows.map(row => fields.map(key => finite(row?.[key]) === null ? '' : row[key]).join(','))].join('\r\n'); const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const a = n('a'); a.href = url; a.download = `${String(runId).replace(/[^a-zA-Z0-9_-]/g, '_')}_spectrum.csv`; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000); }
  async function loadSpectrum(caseId, runId, host) {
    const key = `${caseId}/${runId}`; try { let data = app.spectrumCache.get(key); if (!data) { data = await api(`/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/spectrum`); app.spectrumCache.set(key, data); } if (!host.isConnected || app.state?.id !== caseId || app.selectedRun !== runId) return; const rows = Array.isArray(data.spectrum) ? data.spectrum : []; if (!rows.length) { host.replaceChildren(n('div', 'empty-state', '这次运行没有可用光谱记录。请查看报告或错误日志；未绘制替代曲线。')); return; } host.replaceChildren(spectrumChart(rows), button('下载本次实际光谱 CSV ↓', () => downloadCsv(rows, runId), 'secondary small'), detail('查看实际数据点', '保留后端返回精度', spectrumTable(rows))); }
    catch (e) { if (!host.isConnected) return; host.replaceChildren(info(`实际光谱暂时无法读取：${e.message}`, 'warning'), button('重新读取光谱', () => loadSpectrum(caseId, runId, host), 'secondary small')); }
  }
  async function boot() { try { app.bootstrap = await api('/api/bootstrap'); if (!Array.isArray(app.bootstrap.cases)) app.bootstrap.cases = []; renderRuntime(); const id = idFromHash(); if (id) await loadCase(id); else {const w=location.hash.match(/^#workspace=([a-f0-9]{32}|default)$/)?.[1];if(w&&app.bootstrap.workspaces?.items.some(x=>x.id===w))app.workspace=w;else if((app.bootstrap.workspaces?.items.find(x=>x.id==='default')?.case_count||0)>=32){const available=app.bootstrap.workspaces.items.find(x=>x.case_count<32);if(available){app.workspace=available.id;announce('原工作区已满，已切换到可继续添加案例的工作区：'+available.label+'。原记录保留。');}}render();} } catch (e) { announce(e.message, true); content.replaceChildren(append(n('section', 'card'), n('h2', '', '暂时无法读取本地工作台'), p('请保留本地服务启动窗口，检查连接后重新读取。这里不会显示模拟任务或伪造运行结果。', 'card-copy'), button('重新连接', boot, 'secondary'))); } }
  $('workspace-select').addEventListener('change',e=>{if(app.busy)return;app.workspace=e.target.value;goHome();});$('new-workspace').addEventListener('click',createWorkspace);
  $('case-select').addEventListener('change', event => { if (event.target.value) loadCase(event.target.value); }); $('home-button').addEventListener('click', goHome); document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); goHome(); }); window.addEventListener('hashchange', () => { if (app.busy) { selectHash(app.state?.id || ''); return; } const id = idFromHash(); if (id) loadCase(id); else goHome(); }); window.addEventListener('beforeunload', () => stopPolling()); boot();
})();
