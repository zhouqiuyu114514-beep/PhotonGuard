"""No financial reset; reserve-time soft guard rejects before counters mutate."""
from datetime import datetime,timezone
from decimal import Decimal
import json
import pytest
from photonguard.research_budget import Guard,REFERENCE
from photonguard.development_phase import ledger_for

def plan(path):
    value={'reference':REFERENCE,'financial_approval_sha256':'binding','baseline_attempts':27,'baseline_reserved_cny':'4.138184000027',
        'new_cost_soft_limit_cny':'5','maximum_new_development_requests':12,'old_ledger_reset':False,'worst_reservation_unchanged':True}
    path.write_text(json.dumps(value));return Guard(path)

def state(calls=27,cost='4.138184000027'):return {'approval_sha256':'binding','attempts':calls,'reserved_cny':cost}

def test_worst_reservation_still_required_inside_new_window(tmp_path):
    guard=plan(tmp_path/'plan.json');guard(state(),Decimal('6.268104000028'))
    with pytest.raises(ValueError):guard(state(29,'7.138184000027'),Decimal('9.268104000028'))

def test_request_cap_history_and_changed_plan_stop(tmp_path):
    path=tmp_path/'plan.json';guard=plan(path)
    with pytest.raises(ValueError):guard(state(39),Decimal('4.138184000027'))
    with pytest.raises(ValueError):guard(state(26),Decimal('4.138184000027'))
    with pytest.raises(ValueError):guard(state(28,'4.0'),Decimal('4.2'))
    value=json.loads(path.read_text());value['baseline_attempts']=28;path.write_text(json.dumps(value))
    with pytest.raises(ValueError):guard(state(28),Decimal('4.138184000027'))

def test_atomic_stage_guard_blocks_before_ledger_mutation(tmp_path):
    checked=datetime.now(timezone.utc).isoformat();ledger=ledger_for(tmp_path,checked)
    ledger._write(ledger._empty());before=ledger.path.read_bytes();received=[]
    def stop(snapshot,next_cny):
        received.append((snapshot,next_cny));raise ValueError('Stage bound')
    ledger.reservation_guard=stop
    with pytest.raises(ValueError):ledger.reserve_worst(True)
    assert ledger.path.read_bytes()==before and len(received)==1
    assert received[0][0]['attempts']==0 and received[0][1]==ledger.worst_quote()[1]
