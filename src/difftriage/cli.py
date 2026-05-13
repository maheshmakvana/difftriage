import json
from dataclasses import asdict
from typing import Literal

import typer

from difftriage.models import RiskInput
from difftriage.scoring import score_pr

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


if __name__ == "__main__":
    app()
