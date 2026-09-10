"""Task 9K2-A live adjudication CLI surface.

`preflight` and `verify` must make zero OpenAI calls. `adjudicate` is the only command
that may construct a client, and it must refuse before construction when the key is
absent or the bundle is already frozen.

No test in this module constructs a real OpenAI client or reaches a network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import foundry.evaluation.phase2_live as phase2_live
from foundry.domain.gaps import GapKind
from foundry.evaluation.comparative_protocol import (
    BlindAdjudicationPacket,
    ConceptCriticality,
    ExpectedConcept,
)
from foundry.evaluation.phase2_adjudication import (
    ADJUDICATOR_INSTRUCTION,
    PHASE2_MODEL,
    PHASE2_REASONING_EFFORT,
    PrimaryCaseAdjudication,
    strict_json_schema,
)
from foundry.evaluation.phase2_live import (
    API_KEY_ENV,
    DEFAULT_JUDGE_BUNDLE_PATH,
    EXIT_AMBIGUOUS,
    EXIT_FROZEN,
    EXIT_LEAK,
    EXIT_MISSING_KEY,
    EXIT_OK,
    EXIT_PAUSED,
    EXIT_SEAL,
    EXIT_STRUCTURAL,
    build_openai_adjudicator,
    build_parser,
    main,
    packet_payload,
)
from foundry.evaluation.phase2_runner import (
    AmbiguousInFlightAdjudication,
    Phase2AlreadyFrozen,
    Phase2Paused,
    Phase2SealViolation,
    Phase2StructuralFailure,
    RawAdjudicationResponse,
)
from foundry.intelligence.comparison import BlindPrediction

API_KEY = "sk-do-not-log-this-value-0123456789"
RUNNER_COMMIT = "2" * 40


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import socket

    def blocked(*_: Any, **__: Any) -> None:
        raise AssertionError("a Phase-2 CLI unit test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield


def _packet() -> BlindAdjudicationPacket:
    prediction = BlindPrediction(
        prediction_id="P-001",
        kind=GapKind.MISSING_INFORMATION,
        subject_key="retention-window",
        description="the retention window is never decided",
        source_event_ids=("E-1",),
        confidence=0.7,
    )
    concept = ExpectedConcept(
        concept_id="C-001",
        semantic_description="the retention window is undecided",
        primary_gap_kind=GapKind.MISSING_INFORMATION,
        criticality=ConceptCriticality.CRITICAL,
        exact_subject_key="retention-window",
        evidence_event_ids=("E-1",),
        evidence_basis="E-1",
        materiality_rationale="material",
    )
    return BlindAdjudicationPacket(
        case_id="H-001",
        source_evidence=(),
        expected_concepts=(concept,),
        system_a_predictions=(prediction,),
        system_b_predictions=(prediction,),
    )


# --------------------------------------------------------------------------- fake SDK


class FakeResponses:
    def __init__(self, parent: FakeOpenAI) -> None:
        self.parent = parent

    def create(self, **kwargs: Any) -> Any:
        self.parent.calls.append(kwargs)

        class Usage:
            input_tokens = 111
            output_tokens = 222

        class Response:
            id = "resp_fake_1"
            output_text = json.dumps({"case_id": "H-001"})
            usage = Usage()

        return Response()


class FakeOpenAI:
    """Stands in for the OpenAI SDK client. Constructing it is the observable event."""

    instances: list[FakeOpenAI] = []

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.responses = FakeResponses(self)
        FakeOpenAI.instances.append(self)


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> FakeOpenAI:
    FakeOpenAI.instances.clear()
    monkeypatch.setattr(phase2_live, "_load_openai_client_class", lambda: FakeOpenAI)
    monkeypatch.setattr(phase2_live, "resolve_openai_sdk_version", lambda: "2.9.0")
    return FakeOpenAI  # type: ignore[return-value]


# --------------------------------------------------------------------------- CLI shape


def test_parser_exposes_the_three_commands() -> None:
    parser = build_parser()
    for command in ("preflight", "adjudicate", "verify"):
        args = parser.parse_args([command, "--runner-commit", RUNNER_COMMIT])
        assert args.command == command


def test_default_judge_bundle_path_is_outside_the_repository() -> None:
    assert DEFAULT_JUDGE_BUNDLE_PATH == (
        "../.foundry-sealed-evals/intent-intelligence-v1/hidden-judge.json"
    )


def test_adjudicate_refuses_before_constructing_a_client_when_the_key_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_sdk: Any
) -> None:
    lines: list[str] = []
    monkeypatch.setattr(phase2_live, "preflight", lambda **_: _stub_preflight())
    code = phase2_live.run_adjudicate(
        repo_root=tmp_path,
        runner_commit_sha=RUNNER_COMMIT,
        judge_bundle_path=tmp_path / "judge.json",
        resume=False,
        env={},
        out=lines.append,
    )
    assert code == EXIT_MISSING_KEY
    assert any("OPENAI_API_KEY NOT AVAILABLE" in line for line in lines)
    assert FakeOpenAI.instances == []


def test_api_key_env_name_is_the_frozen_one() -> None:
    assert API_KEY_ENV == "OPENAI_API_KEY"


def test_no_command_prints_a_key_or_a_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []

    def raising(**_: Any) -> None:
        raise Phase2SealViolation("failed with authorization: Bearer " + API_KEY)

    monkeypatch.setattr(phase2_live, "preflight", raising)
    code = main(
        ["preflight", "--runner-commit", RUNNER_COMMIT, "--repo-root", str(tmp_path)],
        out=lines.append,
    )
    assert code == EXIT_SEAL
    joined = "\n".join(lines)
    assert API_KEY not in joined
    assert "[REDACTED]" in joined


# --------------------------------------------------------------------------- exit codes


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (Phase2AlreadyFrozen("frozen"), EXIT_FROZEN),
        (AmbiguousInFlightAdjudication("STOP - AMBIGUOUS IN-FLIGHT ADJUDICATION"), EXIT_AMBIGUOUS),
        (Phase2Paused("PAUSED_INFRASTRUCTURE"), EXIT_PAUSED),
        (
            Phase2StructuralFailure("STOP - PRIMARY ADJUDICATION STRUCTURAL FAILURE"),
            EXIT_STRUCTURAL,
        ),
        (Phase2SealViolation("seal"), EXIT_SEAL),
    ],
)
def test_each_frozen_failure_mode_has_its_own_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, code: int
) -> None:
    def raising(**_: Any) -> None:
        raise error

    monkeypatch.setattr(phase2_live, "verify_phase2_output", raising)
    assert (
        main(
            ["verify", "--runner-commit", RUNNER_COMMIT, "--repo-root", str(tmp_path)],
            out=lambda _: None,
        )
        == code
    )


def test_an_identity_leak_has_its_own_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foundry.evaluation.phase2_adjudication import BlindPredictionIdentityLeak

    lines: list[str] = []

    def raising(**_: Any) -> None:
        raise BlindPredictionIdentityLeak("STOP - BLIND PREDICTION IDENTITY LEAK: case H-001")

    monkeypatch.setattr(phase2_live, "preflight", raising)
    code = main(
        ["preflight", "--runner-commit", RUNNER_COMMIT, "--repo-root", str(tmp_path)],
        out=lines.append,
    )
    assert code == EXIT_LEAK
    assert any("BLIND PREDICTION IDENTITY LEAK" in line for line in lines)


def test_preflight_reports_only_safe_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []
    monkeypatch.setattr(phase2_live, "preflight", lambda **_: _stub_preflight())
    code = main(
        ["preflight", "--runner-commit", RUNNER_COMMIT, "--repo-root", str(tmp_path)],
        out=lines.append,
    )
    assert code == EXIT_OK
    joined = "\n".join(lines).lower()
    assert "phase2 preflight pass" in joined
    for banned in ("foundry", "baseline", "grok", "concept", "prediction", "rationale"):
        assert banned not in joined


# --------------------------------------------------------------------------- call contract


def test_the_adjudicator_sends_the_exact_frozen_call_contract(fake_sdk: Any) -> None:
    adjudicate = build_openai_adjudicator(api_key=API_KEY)
    adjudicate(_packet())
    client = FakeOpenAI.instances[-1]
    assert client.init_kwargs["api_key"] == API_KEY
    assert len(client.calls) == 1
    sent = client.calls[0]
    assert sent["model"] == PHASE2_MODEL == "gpt-5.6-sol"
    assert sent["reasoning"]["effort"] == PHASE2_REASONING_EFFORT == "high"
    assert sent["store"] is False
    assert sent.get("tools", []) == []
    assert "previous_response_id" not in sent
    assert "conversation" not in sent
    assert "temperature" not in sent
    assert "top_p" not in sent


def test_the_adjudicator_uses_strict_structured_outputs(fake_sdk: Any) -> None:
    adjudicate = build_openai_adjudicator(api_key=API_KEY)
    adjudicate(_packet())
    text = FakeOpenAI.instances[-1].calls[0]["text"]
    assert text["format"]["type"] == "json_schema"
    assert text["format"]["strict"] is True
    assert text["format"]["schema"] == strict_json_schema(PrimaryCaseAdjudication)


def test_the_frozen_instruction_is_sent_verbatim(fake_sdk: Any) -> None:
    adjudicate = build_openai_adjudicator(api_key=API_KEY)
    adjudicate(_packet())
    messages = FakeOpenAI.instances[-1].calls[0]["input"]
    instruction = json.dumps(messages)
    assert ADJUDICATOR_INSTRUCTION in json.loads(instruction)[0]["content"][0]["text"]


def test_every_call_is_fresh(fake_sdk: Any) -> None:
    adjudicate = build_openai_adjudicator(api_key=API_KEY)
    adjudicate(_packet())
    adjudicate(_packet())
    client = FakeOpenAI.instances[-1]
    assert len(client.calls) == 2
    for sent in client.calls:
        assert "previous_response_id" not in sent
        assert sent["store"] is False


def test_the_request_body_carries_the_packet_and_nothing_else(fake_sdk: Any) -> None:
    adjudicate = build_openai_adjudicator(api_key=API_KEY)
    packet = _packet()
    adjudicate(packet)
    messages = FakeOpenAI.instances[-1].calls[0]["input"]
    assert [message["role"] for message in messages] == ["developer", "user"]
    # The developer turn is the frozen instruction verbatim; the user turn is the
    # packet and nothing else. Only the packet turn is scanned for leaked facts.
    sent_packet = messages[1]["content"][0]["text"]
    assert sent_packet == packet_payload(packet)
    lowered = sent_packet.lower()
    for banned in ("foundry", "baseline", "xai", "grok", "cost", "latency", "execution"):
        assert banned not in lowered
    assert packet.case_id in sent_packet


def test_packet_payload_is_canonical_and_carries_no_identity() -> None:
    payload = packet_payload(_packet())
    parsed = json.loads(payload)
    assert set(parsed) == {
        "case_id",
        "source_evidence",
        "expected_concepts",
        "system_a_predictions",
        "system_b_predictions",
    }


def test_the_adjudicator_returns_the_raw_text_for_the_runner_to_validate(
    fake_sdk: Any,
) -> None:
    adjudicate = build_openai_adjudicator(api_key=API_KEY)
    response = adjudicate(_packet())
    assert isinstance(response, RawAdjudicationResponse)
    assert response.provider_response_id == "resp_fake_1"
    assert response.input_tokens == 111
    assert response.output_tokens == 222
    # The adapter never parses or repairs; the runner owns validation.
    assert response.output_text == json.dumps({"case_id": "H-001"})


def test_the_sdk_is_imported_lazily_inside_the_execution_path() -> None:
    """Importing the CLI must never require the evaluation-only OpenAI dependency."""
    source = Path(phase2_live.__file__).read_text(encoding="utf-8")
    module_level = source.split("\ndef ")[0]
    assert "import openai" not in module_level
    assert "from openai" not in module_level
    assert 'importlib.import_module("openai")' in source


def test_a_missing_sdk_is_a_seal_violation_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    def absent(name: str) -> Any:
        raise ImportError("No module named 'openai'")

    monkeypatch.setattr(importlib, "import_module", absent)
    with pytest.raises(Phase2SealViolation, match="openai"):
        phase2_live._load_openai_client_class()


def test_live_module_never_names_a_contestant_surface() -> None:
    source = Path(phase2_live.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "execution-assignment",
        "XAIIntentIntelligence",
        "XAIBaselineIntelligence",
        "phase1/raw",
        "phase1/records",
        "ContestantId",
    ):
        assert forbidden not in source


def _stub_preflight() -> Any:
    class _Stub:
        case_sequence = tuple(f"H-{index:03d}" for index in range(1, 13))
        blind_output_count = 24
        adjudication_runner_commit = RUNNER_COMMIT
        experiment_manifest_sha256 = "a" * 64
        phase1_bundle_sha256 = "b" * 64
        hidden_judge_commitment_sha256 = "c" * 64
        adjudicator_instruction_sha256 = "d" * 64
        adjudication_mechanism_sha256 = "e" * 64
        semantic_rubric_sha256 = "f" * 64
        phase1_output_commit = "0" * 40
        phase1_runner_commit = "1" * 40
        packet_digests = tuple("9" * 64 for _ in range(12))
        runner_artifacts = ()
        sdk_version = "2.9.0"

    return _Stub()
