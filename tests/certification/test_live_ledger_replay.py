"""Replay and containment for genuinely model-authored ledgers — every contestant.

Runs offline, always. It reads the event stream preserved from each contestant's passing
live Case A run and proves the T12 replay law holds for a ledger whose proposal really came
from that model — and that task certification granted the model permission to *compute*,
never authority.

**Contestant-neutral by construction.** The suite discovers every ledger under
``tests/certification/evidence/<provider>/<model>/`` and derives the expected author from
the path, so a new contestant is enrolled in these proofs by existing, not by editing this
file. A provider whose ledger was never captured simply contributes no cases.

**Every provider is bombed, not just the one that authored the ledger.** Provider-free
replay is a Foundry invariant, so the guard has to be about *all* model access rather than
about whichever vendor happened to be certified first: a bomb that covered only xAI would
let an OpenAI ledger reach the OpenAI client and still pass, which would quietly retire the
invariant at the moment a second provider arrived. The runtime's own ``execute`` is bombed
as the universal chokepoint, and each installed adapter is bombed individually behind it.
"""

from __future__ import annotations

import json
import pathlib
import pkgutil
from importlib import import_module

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
from foundry.model_runtime.domain import ModelIdentity
from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._intent_synthesis_exam import (
    EXPECTED_POLICY_VERSION,
    PROJECT,
    SCOPE,
)


def _discovered_ledgers() -> list[tuple[ModelIdentity, pathlib.Path]]:
    """Every captured contestant ledger, identified by its evidence path."""
    found: list[tuple[ModelIdentity, pathlib.Path]] = []
    if not EVIDENCE_ROOT.exists():
        return found
    for ledger in sorted(EVIDENCE_ROOT.glob("*/*/case_a_ledger.json")):
        model_dir = ledger.parent
        identity = ModelIdentity(provider=model_dir.parent.name, model=model_dir.name)
        found.append((identity, ledger))
    return found


LEDGERS = _discovered_ledgers()

pytestmark = pytest.mark.skipif(
    not LEDGERS,
    reason="LIVE_LEDGER_NOT_CAPTURED: run a live certification exam first",
)

CASES = [
    pytest.param(identity, path, id=f"{identity.provider}/{identity.model}")
    for identity, path in LEDGERS
]


@pytest.fixture(autouse=True)
def provider_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any model access during reconstruction fails the test, for every provider."""

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("replay must never reach a model or provider")

    import foundry.adapters.intent_synthesis.model_runtime as intent_adapter
    import foundry.adapters.model_runtime as adapters
    import foundry.model_runtime.runtime as runtime_module

    # The universal chokepoint: nothing can reach any provider without passing through it.
    monkeypatch.setattr(runtime_module.ModelRuntime, "execute", boom)
    monkeypatch.setattr(intent_adapter.ModelRuntimeIntentSynthesizer, "synthesize", boom)

    # Defence in depth: every installed adapter's transport, discovered rather than listed,
    # so a provider added later is covered without anyone remembering to come back here.
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
        for client_symbol in ("Client", "OpenAI"):
            if hasattr(module, client_symbol):
                monkeypatch.setattr(module, client_symbol, boom, raising=False)
                bombed.append(f"{info.name}.{client_symbol}")

    assert bombed, "no provider adapter was bombed; the containment proof would be vacuous"


def _events(ledger: pathlib.Path) -> tuple[StoredEvent, ...]:
    raw = json.loads(ledger.read_text())
    return tuple(
        StoredEvent(sequence=entry["sequence"], event=parse_event(entry["event"])) for entry in raw
    )


def _canonical(value: object) -> str:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def test_the_bomb_would_actually_fire_if_replay_touched_a_provider() -> None:
    """Without this, a silently inert bomb would make every proof below vacuous."""
    import foundry.model_runtime.runtime as runtime_module

    with pytest.raises(AssertionError, match="never reach a model"):
        runtime_module.ModelRuntime.execute(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_the_live_authored_ledger_replays_identically_three_ways(
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
    again = replay(PROJECT, events)

    assert _canonical(direct) == _canonical(reparsed) == _canonical(again)
    assert _canonical(direct.intent_synthesis) == _canonical(reparsed.intent_synthesis)
    assert _canonical(direct.objects) == _canonical(reparsed.objects)
    assert _canonical(direct.semantic.derivations) == _canonical(reparsed.semantic.derivations)


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_the_model_authored_decision_survives_replay_exactly(
    identity: ModelIdentity, ledger: pathlib.Path
) -> None:
    state = replay(PROJECT, _events(ledger))
    assert state.intent_synthesis.decisions, "the preserved ledger holds no decision"
    record = next(iter(state.intent_synthesis.decisions.values()))

    # The author is the live model that actually sat the exam, recorded truthfully and
    # reconstructed from the log. It is checked against the evidence path, so a ledger
    # filed under the wrong contestant fails here rather than certifying the wrong model.
    assert record.author.provider == identity.provider
    assert record.author.model == identity.model
    assert record.author.policy_version == EXPECTED_POLICY_VERSION

    requirement = state.objects[record.identity.object_id("REQ")]
    assert isinstance(requirement, Requirement)
    assert requirement.created_at == record.decided_at
    assert requirement.confidence == record.proposal.confidence
    assert requirement.statement == record.proposal.statement


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_task_certification_grants_compute_not_authority(
    identity: ModelIdentity, ledger: pathlib.Path
) -> None:
    """§22: the Requirement stays PROPOSED. Certifying the model changes nothing here."""
    state = replay(PROJECT, _events(ledger))
    record = next(iter(state.intent_synthesis.decisions.values()))
    requirement = state.objects[record.identity.object_id("REQ")]

    assert requirement.authority is Authority.PROPOSED
    assert requirement.authority is not Authority.CANONICAL
    assert requirement.materiality is Materiality.LOW


@pytest.mark.parametrize(("identity", "ledger"), CASES)
def test_a_proposed_low_requirement_keeps_its_existing_downstream_behaviour(
    identity: ModelIdentity, ledger: pathlib.Path
) -> None:
    """Closure and the package behave exactly as they do for any PROPOSED LOW Requirement."""
    state = replay(PROJECT, _events(ledger))
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
