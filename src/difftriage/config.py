from __future__ import annotations
from copy import deepcopy
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "threshold": 50,
    "block_threshold": 75,
    "review_threshold": 50,
    "enable_confidence_bands": True,
    "weights": {
        "blast_radius": 0.20,
        "behavior_change": 0.18,
        "test_impact": 0.16,
        "complexity": 0.12,
        "dependency_config": 0.10,
        "data_schema": 0.08,
        "security_privacy": 0.08,
        "ai_uncertainty": 0.05,
        "observability_gap": 0.03,
    },
    "rules": {
        "risky_path_patterns": ["auth", "billing", "migrations", ".github/workflows", "infra", "config", "permissions", "token"],
        "schema_patterns": ["migrations", "schema", "models", "ddl"],
        "security_patterns": ["auth", "token", "permission", "secret", "privacy"],
        "observability_patterns": ["log", "metrics", "trace"],
        "safe_path_patterns": ["docs/", ".md", "tests/"],
        "docs_path_patterns": ["docs/", ".md", ".rst", ".txt", "readme", "changelog", "license"],
        "test_path_patterns": ["tests/", "test_", "_test.", ".spec.", ".test."],
    },
    "policy": {
        "docs_tests_only_max_score": 18,
        "docs_tests_only_review_threshold": 70,
        "safe_change_max_score": 30,
        "security_block_score": 70,
        "schema_block_score": 78,
        "schema_review_score": 45,
        "dependency_review_score": 55,
        "missing_tests_review_score": 45,
    },
    "override": {
        "require_reason_min_length": 12,
        "allow_score_override": True,
        "allow_schema_override": True,
        "allow_dependency_override": True,
        "allow_security_override": True,
    },
}


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return deepcopy(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return deepcopy(DEFAULT_CONFIG)
    return _deep_merge(DEFAULT_CONFIG, data)
