"use strict";
window.PhotonGuardNovice=(()=>{
 const el=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
 function button(text,run){const b=el('button',text);b.type='button';b.className='button';b.onclick=run;return b;}
 // Tab-local drafts survive reloads without sharing edits between tabs or data roots.
 const memory=new Map();
 const key=(s,scope,kind)=>'photonguard-novice-v1:'+JSON.stringify([scope||'',s.workspace_id||'default',s.id,kind]);
 function read(s,scope,kind){const k=key(s,scope,kind);if(memory.has(k))return memory.get(k);try{const raw=sessionStorage.getItem(k);return raw?JSON.parse(raw):memory.get(k)||null;}catch(_){return memory.get(k)||null;}}
 function remove(s,scope,kind){const k=key(s,scope,kind);memory.delete(k);try{sessionStorage.removeItem(k);}catch(_){}}
 function write(s,scope,kind,value){const k=key(s,scope,kind);memory.set(k,value);try{sessionStorage.setItem(k,JSON.stringify(value));return true;}catch(_){return false;}}
 function saved(s,scope){remove(s,scope,'draft');}
 function begin(s,scope,type){if(type==='novice-ai-review')write(s,scope,'pending',{revision:s.revision,type});}
 function settled(s,scope){remove(s,scope,'pending');}
 const credentialLike=text=>/\bsk-[a-zA-Z0-9_-]{16,}|Bearer\s+[a-zA-Z0-9_.-]{16,}/i.test(text);
 function download(text){const a=el('a');const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));a.href=url;a.download='PhotonGuard-unsaved-material.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function create(s,h){
  const d=s.novice,host=el('section');host.className='card novice-card';
  host.append(el('h1',d.kind==='teaching'?'看一层薄膜怎样反射和透射光':'整理已有模型资料'),el('p','无需准备Python脚本。先核对资料，再按受支持模板运行。'));
  host.append(el('p',d.kind==='teaching'?'这是有版本的合成教学示例，参数来自公开练习卡，不是你的实际器件。':'只采用你明确提供的参数；资料不足时可以保存暂停。'));
  if(s.actor_type==='SIMULATED')host.append(el('p',s.simulation_context?'模拟操作记录，仅供查看，不会启动新计算。':'模拟操作记录，不属于真人使用记录；计算仍需单独确认。'));
  if(d.derived_from)host.append(el('p','这是从已有案例另建的可编辑草稿，需重新核对并确认。原案例来源：'+d.derived_from.template_source));
  if(s.paused_reason){host.append(el('p','已暂停：'+s.paused_reason),button('恢复编辑',()=>h.mutate('resume')));return host;}
  let text=null,reviewButton=null,saveButton=null,dirty=false,recovery=false,conflict=false;
  let pending=read(s,h.scope,'pending');
  if(pending&&Number.isInteger(pending.revision)&&s.revision>pending.revision){settled(s,h.scope);pending=null;host.append(el('p','已读取上次操作后的最新记录；没有自动重发模型请求。'));}
  const recoveryPanel=el('div'),conflictPanel=el('div'),backup=el('p'),unsaved=el('p','资料已修改，下面仍是已保存版本的摘要。请先保存，或选择保存暂停。');unsaved.hidden=true;unsaved.setAttribute('role','status');backup.setAttribute('role','status');
  let local=read(s,h.scope,'draft');
  if(local&&!(typeof local.text==='string'&&local.text.length<=24000&&typeof local.base_text==='string'&&local.base_text.length<=24000&&Number.isInteger(local.base_revision)&&!credentialLike(local.text))){local=null;backup.textContent='本标签页的暂存资料无法恢复。请使用已下载的备份；已保存资料仍在。';}
  if(local&&local.text===d.original_text){saved(s,h.scope);local=null;}
  let baseText=d.original_text,baseRevision=s.revision;
  if(d.kind==='specified'){
   text=el('textarea');text.rows=10;text.value=d.original_text;text.maxLength=24000;text.setAttribute('aria-label','已有模型资料');
   saveButton=button('保存并整理资料',()=>{if(!recovery&&!conflict&&!pending)h.mutate('novice-material',{text:text.value});});
   host.append(el('label','粘贴已有模型资料，未知的内容留空'),text,saveButton,recoveryPanel,conflictPanel);
   if(h.service?.mode==='PRODUCT_DEEPSEEK'&&h.service.live_enabled){reviewButton=button('把已保存资料交给真实AI整理',()=>{if(!dirty&&!recovery&&!conflict&&!pending)h.mutate('novice-ai-review',{approve_data:true});});host.append(el('p','可将已保存的原文发送给真实DeepSeek整理：每次最多2次请求，使用当前已授权额度。输出仍需核对，不能补造缺项。'),reviewButton);}
   host.append(unsaved,backup,button('下载编辑框中的资料',()=>download(text.value)));
  }
  if(pending)host.append(el('p','上一次AI整理的响应尚未确认。先读取最新记录；不会自动重发或恢复确认勾选。'),button('仅读取最新状态',h.refresh));
  if(d.model_attempt)host.append(el('p',`真实AI整理：${d.model_attempt.status==='DRAFT_RETURNED'?'已返回草稿':'本次未完成'}，本次${d.model_attempt.calls}次请求。${d.model_attempt.guard?.accepted?'已得到待核对草稿。':'回答未通过校验，原稿与失败记录保留。'}`));
  host.append(el('h2','任务摘要'));
  if(d.ready){const t=d.task;host.append(el('p',`空气中的单层薄膜：折射率 ${t.layers[0].n}，膜厚 ${t.layers[0].thickness_um} 微米（${t.layers[0].thickness_um*1000} nm）；波长 ${t.wavelength_um.join('–')} 微米，${t.nfreq} 个等波长点。线性、无损、无色散、各向同性、正入射Ex。`));}
  if(d.missing.length||d.blockers.length){host.append(el('h3','继续前需要一次核对这些资料'));const list=el('ul');d.missing.forEach(x=>list.append(el('li',x.label+'：'+(x.status==='conflict'?'来源冲突，不能替你选边':'尚缺独立依据'))));d.blockers.forEach(x=>list.append(el('li',x)));host.append(list);}
  if(d.blockers.some(x=>x.includes('真实波导'))&&h.createModeDemo)host.append(button('另开合成LN教学示例',h.createModeDemo));
  const annotations=d.intake?.result?.source_annotations||[];
  if(annotations.length){const notes=el('details');notes.append(el('summary','查看未作为实际参数的说明'));const list=el('ul');annotations.forEach(x=>list.append(el('li',x.reason+' · 第'+x.evidence.line+'行：'+x.evidence.quote)));notes.append(list);host.append(notes);}
  const source=el('details');source.append(el('summary','查看原始资料、参数出处与模板'),el('pre',JSON.stringify({original:d.original_text,fields:d.intake?.result?.normalized_response?.fields,template:d.template_id,source:d.template_source,plan:d.plan},null,2)));host.append(source);
  host.append(el('p','模板提供技术设置，设置本身不保证精度。初次最多8次FDTD；没有自动修复或模型请求。需要修复时会另列具体修改。'));
  const consent=el('input');consent.type='checkbox';consent.id='novice-consent';const label=el('label');label.className='check-approval';label.append(consent,el('span','我已核对这份任务摘要，确认按本计划开始检查。'));
  const blocked=()=>dirty||recovery||conflict||!!pending;
  const start=button('确认摘要并开始检查',()=>{if(!blocked()&&consent.checked&&d.ready)h.mutate('novice-start',{approve:true,plan_sha256:d.plan_sha256});});
  const pause=button('资料暂缺，保存暂停',()=>{if(!recovery&&!conflict&&!pending)text?h.mutate('novice-pause',{text:text.value}):h.mutate('pause',{reason:'无脚本任务资料尚缺，保留未知。'});});
  function update(){start.disabled=blocked()||!consent.checked||!d.ready;if(reviewButton)reviewButton.disabled=blocked();if(saveButton)saveButton.disabled=recovery||conflict||!!pending;pause.disabled=recovery||conflict||!!pending;unsaved.hidden=!dirty;}
  function remember(){
   if(!dirty){saved(s,h.scope);backup.textContent='';return;}
   if(credentialLike(text.value)){saved(s,h.scope);backup.textContent='检测到疑似密钥，未写入本标签页暂存。请移除密钥后再保存资料。';return;}
   const durable=write(s,h.scope,'draft',{text:text.value,base_text:baseText,base_revision:baseRevision});
   backup.textContent=durable?'未保存文字已在本标签页临时保留，可在刷新后恢复。关闭标签页前请保存或下载。':'浏览器不允许暂存；刷新可能丢失未保存文字。请先保存或下载备份。';
  }
  consent.onchange=update;
  if(text){
   text.oninput=()=>{dirty=text.value!==d.original_text;consent.checked=false;remember();update();};
   if(local){
    recovery=true;text.disabled=true;
    recoveryPanel.append(el('p','检测到本标签页未保存的草稿。先选择恢复或丢弃；当前摘要来自已保存资料。'),button('恢复本标签页草稿',()=>{
     recovery=false;text.disabled=false;text.value=local.text;baseText=local.base_text;baseRevision=local.base_revision;dirty=text.value!==d.original_text;conflict=baseText!==d.original_text;consent.checked=false;recoveryPanel.replaceChildren();
     if(conflict){const previous=el('details');previous.open=true;previous.append(el('summary','其他页面已保存的新资料'),el('pre',d.original_text));conflictPanel.append(el('p','资料已在别处更新。编辑框保留本标签页草稿；核对下方最新资料后才能保存，不会自动覆盖。'),previous,button('已核对差异，允许保存当前草稿',()=>{conflict=false;baseText=d.original_text;baseRevision=s.revision;conflictPanel.replaceChildren();remember();update();}));}
     remember();update();
    }),button('丢弃本标签页草稿',()=>{saved(s,h.scope);local=null;recovery=false;text.disabled=false;text.value=d.original_text;dirty=false;recoveryPanel.replaceChildren();backup.textContent='已保留服务端保存的资料。';update();}));
   }
  }
  host.append(label,start,pause);update();return host;
 }
 return {create,saved,begin,settled};
})();
