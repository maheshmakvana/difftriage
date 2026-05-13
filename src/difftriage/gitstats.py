from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Literal


DiffMode = Literal["range", "staged", "worktree"]


class GitDiffError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitFileChange:
    path: str
    status: str
    added: int
    deleted: int
    is_binary: bool
    old_path: str | None = None


@dataclass(frozen=True)
class GitDiffStats:
    files_changed: int
    lines_added: int
    lines_deleted: int
    changed_paths: list[str]
    file_changes: list[GitFileChange]
    binary_files: list[str]
    renamed: list[tuple[str, str]]
    deleted_files: list[str]


def _run_git(args: list[str], *, cwd: str | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as e:
        raise GitDiffError("git executable not found on PATH") from e

    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitDiffError(msg or f"git failed with exit code {proc.returncode}")
    return proc.stdout


def _ensure_git_repo(*, cwd: str | None) -> None:
    out = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    if out.strip() != b"true":
        raise GitDiffError("not inside a git work tree")


def _decode_path(raw: bytes) -> str:
    # Git paths are bytes; decode as UTF-8 with replacement for robustness.
    return raw.decode("utf-8", errors="replace")


def _build_diff_args(
    *,
    mode: DiffMode,
    base: str | None,
    head: str | None,
    range_spec: str | None,
    pathspecs: list[str] | None,
    rename_detection: bool,
    rename_threshold: int,
) -> list[str]:
    args: list[str] = ["diff"]

    if rename_detection:
        args.append(f"--find-renames={int(rename_threshold)}%")
    else:
        args.append("--no-renames")

    if mode == "staged":
        args.append("--cached")
    elif mode == "worktree":
        # worktree vs index: plain `git diff`
        pass
    else:
        if range_spec:
            # Let git parse revspec like "main..HEAD".
            args.append(range_spec)
        else:
            if not base or not head:
                raise GitDiffError("base/head must be set when mode='range' and range_spec not provided")
            args.append(f"{base}..{head}")

    if pathspecs:
        args.append("--")
        args.extend(pathspecs)

    return args


def _parse_name_status_z(out: bytes) -> tuple[dict[str, GitFileChange], list[tuple[str, str]]]:
    tokens = [t for t in out.split(b"\0") if t]
    changes: dict[str, GitFileChange] = {}
    renamed: list[tuple[str, str]] = []

    i = 0
    while i < len(tokens):
        status_token = tokens[i]
        status = status_token.decode("ascii", errors="replace")
        if not status:
            i += 1
            continue
        code = status[0]
        i += 1

        if code in {"R", "C"}:
            if i + 1 >= len(tokens):
                break
            old_path = _decode_path(tokens[i])
            new_path = _decode_path(tokens[i + 1])
            i += 2
            renamed.append((old_path, new_path))
            changes[new_path] = GitFileChange(
                path=new_path,
                status=code,
                added=0,
                deleted=0,
                is_binary=False,
                old_path=old_path,
            )
            continue

        if i >= len(tokens):
            break
        path = _decode_path(tokens[i])
        i += 1
        changes[path] = GitFileChange(path=path, status=code, added=0, deleted=0, is_binary=False, old_path=None)

    return changes, renamed


def _parse_numstat_z(
    out: bytes,
    *,
    treat_binary_as_lines: int,
) -> list[tuple[str, int, int, bool, str | None]]:
    """
    Parse `git diff --numstat -z` output.

    Returns entries as:
      (path, added, deleted, is_binary, old_path)

    Notes:
    - For binary changes, added/deleted may be '-'. We convert to a heuristic line count.
    - For renames/copies under `-z`, some git versions emit two subsequent NUL-terminated paths.
      We treat (old, new) and return the canonical path as the new path.
    """
    tokens = [t for t in out.split(b"\0") if t]
    entries: list[tuple[str, int, int, bool, str | None]] = []

    i = 0
    while i < len(tokens):
        rec = tokens[i]
        i += 1
        parts = rec.split(b"\t")
        if len(parts) < 3:
            continue

        added_raw, deleted_raw = parts[0], parts[1]
        path_part = b"\t".join(parts[2:])

        is_binary = added_raw == b"-" or deleted_raw == b"-"
        if is_binary:
            added = int(treat_binary_as_lines)
            deleted = int(treat_binary_as_lines)
        else:
            try:
                added = int(added_raw.decode("ascii", errors="strict"))
                deleted = int(deleted_raw.decode("ascii", errors="strict"))
            except ValueError:
                continue

        if path_part:
            path = _decode_path(path_part)
            entries.append((path, added, deleted, is_binary, None))
            continue

        # Some git versions emit NUL-separated paths after an empty path field.
        if i >= len(tokens):
            break
        first_path = _decode_path(tokens[i])
        i += 1

        # If the next token looks like another numstat record, treat this as a single-path entry.
        if i >= len(tokens) or b"\t" in tokens[i]:
            entries.append((first_path, added, deleted, is_binary, None))
            continue

        second_path = _decode_path(tokens[i])
        i += 1
        entries.append((second_path, added, deleted, is_binary, first_path))

    return entries


def collect_git_diff_stats(
    *,
    mode: DiffMode,
    base: str | None = None,
    head: str | None = None,
    range_spec: str | None = None,
    pathspecs: list[str] | None = None,
    rename_detection: bool = True,
    rename_threshold: int = 50,
    treat_binary_as_lines: int = 250,
) -> GitDiffStats:
    cwd = os.getcwd()
    _ensure_git_repo(cwd=cwd)

    diff_base_args = _build_diff_args(
        mode=mode,
        base=base,
        head=head,
        range_spec=range_spec,
        pathspecs=pathspecs,
        rename_detection=rename_detection,
        rename_threshold=rename_threshold,
    )

    name_status_out = _run_git(["-c", "core.quotepath=off", *diff_base_args, "-z", "--name-status"], cwd=cwd)
    changes, renamed = _parse_name_status_z(name_status_out)

    numstat_out = _run_git(["-c", "core.quotepath=off", *diff_base_args, "-z", "--numstat"], cwd=cwd)
    num_entries = _parse_numstat_z(numstat_out, treat_binary_as_lines=treat_binary_as_lines)

    for path, added, deleted, is_binary, old_path in num_entries:
        existing = changes.get(path)
        if existing is None:
            changes[path] = GitFileChange(
                path=path,
                status="M",
                added=added,
                deleted=deleted,
                is_binary=is_binary,
                old_path=old_path,
            )
        else:
            changes[path] = GitFileChange(
                path=existing.path,
                status=existing.status,
                added=added,
                deleted=deleted,
                is_binary=is_binary,
                old_path=existing.old_path or old_path,
            )

    file_changes = list(changes.values())
    changed_paths = sorted({c.path for c in file_changes})
    files_changed = len(changed_paths)
    lines_added = sum(c.added for c in file_changes)
    lines_deleted = sum(c.deleted for c in file_changes)
    binary_files = sorted({c.path for c in file_changes if c.is_binary})
    deleted_files = sorted({c.path for c in file_changes if c.status == "D"})

    return GitDiffStats(
        files_changed=files_changed,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        changed_paths=changed_paths,
        file_changes=sorted(file_changes, key=lambda c: (c.path, c.status)),
        binary_files=binary_files,
        renamed=sorted(set(renamed)),
        deleted_files=deleted_files,
    )

