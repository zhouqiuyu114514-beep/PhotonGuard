"""A pause preserves the current draft and cannot reuse a previous judgment."""
import copy
import pytest
from photonguard.workflow import WorkflowStore,WorkflowError
from photonguard.novice import TEMPLATE_TEXT

def test_pause_saves_current_material_and_survives_restart(tmp_path):
    store=WorkflowStore(tmp_path/'data',allow_workers=False)
    try:
        s=store.create('novice-specified')
        s=store.action(s['id'],{'type':'novice-material','expected_revision':s['revision'],'text':TEMPLATE_TEXT})
        raw=store._load(s['id']);raw['novice']['model_attempt']={'status':'SYNTHETIC_TEST_MARKER'};store._save(raw);s=store.get(s['id'])
        changed=TEMPLATE_TEXT.replace('膜厚为300 nm。','膜厚为510 nm。')
        paused=store.action(s['id'],{'type':'novice-pause','expected_revision':s['revision'],'text':changed})
        assert paused['paused_reason'] and paused['novice']['original_text']==changed
        assert paused['novice']['task']['layers'][0]['thickness_um']==.51
        assert not paused['novice'].get('model_attempt') and paused['intake']['confirmation'] is None
        assert not paused['approval'] and not paused['runs'] and not list((tmp_path/'data').rglob('task.lock.json'))
        with pytest.raises(WorkflowError):store.action(s['id'],{'type':'novice-ai-review','expected_revision':paused['revision'],'approve_data':True})
        ident=s['id']
    finally:store.close()
    again=WorkflowStore(tmp_path/'data',allow_workers=False)
    try:
        restored=again.get(ident);assert restored['paused_reason'] and restored['novice']['original_text']==changed
        resumed=again.action(ident,{'type':'resume','expected_revision':restored['revision']})
        assert not resumed['paused_reason'] and resumed['novice']['original_text']==changed and resumed['approval'] is None
    finally:again.close()

def test_stale_or_invalid_pause_does_not_overwrite_current_material(tmp_path):
    store=WorkflowStore(tmp_path/'data',allow_workers=False)
    try:
        s=store.create('novice-specified');old=s['revision']
        s=store.action(s['id'],{'type':'novice-material','expected_revision':old,'text':TEMPLATE_TEXT})
        before=copy.deepcopy(store._load(s['id']))
        for version,text in [(old,'stale text'),(s['revision'],'')]:
            with pytest.raises(WorkflowError):store.action(s['id'],{'type':'novice-pause','expected_revision':version,'text':text})
            assert store._load(s['id'])==before
    finally:store.close()

def test_teaching_material_cannot_be_changed_by_pause(tmp_path):
    store=WorkflowStore(tmp_path/'data',allow_workers=False)
    try:
        s=store.create('novice-teaching');before=copy.deepcopy(store._load(s['id']))
        with pytest.raises(WorkflowError):store.action(s['id'],{'type':'novice-pause','expected_revision':s['revision'],'text':'膜厚为999 nm。'})
        assert store._load(s['id'])==before
    finally:store.close()
