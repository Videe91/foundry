"""Frozen identity, configuration and budgets of the IE2 + IE3 long-horizon experiment.

Every value is a pasted literal (design §3, §4, §12). IE2 is the validated
``intent-v2-locus-v5`` policy on xAI ``grok-4.6`` (reasoning effort high), exactly as
validation v5 ran it: ``XAIReproposingSemanticReasoner`` under
``AdmissionPolicy(canonical_facets=True)`` in ``ExecutionMode.EXPERIMENT``. IE3 is the
certified ``openai/gpt-6-astra`` identity of the exam-v6 certificate (runtime-v4), also in
``ExecutionMode.EXPERIMENT``. Every semantic call has exactly one attempt; nothing is
re-proposed, repaired or retried. The experiment is single-use.

This module decides nothing semantic and never imports the answer key.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from foundry.domain.structural_refusal import ExecutionMode

EXPERIMENT_VERSION: Final = "intent-ie2-ie3-long-horizon-v1"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1/"
DESIGN_SPEC_PATH: Final = "docs/superpowers/specs/2026-09-29-ie2-ie3-long-horizon-v1-design.md"
SEALED_FILE_NAMES: Final = ("manifest.json", "expectations.json")
RAW_FILE_NAMES: Final = ("run.json",)

HISTORICAL_EXPERIMENT: Final = "intent-v2-long-horizon-bounded-memory-v1"
HISTORICAL_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
)
HISTORICAL_CORPUS_SHA256: Final = "50b83eeaa31d9ee2049155f959cece3058f96f620b19d8c88413bb2e87ffb21d"
"""The 9P3 manifest's ``corpus_sha256``: the structural evidence records of all 192 items."""

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
PROJECT_ID: Final = "PROJ-LH23-ORION"
TURNS: Final = tuple(range(1, 17))

# --- IE2: the validated locus policy (validation v5, 20b4005) -------------------------------

IE2_PROVIDER: Final = "xai"
IE2_MODEL: Final = "grok-4.6"
IE2_REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"
IE2_POLICY_VERSION: Final = "intent-v2-locus-v5"
IE2_REASONER_CLASS: Final = "XAIReproposingSemanticReasoner"
IE2_PROMPT_SHA256: Final = "cc913e3d7aee49e13e2e40745ddc791df0dee0e663893f42be39a475e16a09dc"
IE2_OUTPUT_SCHEMA: Final = "AccountedDraftPayload"
IE2_OUTPUT_SCHEMA_SHA256: Final = "921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142"
IE2_VALIDATION: Final = "intent-v2-locus-validation-v5 LOCUS_POLICY_VALIDATED at 20b4005"
CANONICAL_FACETS: Final = True

# --- IE3: the certified Astra identity (exam v6, 4d654b1) -----------------------------------

IE3_PROVIDER: Final = "openai"
IE3_MODEL: Final = "gpt-6-astra"
IE3_REASONING_EFFORT: Final = "high"
IE3_REASONING_MODE: Final = "standard"
IE3_OUTPUT_GUARD: Final = 16000
IE3_TIMEOUT_SECONDS: Final = 180.0
IE3_TASK: Final = "INTENT_GRAPH_SYNTHESIS"
IE3_POLICY_ID: Final = "intent-synthesis.graph-v1"
IE3_POLICY_VERSION: Final = "intent-graph-synthesis-runtime-v4"
IE3_PROMPT_SHA256: Final = "fd395605ecd12f39430a9bb0140bf1a3ce6dc43643859e94485a23970856a6e4"
IE3_CANONICAL_SCHEMA_SHA256: Final = (
    "6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494"
)
IE3_WIRE_SCHEMA_SHA256: Final = "7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa"
IE3_WIRE_SCHEMA_COMPILER: Final = "foundry.openai-structured-outputs.v1"
IE3_EXAM_VERSION: Final = "6"
IE3_EXAM_SHA256: Final = "818f6f87a81a66680625da1563496bf0844efff19b1fe9e6686803aecbd7243c"
IE3_CERTIFICATE_PATH: Final = (
    "tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_v6/"
    "certification.json"
)
IE3_CERTIFICATE_SHA256: Final = "851c8a6b89b9962ea0561a38b70f68b2385fad72750ffc958bbb807bf93e5904"
ROOT_STALENESS_BOUNDARY_COMMIT: Final = "0b8f077"

# --- budgets (design §12) -------------------------------------------------------------------

IE2_CALLS_PER_TURN: Final = 2
IE3_CALLS_PER_TURN: Final = 1
MAX_IE2_CALLS: Final = 32
MAX_IE3_CALLS: Final = 16
MAX_IE2_COST_USD: Final = 20.0
"""xAI reports cost per call; OpenAI does not, so IE3 is bounded by calls and output guard."""

OBSERVED_AT: Final = datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
