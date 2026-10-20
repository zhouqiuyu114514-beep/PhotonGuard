"""Integration boundaries between synthetic facts and the stable task schema."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import export_task_draft as bridge
import intent_pilot as pilot

HERE = Path(__file__).resolve().parent


class DraftTests(unittest.TestCase):
    def inputs(self, name="complete"):
        return (pilot.read_json(HERE / "fixtures" / (name + ".bundle.json")),
                pilot.read_json(HERE / "fixtures" / (name + ".mock.json")))

    def test_native_schema_preserves_independent_values_and_exact_audit(self):
        task, result = bridge.draft(*self.inputs())
        self.assertEqual(task["layers"], [{"n": 2, "thickness_um": .2}])
        self.assertEqual(task["units_um"], 1)
        self.assertEqual(task["wavelength_um"], [.5, .9])
        self.assertIs(type(task["nfreq"]), int)
        self.assertIs(type(task["physics"]["dimensions"]), int)
        self.assertIs(type(task["physics"]["lossless"]), bool)
        self.assertIsNone(result["stable_task_schema_check"])
        self.assertFalse(result["task_approved"])
        self.assertFalse(result["task_lock_created"])
        self.assertEqual(result["ignored_script_fact_ids"], ["script-n"])
        self.assertEqual(result["fields"][10]["suggested_value"], "0.2000")

    def test_unresolved_fields_remain_blank_and_stable_confirmation_refuses(self):
        task, result = bridge.draft(*self.inputs("needs-clarification"))
        self.assertIsNone(task["layers"][0]["n"])
        self.assertIsNone(task["layers"][0]["thickness_um"])
        self.assertIsNone(task["wavelength_um"][1])
        self.assertEqual(len(result["questions"]), 3)
        self.assertIsNotNone(result["stable_task_schema_check"])
        from photonguard.task_review import confirm_task
        with tempfile.TemporaryDirectory() as tmp:
            path, lock = Path(tmp) / "draft.json", Path(tmp) / "lock.json"
            path.write_text(json.dumps(task), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未写入锁"):
                confirm_task(path, lock)
            self.assertFalse(lock.exists())

    def test_invalid_sources_and_stale_hash_rejected_before_output_creation(self):
        bundle, proposal = self.inputs()
        for mutation in ("hash", "quote", "approval"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                b, p = deepcopy(bundle), deepcopy(proposal)
                if mutation == "hash": p["bundle_sha256"] = "0" * 64
                elif mutation == "quote": b["facts"][0]["source"]["quote"] = "invented"
                else: p["approved"] = True
                bp, pp, out = Path(tmp) / "bundle.json", Path(tmp) / "proposal.json", Path(tmp) / "out"
                bp.write_text(pilot.canonical(b), encoding="utf-8")
                pp.write_text(pilot.canonical(p), encoding="utf-8")
                with self.assertRaises(ValueError): bridge.export(bp, pp, out)
                self.assertFalse(out.exists())

    def test_export_preserves_inputs_refuses_existing_directory_and_creates_no_lock(self):
        bp, pp = (HERE / "fixtures" / ("complete." + n + ".json") for n in ("bundle", "mock"))
        before = [p.read_bytes() for p in (bp, pp)]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "review"
            result = bridge.export(bp, pp, out)
            self.assertEqual(result["model_calls"], 0)
            self.assertEqual(result["solver_calls"], 0)
            self.assertEqual({p.name for p in out.iterdir()}, {
                "task.draft.json", "intent-review.json", "bundle.original.json",
                "proposal.original.json", "REVIEW.zh.md"})
            saved = {p.name: p.read_bytes() for p in out.iterdir()}
            with self.assertRaises(FileExistsError): bridge.export(bp, pp, out)
            self.assertEqual(saved, {p.name: p.read_bytes() for p in out.iterdir()})
        self.assertEqual(before, [p.read_bytes() for p in (bp, pp)])

    def test_pure_conversion_has_no_network_solver_or_process(self):
        inputs = self.inputs()
        before = pilot.canonical(inputs)
        with patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            task, result = bridge.draft(*inputs)
        self.assertEqual(pilot.canonical(inputs), before)
        self.assertFalse(result["source_semantics_verified"])
        self.assertNotEqual(task["layers"][0]["n"], 1.45)

    def test_invalid_case_id_cannot_inject_paths(self):
        for name in ("../task.lock.json", "", "approved\ntrue", 1):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bridge.draft(*self.inputs(), case_id=name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
