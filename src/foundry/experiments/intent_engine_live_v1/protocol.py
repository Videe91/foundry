"""Frozen identity, run law and budget of the first live end-to-end Intent Engine validation.

Every value is a pasted literal, checked against the code it names by the offline tests, so a
drift in any identity is a red test before it is a live call. The system under test is the
architecture frozen at ``d229bca`` (IE2) and the current IE3 graph certificate, unchanged.

The question: after realistic requirements and changes over time, does Foundry end with the
correct canonical understanding of what must become true? One canonical sequential run through
the Larkspur Tool Library; every model response is first-response evidence; nothing is
repaired; no experiment-only retry exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from foundry.domain.structural_refusal import ExecutionMode

EXPERIMENT_VERSION: Final = "intent-engine-live-e2e-v1"
ARCHITECTURE_FREEZE_COMMIT: Final = "d229bca"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-10-02-intent-engine-live-e2e-v1/"
)
SEALED_FILE_NAMES: Final = ("manifest.json", "oracle.json")
RAW_FILE_NAMES: Final = ("run.json", "report.json")
ROLE_BINDING_FILE: Final = "role_binding.json"
"""Written only by a founder decision, after the seal and before the first live call."""

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
"""The verified pipeline in EXPERIMENT mode: in this mode the runtime never invokes the
bounded structural re-proposal (that is a PRODUCTION-only law), so the run has no retry at all."""
PROJECT_ID: Final = "PROJ-LARKSPUR-LIVE-1"
FOUNDER: Final = "human://founder"
OBSERVED_AT: Final = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

# --- IE2: the frozen runtime ----------------------------------------------------------------

WRITER_POLICY_VERSION: Final = "intent-v2-locus-v7"
WRITER_REASONER_CLASS: Final = "XAIConflictSemanticReasoner"
WRITER_PROMPT_SHA256: Final = "34b5ef06a9abf26017ce6cba0dfa4d32f5a391a7137261401eaaf5798f0d7d0b"
WRITER_OUTPUT_SCHEMA: Final = "ConflictAccountedDraftPayload"
WRITER_OUTPUT_SCHEMA_SHA256: Final = (
    "2c532fc1fa7630449f92e8b5d3e891141f64ef367dddf6c4e14af6b0253718ea"
)
WRITER_CORRECTION_LAW: Final = "TARGET_SET"
WRITER_TRANSPORT: Final = "xai-sdk (XAISemanticReasoner adapter; not the Model Runtime)"

VERIFIER_TASK: Final = "SEMANTIC_COMPLETENESS_VERIFICATION"
VERIFIER_POLICY_ID: Final = "ie2-semantic-completeness"
VERIFIER_POLICY_VERSION: Final = "ie2-semantic-admission-v4"
VERIFIER_ADAPTER_CLASS: Final = "ModelRuntimeAdmissionVerifier"
VERIFIER_INSTRUCTION_SHA256: Final = (
    "42a58b9a5fc25f0a0642526de612dab59c4fdd75203de54eb4e46c9a34fd43cd"
)
VERIFIER_OUTPUT_SCHEMA: Final = "AdmissionReport"

PIPELINE: Final = "ie2-verified-assimilation-v1"
HOLD_PROTOCOL: Final = "ie2-runtime-holds-v1"
AUTHORITY_PROTOCOL: Final = "ie2-authority-routing-v2"
ADMISSION_POLICY: Final = {"canonical_facets": True, "correction_sets": True}

# --- IE3: the current graph certificate -------------------------------------------------------

IE3_CERTIFICATE_PATH: Final = (
    "tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_v6/"
    "certification.json"
)
"""Reused unchanged from the long-horizon experiment's frozen IE3 identity (runtime-v4)."""

# --- the outcome adjudicator (evaluation only) -------------------------------------------------

ADJUDICATOR_TASK: Final = "EVALUATION"
ADJUDICATOR_POLICY_ID: Final = "intent-engine-outcome-adjudication"
ADJUDICATOR_POLICY_VERSION: Final = "intent-engine-outcome-adjudication-v1"

# --- run law and budget ----------------------------------------------------------------------

RETRY_LAW: Final = (
    "NONE: one canonical sequential run; every model response is first-response evidence; "
    "no manual repair; no experiment-only retry; the runtime's bounded structural "
    "re-proposal is PRODUCTION-only and is not invoked in EXPERIMENT mode; a failed or "
    "refused call is recorded as it happened and the run continues with the next step"
)
MAX_WRITER_CALLS_PER_STEP: Final = 2
"""Call 1 (concern/address) and Call 2 (claims). Nothing else."""
MAX_VERIFIER_CALLS_PER_STEP: Final = 1
MAX_IE3_CALLS: Final = 1
"""IE3 runs once, on the settled IE2 state after the last step."""
MAX_ADJUDICATOR_CALLS: Final = 1
MAX_WRITER_COST_USD: Final = 25.0
