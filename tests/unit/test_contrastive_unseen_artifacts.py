"""9P2 T6: sealed preregistration artifacts, the prepare script, and the write-once raw
artifact writers (spec §11, §16, §17; brief T6; clarifications C3, C4, C5).

Every reasoner here is a scripted fake deriving structurally valid judgments from the
request it is shown; every ledger is a real ``SemanticGovernor`` over an
``InMemoryEventStore``; every git repository the prepare script sees is a throwaway one
created under ``tmp_path``. The only Kestrel wording that flows through these tests is
the runner's own frozen evidence; everything this file authors is opaque. ZERO live
calls; sockets are blocked.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import socket
import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest

import scripts.prepare_contrastive_unseen_lifecycle as prepare
from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    DEFAULT_MODEL,
    POLICY_VERSION,
    PROVIDER,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION_SHA256,
    XAIProviderError,
)
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
from foundry.experiments.contrastive_unseen import artifacts as artifacts_module
from foundry.experiments.contrastive_unseen import integrity
from foundry.experiments.contrastive_unseen.artifacts import (
    DECISION_RESULTS,
    ECONOMY_RULE,
    FINAL_SEAL_RULE,
    PREREGISTRATION_FILE_NAMES,
    RAW_ARTIFACT_PATHS,
    SPEC_PATH,
    ExperimentManifest,
    build_manifest,
    canonical_bytes,
    canonical_sha256,
    existing_raw_artifacts,
    expectations_json,
    pretty_json,
    verdicts_document,
    write_preflight,
    write_preregistration,
    write_run_artifacts,
)
from foundry.experiments.contrastive_unseen.expectations import expectations_document
from foundry.experiments.contrastive_unseen.integrity import (
    EXPERIMENT_ARTIFACT_DIR,
    GRPC_DNS_RESOLVER_FROZEN,
    HISTORICAL_9P_ARTIFACT_DIR,
    REQUIRED_MANIFEST_KEYS,
    V1_ABORT_EVIDENCE_SHA,
    V1_ARTIFACT_DIR,
    GateResult,
    preflight,
)
from foundry.experiments.contrastive_unseen.leakage import (
    LeakageResult,
    needle_set_sha256,
    run_leakage_gate,
)
from foundry.experiments.contrastive_unseen.runner import (
    A_PROJECT_ID,
    F_PROJECT_ID,
    ExperimentBudget,
    RunResult,
    RunStatus,
    StepRecord,
    build_arm_reasoners,
    r_project_id,
    run_experiment,
)
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    EXPERIMENT_VERSION,
    FROZEN_CORE_SHA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    PROJECT_ID,
    SCOPE,
    evidence_records,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 12, tzinfo=UTC)
FR_FINGERPRINT = ReasonerFingerprint(
    provider="fake", model="fake-model", policy_version=CONTRASTIVE_POLICY_VERSION
)
A_FINGERPRINT = ReasonerFingerprint(
    provider="fake", model="fake-model", policy_version=POLICY_VERSION
)
HARNESS_SHA = "a" * 40
SPEC_SHA = "b" * 64
SECRET_TOKEN = "xai-abcdef123456"
HISTORICAL_DIR = Path(HISTORICAL_9P_ARTIFACT_DIR)
V1_DIR = Path("docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1")
"""The sealed v1 experiment directory: immutable historical evidence, read only."""
V1_SHA = "53b7bf15fc51bf573f34efb1d98d370586423097"
ARTIFACTS_SOURCE = Path(artifacts_module.__file__).read_text(encoding="utf-8")
PREPARE_SOURCE = Path(prepare.__file__).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- the §17.2 tree, restated literally --------------------------------------------

_ARM_FILES = (
    "requests.json",
    "drafts.json",
    "receipts.json",
    "decisions.json",
    "authorizations.json",
    "ledger.json",
    "result.json",
)
_R_FILES = (
    "requests.json",
    "drafts.json",
    "receipts.json",
    "decisions.json",
    "ledger.json",
    "result.json",
)
EXPECTED_RAW_PATHS = (
    "preflight.json",
    "verdicts.json",
    "report.md",
    *(f"F/{name}" for name in _ARM_FILES),
    *(f"A/{name}" for name in _ARM_FILES),
    *(f"R/T{t}/{name}" for t in (1, 2, 3, 4) for name in _R_FILES),
)


# --- scripted fakes (the T5 idiom) ---------------------------------------------------


class FakeReceipt(FrozenModel):
    """Adapter-style economics of one scripted call."""

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

    def __init__(self, fingerprint: ReasonerFingerprint) -> None:
        self._fingerprint = fingerprint
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
            reasoner=self._fingerprint,
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
    """Runs ``LifecycleScript`` per call unless an exception is scripted for that call.

    Its fingerprint carries the policy of the arm named by ``label``."""

    def __init__(self, *, label: str, failures: dict[int, BaseException] | None = None) -> None:
        self._label = label
        self._script = LifecycleScript(self.fingerprint)
        self._failures = failures or {}
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[FakeReceipt] = []
        self._drafts: list[str] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return A_FINGERPRINT if self._label == "A" else FR_FINGERPRINT

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


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0 + timedelta(minutes=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _run(
    *,
    f_failures: dict[int, BaseException] | None = None,
    a_failures: dict[int, BaseException] | None = None,
) -> RunResult:
    reasoners = build_arm_reasoners(
        inner_f=ScriptedReasoner(label="F", failures=f_failures),
        inner_a=ScriptedReasoner(label="A", failures=a_failures),
        inner_r=ScriptedReasoner(label="R"),
        budget=ExperimentBudget(),
    )
    clock = _clock()
    return run_experiment(
        reasoner_f=reasoners.f,
        reasoner_a=reasoners.a,
        reasoner_r=reasoners.r,
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


@pytest.fixture(scope="module")
def completed_run() -> RunResult:
    run = _run()
    assert run.status is RunStatus.COMPLETED
    return run


@pytest.fixture(scope="module")
def aborted_run() -> RunResult:
    run = _run(a_failures={0: XAIProviderError(f"provider rejected key {SECRET_TOKEN}")})
    assert run.status is RunStatus.ABORTED_PROVIDER
    return run


@pytest.fixture(scope="module")
def leakage_ok() -> LeakageResult:
    result = run_leakage_gate()
    assert result.passed
    return result


def _manifest() -> ExperimentManifest:
    return build_manifest(harness_code_sha=HARNESS_SHA, spec_sha256=SPEC_SHA)


def _gates(*, failing: str | None = None, detail: str = "ok") -> tuple[GateResult, ...]:
    return tuple(
        GateResult(name=name, passed=name != failing, detail=detail)
        for name in integrity.GATE_NAMES
    )


def _relative_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _step(run: RunResult, arm: str, t: int) -> StepRecord:
    (step,) = [s for s in run.steps if s.arm == arm and s.t == t]
    return step


def _dir_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


# --- throwaway git repositories (local subprocess; never network) ---------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, local repository
        ["git", "-C", str(repo), *args], capture_output=True, check=True, text=True
    ).stdout


def _throwaway_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo whose first commit plays the frozen core and whose HEAD adds harness code."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "opaque@example.invalid")
    _git(repo, "config", "user.name", "opaque")
    _git(repo, "config", "commit.gpgsign", "false")
    spec = repo / SPEC_PATH
    spec.parent.mkdir(parents=True)
    spec.write_text("# opaque spec body\n\nOPAQUE_SPEC_LINE\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "frozen core")
    frozen = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "harness.py").write_text("# opaque harness\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "harness")
    head = _git(repo, "rev-parse", "HEAD").strip()
    return repo, frozen, head


def _prepare(repo: Path, frozen: str, *args: str) -> int:
    return prepare.main(list(args), cwd=repo, frozen_core_sha=frozen)


# --- canonical JSON -------------------------------------------------------------------


def test_canonical_bytes_match_the_brief_and_hash_is_insertion_order_stable() -> None:
    forward = {"b": [1, {"y": 2, "x": 1}], "a": "é", "c": {"k": None}}
    backward = {"c": {"k": None}, "a": "é", "b": [1, {"x": 1, "y": 2}]}

    expected = json.dumps(
        forward, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert canonical_bytes(forward) == expected
    assert canonical_bytes(backward) == expected
    assert canonical_sha256(forward) == canonical_sha256(backward)
    assert canonical_sha256(forward) == hashlib.sha256(expected).hexdigest()

    manifest = _manifest().model_dump(mode="json")
    reversed_manifest = dict(reversed(list(manifest.items())))
    assert list(reversed_manifest) != list(manifest)
    assert canonical_sha256(reversed_manifest) == canonical_sha256(manifest)
    assert canonical_sha256(_manifest()) == canonical_sha256(manifest)


def test_pretty_json_is_indented_sorted_and_newline_terminated() -> None:
    text = pretty_json({"z": 1, "a": "é"})

    assert text == '{\n  "a": "é",\n  "z": 1\n}\n'
    assert canonical_sha256(json.loads(text)) == canonical_sha256({"a": "é", "z": 1})


# --- manifest and expectations ----------------------------------------------------------


def test_expectations_json_hashes_to_the_canonical_expectations_document() -> None:
    text = expectations_json()

    assert text == pretty_json(expectations_document())
    assert text.endswith("\n")
    assert json.loads(text) == expectations_document()
    assert canonical_sha256(json.loads(text)) == canonical_sha256(expectations_document())
    assert _manifest().expectations_sha256 == canonical_sha256(expectations_document())
    assert not artifacts_module.contains_secret_shape(text)


def test_manifest_seals_the_frozen_identity_without_a_self_referential_seal() -> None:
    manifest = _manifest()
    document = manifest.model_dump(mode="json")

    assert isinstance(manifest, FrozenModel)
    assert set(REQUIRED_MANIFEST_KEYS) <= set(document)
    assert document["experiment_version"] == EXPERIMENT_VERSION
    assert document["artifact_format_version"] == 1
    assert document["frozen_core_sha"] == FROZEN_CORE_SHA
    assert document["harness_code_sha"] == HARNESS_SHA
    assert document["final_seal_rule"] == FINAL_SEAL_RULE
    assert FINAL_SEAL_RULE == (
        "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; "
        "parent..HEAD may add only manifest.json and expectations.json"
    )
    assert document["spec_path"] == SPEC_PATH
    assert (
        SPEC_PATH == "docs/superpowers/specs/2026-09-12-9p2-unseen-lifecycle-experiment-design.md"
    )
    assert document["spec_sha256"] == SPEC_SHA
    assert (document["provider"], document["model"], document["reasoning_effort"]) == (
        "xai",
        "grok-4.6",
        "high",
    )
    assert (document["provider"], document["model"]) == (PROVIDER, DEFAULT_MODEL)
    assert document["fr_policy_version"] == CONTRASTIVE_POLICY_VERSION == "intent-v2-9p2-v1"
    assert document["fr_prompt_sha256"] == CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    assert document["fr_prompt_sha256"] == integrity.FR_PROMPT_SHA256_FROZEN
    assert document["a_policy_version"] == POLICY_VERSION == "intent-v2-9p-v4"
    assert document["a_prompt_sha256"] == SYSTEM_INSTRUCTION_SHA256
    assert document["a_prompt_sha256"] == integrity.A_PROMPT_SHA256_FROZEN
    assert document["output_schema_sha256"] == SEMANTIC_OUTPUT_SCHEMA_SHA256
    assert document["output_schema_sha256"] == integrity.OUTPUT_SCHEMA_SHA256_FROZEN
    assert document["arm_schedule"] == [[t, arm] for t, arm in ARM_SCHEDULE]
    assert document["ceilings"] == {
        "max_frontier_calls": MAX_FRONTIER_CALLS,
        "max_judge_calls": MAX_JUDGE_CALLS,
        "max_human_authorizations": MAX_HUMAN_AUTHORIZATIONS,
        "max_cost_usd": MAX_COST_USD,
    }
    assert document["evidence"] == [r.model_dump(mode="json") for r in evidence_records()]
    assert document["economy_rule"] == ECONOMY_RULE
    assert ECONOMY_RULE == "4*F_input_tokens_T2_T4 <= 3*R_input_tokens_T2_T4"
    assert document["decision_results"] == ["PASS", "INCONCLUSIVE", "FAIL"]
    assert DECISION_RESULTS == ("PASS", "INCONCLUSIVE", "FAIL")
    assert document["leakage_needle_set_sha256"] == needle_set_sha256()
    assert document["expectations_sha256"] == canonical_sha256(expectations_document())
    assert document["historical_9p_artifact_dir"] == HISTORICAL_9P_ARTIFACT_DIR
    assert document["lifecycle_project_id"] == PROJECT_ID
    assert document["scope"] == SCOPE
    # v2 operational preregistration: the resolver and the preserved v1 abort evidence.
    assert document["grpc_dns_resolver"] == GRPC_DNS_RESOLVER_FROZEN == "native"
    assert document["v1_abort_evidence_sha"] == V1_ABORT_EVIDENCE_SHA == V1_SHA
    assert document["v1_artifact_dir"] == V1_ARTIFACT_DIR == str(V1_DIR) + "/"
    assert document["predecessor_experiment_version"] == "intent-v2-contrastive-unseen-lifecycle-v1"
    assert document["experiment_version"] == "intent-v2-contrastive-unseen-lifecycle-v2"
    # No self-referential seal: nothing in the manifest names a final seal SHA.
    assert not any("seal_sha" in key for key in document)
    assert FROZEN_CORE_SHA not in (HARNESS_SHA, SPEC_SHA)
    assert all(
        value not in ("", None) for value in document.values() if not isinstance(value, list)
    )


def test_v2_manifest_fields_are_inside_the_canonical_bytes() -> None:
    """The seal hash covers the resolver and the v1 evidence sha: changing either changes
    ``canonical_sha256``; the manifest never derives them from the environment."""
    manifest = _manifest()
    sealed = canonical_sha256(manifest)
    assert canonical_sha256(manifest.model_copy(update={"grpc_dns_resolver": "ares"})) != sealed
    assert (
        canonical_sha256(manifest.model_copy(update={"v1_abort_evidence_sha": "0" * 40})) != sealed
    )
    assert canonical_sha256(_manifest()) == sealed
    for key in (
        "grpc_dns_resolver",
        "v1_abort_evidence_sha",
        "v1_artifact_dir",
        "predecessor_experiment_version",
    ):
        assert key.encode("utf-8") in canonical_bytes(manifest)
    dumped = manifest.model_dump(mode="json")
    with pytest.raises(ValueError, match="v1_abort_evidence_sha"):
        ExperimentManifest.model_validate({**dumped, "v1_abort_evidence_sha": "not-a-sha"})
    with pytest.raises(ValueError, match="grpc_dns_resolver"):
        ExperimentManifest.model_validate({**dumped, "grpc_dns_resolver": ""})


def test_v2_manifest_equals_the_sealed_v1_manifest_on_every_scientific_key() -> None:
    """Byte-identity of the science to v1: rebuilding the manifest against the v1 spec
    hash reproduces every sealed v1 value except the version, the harness HEAD, the
    grading-document hash (which embeds the version literal) and the four v2 keys."""
    v1 = _read_json(V1_DIR / "manifest.json")
    v1_expectations = _read_json(V1_DIR / "expectations.json")
    assert v1["experiment_version"] == "intent-v2-contrastive-unseen-lifecycle-v1"
    assert v1["expectations_sha256"] == canonical_sha256(v1_expectations)

    v2 = build_manifest(harness_code_sha=HARNESS_SHA, spec_sha256=v1["spec_sha256"]).model_dump(
        mode="json"
    )

    new_keys = {
        "grpc_dns_resolver",
        "v1_abort_evidence_sha",
        "v1_artifact_dir",
        "predecessor_experiment_version",
    }
    assert set(v2) == set(v1) | new_keys
    for key in (
        "evidence",
        "arm_schedule",
        "ceilings",
        "fr_prompt_sha256",
        "a_prompt_sha256",
        "fr_policy_version",
        "a_policy_version",
        "output_schema_sha256",
        "leakage_needle_set_sha256",
        "economy_rule",
        "decision_results",
        "frozen_core_sha",
        "spec_path",
        "spec_sha256",
        "provider",
        "model",
        "reasoning_effort",
        "final_seal_rule",
        "artifact_format_version",
        "historical_9p_artifact_dir",
        "lifecycle_project_id",
        "scope",
    ):
        assert v2[key] == v1[key], key
    differing = sorted(key for key in v1 if v1[key] != v2[key])
    assert differing == ["expectations_sha256", "experiment_version", "harness_code_sha"]
    # expectations_sha256 differs ONLY because the grading document carries the version.
    assert v2["expectations_sha256"] == canonical_sha256(
        {**v1_expectations, "experiment_version": "intent-v2-contrastive-unseen-lifecycle-v2"}
    )
    assert v2["predecessor_experiment_version"] == v1["experiment_version"]
    assert v2["v1_abort_evidence_sha"] == V1_SHA
    assert v2["v1_artifact_dir"] == str(V1_DIR) + "/"


class _FakeGit:
    """Only what the manifest-reading gates need; the git-facing gates are not under test."""

    def head(self) -> str:
        return "c" * 40

    def dirty(self) -> str:
        return ""

    def parents(self, sha: str) -> tuple[str, ...]:
        return (HARNESS_SHA,)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return True

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        return ()

    def show_bytes(self, sha: str, path: str) -> bytes:
        return b""


class _FakeCommands:
    def run(self, argv: tuple[str, ...]) -> tuple[int, str]:
        return 0, "fake"


def test_written_manifest_passes_every_manifest_reading_preflight_gate(
    tmp_path: Path, leakage_ok: LeakageResult
) -> None:
    hashes = write_preregistration(tmp_path, _manifest())
    manifest = _read_json(tmp_path / "manifest.json")
    package = Path(artifacts_module.__file__).parent
    sources = {
        name: (package / name).read_text(encoding="utf-8")
        for name in integrity.REQUIRED_REQUEST_PATH_MODULES
    }

    results = preflight(
        git=_FakeGit(),
        commands=_FakeCommands(),
        frozen_sha="c" * 40,
        manifest=manifest,
        expectations_bytes=(tmp_path / "expectations.json").read_bytes(),
        request_path_sources=sources,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )

    by_name = {r.name: r for r in results}
    for name in (
        "grpc_dns_resolver_is_native",
        "v1_abort_artifacts_unchanged",
        "fr_policy_is_9p2",
        "fr_prompt_hash_frozen",
        "a_policy_is_9p",
        "a_prompt_hash_frozen",
        "output_schema_hash_frozen",
        "evidence_manifest_frozen",
        "arm_schedule_frozen",
        "ceilings_frozen",
        "answer_key_not_imported_by_request_path",
        "contrastive_leakage_gate_passes",
    ):
        assert by_name[name].passed, by_name[name].detail
    assert hashes["expectations.json"] == manifest["expectations_sha256"]


def test_write_preregistration_writes_exactly_two_files_and_refuses_to_overwrite(
    tmp_path: Path,
) -> None:
    manifest = _manifest()

    hashes = write_preregistration(tmp_path, manifest)

    assert PREREGISTRATION_FILE_NAMES == ("manifest.json", "expectations.json")
    assert _relative_files(tmp_path) == {"manifest.json", "expectations.json"}
    manifest_text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert manifest_text == pretty_json(manifest.model_dump(mode="json"))
    assert (tmp_path / "expectations.json").read_text(encoding="utf-8") == expectations_json()
    assert hashes == {
        "manifest.json": canonical_sha256(json.loads(manifest_text)),
        "expectations.json": canonical_sha256(expectations_document()),
    }
    before = _dir_snapshot(tmp_path)
    with pytest.raises(FileExistsError):
        write_preregistration(tmp_path, manifest)
    assert _dir_snapshot(tmp_path) == before

    other = tmp_path / "other"
    other.mkdir()
    (other / "expectations.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_preregistration(other, manifest)
    assert _relative_files(other) == {"expectations.json"}


def test_write_preregistration_refuses_a_manifest_whose_expectations_hash_drifted(
    tmp_path: Path,
) -> None:
    drifted = _manifest().model_copy(update={"expectations_sha256": "0" * 64})

    with pytest.raises(ValueError, match="expectations_sha256"):
        write_preregistration(tmp_path, drifted)
    assert _relative_files(tmp_path) == set()


# --- prepare script ------------------------------------------------------------------------


def test_prepare_default_out_and_frozen_core_are_the_frozen_literals() -> None:
    parser = prepare.build_parser()
    args = parser.parse_args([])

    assert args.out == "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2"
    assert args.out == prepare.DEFAULT_OUT
    assert prepare.DEFAULT_OUT + "/" == EXPERIMENT_ARTIFACT_DIR
    assert not prepare.DEFAULT_OUT.endswith("/")
    signature = inspect.signature(prepare.main)
    assert signature.parameters["frozen_core_sha"].default == FROZEN_CORE_SHA
    assert signature.parameters["frozen_core_sha"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["cwd"].kind is inspect.Parameter.KEYWORD_ONLY


def test_prepare_refuses_a_dirty_worktree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, frozen, _head = _throwaway_repo(tmp_path)
    (repo / "stray.txt").write_text("opaque\n", encoding="utf-8")

    code = _prepare(repo, frozen, "--out", "out")

    assert code == 2
    assert "dirty" in capsys.readouterr().out.casefold()
    assert not (repo / "out").exists()


def test_prepare_refuses_when_head_does_not_descend_from_frozen_core(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _frozen, _head = _throwaway_repo(tmp_path)

    code = _prepare(repo, "f" * 40, "--out", "out")

    assert code == 2
    assert "frozen core" in capsys.readouterr().out.casefold()
    assert not (repo / "out").exists()


@pytest.mark.parametrize("existing", ["manifest.json", "expectations.json"])
def test_prepare_refuses_existing_preregistration_files(
    tmp_path: Path, existing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, frozen, _head = _throwaway_repo(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / existing).write_text("opaque\n", encoding="utf-8")

    code = _prepare(repo, frozen, "--out", str(out))

    assert code == 2
    assert existing in capsys.readouterr().out
    assert _relative_files(out) == {existing}
    assert (out / existing).read_text(encoding="utf-8") == "opaque\n"


def test_prepare_refuses_when_working_tree_spec_differs_from_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, frozen, _head = _throwaway_repo(tmp_path)
    spec = repo / SPEC_PATH
    spec.write_text("# drifted opaque spec\n", encoding="utf-8")
    # Hide the drift from ``status --porcelain`` so only the byte comparison can catch it.
    _git(repo, "update-index", "--assume-unchanged", SPEC_PATH)
    assert _git(repo, "status", "--porcelain").strip() == ""

    code = _prepare(repo, frozen, "--out", "out")

    assert code == 2
    assert "spec" in capsys.readouterr().out.casefold()
    assert not (repo / "out").exists()


def test_prepare_writes_exactly_two_files_sealing_the_pre_artifact_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, frozen, head = _throwaway_repo(tmp_path)
    spec_bytes = (repo / SPEC_PATH).read_bytes()

    code = _prepare(repo, frozen, "--out", "out/experiment")

    assert code == 0
    out = repo / "out" / "experiment"
    assert _relative_files(out) == {"manifest.json", "expectations.json"}
    manifest = _read_json(out / "manifest.json")
    assert manifest["harness_code_sha"] == head
    assert manifest["frozen_core_sha"] == FROZEN_CORE_SHA
    assert manifest["spec_sha256"] == hashlib.sha256(spec_bytes).hexdigest()
    assert manifest["expectations_sha256"] == canonical_sha256(
        _read_json(out / "expectations.json")
    )
    # The script sealed the pre-artifact HEAD and committed nothing.
    assert _git(repo, "rev-parse", "HEAD").strip() == head
    assert sorted(line[3:] for line in _git(repo, "status", "--porcelain").splitlines()) == ["out/"]
    printed = capsys.readouterr().out
    assert f"manifest.json {canonical_sha256(manifest)}" in printed
    assert f"expectations.json {manifest['expectations_sha256']}" in printed


def test_prepare_uses_only_the_four_read_only_git_commands_and_no_reasoner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, frozen, _head = _throwaway_repo(tmp_path)
    seen: list[tuple[str, ...]] = []
    real_run = subprocess.run

    def _spy(argv: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(tuple(argv))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(prepare.subprocess, "run", _spy)

    assert _prepare(repo, frozen, "--out", "out") == 0

    subcommands = [argv[argv.index(str(repo)) + 1] for argv in seen]
    assert all(argv[0] == "git" for argv in seen)
    assert set(subcommands) == {"status", "rev-parse", "merge-base", "show"}
    assert [a for a in seen if a[-2:] == ("status", "--porcelain")]
    assert [a for a in seen if a[-2:] == ("rev-parse", "HEAD")]
    assert [a for a in seen if "--is-ancestor" in a and frozen in a]
    assert [a for a in seen if a[-1] == f"HEAD:{SPEC_PATH}"]

    tree = ast.parse(PREPARE_SOURCE)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "XAISemanticReasoner" not in names
    assert "XAIContrastiveSemanticReasoner" not in names
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(m in {"socket", "httpx", "urllib", "requests", "xai_sdk"} for m in imported)
    assert "XAI_API_KEY" not in PREPARE_SOURCE


# --- raw artifact writers ------------------------------------------------------------------


def test_raw_artifact_paths_restate_the_spec_tree() -> None:
    assert RAW_ARTIFACT_PATHS == EXPECTED_RAW_PATHS
    assert len(set(RAW_ARTIFACT_PATHS)) == len(RAW_ARTIFACT_PATHS)


def test_raw_writers_create_exactly_the_spec_tree(
    tmp_path: Path, completed_run: RunResult, leakage_ok: LeakageResult
) -> None:
    assert existing_raw_artifacts(tmp_path) == ()
    write_preflight(
        tmp_path,
        _gates(),
        frozen_sha="c" * 40,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    write_run_artifacts(tmp_path, completed_run)

    assert _relative_files(tmp_path) == set(EXPECTED_RAW_PATHS)
    assert existing_raw_artifacts(tmp_path) == RAW_ARTIFACT_PATHS
    preflight_document = _read_json(tmp_path / "preflight.json")
    assert preflight_document["all_passed"] is True
    assert preflight_document["run_status"] is None
    assert preflight_document["frontier_calls"] == 0
    assert [g["name"] for g in preflight_document["gates"]] == list(integrity.GATE_NAMES)
    assert len(preflight_document["gates"]) == 22
    assert preflight_document["frozen_sha"] == "c" * 40
    assert preflight_document["observed_grpc_dns_resolver"] == "native"
    assert preflight_document["leakage"] == leakage_ok.model_dump(mode="json")
    for name in RAW_ARTIFACT_PATHS:
        if name.endswith(".json"):
            _read_json(tmp_path / name)


@pytest.mark.parametrize("observed", [None, "", "ares", "Native", "native"])
def test_preflight_json_records_the_observed_resolver_verbatim(
    tmp_path: Path, leakage_ok: LeakageResult, observed: str | None
) -> None:
    """The observed value is recorded as handed in -- never stripped, cased or defaulted
    -- so a failed gate 21 is auditable from the artifact alone."""
    gates = _gates(failing=None if observed == "native" else "grpc_dns_resolver_is_native")

    write_preflight(
        tmp_path,
        gates,
        frozen_sha="c" * 40,
        leakage=leakage_ok,
        observed_grpc_dns_resolver=observed,
    )

    document = _read_json(tmp_path / "preflight.json")
    assert document["observed_grpc_dns_resolver"] == observed
    assert document["frontier_calls"] == 0
    assert document["all_passed"] is (observed == "native")


def test_arm_and_step_results_carry_the_raw_structural_record(
    tmp_path: Path, completed_run: RunResult
) -> None:
    write_run_artifacts(tmp_path, completed_run)

    f_result = _read_json(tmp_path / "F" / "result.json")
    assert f_result["arm"] == "F"
    assert f_result["project_id"] == F_PROJECT_ID
    assert f_result["run_status"] == "COMPLETED"
    assert [s["status"] for s in f_result["steps"]] == ["COMPLETED"] * 4
    assert [s["t"] for s in f_result["steps"]] == [1, 2, 3, 4]
    assert f_result["steps"][0]["evidence_ids_shown"] == ["EV-K-A1", "EV-K-B1", "EV-K-N1"]
    assert set(f_result["roots"]) == {"A", "B", "N"}
    assert all(root["status"] == "DESIGNATED" for root in f_result["roots"].values())
    assert f_result["replay"]["status"] == "REPLAY_MATCH"
    assert f_result["budget"] == completed_run.budget.model_dump(mode="json")
    calls = f_result["steps"][1]["calls"]
    assert [c["call_number"] for c in calls] == [1, 2]
    assert calls[0]["receipt"]["input_tokens"] == 102
    assert calls[0]["economics"] == {
        "input_tokens": 102,
        "output_tokens": 12,
        "cost_usd": 0.01,
        "wall_clock_ms": 5,
        "draft_count": 1,
    }
    assert f_result["final_state"] == completed_run.f.final_state.model_dump(mode="json")
    assert f_result["final_view"] == completed_run.f.final_view.model_dump(mode="json")

    a_result = _read_json(tmp_path / "A" / "result.json")
    assert a_result["replay"] is None
    assert a_result["project_id"] == A_PROJECT_ID

    ledger = _read_json(tmp_path / "F" / "ledger.json")
    assert ledger["project_id"] == F_PROJECT_ID
    assert ledger["event_count"] == len(completed_run.f.ledger)
    assert ledger["events"] == [e.model_dump(mode="json") for e in completed_run.f.ledger]

    authorizations = _read_json(tmp_path / "F" / "authorizations.json")
    assert authorizations["records"] == [
        a.model_dump(mode="json") for a in completed_run.f.authorizations
    ]
    decisions = _read_json(tmp_path / "F" / "decisions.json")
    assert [len(s["stage_decisions"]) for s in decisions["steps"]] == [2] * 4
    drafts = _read_json(tmp_path / "F" / "drafts.json")
    assert [d["payload"] for d in drafts["drafts"]][:2] == ["draft:F:1", "draft:F:2"]
    receipts = _read_json(tmp_path / "F" / "receipts.json")
    assert len(receipts["receipts"]) == 8

    for t in (1, 2, 3, 4):
        step = completed_run.r_steps[t]
        result = _read_json(tmp_path / "R" / f"T{t}" / "result.json")
        assert result["arm"] == "R"
        assert result["t"] == t
        assert result["project_id"] == r_project_id(t)
        assert result["status"] == "COMPLETED"
        assert result["evidence_ids_shown"] == list(step.evidence_ids_shown)
        assert result["state_snapshot"] == step.state_snapshot.model_dump(mode="json")  # type: ignore[union-attr]
        assert [c["call_number"] for c in result["calls"]] == [1, 2]
        r_ledger = _read_json(tmp_path / "R" / f"T{t}" / "ledger.json")
        assert r_ledger["project_id"] == r_project_id(t)
        assert r_ledger["event_count"] == len(step.ledger)


def test_not_run_and_failed_cells_are_written_never_omitted(
    tmp_path: Path, aborted_run: RunResult
) -> None:
    write_run_artifacts(tmp_path, aborted_run)

    assert _relative_files(tmp_path) == set(EXPECTED_RAW_PATHS) - {"preflight.json"}
    for t in (1, 2, 3, 4):
        result = _read_json(tmp_path / "R" / f"T{t}" / "result.json")
        assert result["status"] == "NOT_RUN"
        assert result["error"] is None
        assert result["calls"] == []
        assert result["evidence_ids_shown"] == []
        assert result["state_snapshot"] is None
        assert _read_json(tmp_path / "R" / f"T{t}" / "requests.json")["requests"] == []
        assert _read_json(tmp_path / "R" / f"T{t}" / "ledger.json")["events"] == []
    a_result = _read_json(tmp_path / "A" / "result.json")
    assert a_result["run_status"] == "ABORTED_PROVIDER"
    assert [s["status"] for s in a_result["steps"]] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert a_result["steps"][0]["error"] is not None
    f_result = _read_json(tmp_path / "F" / "result.json")
    assert [s["status"] for s in f_result["steps"]] == [
        "COMPLETED",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    ]


def test_raw_writers_refuse_to_overwrite_any_existing_raw_path(
    tmp_path: Path, completed_run: RunResult, leakage_ok: LeakageResult
) -> None:
    write_preflight(
        tmp_path,
        _gates(failing="worktree_clean"),
        frozen_sha="c" * 40,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    failed_preflight = _read_json(tmp_path / "preflight.json")
    assert failed_preflight["all_passed"] is False
    assert failed_preflight["run_status"] == "ABORTED_PREFLIGHT"  # spec §14.1
    assert failed_preflight["frontier_calls"] == 0
    before = _dir_snapshot(tmp_path)

    with pytest.raises(FileExistsError, match="preflight.json"):
        write_preflight(
            tmp_path,
            _gates(),
            frozen_sha="c" * 40,
            leakage=leakage_ok,
            observed_grpc_dns_resolver="native",
        )
    assert _dir_snapshot(tmp_path) == before  # the failed preflight is preserved
    assert existing_raw_artifacts(tmp_path) == ("preflight.json",)

    stray = tmp_path / "R" / "T3" / "ledger.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("opaque\n", encoding="utf-8")
    before = _dir_snapshot(tmp_path)
    with pytest.raises(FileExistsError, match="R/T3/ledger.json"):
        write_run_artifacts(tmp_path, completed_run)
    assert _dir_snapshot(tmp_path) == before

    stray.unlink()
    write_run_artifacts(tmp_path, completed_run)
    before = _dir_snapshot(tmp_path)
    with pytest.raises(FileExistsError):
        write_run_artifacts(tmp_path, completed_run)
    assert _dir_snapshot(tmp_path) == before


def test_requests_preserve_exact_rendered_text_and_hash(
    tmp_path: Path, completed_run: RunResult
) -> None:
    write_run_artifacts(tmp_path, completed_run)

    for arm, summary in (("F", completed_run.f), ("A", completed_run.a)):
        document = _read_json(tmp_path / arm / "requests.json")
        assert document["arm"] == arm
        assert len(document["requests"]) == 8
        for written, record in zip(document["requests"], summary.requests, strict=True):
            assert written == record.model_dump(mode="json")
            assert written["rendered_user_request"] == record.rendered_user_request
            assert (
                hashlib.sha256(written["rendered_user_request"].encode("utf-8")).hexdigest()
                == written["request_sha256"]
                == record.request_sha256
            )
            assert json.loads(written["rendered_user_request"])  # the exact request JSON
        assert [(r["t"], r["call_number"]) for r in document["requests"]] == [
            (t, c) for t in (1, 2, 3, 4) for c in (1, 2)
        ]
    for t in (1, 2, 3, 4):
        document = _read_json(tmp_path / "R" / f"T{t}" / "requests.json")
        records = completed_run.r_steps[t].requests
        assert document["requests"] == [r.model_dump(mode="json") for r in records]
        assert [r["call_number"] for r in document["requests"]] == [1, 2]


def test_secret_shapes_are_redacted_from_error_text_and_never_persist(
    tmp_path: Path, aborted_run: RunResult, leakage_ok: LeakageResult
) -> None:
    assert SECRET_TOKEN in (aborted_run.error or "")
    gates = _gates(failing="track_a_regression_passes", detail=f"auth failed for {SECRET_TOKEN}")

    write_preflight(
        tmp_path,
        gates,
        frozen_sha="c" * 40,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    write_run_artifacts(tmp_path, aborted_run)

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET_TOKEN not in path.read_text(encoding="utf-8"), path
    verdicts = _read_json(tmp_path / "verdicts.json")
    assert "[REDACTED]" in verdicts["operational_error"]
    assert verdicts["operational_error"].startswith("XAIProviderError: provider rejected key ")
    a_result = _read_json(tmp_path / "A" / "result.json")
    assert "[REDACTED]" in a_result["steps"][0]["error"]
    preflight_document = _read_json(tmp_path / "preflight.json")
    failing = [g for g in preflight_document["gates"] if not g["passed"]]
    assert failing and "[REDACTED]" in failing[0]["detail"]
    assert "[REDACTED]" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_a_secret_shape_inside_a_rendered_request_makes_writing_fail(
    tmp_path: Path, completed_run: RunResult
) -> None:
    f_t2 = _step(completed_run, "F", 2)
    poisoned_record = f_t2.requests[0].model_copy(
        update={"rendered_user_request": f'{{"api_key": "{SECRET_TOKEN}"}}'}
    )
    poisoned_step = f_t2.model_copy(update={"requests": (poisoned_record, f_t2.requests[1])})
    steps = tuple(poisoned_step if s is f_t2 else s for s in completed_run.steps)
    poisoned = completed_run.model_copy(update={"steps": steps})

    with pytest.raises(ValueError, match="rendered_user_request"):
        write_run_artifacts(tmp_path, poisoned)
    assert _relative_files(tmp_path) == set()

    summary_record = completed_run.f.requests[2].model_copy(
        update={"rendered_user_request": f"Authorization: Bearer {SECRET_TOKEN}"}
    )
    summary = completed_run.f.model_copy(
        update={
            "requests": (
                *completed_run.f.requests[:2],
                summary_record,
                *completed_run.f.requests[3:],
            )
        }
    )
    with pytest.raises(ValueError, match="rendered_user_request"):
        write_run_artifacts(tmp_path, completed_run.model_copy(update={"f": summary}))
    assert _relative_files(tmp_path) == set()


# --- verdicts (C3 / C5) ----------------------------------------------------------------------


def test_raw_verdicts_carry_only_deterministic_f_checks_and_no_scientific_decision(
    tmp_path: Path, completed_run: RunResult
) -> None:
    write_run_artifacts(tmp_path, completed_run)
    verdicts = _read_json(tmp_path / "verdicts.json")

    assert verdicts == verdicts_document(completed_run)
    assert verdicts["operational_status"] == "COMPLETED"
    assert verdicts["operational_error"] is None
    assert verdicts["scientific_decision"] is None
    integrity_verdicts = verdicts["integrity"]
    assert list(integrity_verdicts) == ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
    assert integrity_verdicts["F2"]["passed"] is None
    for fid in ("F1", "F3", "F4", "F5", "F6", "F7", "F8"):
        assert integrity_verdicts[fid]["passed"] is True, (fid, integrity_verdicts[fid])
        assert isinstance(integrity_verdicts[fid]["detail"], str)
    assert verdicts["semantic_checkpoints"] == {
        arm: {"C1": None, "C2": None, "C3": None} for arm in ("F", "A", "R")
    }
    assert verdicts["material_errors"] == {"F": None, "A": None, "R": None}
    assert verdicts["adjudication"] == "architect adjudication pending"
    # The module never reaches for the decision rule or a semantic grade.
    tree = ast.parse(ARTIFACTS_SOURCE)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "decision_rule" not in names
    assert "DecisionInputs" not in names


def test_aborted_run_verdicts_are_all_null_with_the_operational_status(
    tmp_path: Path, aborted_run: RunResult
) -> None:
    write_run_artifacts(tmp_path, aborted_run)
    verdicts = _read_json(tmp_path / "verdicts.json")

    assert verdicts["operational_status"] == "ABORTED_PROVIDER"
    assert all(v["passed"] is None for v in verdicts["integrity"].values())
    assert verdicts["scientific_decision"] is None
    assert verdicts["material_errors"] == {"F": None, "A": None, "R": None}
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "scientific_decision = null (architect adjudication pending)" in report
    assert "ABORTED_PROVIDER" in report


def _with_f_requests(run: RunResult, requests: tuple[Any, ...]) -> RunResult:
    return run.model_copy(update={"f": run.f.model_copy(update={"requests": requests})})


def _with_f_step(run: RunResult, t: int, **update: Any) -> RunResult:
    original = _step(run, "F", t)
    replaced = original.model_copy(update=update)
    return run.model_copy(
        update={"steps": tuple(replaced if s is original else s for s in run.steps)}
    )


def test_f1_fails_when_two_roots_share_an_address_id(completed_run: RunResult) -> None:
    roots = dict(completed_run.f.roots)
    roots["B"] = roots["B"].model_copy(update={"address_id": roots["A"].address_id})
    run = completed_run.model_copy(
        update={"f": completed_run.f.model_copy(update={"roots": roots})}
    )

    assert verdicts_document(run)["integrity"]["F1"]["passed"] is False

    roots["B"] = completed_run.f.roots["B"].model_copy(
        update={"status": "UNDESIGNATED", "address_id": None}
    )
    run = completed_run.model_copy(
        update={"f": completed_run.f.model_copy(update={"roots": roots})}
    )
    assert verdicts_document(run)["integrity"]["F1"]["passed"] is False


def test_f3_fails_on_a_widened_kind_set_or_a_third_request(completed_run: RunResult) -> None:
    widened = completed_run.f.requests[0].model_copy(
        update={"allowed_judgment_kinds": ("BIND_TO_ADDRESS", "CREATE_ADDRESS", "EQUIVALENT")}
    )
    run = _with_f_requests(completed_run, (widened, *completed_run.f.requests[1:]))
    assert verdicts_document(run)["integrity"]["F3"]["passed"] is False

    third = completed_run.f.requests[3]
    run = _with_f_requests(completed_run, (*completed_run.f.requests, third))
    assert verdicts_document(run)["integrity"]["F3"]["passed"] is False
    assert verdicts_document(run)["integrity"]["F6"]["passed"] is False


def test_f4_fails_when_a_proposal_cites_an_id_outside_that_requests_evidence(
    completed_run: RunResult,
) -> None:
    f_t2 = _step(completed_run, "F", 2)
    call_two = f_t2.requests[1].model_copy(update={"citable_evidence_ids": ("EV-K-A1",)})
    run = _with_f_step(completed_run, 2, requests=(f_t2.requests[0], call_two))

    assert verdicts_document(run)["integrity"]["F4"]["passed"] is False


def test_f5_fails_on_an_out_of_scope_known_address(completed_run: RunResult) -> None:
    f_t2 = _step(completed_run, "F", 2)
    rendered = json.loads(f_t2.requests[0].rendered_user_request)
    assert rendered["known_addresses"]
    rendered["known_addresses"][0]["scope"] = ["other-scope"]
    widened = f_t2.requests[0].model_copy(
        update={"rendered_user_request": json.dumps(rendered, separators=(",", ":"))}
    )
    run = _with_f_step(completed_run, 2, requests=(widened, f_t2.requests[1]))

    assert verdicts_document(run)["integrity"]["F5"]["passed"] is False


def test_f6_fails_when_a_call_is_missing_or_duplicated(completed_run: RunResult) -> None:
    run = _with_f_requests(completed_run, completed_run.f.requests[:7])
    assert verdicts_document(run)["integrity"]["F6"]["passed"] is False

    duplicated = (*completed_run.f.requests[:7], completed_run.f.requests[6])
    run = _with_f_requests(completed_run, duplicated)
    assert verdicts_document(run)["integrity"]["F6"]["passed"] is False


def test_f7_reports_the_replay_result(completed_run: RunResult) -> None:
    replay = completed_run.f.replay
    assert replay is not None
    mismatched = replay.model_copy(update={"status": "REPLAY_MISMATCH", "state_matches": False})
    run = completed_run.model_copy(
        update={"f": completed_run.f.model_copy(update={"replay": mismatched})}
    )

    assert verdicts_document(run)["integrity"]["F7"]["passed"] is False


def test_f8_fails_when_a_model_supersede_is_the_applied_judgment(
    completed_run: RunResult,
) -> None:
    state = completed_run.f.final_state
    model_supersede_ids = [
        judgment_id
        for judgment_id, judgment in state.semantic.judgments.items()
        if isinstance(judgment.proposal, SupersedeProposal) and not judgment.reasoner.is_human
    ]
    assert model_supersede_ids
    semantic = state.semantic.model_copy(
        update={
            "applied_judgment_ids": (*state.semantic.applied_judgment_ids, model_supersede_ids[0])
        }
    )
    run = completed_run.model_copy(
        update={
            "f": completed_run.f.model_copy(
                update={"final_state": state.model_copy(update={"semantic": semantic})}
            )
        }
    )

    assert verdicts_document(run)["integrity"]["F8"]["passed"] is False


# --- report -----------------------------------------------------------------------------


def test_report_summarises_the_run_and_names_the_pending_adjudication(
    tmp_path: Path, completed_run: RunResult
) -> None:
    write_run_artifacts(tmp_path, completed_run)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "scientific_decision = null (architect adjudication pending)" in report
    assert "COMPLETED" in report
    for position, (t, arm) in enumerate(ARM_SCHEDULE):
        assert f"| {position} | T{t} | {arm} | COMPLETED |" in report
    assert f"frontier_calls: {completed_run.budget.frontier_calls}" in report
    for fid in ("F1", "F3", "F8"):
        assert f"| {fid} |" in report
    assert "| F2 | null |" in report
    assert F_PROJECT_ID in report and A_PROJECT_ID in report


# --- the historical 9P artifact directory is never touched --------------------------------


def test_no_previous_9p_artifact_path_is_touched(tmp_path: Path, completed_run: RunResult) -> None:
    assert HISTORICAL_DIR.is_dir(), "the historical 9P artifact directory must exist to guard"
    before = _dir_snapshot(HISTORICAL_DIR)
    assert before
    repo, frozen, _head = _throwaway_repo(tmp_path)

    assert _prepare(repo, frozen, "--out", "out") == 0
    write_run_artifacts(tmp_path / "raw", completed_run)

    assert _dir_snapshot(HISTORICAL_DIR) == before
    assert os.path.commonpath([HISTORICAL_DIR.resolve(), tmp_path.resolve()]) != str(
        HISTORICAL_DIR.resolve()
    )
    assert _manifest().historical_9p_artifact_dir == str(HISTORICAL_DIR) + "/"
