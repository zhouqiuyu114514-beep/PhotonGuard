import hashlib
from pathlib import Path
import pytest
from research.goal_certificate.evidence_resolver import EvidenceResolver
from research.goal_certificate.packet_replay import verify_packet

def bound():return {'path':'/missing/original worker.py','bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest()}

@pytest.mark.parametrize('name',['中文 目录一','第二个 folder'])
def test_relocation_does_not_require_original(tmp_path,name):
    root=tmp_path/name;root.mkdir();p=root/'worker.py';p.write_bytes(b'abc')
    p.chmod(0o444);root.chmod(0o555)
    try:
        item=EvidenceResolver(root,{bound()['path']:'worker.py'}).resolve(bound())
        assert item.path==p and item.original_receipt==bound()
    finally:root.chmod(0o755)

@pytest.mark.parametrize('alias',['../escape','/absolute','C:/host','..\\escape'])
def test_escape_refused(tmp_path,alias):
    with pytest.raises(ValueError,match='ESCAPE'):EvidenceResolver(tmp_path,{bound()['path']:alias}).resolve(bound())

def test_wrong_alias_missing_and_size(tmp_path):
    r=EvidenceResolver(tmp_path,{bound()['path']:'wrong'})
    with pytest.raises(ValueError,match='MISSING'):r.resolve(bound())
    (tmp_path/'wrong').write_bytes(b'xyz')
    with pytest.raises(ValueError,match='HASH'):r.resolve(bound())
    (tmp_path/'wrong').write_bytes(b'abcd')
    with pytest.raises(ValueError,match='SIZE'):r.resolve(bound())
    with pytest.raises(ValueError,match='UNMAPPED'):EvidenceResolver(tmp_path,{}).resolve(bound())

def test_symlink_escape(tmp_path):
    outside=tmp_path/'outside';outside.write_bytes(b'abc');root=tmp_path/'packet';root.mkdir()
    (root/'alias').symlink_to(outside)
    with pytest.raises(ValueError,match='ESCAPE'):EvidenceResolver(root,{bound()['path']:'alias'}).resolve(bound())

def test_output_conflict_precedes_replay(tmp_path):
    out=tmp_path/'existing';out.write_text('keep')
    with pytest.raises(ValueError,match='OUTPUT_ALREADY_EXISTS'):verify_packet(tmp_path/'missing',out)
    assert out.read_text()=='keep'
    with pytest.raises(ValueError,match='OUTPUT_INSIDE'):verify_packet(tmp_path,tmp_path/'new')
    assert not (tmp_path/'new').exists()
