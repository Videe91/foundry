"""9P2 T7: the live-capable entry point and its preflight-before-construction law
(spec §14.1, §15, §16, §17.2-§17.4; brief T7; clarification C2; Controller Ruling 7).

Every git fact and regression command is an injected fake returning realistic values;
every reasoner is a scripted fake injected through ``reasoner_factory``; every
experiment directory is a throwaway under ``tmp_path`` sealed with the real
``build_manifest``/``write_preregistration``. ``--live`` is never run against a real
provider; no real ``XAI_API_KEY`` is read; no ``XAISemanticReasoner`` is constructed.
ZERO live calls; sockets are blocked.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import scripts.run_contrastive_unseen_lifecycle as entrypoint
from foundry.adapters.semantics.xai_reasoner import XAIProviderError
from foundry.application.semantic_reducer import address_id_for
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.experiments.contrastive_unseen.artifacts import (
    RAW_ARTIFACT_PATHS,
    build_manifest,
    write_preregistration,
)
from foundry.experiments.contrastive_unseen.integrity import (
    GATE_NAMES,
    PREREGISTRATION_FILES,
    SCOPE_CLOSURE_REGRESSION_ARGV,
    TRACK_A_REGRESSION_ARGV,
)
from foundry.experiments.contrastive_unseen.timeline import FROZEN_CORE_SHA
from foundry.ports.semantic_reasoner import ReasoningRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 9, 12, tzinfo=UTC)
FINGERPRINT = ReasonerFingerprint(provider="fake", model="fake-model", policy_version="fake-v0")
HARNESS_SHA = "a" * 40
SEAL_SHA = "5" * 40
SPEC_SHA = "b" * 64
KEY_CANARY = "FAKE-KEY-CANARY-0123456789"
ENV_CANARY = "UNRELATED-ENV-CANARY-9876543210"
SECRET_SHAPED = "xai-abcdef123456"
HARNESS_CHANGES = (
    "src/foundry/experiments/contrastive_unseen/__init__.py",
    "src/foundry/experiments/contrastive_unseen/timeline.py",
    "src/foundry/experiments/contrastive_unseen/runner.py",
    "scripts/run_contrastive_unseen_lifecycle.py",
    "tests/integration/test_contrastive_unseen_entrypoint.py",
    "docs/superpowers/plans/2026-09-12-9p2-unseen-lifecycle-experiment.md",
    *PREREGISTRATION_FILES,
)
CORE_PATH = "src/foundry/domain/semantic_judgment.py"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- injected git / command fakes (realistic values, never hard-coded success) --------


class FakeGit:
    def __init__(
        self,
        *,
        head: str = SEAL_SHA,
        dirty: str = "",
        parents: dict[str, tuple[str, ...]] | None = None,
        ancestors: frozenset[tuple[str, str]] = frozenset({(FROZEN_CORE_SHA, SEAL_SHA)}),
        changed: dict[tuple[str, str], tuple[str, ...]] | None = None,
    ) -> None:
        self._head = head
        self._dirty = dirty
        self._parents = parents if parents is not None else {SEAL_SHA: (HARNESS_SHA,)}
        self._ancestors = ancestors
        self._changed = (
            changed
            if changed is not None
            else {
                (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
                (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
            }
        )
        self.calls: list[tuple[str, ...]] = []

    def head(self) -> str:
        self.calls.append(("head",))
        return self._head

    def dirty(self) -> str:
        self.calls.append(("dirty",))
        return self._dirty

    def parents(self, sha: str) -> tuple[str, ...]:
        self.calls.append(("parents", sha))
        return self._parents.get(sha, ())

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", ancestor, descendant))
        return (ancestor, descendant) in self._ancestors

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        self.calls.append(("changed_paths", base, head))
        return self._changed.get((base, head), ())

    def show_bytes(self, sha: str, path: str) -> bytes:
        self.calls.append(("show_bytes", sha, path))
        return b""


class FakeCommands:
    def __init__(self, exit_codes: dict[tuple[str, ...], int] | None = None) -> None:
        self._exit_codes = exit_codes or {}
        self.argvs: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> tuple[int, str]:
        self.argvs.append(argv)
        code = self._exit_codes.get(argv, 0)
        return code, f"fake output for {' '.join(argv)} (exit {code})"


# --- environment fakes ---------------------------------------------------------------


class PoisonedEnv(dict[str, str]):
    """Any read is a violation: the key must not be touched on this path."""

    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"environment read of {key!r} is forbidden on this path")

    def get(self, key: str, default: Any = None) -> Any:
        raise AssertionError(f"environment read of {key!r} is forbidden on this path")

    def __contains__(self, key: object) -> bool:
        raise AssertionError(f"environment probe of {key!r} is forbidden on this path")


class RecordingEnv(dict[str, str]):
    """Records which names were read so a test can prove the key was read only once."""

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        self.reads.append(key)
        return super().get(key, default)


# --- scripted fake reasoners (the T5/T6 idiom) ---------------------------------------


class FakeReceipt(FrozenModel):
    invocation_id: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    wall_clock_ms: int
    draft_count: int


def _create_id(evidence_id: str) -> str:
    return f"J-create-{evidence_id}"


def _bind_id(evidence_id: str) -> str:
    return f"J-bind-{evidence_id}"


def _claim_id(evidence_id: str) -> str:
    return f"J-claim-{evidence_id}"


def _supersede_id(evidence_id: str) -> str:
    return f"J-supersede-{evidence_id}"


class LifecycleScript:
    """Structurally valid judgments derived only from the request shown to it."""

    def __init__(self) -> None:
        self._address_of: dict[tuple[str, str], str] = {}

    def __call__(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            return self._call_one(request)
        return self._call_two(request)

    def _judgment(
        self, request: ReasoningRequest, judgment_id: str, proposal: JudgmentProposal
    ) -> SemanticJudgment:
        return SemanticJudgment(
            judgment_id=judgment_id,
            project_id=request.project_id,
            proposal=proposal,
            visible_evidence_ids=tuple(item.evidence_id for item in request.evidence),
            rationale=f"Opaque rationale for {judgment_id}.",
            reasoner=FINGERPRINT,
            invocation_id=f"INV-{judgment_id}",
            proposed_at=T0,
        )

    def _call_one(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        known = {address.address_id for address in request.known_addresses}
        judgments: list[SemanticJudgment] = []
        for item in request.evidence:
            candidate = SemanticCandidate(
                candidate_id=f"CAND-{item.evidence_id}",
                subject=f"subject {item.evidence_id}",
                facet="lifecycle",
                scope=item.scope,
                evidence_ids=(item.evidence_id,),
            )
            predecessor = item.supersedes_evidence_id
            prior = (
                self._address_of.get((request.project_id, predecessor))
                if predecessor is not None
                else None
            )
            if prior is not None and prior in known:
                judgment_id = _bind_id(item.evidence_id)
                proposal: JudgmentProposal = BindToAddressProposal(
                    candidate=candidate, address_id=prior
                )
                address_id = prior
            else:
                judgment_id = _create_id(item.evidence_id)
                proposal = CreateAddressProposal(candidate=candidate)
                address_id = address_id_for(request.project_id, judgment_id)
            self._address_of[(request.project_id, item.evidence_id)] = address_id
            judgments.append(self._judgment(request, judgment_id, proposal))
        return tuple(judgments)

    def _call_two(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        known_creators = {claim.created_by_judgment_id for claim in request.known_claims}
        judgments: list[SemanticJudgment] = []
        for item in request.evidence:
            address_id = self._address_of[(request.project_id, item.evidence_id)]
            judgments.append(
                self._judgment(
                    request,
                    _claim_id(item.evidence_id),
                    AssertClaimProposal(
                        address_id=address_id,
                        predicate="policy_value",
                        value=ClaimValue(
                            kind=ClaimValueKind.TEXT, text=f"value {item.evidence_id}"
                        ),
                        evidence_ids=(item.evidence_id,),
                        authority=Authority.OBSERVED,
                    ),
                )
            )
            predecessor = item.supersedes_evidence_id
            if predecessor is not None and _claim_id(predecessor) in known_creators:
                judgments.append(
                    self._judgment(
                        request,
                        _supersede_id(item.evidence_id),
                        SupersedeProposal(
                            target_judgment_id=_claim_id(predecessor),
                            reason="Opaque supersession reason.",
                        ),
                    )
                )
        return tuple(judgments)


class ScriptedReasoner:
    """Runs ``LifecycleScript`` per call unless an exception is scripted for that call."""

    def __init__(self, *, label: str, failures: dict[int, BaseException] | None = None) -> None:
        self._script = LifecycleScript()
        self._failures = failures or {}
        self._label = label
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[FakeReceipt] = []
        self._drafts: list[str] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return FINGERPRINT

    @property
    def receipts(self) -> tuple[FakeReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[str, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        failure = self._failures.get(index)
        if failure is not None:
            raise failure
        self._receipts.append(
            FakeReceipt(
                invocation_id=f"{self._label}-{index + 1}",
                cost_usd=0.01,
                input_tokens=100 + index,
                output_tokens=10 + index,
                wall_clock_ms=5,
                draft_count=1,
            )
        )
        self._drafts.append(f"draft:{self._label}:{index + 1}")
        return self._script(request)


class FakeFactory:
    """Builds scripted arms; records every api_key it was handed (never printed)."""

    def __init__(
        self,
        *,
        f_failures: dict[int, BaseException] | None = None,
        a_failures: dict[int, BaseException] | None = None,
        r_failures: dict[int, BaseException] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.f = ScriptedReasoner(label="F", failures=f_failures)
        self.a = ScriptedReasoner(label="A", failures=a_failures)
        self.r = ScriptedReasoner(label="R", failures=r_failures)

    def __call__(
        self, *, api_key: str
    ) -> tuple[ScriptedReasoner, ScriptedReasoner, ScriptedReasoner]:
        self.calls.append(api_key)
        return self.f, self.a, self.r

    @property
    def total_requests(self) -> int:
        return len(self.f.requests) + len(self.a.requests) + len(self.r.requests)


def _poisoned_factory(*, api_key: str) -> tuple[Any, Any, Any]:
    raise AssertionError("reasoner_factory must not be called on this path")


# --- fixtures and helpers -------------------------------------------------------------


@pytest.fixture
def sealed(tmp_path: Path) -> Path:
    out = tmp_path / "experiment"
    out.mkdir()
    write_preregistration(out, build_manifest(harness_code_sha=HARNESS_SHA, spec_sha256=SPEC_SHA))
    return out


def _seal_bytes(out: Path) -> dict[str, bytes]:
    return {name: (out / name).read_bytes() for name in ("manifest.json", "expectations.json")}


def _dir_snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _relative_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _main(
    mode: str,
    out: Path,
    *,
    frozen_sha: str = SEAL_SHA,
    cwd: Path = REPO_ROOT,
    env: Any = None,
    factory: Callable[..., Any] = _poisoned_factory,
    git: FakeGit | None = None,
    commands: FakeCommands | None = None,
) -> int:
    return entrypoint.main(
        [mode, "--frozen-sha", frozen_sha, "--out", str(out)],
        cwd=cwd,
        env=PoisonedEnv() if env is None else env,
        reasoner_factory=factory,
        git=git if git is not None else FakeGit(),
        commands=commands if commands is not None else FakeCommands(),
    )


def _gate_table(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {gate["name"]: gate for gate in document["gates"]}


def _request_count(out: Path) -> int:
    paths = ("F/requests.json", "A/requests.json", *(f"R/T{t}/requests.json" for t in (1, 2, 3, 4)))
    return sum(len(_read_json(out / path)["requests"]) for path in paths)


def _all_artifact_text(out: Path) -> Iterator[tuple[str, str]]:
    for path in RAW_ARTIFACT_PATHS:
        file = out / path
        if file.exists():
            yield path, file.read_text(encoding="utf-8")


# --- argument handling ---------------------------------------------------------------


@pytest.mark.parametrize("bad_sha", ["abc", "A" * 40, "g" * 40, "5" * 39, "5" * 41])
def test_frozen_sha_must_be_forty_lowercase_hex(sealed: Path, bad_sha: str) -> None:
    code = _main("--preflight-only", sealed, frozen_sha=bad_sha)

    assert code == 2
    assert _relative_files(sealed) == {"manifest.json", "expectations.json"}


def test_modes_are_mutually_exclusive_and_required(sealed: Path) -> None:
    argv_common = ["--frozen-sha", SEAL_SHA, "--out", str(sealed)]
    kwargs: dict[str, Any] = {
        "cwd": REPO_ROOT,
        "env": PoisonedEnv(),
        "reasoner_factory": _poisoned_factory,
        "git": FakeGit(),
        "commands": FakeCommands(),
    }

    assert entrypoint.main(argv_common, **kwargs) == 2
    assert entrypoint.main(["--preflight-only", "--live", *argv_common], **kwargs) == 2
    assert _relative_files(sealed) == {"manifest.json", "expectations.json"}


# --- preflight-only ------------------------------------------------------------------


def test_preflight_only_prints_document_writes_nothing_and_constructs_nothing(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _dir_snapshot(sealed)
    git = FakeGit()
    commands = FakeCommands()

    code = _main("--preflight-only", sealed, git=git, commands=commands)

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["all_passed"] is True
    assert document["frozen_sha"] == SEAL_SHA
    assert tuple(gate["name"] for gate in document["gates"]) == GATE_NAMES
    assert all(gate["passed"] for gate in document["gates"])
    assert document["leakage"]["passed"] is True
    assert set(document) == {
        "artifact_format_version",
        "experiment_version",
        "frozen_sha",
        "all_passed",
        "gates",
        "leakage",
    }
    assert _dir_snapshot(sealed) == before
    assert ("head",) in git.calls and ("dirty",) in git.calls
    assert TRACK_A_REGRESSION_ARGV in commands.argvs
    assert SCOPE_CLOSURE_REGRESSION_ARGV in commands.argvs


def test_preflight_only_exits_3_on_dirty_tree_and_still_prints_the_document(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _dir_snapshot(sealed)

    code = _main("--preflight-only", sealed, git=FakeGit(dirty=" M src/foundry/x.py"))

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    assert document["all_passed"] is False
    gates = _gate_table(document)
    assert gates["worktree_clean"]["passed"] is False
    assert "src/foundry/x.py" in gates["worktree_clean"]["detail"]
    assert _dir_snapshot(sealed) == before


def test_preflight_only_refuses_without_seal_files(tmp_path: Path) -> None:
    out = tmp_path / "unsealed"
    out.mkdir()

    assert _main("--preflight-only", out) == 2
    assert _relative_files(out) == set()


def test_gates_use_injected_git_results_not_hard_coded_success(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git = FakeGit(
        parents={SEAL_SHA: ("c" * 40,)},
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): (*HARNESS_CHANGES, CORE_PATH),
        },
    )

    code = _main("--preflight-only", sealed, git=git)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["head_equals_final_seal"]["passed"] is False
    assert HARNESS_SHA in gates["head_equals_final_seal"]["detail"]
    assert gates["core_paths_unchanged_since_frozen_core"]["passed"] is False
    assert CORE_PATH in gates["core_paths_unchanged_since_frozen_core"]["detail"]
    assert gates["worktree_clean"]["passed"] is True
    assert ("changed_paths", FROZEN_CORE_SHA, SEAL_SHA) in git.calls


def test_failing_regression_command_fails_its_gate(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = FakeCommands({TRACK_A_REGRESSION_ARGV: 1})

    code = _main("--preflight-only", sealed, commands=commands)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["track_a_regression_passes"]["passed"] is False
    assert gates["scope_closure_regression_passes"]["passed"] is True


def test_tampered_manifest_prompt_hash_fails_gate_6_from_real_bytes(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _read_json(sealed / "manifest.json")
    manifest["fr_prompt_sha256"] = "0" * 64
    (sealed / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    code = _main("--preflight-only", sealed)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["fr_prompt_hash_frozen"]["passed"] is False
    assert "0" * 64 in gates["fr_prompt_hash_frozen"]["detail"]
    assert gates["a_prompt_hash_frozen"]["passed"] is True


def test_missing_request_path_file_fails_gate_16_without_fabrication(
    sealed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "not-the-repo"
    elsewhere.mkdir()

    code = _main("--preflight-only", sealed, cwd=elsewhere)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["answer_key_not_imported_by_request_path"]["passed"] is False
    assert "missing" in gates["answer_key_not_imported_by_request_path"]["detail"]
    assert "runner.py" in gates["answer_key_not_imported_by_request_path"]["detail"]


# --- live: refusals before anything else ---------------------------------------------


def test_live_refuses_without_seal_files(tmp_path: Path) -> None:
    out = tmp_path / "unsealed"
    out.mkdir()

    assert _main("--live", out) == 2
    assert _relative_files(out) == set()


def test_live_refuses_when_a_raw_artifact_exists(sealed: Path) -> None:
    (sealed / "preflight.json").write_text("{}\n", encoding="utf-8")
    before = _dir_snapshot(sealed)
    git = FakeGit()

    code = _main("--live", sealed, git=git)

    assert code == 2
    assert _dir_snapshot(sealed) == before
    assert git.calls == []


def test_live_refuses_when_a_nested_raw_artifact_exists(sealed: Path) -> None:
    (sealed / "R" / "T3").mkdir(parents=True)
    (sealed / "R" / "T3" / "result.json").write_text("{}\n", encoding="utf-8")
    before = _dir_snapshot(sealed)

    assert _main("--live", sealed) == 2
    assert _dir_snapshot(sealed) == before


# --- live: preflight before key and construction -------------------------------------


def test_live_failed_preflight_writes_preflight_only_and_never_reads_key(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, git=FakeGit(dirty="?? scratch.txt"))

    assert code == 3
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}
    preflight = _read_json(sealed / "preflight.json")
    assert preflight["all_passed"] is False
    assert _gate_table(preflight)["worktree_clean"]["passed"] is False
    assert "ABORTED_PREFLIGHT" in capsys.readouterr().out
    assert _seal_bytes(sealed) == seal_before


def test_live_missing_key_after_passed_preflight_is_aborted_runtime_with_zero_calls(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = RecordingEnv({"UNRELATED": ENV_CANARY})
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=env)

    assert code == 4
    assert env.reads == ["XAI_API_KEY"]
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "MISSING_API_KEY"
    assert f_result["budget"]["frontier_calls"] == 0
    assert f_result["budget"]["provider_cost_usd"] == "0"
    assert [step["status"] for step in f_result["steps"]] == ["NOT_RUN"] * 4
    assert [s["status"] for s in _read_json(sealed / "A/result.json")["steps"]] == ["NOT_RUN"] * 4
    for t in (1, 2, 3, 4):
        assert _read_json(sealed / f"R/T{t}/result.json")["status"] == "NOT_RUN"
    assert _request_count(sealed) == 0
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["scientific_decision"] is None
    for path, text in _all_artifact_text(sealed):
        assert ENV_CANARY not in text, path
        assert "UNRELATED" not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_RUNTIME" in out
    assert ENV_CANARY not in out
    assert _seal_bytes(sealed) == seal_before


def test_live_empty_key_is_the_same_runtime_abort(sealed: Path) -> None:
    code = _main("--live", sealed, env=RecordingEnv({"XAI_API_KEY": ""}))

    assert code == 4
    assert _read_json(sealed / "F/result.json")["run_error"] == "MISSING_API_KEY"
    assert _request_count(sealed) == 0


def test_live_preflight_runs_before_the_key_is_read_and_before_construction(
    sealed: Path,
) -> None:
    """A failing gate with a poisoned env and a poisoned factory: neither is touched."""
    code = _main(
        "--live",
        sealed,
        env=PoisonedEnv(),
        factory=_poisoned_factory,
        git=FakeGit(ancestors=frozenset()),
    )

    assert code == 3
    preflight = _read_json(sealed / "preflight.json")
    assert _gate_table(preflight)["seal_descends_from_frozen_core"]["passed"] is False
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}


# --- live: fake success ---------------------------------------------------------------


def test_live_fake_success_writes_full_tree_and_24_request_records(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = FakeFactory()
    env = RecordingEnv({"XAI_API_KEY": KEY_CANARY, "UNRELATED": ENV_CANARY})
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=env, factory=factory)

    assert code == 0
    assert factory.calls == [KEY_CANARY]
    assert env.reads == ["XAI_API_KEY"]
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    assert _request_count(sealed) == 24
    assert factory.total_requests == 24
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "COMPLETED"
    assert f_result["budget"]["frontier_calls"] == 24
    assert [step["status"] for step in f_result["steps"]] == ["COMPLETED"] * 4
    for t in (1, 2, 3, 4):
        assert _read_json(sealed / f"R/T{t}/result.json")["status"] == "COMPLETED"
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["scientific_decision"] is None
    for path, text in _all_artifact_text(sealed):
        assert KEY_CANARY not in text, path
        assert ENV_CANARY not in text, path
    out = capsys.readouterr().out
    assert "COMPLETED" in out
    assert KEY_CANARY not in out
    assert _seal_bytes(sealed) == seal_before


def test_preflight_only_document_equals_the_live_preflight_json(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main("--preflight-only", sealed) == 0
    printed = json.loads(capsys.readouterr().out)

    assert _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=FakeFactory()) == 0

    assert _read_json(sealed / "preflight.json") == printed


def test_second_live_attempt_refuses_before_construction(sealed: Path) -> None:
    assert _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=FakeFactory()) == 0
    after_first = _dir_snapshot(sealed)

    code = _main(
        "--live",
        sealed,
        env=PoisonedEnv(),
        factory=_poisoned_factory,
        git=FakeGit(dirty="?? would-fail-anyway"),
    )

    assert code == 2
    assert _dir_snapshot(sealed) == after_first


# --- live: failure discipline ---------------------------------------------------------


def test_provider_failure_preserves_earlier_artifacts_and_stops_later_calls(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Schedule position 3 is A T2 (T2 runs A, R, F); its Call 1 is A's third request
    # (index 2). Completed before it: F T1, A T1, R T1 -- six calls; the failed call
    # is the seventh and is itself recorded.
    failure = XAIProviderError(f"provider rejected key {SECRET_SHAPED}")
    factory = FakeFactory(a_failures={2: failure})

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=factory)

    assert code == 4
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_PROVIDER"
    assert f_result["run_error"].startswith("XAIProviderError: provider rejected key ")
    assert SECRET_SHAPED not in f_result["run_error"]
    assert "[REDACTED]" in f_result["run_error"]
    assert [s["status"] for s in f_result["steps"]] == [
        "COMPLETED",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    ]
    a_result = _read_json(sealed / "A/result.json")
    assert [s["status"] for s in a_result["steps"]] == ["COMPLETED", "FAILED", "NOT_RUN", "NOT_RUN"]
    assert [_read_json(sealed / f"R/T{t}/result.json")["status"] for t in (1, 2, 3, 4)] == [
        "COMPLETED",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    ]
    assert len(_read_json(sealed / "F/requests.json")["requests"]) == 2
    assert len(_read_json(sealed / "A/requests.json")["requests"]) == 3
    assert len(_read_json(sealed / "R/T1/requests.json")["requests"]) == 2
    assert len(_read_json(sealed / "R/T2/requests.json")["requests"]) == 0
    assert _request_count(sealed) == 7
    assert factory.total_requests == 7
    assert f_result["budget"]["frontier_calls"] == 7
    for path, text in _all_artifact_text(sealed):
        assert KEY_CANARY not in text, path
        assert SECRET_SHAPED not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_PROVIDER" in out
    assert KEY_CANARY not in out
    assert SECRET_SHAPED not in out


def test_exception_escaping_the_runner_is_recorded_as_aborted_runtime(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(**_kwargs: Any) -> Any:
        raise RuntimeError("session construction failed")

    monkeypatch.setattr(entrypoint, "run_experiment", _explode)
    factory = FakeFactory()

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=factory)

    assert code == 4
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "RuntimeError: session construction failed"
    assert _request_count(sealed) == 0
    assert factory.total_requests == 0


def test_reasoner_construction_failure_is_recorded_as_aborted_runtime(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A factory that raises (client bootstrap, native deps, credential shape) is an
    unhandled runtime failure: recorded, the tree persisted, exit 4 -- never a traceback."""

    def _bootstrap_fails(*, api_key: str) -> tuple[Any, Any, Any]:
        raise RuntimeError(f"client bootstrap failed for key {SECRET_SHAPED}")

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=_bootstrap_fails)

    assert code == 4
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("RuntimeError: client bootstrap failed for key ")
    assert "MISSING" not in f_result["run_error"]
    assert SECRET_SHAPED not in f_result["run_error"]
    assert KEY_CANARY not in f_result["run_error"]
    assert f_result["budget"]["frontier_calls"] == 0
    assert [s["status"] for s in f_result["steps"]] == ["NOT_RUN"] * 4
    assert _request_count(sealed) == 0
    for path, text in _all_artifact_text(sealed):
        assert KEY_CANARY not in text, path
        assert SECRET_SHAPED not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_RUNTIME" in out
    assert KEY_CANARY not in out
    assert SECRET_SHAPED not in out


def test_interrupt_escaping_the_runner_is_preserved_as_aborted_runtime(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _interrupt(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "run_experiment", _interrupt)

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=FakeFactory())

    assert code == 4
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "INTERRUPTED: KeyboardInterrupt"


# --- identity guard (Controller Ruling 7) ---------------------------------------------


def test_in_process_prompt_drift_after_preflight_aborts_before_any_forwarded_call(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entrypoint, "CONTRASTIVE_SYSTEM_INSTRUCTION", "tampered after seal")
    factory = FakeFactory()

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=factory)

    assert code == 4
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "fr_prompt_sha256" in f_result["run_error"]
    assert f_result["budget"]["frontier_calls"] == 0
    assert factory.total_requests == 0
    assert [s["status"] for s in f_result["steps"]] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert _request_count(sealed) == 0  # the guard sits outside the recorder: nothing rendered


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("SYSTEM_INSTRUCTION", "tampered", "a_prompt_sha256"),
        ("POLICY_VERSION", "intent-v2-9p-v5", "a_policy_version"),
        ("CONTRASTIVE_POLICY_VERSION", "intent-v2-9p2-v2", "fr_policy_version"),
        ("MAX_FRONTIER_CALLS", 25, "ceilings"),
        ("MAX_COST_USD", 9.0, "ceilings"),
    ],
)
def test_identity_guard_checks_every_sealed_identity_field(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: object, field: str
) -> None:
    monkeypatch.setattr(entrypoint, name, value)
    factory = FakeFactory()

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=factory)

    assert code == 4
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert field in f_result["run_error"]
    assert factory.total_requests == 0


def test_identity_guard_schema_drift_aborts_before_forwarding(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entrypoint, "semantic_output_schema_sha256", lambda: "0" * 64)
    factory = FakeFactory()

    code = _main("--live", sealed, env={"XAI_API_KEY": KEY_CANARY}, factory=factory)

    assert code == 4
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "output_schema_sha256" in f_result["run_error"]
    assert factory.total_requests == 0


def test_identity_guard_is_transparent_when_identity_holds() -> None:
    from foundry.experiments.contrastive_unseen.runner import (
        ExperimentBudget,
        build_arm_reasoners,
    )

    manifest = build_manifest(harness_code_sha=HARNESS_SHA, spec_sha256=SPEC_SHA).model_dump(
        mode="json"
    )
    budget = ExperimentBudget()
    arms = build_arm_reasoners(
        inner_f=ScriptedReasoner(label="F"),
        inner_a=ScriptedReasoner(label="A"),
        inner_r=ScriptedReasoner(label="R"),
        budget=budget,
    )

    guarded = entrypoint.IdentityGuardReasoner(arms.f, manifest=manifest)

    assert guarded.budget is budget
    assert guarded.recording is arms.f.recording
    assert guarded.fingerprint == arms.f.fingerprint
    assert isinstance(guarded, type(arms.f))


# --- default factory shape (adapters are monkeypatched; nothing real is constructed) ---


def test_default_factory_constructs_f_a_r_with_the_frozen_model_and_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[str, dict[str, Any]]] = []

    class FakeBase:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(("base", kwargs))

    class FakeContrastive:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(("contrastive", kwargs))

    monkeypatch.setattr(entrypoint, "XAISemanticReasoner", FakeBase)
    monkeypatch.setattr(entrypoint, "XAIContrastiveSemanticReasoner", FakeContrastive)

    f, a, r = entrypoint.default_reasoner_factory(api_key="opaque-key")

    assert isinstance(f, FakeContrastive)
    assert isinstance(a, FakeBase)
    assert isinstance(r, FakeContrastive)
    assert [kind for kind, _ in constructed] == ["contrastive", "base", "contrastive"]
    for _, kwargs in constructed:
        assert kwargs == {"api_key": "opaque-key", "model": "grok-4.6", "reasoning_effort": "high"}
