"""The four model roles, what each requires, who can lawfully serve it, and the binding check.

No identity is selected here. ``ROLE_REQUIREMENTS`` and ``CANDIDATES`` are sealed facts about the
repository at the freeze (configured providers, adapters, certificates). The founder binds the
writer, verifier and adjudicator identities in ``role_binding.json`` after the seal; the runner
refuses to start unless ``binding_findings`` is empty. IE3 is not chosen: it is the identity the
current graph certificate binds.

Independence (the runtime law, ``independent``): two models are independent iff provider or model
differs. The writer and verifier must be independent (the pipeline refuses otherwise); the
adjudicator must differ from the writer, the verifier and the IE3 model, because it judges all
three.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.experiments.intent_engine_live_v2 import protocol
from foundry.experiments.long_horizon_ie2_ie3 import protocol as lh

__all__ = [
    "CANDIDATES",
    "IE3_IDENTITY",
    "ROLE_REQUIREMENTS",
    "BoundModel",
    "Candidate",
    "RoleBinding",
    "RoleRequirement",
    "binding_findings",
]

Role = Literal["WRITER", "VERIFIER", "IE3", "ADJUDICATOR"]


class RoleRequirement(FrozenModel):
    role: Role
    job: str
    transport: str
    identity_contract: dict[str, str]
    independence: str
    authority: str


ROLE_REQUIREMENTS: Final[tuple[RoleRequirement, ...]] = (
    RoleRequirement(
        role="WRITER",
        job="IE2 Call 1 (concern/address binding) and Call 2 (claims, proposition accounting, "
        "conflict declarations) for every step",
        transport=protocol.WRITER_TRANSPORT,
        identity_contract={
            "policy_version": protocol.WRITER_POLICY_VERSION,
            "reasoner_class": protocol.WRITER_REASONER_CLASS,
            "prompt_sha256": protocol.WRITER_PROMPT_SHA256,
            "output_schema": protocol.WRITER_OUTPUT_SCHEMA,
            "output_schema_sha256": protocol.WRITER_OUTPUT_SCHEMA_SHA256,
            "correction_law": protocol.WRITER_CORRECTION_LAW,
        },
        independence="independent of the verifier (runtime law)",
        authority="proposals only; admission, authority routing and the founder decide",
    ),
    RoleRequirement(
        role="VERIFIER",
        job="semantic admission (completeness and consistency) of every Call-2 proposal",
        transport="Model Runtime, task SEMANTIC_COMPLETENESS_VERIFICATION (contract-bound)",
        identity_contract={
            "policy_id": protocol.VERIFIER_POLICY_ID,
            "policy_version": protocol.VERIFIER_POLICY_VERSION,
            "adapter_class": protocol.VERIFIER_ADAPTER_CLASS,
            "instruction_sha256": protocol.VERIFIER_INSTRUCTION_SHA256,
            "output_schema": protocol.VERIFIER_OUTPUT_SCHEMA,
            "certification": "a descriptor certifying exactly ADMISSION_V5_CONTRACT for the task",
        },
        independence="independent of the writer (runtime law)",
        authority="verdicts only; the runtime holds or admits",
    ),
    RoleRequirement(
        role="IE3",
        job="intent graph synthesis, once, on the settled IE2 state",
        transport="Model Runtime, task INTENT_GRAPH_SYNTHESIS, runtime-v4 graph adapter",
        identity_contract={
            "provider": lh.IE3_PROVIDER,
            "model": lh.IE3_MODEL,
            "policy_id": lh.IE3_POLICY_ID,
            "policy_version": lh.IE3_POLICY_VERSION,
            "prompt_sha256": lh.IE3_PROMPT_SHA256,
            "canonical_schema_sha256": lh.IE3_CANONICAL_SCHEMA_SHA256,
            "wire_schema_sha256": lh.IE3_WIRE_SCHEMA_SHA256,
            "wire_schema_compiler": lh.IE3_WIRE_SCHEMA_COMPILER,
            "certificate": lh.IE3_CERTIFICATE_PATH,
            "certificate_sha256": lh.IE3_CERTIFICATE_SHA256,
        },
        independence="none required by runtime law",
        authority="graph proposals; IE3 admission decides",
    ),
    RoleRequirement(
        role="ADJUDICATOR",
        job="map the final IE2/IE3 state onto the hidden final-truth oracle, once, after the run",
        transport="Model Runtime, task EVALUATION (not contract-bound)",
        identity_contract={
            "policy_id": protocol.ADJUDICATOR_POLICY_ID,
            "policy_version": protocol.ADJUDICATOR_POLICY_VERSION,
            "output_schema": "OutcomeAdjudicationAnswer",
        },
        independence="a model other than the writer, the verifier and the IE3 model",
        authority="none: experiment evaluation only; never written to any ledger",
    ),
)

IE3_IDENTITY: Final = (lh.IE3_PROVIDER, lh.IE3_MODEL)

Status = Literal["CERTIFIED", "ELIGIBLE_UNVALIDATED", "BLOCKED_NO_CERTIFICATION", "INELIGIBLE"]


class Candidate(FrozenModel):
    role: Role
    provider: str
    model: str
    status: Status
    basis: str


CANDIDATES: Final[tuple[Candidate, ...]] = (
    Candidate(role="WRITER", provider="xai", model="grok-4.6", status="ELIGIBLE_UNVALIDATED",
              basis="the only IE2 writer in Foundry's history (validations v1-v6; v5 VALIDATED "
              "at 20b4005, v6 NOT_VALIDATED); policy v7 ran live once, in live e2e v1 (FAIL, "
              "for the harness routing defect and the replacement hole this lineage fixes); "
              "Call-2 policies have no registry certification; XAI_API_KEY configured"),
    Candidate(role="WRITER", provider="xai", model="grok-4.7", status="ELIGIBLE_UNVALIDATED",
              basis="reachable through the same adapter; no IE2 history at all"),
    Candidate(role="WRITER", provider="openai", model="gpt-6-astra", status="INELIGIBLE",
              basis="no Call-2 writer adapter exists for this provider"),
    Candidate(role="WRITER", provider="anthropic", model="(any)", status="INELIGIBLE",
              basis="no Call-2 writer adapter exists for this provider"),
    Candidate(role="VERIFIER", provider="openai", model="gpt-6-astra",
              status="BLOCKED_NO_CERTIFICATION",
              basis="AdmissionReportV5 compiles to the OpenAI wire; no certificate binds "
              "ADMISSION_V5_CONTRACT; served the v4 contract in live e2e v1 by experiment-scoped "
              "authorization (41/41 COMPLETE + NO_CONFLICT); NOT CERTIFIED on completeness "
              "exams v2-v5 and structured v1 (earlier contracts)"),
    Candidate(role="VERIFIER", provider="anthropic", model="claude-opus-5-5",
              status="BLOCKED_NO_CERTIFICATION",
              basis="AdmissionReportV5 compiles to the Anthropic wire; no completeness or "
              "admission certification of any version"),
    Candidate(role="VERIFIER", provider="anthropic", model="claude-fable-5-1",
              status="BLOCKED_NO_CERTIFICATION",
              basis="as claude-opus-5-5"),
    Candidate(role="VERIFIER", provider="anthropic", model="claude-sonnet-5",
              status="BLOCKED_NO_CERTIFICATION",
              basis="as claude-opus-5-5"),
    Candidate(role="IE3", provider="openai", model="gpt-6-astra", status="CERTIFIED",
              basis="intent_graph_synthesis_exam_v6 PASS (runtime-v4): the current graph "
              "certificate"),
    Candidate(role="ADJUDICATOR", provider="anthropic", model="claude-opus-5-5",
              status="BLOCKED_NO_CERTIFICATION",
              basis="EVALUATION has no certification exam; usable only by an explicit "
              "experiment-scoped founder binding; must differ from writer, verifier, IE3; "
              "adjudicated live e2e v1 completely and certainly"),
    Candidate(role="ADJUDICATOR", provider="anthropic", model="claude-fable-5-1",
              status="BLOCKED_NO_CERTIFICATION", basis="as claude-opus-5-5"),
    Candidate(role="ADJUDICATOR", provider="anthropic", model="claude-sonnet-5",
              status="BLOCKED_NO_CERTIFICATION", basis="as claude-opus-5-5"),
    Candidate(role="ADJUDICATOR", provider="xai", model="grok-4.7",
              status="BLOCKED_NO_CERTIFICATION",
              basis="as claude-opus-5-5; same provider as the writer (allowed by the model-level "
              "law, weaker separation)"),
)  # fmt: skip


class BoundModel(FrozenModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class RoleBinding(FrozenModel):
    """The founder's binding, written after the seal. Each uncertified use is authorized in
    words the founder signs; nothing here is inferred."""

    decided_by: str = Field(min_length=1)
    writer: BoundModel
    writer_reasoning_effort: Literal["low", "high"]
    verifier: BoundModel
    verifier_authorization: str = Field(min_length=1)
    """The founder's experiment-scoped authorization to serve ADMISSION_V5_CONTRACT without a
    certificate (no model holds one)."""
    adjudicator: BoundModel
    adjudicator_authorization: str = Field(min_length=1)


def _same(a: BoundModel, provider: str, model: str) -> bool:
    return a.provider == provider and a.model == model


def binding_findings(binding: RoleBinding) -> tuple[str, ...]:
    """Every way the binding breaks a sealed role requirement. Empty means it may run."""
    out: list[str] = []
    eligible = {(c.role, c.provider, c.model) for c in CANDIDATES if c.status != "INELIGIBLE"}
    for role, bound in (
        ("WRITER", binding.writer),
        ("VERIFIER", binding.verifier),
        ("ADJUDICATOR", binding.adjudicator),
    ):
        if (role, bound.provider, bound.model) not in eligible:
            out.append(f"NOT_A_SEALED_CANDIDATE: {role} {bound.provider}/{bound.model}")
    w, v, a = binding.writer, binding.verifier, binding.adjudicator
    if _same(v, w.provider, w.model):
        out.append("VERIFIER_NOT_INDEPENDENT_OF_WRITER")
    for label, other in (("WRITER", w), ("VERIFIER", v)):
        if _same(a, other.provider, other.model):
            out.append(f"ADJUDICATOR_IS_THE_{label}")
    if _same(a, *IE3_IDENTITY):
        out.append("ADJUDICATOR_IS_THE_IE3_MODEL")
    if binding.decided_by != protocol.FOUNDER:
        out.append(f"NOT_DECIDED_BY_THE_FOUNDER: {binding.decided_by}")
    return tuple(out)
