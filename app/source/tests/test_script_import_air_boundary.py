"""Derived-air rounding must not widen candidate policy or alter old receipts."""
import copy
import math
from pathlib import Path

import pytest

from photonguard.core import candidate_problem, load
from photonguard.script_import import preview_bytes, preview_script, validate_provenance


ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "examples/script_import/film_n2.py").read_text()


def preview(thickness=.45, air=3.0, cell=None):
    text = SOURCE.replace("d = 0.3", f"d = {thickness!r}")
    text = text.replace("air = 3.0", f"air = {air!r}")
    if cell is not None:
        text = text.replace("cell_z = d + 2 * air + 2 * pml", f"cell_z = {cell!r}")
    return preview_bytes(text.encode(), "film_n2.py")


@pytest.mark.parametrize("thickness,air,boundary", [(.45, 3.0, 3.0), (4.1, 5.0, 5.0)])
def test_exactly_one_outward_ulp_is_recorded_and_replayable(thickness, air, boundary):
    report = preview(thickness, air)
    assert report["status"] == "EXTRACTED", report["unresolved"]
    candidate = report["candidate"]
    assert candidate["numerics"]["air_um"] == boundary
    assert report["extracted_fields"]["numerics.air_um"] == boundary
    direction = -math.inf if boundary == 3 else math.inf
    assert report["numeric_normalizations"] == [{
        "field": "numerics.air_um",
        "raw_value": math.nextafter(boundary, direction),
        "normalized_value": boundary,
        "reason": "derived-air-one-ulp-outside-supported-boundary",
        "derivation": "(cell_z - total_layer_thickness - 2 * pml) / 2",
    }]
    assert candidate["origin"]["script_import"]["numeric_normalizations"] == report["numeric_normalizations"]
    assert candidate_problem(candidate) is None
    validate_provenance(candidate, load(ROOT / "examples/film_n2/task.json"))
    changed = copy.deepcopy(candidate)
    changed["origin"]["script_import"]["numeric_normalizations"][0]["raw_value"] = boundary
    with pytest.raises(ValueError, match="provenance differs"):
        validate_provenance(changed, load(ROOT / "examples/film_n2/task.json"))


@pytest.mark.parametrize("cell", [8.449999999999998, 12.450000000000003, 8.4, 12.5])
def test_more_than_one_outward_ulp_remains_unsupported(cell):
    report = preview(cell=cell)
    assert report["status"] == "UNSUPPORTED"
    assert report["candidate"] is None
    assert "Out-of-range numerical setting air_um" in report["unresolved"][0]["reason"]
    assert "numeric_normalizations" not in report


@pytest.mark.parametrize("cell", [8.450000000000001, 12.449999999999998, 10.45])
def test_legal_derived_floats_are_preserved_bit_for_bit(cell):
    expected = (cell - .45 - 2.0) / 2
    assert 3 <= expected <= 5
    report = preview(cell=cell)
    assert report["status"] == "EXTRACTED", report["unresolved"]
    assert report["candidate"]["numerics"]["air_um"].hex() == expected.hex()
    assert "numeric_normalizations" not in report
    assert "numeric_normalizations" not in report["candidate"]["origin"]["script_import"]


@pytest.mark.parametrize("air", [math.nextafter(3.0, -math.inf), math.nextafter(5.0, math.inf)])
def test_independent_candidate_validation_keeps_exact_bounds(air):
    candidate = preview_bytes(SOURCE.encode())["candidate"]
    candidate["numerics"]["air_um"] = air
    assert candidate_problem(candidate)["reason"] == "Out-of-range numerical setting air_um"


@pytest.mark.parametrize("name", ["film_n2.py", "numerical_film_scan.py", "wavelength35_index_mismatch.py"])
def test_existing_fixture_values_and_receipt_shape_are_unchanged(name):
    report = preview_script(ROOT / "examples/script_import" / name)
    assert report["status"] == "EXTRACTED"
    assert report["candidate"]["numerics"]["air_um"].hex() == (3.0).hex()
    assert "numeric_normalizations" not in report
    assert "numeric_normalizations" not in report["candidate"]["origin"]["script_import"]
