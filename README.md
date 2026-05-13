# DiffTriage - Pro PR Risk Gating for AI-Generated Code

**difftriage** is an open-source Python library for production-grade pull request risk analysis.

It scores change risk across blast radius, behavior change, test impact, schema/security sensitivity, AI uncertainty, and observability gaps. It then enforces configurable merge policy decisions: `pass`, `review_required`, `block`, and `override_required_review`.

[![PyPI version](https://img.shields.io/pypi/v/difftriage.svg)](https://pypi.org/project/difftriage/)
[![Python](https://img.shields.io/pypi/pyversions/difftriage.svg)](https://pypi.org/project/difftriage/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

---

## Why DiffTriage

Teams shipping more AI-assisted code often face:
- more regressions in core paths,
- slower reviews,
- weak signal-to-noise in large diffs.

DiffTriage provides a deterministic, explainable risk gate with rule-level scoring so teams can move fast without blind merges.

---

## Key Features

- Multi-factor risk model (9 weighted dimensions)
- Explainable scoring with per-rule contributions
- Policy decisions: `pass` / `review_required` / `block` / `override_required_review`
- Confidence bands near threshold boundaries
- False-positive controls for docs/tests-only changes
- Override governance with audit-friendly policy flags
- CI-friendly CLI with multiple output modes
- GitHub + PyPI release workflows (trusted publishing ready)

---

## Installation

```bash
pip install difftriage
```

Requires Python 3.10+.

---

## Quick Start

```bash
difftriage score \
  --files-changed 12 \
  --lines-added 420 \
  --lines-deleted 130 \
  --changed-path src/auth/service.py \
  --changed-path db/migrations/001.sql \
  --dependencies-changed \
  --output text
```

Example result:
- risk score + level
- decision + confidence
- top risk drivers
- rule scores

---

## CLI Usage

Output formats:
- `--output text` (default)
- `--output json`
- `--output markdown`

Exit semantics:
- `--exit-mode threshold`:
  - `0` pass
  - `2` fail
- `--exit-mode decision`:
  - `0` pass
  - `3` review required
  - `2` block

Examples:

```bash
# JSON for automation
difftriage score --files-changed 8 --lines-added 140 --lines-deleted 35 --changed-path src/payments.py --output json

# Markdown for PR comments
difftriage score --files-changed 8 --lines-added 140 --lines-deleted 35 --changed-path src/payments.py --output markdown --exit-mode decision
```

---

## Risk Model

Default weighted dimensions:

- `blast_radius` (0.20)
- `behavior_change` (0.18)
- `test_impact` (0.16)
- `complexity` (0.12)
- `dependency_config` (0.10)
- `data_schema` (0.08)
- `security_privacy` (0.08)
- `ai_uncertainty` (0.05)
- `observability_gap` (0.03)

Scoring levels:
- `0-24`: low
- `25-49`: medium
- `50-74`: high
- `75-100`: critical

---

## Configuration

Create `.difftriage.yml` in repo root:

```yaml
threshold: 50
review_threshold: 50
block_threshold: 75
enable_confidence_bands: true

weights:
  blast_radius: 0.20
  behavior_change: 0.18
  test_impact: 0.16
  complexity: 0.12
  dependency_config: 0.10
  data_schema: 0.08
  security_privacy: 0.08
  ai_uncertainty: 0.05
  observability_gap: 0.03

rules:
  risky_path_patterns: ["auth", "billing", "migrations", ".github/workflows", "infra", "config", "permissions", "token"]
  schema_patterns: ["migrations", "schema", "models", "ddl"]
  security_patterns: ["auth", "token", "permission", "secret", "privacy"]
  observability_patterns: ["log", "metrics", "trace"]
  safe_path_patterns: ["docs/", ".md", "tests/"]

policy:
  docs_tests_only_max_score: 18
  safe_change_max_score: 30
  security_block_score: 70
  schema_block_score: 78
  schema_review_score: 45
  dependency_review_score: 55
  missing_tests_review_score: 45

override:
  require_reason_min_length: 12
  allow_score_override: true
  allow_schema_override: true
  allow_dependency_override: true
  allow_security_override: true
```

---

## CI Integration

DiffTriage is designed for CI gates:

```bash
difftriage score ... --output json --exit-mode decision
```

Recommended policy:
- treat `review_required` as protected-branch reviewer gate,
- treat `block` as merge stop,
- allow audited overrides only for approved emergency paths.

---

## Release and Publishing

This repo includes:
- `.github/workflows/ci.yml` for tests + build checks
- `.github/workflows/release.yml` for tag-based PyPI publishing

Publish flow:
1. Push tag `vX.Y.Z`
2. Build artifacts
3. Publish with `pypa/gh-action-pypi-publish` via GitHub OIDC

---

## Local Validation

```bash
pip install -e . pytest build twine
pytest -q
python -m build
twine check dist/*
```

---

## Contributing

Issues and pull requests are welcome.

---

## License

MIT - see `LICENSE`.