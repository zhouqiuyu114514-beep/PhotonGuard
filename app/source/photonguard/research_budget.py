"""Stricter research soft limit attached to the original cumulative 20 CNY ledger."""
from decimal import Decimal
from datetime import datetime,timezone
from pathlib import Path
import hashlib
from .core import load
from .workflow import write_once

REFERENCE='research-plan-20261007-development-v1'
NAME='research-plan-20261007-development.json'

def prepare(ledger,phase):
    path=Path(phase)/NAME
    with ledger._locked():
        state=ledger._read(require_existing=True)
        if state['pending'] is not None or state['halted']:raise ValueError('Unsettled phase cannot begin a research window.')
        if not path.exists():
            write_once(path,{'schema_version':1,'reference':REFERENCE,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'financial_approval_sha256':state['approval_sha256'],'baseline_attempts':state['attempts'],
                'baseline_reserved_cny':state['reserved_cny'],'baseline_ledger_sha256':hashlib.sha256(ledger.path.read_bytes()).hexdigest(),
                'new_cost_soft_limit_cny':'5','maximum_new_development_requests':12,
                'owner_authorization':'2026-10-07 owner adopted CODEX_下一阶段任务书.md; stage soft cap, not a new financial allowance',
                'evaluation_not_yet_started':True,'old_ledger_reset':False,'worst_reservation_unchanged':True})
    guard=Guard(path);guard.check(ledger.snapshot(),Decimal(ledger.snapshot()['reserved_cny']))
    return path,guard.sha256

class Guard:
    def __init__(self,path,expected_sha256=None):
        self.path=Path(path);self.sha256=hashlib.sha256(self.path.read_bytes()).hexdigest();self.plan=load(self.path)
        if expected_sha256 is not None and self.sha256!=expected_sha256:raise ValueError('Research plan binding changed.')
        p=self.plan
        if p.get('reference')!=REFERENCE or p.get('new_cost_soft_limit_cny')!='5' or p.get('maximum_new_development_requests')!=12 or p.get('old_ledger_reset') is not False or p.get('worst_reservation_unchanged') is not True:
            raise ValueError('Research window differs; no renewal or reset.')
        if type(p.get('baseline_attempts')) is not int or p['baseline_attempts']<0 or Decimal(p['baseline_reserved_cny'])<0:
            raise ValueError('Research baseline invalid.')

    def check(self,state,next_reserved_cny):
        if hashlib.sha256(self.path.read_bytes()).hexdigest()!=self.sha256:raise ValueError('Research plan changed after binding.')
        p=self.plan;spent=Decimal(state['reserved_cny'])-Decimal(p['baseline_reserved_cny'])
        calls=state['attempts']-p['baseline_attempts']
        if (state['approval_sha256']!=p['financial_approval_sha256'] or calls<0 or spent<0
            or calls>p['maximum_new_development_requests'] or Decimal(next_reserved_cny)-Decimal(p['baseline_reserved_cny'])>Decimal(p['new_cost_soft_limit_cny'])):
            raise ValueError('Research window exceeds bound or cumulative history moved backwards.')

    def __call__(self,state,next_reserved_cny):
        self.check(state,next_reserved_cny)
        if state['attempts']-self.plan['baseline_attempts']>=self.plan['maximum_new_development_requests']:
            raise ValueError('Research development request cap reached; no automatic additional calls.')
