// Runs the actual UI in a minimal DOM; no browser, network, solver or model.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.value='';this.selectedIndex=0;this.isConnected=false;this.textContent='';}
 append(...v){this.children.push(...v);}
 replaceChildren(...v){this.children=v;}
 setAttribute(k,v){this[k]=v;}
}
const root=process.argv[2],fixture=process.argv[3];
const context={window:{},document:{createElement:t=>new Element(t)},queueMicrotask:()=>{},JSON,Number,Object};
vm.createContext(context);vm.runInContext(fs.readFileSync(root+'/photonguard/workflow_assets/repair.js','utf8'),context);
const source=JSON.parse(fs.readFileSync(fixture,'utf8'));
const all=e=>[e,...e.children.flatMap(c=>typeof c==='object'?all(c):[])];
for(const mode of ['live','rules']){
 const s=structuredClone(source);s.approval=null;s.pipeline=null;s.runs=[];s.repair_trial.mode=mode;
 const calls=[];const h={mutate:(...a)=>{calls.push(a);return true;},service:{live_enabled:true,reserved_cny:'4.1'}};
 const page=context.window.PhotonGuardRepair.create(s,h),nodes=all(page);
 assert.equal(nodes.find(x=>x.className==='simple-steps').children.length,3);
 const consent=nodes.find(x=>x.id==='one-task-consent'),start=nodes.find(x=>x.textContent==='确认需求并开始检查');
 assert(start.disabled);consent.checked=true;consent.onchange();assert(!start.disabled);start.onclick();
 assert.equal(calls.length,1);assert.equal(calls[0][0],'start-review');assert.equal(calls[0][1].diagnostic_mode,mode);
 assert(nodes.filter(x=>x.tag==='details').every(x=>x.open!==true));
}
{
 const s=structuredClone(source);s.pipeline.status='AWAITING_APPROVAL';delete s.repair_result;
 const calls=[],page=context.window.PhotonGuardRepair.create(s,{mutate:(...a)=>calls.push(a),service:{live_enabled:true}}),nodes=all(page);
 const consent=nodes.find(x=>x.id==='one-repair-consent'),start=nodes.find(x=>x.textContent==='批准这份修复并自动复验');
 assert(start.disabled);consent.checked=true;consent.onchange();start.onclick();assert.equal(calls.length,1);
 assert.equal(calls[0][0],'approve-repair');assert.equal(calls[0][1].card_sha256,s.repair_card_sha256);
}
{
 const page=context.window.PhotonGuardRepair.create(source,{service:{live_enabled:true}}),nodes=all(page);
 assert(nodes.some(x=>x.textContent.includes('最大光谱误差')));
 assert(nodes.some(x=>x.tag==='a'&&x.href.endsWith('/repaired-recipe')));
}
console.log('Actual three-step UI: both modes, disabled-before-consent, one repair action, collapsed details, measured result and download passed. Zero requests.');
