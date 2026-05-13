import json
from dataclasses import asdict
from typing import Literal

import typer

from difftriage.models import RiskInput
from difftriage.scoring import score_pr
from difftriage.gitstats import GitDiffError, collect_git_diff_stats

app = typer.Typer(no_args_is_help=True)

OutputFormat = Literal["text", "json", "markdown"]
ExitMode = Literal["threshold", "decision"]


def _render_text(report: object) -> str:
    lines = [
        (
            f"risk_score={report.score} level={report.level} threshold={report.threshold} "
            f"passed={report.passed} decision={report.decision} confidence={report.confidence}"
        ),
        "top_drivers:",
    ]
    for driver in report.drivers:
        lines.append(f"- {driver}")
    lines.append("rule_scores:")
    for rule, val in sorted(report.rule_scores.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"- {rule}: {val}")
    return "\n".join(lines)


def _render_markdown(report: object) -> str:
    lines = [
        "| Metric | Value |",
        "|---|---|",
        f"| Risk Score | {report.score} |",
        f"| Risk Level | {report.level} |",
        f"| Threshold | {report.threshold} |",
        f"| Passed | {report.passed} |",
        f"| Decision | {report.decision} |",
        f"| Confidence | {report.confidence} |",
        "",
        "### Top Drivers",
    ]
    for driver in report.drivers:
        lines.append(f"- {driver}")
    lines.extend(["", "### Rule Scores", "", "| Rule | Score |", "|---|---:|"])
    for rule, val in sorted(report.rule_scores.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| `{rule}` | {val} |")
    return "\n".join(lines)


def _exit_code(report: object, exit_mode: ExitMode) -> int:
    if exit_mode == "threshold":
        return 0 if report.passed else 2

    if report.decision == "pass":
        return 0
    if report.decision in {"review_required", "override_required_review"}:
        return 3
    return 2


@app.command()
def score(
    files_changed: int = typer.Option(...),
    lines_added: int = typer.Option(...),
    lines_deleted: int = typer.Option(...),
    changed_path: list[str] = typer.Option([]),
    tests_changed: bool = typer.Option(False),
    dependencies_changed: bool = typer.Option(False),
    ai_uncertainty_hits: int = typer.Option(0),
    config: str = typer.Option(".difftriage.yml"),
    threshold: float | None = typer.Option(None),
    output: OutputFormat = typer.Option("text"),
    exit_mode: ExitMode = typer.Option("threshold"),
) -> None:
    report = score_pr(
        RiskInput(
            files_changed=files_changed,
            lines_added=lines_added,
            lines_deleted=lines_deleted,
            changed_paths=changed_path,
            tests_changed=tests_changed,
            dependencies_changed=dependencies_changed,
            ai_uncertainty_hits=ai_uncertainty_hits,
        ),
        config_path=config,
        threshold_override=threshold,
    )

    if output == "json":
        typer.echo(json.dumps(asdict(report), indent=2))
    elif output == "markdown":
        typer.echo(_render_markdown(report))
    else:
        typer.echo(_render_text(report))

    raise typer.Exit(code=_exit_code(report, exit_mode))


def _auto_dependencies_changed(paths: list[str]) -> bool:
    lowered = [p.replace("\\", "/").lower() for p in paths]
    dep_files = [
        "pyproject.toml",
        "poetry.lock",
        "pdm.lock",
        "uv.lock",
        "pipfile",
        "pipfile.lock",
        "setup.cfg",
        "setup.py",
        "environment.yml",
    ]
    if any(p.endswith(tuple(dep_files)) for p in lowered):
        return True
    if any(p.endswith(".txt") and ("requirements" in p or "constraints" in p) for p in lowered):
        return True
    if any(p.endswith((".yml", ".yaml")) and ("conda" in p) for p in lowered):
        return True
    return False


@app.command("score-git")
def score_git(
    range_spec: str | None = typer.Option(None, "--range"),
    base: str = typer.Option("HEAD~1"),
    head: str = typer.Option("HEAD"),
    staged: bool = typer.Option(False, "--staged", "--cached"),
    worktree: bool = typer.Option(False, "--worktree"),
    path: list[str] = typer.Option([], "--path"),
    rename_detection: bool = typer.Option(True, "--rename-detection/--no-rename-detection"),
    rename_threshold: int = typer.Option(50, "--rename-threshold"),
    treat_binary_as_lines: int = typer.Option(250, "--treat-binary-as-lines"),
    auto_tests: bool = typer.Option(True, "--auto-tests/--no-auto-tests"),
    auto_deps: bool = typer.Option(True, "--auto-deps/--no-auto-deps"),
    tests_changed: bool | None = typer.Option(None, "--tests-changed/--no-tests-changed"),
    dependencies_changed: bool | None = typer.Option(None, "--dependencies-changed/--no-dependencies-changed"),
    ai_uncertainty_hits: int = typer.Option(0),
    ai_generated_ratio: float = typer.Option(0.0),
    override_approved: bool = typer.Option(False),
    override_reason: str = typer.Option(""),
    config: str = typer.Option(".difftriage.yml"),
    threshold: float | None = typer.Option(None),
    output: OutputFormat = typer.Option("text"),
    exit_mode: ExitMode = typer.Option("threshold"),
) -> None:
    if sum(1 for x in (staged, worktree) if x) > 1:
        raise typer.BadParameter("Choose only one of --staged/--cached or --worktree (or neither for commit range mode).")
    if range_spec and (staged or worktree):
        raise typer.BadParameter("--range cannot be combined with --staged/--worktree.")

    mode: Literal["range", "staged", "worktree"]
    if staged:
        mode = "staged"
    elif worktree:
        mode = "worktree"
    else:
        mode = "range"

    try:
        stats = collect_git_diff_stats(
            mode=mode,
            base=base,
            head=head,
            range_spec=range_spec,
            pathspecs=path or None,
            rename_detection=rename_detection,
            rename_threshold=rename_threshold,
            treat_binary_as_lines=treat_binary_as_lines,
        )
    except GitDiffError as e:
        typer.echo(f"difftriage score-git: {e}", err=True)
        raise typer.Exit(code=2)

    resolved_tests_changed = tests_changed
    if resolved_tests_changed is None:
        resolved_tests_changed = False
        if auto_tests:
            resolved_tests_changed = any("tests/" in p.replace("\\", "/").lower() for p in stats.changed_paths)

    resolved_deps_changed = dependencies_changed
    if resolved_deps_changed is None:
        resolved_deps_changed = False
        if auto_deps:
            resolved_deps_changed = _auto_dependencies_changed(stats.changed_paths)

    report = score_pr(
        RiskInput(
            files_changed=stats.files_changed,
            lines_added=stats.lines_added,
            lines_deleted=stats.lines_deleted,
            changed_paths=stats.changed_paths,
            tests_changed=bool(resolved_tests_changed),
            dependencies_changed=bool(resolved_deps_changed),
            ai_uncertainty_hits=ai_uncertainty_hits,
            ai_generated_ratio=ai_generated_ratio,
            override_approved=override_approved,
            override_reason=override_reason,
        ),
        config_path=config,
        threshold_override=threshold,
    )

    if output == "json":
        payload = asdict(report)
        payload["git"] = {
            "files_changed": stats.files_changed,
            "lines_added": stats.lines_added,
            "lines_deleted": stats.lines_deleted,
            "binary_files": stats.binary_files,
            "renamed": stats.renamed,
            "deleted_files": stats.deleted_files,
        }
        typer.echo(json.dumps(payload, indent=2))
    elif output == "markdown":
        typer.echo(_render_markdown(report))
    else:
        typer.echo(_render_text(report))

    raise typer.Exit(code=_exit_code(report, exit_mode))


if __name__ == "__main__":
    app()
