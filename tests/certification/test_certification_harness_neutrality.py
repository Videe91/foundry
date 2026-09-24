"""Controls on the certification harness itself: isolation, taxonomy, honest telemetry.

The semantic scorers are attacked in ``test_intent_synthesis_exam_harness``. These are the
controls on the machinery *around* them — the parts that only became load-bearing once a
second contestant existed.

Three properties are worth failing a build over:

* **evidence isolation** — a contestant that could write another contestant's artifact
  could destroy a completed certification record, which is the one thing a certification
  system must never permit;
* **failure taxonomy** — a truncated call, a refused call, a transport fault and a wrong
  answer are four different situations, and a generic assertion that flattened them would
  let a harness defect be recorded as model incompetence;
* **honest telemetry** — unknown must survive as unknown all the way into the artifact,
  because the only alternatives are fabricating ``cost_usd=0`` or ``finish_reason="stop"``.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from foundry.model_runtime.domain import ModelIdentity
from foundry.model_runtime.errors import (
    ModelProtocolError,
    ModelProviderError,
    ModelRequestError,
)
from tests.certification._certification_run import (
    EVIDENCE_ROOT,
    Contestant,
    HarnessLimitReached,
    ProtocolTaskFailure,
    TransportFailure,
    assert_guard_was_not_binding,
    classify_execution_failure,
    run_attempt,
    write_measurements,
)
from tests.certification._intent_synthesis_exam import build_case_a

GROK = ModelIdentity(provider="xai", model="grok-4.7")
ASTRA = ModelIdentity(provider="openai", model="gpt-6-astra")


def contestant(identity: ModelIdentity, *, guard: int = 2000) -> Contestant:
    return Contestant(
        identity=identity,
        credential_env="UNUSED_IN_THESE_CONTROLS",
        provider_factory=lambda _key: pytest.fail("no provider may be built by these controls"),
        max_output_tokens=guard,
    )


# --- evidence isolation -----------------------------------------------------------------------


def test_each_contestant_writes_under_its_own_provider_and_model() -> None:
    grok, astra = contestant(GROK), contestant(ASTRA)

    assert grok.evidence_dir == EVIDENCE_ROOT / "xai" / "grok-4.7"
    assert astra.evidence_dir == EVIDENCE_ROOT / "openai" / "gpt-6-astra"
    assert grok.measurements_path != astra.measurements_path
    assert grok.ledger_path != astra.ledger_path


def test_no_two_contestants_can_share_an_evidence_path() -> None:
    """The property that actually matters: one run can never overwrite another's record."""
    identities = [
        GROK,
        ASTRA,
        ModelIdentity(provider="openai", model="gpt-6-sol"),
        ModelIdentity(provider="anthropic", model="claude-opus-5"),
    ]
    paths = [
        p for i in identities for p in (contestant(i).measurements_path, contestant(i).ledger_path)
    ]
    assert len(set(paths)) == len(paths), "two contestants resolved to the same evidence file"


def test_the_single_shared_artifact_paths_are_gone() -> None:
    """The pre-migration layout had one global file per artifact. It must not come back."""
    assert not pathlib.Path("tests/certification/_last_run_measurements.json").exists()
    assert not pathlib.Path("tests/certification/_live_case_a_ledger.json").exists()


def test_the_migrated_grok_evidence_is_present_and_still_grok() -> None:
    """MR4's record survived the move intact, under its own contestant directory."""
    payload = json.loads(contestant(GROK).measurements_path.read_text())

    assert payload["candidate"] == "xai/grok-4.7"
    assert len(payload["calls"]) == 15
    assert payload["policy_version"] == "intent-synthesis-runtime-v1"


# --- failure taxonomy (R5) --------------------------------------------------------------------


def test_a_transport_fault_is_never_a_model_verdict() -> None:
    cause = ModelProviderError("provider 'openai' failed executing 'gpt-6-astra'")
    with pytest.raises(TransportFailure) as error:
        classify_execution_failure(cause)
    assert error.value.__cause__ is cause


@pytest.mark.parametrize("reason", ["max_output_tokens", "max_messages"])
def test_reaching_the_output_guard_is_a_harness_limit_not_incompetence(reason: str) -> None:
    """The guard is the certification's own bound; a model cannot fail an exam for it."""
    cause = ModelProtocolError(f"OpenAI returned an incomplete response (reason: {reason})")
    with pytest.raises(HarnessLimitReached) as error:
        classify_execution_failure(cause)
    assert error.value.__cause__ is cause


def test_a_refusal_or_schema_break_is_a_protocol_task_failure() -> None:
    cause = ModelProtocolError(
        "OpenAI returned a refusal instead of the requested structured output"
    )
    with pytest.raises(ProtocolTaskFailure) as error:
        classify_execution_failure(cause)
    assert error.value.__cause__ is cause


def test_the_three_categories_are_genuinely_distinct_types() -> None:
    """A shared base would let one `except` clause silently absorb all three."""
    assert not issubclass(TransportFailure, ProtocolTaskFailure)
    assert not issubclass(HarnessLimitReached, ProtocolTaskFailure)
    assert not issubclass(ProtocolTaskFailure, TransportFailure)
    # Incomplete runs are not verdicts, so they must not masquerade as assertion failures.
    assert not issubclass(TransportFailure, AssertionError)
    assert not issubclass(HarnessLimitReached, AssertionError)


def test_an_unrelated_failure_is_left_alone_to_surface_as_itself() -> None:
    """Only the two runtime categories are reclassified; nothing else is swallowed."""
    classify_execution_failure(ModelRequestError("a caller bug"))  # returns, raises nothing


# --- the predeclared guard must stay non-binding ------------------------------------------------


def measurement(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "case": "A",
        "attempt": 1,
        "provider": "openai",
        "model": "gpt-6-astra",
        "input_tokens": 3000,
        "output_tokens": 120,
        "cost_usd": None,
        "wall_clock_ms": 20000,
        "finish_reason": None,
        "outcome": "NEW",
        "governance_error": None,
    }
    base.update(overrides)
    return base


def test_a_run_that_reached_the_guard_is_refused() -> None:
    with pytest.raises(HarnessLimitReached, match="output guard"):
        assert_guard_was_not_binding(
            contestant(ASTRA, guard=16000), [measurement(output_tokens=16000)]
        )


def test_a_run_with_headroom_passes() -> None:
    assert_guard_was_not_binding(contestant(ASTRA, guard=16000), [measurement(output_tokens=900)])


def test_unreported_output_tokens_cannot_hide_a_binding_guard() -> None:
    """Absent counts are not treated as proof of headroom, only as absent."""
    assert_guard_was_not_binding(contestant(ASTRA, guard=16000), [measurement(output_tokens=None)])


# --- honest telemetry all the way into the artifact ---------------------------------------------


def test_a_provider_reporting_no_cost_yields_unknown_not_zero(tmp_path: pathlib.Path) -> None:
    """The exact shape OpenAI produces. Nothing here may become a fabricated measurement."""
    astra = Contestant(
        identity=ASTRA,
        credential_env="UNUSED",
        provider_factory=lambda _key: pytest.fail("no provider"),
        max_output_tokens=16000,
    )
    calls = [measurement(attempt=i) for i in range(1, 16)]

    import tests.certification._certification_run as runner

    original = runner.EVIDENCE_ROOT
    runner.EVIDENCE_ROOT = tmp_path  # write the control's artifact somewhere disposable
    try:
        payload = write_measurements(
            astra,
            calls,
            policy_version="intent-synthesis-runtime-v1",
            prompt_sha256="af49dbd3",
            runs_per_case=3,
        )
    finally:
        runner.EVIDENCE_ROOT = original

    assert payload["known_cost_total"] is None, "no cost was reported; none may be invented"
    assert payload["known_cost_samples"] == 0
    assert payload["unknown_cost_samples"] == 15
    assert payload["reported_finish_reasons"] == [], "no finish reason may be synthesized"
    assert payload["output_token_guard"] == 16000
    assert payload["output_token_high_water"] == 120

    serialized = json.dumps(payload)
    assert '"cost_usd": 0' not in serialized
    assert '"stop"' not in serialized


def test_reported_cost_is_still_summed_when_a_provider_does_supply_it(
    tmp_path: pathlib.Path,
) -> None:
    """The unknown-safe path must not have made known values disappear."""
    grok = contestant(GROK)
    calls = [measurement(cost_usd=0.01, finish_reason="REASON_STOP") for _ in range(3)]

    import tests.certification._certification_run as runner

    original = runner.EVIDENCE_ROOT
    runner.EVIDENCE_ROOT = tmp_path
    try:
        payload = write_measurements(
            grok,
            calls,
            policy_version="intent-synthesis-runtime-v1",
            prompt_sha256="af49dbd3",
            runs_per_case=1,
        )
    finally:
        runner.EVIDENCE_ROOT = original

    assert payload["known_cost_samples"] == 3
    assert payload["unknown_cost_samples"] == 0
    assert payload["known_cost_total"] == pytest.approx(0.03)
    assert payload["reported_finish_reasons"] == ["REASON_STOP"]


# --- the runner must actually USE the taxonomy --------------------------------------------------
#
# Testing the classifier in isolation proves only that it can classify. Until something
# drives `run_attempt` itself, deleting its call to the classifier changes no test — and
# the flattening would then be discovered during a billed live run, which is the one place
# it must never be discovered. These controls exercise the real runner offline by failing
# at the provider seam, so the wiring is asserted without a network or a credential.


class ExplodingProvider:
    """A real-shaped provider that fails the way a live one would."""

    def __init__(self, provider_id: str, failure: BaseException) -> None:
        self._provider_id = provider_id
        self._failure = failure
        self.calls = 0

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def execute(self, **kwargs: Any) -> Any:
        self.calls += 1
        raise self._failure


def exploding_contestant(identity: ModelIdentity, failure: BaseException, *, guard: int = 2000):
    return Contestant(
        identity=identity,
        credential_env="UNUSED",
        provider_factory=lambda _key: ExplodingProvider(identity.provider, failure),
        max_output_tokens=guard,
    )


def test_the_runner_classifies_a_transport_fault_rather_than_flattening_it() -> None:
    failure = ModelProviderError("provider 'openai' failed executing 'gpt-6-astra'")
    with pytest.raises(TransportFailure):
        run_attempt(exploding_contestant(ASTRA, failure), build_case_a(), "A", 1, api_key="unused")


def test_the_runner_classifies_a_guard_truncation_as_a_harness_limit() -> None:
    failure = ModelProtocolError(
        "OpenAI returned an incomplete response (reason: max_output_tokens)"
    )
    with pytest.raises(HarnessLimitReached):
        run_attempt(exploding_contestant(ASTRA, failure), build_case_a(), "A", 1, api_key="unused")


def test_the_runner_classifies_a_refusal_as_a_protocol_task_failure() -> None:
    failure = ModelProtocolError("OpenAI returned a refusal instead of the requested output")
    with pytest.raises(ProtocolTaskFailure):
        run_attempt(exploding_contestant(ASTRA, failure), build_case_a(), "A", 1, api_key="unused")
