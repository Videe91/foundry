"""Frozen identity, configuration and budgets of locus validation v5 (design §2, §10).

Everything here is a pasted literal. The policy under test is ``intent-v2-locus-v5``
(``XAIReproposingSemanticReasoner``: canonical facets, governed-concern grain and proposition
accounting, output contract ``AccountedDraftPayload``), run under
``AdmissionPolicy(canonical_facets=True)`` in ``ExecutionMode.EXPERIMENT``: every semantic
call gets exactly ONE attempt, and a structurally refused answer is a failed attempt, never
re-proposed. The provider configuration is v2's to v4's, held constant so that the policy is
the only variable. The experiment is single-use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

from foundry.domain.structural_refusal import ExecutionMode

EXPERIMENT_VERSION: Final = "intent-v2-locus-validation-v5"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-29-locus-validation-v5/"
DESIGN_SPEC_PATH: Final = "docs/superpowers/specs/2026-09-29-locus-policy-validation-v5-design.md"
SEALED_FILE_NAMES: Final = ("manifest.json", "expectations.json")
RAW_FILE_NAMES: Final = ("run.json",)

PREDECESSOR_EXPERIMENT: Final = "intent-v2-locus-validation-v4"
PREDECESSOR_ADJUDICATION_SHA: Final = "ae1ebcc"
"""v4 tested ``intent-v2-locus-v3`` and ended LOCUS_POLICY_NOT_VALIDATED (claim extraction:
C09's acknowledgement and C8's extension silently dropped). It stays untouched."""

POLICY_COMMIT: Final = "47b599c"
"""The commit at which the policy under test (introduced with proposition accounting in
``c4a4649`` and made re-proposable, production-only, in ``47b599c``) was taken."""

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
"""Single attempt per semantic call; no re-proposal (``REPROPOSE_MODES`` excludes it)."""

PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"

POLICY_VERSION_FROZEN: Final = "intent-v2-locus-v5"
REASONER_CLASS_FROZEN: Final = "XAIReproposingSemanticReasoner"
PROMPT_SHA256_FROZEN: Final = "cc913e3d7aee49e13e2e40745ddc791df0dee0e663893f42be39a475e16a09dc"
OUTPUT_SCHEMA_FROZEN: Final = "AccountedDraftPayload"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142"
)
HISTORICAL_OUTPUT_SCHEMA_SHA256: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)
CANONICAL_FACETS: Final = True
"""Every governor runs ``AdmissionPolicy(canonical_facets=True)``."""

LedgerId = Literal["core", "orion", "jobs", "conflict", "large"]
LEDGERS: Final[tuple[LedgerId, ...]] = ("core", "orion", "jobs", "conflict", "large")
PROJECT_IDS: Final[dict[LedgerId, str]] = {
    "core": "PROJ-LV5-CORE",
    "orion": "PROJ-LV5-ORION",
    "jobs": "PROJ-LV5-JOBS",
    "conflict": "PROJ-LV5-CONFLICT",
    "large": "PROJ-LV5-LARGE",
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
"""core 4 + orion 4 + jobs 4 + conflict 2 + large 4. No re-proposal call exists."""
MAX_COST_USD: Final = 5.0
OBSERVED_AT: Final = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
