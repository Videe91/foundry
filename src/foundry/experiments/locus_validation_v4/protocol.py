"""Frozen identity, configuration and budgets of locus validation v4 (design §2, §10).

Everything here is a pasted literal. The policy under test is the canonical-facet policy
``intent-v2-locus-v3`` (``XAICanonicalFacetSemanticReasoner``, output contract
``ConcernDraftPayload``), run under ``AdmissionPolicy(canonical_facets=True)``. The provider
configuration is v2's and v3's, held constant so that the policy is the only variable. The
experiment is single-use: a second live run of this identity is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

EXPERIMENT_VERSION: Final = "intent-v2-locus-validation-v4"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-29-locus-validation-v4/"
DESIGN_SPEC_PATH: Final = "docs/superpowers/specs/2026-09-29-locus-policy-validation-v4-design.md"
SEALED_FILE_NAMES: Final = ("manifest.json", "expectations.json")
RAW_FILE_NAMES: Final = ("run.json",)

PREDECESSOR_EXPERIMENT: Final = "intent-v2-locus-validation-v3"
PREDECESSOR_ADJUDICATION_SHA: Final = "4e277a6"
"""v3 tested ``intent-v2-locus-v2`` and ended LOCUS_POLICY_NOT_VALIDATED (facets; an answer-key
omission at C09). It stays untouched as historical evidence."""

POLICY_COMMIT: Final = "ce5195f"
"""The commit that introduced the policy under test."""

PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"

POLICY_VERSION_FROZEN: Final = "intent-v2-locus-v3"
REASONER_CLASS_FROZEN: Final = "XAICanonicalFacetSemanticReasoner"
PROMPT_SHA256_FROZEN: Final = "83a717a9e11d26841b0538bcb781eb766b07bdfc94873213da0965be5ac2d803"
OUTPUT_SCHEMA_FROZEN: Final = "ConcernDraftPayload"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "08d881db080f87b45abebc3fb79ce53229ccf490b1ba331f75744efb55051b79"
)
HISTORICAL_OUTPUT_SCHEMA_SHA256: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)
CANONICAL_FACETS: Final = True
"""Every governor runs ``AdmissionPolicy(canonical_facets=True)``."""

LedgerId = Literal["core", "orion", "jobs", "conflict", "large"]
LEDGERS: Final[tuple[LedgerId, ...]] = ("core", "orion", "jobs", "conflict", "large")
PROJECT_IDS: Final[dict[LedgerId, str]] = {
    "core": "PROJ-LV4-CORE",
    "orion": "PROJ-LV4-ORION",
    "jobs": "PROJ-LV4-JOBS",
    "conflict": "PROJ-LV4-CONFLICT",
    "large": "PROJ-LV4-LARGE",
}
SCOPES: Final[dict[LedgerId, str]] = {
    "core": "dispatch",
    "orion": "orion",
    "jobs": "scheduler",
    "conflict": "portal",
    "large": "payments",
}
MODEL_SEEDED: Final[frozenset[LedgerId]] = frozenset({"core", "orion", "jobs", "large"})
"""Ledgers whose T1 world the model forms (two calls). Only ``conflict`` is seeded by a
human author, because an incompatible pair that already exists cannot be produced by one
model delta under the same-response reference law (design §4.4)."""

CALLS_PER_DELTA: Final = 2
MAX_FRONTIER_CALLS: Final = 18
"""core 4 + orion 4 + jobs 4 + conflict 2 + large 4."""
MAX_COST_USD: Final = 5.0
OBSERVED_AT: Final = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
