"""Frozen identity, run law and budget of the second live end-to-end Intent Engine validation.

A new lineage. ``intent-engine-live-e2e-v1`` stands, frozen, as FAIL (52fc54a). v2 changes
exactly what v1 taught, and nothing else:

1. **Founder-decision routing** by runtime provenance (``ROUTING_LAW``): a preregistered decision
   binds to the correction work proposed inside its step's ledger window by judgments that saw
   exactly that step's immutable evidence; never to a concern label or any model wording.
2. **The semantic admission verifier v5** (``ie2-semantic-admission-v5``): every proposed
   supersession target is shown separately and judged SUPPORTED_REPLACEMENT /
   CONFLICTING_EVIDENCE / UNCERTAIN (``REPLACEMENT_LAW``).

Same corpus, same oracle meaning, same scorer, same writer, IE3 and adjudicator contracts, same
no-retry law, same budgets. Every value is a pasted literal checked by the offline tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from foundry.domain.structural_refusal import ExecutionMode

EXPERIMENT_VERSION: Final = "intent-engine-live-e2e-v2"
PREDECESSOR: Final = "intent-engine-live-e2e-v1: sealed verdict FAIL at 52fc54a (frozen)"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-10-02-intent-engine-live-e2e-v2/"
)
SEALED_FILE_NAMES: Final = ("manifest.json", "oracle.json")
RAW_FILE_NAMES: Final = ("run.json", "report.json")
ROLE_BINDING_FILE: Final = "role_binding.json"
"""Written only by a founder decision, after the seal and before the first live call."""

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
"""In this mode the runtime never invokes the PRODUCTION-only bounded structural re-proposal,
so the run has no retry at all."""
PROJECT_ID: Final = "PROJ-LARKSPUR-LIVE-2"
FOUNDER: Final = "human://founder"
OBSERVED_AT: Final = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

# --- IE2 ---------------------------------------------------------------------------------------

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
VERIFIER_POLICY_VERSION: Final = "ie2-semantic-admission-v5"
VERIFIER_ADAPTER_CLASS: Final = "ModelRuntimeAdmissionVerifierV5"
VERIFIER_INSTRUCTION_SHA256: Final = (
    "cd05d22557307c7e62275f8f965a3dff36d55a24c6f8e367ac82248b81bc10da"
)
VERIFIER_OUTPUT_SCHEMA: Final = "AdmissionReportV5"

PIPELINE: Final = "ie2-verified-assimilation-v1"
HOLD_PROTOCOL: Final = "ie2-runtime-holds-v1"
AUTHORITY_PROTOCOL: Final = "ie2-authority-routing-v2"
ADMISSION_POLICY: Final = {"canonical_facets": True, "correction_sets": True}

ROUTING_LAW: Final = (
    "provenance-v1: a preregistered founder decision binds to the PENDING correction set(s) "
    "proposed inside its step's ledger window (from the step's evidence ingestion to the end "
    "of its assimilation) whose every member judgment saw exactly the step's immutable "
    "evidence item; exactly one -> delivered; none -> nothing to decide with the recorded "
    "runtime reason (HELD, REFUSED, NO_CORRECTION_PROPOSED), else RoutingUnexplained; more "
    "than one, or any foreign provenance -> RoutingAmbiguous. RoutingAmbiguous and "
    "RoutingUnexplained stop the run: NOT_VALIDATED. No subject, facet, predicate, value or "
    "statement is ever read."
)
REPLACEMENT_LAW: Final = (
    "ie2-semantic-admission-v5: every proposed supersession target is shown to the verifier "
    "apart from ordinary consistency context and judged SUPPORTED_REPLACEMENT (continue to "
    "correction sets and founder authority), CONFLICTING_EVIDENCE (the existing contradiction "
    "hold; the settled claim stays current; no correction work) or UNCERTAIN (the existing "
    "unresolved hold). Deterministic code checks only that every supplied target is judged "
    "exactly once and nothing else is named; a writer conflict and a replacement conflict on "
    "one unit are one gap."
)

# --- IE3 and the outcome adjudicator (unchanged from v1) ------------------------------------------

IE3_CERTIFICATE_PATH: Final = (
    "tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_v6/"
    "certification.json"
)
ADJUDICATOR_TASK: Final = "EVALUATION"
ADJUDICATOR_POLICY_ID: Final = "intent-engine-outcome-adjudication"
ADJUDICATOR_POLICY_VERSION: Final = "intent-engine-outcome-adjudication-v1"

# --- run law and budget (unchanged from v1) ------------------------------------------------------

RETRY_LAW: Final = (
    "NONE: one canonical sequential run; every model response is first-response evidence; "
    "no manual repair; no experiment-only retry; the runtime's bounded structural "
    "re-proposal is PRODUCTION-only and is not invoked in EXPERIMENT mode; a failed or "
    "refused call is recorded as it happened and the run continues with the next step"
)
MAX_WRITER_CALLS_PER_STEP: Final = 2
MAX_VERIFIER_CALLS_PER_STEP: Final = 1
MAX_IE3_CALLS: Final = 1
MAX_ADJUDICATOR_CALLS: Final = 1
MAX_WRITER_COST_USD: Final = 25.0
