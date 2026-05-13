import shutil
import subprocess
from pathlib import Path

import pytest

from difftriage.gitstats import GitDiffError, collect_git_diff_stats


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git failed: {' '.join(args)}")
    return proc.stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available on PATH")
def test_collect_basic_modify(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "a.txt").write_text("line1\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")

    (repo / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "modify")

    monkeypatch.chdir(repo)
    stats = collect_git_diff_stats(mode="range", base="HEAD~1", head="HEAD")
    assert stats.files_changed == 1
    assert stats.lines_added == 2
    assert stats.lines_deleted == 0
    assert stats.changed_paths == ["a.txt"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available on PATH")
def test_collect_rename_and_binary(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "src").mkdir()
    (repo / "src" / "old.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "bin.dat").write_bytes(b"\x00\x01\x02\x03\x04")
    _git(repo, "add", "src/old.py", "bin.dat")
    _git(repo, "commit", "-m", "init")

    _git(repo, "mv", "src/old.py", "src/new.py")
    (repo / "bin.dat").write_bytes(b"\x10\x11\x12\x13\x14\x15")
    _git(repo, "add", "src/new.py", "bin.dat")
    _git(repo, "commit", "-m", "rename+binary")

    monkeypatch.chdir(repo)
    stats = collect_git_diff_stats(mode="range", base="HEAD~1", head="HEAD", treat_binary_as_lines=123)
    assert "src/new.py" in stats.changed_paths
    assert ("src/old.py", "src/new.py") in stats.renamed
    assert "bin.dat" in stats.binary_files
    assert stats.lines_added >= 123
    assert stats.lines_deleted >= 123


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available on PATH")
def test_staged_and_worktree_modes(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")

    (repo / "a.txt").write_text("a\nb\n", encoding="utf-8")
    _git(repo, "add", "a.txt")  # stage +1
    (repo / "a.txt").write_text("a\nb\nc\n", encoding="utf-8")  # unstaged +1

    monkeypatch.chdir(repo)
    staged = collect_git_diff_stats(mode="staged", treat_binary_as_lines=10)
    worktree = collect_git_diff_stats(mode="worktree", treat_binary_as_lines=10)
    assert staged.lines_added == 1
    assert worktree.lines_added == 1


def test_not_a_git_repo_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(GitDiffError):
        collect_git_diff_stats(mode="worktree")

