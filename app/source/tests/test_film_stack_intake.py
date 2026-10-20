"""Independent explicit inputs and simulated confirmation, no provider calls."""
import copy, json
import pytest
from photonguard.core import load, digest, POLICY_HASH
from photonguard.workflow_intake import prepare, apply
from photonguard.task_mapping import project
from tools.serve_ai_repair import OPTIONS

def document():
    task=load('examples/multilayer/task.json')
    return {'schema':'film_stack_task_v2','case_id':'STACK-DEVELOPMENT','incident_direction':'+z','layer_order':'incident_to_exit',
        'units_um':1,'physics':{**task['physics'],'linear':True,'field_component':'Ex'},
        'layers':[{**v,'source':f'独立公开任务卡第{i+1}层'} for i,v in enumerate(task['layers'])],
        'wavelength_um':task['wavelength_um'],'nfreq':41,'sampling':{'kind':'equal_wavelength'},'source':'独立公开多层合成开发任务卡'}

def reviewed(doc):
    intake=apply(prepare('stack',json.dumps(doc,ensure_ascii=False)),{'type':'intake-review','mode':'mock'})
    return apply(intake,{'type':'intake-confirm','approve':True,'result_sha256':intake['result_sha256']})

def test_explicit_stack_preserves_full_order_units_and_sources():
    doc=document();task,record,context=project(reviewed(doc),OPTIONS)
    assert task['layers']==[{k:v for k,v in r.items() if k!='source'} for r in doc['layers']]
    assert record['mapping_adapter']=='film_stack_task_v2' and record['task_approved'] is False
    assert task['sampling']=={'kind':'equal_wavelength'} and len(task['sources'])==4

@pytest.mark.parametrize('mutation',['unknown','order','source','anisotropy','loss','outside','too_many','script_source','unit','sampling'])
def test_incomplete_conflicting_or_unsupported_data_cannot_confirm(mutation):
    doc=document()
    if mutation=='unknown':doc['layers'][1]['n']=None
    if mutation=='order':doc['layer_order']='exit_to_incident'
    if mutation=='source':doc['layers'][1]['source']=''
    if mutation=='anisotropy':doc['physics']['isotropic']=False
    if mutation=='loss':doc['physics']['lossless']=False
    if mutation=='outside':doc['physics']['n_exit']=1.44
    if mutation=='too_many':doc['layers']*=3
    if mutation=='script_source':doc['source']='仅待检脚本的AST提取'
    if mutation=='unit':doc['units_um']=1000
    if mutation=='sampling':doc['sampling']={'kind':'unknown'}
    intake=apply(prepare('stack',json.dumps(doc,ensure_ascii=False)),{'type':'intake-review','mode':'mock'})
    assert not intake['result']['confirmable']
    with pytest.raises(ValueError):apply(intake,{'type':'intake-confirm','approve':True,'result_sha256':intake['result_sha256']})

def test_changed_layer_after_confirmation_is_not_silently_mapped():
    intake=reviewed(document());intake['result']['independent_document']['layers'].reverse()
    with pytest.raises(ValueError):project(intake,OPTIONS)

def test_explicit_natural_layer_list_no_default_missing_materials():
    text='''空间维度为1D。
入射角为0 deg。
相对磁导率为1。
所有介质无损。
所有介质各向同性。
所有介质无色散。
所有介质线性。
场分量为Ex。
膜层数量为2。
入射折射率为1。
出射折射率为1。
真空波长下界为1300 nm。
真空波长上界为1700 nm。
等波长采样点数为35。
1个Meep单位为1 um。
入射方向为+z。
层序为从入射侧到出射侧。
第1层：折射率为1.45，厚度为213 nm，出处为独立任务书第一层。
第2层：折射率为2.1，厚度为167 nm，出处为独立任务书第二层。'''
    intake=apply(prepare('natural-stack',text),{'type':'intake-review','mode':'mock'})
    assert intake['result']['confirmable']
    assert intake['result']['normalized_task']['layers'][0]['thickness_um']==0.213
    missing=apply(prepare('missing-stack',text.replace('所有介质线性。','')),{'type':'intake-review','mode':'mock'})
    assert not missing['result']['confirmable']
    conflict=apply(prepare('bad-order',text.replace('第2层：','第1层：')),{'type':'intake-review','mode':'mock'})
    assert not conflict['result']['confirmable']
