import copy
import numpy as np
import pytest
from test_inverse_journeys import data
from photonguard.core import digest
from photonguard.experiments import inverse_models as m, inverse_profiles as engine, goal_design as gd
from photonguard.experiments import observations
from photonguard.experiments import observation_contract as oc


def independent(groups, settings):
    settings['weighting']=oc.INDEPENDENT
    settings['future_noise']={'sigma':.01,'independent':True,'source':'USER_DECLARED','reference':'Declared future point noise'}
    for i,g in enumerate(groups):
        g['scale_source']='KNOWN_MEASUREMENT_SD'
        g['noise']=dict(settings['future_noise'],acquisition_id=f'observation-{i}')
    return groups,settings


def calibrated(offsets=(-.08,0.,.08),weights=(.25,.5,.25)):
    return {'kind':'CALIBRATED_INTENSITY_AVERAGE','kernel':{'offsets_mm':list(offsets),'weights':list(weights),'source':'INDEPENDENT_CALIBRATION','reference':'Known physical-coordinate reference calibration'}}


def candidate():
    return {'slit_width_um':20.,'slit_separation_um':180.,'center_shift_mm':.12,'amplitude@0':1.,'background@0':.04}


def test_legacy_plan_and_residual_objective_unchanged():
    groups,cfg,_=data();groups[0].pop('observation',None);before=m.plan(groups,cfg)
    assert 'statistical_protocol' not in before and 'observation' not in before['groups'][0]
    m.verify_plan(before)
    doubled=copy.deepcopy(groups);doubled.append(copy.deepcopy(groups[0]));doubled[1]['dataset']['intensity'][1]+=.003
    doubled[1]['dataset']['sha256']=digest({k:v for k,v in doubled[1]['dataset'].items() if k!='sha256'})
    old=engine.run(m.plan(doubled,cfg));explicit=engine.run(m.plan(doubled,dict(cfg,weighting=oc.EQUAL_MSE)))
    assert old['estimated_parameters']==explicit['estimated_parameters'] and old['best_cost']==explicit['best_cost']
    assert 'statistical_protocol' not in old
    assert 'Fisher' in explicit['statistical_protocol']['scale_interpretation']


def test_independent_repeat_information_and_duplicate_rejection():
    groups,cfg,_=data();groups,cfg=independent(groups,cfg);params=candidate()
    before=gd.information(groups,cfg,params)
    second,_,_=data(seed=100);second[0]['noise']=dict(groups[0]['noise'],acquisition_id='new-independent-exposure');second[0]['scale_source']='KNOWN_MEASUREMENT_SD'
    params.update({'amplitude@1':1.,'background@1':.04})
    after=gd.information(groups+second,cfg,params)
    for key in before['scales']:
        assert after['scales'][key]==pytest.approx(before['scales'][key]/np.sqrt(2),rel=1e-6)
    duplicate=copy.deepcopy(groups[0]);duplicate['noise']['acquisition_id']='renamed-file'
    with pytest.raises(ValueError,match='复制'):m.plan(groups+[duplicate],cfg)


def test_split_same_acquisition_is_mergeable_without_extra_information():
    groups,cfg,raw=data(count=80);groups,cfg=independent(groups,cfg)
    header,*lines=raw.splitlines();parts=[]
    for i,chunk in enumerate((lines[:40],lines[40:])):
        g=copy.deepcopy(groups[0]);g['raw_file']=f'fragment-{i}.csv'
        g['dataset']=observations.parse_csv(header+'\n'+'\n'.join(chunk),source_kind='SYNTHETIC_TEACHING',source_name='frozen development case');parts.append(g)
    with pytest.raises(ValueError,match='先合并'):m.plan(parts,cfg)
    combined=oc.merge_acquisition_fragments(parts,cfg)
    m.plan(combined['groups'],cfg)
    before=gd.information(groups,cfg,candidate());after=gd.information(combined['groups'],cfg,candidate())
    assert after==before and len(m.layout(combined['groups'],cfg)[0])==5
    assert len(combined['raw_csv_by_file'])==1
    with pytest.raises(ValueError,match='重复'):oc.merge_acquisition_fragments([parts[0],parts[0]],cfg)


@pytest.mark.parametrize('mutation',[lambda g:g.pop('noise'),lambda g:g['noise'].update(independent=False),lambda g:g['noise'].update(sigma=-1),lambda g:g['noise'].update(reference=''),lambda g:g.update(scale_source='DECLARED_NUMERICAL_SCALE')])
def test_noise_requires_evidence_and_units(mutation):
    groups,cfg,_=data();groups,cfg=independent(groups,cfg);mutation(groups[0])
    with pytest.raises(ValueError):m.plan(groups,cfg)


def test_robust_units_and_future_point_counts_are_explicit():
    groups,cfg,_=data(m.GAUSSIAN,count=21);groups,cfg=independent(groups,cfg)
    cfg['loss']='soft_l1'
    with pytest.raises(ValueError,match='f_scale_units'):m.plan(groups,cfg)
    cfg['f_scale_units']='STANDARDIZED_NOISE_SD';m.plan(groups,cfg)
    cfg['loss']='linear';params={'waist_radius_um':80.,'waist_z_mm':40.}
    five=gd.information(groups,cfg,params,np.linspace(-100,180,5))
    many=gd.information(groups,cfg,params,np.linspace(-100,180,81))
    assert many['scales']['waist_z_mm']<five['scales']['waist_z_mm']
    cfg.pop('future_noise')
    with pytest.raises(ValueError,match='future_noise'):gd.information(groups,cfg,params,np.linspace(-100,180,5))


def test_known_kernel_nonuniform_coordinates_and_no_padding():
    groups,cfg,_=data();g=groups[0];g['observation']=calibrated();pars=dict(cfg['fixed'],slit_width_um=20.,slit_separation_um=180.,center_shift_mm=.12,amplitude=.9,background=.06)
    xx=np.array([-4.,-.8,-.79,0.,.002,.4,3.9])
    predicted=m.predict_observation(xx,pars,m.SLIT,g)
    expected=sum(w*m.predict(xx-delta,pars,m.SLIT) for delta,w in zip([-.08,0,.08],[.25,.5,.25]))
    assert np.allclose(predicted,expected,atol=1e-15)
    assert predicted[-1]==pytest.approx(m.predict_observation([xx[-1]],pars,m.SLIT,g)[0],abs=1e-15)
    g['observation']['kernel']['weights']=[1.,1.,1.]
    with pytest.raises(ValueError,match='归一'):m.plan(groups,cfg)
    g['observation']=calibrated((-20.,20.),(.5,.5))
    with pytest.raises(ValueError,match='近轴'):m.plan(groups,cfg)


def test_kernel_does_not_apply_to_gaussian_or_change_fixed_physics():
    groups,cfg,_=data(m.GAUSSIAN);groups[0]['observation']=calibrated()
    with pytest.raises(ValueError,match='仅适用'):m.plan(groups,cfg)
    groups,cfg,_=data();groups[0]['observation']={'kind':'UNKNOWN'}
    plan=m.plan(groups,cfg);result=engine.run(plan)
    assert result['observation_assessment'][0]['status']=='OBSERVATION_ASSUMPTION_NOT_VERIFIED'
    assert not any('BLUR' in flag for flag in result['warnings'])


def test_disagreement_envelope_uses_the_public_calibration():
    groups,cfg,_=data();groups[0]['observation']=calibrated();params=candidate();names,_,_=m.layout(groups,cfg)
    x=np.linspace(-3,3,81);_,envelope=gd.disagreement(x,cfg,[params],names,group=groups[0])
    p=m.values([params[k] for k in names],names,cfg);p.update(amplitude=1.,background=0.)
    expected=m.predict_observation(x,p,m.SLIT,groups[0])
    assert np.allclose(envelope['min'],expected) and not np.allclose(envelope['min'],m.predict(x,p,m.SLIT))


def test_future_sensitivity_does_not_rewrite_existing_measurements():
    groups,cfg,_=data();groups,cfg=independent(groups,cfg);saved=copy.deepcopy((groups,cfg));params=candidate()
    x=np.linspace(-4,4,81)
    bright=gd.information(groups,cfg,params,x,future_assumption={'noise_multiplier':.75,'amplitude_multiplier':1.2})
    dim=gd.information(groups,cfg,params,x,future_assumption={'noise_multiplier':1.5,'amplitude_multiplier':.8})
    assert bright['scales']['slit_width_um']<dim['scales']['slit_width_um'] and (groups,cfg)==saved
    cfg['fixed']['amplitude']=1.;cfg['bounds'].pop('amplitude')
    low=gd.information(groups,cfg,params,x,future_assumption={'noise_multiplier':1.,'amplitude_multiplier':.8})
    high=gd.information(groups,cfg,params,x,future_assumption={'noise_multiplier':1.,'amplitude_multiplier':1.2})
    assert low['scales']==high['scales']
