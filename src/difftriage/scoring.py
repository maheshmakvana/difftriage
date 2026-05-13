from __future__ import annotations

from typing import Any

from difftriage.config import load_config
from difftriage.models import RiskInput, RiskReport


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _risk_level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def _confidence(score: float, review_threshold: float, block_threshold: float) -> str:
    # Scores near enforcement edges are inherently less certain.
    band = 5.0
    if abs(score - review_threshold) <= band or abs(score - block_threshold) <= band:
        return "medium"
    return "high"


def _matches(path: str, patterns: list[str]) -> bool:
    return any(pattern.lower() in path for pattern in patterns)


def _path_profile(paths: list[str], rules: dict[str, Any], files_changed: int) -> dict[str, Any]:
    lowered = [p.replace("\\", "/").lower() for p in paths]
    file_count = max(files_changed, len(lowered), 1)
    docs_patterns = rules["docs_path_patterns"]
    test_patterns = rules["test_path_patterns"]
    safe_patterns = rules["safe_path_patterns"]

    docs = [p for p in lowered if _matches(p, docs_patterns)]
    tests = [p for p in lowered if _matches(p, test_patterns)]
    safe = [p for p in lowered if _matches(p, safe_patterns) or p in docs or p in tests]
    risky = [p for p in lowered if _matches(p, rules["risky_path_patterns"])]
    schema = [p for p in lowered if _matches(p, rules["schema_patterns"])]
    security = [p for p in lowered if _matches(p, rules["security_patterns"])]
    observability = [p for p in lowered if _matches(p, rules["observability_patterns"])]

    docs_or_tests_only = bool(lowered) and len(set(docs + tests + safe)) == len(set(lowered))

    return {
        "paths": lowered,
        "file_count": file_count,
        "docs_count": len(set(docs)),
        "tests_count": len(set(tests)),
        "safe_count": len(set(safe)),
        "non_safe_count": max(0, file_count - len(set(safe))),
        "risky": risky,
        "schema": schema,
        "security": security,
        "observability": observability,
        "docs_or_tests_only": docs_or_tests_only,
        "risky_ratio": len(set(risky)) / file_count,
    }


def _breakdown_item(
    name: str,
    score: float,
    weight: float,
    rationale: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "rule": name,
        "score": round(score, 2),
        "weight": weight,
        "contribution": round(score * weight, 2),
        "rationale": rationale,
        "evidence": evidence or [],
    }


def _has_valid_override(risk_input: RiskInput, override_config: dict[str, Any]) -> bool:
    reason = risk_input.override_reason.strip()
    min_length = int(override_config.get("require_reason_min_length", 12))
    return risk_input.override_approved and len(reason) >= min_length


def _override_satisfies(reason: str, risk_input: RiskInput, override_config: dict[str, Any]) -> bool:
    if not risk_input.override_approved:
        return False
    if reason == "schema":
        return bool(override_config.get("allow_schema_override", True))
    if reason == "security":
        return bool(override_config.get("allow_security_override", True)) and _has_valid_override(risk_input, override_config)
    if reason == "score":
        return bool(override_config.get("allow_score_override", True)) and _has_valid_override(risk_input, override_config)
    if reason == "dependency":
        return bool(override_config.get("allow_dependency_override", True)) and _has_valid_override(risk_input, override_config)
    return False


def score_pr(risk_input: RiskInput, config_path: str | None = None, threshold_override: float | None = None) -> RiskReport:
    config = load_config(config_path)
    weights = config["weights"]
    rules = config["rules"]
    policy = config["policy"]
    override_config = config["override"]

    profile = _path_profile(risk_input.changed_paths, rules, risk_input.files_changed)
    file_count = profile["file_count"]
    non_safe_files = profile["non_safe_count"]
    churn = risk_input.lines_added + risk_input.lines_deleted
    docs_tests_only = profile["docs_or_tests_only"]

    code_file_factor = 0.15 if docs_tests_only else 1.0
    churn_factor = 0.12 if docs_tests_only else 1.0

    blast_radius = _clamp((non_safe_files * 7) + ((churn * churn_factor) / 28))
    behavior_change = _clamp((non_safe_files * 6) + ((risk_input.lines_added * churn_factor) / 32))
    complexity = _clamp((file_count * 3.5 * code_file_factor) + ((churn * churn_factor) / 24))

    schema_hits = len(set(profile["schema"]))
    security_hits = len(set(profile["security"]))
    observability_hits = len(set(profile["observability"]))
    risky_ratio = profile["risky_ratio"]

    missing_tests = not risk_input.tests_changed and not docs_tests_only
    test_impact = 0.0 if not missing_tests else _clamp(32 + (complexity * 0.45) + (risky_ratio * 22))
    dependency_config = 65.0 if risk_input.dependencies_changed else 0.0
    data_schema = _clamp(schema_hits * 32)
    security_privacy = _clamp(security_hits * 28)
    ai_uncertainty = _clamp((risk_input.ai_uncertainty_hits * 12) + (risk_input.ai_generated_ratio * 25))
    observability_gap = 0.0 if observability_hits > 0 or docs_tests_only else _clamp((risky_ratio * 35) + (8 if non_safe_files > 4 else 0))

    rule_scores = {
        "blast_radius": round(blast_radius, 2),
        "behavior_change": round(behavior_change, 2),
        "test_impact": round(test_impact, 2),
        "complexity": round(complexity, 2),
        "dependency_config": round(dependency_config, 2),
        "data_schema": round(data_schema, 2),
        "security_privacy": round(security_privacy, 2),
        "ai_uncertainty": round(ai_uncertainty, 2),
        "observability_gap": round(observability_gap, 2),
    }

    raw_score = sum(rule_scores[name] * weights[name] for name in weights)
    score_cap = None
    policy_flags: list[str] = []
    if docs_tests_only:
        score_cap = float(policy["docs_tests_only_max_score"])
        policy_flags.append("docs_tests_only_low_false_positive_cap")
    elif profile["safe_count"] and profile["safe_count"] >= file_count * 0.75:
        score_cap = float(policy["safe_change_max_score"])
        policy_flags.append("mostly_safe_paths_score_cap")

    score = min(raw_score, score_cap) if score_cap is not None else raw_score

    threshold = threshold_override if threshold_override is not None else float(config["threshold"])
    review_threshold = float(config["review_threshold"])
    block_threshold = float(config["block_threshold"])

    rule_breakdown = [
        _breakdown_item(
            "blast_radius",
            blast_radius,
            weights["blast_radius"],
            f"{non_safe_files} non-safe file(s), {churn} total changed line(s)",
        ),
        _breakdown_item(
            "behavior_change",
            behavior_change,
            weights["behavior_change"],
            f"{risk_input.lines_added} added line(s) across implementation-sensitive paths",
        ),
        _breakdown_item(
            "test_impact",
            test_impact,
            weights["test_impact"],
            "Tests changed or docs/tests-only change" if not missing_tests else "Implementation change without test changes",
        ),
        _breakdown_item(
            "complexity",
            complexity,
            weights["complexity"],
            f"{file_count} file(s), churn factor adjusted for docs/tests-only safety",
        ),
        _breakdown_item(
            "dependency_config",
            dependency_config,
            weights["dependency_config"],
            "Dependency/config change declared" if risk_input.dependencies_changed else "No dependency change declared",
        ),
        _breakdown_item(
            "data_schema",
            data_schema,
            weights["data_schema"],
            f"{schema_hits} schema-sensitive path hit(s)",
            profile["schema"][:5],
        ),
        _breakdown_item(
            "security_privacy",
            security_privacy,
            weights["security_privacy"],
            f"{security_hits} security/privacy path hit(s)",
            profile["security"][:5],
        ),
        _breakdown_item(
            "ai_uncertainty",
            ai_uncertainty,
            weights["ai_uncertainty"],
            f"{risk_input.ai_uncertainty_hits} uncertainty hit(s), generated ratio {risk_input.ai_generated_ratio}",
        ),
        _breakdown_item(
            "observability_gap",
            observability_gap,
            weights["observability_gap"],
            "Risky code path has observability coverage" if observability_gap == 0 else "Risky code path without observability signal",
        ),
    ]

    if score_cap is not None and raw_score > score:
        policy_flags.append(f"score_capped_from_{round(raw_score, 2)}_to_{round(score, 2)}")

    hard_blocks: list[str] = []
    review_reasons: list[str] = []
    overrideable_reasons: list[str] = []

    if score >= block_threshold:
        hard_blocks.append("score_at_or_above_block_threshold")
        overrideable_reasons.append("score")
    elif score >= review_threshold:
        review_reasons.append("score_at_or_above_review_threshold")

    if security_privacy >= float(policy["security_block_score"]):
        hard_blocks.append("security_privacy_gate")
        if bool(override_config.get("allow_security_override", False)):
            overrideable_reasons.append("security")
    if data_schema >= float(policy["schema_block_score"]):
        hard_blocks.append("schema_gate")
        if bool(override_config.get("allow_schema_override", True)):
            overrideable_reasons.append("schema")
    elif data_schema >= float(policy["schema_review_score"]):
        review_reasons.append("schema_review_gate")
    if dependency_config >= float(policy["dependency_review_score"]):
        review_reasons.append("dependency_or_config_review_gate")
    if test_impact >= float(policy["missing_tests_review_score"]):
        review_reasons.append("missing_tests_review_gate")

    valid_override = _has_valid_override(risk_input, override_config)
    block_reason_map = {
        "score_at_or_above_block_threshold": "score",
        "schema_gate": "schema",
        "security_privacy_gate": "security",
    }
    non_overrideable_blocks = [
        reason
        for reason in hard_blocks
        if block_reason_map.get(reason) not in overrideable_reasons
    ]
    unsatisfied_override_blocks = [
        reason
        for reason in hard_blocks
        if reason not in non_overrideable_blocks and not _override_satisfies(block_reason_map[reason], risk_input, override_config)
    ]

    if hard_blocks and not non_overrideable_blocks and not unsatisfied_override_blocks:
        if hard_blocks == ["schema_gate"] and not review_reasons and score < review_threshold:
            decision = "pass"
            policy_flags.append("valid_schema_override_downgraded_block_to_pass")
        else:
            decision = "override_required_review"
            policy_flags.append("valid_override_downgraded_block_to_review")
    elif hard_blocks:
        decision = "block"
    elif review_reasons:
        decision = "review_required"
    else:
        decision = "pass"

    if hard_blocks:
        policy_flags.extend(hard_blocks)
    if review_reasons:
        policy_flags.extend(review_reasons)
    if risk_input.override_approved and unsatisfied_override_blocks:
        policy_flags.append("override_missing_required_reason")

    level = _risk_level(score)
    conf = _confidence(score, review_threshold, block_threshold) if config.get("enable_confidence_bands", True) else "high"

    drivers = []
    for item in sorted(rule_breakdown, key=lambda x: x["contribution"], reverse=True)[:4]:
        if item["score"] > 0:
            drivers.append(f"{item['rule']}: {item['score']} ({item['rationale']})")
    if not drivers:
        drivers.append("No major risk driver detected")

    passed = decision == "pass" and score < threshold

    return RiskReport(
        score=round(score, 2),
        threshold=threshold,
        passed=passed,
        level=level,
        drivers=drivers,
        decision=decision,
        confidence=conf,
        rule_scores=rule_scores,
        review_threshold=review_threshold,
        block_threshold=block_threshold,
        rule_breakdown=rule_breakdown,
        policy_flags=policy_flags,
        override_gates={
            "override_requested": risk_input.override_approved,
            "override_reason_provided": bool(risk_input.override_reason.strip()),
            "override_valid": valid_override,
            "overrideable_reasons": sorted(set(overrideable_reasons)),
            "non_overrideable_blocks": non_overrideable_blocks,
            "unsatisfied_override_blocks": unsatisfied_override_blocks,
        },
    )
