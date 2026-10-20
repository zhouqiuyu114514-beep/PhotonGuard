from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import json

import pytest

from photonguard.backend import ApprovedRates, BackendAuthorization
from photonguard.cny_budget import CnyApproval, PersistentCnyLedger


def ledger(tmp_path, budget="0.28", attempts=1):
    auth = BackendAuthorization(True, "OFFLINE-CNY-TEST", "deepseek-flash", "0.042", attempts,
                                ApprovedRates("0.30", "1.20", "2026-10-06",
                                              "https://api-docs.deepseek.com/quick_start/pricing/"))
    cny = CnyApproval(budget, "2", "8", "2026-10-06",
                      "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/")
    return PersistentCnyLedger(auth, tmp_path / "budget.ledger.json", cny)


def test_cny_reservation_persists_and_rerun_never_resets(tmp_path):
    item = ledger(tmp_path)
    result = item.reserve(Decimal("0.0417792"), True)
    assert Decimal(result["reserved_cny"]) >= Decimal("0.278528")
    assert Decimal(result["reserved_cny"]) < Decimal("0.28")
    assert result["live_provider_attempts"] == 1
    assert ledger(tmp_path).snapshot() == result
    with pytest.raises(ValueError): ledger(tmp_path).reserve(Decimal("0.000001"), True)


def test_insufficient_cny_blocks_even_with_sufficient_usd(tmp_path):
    item = ledger(tmp_path, budget="0.27")
    with pytest.raises(ValueError): item.reserve(Decimal("0.0417792"), True)
    assert item.snapshot()["attempts"] == 0
    assert not item.path.exists()


def test_native_usage_estimate_and_halt_keep_full_reservation(tmp_path):
    item = ledger(tmp_path)
    item.reserve(Decimal("0.0417792"), True)
    item.halt()
    result = item.snapshot()
    assert result["halted"] is True and result["attempts"] == 1
    assert Decimal(result["reserved_cny"]) >= Decimal("0.278528")
    assert item.estimated_cny({"prompt_tokens": 100, "completion_tokens": 40}) == Decimal("0.00052")


def test_concurrent_process_compatible_instances_cannot_double_dispatch(tmp_path):
    def attempt(_):
        try:
            ledger(tmp_path).reserve(Decimal("0.0417792"), True)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    assert ledger(tmp_path).snapshot()["attempts"] == 1


@pytest.mark.parametrize("change", ["nan", "wrong_binding", "under_reserved", "duplicate", "negative"])
def test_corrupt_ledger_refuses_reuse(tmp_path, change):
    item = ledger(tmp_path)
    item.reserve(Decimal("0.0417792"), True)
    value = json.loads(item.path.read_text())
    if change == "nan": value["reserved_cny"] = "NaN"
    elif change == "wrong_binding": value["approval_sha256"] = "0" * 64
    elif change == "under_reserved": value["reserved_cny"] = "0.01"
    elif change == "negative": value["attempts"] = -1
    raw = json.dumps(value)
    if change == "duplicate": raw = raw[:-1] + ',"attempts":0}'
    item.path.write_text(raw)
    with pytest.raises(ValueError): item.reserve(Decimal("0.000001"), True)


def test_approval_tariff_change_and_symlink_are_rejected(tmp_path):
    item = ledger(tmp_path)
    item.reserve(Decimal("0.0417792"), True)
    changed = PersistentCnyLedger(item.authorization, item.path,
                                  replace(item.cny, total_budget_cny="20"))
    with pytest.raises(ValueError): changed.snapshot()
    link = tmp_path / "alias.ledger.json"
    link.symlink_to(item.path)
    with pytest.raises(ValueError): PersistentCnyLedger(item.authorization, link, item.cny).snapshot()
