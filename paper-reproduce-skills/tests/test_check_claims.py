"""Unit tests for scripts/check_claims.py (stdlib unittest only)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_claims  # noqa: E402


class TestParseTolerance(unittest.TestCase):
    def test_rel_percent(self):
        width, warn = check_claims.parse_tolerance("rel±10%", 0.40)
        self.assertAlmostEqual(width, 0.04)
        self.assertIsNone(warn)

    def test_abs(self):
        width, warn = check_claims.parse_tolerance("abs±0.3", 30.0)
        self.assertAlmostEqual(width, 0.3)
        self.assertIsNone(warn)

    def test_abs_pt_suffix(self):
        width, warn = check_claims.parse_tolerance("abs±2pt", 85.0)
        self.assertAlmostEqual(width, 2.0)
        self.assertIsNone(warn)

    def test_ascii_variant(self):
        width, warn = check_claims.parse_tolerance("rel+-5%", 100.0)
        self.assertAlmostEqual(width, 5.0)
        self.assertIsNone(warn)

    def test_unparseable_falls_back(self):
        width, warn = check_claims.parse_tolerance("whatever", 0.40)
        self.assertAlmostEqual(width, 0.04)
        self.assertIn("fell back", warn)


class TestInferDirection(unittest.TestCase):
    def test_higher(self):
        self.assertEqual(check_claims.infer_direction({"metric_name": "PSNR (dB)"}), "higher_better")
        self.assertEqual(check_claims.infer_direction({"metric_name": "mIoU"}), "higher_better")

    def test_lower(self):
        self.assertEqual(check_claims.infer_direction({"metric_name": "Chamfer Distance (DTU mean)"}), "lower_better")
        self.assertEqual(check_claims.infer_direction({"metric_name": "LPIPS"}), "lower_better")

    def test_arrow_beats_keyword(self):
        self.assertEqual(check_claims.infer_direction({"metric_name": "score ↓"}), "lower_better")

    def test_explicit_field_wins(self):
        self.assertEqual(
            check_claims.infer_direction({"metric_name": "PSNR", "direction": "lower_better"}),
            "lower_better")

    def test_unknown(self):
        self.assertEqual(check_claims.infer_direction({"metric_name": "mystery metric"}), "unknown")

    def test_word_boundary(self):
        # 'cd' must not match inside another word
        self.assertEqual(check_claims.infer_direction({"metric_name": "encoded score"}), "unknown")
        self.assertEqual(check_claims.infer_direction({"metric_name": "CD (mm)"}), "lower_better")


class TestJudge(unittest.TestCase):
    def _claim(self, metric, target, direction=None):
        c = {"metric_name": metric, "paper_target": target}
        if direction:
            c["direction"] = direction
        return c

    def test_higher_better(self):
        c = self._claim("PSNR", 30.0)
        self.assertEqual(check_claims.judge(c, 30.5, 0.3), "matched")
        self.assertEqual(check_claims.judge(c, 29.8, 0.3), "within_tolerance")
        self.assertEqual(check_claims.judge(c, 29.0, 0.3), "missed")

    def test_lower_better(self):
        c = self._claim("Chamfer", 0.40)
        self.assertEqual(check_claims.judge(c, 0.375, 0.04), "matched")
        self.assertEqual(check_claims.judge(c, 0.43, 0.04), "within_tolerance")
        self.assertEqual(check_claims.judge(c, 0.50, 0.04), "missed")

    def test_unknown_never_matched(self):
        c = self._claim("mystery", 1.0)
        self.assertEqual(check_claims.judge(c, 1.0, 0.1), "within_tolerance")
        self.assertEqual(check_claims.judge(c, 0.5, 0.1), "missed")


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        os.makedirs(os.path.join(self.root, "reports", "eval"))
        self.eval_log = os.path.join("reports", "eval", "run.log")
        with open(os.path.join(self.root, self.eval_log), "w", encoding="utf-8") as f:
            f.write("epoch 30 done\nfinal chamfer_mean: 0.375 on DTU\npsnr: 29.8\n")
        self.analysis = os.path.join(self.root, "analysis.json")
        with open(self.analysis, "w", encoding="utf-8") as f:
            json.dump({"paper_claims": [
                {"id": "dtu_chamfer", "metric_name": "Chamfer Distance (DTU mean)",
                 "paper_target": 0.40, "tolerance": "rel±10%",
                 "claim_source": "paper Table 1"},
                {"id": "psnr", "metric_name": "PSNR", "paper_target": 30.0,
                 "tolerance": "abs±0.3", "claim_source": "paper Table 2"},
                {"id": "unmeasured", "metric_name": "SSIM", "paper_target": 0.9,
                 "tolerance": "abs±0.01", "claim_source": "paper Table 2"},
            ]}, f)
        self.observed = os.path.join(self.root, "observed.json")
        self.output = os.path.join(self.root, "claims.json")

    def tearDown(self):
        self.dir.cleanup()

    def _write_observed(self, results):
        with open(self.observed, "w", encoding="utf-8") as f:
            json.dump({"results": results}, f)

    def _run(self):
        rc = check_claims.main([
            "--analysis", self.analysis, "--observed", self.observed,
            "--output", self.output, "--repo-root", self.root])
        self.assertEqual(rc, 0)
        with open(self.output, encoding="utf-8") as f:
            return json.load(f)

    def test_full_flow(self):
        self._write_observed([
            {"id": "dtu_chamfer", "observed": 0.375,
             "evidence_path": self.eval_log,
             "evidence_snippet": "final chamfer_mean: 0.375 on DTU"},
            {"id": "psnr", "observed": 29.8,
             "evidence_path": self.eval_log,
             "evidence_snippet": "psnr: 29.8"},
        ])
        out = self._run()
        by_id = {r["id"]: r for r in out["results"]}
        self.assertEqual(by_id["dtu_chamfer"]["status"], "matched")
        self.assertAlmostEqual(by_id["dtu_chamfer"]["delta_rel_pct"], -6.25)
        self.assertEqual(by_id["psnr"]["status"], "within_tolerance")
        self.assertEqual(by_id["unmeasured"]["status"], "not_evaluated")
        self.assertEqual(out["audit"]["matched"], 1)
        self.assertEqual(out["audit"]["not_evaluated"], 1)

    def test_fabricated_snippet_demoted(self):
        self._write_observed([
            {"id": "dtu_chamfer", "observed": 0.375,
             "evidence_path": self.eval_log,
             "evidence_snippet": "chamfer_mean: 0.375 (never printed)"},
        ])
        out = self._run()
        row = out["results"][0]
        self.assertEqual(row["status"], "not_evaluated")
        self.assertIn("evidence check failed", row["note"])
        self.assertTrue(out["audit"]["evidence_failures"])

    def test_observed_number_not_in_snippet(self):
        self._write_observed([
            {"id": "psnr", "observed": 30.1,
             "evidence_path": self.eval_log,
             "evidence_snippet": "psnr: 29.8"},
        ])
        out = self._run()
        by_id = {r["id"]: r for r in out["results"]}
        self.assertEqual(by_id["psnr"]["status"], "not_evaluated")

    def test_missing_evidence_file(self):
        self._write_observed([
            {"id": "psnr", "observed": 29.8,
             "evidence_path": "reports/eval/nope.log",
             "evidence_snippet": "psnr: 29.8"},
        ])
        out = self._run()
        by_id = {r["id"]: r for r in out["results"]}
        self.assertEqual(by_id["psnr"]["status"], "not_evaluated")

    def test_missing_observed_file_still_writes_output(self):
        # no _write_observed call: file absent
        out = self._run()
        self.assertEqual(len(out["results"]), 3)
        self.assertTrue(all(r["status"] == "not_evaluated" for r in out["results"]))
        self.assertTrue(any("not found" in (f["reason"] or "")
                            for f in out["audit"]["evidence_failures"]))

    def test_whitespace_normalized_snippet(self):
        self._write_observed([
            {"id": "psnr", "observed": 29.8,
             "evidence_path": self.eval_log,
             "evidence_snippet": "psnr:   29.8"},
        ])
        out = self._run()
        by_id = {r["id"]: r for r in out["results"]}
        self.assertEqual(by_id["psnr"]["status"], "within_tolerance")


if __name__ == "__main__":
    unittest.main()
