"""Intent preparation never promotes script observations to approved physics."""
from pathlib import Path

import pytest

from photonguard.cli import main
from photonguard.core import load, verify_lock, write_json
from photonguard.script_import import preview_bytes

ROOT = Path(__file__).parents[1]
RAW = (ROOT / "examples/script_import/film_n2.py").read_bytes()


@pytest.fixture
def inputs(tmp_path):
    raw = RAW.replace(b"mp.Medium(index=n)", b"mp.Medium(epsilon=n)")
    candidate = preview_bytes(raw)["candidate"]
    cp = tmp_path / "candidate.json"
    tp = tmp_path / "task.json"
    write_json(cp, candidate)
    write_json(tp, load(ROOT / "examples/film_n2/task.json"))
    return cp, tp


def test_prepare_keeps_all_intent_unknown_and_original_untouched(inputs, tmp_path):
    cp, _ = inputs
    before = cp.read_bytes()
    out = tmp_path / "review"
    assert main(["prepare-task", str(cp), "--out", str(out)]) == 0
    task = load(out / "task.draft.json")
    assert all(value is None for value in task["physics"].values())
    assert task["layers"] == [{"n": None, "thickness_um": None}]
    assert task["units_um"] is None and task["nfreq"] is None
    assert task["wavelength_um"] == [None, None] and task["sources"] == []
    observations = load(out / "script-observations.json")
    assert observations["script_layers"][0]["material_kind"] == "epsilon"
    assert observations["script_layers"][0]["material_value"] == 2
    assert observations["task_approved"] is False
    assert set(x.name for x in out.iterdir()) == {"task.draft.json", "script-observations.json", "REVIEW.zh.md"}
    assert cp.read_bytes() == before
    assert main(["prepare-task", str(cp), "--out", str(out)]) == 3
    assert cp.read_bytes() == before


def test_incomplete_draft_cannot_be_confirmed(inputs, tmp_path, capsys, monkeypatch):
    cp, _ = inputs
    monkeypatch.setattr("photonguard.cli.run_case", lambda *a: pytest.fail("No solver expected"))
    out = tmp_path / "review"
    assert main(["prepare-task", str(cp), "--out", str(out)]) == 0
    lock = tmp_path / "lock.json"
    assert main(["confirm", str(out / "task.draft.json"), "--lock", str(lock), "--approve"]) == 3
    error = capsys.readouterr().err
    assert "physics.dimensions" in error and "layers.0.n" in error and "sources" in error
    assert not lock.exists()


def test_confirm_preserves_intended_material_mismatch(inputs, tmp_path):
    cp, tp = inputs
    before = {p: p.read_bytes() for p in (cp, tp)}
    lock = tmp_path / "lock.json"
    assert main(["confirm", str(tp), "--candidate", str(cp), "--lock", str(lock), "--approve"]) == 0
    assert verify_lock(load(tp), load(lock))
    assert load(tp)["layers"][0]["n"] == 2
    assert load(cp)["layers"][0]["material_value"] == 2
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("change", ["spectrum", "physics", "scale", "receipt", "recipe"])
def test_invalid_confirmation_creates_no_lock(inputs, tmp_path, change):
    cp, tp = inputs
    task, candidate = load(tp), load(cp)
    if change == "spectrum": task["nfreq"] = 43
    elif change == "physics": task["physics"]["dimensions"] = 2
    elif change == "scale": task["units_um"] = .001
    elif change == "receipt": candidate["origin"]["script_import"]["source_sha256"] = "0" * 64
    else: candidate["layers"][0]["material_value"] = 4
    write_json(tp, task)
    write_json(cp, candidate)
    lock = tmp_path / "lock.json"
    assert main(["confirm", str(tp), "--candidate", str(cp), "--lock", str(lock), "--approve"]) == 3
    assert not lock.exists()


@pytest.mark.parametrize("kind", ["existing", "input", "symlink"])
def test_confirmation_cannot_overwrite_locks_or_inputs(inputs, tmp_path, kind):
    cp, tp = inputs
    lock = tp if kind == "input" else tmp_path / "lock.json"
    if kind == "existing": lock.write_bytes(b"original lock evidence")
    if kind == "symlink": lock.symlink_to(tp)
    before = lock.read_bytes()
    assert main(["confirm", str(tp), "--candidate", str(cp), "--lock", str(lock), "--approve"]) == 3
    assert lock.read_bytes() == before


def test_prepare_rejects_changed_import_receipt(inputs, tmp_path):
    cp, _ = inputs
    candidate = load(cp)
    candidate["layers"][0]["material_value"] = 4
    write_json(cp, candidate)
    out = tmp_path / "review"
    assert main(["prepare-task", str(cp), "--out", str(out)]) == 3
    assert not out.exists()


def test_confirmation_still_requires_explicit_approval(inputs, tmp_path):
    cp, tp = inputs
    lock = tmp_path / "lock.json"
    with pytest.raises(SystemExit) as error:
        main(["confirm", str(tp), "--candidate", str(cp), "--lock", str(lock)])
    assert error.value.code == 2 and not lock.exists()


def test_confirm_regular_json_task_remains_supported(inputs, tmp_path):
    _, tp = inputs
    lock = tmp_path / "lock.json"
    assert main(["confirm", str(tp), "--lock", str(lock), "--approve"]) == 0
    assert verify_lock(load(tp), load(lock))
