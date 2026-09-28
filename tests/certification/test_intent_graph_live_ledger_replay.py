"""Replay, containment and certificate binding for model-authored IE3 graph ledgers.

Offline, always. Discovers every ledger under
``tests/certification/evidence/<provider>/<model>/intent_graph_synthesis/`` and derives the
expected author from the path, so a new contestant is enrolled by existing. Every provider is
bombed, the graph adapter included, because provider-free replay is a Foundry invariant rather
than a property of one vendor.

It also binds the recorded certification to the contestant it names. A record certifies one
provider, model, task, policy and prompt digest together, so an edited prompt, a different
model or a new policy version is never silently covered by an old record.
"""

from __future__ import annotations

import json
import pathlib
import pkgutil
from importlib import import_module
from typing import Any

import pytest

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    GRAPH_SYNTHESIS_POLICY_ID,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.xai import XAIModelProvider
from foundry.application.replay import replay
from foundry.domain.common import Authority
from foundry.domain.events import EventType, StoredEvent, parse_event
from foundry.domain.intent_synthesis import IntentSynthesisRoute
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._intent_graph_exam import (
    GRAPH_CERTIFICATION_RECORD_FORMAT,
    GRAPH_EXAM_ID,
    GRAPH_EXAM_VERSION,
    SCHEMA_BOUND_RECORD_FORMAT,
    certificate_binds,
    graph_exam_sha256,
    historical_certificate_binds,
    record_format,
    schema_bound_certificate_binds,
)
from tests.certification._intent_synthesis_exam import PROJECT
from tests.certification._schema_identity import schema_sha256

_NAMESPACES = "intent_graph_synthesis*"
"""Every graph evidence namespace: the immutable runtime-v1 record and each later one."""


def _recorded_policy_version(ledger: pathlib.Path) -> str:
    """The policy the ledger was produced under, from its own record, never today's constant."""
    return str(json.loads((ledger.parent / "certification.json").read_text())["policy_version"])


def _discovered() -> list[tuple[ModelIdentity, pathlib.Path]]:
    found: list[tuple[ModelIdentity, pathlib.Path]] = []
    if not EVIDENCE_ROOT.exists():
        return found
    for ledger in sorted(EVIDENCE_ROOT.glob(f"*/*/{_NAMESPACES}/case_*_ledger.json")):
        model_dir = ledger.parent.parent
        found.append((ModelIdentity(provider=model_dir.parent.name, model=model_dir.name), ledger))
    return found


LEDGERS = _discovered()
CERTIFICATES = sorted(EVIDENCE_ROOT.glob(f"*/*/{_NAMESPACES}/certification.json"))

pytestmark = pytest.mark.skipif(
    not LEDGERS, reason="LIVE_GRAPH_LEDGER_NOT_CAPTURED: run the live graph exam first"
)

CASES = [
    pytest.param(identity, path, id=f"{identity.provider}/{identity.model}/{path.stem}")
    for identity, path in LEDGERS
]


@pytest.fixture(autouse=True)
def provider_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any model access during reconstruction fails the test, for every provider."""

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("replay must never reach a model or provider")

    import foundry.adapters.intent_graph_synthesis.model_runtime as graph_adapter
    import foundry.adapters.intent_synthesis.model_runtime as intent_adapter
    import foundry.adapters.model_runtime as adapters
    import foundry.model_runtime.runtime as runtime_module

    monkeypatch.setattr(runtime_module.ModelRuntime, "execute", boom)
    monkeypatch.setattr(intent_adapter.ModelRuntimeIntentSynthesizer, "synthesize", boom)
    monkeypatch.setattr(graph_adapter.ModelRuntimeIntentGraphSynthesizer, "synthesize", boom)
    bombed: list[str] = []
    for info in pkgutil.iter_modules(adapters.__path__):
        module = import_module(f"{adapters.__name__}.{info.name}")
        for attribute in vars(module).values():
            if (
                isinstance(attribute, type)
                and hasattr(attribute, "provider_id")
                and getattr(attribute, "execute", None) is not None
            ):
                monkeypatch.setattr(attribute, "execute", boom, raising=False)
                bombed.append(f"{info.name}.{attribute.__name__}")
        for client_symbol in ("Client", "OpenAI", "Anthropic"):
            if hasattr(module, client_symbol):
                monkeypatch.setattr(module, client_symbol, boom, raising=False)
                bombed.append(f"{info.name}.{client_symbol}")
    assert bombed, "no provider adapter was bombed; the containment proof would be vacuous"


def _events(ledger: pathlib.Path) -> tuple[StoredEvent, ...]:
    return tuple(
        StoredEvent(sequence=entry["sequence"], event=parse_event(entry["event"]))
        for entry in json.loads(ledger.read_text())
    )


def _canonical(value: Any) -> str:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def test_the_bomb_would_fire() -> None:
    import foundry.model_runtime.runtime as runtime_module

    with pytest.raises(AssertionError, match="never reach a model"):
        runtime_module.ModelRuntime.execute(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_the_graph_ledger_replays_identically_three_ways(
    identity: ModelIdentity, ledger: pathlib.Path
) -> None:
    events = _events(ledger)
    direct = replay(PROJECT, events)
    reparsed = replay(
        PROJECT,
        tuple(
            StoredEvent(
                sequence=s.sequence,
                event=parse_event(json.loads(json.dumps(s.event.model_dump(mode="json")))),
            )
            for s in events
        ),
    )
    assert _canonical(direct) == _canonical(reparsed) == _canonical(replay(PROJECT, events))


def _graph_record(ledger: pathlib.Path) -> Any:
    state = replay(PROJECT, _events(ledger))
    decisions = list(state.intent_graph_synthesis.decisions.values())
    return state, decisions


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_the_model_authored_graph_decision_survives_replay_truthfully(
    identity: ModelIdentity, ledger: pathlib.Path
) -> None:
    state, decisions = _graph_record(ledger)
    if not decisions:
        # A refused attempt left no decision; that is evidence, and its absence is exact.
        types = {e.event.event_type for e in _events(ledger)}
        assert EventType.INTENT_GRAPH_SYNTHESIS_DECIDED not in types
        return
    (record,) = decisions
    assert record.author.provider == identity.provider
    assert record.author.model == identity.model
    assert record.author.policy_version == _recorded_policy_version(ledger)
    if record.compiled is not None:
        for obj in record.compiled.objects:
            assert state.objects[obj.id] == obj


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_task_certification_grants_compute_not_authority(
    identity: ModelIdentity, ledger: pathlib.Path
) -> None:
    state, decisions = _graph_record(ledger)
    for record in decisions:
        for assignment in record.node_assignments:
            assert assignment.authority is not Authority.CANONICAL
        if record.compiled is not None:
            assert all(o.authority is Authority.PROPOSED for o in record.compiled.objects)


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_a_no_change_decision_has_no_effect(identity: ModelIdentity, ledger: pathlib.Path) -> None:
    events = _events(ledger)
    state, decisions = _graph_record(ledger)
    for record in decisions:
        if record.decision.route is not IntentSynthesisRoute.NO_CHANGE:
            continue
        assert record.compiled is None
        assert record.result.unchanged_object_refs
        before = replay(PROJECT, events[:-1])
        assert _canonical(before.objects) == _canonical(state.objects)
        assert _canonical(before.semantic.derivations) == _canonical(state.semantic.derivations)
        assert _canonical(before.gaps) == _canonical(state.gaps)


PROVIDERS: dict[str, Any] = {
    "xai": XAIModelProvider,
    "openai": OpenAIModelProvider,
    "anthropic": AnthropicModelProvider,
}
SCHEMA_FIELDS = ("canonical_schema_sha256", "wire_schema_sha256", "wire_schema_compiler")
EXAM_FIELDS = ("exam_id", "exam_version", "exam_sha256")


def _current_identity(identity: ModelIdentity) -> dict[str, Any]:
    provider = PROVIDERS[identity.provider]
    return {
        "identity": identity,
        "task": ModelTask.INTENT_GRAPH_SYNTHESIS,
        "policy_id": GRAPH_SYNTHESIS_POLICY_ID,
        "policy_version": GRAPH_SYNTHESIS_POLICY_VERSION,
        "prompt_sha256": GRAPH_SYSTEM_INSTRUCTION_SHA256,
        "canonical_schema_sha256": GRAPH_ANSWER_SCHEMA_SHA256,
        "wire_schema_sha256": schema_sha256(provider.wire_schema(IntentGraphDraftPayload)),
        "wire_schema_compiler": provider.WIRE_SCHEMA_COMPILER,
        "exam_id": GRAPH_EXAM_ID,
        "exam_version": GRAPH_EXAM_VERSION,
        "exam_sha256": graph_exam_sha256(),
    }


@pytest.mark.parametrize(
    "path", CERTIFICATES, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}"
)
def test_the_recorded_certification_binds_exactly_its_contestant(path: pathlib.Path) -> None:
    """Each record is read in the format it was written in, and binds only what it examined."""
    record = json.loads(path.read_text())
    model_dir = path.parent.parent
    identity = ModelIdentity(provider=model_dir.parent.name, model=model_dir.name)
    assert (record["provider"], record["model"]) == (identity.provider, identity.model)
    assert record["task"] == ModelTask.INTENT_GRAPH_SYNTHESIS.value
    assert record["verdict"] in {"PASS", "NOT CERTIFIED"}
    assert record["recorded_attempts"] == record["required_attempts"] or record["verdict"] != "PASS"
    passed = record["verdict"] == "PASS"
    current = _current_identity(identity)
    own = {
        "identity": identity,
        "task": ModelTask.INTENT_GRAPH_SYNTHESIS,
        "policy_id": record["policy_id"],
        "policy_version": record["policy_version"],
        "prompt_sha256": record["prompt_sha256"],
    }

    if record_format(record) == GRAPH_CERTIFICATION_RECORD_FORMAT:
        own.update({field: record[field] for field in (*SCHEMA_FIELDS, *EXAM_FIELDS)})
        is_current = all(record.get(key) == current[key] for key in own if key != "identity")
        assert certificate_binds(record, **own) is passed
        assert certificate_binds(record, **current) is (passed and is_current)
    elif record_format(record) == SCHEMA_BOUND_RECORD_FORMAT:
        # Historical v2: schema-bound, written before exam binding. It records no exam identity,
        # none is fabricated into it, and it can never bind an exam-bound identity.
        assert not set(EXAM_FIELDS) & record.keys()
        own.update({field: record[field] for field in SCHEMA_FIELDS})
        assert schema_bound_certificate_binds(record, **own) is passed
        assert not certificate_binds(record, **current)
    else:
        # Historical v1: written before schema binding. It records no schema identity, none is
        # fabricated into it, and it can never bind a schema-bound identity.
        assert not set((*SCHEMA_FIELDS, *EXAM_FIELDS)) & record.keys()
        assert historical_certificate_binds(record, **own) is passed
        assert not certificate_binds(record, **current)

    for changed in (
        {"prompt_sha256": "0" * 64},
        {"policy_version": "intent-graph-synthesis-runtime-v4"},
        {"canonical_schema_sha256": "0" * 64},
        {"wire_schema_sha256": "0" * 64},
        {"wire_schema_compiler": "another-compiler"},
        {"exam_sha256": "0" * 64},
        {"exam_version": "1"},
        {"exam_id": "another-exam"},
    ):
        assert not certificate_binds(record, **{**current, **changed})
    other_model = ModelIdentity(provider=identity.provider, model=identity.model + "-other")
    assert not certificate_binds(record, **{**current, "identity": other_model})
