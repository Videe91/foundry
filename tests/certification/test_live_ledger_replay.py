"""MR4 §21/§22 — replay and containment for a genuinely model-authored ledger.

Runs offline, always. It reads the event stream preserved from a passing live Case A run
and proves the T12 replay law holds for a ledger whose proposal really came from Grok —
and that task certification granted the model permission to *compute*, never authority.

A provider bomb is installed: any attempt to construct a model provider or call a
synthesizer during reconstruction fails the test. Replay reads the decision; it never
recreates it.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from foundry.application.handoff_v2 import (
    IntentDeliveryNotReadyError,
    build_intent_decision_handoff_v2,
)
from foundry.application.package import build_intent_package
from foundry.application.replay import replay
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, Materiality
from foundry.domain.events import StoredEvent, parse_event
from foundry.domain.semantic import Requirement
from tests.certification._intent_synthesis_exam import (
    CANDIDATE,
    EXPECTED_POLICY_VERSION,
    PROJECT,
    SCOPE,
)

LEDGER = pathlib.Path("tests/certification/_live_case_a_ledger.json")

pytestmark = pytest.mark.skipif(
    not LEDGER.exists(),
    reason="LIVE_LEDGER_NOT_CAPTURED: run the live certification exam first",
)


@pytest.fixture(autouse=True)
def provider_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any model construction or call during reconstruction fails the test."""

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("replay must never reach a model or provider")

    import foundry.adapters.intent_synthesis.model_runtime as intent_adapter
    import foundry.adapters.model_runtime.xai as xai_adapter

    monkeypatch.setattr(xai_adapter, "Client", boom)
    monkeypatch.setattr(xai_adapter.XAIModelProvider, "execute", boom)
    monkeypatch.setattr(intent_adapter.ModelRuntimeIntentSynthesizer, "synthesize", boom)


def _events() -> tuple[StoredEvent, ...]:
    raw = json.loads(LEDGER.read_text())
    return tuple(
        StoredEvent(sequence=entry["sequence"], event=parse_event(entry["event"])) for entry in raw
    )


def _canonical(value: object) -> str:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def test_the_live_authored_ledger_replays_identically_three_ways() -> None:
    events = _events()
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
    again = replay(PROJECT, events)

    assert _canonical(direct) == _canonical(reparsed) == _canonical(again)
    assert _canonical(direct.intent_synthesis) == _canonical(reparsed.intent_synthesis)
    assert _canonical(direct.objects) == _canonical(reparsed.objects)
    assert _canonical(direct.semantic.derivations) == _canonical(reparsed.semantic.derivations)


def test_the_model_authored_decision_survives_replay_exactly() -> None:
    state = replay(PROJECT, _events())
    assert state.intent_synthesis.decisions, "the preserved ledger holds no decision"
    record = next(iter(state.intent_synthesis.decisions.values()))

    # The author is the live model, recorded truthfully and reconstructed from the log.
    assert record.author.provider == CANDIDATE.provider
    assert record.author.model == CANDIDATE.model
    assert record.author.policy_version == EXPECTED_POLICY_VERSION

    requirement = state.objects[record.identity.object_id("REQ")]
    assert isinstance(requirement, Requirement)
    assert requirement.created_at == record.decided_at
    assert requirement.confidence == record.proposal.confidence
    assert requirement.statement == record.proposal.statement


def test_task_certification_grants_compute_not_authority() -> None:
    """§22: the Requirement stays PROPOSED. Certifying the model changes nothing here."""
    state = replay(PROJECT, _events())
    record = next(iter(state.intent_synthesis.decisions.values()))
    requirement = state.objects[record.identity.object_id("REQ")]

    assert requirement.authority is Authority.PROPOSED
    assert requirement.authority is not Authority.CANONICAL
    assert requirement.materiality is Materiality.LOW


def test_a_proposed_low_requirement_keeps_its_existing_downstream_behaviour() -> None:
    """Closure and the package behave exactly as they do for any PROPOSED LOW Requirement."""
    state = replay(PROJECT, _events())
    record = next(iter(state.intent_synthesis.decisions.values()))
    requirement_id = record.identity.object_id("REQ")

    closure = evaluate_closure(state, SCOPE)
    # LOW + PROPOSED is non-blocking, so the scope's closure is unchanged by its presence.
    assert "NON_CANONICAL_REQUIREMENT" not in {b.code for b in closure.blockers}

    if closure.closed:
        package = build_intent_package(state, SCOPE)
        assert requirement_id not in package.obligation_ids, (
            "a model-authored PROPOSED Requirement must never enter the contract"
        )
        handoff = build_intent_decision_handoff_v2(state, SCOPE)
        assert requirement_id in handoff.proposed_intent_object_ids
        assert requirement_id not in handoff.canonical_intent_object_ids
    else:
        with pytest.raises(IntentDeliveryNotReadyError):
            build_intent_decision_handoff_v2(state, SCOPE)
