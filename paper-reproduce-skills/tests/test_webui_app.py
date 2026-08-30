"""Unit tests for templates/webui/app.py pure helpers (stdlib unittest only).

The gradio import in app.py is lazy (inside build_ui), so config loading,
command building, output collection, and job execution are testable here
without gradio installed (CI runs on a bare python3).
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "templates", "webui"))
import app  # noqa: E402


def make_config(tmpdir, **overrides):
    cfg = {
        "title": "Test UI",
        "workdir": str(tmpdir),
        "command_template": "cp {input} {output_dir}/result.png",
        "inputs": [{"name": "input", "type": "image", "label": "Input image"}],
        "outputs": [{"type": "image", "glob": "*.png", "label": "Result"}],
    }
    cfg.update(overrides)
    path = Path(tmpdir) / "webui.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


class TestLoadConfig(unittest.TestCase):
    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = app.load_config(make_config(d))
            self.assertTrue(cfg["_uses_output_dir"])
            self.assertEqual(cfg["timeout_s"], 3600)

    def test_missing_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_config(d)
            data = json.loads(path.read_text())
            del data["command_template"]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "command_template"):
                app.load_config(path)

    def test_unknown_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_config(d, command_template="run {nonexistent}")
            with self.assertRaisesRegex(ValueError, "nonexistent"):
                app.load_config(path)

    def test_unknown_input_type(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_config(
                d, inputs=[{"name": "input", "type": "audio", "label": "x"}]
            )
            with self.assertRaisesRegex(ValueError, "audio"):
                app.load_config(path)

    def test_no_output_dir_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_config(d, command_template="python demo.py --img {input}")
            cfg = app.load_config(path)
            self.assertFalse(cfg["_uses_output_dir"])

    def test_empty_outputs_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_config(d, outputs=[])
            with self.assertRaisesRegex(ValueError, "outputs"):
                app.load_config(path)


class TestBuildCommand(unittest.TestCase):
    def test_values_are_shell_quoted(self):
        cmd = app.build_command(
            "python demo.py --img {input}", {"input": "/tmp/my file (1).png"}
        )
        self.assertEqual(cmd, "python demo.py --img '/tmp/my file (1).png'")

    def test_multiple_placeholders(self):
        cmd = app.build_command(
            "run {a} {output_dir}", {"a": "x", "output_dir": "/out"}
        )
        self.assertEqual(cmd, "run x /out")


class TestRunJob(unittest.TestCase):
    def _base_cfg(self, tmpdir, template):
        path = make_config(tmpdir, command_template=template)
        return app.load_config(path)

    def test_output_dir_mode_collects_from_job_dir(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.png"
            src.write_bytes(b"fake")
            cfg = self._base_cfg(d, "cp {input} {output_dir}/result.png")
            log, outputs = app.run_job(cfg, {"input": str(src)}, Path(d) / "jobs")
            self.assertIn("[exit code: 0]", log)
            self.assertEqual([p.name for p in outputs[0]], ["result.png"])

    def test_fixed_path_mode_filters_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            stale = Path(d) / "old.png"
            stale.write_bytes(b"old")
            two_min_ago = time.time() - 120
            os.utime(stale, (two_min_ago, two_min_ago))
            cfg = self._base_cfg(d, "touch fresh.png")
            log, outputs = app.run_job(cfg, {}, Path(d) / "jobs")
            self.assertEqual([p.name for p in outputs[0]], ["fresh.png"])

    def test_nonzero_exit_returns_no_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._base_cfg(d, "false")
            log, outputs = app.run_job(cfg, {}, Path(d) / "jobs")
            self.assertIn("[exit code: 1]", log)
            self.assertEqual(outputs, {})

    def test_timeout_returns_no_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_config(d, command_template="sleep 5", timeout_s=1)
            cfg = app.load_config(path)
            log, outputs = app.run_job(cfg, {}, Path(d) / "jobs")
            self.assertIn("timed out", log)
            self.assertEqual(outputs, {})


class TestStageInputs(unittest.TestCase):
    def test_text_passthrough(self):
        cfg = {"inputs": [{"name": "prompt", "type": "text", "label": "Prompt"}]}
        values = app.stage_inputs(cfg, ["a cat"], Path("/nonexistent"))
        self.assertEqual(values, {"prompt": "a cat"})

    def test_filepath_passthrough(self):
        cfg = {"inputs": [{"name": "input", "type": "image", "label": "Img"}]}
        values = app.stage_inputs(cfg, ["/tmp/x.png"], Path("/nonexistent"))
        self.assertEqual(values, {"input": "/tmp/x.png"})

    def test_files_copied_into_directory(self):
        with tempfile.TemporaryDirectory() as d:
            srcs = []
            for i in range(2):
                p = Path(d) / f"v{i}.png"
                p.write_bytes(b"x")
                srcs.append(str(p))
            cfg = {"inputs": [{"name": "views", "type": "files", "label": "Views"}]}
            staging = Path(d) / "staging"
            values = app.stage_inputs(cfg, [srcs], staging)
            dest = Path(values["views"])
            self.assertEqual(sorted(f.name for f in dest.iterdir()), ["v0.png", "v1.png"])

    def test_missing_required_input_raises(self):
        cfg = {"inputs": [{"name": "input", "type": "image", "label": "Img"}]}
        with self.assertRaisesRegex(ValueError, "required"):
            app.stage_inputs(cfg, [None], Path("/nonexistent"))


if __name__ == "__main__":
    unittest.main()
