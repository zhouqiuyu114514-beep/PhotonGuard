import copy
import pytest
from test_inverse_journeys import store,act
from photonguard.workflow import WorkflowError
from photonguard.experiments import contrast_calibration as c,observation_group as ow,inverse_models as m,observation_contract as oc


def test_independent_observer_estimates_only_one_frequency_and_retains_nonuniqueness():
    data,lesson=c.teaching(8101);out=c.analyze(data)
    assert out['type']=='CONTRAST_AT_FREQUENCY'
    assert out['estimated_contrast_transfer']==pytest.approx(lesson['known_teaching_transfer'],abs=.002)
    assert out['kernel_reconstruction'] is None and out['confidence_interval'] is None
    assert lesson['maximum_noiseless_difference']<2e-15
    assert len({r['compatible_transfer'] for r in lesson['without_dark_equivalent_family']})==3
    assert not any(k in data for k in ('kernel','truth','known_teaching_transfer'))
    with pytest.raises(ValueError):oc.validate_observation({'observation':{'kind':'CALIBRATED_INTENSITY_AVERAGE','kernel':out}},m.SLIT)


@pytest.mark.parametrize('change',[
    lambda d:d.update(input_contrast=None),lambda d:d.update(frequency_per_mm=None),
    lambda d:d.update(position_unit='pixel'),lambda d:d.update(linear_response=False),lambda d:d.update(saturated=True),
    lambda d:d['dark'].update(config_id='different'),lambda d:d['dark'].update(capture_id=d['reference']['capture_id']),
    lambda d:d.update(dark_intensity=[]),lambda d:d.update(x_mm=[0.]*61),
    lambda d:d.update(x_mm=[float(i) for i in range(61)]),
    lambda d:d.update(reference_intensity=[.07]*61),
])
def test_missing_incomparable_or_degenerate_data_is_not_certified(change):
    data,_=c.teaching();change(data)
    with pytest.raises(ValueError):c.analyze(data)


def test_above_passive_range_preserved_not_clipped_or_claimed_verified():
    data,_=c.teaching();data['input_contrast']=.1;out=c.analyze(data)
    assert out['estimated_contrast_transfer']>1 and out['status']=='OUTSIDE_PASSIVE_RANGE_NEEDS_REVIEW'


def test_product_calibration_requires_approval_keeps_root_limits_and_raw_evidence(store):
    s=ow.create(store,{'model':m.SLIT,'teaching':True});before=copy.deepcopy(s['inverse_ledger'])
    s=act(store,s,'inverse_calibration_example');inputs=s['calibration_draft']['inputs']
    assert not s.get('contrast_calibration') and s['inverse_ledger']==before
    with pytest.raises(WorkflowError):act(store,s,'inverse_calibration_run',inputs=inputs)
    s=act(store,s,'inverse_calibration_run',inputs=inputs,approve=True)
    assert s['contrast_calibration']['type']==c.TYPE and s['groups'][0]['observation']=={'kind':'POINT_SAMPLE'}
    assert all(s['inverse_ledger'][k]==v for k,v in before.items())
    assert s['inverse_ledger']['calibration_runs_reserved']==1
    ow.verify(store,s);child=ow.revise(store,s);ow.verify(store,child)
    child=act(store,child,'inverse_calibration_run',inputs=inputs,approve=True)
    assert ow.root_record(store,child)['inverse_ledger']['calibration_runs_reserved']==2
    with pytest.raises(WorkflowError):act(store,child,'inverse_calibration_run',inputs=inputs,approve=True)


def test_failed_signal_attempt_preserves_raw_and_consumes_one_small_run(store):
    s=ow.create(store,{'model':m.SLIT,'teaching':True});data,_=c.teaching();data['reference_intensity']=[.07]*61
    out=act(store,s,'inverse_calibration_run',inputs=data,approve=True)
    assert out['calibration_attempt']['status']=='REJECTED' and not out.get('contrast_calibration')
    assert out['inverse_ledger']['calibration_runs_reserved']==1
    assert (store.folder(s['id'])/'calibrations/1/input.json').is_file()


def test_tampered_calibration_evidence_is_rejected(store):
    s=ow.create(store,{'model':m.SLIT,'teaching':True});data,_=c.teaching()
    out=act(store,s,'inverse_calibration_run',inputs=data,approve=True)
    out['contrast_calibration']['estimated_contrast_transfer']=.3;store.save(out)
    with pytest.raises(WorkflowError):ow.verify(store,out)
