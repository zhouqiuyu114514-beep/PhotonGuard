/* Local review UI with optional cumulative approval. Untrusted materials and model text are rendered as text. */
'use strict';
window.PhotonGuardIntake = (() => {
  const labels = ['空间维度', '入射角', '相对磁导率', '无损', '各向同性', '无色散', '膜层数量', '入射折射率', '膜层折射率', '出射折射率', '膜厚', '波长下界', '波长上界', '等波长采样点数'];
  const states = { proposed: '待核对', unknown: '未知', conflict: '冲突', unsupported: '超范围' };
  function node(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
  function button(text, fn, id) { const b = node('button', text, 'button secondary small'); b.type = 'button'; b.onclick = fn; if (id) b.id = id; return b; }
  function download(value, name) { const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'})); const a = node('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  function create(s, hooks) {
    const card = node('section', null, 'card intake-card'); card.id = 'semantic-intake';
    card.append(node('h2', '自然语言需求 → 参数草稿'), node('p', '我会整理你提供的需求、标出依据并追问缺项。请提供独立设计说明；不会从待检脚本猜测你的目标。本地规则整理不调用 AI。AI 连接请使用光学实验工作台的连接设置。'));
    const batch = hooks.adapter?.batch;
    if (batch) card.append(node('p', `累计 AI 请求 ${batch.requests_used ?? '未知'} 次。${hooks.adapter.live_enabled ? '此入口仅发送已授权的教学资料。' : 'AI 暂不可用，仍可查看已有结果。'}`, 'info-box'));
    if (s.approved_comparison_arm) card.append(node('p', `这份公开合成材料已固定为 ${s.approved_comparison_arm} 对照。点击生成才会发送；完成或失败后不重复派发。`, 'info-box'));
    const intake = s.intake;
    const inputLabel = node('label', '粘贴独立需求原文（每行一个事实；保留缺项和不同版本）', 'field');
    const text = node('textarea'); text.id = 'intake-text'; text.rows = 9; text.maxLength = 24000; text.value = intake?.source_text || ''; inputLabel.append(text); card.append(inputLabel);
    const message = node('p', '', 'info-box'); message.id = 'intake-message'; message.setAttribute('role', 'status'); message.hidden = true;
    const controls = node('div', null, 'action-footer');
    let revision = s.revision, pending = false, cancelled = false, dirty = false;
    const fields = [], prior = new Map();
    const setMessage = value => { message.textContent = value; message.hidden = !value; };
    const current = () => card.isConnected && hooks.isCurrent(s.id);
    const freeze = value => { pending = value; fields.forEach(e => { if (value) { prior.set(e, e.disabled); e.disabled = true; } else e.disabled = prior.get(e) || false; }); cancel.disabled = false; };
    async function action(type, data = {}) {
      if (pending) return; cancelled = false; freeze(true); setMessage(data.mode === 'live' ? '正在处理已授权请求；失败不会自动重试…' : '正在本机处理；没有外部请求…');
      try {
        let next = await hooks.api(`/api/cases/${s.id}/action`, {type, ...data, expected_revision: revision});
        if (!current()) return;
        if (cancelled) {
          next = await hooks.api(`/api/cases/${s.id}/action`, {type: 'intake-cancel', expected_revision: next.revision});
        }
        hooks.accept(next);
      } catch (e) {
        if (!current()) return;
        setMessage(e.status === 409 ? '页面版本已变化；请重新读取记录后审阅。未自动重试。' : e.message);
      } finally { if (current()) freeze(false); }
    }
    const sample = button('填入合成示例（不保存）', () => { text.value = hooks.demo; text.dispatchEvent(new Event('input')); });
    const save = button('保存脱敏材料', () => action('intake-save', {text: text.value}), 'intake-save');
    if (s.approved_comparison_arm) { text.readOnly = true; sample.disabled = true; save.disabled = true; }
    const refresh = button('重新读取已保存记录', () => hooks.refresh(s.id));
    const cancel = button('撤回本次草稿', () => {
      if (pending) { cancelled = true; setMessage('已请求撤回；等待本机处理返回后持久化撤回。不会确认结果。'); return; }
      action('intake-cancel');
    }, 'intake-cancel');
    fields.push(text, sample, save, refresh); controls.append(sample, save, refresh); card.append(controls, message);
    if (!intake) { card.append(node('p', '保存后可选择受限规则整理，或导出当前材料供已有响应匹配。自由表述超出规则能力时保留未知。')); return card; }
    if (intake.redacted) card.append(node('p', '已脱敏疑似秘密；出处行号对应下方脱敏文本。请再次核对。', 'info-box warning'));
    card.append(node('p', `资料状态：${intake.status} · AI 请求 ${intake.model_calls || 0} 次 · 尚未计算`));
    if (intake.adapter_audit) card.append(node('p', `${intake.adapter_audit.mode} · 处理轮次 ${intake.adapter_audit.audits.length} · 工具调用次数 ${intake.adapter_audit.tool_calls} · ${intake.adapter_audit.status}`));
    if (intake.status === 'FAILED') {
      card.append(button('导出本次失败证据', () => download(intake, 'failed-review-evidence.json')));
      if (intake.rejection_code) card.append(node('p', `拒绝记录：${intake.rejection_code}。原记录已保留。`));
      if (!intake.response_evidence) card.append(node('p', '这次旧记录没有保存原始正文；不能复原具体拒绝原因。不会用新答案覆盖它。'));
    }
    if (intake.error) card.append(node('p', intake.error + ' 旧草稿和确认已失效；请修正材料或响应后重新校验。', 'info-box warning'));
    const mode = node('select'); mode.id = 'intake-mode';
    for (const [value, label] of [['mock', '本地规则整理'], ['offline', '导入已有回复（来源未验证）'], ['live', hooks.adapter?.live_enabled ? 'AI 整理' : 'AI 暂不可用']]) { const o = node('option', label); o.value = value; o.disabled = value === 'live' && !hooks.adapter?.live_enabled; mode.append(o); }
    const modeLabel = node('label', '处理模式', 'field'); modeLabel.append(mode); card.append(modeLabel);
    const arm = node('select'); arm.id = 'intake-arm'; for (const v of ['A1', 'A0']) { const o = node('option', v); o.value = v; arm.append(o); }
    if (s.approved_comparison_arm) { arm.value = s.approved_comparison_arm; arm.disabled = true; }
    const armLabel = node('label', '已有教学记录的处理方式', 'field'); armLabel.append(arm); armLabel.hidden = true; card.append(armLabel);
    const responseLabel = node('label', '已有响应 JSON（必须匹配导出材料的哈希与逐字出处）', 'field'); const response = node('textarea'); response.rows = 5; response.id = 'intake-response'; response.maxLength = 131072; responseLabel.append(response); responseLabel.hidden = true; card.append(responseLabel);
    mode.onchange = () => { responseLabel.hidden = mode.value !== 'offline'; invalidateResult(); };
    arm.onchange = () => invalidateResult();
    response.oninput = () => invalidateResult();
    const review = button('整理并核对草稿', () => action('intake-review', {mode: mode.value, arm: arm.value, response_text: mode.value === 'offline' ? response.value : ''}), 'intake-review');
    const exportView = button('导出资料与来源记录', () => download(intake.view, 'semantic-view.json'));
    const actions = node('div', null, 'action-footer'); actions.append(review, exportView, cancel);
    fields.push(mode, arm, response, review, exportView); card.append(actions);
    if (intake.status === 'CANCELLED') { review.disabled = true; actions.append(button('恢复材料（重新生成草稿）', () => action('intake-resume'), 'intake-resume')); }
    const result = intake.result;
    const resultHost = node('div'); card.append(resultHost);
    let confirm = null, agree = null;
    function invalidateResult() { resultHost.hidden = true; if (confirm) confirm.disabled = true; if (agree) agree.checked = false; setMessage('处理模式或响应已改变；重新校验后才可确认当前草稿。'); }
    text.oninput = () => {
      dirty = true; resultHost.hidden = true; review.disabled = true; exportView.disabled = true;
      if (confirm) confirm.disabled = true;
      setMessage('原文已修改：旧草稿与确认已在此页面失效。先保存材料，服务器将清除旧确认；刷新会恢复上次保存内容。');
    };
    if (result) {
      resultHost.append(node('h3', `${result.mode} · ${result.normalized_response.review_status}`), node('p', '引用存在仅证明逐字出处可定位，不证明语义正确或冲突已全部发现。请逐项人工核对。'));
      resultHost.append(node('p', '以下共 14 项，表格可上下滚动查看全部字段和出处。'));
      const table = node('table'); const head = node('tr'); ['参数', '状态', '精确值 / 单位', '原文出处'].forEach(v => head.append(node('th', v))); const thead = node('thead'); thead.append(head); table.append(thead); const tbody = node('tbody');
      Object.entries(result.normalized_response.fields).forEach(([key, f], i) => {
        const tr = node('tr'); tr.className = f.status === 'proposed' ? '' : 'unresolved-field'; tr.append(node('td', `${labels[i]}`), node('td', states[f.status]), node('td', f.value === null ? '待补充' : `${f.value} ${f.unit || ''}`));
        const refs = node('td'); f.evidence.forEach(r => refs.append(node('p', `${r.document} : 第 ${r.line} 行\n「${r.quote}」`))); if (!f.evidence.length) refs.append(node('p', '没有独立出处。请找设计任务书、材料测量记录或向需求提出者确认；不要从待检脚本补值。'));  tr.append(refs); tbody.append(tr);
      }); table.append(tbody); const wrap = node('div', null, 'table-scroll'); wrap.append(table); resultHost.append(wrap);
      result.normalized_response.questions.forEach(q => resultHost.append(node('p', q.text, 'info-box warning')));
      result.scope_problems.forEach(q => resultHost.append(node('p', q, 'info-box warning')));
      if (result.normalized_response.refusal.text) resultHost.append(node('p', result.normalized_response.refusal.text, 'info-box warning'));
      const blocked = node('div', null, 'info-box warning'); blocked.append(node('h3', '这份草稿还不是仿真任务')); blocked.append(node('p', '下一步需要确认仿真的单位尺度、场方向和采样方法。等波长要求现在可通过显式DFT频率列表直接求解，实际点数等于需求点数，没有插值。仍需核对尺度、线性与Ex的独立依据；没有资料就保存暂停。')); const detail = node('details'); detail.append(node('summary', '查看转换限制及依据')); result.bridge_blockers.forEach(q => detail.append(node('p', q))); blocked.append(detail); resultHost.append(blocked);
      agree = node('input'); agree.type = 'checkbox'; agree.id = 'intake-agree'; const agreeLabel = node('label', null, 'unknown-choice'); agreeLabel.append(agree, node('span', '我已逐项核对参数及原文；只确认语义审阅，不授权模型、任务锁或仿真。'));
      confirm = button('确认本份语义草稿', () => action('intake-confirm', {approve: agree.checked, result_sha256: intake.result_sha256}), 'intake-confirm'); confirm.disabled = true;
      agree.disabled = !result.confirmable || intake.status === 'HUMAN_REVIEWED'; agree.onchange = () => { confirm.disabled = !agree.checked || dirty || pending || !result.confirmable; };
      fields.push(agree, confirm); resultHost.append(agreeLabel, confirm, button('导出审阅记录', () => download(intake, 'semantic-review.json')));
      if (intake.confirmation) {
        resultHost.append(node('p', '已保存这份草稿的人工审阅。接下来核对执行映射；保存映射只生成待锁定任务，不运行。', 'info-box'));
        if (s.mapping_review) {
          resultHost.append(node('p', '执行映射已保存：原始等波长要求保留，每个点直接DFT求解，插值点数0。继续下方只读导入脚本及任务锁定。', 'info-box'));
          resultHost.append(button('返回执行映射并重新审阅（保留旧记录）',()=>action('reset-mapping'), 'reset-mapping'));
        } else {
          const mapping = node('section', null, 'mapping-form');
          mapping.append(node('h3', '把已核对需求整理成仿真任务'), node('p', '为什么要补充这些资料：Meep需要知道长度尺度，当前配方只支持线性介质和Ex场。请查课程任务卡、设计说明或建模约定；不从待检脚本反推。'));
          if (s.trial_material) mapping.append(node('p', s.trial_material.mapping_source, 'info-box'));
          const inputs = {};
          for (const [key, label] of [['mapping_source','尺度、线性、Ex的独立出处（写明文件/页码或任务卡）'], ['background','这次任务的背景'], ['goal','你要验证什么'], ['role','你在这次任务中的角色']]) {
            const input = node('textarea'); input.rows = 2; input.maxLength = 4000; input.id = 'mapping-' + key; input.value = s.mapping_draft?.[key] || s.trial_material?.[key] || '';
            const labelNode = node('label', label, 'field'); labelNode.append(input); mapping.append(labelNode); inputs[key] = input; fields.push(input);
          }
          const checks = {};
          for (const [key,label] of [['units','资料明确：1个Meep长度单位对应1微米'], ['linear','资料明确：介质响应为线性'], ['ex','资料明确：正入射Ex场'], ['sampling','保留原始等波长点：换算为逐点DFT频率；没有插值，不改成等频率'], ['precision','已核对nm→微米的精确换算；执行时用双精度数字，范围不变']]) {
            const input = node('input'); input.type = 'checkbox'; input.id = 'mapping-' + key; input.value = s.mapping_draft?.[key] || s.trial_material?.[key] || '';
            const labelNode = node('label', null, 'unknown-choice'); labelNode.append(input,node('span',label)); mapping.append(labelNode); checks[key] = input; fields.push(input);
          }
          const submit = button('保存明确映射，进入脚本检查', () => action('map-task', {options:{...Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value.trim()])),units_um:checks.units.checked ? 1 : null, linear:checks.linear.checked,field_component:checks.ex.checked ? 'Ex' : null,accept_sampling:checks.sampling.checked,accept_decimal_projection:checks.precision.checked}}), 'map-task');
          fields.push(submit); mapping.append(submit,button('没有独立资料，保存暂停',()=>action('pause-mapping',{notes:Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]))}))); resultHost.append(mapping);
        }
      }
    }
    return card;
  }
  return {create};
})();
