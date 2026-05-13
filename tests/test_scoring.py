from difftriage.models import RiskInput
from difftriage.scoring import score_pr


def test_high_risk_without_tests_blocks() -> None:
    report = score_pr(
        RiskInput(
            files_changed=20,
            lines_added=800,
            lines_deleted=200,
            changed_paths=["src/auth/service.py", "src/billing/charge.py", "db/migrations/001.sql", ".github/workflows/ci.yml"],
            tests_changed=False,
            dependencies_changed=True,
            ai_uncertainty_hits=2,
            ai_generated_ratio=0.7,
        ),
        threshold_override=50,
    )
    assert report.decision == "block"
    assert report.passed is False


def test_low_risk_with_tests_passes() -> None:
    report = score_pr(
        RiskInput(
            files_changed=2,
            lines_added=20,
            lines_deleted=4,
            changed_paths=["src/utils/format.py", "tests/test_format.py"],
            tests_changed=True,
        ),
        threshold_override=50,
    )
    assert report.decision == "pass"
    assert report.passed is True


def test_docs_only_reduces_false_positive() -> None:
    report = score_pr(
        RiskInput(
            files_changed=3,
            lines_added=120,
            lines_deleted=30,
            changed_paths=["docs/guide.md", "README.md", "docs/usage.md"],
            tests_changed=False,
        )
    )
    assert report.level in {"low", "medium"}


def test_override_changes_block_to_review_required() -> None:
    base = RiskInput(
        files_changed=12,
        lines_added=400,
        lines_deleted=120,
        changed_paths=["src/auth/token.py", "db/schema.sql"],
        tests_changed=False,
    )
    blocked = score_pr(base)
    assert blocked.decision in {"block", "review_required"}

    override = score_pr(
        RiskInput(**{**base.__dict__, "override_approved": True, "override_reason": "approved by code owners"})
    )
    assert override.decision in {"override_required_review", "review_required", "pass"}


def test_decision_review_required_at_exact_review_threshold_and_confidence_band() -> None:
    # Force a deterministic score of exactly 50.0 via clamping of core rule scores.
    # With default config, review_threshold is 50.
    report = score_pr(
        RiskInput(
            files_changed=1,
            lines_added=4000,
            lines_deleted=0,
            changed_paths=["src/core/worker.py"],
            tests_changed=True,  # keep test_impact at 0 for determinism
        )
    )
    assert report.score == 50.0
    assert report.decision == "review_required"
    assert report.passed is False
    # Confidence band is +/- 5 around the review_threshold.
    assert report.confidence == "medium"


def test_threshold_override_only_affects_passed_not_decision() -> None:
    # Craft a pass decision with a stable score around ~43, then tighten only the pass threshold.
    base = score_pr(
        RiskInput(
            files_changed=1,
            lines_added=2500,
            lines_deleted=0,
            changed_paths=["src/core/worker.py"],
            tests_changed=True,
        )
    )
    assert base.decision == "pass"
    assert base.passed is True
    assert base.score > 40.0

    tightened = score_pr(
        RiskInput(
            files_changed=1,
            lines_added=2500,
            lines_deleted=0,
            changed_paths=["src/core/worker.py"],
            tests_changed=True,
        ),
        threshold_override=40,
    )
    assert tightened.decision == "pass"
    assert tightened.score == base.score
    assert tightened.threshold == 40
    assert tightened.passed is False


def test_security_privacy_hard_block_and_override_required_review() -> None:
    # security_privacy = 22 * security_hits; 4 "auth" paths -> 88 -> hard block.
    blocked = score_pr(
        RiskInput(
            files_changed=4,
            lines_added=0,
            lines_deleted=0,
            changed_paths=[
                "src/auth/a.py",
                "src/auth/b.py",
                "src/auth/c.py",
                "src/auth/d.py",
            ],
            tests_changed=True,
        )
    )
    assert blocked.rule_scores["security_privacy"] >= 70
    assert blocked.decision == "block"
    assert blocked.passed is False

    overridden = score_pr(
        RiskInput(
            files_changed=4,
            lines_added=0,
            lines_deleted=0,
            changed_paths=[
                "src/auth/a.py",
                "src/auth/b.py",
                "src/auth/c.py",
                "src/auth/d.py",
            ],
            tests_changed=True,
            override_approved=True,
            override_reason="Emergency fix; follow-up review required",
        )
    )
    assert overridden.rule_scores["security_privacy"] >= 70
    assert overridden.decision == "override_required_review"
    assert overridden.passed is False


def test_schema_hard_block_can_be_avoided_with_override_approval() -> None:
    # Schema hits can hard-block, but a valid schema override can downgrade a schema-only block
    # all the way to a pass when nothing else triggers review and the score is below the review threshold.
    no_override = score_pr(
        RiskInput(
            files_changed=3,
            lines_added=0,
            lines_deleted=0,
            changed_paths=["migrations/001.sql", "migrations/002.sql", "migrations/003.sql"],
            tests_changed=True,
        )
    )
    assert no_override.rule_scores["data_schema"] >= 70
    assert no_override.decision == "block"
    assert no_override.passed is False

    approved = score_pr(
        RiskInput(
            files_changed=3,
            lines_added=0,
            lines_deleted=0,
            changed_paths=["migrations/001.sql", "migrations/002.sql", "migrations/003.sql"],
            tests_changed=True,
            override_approved=True,
            override_reason="Approved for emergency rollout",
        )
    )
    assert approved.rule_scores["data_schema"] >= 70
    assert approved.decision == "pass"
    assert approved.passed is True
    assert "valid_schema_override_downgraded_block_to_pass" in approved.policy_flags


def test_confidence_bands_can_be_disabled_via_config_injection(monkeypatch) -> None:
    # load_config() does not currently merge enable_confidence_bands from file,
    # so cover this branch by injecting a config with bands disabled.
    import difftriage.scoring as scoring

    real_load = scoring.load_config

    def fake_load_config(_path):
        cfg = real_load(None)
        cfg["enable_confidence_bands"] = False
        return cfg

    monkeypatch.setattr(scoring, "load_config", fake_load_config)

    report = scoring.score_pr(
        RiskInput(
            files_changed=1,
            lines_added=4000,
            lines_deleted=0,
            changed_paths=["src/core/worker.py"],
            tests_changed=True,
        )
    )
    assert report.score == 50.0
    assert report.confidence == "high"


def test_safe_paths_reduce_false_positive_risk() -> None:
    # Same churn and file_count, but safe paths reduce non_safe_files -> lower blast_radius/behavior_change -> lower score.
    non_safe = score_pr(
        RiskInput(
            files_changed=3,
            lines_added=300,
            lines_deleted=0,
            changed_paths=["src/core/a.py", "src/core/b.py", "src/core/c.py"],
            tests_changed=False,
        )
    )
    safe = score_pr(
        RiskInput(
            files_changed=3,
            lines_added=300,
            lines_deleted=0,
            changed_paths=["DOCS/a.MD", "docs/b.md", "docs/c.md"],  # case-insensitive safe hit
            tests_changed=False,
        )
    )

    assert safe.rule_scores["blast_radius"] < non_safe.rule_scores["blast_radius"]
    assert safe.rule_scores["behavior_change"] < non_safe.rule_scores["behavior_change"]
    assert safe.score < non_safe.score
