from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskInput:
    files_changed: int
    lines_added: int
    lines_deleted: int
    changed_paths: list[str] = field(default_factory=list)
    tests_changed: bool = False
    dependencies_changed: bool = False
    ai_uncertainty_hits: int = 0
    ai_generated_ratio: float = 0.0
    override_approved: bool = False
    override_reason: str = ""


@dataclass
class RiskReport:
    score: float
    threshold: float
    passed: bool
    level: str
    drivers: list[str]
    decision: str
    confidence: str
    rule_scores: dict[str, float]
    review_threshold: float = 50.0
    block_threshold: float = 75.0
    rule_breakdown: list[dict[str, Any]] = field(default_factory=list)
    policy_flags: list[str] = field(default_factory=list)
    override_gates: dict[str, Any] = field(default_factory=dict)
