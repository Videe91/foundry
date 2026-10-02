"""Live wiring: the four roles as the founder's binding names them. Built, never called offline.

``live_ports`` turns a lawful ``RoleBinding`` and the three provider keys into the writer,
verifier, IE3 synthesizer and adjudicator. Two registries are experiment-scoped and exist only
because the founder authorizes them in the binding: the verifier's (no model holds a
certificate for ``ADMISSION_V4_CONTRACT``) and the adjudicator's (``EVALUATION`` has no
certification). IE3's registry is derived from its certificate, exactly as the long-horizon
experiment derives it. ``main`` refuses to start unless every preflight gate passes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    ADMISSION_V4_CONTRACT,
    ModelRuntimeAdmissionVerifier,
)
from foundry.adapters.semantics.xai_reasoner import XAIConflictSemanticReasoner
from foundry.experiments.intent_engine_live_v1 import protocol
from foundry.experiments.intent_engine_live_v1.adjudicator import ModelRuntimeOutcomeAdjudicator
from foundry.experiments.intent_engine_live_v1.roles import (
    BoundModel,
    RoleBinding,
    binding_findings,
)
from foundry.experiments.long_horizon_ie2_ie3 import ie3_runtime
from foundry.experiments.long_horizon_ie2_ie3 import protocol as lh
from foundry.experiments.long_horizon_ie2_ie3.recording import RunBudget
from foundry.model_runtime.domain import (
    CertifiedContract,
    ModelCapability,
    ModelDescriptor,
    ModelIdentity,
    ModelTask,
    ModelTier,
)
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime

__all__ = ["KEY_NAMES", "adjudicator_registry", "live_ports", "main", "verifier_registry"]

KEY_NAMES = ("XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
_CAPABILITIES = frozenset({ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT})


def _descriptor(bound: BoundModel, **certified: Any) -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity(provider=bound.provider, model=bound.model),
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=_CAPABILITIES,
        **certified,
    )


def verifier_registry(binding: RoleBinding) -> ModelRegistry:
    """Experiment-scoped, by the founder's ``verifier_authorization``: the bound verifier may
    serve exactly ``ADMISSION_V4_CONTRACT`` and nothing else."""
    task = ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION
    return ModelRegistry(
        descriptors=(
            _descriptor(
                binding.verifier,
                certified_tasks=frozenset({task}),
                certified_contracts=frozenset(
                    {CertifiedContract(task=task, contract=ADMISSION_V4_CONTRACT)}
                ),
            ),
        )
    )


def adjudicator_registry(binding: RoleBinding) -> ModelRegistry:
    """Experiment-scoped, by the founder's ``adjudicator_authorization``: EVALUATION only."""
    return ModelRegistry(
        descriptors=(
            _descriptor(binding.adjudicator, certified_tasks=frozenset({ModelTask.EVALUATION})),
        )
    )


def _provider(bound: BoundModel, keys: dict[str, str]) -> Any:
    if bound.provider == "openai":
        return OpenAIModelProvider(api_key=keys["OPENAI_API_KEY"], reasoning_effort="high")
    if bound.provider == "anthropic":
        return AnthropicModelProvider(api_key=keys["ANTHROPIC_API_KEY"], effort="high")
    raise ValueError(f"no Model Runtime provider is wired for {bound.provider}")


def live_ports(binding: RoleBinding, keys: dict[str, str]) -> tuple[Any, Any, Any, Any]:
    findings = binding_findings(binding)
    if findings:
        raise ValueError(f"the role binding breaks the sealed requirements: {findings}")
    writer = XAIConflictSemanticReasoner(
        api_key=keys["XAI_API_KEY"],
        model=binding.writer.model,
        reasoning_effort=binding.writer_reasoning_effort,
    )
    verifier = ModelRuntimeAdmissionVerifier(
        runtime=ModelRuntime(
            registry=verifier_registry(binding),
            providers=(_provider(binding.verifier, keys),),
        ),
        run_id=f"{protocol.EXPERIMENT_VERSION}-verifier",
    )
    certificate = json.loads(Path(lh.IE3_CERTIFICATE_PATH).read_text())
    synthesizer, _ = ie3_runtime.build_synthesizer(
        ie3_runtime.live_provider(keys["OPENAI_API_KEY"]),
        RunBudget(),
        ie3_runtime.registry_from_certificate(certificate),
    )
    adjudicator = ModelRuntimeOutcomeAdjudicator(
        runtime=ModelRuntime(
            registry=adjudicator_registry(binding),
            providers=(_provider(binding.adjudicator, keys),),
        ),
        run_id=f"{protocol.EXPERIMENT_VERSION}-adjudicator",
    )
    return writer, verifier, synthesizer, adjudicator


def main() -> int:  # pragma: no cover - the live entry point; never run offline
    from datetime import UTC, datetime
    from itertools import count

    from foundry.experiments.intent_engine_live_v1.runner import run_live
    from foundry.experiments.intent_engine_live_v1.seal import (
        load_oracle,
        preflight_gates,
        write_raw,
    )

    gates = preflight_gates()
    failed = {name: reason for name, (ok, reason) in gates.items() if not ok}
    if failed:
        print(json.dumps({"refused": failed}, indent=2))
        return 2
    binding = RoleBinding.model_validate_json(
        (Path(protocol.EXPERIMENT_ARTIFACT_DIR) / protocol.ROLE_BINDING_FILE).read_text()
    )
    keys = {name: os.environ[name] for name in KEY_NAMES}
    writer, verifier, synthesizer, adjudicator = live_ports(binding, keys)
    ids = count(1)
    record = run_live(
        writer=writer,
        verifier=verifier,
        ie3_synthesizer=synthesizer,
        adjudicator=adjudicator,
        oracle=load_oracle,
        clock=lambda: datetime.now(UTC),
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )
    write_raw(record)
    print(record.report.verdict)
    return 0
