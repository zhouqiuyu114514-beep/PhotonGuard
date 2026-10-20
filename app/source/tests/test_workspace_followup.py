"""No solver/model calls: capacity, provenance and HTTP isolation regression."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from photonguard import workflow as wf
from photonguard.core import digest
from photonguard.repair_pipeline import ThreeStepPipeline
from photonguard.mode_pipeline import ModePipeline
from test_workflow_security import store, server, request, action, prepared

def test_full_workspace_keeps_old_cases_and_allows_new_collection(store):
    old=[store.create('own') for _ in range(32)]
    paths={s['id']:store.safe(s['id'],'state.json').read_bytes() for s in old}
    with pytest.raises(wf.WorkflowError,match='32'):store.create('own')
    w=store.create_workspace('第二组')
    fresh=store.create('own',w['id'])
    assert fresh['workspace_id']==w['id']
    assert [x['case_count'] for x in store.workspace_status()['items']]==[32,1]
    assert all(store.safe(i,'state.json').read_bytes()==b for i,b in paths.items())
    assert store.workspace_status()['shared_storage_limit_bytes']==1024**3
    assert len(store.list_cases())==33

def test_capacity_race_and_persistent_spaces(store):
    for _ in range(31):store.create('own')
    def attempt(_):
        try:return store.create('own')['id']
        except wf.WorkflowError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,range(4)))
    assert sum(x is not None for x in results)==1
    for i in range(7):store.create_workspace(str(i))
    with pytest.raises(wf.WorkflowError,match='8个'):store.create_workspace('ninth')
    root=store.root;store.close()
    with_reopen=wf.WorkflowStore(root,allow_workers=False)
    try:assert len(with_reopen.workspaces())==8
    finally:with_reopen.close()

@pytest.mark.parametrize('workspace_id',['../escape','not-found',None,{},['default']])
def test_invalid_workspace_no_new_case(store,workspace_id):
    with pytest.raises(wf.WorkflowError):store.create('own',workspace_id)
    assert store.list_cases()==[]

def test_workspace_http_csrf_and_shared_no_workers(server):
    assert request(server,'POST','/api/workspaces',{'label':'new'},omit=['X-CSRF-Token'])[0]==403
    assert len(server.store.workspaces())==1
    code,_,body=request(server,'POST','/api/workspaces',{'label':'new'})
    assert code==201
    ident=json.loads(body)['id']
    code,_,body=request(server,'POST','/api/cases',{'mode':'own','workspace_id':ident})
    assert code==201 and json.loads(body)['workspace_id']==ident
    boot=json.loads(request(server)[2])
    assert boot['workspaces']['items'][1]['case_count']==1
    assert boot['runtime']['workers_enabled'] is False

def test_metadata_cannot_change_locked_task_or_claim_human(store):
    s=prepared(store,confirm=True)
    before={k:digest(s[k]) for k in ('task','approval','candidate')}
    s=action(store,s,'case-metadata',label='模拟试用A',record_type='SIMULATED_AI_USER')
    assert {k:digest(s[k]) for k in before}==before
    assert s['record_type']=='SIMULATED_AI_USER'
    with pytest.raises(wf.WorkflowError):action(store,s,'case-metadata',label='bad',record_type='HUMAN_USER')
    with pytest.raises(wf.WorkflowError):action(store,s,'case-metadata',label='bad',record_type='UNCLASSIFIED',task={})
    assert len(list(store.case_dir(s['id']).glob('display-metadata-*')))==1

def test_workspace_does_not_inherit_paid_binding_or_approval(store):
    store.pipeline_controller=ThreeStepPipeline(store,None)
    store.mode_controller=ModePipeline(store,None)
    w=store.create_workspace('隔离案例')
    s=store.create('own',w['id'])
    assert s['three_step'] and not s['approval'] and not s['candidate']
    m=store.mode_controller.create_demo(w['id'])
    assert m['workspace_id']==w['id'] and not m['adapter_flow'].get('mode_lock')

def test_new_version_retains_workspace_and_no_approval(store):
    w=store.create_workspace('version')
    s=store.create('own',w['id'])
    child=action(store,s,'derive-version',reason='独立新说明')
    assert child['workspace_id']==w['id'] and not child['approval']
    assert child['parent_version']['case_id']==s['id']
