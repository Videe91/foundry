"""Frozen identity, configuration and budgets of locus validation v6 (design §2, §10).

Everything here is a pasted literal. The policy under test is ``intent-v2-locus-v6``
(``XAICorrectionSetSemanticReasoner``: canonical facets, governed-concern grain, proposition
accounting and the TARGET_SET correction law, output contract ``AccountedDraftPayload``),
unchanged. Every governor of this validation runs
``AdmissionPolicy(canonical_facets=True, correction_sets=True)``: atomic correction-set
authority (``ie2-authority-routing-v2``) is enabled here and nowhere in production. Every
semantic call gets exactly ONE attempt (``ExecutionMode.EXPERIMENT``); a structurally refused
answer is a failed attempt, never re-proposed. Human authority is a deterministic scripted
actor, never the model. The experiment is single-use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

from foundry.domain.structural_refusal import ExecutionMode

EXPERIMENT_VERSION: Final = "intent-v2-locus-validation-v6"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-30-locus-validation-v6/"
DESIGN_SPEC_PATH: Final = "docs/superpowers/specs/2026-09-30-locus-policy-validation-v6-design.md"
GRAIN_DECISION_PATH: Final = (
    "docs/superpowers/specs/2026-09-30-ie2-governed-concern-grain-clarification.md"
)
SEALED_FILE_NAMES: Final = ("manifest.json", "expectations.json")
RAW_FILE_NAMES: Final = ("run.json",)

PREDECESSOR_EXPERIMENT: Final = "intent-v2-locus-validation-v5"
"""v5 tested ``intent-v2-locus-v5``. It stays untouched; its regression texts are reused here
byte for byte under new evidence ids."""

POLICY_COMMIT: Final = "be780ce"
"""The commit that introduced the policy under test (correction target sets, v6)."""
AUTHORITY_COMMIT: Final = "537d025"
"""The commit that introduced atomic correction-set authority (``ie2-authority-routing-v2``)."""

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
"""Single attempt per semantic call; no re-proposal (``REPROPOSE_MODES`` excludes it)."""

PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"

POLICY_VERSION_FROZEN: Final = "intent-v2-locus-v6"
REASONER_CLASS_FROZEN: Final = "XAICorrectionSetSemanticReasoner"
PROMPT_SHA256_FROZEN: Final = "13aa87743ed7a3f3ca8620d1ceec914a26bcf916196cd592b2aa713b34af5190"
OUTPUT_SCHEMA_FROZEN: Final = "AccountedDraftPayload"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142"
)
HISTORICAL_OUTPUT_SCHEMA_SHA256: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)
CORRECTION_LAW_FROZEN: Final = "TARGET_SET"
CANONICAL_FACETS: Final = True
CORRECTION_SETS: Final = True
"""Every governor runs ``AdmissionPolicy(canonical_facets=True, correction_sets=True)``."""
AUTHORITY_PROTOCOL: Final = "ie2-authority-routing-v2"

LedgerId = Literal["core", "orion", "jobs", "conflict", "large", "dense"]
LEDGERS: Final[tuple[LedgerId, ...]] = ("core", "orion", "jobs", "conflict", "large", "dense")
PROJECT_IDS: Final[dict[LedgerId, str]] = {
    "core": "PROJ-LV6-CORE",
    "orion": "PROJ-LV6-ORION",
    "jobs": "PROJ-LV6-JOBS",
    "conflict": "PROJ-LV6-CONFLICT",
    "large": "PROJ-LV6-LARGE",
    "dense": "PROJ-LV6-DENSE",
}
SCOPES: Final[dict[LedgerId, str]] = {
    "core": "dispatch",
    "orion": "orion",
    "jobs": "scheduler",
    "conflict": "portal",
    "large": "payments",
    "dense": "carshare",
}
MODEL_SEEDED: Final[frozenset[LedgerId]] = frozenset({"core", "orion", "jobs", "large", "dense"})
"""Ledgers whose T1 world the model forms. Only ``conflict`` is seeded by a human author."""

BRANCHED: Final[LedgerId] = "dense"
"""The one ledger whose post-T2 state is decided by the scripted human, in two branches."""
Branch = Literal["AGREE", "DECLINE"]
BRANCHES: Final[tuple[Branch, ...]] = ("AGREE", "DECLINE")
"""After dense T2, the store is cloned once per branch: the scripted human AGREEs every
pending correction set in one, DECLINEs every one in the other; each then assimilates the
same T3 delta."""

ARCHITECT: Final = "human://validation-architect"
"""The scripted human authority. It holds a live project-wide ``AuthorityRecord`` in the dense
ledger, recorded before T1. It is never the model."""

CALLS_PER_DELTA: Final = 2
MAX_FRONTIER_CALLS: Final = 26
"""core 4 + orion 4 + jobs 4 + conflict 2 + large 4 + dense 8 (T1, T2, and T3 in each branch).
No re-proposal call exists."""
MAX_COST_USD: Final = 8.0
OBSERVED_AT: Final = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
