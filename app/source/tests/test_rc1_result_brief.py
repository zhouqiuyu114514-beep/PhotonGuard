import copy,json
import pytest
from photonguard.experiments.report import result_brief
from photonguard.experiments.record_view import record_view
from photonguard.experiments.summary_html import render_summary

def saved(value=87.4645778546,target=2,operator='<='):
    goal={'metric':'screen_radius_um','operator':operator,'target':target,'tolerance':.03}
    candidate={'id':'c1','parameters':{'focal_length_mm':125},'changes':{'focal_length_mm':125},'status':'RUN_COMPLETED','all_checks_passed':True,
        'goal':{**goal,'value':value,'unit':'um','met':False},'data':{'x':[0,1,2],'x_label':'mm','y_label':'um','series':[{'label':'actual','y':[3,2,4]}]}}
    return {'id':'a'*32,'revision':1,'status':'COMPLETED','domain':'gaussian','title':'<script>alert(1)</script>','spec':{'goal':goal,'known_parameters':{'wavelength_nm':710}},'plan':{'goal':goal,'goal_sampling_points':[1],'assumptions':['ideal']},'result':{'ranking':['c1'],'winner_id':'c1','candidates':[candidate],'resources':{'fast_evaluations':1}}}

@pytest.mark.parametrize('operator,target,value,gap,deviation',[('<=',2,87.4645778546,85.4645778546,85.4645778546),('>=',0,-2,2,2),('near',0,.02,0,.02),('near',0,.07,.04,.07),('minimize',0,2,None,2)])
def test_gap_uses_absolute_units_and_zero_target(operator,target,value,gap,deviation):
    b=result_brief(saved(value,target,operator));assert b['unmet_gap']==pytest.approx(gap) if gap is not None else b['unmet_gap'] is None
    assert b['absolute_deviation']==pytest.approx(deviation)
    assert b['best_label']=='焦距 125 mm'

def test_invalid_candidate_not_promoted_to_success():
    s=saved();s['result']['candidates'][0]['all_checks_passed']=False;s['result']['candidates'][0]['goal']['met']=True
    b=result_brief(s);assert b['best'] is None and b['met_count']==0 and b['valid_count']==0

def test_rescore_restore_and_sampling_are_not_new_physics():
    parent=saved();child=copy.deepcopy(parent);child['id']='b'*32;child['reuse']={'source_id':parent['id']}
    child['spec']['goal']['target']=100;child['result']['candidates'][0]['goal']['target']=100
    b=result_brief(child,parent);assert b['comparison']['rows'][0]['difference']==0 and b['operation']=='rescore' and '没有改善' in b['answers']['new_calculation']
    child['plan']['goal_sampling_points']=[2];assert result_brief(child,parent)['comparison']['rows']==[]
    child['command_receipt']={'command':{'action':'restore'}};assert result_brief(child,parent)['operation']=='restore'

def test_self_contained_html_uses_view_and_no_private_audit_or_script():
    s=saved();s['private_audit']={'key':'PRIVATE_TEST_SENTINEL','path':'/home/private/file'}
    v=record_view(s);text=render_summary(s,v).decode()
    assert v['brief']['headline'] in text and '87.46458' in text and '<svg' in text
    assert '<script>' not in text and '&lt;script&gt;' in text and 'PRIVATE_TEST_SENTINEL' not in text and '/home/private/' not in text
    assert 'src="http' not in text and 'fetch(' not in text and 'default-src' in text
    assert 'python -m photonguard.experiments.cli' in text
