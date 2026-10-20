import copy
import io
import json
import time
import zipfile
import numpy as np
import pytest
from photonguard.workflow import WorkflowStore, WorkflowError
from photonguard.experiments import observations as obs, inference as inf, observation_workflow as ow
from photonguard.experiments.service import store_for
from photonguard.core import digest
from test_workflow_security import server,request


def sample(ident='OBS01'):
    row=next(r for r in ow.samples() if r['id']==ident)
    raw=(ow.SAMPLES/(ident+'.csv')).read_text()
    return obs.parse_csv(raw,source_name=row['title'],source_kind='SYNTHETIC_TEACHING'),copy.deepcopy(row['settings'])


@pytest.fixture
def store(tmp_path):
    owner=WorkflowStore(tmp_path/'work',allow_workers=True)
    yield store_for(owner)
    owner.close()


def act(store,s,kind,**kw):return store.action(s['id'],{'type':kind,'expected_revision':s['revision'],**kw})


@pytest.mark.parametrize('bad', ['=1+2','NaN','Infinity','1e999','sk-THISISASYNTHETICCREDENTIAL0000','', '1,2'])
def test_csv_rejects_nonfinite_formulas_and_missing_without_cleanup(bad):
    raw='position_mm,intensity_relative\n'+'\n'.join(f'{i},{bad if i==5 else 1}' for i in range(20))
    with pytest.raises(ValueError):obs.parse_csv(raw,source_name='test')


def test_unit_mapping_and_original_hash():
    raw='position_um,intensity_relative\n'+'\n'.join(f'{i*1000},{i*.1}' for i in range(20))
    d=obs.parse_csv(raw,source_name='test');assert d['x_mm'][-1]==19
    obs.verify(d,raw.encode())
    with pytest.raises(ValueError):obs.verify(d,(raw+'\n').encode())
    with pytest.raises(ValueError):obs.parse_csv(raw,position_unit='mm',source_name='test')
    with pytest.raises(ValueError):obs.parse_csv(raw.replace('position_um','pixel'),position_unit='mm',source_name='test')


def test_pixel_and_unknown_scale_pause():
    d,s=sample('OBS03');problems,missing=inf.issues(d,s)
    assert d['x_mm'] is None and 'focal_length_mm' in missing and any('刻度' in p for p in problems)
    with pytest.raises(ValueError):inf.plan(d,s)


@pytest.mark.parametrize('bad', ['NEAR_FIELD','FREE_SPACE','UNKNOWN'])
def test_plane_mismatch_never_fits(bad):
    d,s=sample();s['fixed']['measurement_plane']=bad
    with pytest.raises(ValueError):inf.plan(d,s)


def test_unknown_optical_scale_and_extra_parameters_rejected():
    d,s=sample();s['fixed']['focal_length_mm']=None;s['fixed']['slit_width_um']=None
    assert {'focal_length_mm','slit_width_um'}<=set(inf.issues(d,s)[1])
    s['bounds']['focal_length_mm']=[100,300]
    with pytest.raises(ValueError):inf.plan(d,s)


@pytest.mark.parametrize('ident',['OBS01','OBS02'])
def test_bounded_fit_recovery_all_rows_and_actual_jacobian_calls(ident):
    d,s=sample(ident);p=inf.plan(d,s);before=copy.deepcopy(d);r=inf.fit(d,p)
    assert r['status']=='ESTIMATE_READY',r['warnings']
    assert abs(r['estimated_parameters']['slit_separation_um']-180)<1
    assert d==before and len(r['data']['observed'])==401
    assert r['metrics']['training']['count']==320 and r['metrics']['holdout']['count']==81
    assert r['resources']['actual_residual_calls']>r['resources']['reported_nfev_total']
    assert sum(x['actual_residual_calls'] for x in r['starts'])==r['resources']['actual_residual_calls']<=12000
    assert len(r['starts'])==9 and r['confidence_interval'] is None


def test_budget_stop_retains_failed_start():
    d,s=sample();s['budget']={'max_residual_calls':2};r=inf.fit(d,inf.plan(d,s))
    assert not r['usable_for_forward'] and r['resources']['actual_residual_calls']==2
    assert r['starts'][0]['status']=='RESOURCE_STOP'


def test_short_data_does_not_claim_unique_estimate():
    d,s=sample();x=np.linspace(-.1,.1,50);y=inf.predict(x,[180,.12,.9,.03],s['fixed'])
    raw='position_mm,intensity_relative\n'+'\n'.join(f'{a},{b}' for a,b in zip(x,y))
    d=obs.parse_csv(raw,source_name='short');r=inf.fit(d,inf.plan(d,s))
    assert not r['usable_for_forward']
    if r.get('estimated_parameters'):assert 'INSUFFICIENT_INFORMATION' in r['warnings']


def test_model_mismatch_not_certified():
    d,s=sample();x=np.array(d['x_mm']);y=.4+.3*np.sin(x*1.8)+.1*x
    raw='position_mm,intensity_relative\n'+'\n'.join(f'{a},{b}' for a,b in zip(x,y))
    d=obs.parse_csv(raw,source_name='model mismatch');r=inf.fit(d,inf.plan(d,s))
    assert not r['usable_for_forward']


def test_scale_degeneracy_is_real_and_fixed_contract_avoids_it():
    x=np.linspace(-3,3,50);fixed={'wavelength_nm':633,'focal_length_mm':200,'slit_width_um':20}
    y=inf.predict(x,[180,.12,.9,.03],fixed)
    scaled={**fixed,'focal_length_mm':400,'slit_width_um':40}
    assert np.allclose(y,inf.predict(x,[360,.12,.9,.03],scaled))


def test_approvals_revision_and_frozen_evidence(store):
    s=ow.create(store,{'sample_id':'OBS01'});s=act(store,s,'fit_plan',settings=s['fit_settings'])
    with pytest.raises(WorkflowError):act(store,s,'fit_run',approve=False,plan_sha256=s['fit_plan']['sha256'])
    with pytest.raises(WorkflowError):act(store,s,'fit_run',approve=True,plan_sha256='old')
    old=copy.deepcopy(s);s=act(store,s,'fit_run',approve=True,plan_sha256=s['fit_plan']['sha256'])
    for _ in range(200):
        s=store.get(s['id'])
        if s['status']!='RUNNING':break
        time.sleep(.05)
    assert s['status']=='COMPLETED',s
    assert s['fit_result']['usable_for_forward']
    with pytest.raises(WorkflowError):act(store,s,'fit_plan',settings=old['fit_settings'])
    raw=store.export(s['id'])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.read('original.csv')==(ow.SAMPLES/'OBS01.csv').read_bytes()
        assert 'SUMMARY.html' in z.namelist() and 'tables/fit-and-residual.csv' in z.namelist()
    child=act(store,s,'fit_revise');assert child['parent_id']==s['id'] and child['observation_root']==s['id']
    assert store.get(s['id'])['fit_result']==s['fit_result']
    before=digest(s['fit_result'])
    forward=act(store,s,'fit_forward',approve_estimate=True,geometry={'slit_height_um':100,'grid_size':512,'window_mm':.8})
    assert forward['status']=='PLANNED' and forward['parent_id']==s['id']
    assert len(forward['plan']['candidates'])==1
    assert forward['spec']['parameter_sources']['slit_separation_um']['source_kind']=='MODEL_ESTIMATE'
    assert digest(store.get(s['id'])['fit_result'])==before
    assert store.public_record(forward)['experiment_record']['result_context'] is None
    unrelated=ow.create(store,{'sample_id':'OBS03'})
    with zipfile.ZipFile(io.BytesIO(store.export_family(s['id']))) as z:
        manifest=json.loads(z.read('FAMILY_MANIFEST.json'))
        assert {v['id'] for v in manifest['versions']}=={s['id'],child['id'],forward['id']}
        assert unrelated['id'] not in z.namelist()
        assert z.read(s['id']+'/original.csv')==(ow.SAMPLES/'OBS01.csv').read_bytes()
        assert json.loads(z.read(forward['id']+'/case.json'))['estimate_origin']['source_kind']=='MODEL_ESTIMATE'
        import hashlib
        assert all(hashlib.sha256(z.read(name)).hexdigest()==sha for name,sha in manifest['files'].items())
    (store.folder(s['id'])/'original.csv').write_text('tampered')
    with pytest.raises(ValueError):store.export(s['id'])


def test_http_import_csrf_and_invalid_data(server):
    body={'sample_id':'OBS03'}
    assert request(server,'POST','/api/experiments/observations',body,omit=['X-CSRF-Token'])[0]==403
    status,_,raw=request(server,'POST','/api/experiments/observations',body)
    assert status==201 and json.loads(raw)['kind']=='observation'
    s=json.loads(raw)
    status,_,raw=request(server,'POST','/api/experiments/cases/'+s['id']+'/action',{'type':'fit_plan','expected_revision':s['revision'],'settings':s['fit_settings']})
    assert status==200 and json.loads(raw)['status']=='NEEDS_INFORMATION'


def test_sample_truth_not_in_public_catalog():
    assert all('truth' not in json.dumps(row).lower() and '180' not in json.dumps(row) for row in ow.samples())


def test_no_scipy_leaves_forward_cases_available(store,monkeypatch):
    real=ow.importlib.util.find_spec
    monkeypatch.setattr(ow.importlib.util,'find_spec',lambda name:None if name=='scipy' else real(name))
    assert not store.bootstrap()['capabilities']['analysis']
    assert len(store.bootstrap()['case_library'])==12
    s=ow.create(store,{'sample_id':'OBS01'});s=act(store,s,'fit_plan',settings=s['fit_settings'])
    with pytest.raises(WorkflowError,match='SciPy'):act(store,s,'fit_run',approve=True,plan_sha256=s['fit_plan']['sha256'])
    assert store.get(s['id'])['analysis_ledger']['fit_runs_reserved']==0


def test_fit_quota_shared_with_revised_settings(store):
    s=ow.create(store,{'sample_id':'OBS01'})
    s['analysis_ledger']['fit_runs_reserved']=3;store.save(s)
    c=act(store,s,'fit_revise');c=act(store,c,'fit_plan',settings=c['fit_settings'])
    with pytest.raises(WorkflowError,match='3 次'):act(store,c,'fit_run',approve=True,plan_sha256=c['fit_plan']['sha256'])
    assert store.get(c['id'])['status']=='PLANNED'


def test_settings_tampering_and_running_family_refuse_export(store):
    s=ow.create(store,{'sample_id':'OBS01'});s=act(store,s,'fit_plan',settings=s['fit_settings'])
    s['fit_settings']['fixed']['focal_length_mm']=300;store.save(s)
    with pytest.raises(WorkflowError,match='拟合计划'):store.export(s['id'])
    s=ow.create(store,{'sample_id':'OBS03'});c=act(store,s,'fit_revise')
    c['status']='RUNNING';store.save(c)
    with pytest.raises(WorkflowError,match='计算中'):store.export_family(s['id'])


def test_row_limit_and_oversized_license_rejected():
    raw='position_mm,intensity_relative\n'+'\n'.join(f'{i},1' for i in range(5001))
    with pytest.raises(ValueError):obs.parse_csv(raw,source_name='too many')
    raw='position_mm,intensity_relative\n'+'\n'.join(f'{i},1' for i in range(20))
    with pytest.raises(ValueError):obs.parse_csv(raw,source_name='test',license_name='x'*301)


def test_family_endpoint_preserves_drafts(server):
    status,_,raw=request(server,'POST','/api/experiments/observations',{'sample_id':'OBS03'})
    s=json.loads(raw)
    status,_,raw=request(server,'GET','/api/experiments/cases/'+s['id']+'/family-export')
    assert status==200
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest=json.loads(z.read('FAMILY_MANIFEST.json'))
        assert len(manifest['versions'])==1 and manifest['model_calls']==0


def test_rejected_data_followup_keeps_parent_and_spent_budget(store):
    from test_case_recovery import completed
    s=completed(store)  # Saved synthetic unit-test evidence, no solver call.
    s['estimate_origin']={'source_kind':'MODEL_ESTIMATE','record_id':'b'*32}
    ledger=s['exploration_ledger'];ledger['used_output_bytes']=ledger['output_limit_bytes']
    store.save(s);before=copy.deepcopy(ledger)
    request={'case_id':'D02','bounds':{'min':120,'max':230},'goal':{'metric':'fringe_period_mm','operator':'near','target':.8,'tolerance':.02}}
    child=act(store,s,'explore_case',new_exploration=True,case_id='D02',request=request)
    assert child['status']=='NEEDS_INFORMATION' and child['plan'] is None
    assert child['parent_id']==s['id'] and child['family_id']==s['family_id']
    assert store.get(s['id'])['exploration_ledger']==before
