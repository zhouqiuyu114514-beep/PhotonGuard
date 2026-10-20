"""Human approval simulation only; no network and no paid model calls."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from photonguard.core import task_problem,digest
from photonguard.sampling import frequencies,description
from photonguard.script_import import preview_bytes,validate_provenance
from photonguard.workflow_intake import prepare,review,apply
from photonguard.workflow import WorkflowStore,WorkflowError
from photonguard.task_mapping import project

ROOT=Path(__file__).resolve().parents[1]
TEXT = """空间维度为1D。
入射角为0 deg。
相对磁导率为1。
所有介质无损。
所有介质各向同性。
所有介质无色散。
膜层数量为1。
入射折射率为1。
膜层折射率为1.7。
出射折射率为1。
膜厚为250 nm。
真空波长下界为1350 nm。
真空波长上界为1650 nm。
等波长采样点数为35。"""
OPTIONS={'units_um':1,'linear':True,'field_component':'Ex',
    'mapping_source':'独立合成任务卡v1：1单位=1微米，线性介质、正入射Ex。',
    'accept_sampling':True,'accept_decimal_projection':True,
    'background':'独立合成单膜课程练习','goal':'检查单膜R/T与独立任务的一致性','role':'审阅参数及批准修改的学习者'}

def reviewed(text=TEXT):
    value=prepare('synthetic-test',text)
    value=apply(value,{'type':'intake-review','mode':'mock'})
    return value

def confirmed():
    value=reviewed()
    return apply(value,{'type':'intake-confirm','approve':True,'result_sha256':value['result_sha256']})

def mapped(): return project(confirmed(),copy.deepcopy(OPTIONS))[0]

def test_wavelength_grid_is_direct_and_unequal_frequency():
    task=mapped();grid=np.asarray(frequencies(task))
    assert np.allclose(1/grid,np.linspace(1.65,1.35,35),rtol=0,atol=1e-14)
    assert not np.allclose(np.diff(grid),np.diff(grid)[0])
    assert description(task)['interpolated_point_count']==0
    assert task_problem(task) is None

def test_matching_explicit_ast_and_wrong_frequency_grid_refused():
    task=mapped();raw=(ROOT/'examples/script_import/wavelength35_index_mismatch.py').read_bytes()
    preview=preview_bytes(raw);assert preview['status']=='EXTRACTED',preview['unresolved']
    validate_provenance(preview['candidate'],task)
    bad=raw.replace(b'.add_flux(frequencies_for_monitors,',b'.add_flux(fcen, df, nfreq,')
    other=preview_bytes(bad);assert other['status']=='EXTRACTED'
    with pytest.raises(ValueError,match='cannot be silently replaced'):validate_provenance(other['candidate'],task)

def test_tampered_explicit_grid_and_code_never_accepted():
    raw=(ROOT/'examples/script_import/wavelength35_index_mismatch.py').read_bytes()
    candidate=preview_bytes(raw)['candidate'];candidate['origin']['script_import']['spectrum']['frequencies'][1]*=1.001
    with pytest.raises(ValueError):validate_provenance(candidate,mapped())
    assert preview_bytes(raw+b'\n__import__("os").system("echo unsafe")\n')['status']=='UNSUPPORTED'

@pytest.mark.parametrize('change',[{'units_um':None},{'linear':False},{'field_component':None},{'accept_sampling':False},{'mapping_source':''}])
def test_missing_mapping_basis_does_not_guess(change):
    options=copy.deepcopy(OPTIONS);options.update(change)
    with pytest.raises(ValueError):project(confirmed(),options)

@pytest.mark.parametrize('text',[TEXT.replace('膜厚为250 nm。',''),TEXT+'\n膜层折射率为1.9。',TEXT.replace('入射角为0 deg。','入射角为15 deg。')])
def test_missing_conflict_and_unsupported_stop(text):
    value=reviewed(text)
    assert not value['result']['confirmable']
    with pytest.raises(ValueError):apply(value,{'type':'intake-confirm','approve':True,'result_sha256':value['result_sha256']})
    with pytest.raises(ValueError):project(value,OPTIONS)

def test_version_pause_stale_click_and_failure_recovery(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state=store.create('own');ident=state['id']
        def action(kind,**data):
            nonlocal state
            state=store.action(ident,{'type':kind,'expected_revision':state['revision'],**data});return state
        action('intake-save',text=TEXT)
        action('intake-review',mode='mock')
        action('pause',reason='资料暂缺，未知不猜')
        assert state['intake']['result']
        with pytest.raises(WorkflowError):action('intake-confirm',approve=True,result_sha256=state['intake']['result_sha256'])
        action('resume');action('intake-confirm',approve=True,result_sha256=state['intake']['result_sha256'])
        action('map-task',options=OPTIONS)
        action('import',name='wavelength.py',source=(ROOT/'examples/script_import/wavelength35_index_mismatch.py').read_text())
        old_revision=state['revision'];action('confirm',approve=True)
        with pytest.raises(WorkflowError,match='过期'):store.action(ident,{'type':'confirm','approve':True,'expected_revision':old_revision})
        old_task=digest(state['task'])
        child=action('derive-version',reason='任务书v2更新需求，保留原版')
        assert child['id']!=ident and child['parent_version']['task_sha256']==old_task
        assert not child['approval'] and not child['runs'] and not child['intake']['confirmation']
        state=store.get(ident)
        with patch('photonguard.workflow.subprocess.Popen',side_effect=OSError('synthetic failure')):action('run')
        assert state['job']['status']=='failed' and state['job_attempts']==1 and not state['runs']
        with patch('photonguard.workflow.subprocess.Popen') as process:
            process.return_value.pid=12345
            action('run');assert process.call_count==1
        assert state['job_attempts']==2
    finally:store.close()

def test_sampling_report_initialization_even_without_solver_budget(tmp_path):
    from photonguard.core import write_json,lock_task
    from photonguard.runner import run_case
    task=mapped();candidate=preview_bytes((ROOT/'examples/script_import/wavelength35_index_mismatch.py').read_bytes())['candidate']
    write_json(tmp_path/'task.json',task);write_json(tmp_path/'candidate.json',candidate)
    lock_task(tmp_path/'task.json',tmp_path/'lock.json')
    report,out=run_case(tmp_path/'task.json',tmp_path/'candidate.json',tmp_path/'lock.json',tmp_path/'evidence',max_fdtd_runs=0)
    assert report['sampling']['actual_solver_point_count']==0
    assert len(report['sampling']['planned_solver_frequencies_per_um'])==35
    assert report['status']!='PASS' and report['resource_usage']['fdtd_runs']==0

def test_mapping_pause_saved_reset_and_changed_task_cannot_lock(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=False)
    try:
        state=store._load(store.create('own')['id']);ident=state['id']
        state['intake']=confirmed();store._save(state)
        def action(kind,**data):
            nonlocal state
            state=store.action(ident,{'type':kind,'expected_revision':state['revision'],**data});return state
        notes={k:OPTIONS[k] for k in ('mapping_source','background','goal','role')}
        action('pause-mapping',notes=notes);assert state['mapping_draft']==notes and state['paused_reason']
        assert not state['approval'] and not state['job']
        action('resume');action('map-task',options=OPTIONS)
        changed=copy.deepcopy(state['task']);changed['layers'][0]['n']=1.8
        action('task',task=changed)
        assert state['readiness']['provenance_problem']
        with pytest.raises(WorkflowError):action('confirm',approve=True)
        action('reset-mapping');assert not state.get('mapping_review') and not state['task_reviewed']
        action('map-task',options=OPTIONS);assert state['task']['layers'][0]['n']==1.7
    finally:store.close()

def test_http_trial_material_is_read_only_and_model_dispatch_disabled(tmp_path):
    import http.client,threading
    from photonguard.workflow import make_server
    server=make_server(tmp_path,port=0,allow_workers=False)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
        conn.request('GET','/api/closed-loop-example');response=conn.getresponse()
        assert response.status==200
        value=json.loads(response.read());assert value['script_executed'] is False and value['synthetic'] is True
        assert preview_bytes(value['source'].encode())['status']=='EXTRACTED'
        conn.close()
    finally:server.shutdown();server.server_close();thread.join()
