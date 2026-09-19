"""Read the real Codex skill catalog without logging in or running a model."""

import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    not os.environ.get("CODEX_BINARY"), reason="set CODEX_BINARY to test a real CLI"
)
def test_codex_discovers_shared_skills(tmp_path: Path) -> None:
    binary = shutil.which(os.environ["CODEX_BINARY"])
    assert binary, "CODEX_BINARY must point to an installed Codex CLI"
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".codex").mkdir()
    # Same canonical sources as the image's /etc/codex/skills symlink.
    skills_dir = ROOT / "paper-reproduce-skills/skills"
    (tmp_path / ".agents/skills").symlink_to(skills_dir, target_is_directory=True)
    proc = subprocess.Popen(
        [binary, "app-server"],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "CODEX_HOME": str(tmp_path / ".codex"),
            "PATH": os.environ["PATH"],
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)

    def request(ident: int, method: str, params: dict) -> dict:
        proc.stdin.write(
            json.dumps({"id": ident, "method": method, "params": params}) + "\n"
        )
        proc.stdin.flush()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not selector.select(timeout=1):
                continue
            line = proc.stdout.readline()
            assert line, "Codex app-server exited before returning its skill catalog"
            message = json.loads(line)
            if message.get("id") == ident:
                assert "error" not in message, message
                return message["result"]
        pytest.fail(f"Codex app-server timed out: {method}")

    try:
        request(
            1,
            "initialize",
            {"clientInfo": {"name": "paper-reproducer-test", "version": "1"}},
        )
        proc.stdin.write(json.dumps({"method": "initialized"}) + "\n")
        proc.stdin.flush()
        catalog = request(
            2, "skills/list", {"cwds": [str(tmp_path)], "forceReload": True}
        )
        group = catalog["data"][0]
        assert not group["errors"]
        skills = {skill["name"]: skill for skill in group["skills"]}
        expected = {
            f"paper-reproduce:{path.parent.name}"
            for path in skills_dir.glob("*/SKILL.md")
        }
        assert expected <= skills.keys()
        entry = skills["paper-reproduce:reimplement"]
        assert entry["enabled"]
        assert entry["interface"]["defaultPrompt"].startswith(
            "Use $paper-reproduce:reimplement"
        )
    finally:
        selector.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
