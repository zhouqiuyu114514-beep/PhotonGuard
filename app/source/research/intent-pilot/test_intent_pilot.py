"""Boundary tests for the synthetic offline proof. No model/solver needed.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import intent_pilot as pilot


HERE = Path(__file__).resolve().parent


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.bundle = pilot.read_json(HERE / "fixtures/complete.bundle.json")
        self.proposal = pilot.read_json(HERE / "fixtures/complete.mock.json")

    def sync(self):
        self.proposal["bundle_sha256"] = pilot.digest(self.bundle)

    def field(self, path):
        return next(f for f in self.proposal["fields"] if f["path"] == path)

    def fact(self, path):
        return next(f for f in self.bundle["facts"] if f["path"] == path)

    def result(self):
        return pilot.review(self.bundle, self.proposal)

    def test_complete_is_review_only_and_converts_units(self):
        result = self.result()
        fields = {f["path"]: f for f in result["fields"]}
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        for path, value in (("units_um", "1.000"), ("layers.0.thickness_um", "0.2000"),
                            ("wavelength_um.0", "0.500"), ("layers.0.n", "2")):
            self.assertEqual(fields[path]["suggested_value"], value)
        self.assertFalse(result["task_approved"])
        self.assertFalse(result["task_lock_created"])
        self.assertFalse(result["source_semantics_verified"])
        self.assertEqual(result["ignored_script_fact_ids"], ["script-n"])

    def test_unknown_conflict_and_script_fallback_stay_blank(self):
        bundle = pilot.read_json(HERE / "fixtures/needs-clarification.bundle.json")
        proposal = pilot.read_json(HERE / "fixtures/needs-clarification.mock.json")
        result = pilot.review(bundle, proposal)
        self.assertEqual(result["status"], "CLARIFICATION_REQUIRED")
        self.assertEqual(len(result["questions"]), 3)
        for field in result["fields"]:
            if field["state"] != "proposed":
                self.assertIsNone(field["suggested_value"])
        proposal["fields"][9]["evidence_ids"] = ["script-n"]
        with self.assertRaisesRegex(ValueError, "independent"):
            pilot.review(bundle, proposal)

    def test_rejects_extra_keys_at_every_nested_level(self):
        locations = [lambda: self.bundle, lambda: self.bundle["documents"][0],
                     lambda: self.bundle["facts"][0], lambda: self.bundle["facts"][0]["source"],
                     lambda: self.proposal, lambda: self.proposal["fields"][0]]
        for location in locations:
            with self.subTest(location=location):
                self.setUp()
                location()["approved"] = True
                self.sync()
                with self.assertRaises(ValueError):
                    self.result()

    def test_rejects_illegal_paths_and_value_injection(self):
        for path in ("../task.lock.json", "physics.rt_tolerance", "layers.1.n", "layers.0.epsilon"):
            with self.subTest(path=path):
                self.setUp()
                self.proposal["fields"][0]["path"] = path
                with self.assertRaises(ValueError):
                    self.result()
        self.setUp()
        self.proposal["fields"][0]["value"] = 1
        with self.assertRaises(ValueError):
            self.result()

    def test_rejects_invalid_source_reference_or_quote(self):
        for key, value in (("document_id", "missing"), ("line", 999),
                           ("line", True), ("quote", "fabricated quote")):
            with self.subTest(key=key):
                self.setUp()
                self.bundle["facts"][0]["source"][key] = value
                self.sync()
                with self.assertRaises(ValueError):
                    self.result()

    def test_rejects_unknown_wrong_field_and_duplicate_evidence(self):
        for refs in (["nonexistent"], ["spec-02"], ["spec-01", "spec-01"]):
            with self.subTest(refs=refs):
                self.proposal["fields"][0]["evidence_ids"] = refs
                with self.assertRaises(ValueError):
                    self.result()

    def test_rejects_duplicate_fact_document_and_proposal_paths(self):
        for area in ("facts", "documents", "fields"):
            with self.subTest(area=area):
                self.setUp()
                if area == "fields":
                    self.proposal["fields"][-1] = deepcopy(self.proposal["fields"][0])
                else:
                    self.bundle[area].append(deepcopy(self.bundle[area][0]))
                    self.sync()
                with self.assertRaises(ValueError):
                    self.result()

    def test_cannot_hide_conflicting_independent_fact(self):
        other = deepcopy(self.fact("layers.0.n"))
        other["id"], other["value"] = "alternate-n", 3
        self.bundle["facts"].append(other)
        self.sync()
        with self.assertRaisesRegex(ValueError, "cite all"):
            self.result()
        field = self.field("layers.0.n")
        field["evidence_ids"].append("alternate-n")
        with self.assertRaisesRegex(ValueError, "state inconsistent"):
            self.result()
        field["state"] = "conflict"
        result = self.result()
        self.assertEqual(result["status"], "CLARIFICATION_REQUIRED")

    def test_equivalent_units_are_not_a_conflict(self):
        other = deepcopy(self.fact("layers.0.thickness_um"))
        other.update(id="same-thickness", value=200, unit="nm")
        self.bundle["facts"].append(other)
        self.field("layers.0.thickness_um")["evidence_ids"].append("same-thickness")
        self.sync()
        self.assertEqual(self.result()["status"], "REVIEW_REQUIRED")

    def test_missing_units_and_unknown_values_cannot_be_guessed(self):
        for key in ("unit", "value"):
            with self.subTest(key=key):
                self.setUp()
                self.fact("layers.0.thickness_um")[key] = None
                self.sync()
                with self.assertRaisesRegex(ValueError, "state inconsistent"):
                    self.result()
                self.field("layers.0.thickness_um")["state"] = "unknown"
                self.assertEqual(self.result()["status"], "CLARIFICATION_REQUIRED")

    def test_nonfinite_and_boolean_numbers_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, "2", 10**13):
            with self.subTest(value=value):
                self.setUp()
                self.fact("layers.0.n")["value"] = value
                with self.assertRaises(ValueError):
                    pilot.validate_bundle(self.bundle)
        self.setUp()
        self.fact("nfreq")["value"] = 21.5
        with self.assertRaises(ValueError):
            pilot.validate_bundle(self.bundle)

    def test_wrong_dimensions_of_units_rejected(self):
        for unit in ("Hz", "m", "epsilon", "", [], "nm"):
            with self.subTest(unit=unit):
                self.fact("layers.0.n")["unit"] = unit
                with self.assertRaises(ValueError):
                    pilot.validate_bundle(self.bundle)

    def test_out_of_scope_requires_unsupported_state_and_no_value(self):
        for path, value in (("physics.dispersive", True), ("units_um", 2000),
                            ("layers.0.n", 6), ("nfreq", 202)):
            with self.subTest(path=path):
                self.setUp()
                self.fact(path)["value"] = value
                self.sync()
                with self.assertRaises(ValueError):
                    self.result()
                self.field(path)["state"] = "unsupported"
                result = self.result()
                self.assertEqual(result["status"], "OUT_OF_SCOPE")
                self.assertIn(path, result["scope_blockers"])
                self.assertIsNone(next(f for f in result["fields"] if f["path"] == path)["suggested_value"])

    def test_invalid_wavelength_order_clears_both_values(self):
        self.fact("wavelength_um.0")["value"] = 1000
        self.sync()
        result = self.result()
        self.assertEqual(result["questions"][0]["reason"], "invalid_order")
        self.assertEqual(len(result["questions"]), 1)
        self.assertTrue(all(f["suggested_value"] is None for f in result["fields"]
                            if f["path"].startswith("wavelength_um.")))

    def test_stale_bundle_or_fake_approval_or_missing_path_rejected(self):
        self.proposal["bundle_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.result()
        self.sync()
        self.proposal["fields"][0]["state"] = "approved"
        with self.assertRaises(ValueError):
            self.result()
        self.setUp()
        self.proposal["fields"].pop()
        with self.assertRaises(ValueError):
            self.result()

    def test_json_duplicate_keys_nonfinite_and_oversize_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                    b'{"a":1e999}', b' ' * (pilot.LIMIT_BYTES + 1)):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(ValueError):
                    pilot.loads(raw)

    def test_pure_review_cannot_write_run_process_connect_or_import_solver(self):
        before = pilot.canonical([self.bundle, self.proposal])
        initial_modules = set(sys.modules)
        with patch("builtins.open", side_effect=AssertionError("file access")), \
             patch.object(Path, "open", side_effect=AssertionError("file access")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
             patch.object(os, "system", side_effect=AssertionError("shell")):
            result = self.result()
        self.assertEqual(before, pilot.canonical([self.bundle, self.proposal]))
        self.assertEqual(result["solver_calls"], 0)
        added_modules = set(sys.modules) - initial_modules
        self.assertNotIn("meep", added_modules)
        self.assertFalse(any(name == "photonguard" or name.startswith("photonguard.")
                             for name in added_modules))

    def test_cli_treats_code_as_text_preserves_inputs_and_rejects_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sentinel = folder / "executed"
            source_text = f"__import__('pathlib').Path({str(sentinel)!r}).touch()"
            self.bundle["documents"][0]["lines"][0] = source_text
            self.bundle["facts"][0]["source"]["quote"] = source_text
            self.sync()
            inputs = [folder / "bundle.json", folder / "proposal.json"]
            for path, data in zip(inputs, (self.bundle, self.proposal)):
                path.write_text(pilot.canonical(data))
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
            command = [sys.executable, "-B", str(HERE / "intent_pilot.py"), *map(str, inputs)]
            run = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse(json.loads(run.stdout)["task_approved"])
            self.assertFalse(sentinel.exists())
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()})
            refused = subprocess.run(command + ["--approve"], capture_output=True, text=True,
                                     check=False, timeout=10)
            self.assertEqual(refused.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
