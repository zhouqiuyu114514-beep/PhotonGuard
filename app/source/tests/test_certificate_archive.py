import copy,hashlib,json,shutil
from pathlib import Path
import pytest
from photonguard.certificate_archive import ARCHIVE,overview,render

@pytest.mark.parametrize('ident,phrase',[
    ('efficiency','不是转换效率'),('order','另一个任务'),('length','新证书'),('geometry','新模型哈希'),
    ('unknown','不猜测'),('window','不能重放旧批准'),('history','不把旧报告改成 PASS'),('replay','新增求解 0')])
def test_eight_deterministic_simulated_user_questions(ident,phrase):
    # Scripted comprehension cases: no human participant, no model or solver.
    value=overview();answer=next(q['answer'] for q in value['questions'] if q['id']==ident)
    assert phrase in answer
    assert value['applies_to_current_case'] is False
    assert value['archive_actions']=={'new_solver_calls':0,'new_paid_AI_calls':0,'human_participants':0}

def test_archive_has_three_independent_verdicts():
    value=overview()
    assert value['historical']['verification_status']=='INCONCLUSIVE'
    assert value['historical']['design_goal_status']=='NOT_EVALUATED'
    assert value['strict']['decision']=='EXCLUDED_FOR_THIS_FROZEN_MODEL'
    assert value['strict']['phase_factor_upper']<.8
    assert value['design']['status']=='NO_FEASIBLE_CANDIDATE_OBSERVED_IN_THIS_WINDOW'
    assert all(r['strict_certificate']=='NOT_STARTED' for r in value['design']['candidates'])
    page=render(value)
    assert page.count('data-trial=')==8 and '不是转换效率' in page and '不计为 AI 修复成功' in page
    assert 'F ≤ 0.000499072' in page and '<style>' not in page

def test_tampered_archive_and_new_model_refused(tmp_path):
    root=tmp_path/'archive';shutil.copytree(ARCHIVE,root)
    path=root/'original-certificate.json';value=json.loads(path.read_text());value['continuous_model_hash']='a'*64;path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='ARCHIVE_BYTES'):overview(root)
    manifest=json.loads((root/'manifest.json').read_text());manifest['files'][path.name]={'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='ORIGINAL_CERTIFICATE_BINDING'):overview(root)

def test_product_http_archive_is_read_only(tmp_path):
    import http.client,threading
    from photonguard.workflow import make_server
    with make_server(tmp_path/'workspace',port=0,allow_workers=False) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
        for path,expected in [('/research-certificate','研究档案'),('/api/research-certificate','SAVED_RESEARCH_ARCHIVE')]:
            conn.request('GET',path);response=conn.getresponse();body=response.read().decode()
            assert response.status==200 and expected in body
        assert server.store.list_cases()==[]
        conn.request('GET','/assets/certificate-report.css');response=conn.getresponse()
        assert response.status==200 and b'grid-template-columns' in response.read()
        conn.close();server.shutdown();thread.join()
