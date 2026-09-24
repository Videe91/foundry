"""Intent Synthesis over the shared Model Runtime (MR3).

Connects the certified ``IntentSynthesizer`` port to the certified ``ModelRuntime``. It
converts model output and nothing else: no governance, no routing, no validation, no
ledger. T7 and T8 remain the authority, and this adapter is deliberately powerless to
weaken them.

Provider-neutral by construction. Nothing here names a vendor; swapping the model is a
Model Runtime configuration change, and the same adapter class serves any certified
provider.

Two laws carry the weight of this slice.

**Authorship must stay truthful (C9/I22).** T8 reads ``fingerprint`` *before* the call and
writes it as durable authorship on the decision record. So an instance is bound to one
expected ``ModelIdentity``, and if the runtime executes a different model the adapter
raises rather than returning a result — a decision naming a model that never ran would be
a durable lie, and nothing model-derived has been written yet, so failing here is safe.

**The model must not be able to state what it cannot know.** The legacy ``GapProposal``
carries ``source_event_ids``, ``affected_proposal_ids``, a free ``GapKind`` and
``blocking``. The Intent request exposes no event ids at all, so those fields could only
ever be invented. The model-facing draft omits them entirely: the model cannot express
them, rather than being trusted not to. Runtime maps the draft into ``GapProposal``
deterministically, and T8's own ``_validate_model_gaps`` still re-checks the result
independently.

**Known limitation, stated rather than buried.** Because the fingerprint is read before
execution and becomes durable, dynamic fallback or model-switching *within one synthesis
invocation* is not legal under the current authorship contract. That is a real constraint
on multi-model routing, and it belongs to a future Reasoning Orchestrator and authorship
evolution — not to this slice.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import GapKind
from foundry.domain.intent_synthesis import (
    IntentSynthesisResult,
    RequirementSynthesisProposal,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.intelligence.proposals import GapProposal
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.errors import ModelProtocolError
from foundry.model_runtime.runtime import ModelRuntime
from foundry.ports.intent_synthesizer import IntentSynthesisRequest

__all__ = [
    "INTENT_SYNTHESIS_POLICY_ID",
    "INTENT_SYNTHESIS_POLICY_VERSION",
    "SYSTEM_INSTRUCTION",
    "SYSTEM_INSTRUCTION_SHA256",
    "IntentAmbiguityDraft",
    "IntentSynthesisDraftPayload",
    "ModelRuntimeIntentSynthesizer",
    "render_intent_synthesis_request",
]

INTENT_SYNTHESIS_POLICY_ID: Final[str] = "intent-synthesis.slice1"
INTENT_SYNTHESIS_POLICY_VERSION: Final[str] = "intent-synthesis-runtime-v1"
"""Pinned policy identity. It lands in ``ReasonerFingerprint.policy_version`` and becomes
durable, so a prompt change requires a deliberate version bump — never a silent edit."""


SYSTEM_INSTRUCTION: Final[str] = """\
You are an untrusted Intent Synthesis reasoner inside Foundry.

You are not authority. You are not project memory. You do not own the ledger, write \
events, create Requirements, or verify anything. Deterministic Foundry governance decides \
what, if anything, your output is allowed to affect.

Your only job is: given the exact supplied bounded semantic basis and the exact supplied \
known intent snapshot, propose Requirements that are genuinely supported by that material, \
or report blocking ambiguity when a sound Requirement cannot be formed.

EVIDENCE BOUNDARY
Reason only over request.basis, request.known_intent_objects and \
request.allowed_target_kinds. Do not perform external research. Do not use the web or any \
tool. Do not rely on unstated facts. Do not invent identifiers. The request contains no \
evidence content, so do not claim to have read any.

SLICE 1 IS REQUIREMENT ONLY
The only legal synthesized intent kind is REQUIREMENT. Do not propose a Goal, Constraint, \
Intent, Decision, Assumption, Contract or any other kind, even where one seems useful.

BASIS REFERENCES
A proposal may cite only claim_id values present in the supplied basis. Never invent a \
claim id. Cite the minimum sufficient set of basis claims for the commitment you propose.

EXISTING INTENT
When naming an existing target, use only object ids present in known_intent_objects.
NEW: the Requirement is not already represented; do not name relates_to_object_id.
EXISTING_UNCHANGED: an existing non-stale object already expresses the same commitment \
adequately; name that exact object id.
REPLACES_STALE: a visible object is explicitly marked is_stale = true and your proposed \
Requirement is its appropriate replacement; name that exact object id.
Do not treat sound, non-stale intent as stale. Do not replace an object merely to reword it.

AMBIGUITY
If the supplied material permits materially different Requirements and you cannot form one \
without inventing a choice, report ambiguity instead. Do not guess. Do not re-open \
contradictions runtime already filtered out. Do not use ambiguity as a generic refusal.

RATIONALE
One to three sentences explaining the connection to the cited basis. It is not \
chain-of-thought. Do not emit hidden reasoning or deliberation.

CONFIDENCE
Optional metadata only. It is never authority. Do not fabricate a precision you do not have.

AUTHORITY IS NOT YOURS
Never emit or claim authority, CANONICAL, PROPOSED, materiality, scope, lifecycle, \
object_id, event_id, proposal_instance_id, created_at, provenance, relations, \
requires_metric or requires_verification. Foundry runtime owns every one of them.

OUTPUT
Return Requirement proposals, or blocking ambiguity gaps. Never both. Never neither.\
"""

SYSTEM_INSTRUCTION_SHA256: Final[str] = (
    "af49dbd3ac8049642cfb7a2af70acf719da4e2c2af5faf7128ec47d6413e8f5d"
)
"""Pasted literal digest of ``SYSTEM_INSTRUCTION``.

Deliberately NOT computed at import time: a digest derived from the prompt would agree
with any prompt whatsoever. A test hashes the live text and compares, so editing the
instruction breaks the build until the hash and the policy version are both updated on
purpose.
"""


class IntentAmbiguityDraft(FrozenModel):
    """What the model may say about an ambiguity — and nothing more.

    Deliberately smaller than the frozen ``GapProposal``. That type carries
    ``source_event_ids``, ``affected_proposal_ids``, ``kind`` and ``blocking``; the Intent
    request exposes no event ids and Slice 1 admits only one gap kind, so a model filling
    those fields would be inventing provenance and classification. Omitting them makes
    that structurally impossible rather than merely discouraged.
    """

    proposal_id: str = Field(min_length=1)
    subject_key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class IntentSynthesisDraftPayload(FrozenModel):
    """The model-facing output envelope.

    Both branches are carried through exactly as returned. The adapter never picks one,
    never fills an empty result and never repairs a mixed one: C24 is T8's law, and
    deterministic validation must stay independent of the adapter that produced the input.
    """

    proposals: tuple[RequirementSynthesisProposal, ...] = ()
    ambiguity_gaps: tuple[IntentAmbiguityDraft, ...] = ()


def render_intent_synthesis_request(request: IntentSynthesisRequest) -> str:
    """Canonical JSON of the exact approved request. Nothing added, nothing fetched.

    The bounded request is what T7 decided the model may see. Enriching it here would
    quietly widen the model's context beyond what was approved, and no test downstream
    would notice.
    """
    return json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _as_gap_proposal(draft: IntentAmbiguityDraft) -> GapProposal:
    """Deterministic mapping. Every field the model could not know is fixed by runtime."""
    return GapProposal(
        proposal_id=draft.proposal_id,
        kind=GapKind.AMBIGUITY,
        subject_key=draft.subject_key,
        description=draft.description,
        affected_proposal_ids=(),
        source_event_ids=(),
        blocking=True,
        confidence=draft.confidence,
    )


class ModelRuntimeIntentSynthesizer:
    """An ``IntentSynthesizer`` backed by the shared Model Runtime.

    Bound to one expected ``ModelIdentity`` because its fingerprint becomes durable
    authorship. Holds no conversation, no history and no project state: each call carries
    its complete bounded request.
    """

    def __init__(
        self,
        *,
        runtime: ModelRuntime,
        model_identity: ModelIdentity,
        trace_factory: Callable[[], ModelTraceContext],
        execution_constraints: ModelExecutionConstraints | None = None,
    ) -> None:
        self._runtime = runtime
        self._model_identity = model_identity
        self._trace_factory = trace_factory
        self._constraints = execution_constraints or ModelExecutionConstraints()

    def __repr__(self) -> str:
        return (
            f"ModelRuntimeIntentSynthesizer(model={self._model_identity.provider}/"
            f"{self._model_identity.model}, policy={INTENT_SYNTHESIS_POLICY_VERSION!r})"
        )

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        """Configured identity plus pinned policy. The model never supplies any of it."""
        return ReasonerFingerprint(
            provider=self._model_identity.provider,
            model=self._model_identity.model,
            policy_version=INTENT_SYNTHESIS_POLICY_VERSION,
        )

    def synthesize(self, request: IntentSynthesisRequest) -> IntentSynthesisResult:
        model_request = ModelRequest(
            task=ModelTask.INTENT_SYNTHESIS,
            tier=ModelTier.REASONER,
            messages=(
                ModelMessage(role=MessageRole.SYSTEM, content=SYSTEM_INSTRUCTION),
                ModelMessage(
                    role=MessageRole.USER, content=render_intent_synthesis_request(request)
                ),
            ),
            required_capabilities=frozenset(
                {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
            ),
            policy_id=INTENT_SYNTHESIS_POLICY_ID,
            policy_version=INTENT_SYNTHESIS_POLICY_VERSION,
            constraints=self._constraints,
            trace=self._trace_factory(),
        )

        result = self._runtime.execute(model_request, output_type=IntentSynthesisDraftPayload)
        self._require_configured_identity(result.metadata.identity)

        return IntentSynthesisResult(
            proposals=result.output.proposals,
            gap_proposals=tuple(_as_gap_proposal(d) for d in result.output.ambiguity_gaps),
        )

    def _require_configured_identity(self, executed: ModelIdentity) -> None:
        """Fail closed when the runtime executed a model this instance does not speak for.

        The runtime may consider the routed model entirely valid; that is not the question.
        T8 has already read this instance's fingerprint as the author, so returning a
        result here would write a decision record naming a model that never ran. Nothing
        model-derived is durable yet, so refusing is the safe outcome.
        """
        if executed != self._model_identity:
            raise ModelProtocolError(
                f"this synthesizer speaks for "
                f"{self._model_identity.provider}/{self._model_identity.model}, but the "
                f"runtime executed {executed.provider}/{executed.model}; its fingerprint "
                "is already durable authorship, so no result is returned"
            )
