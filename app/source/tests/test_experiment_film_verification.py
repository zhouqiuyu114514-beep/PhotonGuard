"""Coverage/claim checks; mocked workers are not physical Meep evidence."""
import csv
import json
from pathlib import Path

import pytest

from photonguard.core import task_problem, candidate_problem, verify_lock
from photonguard.experiments import film_verification as fv


def candidate(wave=None):
    return {'id': 'candidate-1', 'parameters': {
        'layers': [{'n': 2.4, 'thickness_um': .633/(4*2.4)}, {'n': 1.45, 'thickness_um': .633/(4*1.45)}],
        'wavelengths_um': wave or [.55,.6,.633,.7,.75]}}


def point_goal(wavelength=.633):
    return {'metric': 'reflectance', 'operator': '>=', 'target': .2, 'wavelength_um': wavelength}


def test_point_projection_includes_exact_goal_without_claiming_full_band():
    task, recipe, coverage = fv._prepare(candidate(), point_goal())
    assert task_problem(task) is None
    assert candidate_problem(recipe) is None
    assert coverage['requested_meep_wavelengths_um'][1] == .633
    assert coverage['kind'] == 'POINT_GOAL_ONLY'
    assert task['nfreq'] == 3
    assert recipe['numerics']['resolution'] == 320
    assert len(recipe['layers']) == 2
    assert recipe['origin']['generated_code_executed'] is False


@pytest.mark.parametrize('wavelength', [.5,5])
def test_boundary_point_is_an_actual_endpoint(wavelength):
    task, recipe, coverage = fv._prepare(candidate([wavelength]), point_goal(wavelength))
    assert task_problem(task) is None
    assert wavelength in coverage['requested_meep_wavelengths_um']
    assert .5 <= task['wavelength_um'][0] < task['wavelength_um'][1] <= 5


def test_band_projection_requires_original_uniform_actual_points():
    goal = {'metric':'reflectance_min','operator':'>=','target':.1}
    task, recipe, coverage = fv._prepare(candidate([.55,.6,.65,.7,.75]), goal)
    assert coverage['kind'] == 'SAME_DISCRETE_GRID'
    assert coverage['requested_meep_wavelengths_um'] == [.55,.6,.65,.7,.75]
    assert task['nfreq'] == 5


@pytest.mark.parametrize('waves', [[.55,.6,.633,.7,.75],[.6,.7]])
def test_nonuniform_or_short_band_stops_without_running(monkeypatch,tmp_path,waves):
    monkeypatch.setattr(fv, 'run_case', lambda *a,**k: pytest.fail('unsupported coverage started Meep'))
    result = fv.verify_film(candidate(waves), {'metric':'reflectance_mean','operator':'>=','target':.1}, tmp_path)
    assert result['status'] == 'UNSUPPORTED_COVERAGE'
    assert result['resources']['actual_fdtd_runs'] == 0
    assert result['goal_meep']['met'] is None


def mocked_runner(status):
    def run(task_path, candidate_path, lock_path, out_root, max_fdtd_runs):
        task=json.loads(Path(task_path).read_text());recipe=json.loads(Path(candidate_path).read_text())
        assert max_fdtd_runs == 8
        assert verify_lock(task,json.loads(Path(lock_path).read_text()))
        out=Path(out_root)/'mock-run';out.mkdir(parents=True)
        lo,hi=task['wavelength_um'];count=task['nfreq']
        wave=[lo+(hi-lo)*i/(count-1) for i in range(count)]
        with (out/'spectrum.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['frequency','wavelength_um','R','T','R_reference','T_reference'])
            writer.writeheader()
            for w in reversed(wave):writer.writerow(dict(frequency=1/w,wavelength_um=w,R=.25,T=.75,R_reference=.25,T_reference=.75))
        report={'status':status,'checks':[{'id':'mock','status':status}],
                'environment':{'meep_actual_version':'MOCK_ONLY'},
                'resource_usage':{'fdtd_runs':8,'fdtd_attempts_reserved':8,'wall_seconds':.1,'peak_worker_rss_kib':100,'workers':'mock'}}
        (out/'report.json').write_text(json.dumps(report));(out/'manifest.json').write_text('{}');(out/'report.html').write_text('mock')
        return report,out
    return run


@pytest.mark.parametrize('legacy,numerical,met', [('PASS','NUMERICAL_PASS',True),('FAIL','NUMERICAL_FAIL',None),('INCONCLUSIVE','NUMERICAL_INCONCLUSIVE',None)])
def test_completed_numerical_and_goal_status_are_distinct(monkeypatch,tmp_path,legacy,numerical,met):
    monkeypatch.setattr(fv,'run_case',mocked_runner(legacy))
    monkeypatch.setattr(fv,'verify_evidence',lambda p:True)
    result=fv.verify_film(candidate(),point_goal(),tmp_path)
    assert result['status']=='RUN_COMPLETED'
    assert result['numerical_status']==numerical
    assert result['goal_meep']['met'] is met
    assert result['goal_meep']['raw_threshold_met'] is True
    assert result['coverage']['complete_for_goal'] is True
    assert result['coverage']['covers_all_fast_samples'] is False
    assert result['resources']['actual_fdtd_runs']==8
    assert result['solver_policy']['max_memory_mib']==1536
    assert result['report']['sha256']


def test_uniform_band_claim_uses_observed_meep_grid(monkeypatch,tmp_path):
    monkeypatch.setattr(fv,'run_case',mocked_runner('PASS'));monkeypatch.setattr(fv,'verify_evidence',lambda p:True)
    result=fv.verify_film(candidate([.55,.6,.65,.7,.75]),{'metric':'reflectance_mean','operator':'>=','target':.2},tmp_path)
    assert result['coverage']['covers_all_fast_samples'] is True
    assert result['goal_meep']['value']==.25
    assert result['goal_meep']['met'] is True


def test_missing_goal_point_is_not_interpolated():
    with pytest.raises(ValueError,match='uniquely present'):
        fv._prepare(candidate(),point_goal(.65))


def test_existing_evidence_is_never_overwritten(tmp_path):
    (tmp_path/'keep.txt').write_text('existing evidence')
    with pytest.raises(ValueError,match='empty'):
        fv.verify_film(candidate(),point_goal(),tmp_path)
    assert (tmp_path/'keep.txt').read_text()=='existing evidence'


def test_corrupt_worker_manifest_is_rejected(monkeypatch,tmp_path):
    monkeypatch.setattr(fv,'run_case',mocked_runner('PASS'));monkeypatch.setattr(fv,'verify_evidence',lambda p:False)
    with pytest.raises(ValueError,match='manifest'):
        fv.verify_film(candidate(),point_goal(),tmp_path)