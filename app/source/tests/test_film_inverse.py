import copy
import numpy as np
import pytest
from test_inverse_journeys import store,act,planned,wait
from photonguard.experiments import film_inverse as f,inverse_models as m,inverse_profiles as engine,observation_group as ow

def group(thickness=263.,wavelengths=(633.,)):
    cfg=f.defaults();y=f.predict(wavelengths,thickness,cfg['fixed']);raw='wavelength_nm,reflectance_calibrated\n'+'\n'.join(f'{w},{r}' for w,r in zip(wavelengths,y))
    ds=f.parse_csv(raw,source_kind='SYNTHETIC_TEACHING',source_name='known finite fixture');g=ow.group_entry(ds,cfg,'scan-0.csv');g['approved']=True;return [g],cfg

def test_single_wavelength_modes_and_period_not_unique():
    groups,cfg=group();r=engine.run(m.plan(groups,cfg));modes=[x['parameters']['thickness_nm'] for x in r['modes']]
    assert len(modes)>4 and min(abs(t-263) for t in modes)<1e-4
    assert r['diagnostics']['period_nm_at_first_wavelength']==158.25
    assert not r['usable_for_forward'] and r['confidence_interval'] is None
    assert np.allclose(f.predict([633],263,cfg['fixed']),f.predict([633],263+158.25,cfg['fixed']))

def test_joint_new_wavelength_reduces_modes_without_truth_in_planner():
    groups,cfg=group();first=engine.run(m.plan(groups,cfg));p=f.propose(groups,cfg,first,{'wavelengths_nm':[500.,550.,650.,750.,850.]})
    selected=next(x for x in p['plans'] if x['id']==p['recommended_id']);second,_=group(wavelengths=selected['wavelengths_nm']);joined=engine.run(m.plan(groups+second,cfg))
    assert len(joined['modes'])<len(first['modes']) and abs(joined['estimated_parameters']['thickness_nm']-263)<1e-4
    assert p['resources']['fdtd_calls']==0

@pytest.mark.parametrize('bad',['wavelength_nm,intensity_relative\n633,0.2','wavelength_nm,reflectance_calibrated\n633,2','wavelength_nm,reflectance_calibrated\n633,0.2\n633,0.3'])
def test_uncalibrated_or_invalid_rejected(bad):
    with pytest.raises(ValueError):f.parse_csv(bad,source_kind='USER_PROVIDED',source_name='source')

def test_free_index_or_absorption_rejected():
    groups,cfg=group();cfg['bounds']['film_index']=[1,3]
    with pytest.raises(ValueError):m.plan(groups,cfg)
    groups,cfg=group();cfg['fixed']['lossless']=False
    with pytest.raises(ValueError):m.plan(groups,cfg)

def test_frozen_teaching_full_store_journey(store,monkeypatch):
    monkeypatch.setattr('secrets.randbits',lambda bits:0)
    s=ow.create(store,{'model':m.FILM,'teaching':True});s=planned(store,s);s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    assert s['status']=='COMPLETED' and len(s['inverse_result']['modes'])>1
    s=act(store,s,'inverse_measurement_plan',constraints={'wavelengths_nm':[500.,550.,650.,750.,850.]});p=s['measurement_plan'];s=act(store,s,'inverse_append',approve=True,teaching=True,proposal_id=p['recommended_id'],proposal_sha256=p['sha256']);s=planned(store,s);s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    assert s['status']=='COMPLETED' and len(s['groups'])==2 and s['inverse_result']['resources']['tmm_evaluations']>0
    ow.verify(store,s);assert store.get(s['inverse_root'])['inverse_ledger']['fit_runs_reserved']==2

def test_teaching_reflectance_out_of_range_is_rejected_without_clipping(tmp_path,monkeypatch):
    import json
    from photonguard.core import digest
    obj={'model':m.FILM,'seed':0,'thickness_nm':316.5,'noise_sd':.001,'film_index':2.}
    folder=tmp_path/'object';folder.mkdir();raw=json.dumps(obj);(folder/'object.json').write_text(raw)
    class FixedNegativeNoise:
        def normal(self,mean,sd,count):return np.full(count,-.001)
    monkeypatch.setattr(np.random,'default_rng',lambda seed:FixedNegativeNoise())
    with pytest.raises(ValueError,match='不截断或重试'):
        f.teaching_acquire(tmp_path,'object',digest(obj),0,[633.])
    assert (folder/'object.json').read_text()==raw
