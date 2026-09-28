"""Frozen identity, configuration and budgets of locus validation v2 (design §2, §9).

Everything here is a pasted literal. The policy under test is the unchanged
``intent-v2-locus-v1`` (``XAILocusSemanticReasoner``); the provider configuration is v1's,
because there is no scientific reason to vary it. The experiment is single-use: a second
live run of this identity is refused (design §10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

EXPERIMENT_VERSION: Final = "intent-v2-locus-validation-v2"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-28-locus-validation-v2/"
DESIGN_SPEC_PATH: Final = "docs/superpowers/specs/2026-09-28-locus-policy-validation-v2-design.md"
SEALED_FILE_NAMES: Final = ("manifest.json", "expectations.json")
RAW_FILE_NAMES: Final = ("run.json",)

PREDECESSOR_EXPERIMENT: Final = "intent-v2-locus-validation-v1"
PREDECESSOR_ADJUDICATION_SHA: Final = "b8cd827"
"""v1 ended LOCUS_POLICY_NOT_VALIDATED on three structural failures later found to be an
expectation defect (one claim per multi-proposition document). v1 stays untouched."""

PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"

POLICY_VERSION_FROZEN: Final = "intent-v2-locus-v1"
PROMPT_SHA256_FROZEN: Final = "e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)

LedgerId = Literal["core", "orion", "conflict", "large"]
LEDGERS: Final[tuple[LedgerId, ...]] = ("core", "orion", "conflict", "large")
PROJECT_IDS: Final[dict[LedgerId, str]] = {
    "core": "PROJ-LV2-CORE",
    "orion": "PROJ-LV2-ORION",
    "conflict": "PROJ-LV2-CONFLICT",
    "large": "PROJ-LV2-LARGE",
}
SCOPES: Final[dict[LedgerId, str]] = {
    "core": "dispatch",
    "orion": "orion",
    "conflict": "portal",
    "large": "payments",
}
MODEL_SEEDED: Final[frozenset[LedgerId]] = frozenset({"core", "orion"})
"""Ledgers whose T1 world is created by the model (two calls). The others are seeded
deterministically by a human author (design §4), so only their T2 delta calls the model."""

CALLS_PER_DELTA: Final = 2
MAX_FRONTIER_CALLS: Final = 12
"""core 4 + orion 4 + conflict 2 + large 2."""
MAX_COST_USD: Final = 3.0
OBSERVED_AT: Final = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
