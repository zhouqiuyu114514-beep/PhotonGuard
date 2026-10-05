"""Viewer/report regression tests. Runnable with unittest or pytest."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from photonguard.report import render_report, spectrum_chart
from photonguard.ui import EvidenceError, EvidenceStore, make_server


def sample_report(**overrides):
    report = {
        "run_id": "original-001", "case_id": "air-film-air", "status": "FAIL",
        "created_at": "2026-10-05T12:00:00Z", "task_hash": "a" * 64,
        "candidate_hash": "b" * 64,
        "backend": {"mode": "rules_only", "actual_llm_calls": 0},
        "resource_usage": {"fdtd_runs": 2, "wall_seconds": 1.234},
        "checks": [{"id": "energy", "status": "FAIL", "summary": "Energy is outside tolerance",
                    "metrics": {"max_energy_error": 0.2}}],
        "assumptions": ["lossless", "normal incidence"],
        "limitations": ["1D only"], "files": {"spectrum": "spectrum.csv"},
    }
    report.update(overrides)
    return report


SPECTRA = [{"frequency": 0.5, "wavelength_um": 2.0, "R": 0.2, "T": 0.8,
            "R_reference": 0.21, "T_reference": 0.79},
           {"frequency": 1.0, "wavelength_um": 1.0, "R": 0.1, "T": 0.9,
            "R_reference": 0.11, "T_reference": 0.89}]


class ReportTests(unittest.TestCase):
    def test_report_has_real_backend_scope_and_metrics(self):
        document = render_report(sample_report(), SPECTRA)
        self.assertIn("AI 未连接", document)
        self.assertIn("rules_only", document)
        self.assertIn("max_energy_error", document)
        self.assertIn("1D · 无损 · 无色散 · 正入射", document)
        self.assertIn("<svg", document)
        self.assertNotIn("<script", document)
        self.assertNotIn('src="http', document)

    def test_untrusted_fields_never_become_html(self):
        attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        report = sample_report(case_id=attack, run_id=attack, task_hash=attack,
                               candidate_hash=attack, created_at=attack,
                               assumptions=[attack], limitations=[attack],
                               checks=[{"id": attack, "status": attack, "summary": attack,
                                        "metrics": {attack: attack}}],
                               files={"link": "javascript:alert(1)"}, patch=attack,
                               backend={"mode": attack, "actual_llm_calls": attack},
                               resource_usage={"fdtd_runs": attack})
        document = render_report(report, [])
        self.assertNotIn("<script", document)
        self.assertNotIn("<img", document)
        self.assertNotIn('href="javascript:', document)
        self.assertIn("&lt;script&gt;", document)

    def test_all_four_statuses_and_unknown_status(self):
        for status in ("PASS", "FAIL", "INCONCLUSIVE", "UNSUPPORTED"):
            self.assertIn(f'class="badge {status}"', render_report(sample_report(status=status), []))
        self.assertIn('class="badge INCONCLUSIVE"', render_report(sample_report(status="made up"), []))

    def test_empty_or_invalid_spectra(self):
        for spectra in ([], [{"wavelength_um": "NaN", "R": 1}],
                        [{"wavelength_um": 1, "R": "<svg onload=alert(1)>"}]):
            self.assertNotIn("<svg", spectrum_chart(spectra))
        document = spectrum_chart([{"wavelength_um": 1, "R": "inf", "T": 0.2}])
        self.assertIn("<svg", document)
        self.assertNotIn("nan", document.lower())

    def test_missing_and_malformed_optional_fields(self):
        document = render_report({"checks": None, "resource_usage": [], "backend": "bad"}, [])
        self.assertIn("INCONCLUSIVE", document)
        self.assertIn("未记录", document)

    def test_extreme_and_single_point_spectra_do_not_crash(self):
        for wavelength in (1, 1e308, -1e308, 1e-310):
            chart = spectrum_chart([{"wavelength_um": wavelength, "R": 0.5}])
            self.assertIn("<circle", chart)
        chart = spectrum_chart([{"wavelength_um": -1e308, "R": 0.5},
                                {"wavelength_um": 1e308, "R": 0.5}])
        self.assertIn("Invalid plot range", chart)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "artifacts" / "original-001"
        self.run.mkdir(parents=True)
        (self.run / "report.json").write_text(json.dumps(sample_report()), encoding="utf-8")
        (self.run / "spectrum.csv").write_text("frequency,wavelength_um,R,T,R_reference,T_reference\n.5,2,.2,.8,.21,.79\n", encoding="utf-8")
        (self.run / "raw").mkdir()
        (self.run / "raw" / "solver.log").write_text("simulation finished\n", encoding="utf-8")
        self.store = EvidenceStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_artifacts_empty(self):
        store = EvidenceStore(self.root / "missing")
        self.assertEqual(store.runs(), [])
        self.assertEqual(store.cases(), [])

    def test_project_and_artifacts_roots(self):
        self.assertEqual(self.store.runs()[0]["run_id"], "original-001")
        self.assertEqual(EvidenceStore(self.root / "artifacts").runs(), self.store.runs())
        self.assertEqual(self.store.cases()[0]["case_id"], "air-film-air")
        self.assertEqual(self.store.spectrum("original-001")[0]["R"], ".2")

    def test_traversal_and_symlinks_denied(self):
        for run_id in ("..", "../secret", "/etc", "x/../../x", "a\\b", "a..b"):
            with self.assertRaises(EvidenceError):
                self.store.report(run_id)
        for name in ("../secret.txt", "/etc/passwd", "raw/../../secret.txt", "a\\b.txt"):
            with self.assertRaises(EvidenceError):
                self.store.download("original-001", name)
        outside = self.root / "secret.txt"
        outside.write_text("secret")
        (self.run / "leak.txt").symlink_to(outside)
        with self.assertRaises(EvidenceError) as raised:
            self.store.download("original-001", "leak.txt")
        self.assertEqual(raised.exception.status, 403)
        (self.root / "artifacts" / "alias").symlink_to(self.run, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            self.store.report("alias")
        self.assertNotIn("alias", [run["run_id"] for run in self.store.runs()])

    def test_file_listing_includes_raw_but_never_symlinks_or_binary(self):
        (self.run / "ignore.bin").write_bytes(b"\x00\x01")
        (self.run / "escape.txt").symlink_to(self.run / "report.json")
        files = [file["name"] for file in self.store.files("original-001")]
        self.assertIn("raw/solver.log", files)
        self.assertIn("report.json", files)
        self.assertNotIn("ignore.bin", files)
        self.assertNotIn("escape.txt", files)

    def test_corrupt_report_visible_as_inconclusive(self):
        (self.run / "report.json").write_text("{not json")
        listed = self.store.runs()[0]
        self.assertEqual(listed["status"], "INCONCLUSIVE")
        self.assertFalse(listed["readable"])
        with self.assertRaises(EvidenceError) as raised:
            self.store.report("original-001")
        self.assertEqual(raised.exception.status, 422)

    def test_missing_spectrum_allowed_but_missing_run_is_not(self):
        (self.run / "spectrum.csv").unlink()
        self.assertEqual(self.store.spectrum("original-001"), [])
        with self.assertRaises(EvidenceError):
            self.store.spectrum("does-not-exist")


class EndpointTests(StoreTests):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        super().tearDown()

    def request(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_home_report_and_json_endpoints(self):
        for path in ("/", "/api/runs", "/api/cases", "/api/health", "/api/runs/original-001",
                     "/api/runs/original-001/spectrum", "/api/runs/original-001/files", "/reports/original-001"):
            with self.subTest(path=path):
                status, headers, payload = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertNotIn("Access-Control-Allow-Origin", headers)
                self.assertTrue(payload)
        _, _, payload = self.request("/api/runs")
        self.assertFalse(json.loads(payload)["ai_connected"])

    def test_downloads_are_attachments(self):
        status, headers, data = self.request("/api/runs/original-001/files/raw/solver.log")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"simulation finished\n")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(headers["Content-Type"], "application/octet-stream")

    def test_comparison_and_same_record_warning(self):
        status, _, data = self.request("/compare?original=original-001&repaired=original-001")
        self.assertEqual(status, 200)
        self.assertIn("当前选择了同一条记录".encode(), data)

    def test_encoded_path_traversal_denied(self):
        for path in ("/api/runs/%2e%2e", "/api/runs/..%2fsecret", "/reports/%252e%252e",
                     "/api/runs/original-001/files/%2e%2e/secret.txt",
                     "/api/runs/original-001/files/raw%5c..%5csecret.txt"):
            with self.subTest(path=path):
                self.assertIn(self.request(path)[0], (400, 404))

    def test_dns_rebinding_host_blocked(self):
        status, _, _ = self.request("/", headers={"Host": f"attacker.example:{self.server.server_port}"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("/", headers={"Host": f"127.0.0.1@attacker.example:{self.server.server_port}"})
        self.assertEqual(status, 403)

    def test_mutating_methods_rejected(self):
        original = (self.run / "report.json").read_bytes()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(self.request("/api/runs/original-001", method)[0], 405)
        self.assertEqual(original, (self.run / "report.json").read_bytes())

    def test_unknown_run_not_found_and_head(self):
        self.assertEqual(self.request("/reports/missing")[0], 404)
        status, _, data = self.request("/", "HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"")

    def test_network_bind_is_refused(self):
        for host in ("0.0.0.0", "::", "192.168.1.2", "example.com"):
            with self.assertRaises(ValueError):
                make_server(self.root, host, 0)


if __name__ == "__main__":
    unittest.main()
