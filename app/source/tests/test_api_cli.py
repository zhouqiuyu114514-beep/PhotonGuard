"""CLI preflight tests. Never access a real credential or call the network."""
from argparse import Namespace
from pathlib import Path
import pytest
from photonguard.api_cli import diagnose_api
from photonguard.core import load,write_json
ROOT=Path(__file__).parents[1]
def test_unapproved_config_stops_before_key_access(tmp_path,monkeypatch):
 def forbidden(*args,**kwargs):raise AssertionError('No credential lookup allowed before authorization')
 monkeypatch.setattr('photonguard.api_cli.os.environ.get',forbidden)
 args=Namespace(approve_data_and_cost=True,config=str(ROOT/'examples/deepseek.config.template.json'))
 with pytest.raises(ValueError,match='No approved'):diagnose_api(args)
def test_missing_explicit_flag_stops():
 with pytest.raises(ValueError,match='Explicit approval'):diagnose_api(Namespace(approve_data_and_cost=False))
def test_config_does_not_accept_embedded_key(tmp_path):
 p=tmp_path/'config.json';write_json(p,{'api_key':'TEST-NONSECRET'})
 with pytest.raises(ValueError,match='without secrets'):diagnose_api(Namespace(approve_data_and_cost=True,config=p))
