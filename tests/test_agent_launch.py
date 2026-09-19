"""Exercise the launch boundary without Docker, a GPU, or real credentials."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "bootstrap.sh"
ENTRYPOINT = ROOT / "paper-reproduce-skills/entrypoint.sh"

# tmux executes the generated command through a shell, just like the real server.
FAKE_TOOL = r"""
import json, os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
if name == "docker" and args[:2] == ["image", "inspect"]:
    if "--format" in args:
        if "host.uid" in args[-1]:
            print(f"{os.getuid()}:{os.getgid()}")
        else:
            print(os.environ.get("IMAGE_AGENT", args[2].removeprefix("paper-reproduce-")))
elif name == "git" and args[0] == "clone":
    pathlib.Path(args[-1], ".git").mkdir(parents=True)
elif name == "tmux" and args[0] in {"new-session", "new-window"}:
    sys.exit(subprocess.call(["bash", "-c", args[-1]]))
elif name == "flock":
    sys.exit(subprocess.call(args[2:]))
elif name == "nvidia-smi":
    if os.environ.get("FAKE_GPU") != "1":
        sys.exit(1)
    if args == ["-L"]:
        print("GPU 0: test GPU")
    elif args:
        print("0")
elif name == "gh":
    sys.exit(1)
"""


@pytest.fixture
def launch_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in (
        "docker",
        "git",
        "tmux",
        "flock",
        "nvidia-smi",
        "gh",
        "claude",
        "codex",
        "curl",
        "pixi",
    ):
        script = bin_dir / name
        script.write_text(f"#!{sys.executable}\n{FAKE_TOOL}")
        script.chmod(0o755)
    # Do not let the bootstrap inventory probe see the user's asset registry.
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALL_LOG": str(tmp_path / "calls.jsonl"),
        "WORKSPACE_DIR": str(tmp_path / "work spaces"),
        "LOCK_DIR": str(tmp_path / "gpu locks"),
        "MANUAL_ASSETS_DIR": str(tmp_path / "no-assets"),
    }
    return env


def run(
    script: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def calls(env: dict[str, str], tool: str) -> list[list[str]]:
    path = Path(env["CALL_LOG"])
    records = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return [record[1:] for record in records if record[0] == tool]


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("batch", [False, True])
def test_agent_mounts_and_launch(
    launch_env: dict[str, str], agent: str, batch: bool
) -> None:
    home = Path(launch_env["HOME"])
    (home / ".claude.json").write_text("{}")
    codex_home = home / "codex config"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text('{"test": "dummy-credential"}')
    (codex_home / "config.toml").write_text('model = "test-model"\n')
    launch_env["CODEX_HOME"] = str(codex_home)
    urls = (
        ["https://example.test/one.git", "https://example.test/two.git"]
        if batch
        else ["https://example.test/one.git"]
    )
    result = run(BOOTSTRAP, launch_env, "--agent", agent, *urls)
    assert result.returncode == 0, result.stderr
    runs = [args for args in calls(launch_env, "docker") if args[0] == "run"]
    assert len(runs) == len(urls)
    for args in runs:
        assert f"PAPER_REPRODUCER_AGENT={agent}" in args
        assert f"{launch_env['WORKSPACE_DIR']}:/workspaces" in args
        assert "REPORT_LANG=ja" in args
        if agent == "codex":
            assert "--model" not in args and "--effort" not in args
            assert f"{codex_home}:/home/claude/.codex" in args
            assert "CODEX_HOME=/home/claude/.codex" in args
            assert not any(":/home/claude/.claude" in arg for arg in args)
        else:
            assert args[-4:] == ["--model", "opus[1m]", "--effort", "xhigh"]
            assert f"{home}/.claude:/home/claude/.claude" in args
            assert f"{home}/.claude.json:/home/claude/.claude.json" in args
            assert not any(":/home/claude/.codex" in arg for arg in args)
    expected_command = (
        "$paper-reproduce:reimplement" if agent == "codex" else "/reimplement"
    )
    assert expected_command in result.stderr
    assert (
        "dummy-credential"
        not in result.stdout + result.stderr + Path(launch_env["CALL_LOG"]).read_text()
    )


@pytest.mark.parametrize(
    ("selected", "options", "expected"),
    [
        (None, [], "claude"),
        ("codex", [], "codex"),
        ("codex", ["--agent=claude"], "claude"),
    ],
)
def test_agent_default_and_precedence(launch_env, selected, options, expected) -> None:
    if selected:
        launch_env["PAPER_REPRODUCER_AGENT"] = selected
    result = run(BOOTSTRAP, launch_env, *options, "https://example.test/one.git")
    assert result.returncode == 0, result.stderr
    launched = next(args for args in calls(launch_env, "docker") if args[0] == "run")
    assert f"PAPER_REPRODUCER_AGENT={expected}" in launched


@pytest.mark.parametrize("options", [["--agent", "invalid"], ["--agent"], ["--agent="]])
def test_invalid_agent_fails_before_side_effects(launch_env, options) -> None:
    result = run(BOOTSTRAP, launch_env, *options)
    assert result.returncode != 0
    assert "--agent" in result.stderr
    assert not Path(launch_env["CALL_LOG"]).exists()


@pytest.mark.parametrize(
    "agent_label", ["codex", "claude", "claude,codex", "<no value>"]
)
def test_old_image_rebuilt_for_codex(launch_env, agent_label) -> None:
    launch_env["IMAGE_AGENT"] = agent_label
    result = run(BOOTSTRAP, launch_env, "--agent=codex", "https://example.test/one.git")
    assert result.returncode == 0, result.stderr
    builds = [args for args in calls(launch_env, "docker") if args[0] == "build"]
    assert bool(builds) == (agent_label != "codex")


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("image_override", [None, "custom-reproducer:local"])
def test_build_selects_agent_and_image(launch_env, agent, image_override) -> None:
    if image_override:
        launch_env["IMAGE_NAME"] = image_override
    result = run(
        BOOTSTRAP,
        launch_env,
        "--agent",
        agent,
        "--rebuild",
        "https://example.test/one.git",
    )
    assert result.returncode == 0, result.stderr
    image_name = image_override or f"paper-reproduce-{agent}"
    build = next(args for args in calls(launch_env, "docker") if args[0] == "build")
    assert f"AGENT={agent}" in build
    assert build[build.index("-t") + 1] == image_name
    launched = next(args for args in calls(launch_env, "docker") if args[0] == "run")
    assert image_name in launched


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_dockerfile_runs_only_selected_installer(launch_env, agent) -> None:
    launch_env["AGENT"] = agent
    launch_env["CODEX_VERSION"] = "0.154.0"
    dockerfile = (ROOT / "paper-reproduce-skills/Dockerfile").read_text()
    # Execute the installer RUN commands with recorded stand-ins, without network access.
    commands = [
        line.removeprefix("RUN ")
        for line in dockerfile.replace("\\\n", " ").splitlines()
        if line.startswith("RUN ")
        and any(
            marker in line
            for marker in ("claude.ai/install.sh", "rtk-cli", "CODEX_VERSION")
        )
    ]
    assert commands
    for command in commands:
        subprocess.run(["bash", "-c", command], env=launch_env, check=True, timeout=30)
    if agent == "codex":
        assert calls(launch_env, "pixi") == [["global", "install", "codex=0.154.0"]]
        assert not calls(launch_env, "curl")
    else:
        assert calls(launch_env, "pixi") == [["global", "install", "rtk-cli"]]
        assert calls(launch_env, "curl") == [["-fsSL", "https://claude.ai/install.sh"]]


def test_codex_batch_gpu_lock_and_repo_file(launch_env, tmp_path) -> None:
    launch_env["FAKE_GPU"] = "1"
    repo_file = tmp_path / "repos.txt"
    repo_file.write_text(
        "# list\nhttps://example.test/one.git\n\nhttps://example.test/two.git # note\n"
    )
    result = run(
        BOOTSTRAP, launch_env, "--agent=codex", "--lang=en", "--repos", str(repo_file)
    )
    assert result.returncode == 0, result.stderr
    assert len(calls(launch_env, "flock")) == 2
    for args in calls(launch_env, "flock"):
        assert args[:2] == ["-x", f"{launch_env['LOCK_DIR']}/gpu-0.lock"]
    for args in calls(launch_env, "docker"):
        if args[0] == "run":
            assert "device=0" in args
            assert "REPORT_LANG=en" in args


@pytest.mark.parametrize("agent", ["claude", "codex", None])
def test_entrypoint_dispatch_and_argument_forwarding(launch_env, agent) -> None:
    if agent:
        launch_env["PAPER_REPRODUCER_AGENT"] = agent
    result = run(ENTRYPOINT, launch_env, "--version")
    assert result.returncode == 0, result.stderr
    selected = agent or "claude"
    args = calls(launch_env, selected)[0]
    assert args[-1] == "--version"
    assert not calls(launch_env, "claude" if selected == "codex" else "codex")
    if selected == "codex":
        assert "--dangerously-bypass-approvals-and-sandbox" in args
        assert 'cli_auth_credentials_store="file"' in args
        assert "--plugin-dir" not in args
        assert "--model" not in args and "-m" not in args
    else:
        assert args[:-1] == [
            "--dangerously-skip-permissions",
            "--plugin-dir",
            "/paper-reproduce-skills",
        ]


def test_entrypoint_rejects_unknown_agent(launch_env) -> None:
    launch_env["PAPER_REPRODUCER_AGENT"] = "unknown"
    result = run(ENTRYPOINT, launch_env)
    assert result.returncode != 0
    assert "unsupported agent" in result.stderr
    assert not calls(launch_env, "claude") and not calls(launch_env, "codex")


def test_codex_symlinked_configuration(launch_env) -> None:
    home = Path(launch_env["HOME"])
    config_dir = home / ".codex"
    config_dir.mkdir()
    managed_dir = home / "managed config"
    managed_dir.mkdir()
    config = managed_dir / "config.toml"
    config.write_text('model = "test-model"\n')
    (config_dir / "config.toml").symlink_to(config)
    result = run(BOOTSTRAP, launch_env, "--agent=codex", "https://example.test/one.git")
    assert result.returncode == 0, result.stderr
    launched = next(args for args in calls(launch_env, "docker") if args[0] == "run")
    assert f"{managed_dir}:{managed_dir}:ro" in launched
    assert config.read_text() == 'model = "test-model"\n'


@pytest.mark.parametrize("option", ["--help", "--list-assets"])
def test_codex_informational_options_need_no_docker(launch_env, option) -> None:
    result = run(BOOTSTRAP, launch_env, "--agent=codex", option)
    assert result.returncode == 0, result.stderr
    assert not calls(launch_env, "docker")


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("batch", [False, True])
def test_full_level_and_claude_model_settings(launch_env, agent, batch) -> None:
    launch_env["REPRODUCE_MODEL"] = "test-model"
    launch_env["REPRODUCE_EFFORT"] = "high"
    urls = ["https://example.test/one.git"]
    if batch:
        urls.append("https://example.test/two.git")
    result = run(BOOTSTRAP, launch_env, "--agent", agent, "--full", *urls)
    assert result.returncode == 0, result.stderr
    runs = [args for args in calls(launch_env, "docker") if args[0] == "run"]
    assert len(runs) == len(urls)
    for args in runs:
        assert "REPRODUCE_LEVEL=full" in args
        if agent == "claude":
            assert args[-4:] == ["--model", "test-model", "--effort", "high"]
        else:
            assert "--model" not in args and "--effort" not in args
