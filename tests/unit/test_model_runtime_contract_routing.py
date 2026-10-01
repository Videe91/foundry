"""Contract-bound certification routing (offline).

Before: a model was eligible for a request when its descriptor listed the request's TASK (plus
tier and capabilities). The request's policy id / version were labels the runtime recorded and
never interpreted, and certificates never took part in routing. So a model certified for the
free-text completeness verifier (policy v1) would have been routed requests of the structured
verifier (policy v2), and the reverse.

Now: a task listed in ``CONTRACT_BOUND_TASKS`` must name its exact output contract
(``ModelContract``: policy id and version, instruction digest, canonical output-schema digest),
and a model may serve it only if its descriptor certifies exactly that contract for that task
(``CertifiedContract``). When the certification binds a provider wire schema and compiler, the
routed adapter must produce exactly that wire schema before any call is made. Anything else is
NOT CERTIFIED FOR THIS REQUEST: no relaxation, no substitution. Tasks that are not contract-bound
route exactly as before.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from foundry.model_runtime.domain import (
    CONTRACT_BOUND_TASKS,
    CertifiedContract,
    MessageRole,
    ModelCapability,
    ModelContract,
    ModelDescriptor,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
    ModelUsage,
    output_schema_sha256,
)
from foundry.model_runtime.errors import ModelRequestError, ModelUnavailableError
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.model_runtime.registry import build_registry
from foundry.model_runtime.runtime import ModelRuntime
from tests.certification._schema_identity import schema_sha256

SCV = ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION
MODEL = ModelIdentity(provider="provider-v", model="verifier-model")


class Answer(BaseModel):
    ok: bool


class OtherAnswer(BaseModel):
    ok: bool
    note: str


def _contract(
    version: str = "policy-v2", instruction: str = "I2", output: type = Answer
) -> ModelContract:
    return ModelContract(
        policy_id="completeness",
        policy_version=version,
        instruction_sha256=hashlib.sha256(instruction.encode()).hexdigest(),
        output_schema_sha256=output_schema_sha256(output),
    )


V2 = _contract()
V1 = _contract(version="policy-v1", instruction="I1")


def _request(contract: ModelContract | None = V2, task: ModelTask = SCV) -> ModelRequest:
    return ModelRequest(
        task=task,
        tier=ModelTier.REASONER,
        messages=(ModelMessage(role=MessageRole.USER, content="x"),),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id=contract.policy_id if contract else "graph",
        policy_version=contract.policy_version if contract else "graph-v6",
        contract=contract,
        trace=ModelTraceContext(run_id="R", call_id="C"),
    )


def _descriptor(
    *certified: CertifiedContract, tasks: frozenset[ModelTask] = frozenset({SCV})
) -> ModelDescriptor:
    return ModelDescriptor(
        identity=MODEL,
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
        ),
        certified_tasks=tasks,
        certified_contracts=frozenset(certified),
    )


def _eligible(
    request: ModelRequest,
    *certified: CertifiedContract,
    tasks: frozenset[ModelTask] = frozenset({SCV}),
) -> bool:
    return bool(build_registry((_descriptor(*certified, tasks=tasks),)).eligible_models(request))


# --- the vocabulary ---------------------------------------------------------------------------


def test_only_semantic_completeness_is_contract_bound_today() -> None:
    assert frozenset({SCV}) == CONTRACT_BOUND_TASKS


def test_the_output_schema_digest_is_the_canonical_certification_digest() -> None:
    assert output_schema_sha256(Answer) == schema_sha256(Answer.model_json_schema())


def test_a_contract_bound_request_must_name_its_contract_and_agree_with_its_policy_label() -> None:
    with pytest.raises(ValidationError, match="contract"):
        _request(contract=None)
    with pytest.raises(ValidationError, match="policy"):
        ModelRequest(
            task=SCV, tier=ModelTier.REASONER,
            messages=(ModelMessage(role=MessageRole.USER, content="x"),),
            policy_id="completeness", policy_version="policy-v1", contract=V2,
            trace=ModelTraceContext(run_id="R", call_id="C"),
        )  # fmt: skip


# --- routing --------------------------------------------------------------------------------------


def test_a_model_certified_for_exactly_this_contract_is_eligible() -> None:
    assert _eligible(_request(V2), CertifiedContract(task=SCV, contract=V2))


@pytest.mark.parametrize(
    ("certified", "why"),
    [
        (CertifiedContract(task=SCV, contract=_contract(version="policy-v3")), "policy version"),
        (CertifiedContract(task=SCV, contract=_contract(instruction="I2-edited")), "instruction"),
        (CertifiedContract(task=SCV, contract=_contract(output=OtherAnswer)), "canonical schema"),
        (
            CertifiedContract(task=SCV, contract=V2.model_copy(update={"policy_id": "x"})),
            "policy id",
        ),
        (CertifiedContract(task=ModelTask.ARCHITECTURE, contract=V2), "unrelated task"),
        (CertifiedContract(task=SCV, contract=V1), "the v1 contract presented for v2"),
    ],
)
def test_any_single_mismatch_is_not_certified_for_this_request(
    certified: CertifiedContract, why: str
) -> None:
    assert not _eligible(_request(V2), certified), why


def test_a_task_only_certification_never_serves_a_contract_bound_request() -> None:
    assert not _eligible(_request(V2))  # certified for the task, bound to no contract


def test_a_v2_certificate_never_serves_v1_and_a_v1_certificate_never_serves_v2() -> None:
    v1_only, v2_only = (
        CertifiedContract(task=SCV, contract=V1),
        CertifiedContract(task=SCV, contract=V2),
    )
    assert _eligible(_request(V1), v1_only) and not _eligible(_request(V2), v1_only)
    assert _eligible(_request(V2), v2_only) and not _eligible(_request(V1), v2_only)
    assert _eligible(_request(V1), v1_only, v2_only) and _eligible(_request(V2), v1_only, v2_only)


def test_a_certification_for_another_task_never_lends_the_task() -> None:
    graph_only = frozenset({ModelTask.ARCHITECTURE})
    assert not _eligible(_request(V2), CertifiedContract(task=SCV, contract=V2), tasks=graph_only)


def test_tasks_that_are_not_contract_bound_route_exactly_as_before() -> None:
    graph = frozenset({ModelTask.ARCHITECTURE})
    assert _eligible(_request(None, ModelTask.ARCHITECTURE), tasks=graph)
    assert not _eligible(_request(None, ModelTask.ARCHITECTURE))


def test_absence_of_a_matching_certificate_fails_closed_at_execution() -> None:
    provider = FakeModelProvider(provider_id="provider-v")
    runtime = ModelRuntime(
        registry=build_registry((_descriptor(CertifiedContract(task=SCV, contract=V1)),)),
        providers=(provider,),
    )
    with pytest.raises(ModelUnavailableError):
        runtime.execute(_request(V2), output_type=Answer)
    assert provider.calls == 0


# --- the runtime checks the declared contract against what is actually executed ----------------


def _answering(provider_id: str = "provider-v") -> FakeModelProvider:
    return FakeModelProvider(
        provider_id=provider_id,
        responses=(ScriptedResponse(output={"ok": True}, model="verifier-model",
                                    usage=ModelUsage(input_tokens=1, output_tokens=1)),),
    )  # fmt: skip


def test_a_request_whose_output_type_is_not_its_declared_contract_is_refused() -> None:
    provider = _answering()
    runtime = ModelRuntime(
        registry=build_registry((_descriptor(CertifiedContract(task=SCV, contract=V2)),)),
        providers=(provider,),
    )
    with pytest.raises(ModelRequestError, match="output schema"):
        runtime.execute(_request(V2), output_type=OtherAnswer)
    assert provider.calls == 0
    assert runtime.execute(_request(V2), output_type=Answer).output == Answer(ok=True)


class WireProvider(FakeModelProvider):
    """A fake adapter that states its wire schema, as every real adapter does."""

    WIRE_SCHEMA_COMPILER = "compiler-a"

    @staticmethod
    def wire_schema(output_type: type[BaseModel]) -> dict[str, Any]:
        return {"wire": output_type.model_json_schema()}

    def execute[T: BaseModel](self, **kwargs: Any) -> ProviderExecutionResult[T]:
        return super().execute(**kwargs)


def _wired(wire: str | None, compiler: str | None) -> tuple[ModelRuntime, WireProvider]:
    provider = WireProvider(
        provider_id="provider-v",
        responses=(ScriptedResponse(output={"ok": True}, model="verifier-model",
                                    usage=ModelUsage(input_tokens=1, output_tokens=1)),),
    )  # fmt: skip
    certified = CertifiedContract(
        task=SCV, contract=V2, wire_schema_sha256=wire, wire_schema_compiler=compiler
    )
    return ModelRuntime(
        registry=build_registry((_descriptor(certified),)), providers=(provider,)
    ), provider


def test_a_certified_wire_schema_and_compiler_must_be_what_the_adapter_sends() -> None:
    right = schema_sha256(WireProvider.wire_schema(Answer))
    runtime, provider = _wired(right, "compiler-a")
    assert runtime.execute(_request(V2), output_type=Answer).output == Answer(ok=True)
    for wire, compiler in ((right, "compiler-b"), ("0" * 64, "compiler-a")):
        runtime, provider = _wired(wire, compiler)
        with pytest.raises(ModelUnavailableError, match="wire"):
            runtime.execute(_request(V2), output_type=Answer)
        assert provider.calls == 0


def test_an_adapter_that_cannot_state_its_wire_schema_cannot_serve_a_wire_bound_contract() -> None:
    provider = _answering()
    certified = CertifiedContract(
        task=SCV, contract=V2, wire_schema_sha256="0" * 64, wire_schema_compiler="compiler-a"
    )
    runtime = ModelRuntime(
        registry=build_registry((_descriptor(certified),)), providers=(provider,)
    )
    with pytest.raises(ModelUnavailableError, match="wire"):
        runtime.execute(_request(V2), output_type=Answer)
    assert provider.calls == 0


def test_a_wire_binding_needs_both_its_schema_and_its_compiler() -> None:
    with pytest.raises(ValidationError):
        CertifiedContract(task=SCV, contract=V2, wire_schema_sha256="0" * 64)
    with pytest.raises(ValidationError):
        CertifiedContract(task=SCV, contract=V2, wire_schema_compiler="compiler-a")
