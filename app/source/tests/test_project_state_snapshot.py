import json
from tools.inspect_project_state import recorded_state


def save(tmp_path, value):
    folder = tmp_path / 'local-validation'
    folder.mkdir(exist_ok=True)
    (folder / 'CURRENT_STATE.json').write_text(json.dumps(value))


def test_snapshot_requires_current_clean_source_and_ledger(tmp_path):
    ledger = {'attempts': 37, 'reserved_cny': '4.422906000037', 'pending': None}
    save(tmp_path, {'source_commit': 'new', 'finance': {'ledger': ledger}, 'validation': {'full_regression': {'pytest_passed': 1014}}})
    fresh = recorded_state(tmp_path, 'new', ledger, True)
    assert fresh['status'] == 'CURRENT'
    assert fresh['recorded_validation']['full_regression']['pytest_passed'] == 1014
    assert fresh['runtime_binding_rechecked'] is False
    assert recorded_state(tmp_path, 'different', ledger, True)['status'] == 'STALE_SNAPSHOT'
    assert recorded_state(tmp_path, 'new', ledger, False)['status'] == 'STALE_SNAPSHOT'
    assert recorded_state(tmp_path, 'new', {**ledger, 'attempts': 38}, True)['status'] == 'STALE_SNAPSHOT'


def test_missing_old_and_invalid_snapshots_do_not_appear_current(tmp_path):
    assert recorded_state(tmp_path, 'new', {}, True)['status'] == 'NO_CANONICAL_SNAPSHOT'
    save(tmp_path, {'source_commit': 'old', 'linux_tests': {'passed': 718}})
    assert recorded_state(tmp_path, 'new', {}, True)['status'] == 'STALE_SNAPSHOT'
    save(tmp_path, [])
    assert recorded_state(tmp_path, 'new', {}, True)['status'] == 'UNREADABLE_CANONICAL_SNAPSHOT'
    save(tmp_path, {'finance': 'invalid'})
    assert recorded_state(tmp_path, 'new', {}, True)['status'] == 'UNREADABLE_CANONICAL_SNAPSHOT'
