"""Owner's incremental 26 CNY product phase; old counters remain immutable."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from .backend import BackendAuthorization, ApprovedRates
from .cny_budget import CnyApproval
from .gui_batch_ledger import GuiBatchLedger
from .core import digest
from .approved_gui import source_manifest, digest_file
from .workflow import write_once,atomic_json
from .workflow_model import wire

REFERENCE='photonguard-product-additional-26cny-20261009'
USD_SOURCE='https://api-docs.deepseek.com/quick_start/pricing/'
CNY_SOURCE='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'

class ProductLedger(GuiBatchLedger):
    def __init__(self, folder):
        self.folder=Path(folder)
        self.phase=json.loads((self.folder/'authorization.json').read_text())
        p=self.phase; checked=p['official_rates_checked_at']
        auth=BackendAuthorization(True,REFERENCE,'deepseek-flash',p['cumulative_cap_usd'],1000000,
            ApprovedRates('0.30','1.20',checked,USD_SOURCE))
        active=self.folder/'active-ledger.json'
        self.epoch=json.loads(active.read_text()) if active.exists() else None
        name=self.epoch['ledger_name'] if self.epoch else 'product-budget.ledger.json'
        import re
        if not re.fullmatch(r'product-budget(?:-epoch[2-9][0-9]*)?\.ledger\.json',name):raise ValueError('Invalid financial epoch path')
        super().__init__(auth,self.folder/name,CnyApproval(p['cumulative_cap_cny'],'2','8',checked,CNY_SOURCE))
        self.reservation_guard=self.guard

    def _binding(self):
        p=self.phase
        if p['reference']!=REFERENCE or p['additional_cny']!='26' or self.authorization.reference!=REFERENCE:
            raise ValueError('Product authorization differs')
        if Decimal(p['cumulative_cap_cny'])!=Decimal(p['carried']['reserved_cny'])+26:
            raise ValueError('Incremental cap differs')
        return digest({'authorization':p,'epoch':self.epoch}) if self.epoch else digest(p)

    def snapshot(self):
        with self._locked():return self._read(require_existing=True)

    def guard(self,*_):
        p=self.phase
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(p['official_rates_checked_at'])).total_seconds()
        if not 0<=age<=86400:raise ValueError('Refresh official prices before dispatch')
        if digest_file(Path(p['previous_ledger']))!=p['previous_ledger_sha256']:
            raise ValueError('Previous ledger changed; reconcile before dispatch')
        for held in (self.epoch or {}).get('held_unknown_requests',[]):
            if digest_file(self.folder/held['closed_ledger_name'])!=held['closed_ledger_sha256']:
                raise ValueError('Closed unknown-cost ledger changed')

def initialize(folder,previous,checked):
    """Called only for the explicit owner amendment, never by a model/simulator."""
    folder=Path(folder);previous=Path(previous)
    folder.mkdir(parents=True,exist_ok=False)
    old=json.loads(previous.read_text())
    if old.get('pending') is not None or old.get('halted'):raise ValueError('Old ledger unresolved')
    value={'schema_version':1,'reference':REFERENCE,'additional_cny':'26',
        'authority':'Owner explicitly authorized real DeepSeek product iteration, up to remaining 26 CNY, overriding suggested request quotas.',
        'balance_is_user_report_not_provider_verified':True,'official_rates_checked_at':checked,
        'official_sources':[USD_SOURCE,CNY_SOURCE],'peak_cny_per_million':{'input_miss':'2','output':'8'},
        'previous_ledger':str(previous.resolve()),'previous_ledger_sha256':digest_file(previous),'carried':old,
        'cumulative_cap_cny':str(Decimal(old['reserved_cny'])+26),
        'cumulative_cap_usd':str(Decimal(old['reserved_usd'])+Decimal('3.9')),
        'physical_solver_extension':False,'simulated_approval_authorizes_spending':False}
    write_once(folder/'authorization.json',value)
    ledger=ProductLedger(folder);state=ledger._empty()
    for k in ('attempts','live_provider_attempts','settled_usd','settled_cny','reserved_usd','reserved_cny'):state[k]=old[k]
    with ledger._locked():ledger._write(state)
    ledger.snapshot();return value

def retain_unknown_reservation(folder,failure_audit):
    """Close a failed epoch at its FULL upper cost, without refund or replay.

    This operator operation never erases or edits the halted original ledger.
    The owner cap, counters and full occupied cost carry into the next epoch.
    It is not exposed as a browser/model tool. Exact failed payload is blocked.
    """
    folder=Path(folder);ledger=ProductLedger(folder);audit=json.loads(Path(failure_audit).read_text())['audit']
    ledger.guard()
    with ledger._locked():
        old=ledger._read(require_existing=True)
        if not old['halted'] or old['pending'] is None or audit.get('status')!='TRANSPORT_FAILURE':raise ValueError('Only a recorded unknown transport failure can be quarantined')
        if audit['budget']['pending']!=old['pending'] or audit.get('usage') is not None:raise ValueError('Failure does not match held reservation')
        held=list((ledger.epoch or {}).get('held_unknown_requests',[]))
        held.append({'closed_ledger_name':ledger.path.name,'closed_ledger_sha256':digest_file(ledger.path),
            'reservation':old['pending'],'request_sha256':audit['request_sha256'],'failure_audit_sha256':digest_file(Path(failure_audit)),
            'cost_status':'PERMANENT_WORST_CASE_OCCUPANCY_NOT_PROVIDER_BILL','old_attempts':old['attempts']})
        epoch={'version':len(held)+1,'ledger_name':f'product-budget-epoch{len(held)+1}.ledger.json',
            'held_unknown_requests':held,'same_owner_budget':True,'refund':'0','automatic_retry':False,
            'carried_snapshot':old,'at':datetime.now(timezone.utc).isoformat()}
        write_once(folder/f'epoch-{epoch["version"]}-receipt.json',epoch)
        atomic_json(folder/'active-ledger.json',epoch)
        next_ledger=ProductLedger(folder);state=next_ledger._empty()
        for k in ('attempts','live_provider_attempts','reserved_usd','reserved_cny'):state[k]=old[k]
        state.update(settled_usd=old['reserved_usd'],settled_cny=old['reserved_cny'])
        with next_ledger._locked():next_ledger._write(state)
    return next_ledger.snapshot()

class ProductClient:
    def __init__(self,root,folder,binding,key_supplier=None):
        self.root=Path(root);self.folder=Path(folder);self.binding=Path(binding)
        self.spec=json.loads(self.binding.read_text());self.ledger=ProductLedger(folder);self.key_supplier=key_supplier
        self.preflight(False)

    def preflight(self,require_key=True):
        if self.spec['source']!=source_manifest(self.root):raise ValueError('Product source changed; retain binding and create a new version')
        if self.spec['authorization_sha256']!=digest(self.ledger.phase):raise ValueError('Authorization binding mismatch')
        if self.spec.get('financial_epoch_sha256')!=digest(self.ledger.epoch):raise ValueError('Financial epoch binding mismatch')
        self.ledger.guard();s=self.ledger.snapshot();usd,cny=self.ledger.worst_quote()
        if s['pending'] or s['halted'] or Decimal(s['reserved_cny'])+cny>Decimal(self.ledger.cny.total_budget_cny):raise ValueError('Budget pending, halted or insufficient')
        if require_key and not callable(self.key_supplier):raise ValueError('Memory credential missing')

    def status(self):
        try:self.preflight();enabled=True
        except (ValueError,OSError):enabled=False
        s=self.ledger.snapshot()
        return {'live_enabled':enabled,'mode':'PRODUCT_DEEPSEEK','model':'deepseek-flash',
            'additional_budget_cny':'26','budget_cny':self.ledger.cny.total_budget_cny,'reserved_cny':s['reserved_cny'],
            'incremental_reserved_cny':str(Decimal(s['reserved_cny'])-Decimal(self.ledger.phase['carried']['reserved_cny'])),
            'incremental_requests':s['attempts']-self.ledger.phase['carried']['attempts']}

    def complete(self,ident,payload):
        import re
        if not re.fullmatch('[A-Za-z0-9_-]{1,100}',ident):raise ValueError('Invalid request ID')
        self.preflight()
        if wire.credential_risk(payload):raise ValueError('Credential-shaped input cannot be archived or sent')
        payload_hash=wire.digest(json.dumps(payload,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode())
        if payload_hash in {x['request_sha256'] for x in (self.ledger.epoch or {}).get('held_unknown_requests',[])}:raise ValueError('Exact unknown-cost request must not be replayed')
        out=self.binding.parent/'requests'/ident
        out.mkdir(parents=True,exist_ok=False)
        write_once(out/'request.json',payload)
        write_once(out/'start.json',{'id':ident,'binding_sha256':digest(self.spec),'actor':'PRODUCT','at':datetime.now(timezone.utc).isoformat()})
        result=wire.complete(payload,self.key_supplier(),self.ledger,require_existing_ledger=True)
        write_once(out/'result.json',result)
        return result

def bind(root,folder,destination,purpose):
    ledger=ProductLedger(folder);ledger.guard()
    value={'schema_version':1,'source':source_manifest(Path(root)),
        'authorization_sha256':digest(ledger.phase),'financial_epoch_sha256':digest(ledger.epoch),'purpose':purpose,
        'endpoint':wire.ENDPOINT,'model':'deepseek-flash','automatic_solver_calls':0}
    write_once(Path(destination),value);return value

def json_payload(prompt,value):
    return {'model':'deepseek-flash','messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(value,ensure_ascii=False)}],
        'max_tokens':4096,'thinking':{'type':'disabled'},'temperature':0,'stream':False,'response_format':{'type':'json_object'}}
