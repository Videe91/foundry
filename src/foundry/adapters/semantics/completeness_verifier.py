"""The provider-neutral IE2 Call-3 verifier: semantic completeness through the Model Runtime.

``ModelRuntimeCompletenessVerifier`` sends one ``CompletenessRequest`` to whichever model the
registry has certified for ``ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION`` (REASONER tier), under
the verifier's own policy ``ie2-semantic-completeness-v1``: this instruction and the
``CompletenessReport`` output contract. It names no provider and no model: selection is the
registry's (policy-bound certification), and the identity that actually executed is reported
back so the application can enforce independence from the writer.

An answer that does not satisfy ``CompletenessReport`` (a runtime protocol failure) is recorded
as no report under the routed model's identity: a FAIL, never repaired, never retried.
"""

from __future__ import annotations

import json
from typing import Final

from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
    CompletenessRequest,
    VerifierIdentity,
)
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.errors import ModelProtocolError
from foundry.model_runtime.routing import select_model
from foundry.model_runtime.runtime import ModelRuntime
from foundry.ports.semantic_completeness import CompletenessVerification

__all__ = [
    "COMPLETENESS_POLICY_ID",
    "COMPLETENESS_SYSTEM_INSTRUCTION",
    "COMPLETENESS_SYSTEM_INSTRUCTION_SHA256",
    "ModelRuntimeCompletenessVerifier",
]

COMPLETENESS_POLICY_ID: Final = "ie2-semantic-completeness"

COMPLETENESS_SYSTEM_INSTRUCTION: Final[str] = (
    "You are Foundry's semantic completeness verifier for Intent Intelligence v2. You are an\n"
    "independent reviewer: you did not write the claims you are shown, and you decide nothing\n"
    "about what becomes true.\n"
    "\n"
    "You receive one CompletenessRequest. It lists every proposition that a claim-writing model\n"
    "stated about its source sentences, and, for each proposition, the claims that "
    "dispose of it:\n"
    "newly ASSERTED claims, or the one existing claim it SUPPORTED. For a correction "
    "you are also\n"
    "shown, as context only, the RETIRED claims it would make obsolete.\n"
    "\n"
    "For EVERY proposition answer exactly one question:\n"
    "\n"
    "    Do the proposition's claims, taken together as a union, preserve every operative\n"
    "    assertion of the proposition, without adding a contradictory or materially different\n"
    "    assertion?\n"
    "\n"
    "An operative assertion is anything the proposition asserts that could change what is true\n"
    "or allowed: an actor, an obligation or permission, a quantity or limit, a timing, a\n"
    "deadline, a condition or eligibility rule, a consequence or effect, an exception, a\n"
    "destination, a repetition rule. A condition and its consequence are two assertions: a\n"
    "deadline for doing something does not by itself state what happens when it is missed.\n"
    "\n"
    "Verdicts:\n"
    "- COMPLETE: the union of the claims states every operative assertion of the proposition and\n"
    "  nothing materially beyond it. A paraphrase is COMPLETE. Several claims that "
    "together state\n"
    "  the proposition are COMPLETE. The number of claims never matters.\n"
    "- INCOMPLETE: at least one operative assertion of the proposition is stated by none of its\n"
    "  claims. List each missing assertion in missing.\n"
    "- OVERREACH: a claim asserts something operative that the proposition does not "
    "state (an extra\n"
    "  rule, a stronger or weaker quantity, a new actor, condition or consequence). List each in\n"
    "  unsupported.\n"
    "- CONTRADICTORY: the claims contradict the proposition or each other. List each in\n"
    "  contradictory.\n"
    "If more than one applies, prefer CONTRADICTORY, then INCOMPLETE, then "
    "OVERREACH, and list what\n"
    "you found.\n"
    "\n"
    "Rules:\n"
    "- Judge meaning, never wording. Do not penalise paraphrase, word order or a "
    "different predicate\n"
    "  name.\n"
    "- Judge each proposition only against its own claims; list their refs, exactly, "
    "in claim_refs.\n"
    "- The source sentences are there to read the proposition; judge the claims against the\n"
    "  proposition, not against your own reading of the source.\n"
    "- You never propose, correct, rewrite or complete a claim, never choose ASSERT, SUPPORT or\n"
    "  SUPERSEDE, and never judge anything but completeness and fidelity.\n"
    "- Return only the CompletenessReport: one verdict per proposition.\n"
)

COMPLETENESS_SYSTEM_INSTRUCTION_SHA256: Final[str] = (
    "56b753a9156883264f9bdd070f9b5b63facb653c68bdb5fbcd0c0322814a0d7c"
)
"""A PASTED LITERAL, checked by ``tests/unit/test_semantic_completeness_adapters.py``."""


class ModelRuntimeCompletenessVerifier:
    def __init__(self, *, runtime: ModelRuntime, run_id: str) -> None:
        self._runtime = runtime
        self._run_id = run_id

    def verify(self, request: CompletenessRequest) -> CompletenessVerification:
        call_id = f"COMPLETENESS-{request.subject_invocation_id}"
        model_request = ModelRequest(
            task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
            tier=ModelTier.REASONER,
            messages=(
                ModelMessage(role=MessageRole.SYSTEM, content=COMPLETENESS_SYSTEM_INSTRUCTION),
                ModelMessage(
                    role=MessageRole.USER,
                    content=json.dumps(request.model_dump(mode="json"), sort_keys=True),
                ),
            ),
            required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
            policy_id=COMPLETENESS_POLICY_ID,
            policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION,
            trace=ModelTraceContext(run_id=self._run_id, call_id=call_id),
        )
        try:
            result = self._runtime.execute(model_request, output_type=CompletenessReport)
        except ModelProtocolError:
            routed = select_model(self._runtime.registry, model_request).identity
            return CompletenessVerification(
                report=None,
                verifier=_identity(routed.provider, routed.model),
                invocation_id=call_id,
            )
        usage = result.metadata.usage
        return CompletenessVerification(
            report=result.output,
            verifier=_identity(result.metadata.identity.provider, result.metadata.identity.model),
            invocation_id=call_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            wall_clock_ms=usage.wall_clock_ms,
        )


def _identity(provider: str, model: str) -> VerifierIdentity:
    return VerifierIdentity(
        provider=provider, model=model, policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
    )
