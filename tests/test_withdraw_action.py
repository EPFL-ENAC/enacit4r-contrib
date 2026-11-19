"""Run withdraw/withdraw.sh against a local bare origin and a fake gh."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

if not shutil.which("bash") or not shutil.which("git"):
    pytest.skip("bash and git are required", allow_module_level=True)

SCRIPT = Path(__file__).resolve().parents[1] / "withdraw" / "withdraw.sh"

FAKE_GH = """#!/usr/bin/env bash
case "$1" in
  workflow) echo "$*" >> "$FAKE_LOG" ;;
  *) exit 2 ;;
esac
"""

# Replace the row "$TARGET,..." by "$TARGET," (the number stays retired).
RETIRE = 'sed -i.bak "s/^$TARGET,.*/$TARGET,/" data.txt && rm data.txt.bak'


def git(*args, cwd, env):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GIT_CONFIG_GLOBAL": str(empty),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "seed",
        "GIT_AUTHOR_EMAIL": "seed@example.org",
        "GIT_COMMITTER_NAME": "seed",
        "GIT_COMMITTER_EMAIL": "seed@example.org",
        "FAKE_LOG": str(tmp_path / "gh.log"),
        "TARGET": "2",
        "REASON": "test data",
        "BASE": "main",
        "COMMAND": RETIRE,
        "DEPLOY_WORKFLOW": "deploy.yml",
    }
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path, env=env)
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path, env=env)
    (seed / "data.txt").write_text("id,name\n1,a\n2,b\n")
    git("add", ".", cwd=seed, env=env)
    git("commit", "-q", "-m", "seed", cwd=seed, env=env)
    git("push", "-q", "origin", "HEAD:main", cwd=seed, env=env)
    work = tmp_path / "work"
    git("clone", "-q", str(origin), str(work), cwd=tmp_path, env=env)
    return {"tmp": tmp_path, "origin": origin, "work": work, "env": env}


def run(repo):
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo["work"],
        env=repo["env"],
        capture_output=True,
        text=True,
    )


def origin_log(repo, fmt="%s"):
    return git("log", f"--format={fmt}", "main", cwd=repo["origin"], env=repo["env"])


def origin_file(repo, path):
    return git("show", f"main:{path}", cwd=repo["origin"], env=repo["env"])


def test_withdraw_is_committed_pushed_and_deployed(repo):
    result = run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert origin_log(repo).splitlines() == ["chore(data): withdraw 2", "seed"]
    assert "test data" in origin_log(repo, "%b")
    assert origin_file(repo, "data.txt") == "id,name\n1,a\n2,\n"
    assert (
        repo["tmp"] / "gh.log"
    ).read_text() == "workflow run deploy.yml --ref main\n"


def test_nothing_to_withdraw_exits_one(repo):
    repo["env"]["TARGET"] = "9"
    result = run(repo)
    assert result.returncode == 1
    assert "nothing to withdraw for 9" in result.stderr
    assert origin_log(repo).splitlines() == ["seed"]
    assert not (repo["tmp"] / "gh.log").exists()


def test_failing_command_exits_one_and_pushes_nothing(repo):
    repo["env"]["COMMAND"] = "echo 'no record 2' >&2; exit 4"
    result = run(repo)
    assert result.returncode == 1
    assert "no record 2" in result.stderr
    assert "failed for 2" in result.stderr
    assert origin_log(repo).splitlines() == ["seed"]
    assert not (repo["tmp"] / "gh.log").exists()


def test_moved_base_is_fetched_and_withdrawn_again(repo):
    other = repo["tmp"] / "other"
    mark = repo["tmp"] / "moved"
    # The first run of the command pushes a concurrent commit to origin.
    repo["env"]["COMMAND"] = (
        f'if [ ! -e "{mark}" ]; then touch "{mark}" && '
        f'git clone -q "{repo["origin"]}" "{other}" && '
        f'echo x > "{other}/other.txt" && git -C "{other}" add other.txt && '
        f'git -C "{other}" commit -q -m concurrent && '
        f'git -C "{other}" push -q origin HEAD:main; fi && {RETIRE}'
    )
    result = run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "refused" in result.stdout
    assert origin_log(repo).splitlines() == [
        "chore(data): withdraw 2",
        "concurrent",
        "seed",
    ]
    assert origin_file(repo, "data.txt") == "id,name\n1,a\n2,\n"
    assert origin_file(repo, "other.txt") == "x\n"
