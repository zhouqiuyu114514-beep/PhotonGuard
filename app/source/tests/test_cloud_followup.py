import hashlib,json,os,subprocess,sys
from pathlib import Path
import pytest
from tools.audit_cloud_reproduction import verify_manifest,interval_margin

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('mode',['O','OO','environment'])
@pytest.mark.parametrize('entry',['bounded','direct','library'])
def test_optimized_certificate_refused_before_input_or_arithmetic(tmp_path,mode,entry):
    env=os.environ.copy();env.pop('PYTHONOPTIMIZE',None)
    flags=['-B']
    if mode=='environment':env['PYTHONOPTIMIZE']='1'
    else:flags+=['-'+mode]
    output=tmp_path/'must-not-exist.json'
    if entry=='library':args=['-c','from research.goal_certificate.interval_arithmetic import C,gershgorin; import numpy as np; print(gershgorin(C.point(np.array([[1+1j]]))))']
    else:
        mod='bounded_checker' if entry=='bounded' else 'checker'
        args=['-m','research.goal_certificate.'+mod,'--model',str(tmp_path/'missing.json'),'--pump','--output',str(output)]
    result=subprocess.run([sys.executable,*flags,*args],cwd=ROOT,env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'CERTIFICATE_OPTIMIZATION_UNSUPPORTED' in result.stderr
    assert not output.exists() and not result.stdout and 'FileNotFoundError' not in result.stderr

def test_normal_mode_rejects_nonhermitian_matrix():
    import numpy as np
    from research.goal_certificate.interval_arithmetic import C,gershgorin
    with pytest.raises(AssertionError):gershgorin(C.point(np.array([[1+1j]])))

def test_manifest_hash_check_survives_optimization(tmp_path):
    (tmp_path/'value').write_text('original');digest=hashlib.sha256(b'original').hexdigest()
    (tmp_path/'MANIFEST.json').write_text(json.dumps({'files':{'value':{'sha256':digest,'bytes':8}}}))
    assert verify_manifest(tmp_path)==1
    (tmp_path/'value').write_text('tampered')
    code='from pathlib import Path; from tools.audit_cloud_reproduction import verify_manifest; import sys; verify_manifest(Path(sys.argv[1]))'
    result=subprocess.run([sys.executable,'-B','-O','-c',code,str(tmp_path)],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'MANIFEST_HASH:value' in result.stderr

def test_manifest_rejects_unlisted_nested_file(tmp_path):
    (tmp_path/'MANIFEST.json').write_text('{"files":{}}');(tmp_path/'extra').write_text('unlisted')
    with pytest.raises(ValueError,match='MANIFEST_FILE_SET'):verify_manifest(tmp_path)

def test_saved_matrix_replay_rejects_imaginary_diagonal():
    diag=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]];zero=[[0.,0.,0.] for _ in range(3)]
    matrix={'R':{'real':[diag,diag],'imag':[zero,zero]}}
    assert interval_margin(matrix)>0
    matrix['R']['imag']=[diag,diag]
    with pytest.raises(ValueError,match='IMAG_HERMITIAN'):interval_margin(matrix)

def test_existing_output_refused_before_model_or_solver(tmp_path):
    output=tmp_path/'result.json';output.write_text('preserved')
    result=subprocess.run([sys.executable,'-B','-m','research.goal_certificate.checker','--model',str(tmp_path/'missing.json'),'--trials',str(tmp_path/'missing.npz'),'--reassemble','--output',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'OUTPUT_ALREADY_EXISTS' in result.stderr
    assert output.read_text()=='preserved' and 'FileNotFoundError' not in result.stderr

def test_pump_cli_binds_loaded_bytes_and_interpreter(tmp_path):
    from test_goal_certificate import model
    original=json.dumps(model(),indent=2).encode();path=tmp_path/'model.json';path.write_bytes(original)
    result=subprocess.run([sys.executable,'-B','-m','research.goal_certificate.bounded_checker','--model',str(path),'--pump'],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    receipt=json.loads(result.stdout);binding=receipt['execution_binding']
    assert receipt['status']=='MODEL_PUMP_UPPER_VERIFIED'
    assert binding['model_file_sha256']==hashlib.sha256(original).hexdigest()
    assert binding['optimization_level']==0 and binding['debug_checks_enabled']
    assert binding['trial_file_sha256'] is None
    assert binding['implementation_files_sha256']['checker.py']==hashlib.sha256((ROOT/'research/goal_certificate/checker.py').read_bytes()).hexdigest()
