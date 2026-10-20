import copy,csv,io
from photonguard.experiments.report import comparison_csv,curve_csv,compare_versions


def case():
    return {'id':'test','domain':'film','plan':{'goal':{'metric':'reflectance','operator':'>=','target':.8,'wavelength_um':.633}},
            'result':{'ranking':['c1'],'candidates':[{'id':'c1','parameters':{'wavelengths_um':[.633]},'all_checks_passed':True,
                'goal':{'metric':'reflectance','unit':'fraction','operator':'>=','value':.91,'target':.8,'met':True,
                        'source':{'kind':'TMM_SAMPLE','label':'TMM实际采样','engine':'tmm'}},
                'verification':{'numerical_status':'NUMERICAL_PASS','goal_meep':{'metric':'reflectance','value':.909,'met':True}},
                'data':{'x':[.633,.65],'x_label':'wavelength_um','y_label':'fraction','series':[{'label':'R','y':[.91,.92]}]}}]}}


def test_table_keeps_independent_values_separate_and_curve_rows_are_actual_samples():
    state=case();rows=list(csv.DictReader(io.StringIO(comparison_csv(state).decode('utf-8-sig'))))
    assert rows[0]['value']=='0.91' and rows[0]['meep_value']=='0.909' and rows[0]['source_kind']=='TMM_SAMPLE'
    points=list(csv.DictReader(io.StringIO(curve_csv(state).decode('utf-8-sig'))))
    assert [(x['x'],x['y']) for x in points]==[('0.633','0.91'),('0.65','0.92')]


def test_comparison_uses_same_parameters_and_metric_not_candidate_number_alone():
    before=case();after=copy.deepcopy(before)
    after['plan']['goal']['target']=.95;after['result']['candidates'][0]['goal']['met']=False
    comparison=compare_versions(before,after)
    assert comparison['rows'][0]['difference']==0
    assert comparison['rows'][0]['previous_goal_met'] is True and comparison['rows'][0]['goal_met'] is False
    after['result']['candidates'][0]['parameters']['wavelengths_um']=[.65]
    assert compare_versions(before,after)['rows']==[]
    after['plan']['goal']['wavelength_um']=.65
    assert compare_versions(before,after)['status']=='DIFFERENT_METRIC_OR_WAVELENGTH'


def test_csv_strings_are_not_executable_formulas():
    state=case();state['result']['candidates'][0]['id']='=2+2'
    row=list(csv.DictReader(io.StringIO(comparison_csv(state).decode('utf-8-sig'))))[0]
    assert row['candidate_id']=="'=2+2"
