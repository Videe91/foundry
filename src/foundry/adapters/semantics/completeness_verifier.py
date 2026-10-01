"""The provider-neutral IE2 Call-3 verifier: semantic completeness through the Model Runtime.

``ModelRuntimeCompletenessVerifier`` sends one ``CompletenessRequest`` to whichever model the
registry has certified for ``ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION`` (REASONER tier), under
the verifier's own policy ``ie2-semantic-completeness-v1``: this instruction and the
``CompletenessReport`` output contract. It names no provider and no model: selection is the
registry's (policy-bound certification), and the identity that actually executed is reported
back so the application can enforce independence from the writer.

An answer that does not satisfy ``CompletenessReport`` (a runtime protocol failure) is recorded
as no report under the routed model's identity: a FAIL, never repaired, never retried.

``ModelRuntimeStructuredCompletenessVerifier`` is the same call under policy
``ie2-semantic-completeness-v2``: its own instruction and the ``StructuredCompletenessReport``
contract, in which every finding is a kind, a direction and verbatim evidence. Same task, same
tier, same provider neutrality; the v1 verifier and its instruction are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    CompletenessReport,
    CompletenessRequest,
    StructuredCompletenessReport,
    VerifierIdentity,
)
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelContract,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
    output_schema_sha256,
)
from foundry.model_runtime.errors import ModelProtocolError
from foundry.model_runtime.routing import select_model
from foundry.model_runtime.runtime import ModelRuntime
from foundry.ports.semantic_completeness import CompletenessVerification

__all__ = [
    "COMPLETENESS_POLICY_ID",
    "COMPLETENESS_V1_CONTRACT",
    "COMPLETENESS_V2_CONTRACT",
    "COMPLETENESS_SYSTEM_INSTRUCTION",
    "COMPLETENESS_SYSTEM_INSTRUCTION_SHA256",
    "STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION",
    "STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256",
    "ModelRuntimeCompletenessVerifier",
    "ModelRuntimeStructuredCompletenessVerifier",
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


STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION: Final[str] = (
    "You are Foundry's semantic completeness verifier for Intent Intelligence v2. You are an\n"
    "independent reviewer: you did not write the claims you are shown, and you decide nothing\n"
    "about what becomes true.\n"
    "\n"
    "You receive one CompletenessRequest. It lists every proposition that a claim-writing model\n"
    "stated about its source sentences, and, for each proposition, the claims that dispose of\n"
    "it: newly ASSERTED claims, or the one existing claim it SUPPORTED. For a correction you are\n"
    "also shown, as context only, the RETIRED claims it would make obsolete.\n"
    "\n"
    "For EVERY proposition answer exactly one question:\n"
    "\n"
    "    Do the proposition's claims, taken together as a union, preserve every operative\n"
    "    assertion of the proposition, without adding a contradictory or materially different\n"
    "    assertion?\n"
    "\n"
    "An operative assertion is anything the proposition asserts that could change what is true\n"
    "or allowed. Classify each one you report as exactly one kind: ACTOR, PERMISSION,\n"
    "OBLIGATION, QUANTITY_LIMIT, TIMING, TIME_ANCHOR (what a timing or deadline is measured\n"
    "from), DEADLINE, CONDITION, ELIGIBILITY, CONSEQUENCE, EXCEPTION, DESTINATION, REPETITION,\n"
    "CHANNEL (the means through which something is done). A condition and its consequence are\n"
    "two assertions: a deadline for doing something does not by itself state what happens when\n"
    "it is missed.\n"
    "\n"
    "Report each problem as one finding with a kind, a direction and verbatim evidence:\n"
    "- MISSING: an operative assertion of the proposition that none of its claims states.\n"
    "  proposition_evidence: the words of the proposition that state it, copied verbatim from\n"
    "  the proposition statement or one of its source sentences. No claim_ref, no\n"
    "  claim_evidence.\n"
    "- UNSUPPORTED: a claim asserting something operative that the proposition does not state\n"
    "  (an extra rule, a stronger or weaker quantity, a new actor, condition or consequence).\n"
    "  claim_ref: that claim's ref, exactly. claim_evidence: the words of that claim's subject,\n"
    "  predicate or value that assert it, copied verbatim. No proposition_evidence.\n"
    "- CONTRADICTORY: a claim that contradicts the proposition. proposition_evidence: the\n"
    "  proposition's words it contradicts, verbatim. claim_ref and claim_evidence: the claim and\n"
    "  its conflicting words, verbatim.\n"
    "Quote the shortest span that states the assertion; never paraphrase, summarise or quote\n"
    "text that is not there. One finding per assertion. explanation is optional free text for a\n"
    "human reader; it is never scored.\n"
    "\n"
    "Verdicts follow from the findings:\n"
    "- COMPLETE: no finding. The union of the claims states every operative assertion and\n"
    "  nothing materially beyond it. A paraphrase is COMPLETE. Several claims that together\n"
    "  state the proposition are COMPLETE. The number of claims never matters.\n"
    "- INCOMPLETE: at least one MISSING finding, and no CONTRADICTORY one.\n"
    "- OVERREACH: UNSUPPORTED findings only.\n"
    "- CONTRADICTORY: at least one CONTRADICTORY finding.\n"
    "If more than one applies, prefer CONTRADICTORY, then INCOMPLETE, then OVERREACH, and list\n"
    "every finding.\n"
    "\n"
    "Rules:\n"
    "- Judge meaning, never wording. Do not penalise paraphrase, word order or a different\n"
    "  predicate name.\n"
    "- Judge each proposition only against its own claims; list their refs, exactly, in\n"
    "  claim_refs.\n"
    "- The source sentences are there to read the proposition; judge the claims against the\n"
    "  proposition, not against your own reading of the source.\n"
    "- You never propose, correct, rewrite or complete a claim, never choose ASSERT, SUPPORT or\n"
    "  SUPERSEDE, and never judge anything but completeness and fidelity.\n"
    "- Return only the StructuredCompletenessReport, with report_format\n"
    "  ie2-semantic-completeness-report.v2: one verdict per proposition.\n"
)

STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256: Final[str] = (
    "07296c5ec2b1f2fee616b3e3a80c762b5882e78c3cd223eba899b1fd74739710"
)
"""A PASTED LITERAL, checked by ``tests/unit/test_semantic_completeness_v2_adapter.py``."""


def _contract(
    policy_version: str,
    instruction: str,
    output_type: type[CompletenessReport] | type[StructuredCompletenessReport],
) -> ModelContract:
    return ModelContract(
        policy_id=COMPLETENESS_POLICY_ID,
        policy_version=policy_version,
        instruction_sha256=hashlib.sha256(instruction.encode()).hexdigest(),
        output_schema_sha256=output_schema_sha256(output_type),
    )


COMPLETENESS_V1_CONTRACT: Final = _contract(
    SEMANTIC_COMPLETENESS_POLICY_VERSION, COMPLETENESS_SYSTEM_INSTRUCTION, CompletenessReport
)
"""The exact contract a v1 request runs under; only a model certified for it may serve it."""
COMPLETENESS_V2_CONTRACT: Final = _contract(
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION,
    StructuredCompletenessReport,
)
"""The exact contract a v2 (structured) request runs under."""


class _RuntimeVerifier:
    _instruction: str
    _policy_version: str
    _output_type: type[CompletenessReport] | type[StructuredCompletenessReport]
    _contract: ModelContract

    def __init__(self, *, runtime: ModelRuntime, run_id: str) -> None:
        self._runtime = runtime
        self._run_id = run_id

    def verify(self, request: CompletenessRequest) -> CompletenessVerification:
        call_id = f"COMPLETENESS-{request.subject_invocation_id}"
        model_request = ModelRequest(
            task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
            tier=ModelTier.REASONER,
            messages=(
                ModelMessage(role=MessageRole.SYSTEM, content=self._instruction),
                ModelMessage(
                    role=MessageRole.USER,
                    content=json.dumps(request.model_dump(mode="json"), sort_keys=True),
                ),
            ),
            required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
            policy_id=COMPLETENESS_POLICY_ID,
            policy_version=self._policy_version,
            trace=ModelTraceContext(run_id=self._run_id, call_id=call_id),
            contract=self._contract,
        )
        try:
            result = self._runtime.execute(model_request, output_type=self._output_type)
        except ModelProtocolError:
            routed = select_model(self._runtime.registry, model_request).identity
            return CompletenessVerification(
                report=None,
                verifier=self._identity(routed.provider, routed.model),
                invocation_id=call_id,
            )
        usage = result.metadata.usage
        return CompletenessVerification(
            report=result.output,
            verifier=self._identity(
                result.metadata.identity.provider, result.metadata.identity.model
            ),
            invocation_id=call_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            wall_clock_ms=usage.wall_clock_ms,
        )

    def _identity(self, provider: str, model: str) -> VerifierIdentity:
        return VerifierIdentity(provider=provider, model=model, policy_version=self._policy_version)


class ModelRuntimeCompletenessVerifier(_RuntimeVerifier):
    """Policy ``ie2-semantic-completeness-v1``: free-text regions."""

    _instruction = COMPLETENESS_SYSTEM_INSTRUCTION
    _policy_version = SEMANTIC_COMPLETENESS_POLICY_VERSION
    _output_type = CompletenessReport
    _contract = COMPLETENESS_V1_CONTRACT


class ModelRuntimeStructuredCompletenessVerifier(_RuntimeVerifier):
    """Policy ``ie2-semantic-completeness-v2``: structured findings with verbatim evidence."""

    _instruction = STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION
    _policy_version = SEMANTIC_COMPLETENESS_POLICY_VERSION_V2
    _output_type = StructuredCompletenessReport
    _contract = COMPLETENESS_V2_CONTRACT
