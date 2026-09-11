"""Immutable artifact schema and entry point for the 9P longitudinal dogfood (Task 16).

The artifact set is the declared pre-run / post-run file lists and nothing else; every
write is atomic and refuses to overwrite; no artifact carries a secret; the entry point
stops before an ``XAISemanticReasoner`` is constructed on any failed gate or missing key.
The only reasoner here is scripted and injected through ``reasoner_factory``; Git is a
fake keyed by ``(commit, path)``; stdin is a scripted stream. ZERO live calls.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import scripts.run_longitudinal_dogfood as script
from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    SYSTEM_INSTRUCTION,
    SemanticDraftPayload,
    SemanticReasoningReceipt,
)
from foundry.application.semantic_reducer import address_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.evaluation.experiment_manifest import canonical_json_bytes, sha256_bytes
from foundry.experiments.longitudinal import artifacts
from foundry.experiments.longitudinal.arm_f import PROJECT_ID, run_arm_f
from foundry.experiments.longitudinal.arm_r import run_arm_r
from foundry.experiments.longitudinal.artifacts import (
    EXPERIMENT_DIR_NAME,
    POST_RUN_FILES,
    PRE_RUN_FILES,
    LongitudinalRun,
    assemble_run,
    build_expectation_manifest,
    build_expectations_document,
    build_pre_run_manifest,
    default_run_config,
    fill_t1_designation,
    render_report,
    system_instruction_sha256,
    write_post_run_artifacts,
    write_pre_run_artifacts,
)
from foundry.experiments.longitudinal.authority import AuthorizationDecision
from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    TRACKED_LOCI,
    ExpectationManifest,
    seal,
)
from foundry.experiments.longitudinal.scoring import (
    ScoringManifest,
    deterministic_verdicts,
    structural_metrics,
)
from foundry.experiments.longitudinal.timeline import (
    VersionedEvidence,
    evidence_hashes,
    load_timeline,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 11, tzinfo=UTC)
FROZEN_SHA = "f" * 40
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="9p-v1")
SCOPE = "intent-engine"
SCOPES = ("intent-engine", "constitution")

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"

J_CREATE_A = "J-T1-create-A"
J_CREATE_B = "J-T1-create-B"
J_CREATE_N = "J-T1-create-N"
J_CLAIM_A = "J-T1-claim-A"
J_CLAIM_B = "J-T1-claim-B"
J_CLAIM_N = "J-T1-claim-N"
J_BIND_A = "J-T2-bind-A"
J_CLAIM_A_NEW = "J-T2-claim-A-new"
J_SUPERSEDE_A = "J-T2-supersede-A"
J_CREATE_C = "J-T3-create-C"
J_CLAIM_C = "J-T3-claim-C"
J_BIND_C = "J-T4-bind-C"
J_CLAIM_C_NEW = "J-T4-claim-C-new"

ADDR_A = address_id_for(PROJECT_ID, J_CREATE_A)
ADDR_B = address_id_for(PROJECT_ID, J_CREATE_B)
ADDR_N = address_id_for(PROJECT_ID, J_CREATE_N)
ADDR_C = address_id_for(PROJECT_ID, J_CREATE_C)

FAKE_KEY = "xai-TESTKEY000000000000000000"

type Batch = (
    list[SemanticJudgment] | Callable[[ReasoningRequest], list[SemanticJudgment]] | BaseException
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _never_construct_the_adapter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every test in this module proves the real adapter is never constructed."""
    constructed: list[str] = []

    class Forbidden:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed.append("constructed")
            raise AssertionError("XAISemanticReasoner must never be constructed in tests")

    monkeypatch.setattr(xai_reasoner, "XAISemanticReasoner", Forbidden)
    return constructed


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    """Serves bytes for exact ``(commit, path)`` pairs; HEAD and status are scripted."""

    def __init__(
        self, blobs: dict[tuple[str, str], bytes], *, head: str = FROZEN_SHA, dirty: str = ""
    ) -> None:
        self._blobs = blobs
        self._head = head
        self._dirty = dirty

    def blob(self, sha: str, path: str) -> bytes:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return self._blobs[(sha, path)]

    def blob_sha(self, sha: str, path: str) -> str:
        return hashlib.sha1(b"blob " + self.blob(sha, path)).hexdigest()

    def head(self) -> str:
        return self._head

    def dirty(self) -> str:
        return self._dirty

    def branch(self) -> str:
        return "fake"


class ScriptedReasoner:
    """One scripted batch per call; exposes receipts and drafts like the adapter."""

    def __init__(
        self,
        batches: list[Batch],
        *,
        on_call: Callable[[int, ReasoningRequest], None] | None = None,
    ) -> None:
        self._batches = batches
        self._on_call = on_call
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[SemanticReasoningReceipt] = []
        self._drafts: list[SemanticDraftPayload] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return MODEL

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[SemanticDraftPayload, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if self._on_call is not None:
            self._on_call(index + 1, request)
        self._receipts.append(
            SemanticReasoningReceipt(
                invocation_id=f"INV-{index + 1}",
                model="grok-4.6",
                reasoning_effort="high",
                input_tokens=100 * len(request.evidence),
                output_tokens=7,
                cost_usd=0.25,
                wall_clock_ms=1,
                draft_count=0,
            )
        )
        self._drafts.append(SemanticDraftPayload(drafts=()))
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        if callable(batch):
            return tuple(batch(request))
        return tuple(batch)


class ScriptedAuthorizer:
    def __init__(self, answers: list[AuthorizationDecision]) -> None:
        self._answers = answers
        self.presented: list[SemanticJudgment] = []

    def __call__(self, pending: SemanticJudgment) -> AuthorizationDecision:
        self.presented.append(pending)
        return self._answers[len(self.presented) - 1]


# --- builders ---------------------------------------------------------------------


def _blobs() -> dict[tuple[str, str], bytes]:
    return {
        (T1, CONSTITUTION): b"constitution v1\n",
        (T1, SPEC): b"spec v1\n",
        (T2, SPEC): b"spec v2\n",
        (T3, REDUCER): b"reducer v1\n",
        (T3, IDENTITY): b"identity v1\n",
        (T4, REDUCER): b"reducer v2\n",
        (T4, SPEC): b"spec v3\n",
    }


def _timeline() -> tuple[VersionedEvidence, ...]:
    return load_timeline(
        FakeGit(_blobs()), project_id="PROJ-9P", observed_at_for=lambda t: T0 + timedelta(days=t)
    )


def _clock() -> Callable[[], datetime]:
    ticks = iter(range(10_000))
    return lambda: T0 + timedelta(minutes=next(ticks))


def _id_factory() -> Callable[[str], str]:
    ticks = iter(range(1, 10_000))
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _judgment(
    judgment_id: str, request: ReasoningRequest, proposal: JudgmentProposal, evidence_id: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=request.project_id,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(candidate_id: str, request: ReasoningRequest, evidence_id: str) -> SemanticCandidate:
    item = next(item for item in request.evidence if item.evidence_id == evidence_id)
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=item.scope,
        evidence_ids=(evidence_id,),
    )


def _create(judgment_id: str, request: ReasoningRequest, evidence_id: str) -> SemanticJudgment:
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id)
    return _judgment(judgment_id, request, CreateAddressProposal(candidate=candidate), evidence_id)


def _bind(
    judgment_id: str, request: ReasoningRequest, address_id: str, evidence_id: str
) -> SemanticJudgment:
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id)
    proposal = BindToAddressProposal(candidate=candidate, address_id=address_id)
    return _judgment(judgment_id, request, proposal, evidence_id)


def _claim(
    judgment_id: str, request: ReasoningRequest, address_id: str, evidence_id: str, quantity: int
) -> SemanticJudgment:
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="day"),
        evidence_ids=(evidence_id,),
        authority=Authority.OBSERVED,
    )
    return _judgment(judgment_id, request, proposal, evidence_id)


def _f_script() -> list[Batch]:
    return [
        lambda r: [
            _create(J_CREATE_A, r, "EV-T1-02"),
            _create(J_CREATE_B, r, "EV-T1-02"),
            _create(J_CREATE_N, r, "EV-T1-01"),
        ],
        lambda r: [
            _claim(J_CLAIM_A, r, ADDR_A, "EV-T1-02", 7),
            _claim(J_CLAIM_B, r, ADDR_B, "EV-T1-02", 8),
            _claim(J_CLAIM_N, r, ADDR_N, "EV-T1-01", 1),
        ],
        lambda r: [_bind(J_BIND_A, r, ADDR_A, "EV-T2-01")],
        lambda r: [
            _claim(J_CLAIM_A_NEW, r, ADDR_A, "EV-T2-01", 14),
            _judgment(
                J_SUPERSEDE_A,
                r,
                SupersedeProposal(target_judgment_id=J_CLAIM_A, reason="Corrected."),
                "EV-T2-01",
            ),
        ],
        lambda r: [_create(J_CREATE_C, r, "EV-T3-02")],
        lambda r: [_claim(J_CLAIM_C, r, ADDR_C, "EV-T3-02", 3)],
        lambda r: [_bind(J_BIND_C, r, ADDR_C, "EV-T4-01")],
        lambda r: [_claim(J_CLAIM_C_NEW, r, ADDR_C, "EV-T4-01", 4)],
    ]


def _r_script() -> list[Batch]:
    def create(t: int) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
        def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
            item = request.evidence[-1]
            candidate = SemanticCandidate(
                candidate_id=f"CAND-T{t}",
                subject=f"subject T{t}",
                facet="retention",
                scope=item.scope,
                evidence_ids=(item.evidence_id,),
            )
            proposal = CreateAddressProposal(candidate=candidate)
            return [_judgment(f"J-T{t}-create", request, proposal, item.evidence_id)]

        return batch

    def assert_claim(t: int) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
        def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
            item = request.evidence[-1]
            address = request.known_addresses[0].address_id
            return [_claim(f"J-T{t}-assert", request, address, item.evidence_id, t)]

        return batch

    batches: list[Batch] = []
    for t in (1, 2, 3, 4):
        batches.extend((create(t), assert_claim(t)))
    return batches


def _select(address_id: str) -> Callable[[Any], str]:
    return lambda _state: address_id


def _fake_run(
    *, authorizer: ScriptedAuthorizer | None = None, failure: str | None = None
) -> LongitudinalRun:
    f = run_arm_f(
        reasoner=ScriptedReasoner(_f_script()),
        timeline=_timeline(),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        authorizer=authorizer or ScriptedAuthorizer([AuthorizationDecision.AGREE]),
        designate_track_a=_select(ADDR_A),
        designate_track_b=_select(ADDR_B),
        designate_track_c=_select(ADDR_C),
        designate_control=_select(ADDR_N),
        scope=SCOPE,
    )
    r = run_arm_r(
        reasoner=ScriptedReasoner(_r_script()),
        timeline=_timeline(),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        scope=SCOPE,
    )
    metrics = structural_metrics(f, r, ScoringManifest())
    return assemble_run(
        frozen_code_sha=FROZEN_SHA,
        run_head_sha=FROZEN_SHA,
        f=f,
        r=r,
        metrics=metrics,
        verdicts=deterministic_verdicts(metrics),
        failure=failure,
    )


def _pre_run(
    timeline: tuple[VersionedEvidence, ...] | None = None,
) -> tuple[dict[str, Any], ExpectationManifest]:
    timeline = timeline or _timeline()
    config = default_run_config()
    expectations = build_expectation_manifest(
        frozen_code_sha=FROZEN_SHA,
        timeline_hashes=evidence_hashes(timeline),
        prompt_sha=system_instruction_sha256(),
        config=config,
    )
    manifest = build_pre_run_manifest(
        frozen_code_sha=FROZEN_SHA,
        timeline_hashes=evidence_hashes(timeline),
        prompt_sha=system_instruction_sha256(),
        config=config,
        expectations_sha=seal(expectations),
        scope=SCOPE,
        scopes=SCOPES,
    )
    return manifest, expectations


def _sealed_dir(tmp_path: Path) -> Path:
    out = tmp_path / EXPERIMENT_DIR_NAME
    manifest, expectations = _pre_run()
    write_pre_run_artifacts(out, manifest, build_expectations_document(expectations))
    return out


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _walk_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _walk_strings(v)]
    return []


# --- declared sets -------------------------------------------------------------------


def test_pre_run_files_and_post_run_files_are_the_declared_sets(tmp_path: Path) -> None:
    assert EXPERIMENT_DIR_NAME == "2026-09-11-incremental-semantic-assimilation-longitudinal"
    assert PRE_RUN_FILES == ("manifest.json", "expectations.json")
    assert POST_RUN_FILES == (
        "persistent/result.json",
        "persistent/ledger.json",
        "reconstruction/T1-result.json",
        "reconstruction/T1-ledger.json",
        "reconstruction/T2-result.json",
        "reconstruction/T2-ledger.json",
        "reconstruction/T3-result.json",
        "reconstruction/T3-ledger.json",
        "reconstruction/T4-result.json",
        "reconstruction/T4-ledger.json",
        "authorizations.json",
        "verdicts.json",
        "report.md",
    )
    assert not set(PRE_RUN_FILES) & set(POST_RUN_FILES)

    out = _sealed_dir(tmp_path)
    assert _files(out) == set(PRE_RUN_FILES)

    write_post_run_artifacts(out, _fake_run())
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)

    # Every JSON artifact is canonical: sorted keys, two-space indent, trailing newline.
    for name in (*PRE_RUN_FILES, *POST_RUN_FILES):
        if not name.endswith(".json"):
            continue
        text = (out / name).read_text(encoding="utf-8")
        payload = json.loads(text)
        assert text == json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_expectations_document_seal_is_over_the_document_minus_the_designation_slot(
    tmp_path: Path,
) -> None:
    out = _sealed_dir(tmp_path)
    manifest = _load(out / "manifest.json")
    document = _load(out / "expectations.json")

    assert document["t1_locus_designation"] is None
    assert [e["id"] for e in document["expectations"]] == [e.id for e in EXPECTATIONS]
    assert [loc["key"] for loc in document["tracked_loci"]] == [loc.key for loc in TRACKED_LOCI]

    parsed = ExpectationManifest.model_validate(document)
    assert seal(parsed) == manifest["expectations_sha256"]
    # ``seal`` excludes exactly the designation slot; the canonical sha of the rest agrees.
    without_slot = {k: v for k, v in document.items() if k != "t1_locus_designation"}
    assert sha256_bytes(canonical_json_bytes(without_slot)) == manifest["expectations_sha256"]
    # The full document (slot included) therefore hashes differently; that is by design.
    assert sha256_bytes(canonical_json_bytes(document)) != manifest["expectations_sha256"]

    assert manifest["frozen_code_sha"] == FROZEN_SHA
    assert manifest["prompt_sha256"] == system_instruction_sha256()
    assert manifest["prompt_sha256"] == hashlib.sha256(SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert manifest["timeline_hashes"] == [dict(h) for h in evidence_hashes(_timeline())]
    assert manifest["ceilings"]["max_frontier_calls"] == 16
    assert manifest["ceilings"]["max_judge_calls"] == 0
    assert manifest["ceilings"]["max_human_authorizations"] == 3
    assert manifest["ceilings"]["max_cost_usd"] == 8.0
    assert manifest["config"]["model"] == "grok-4.6"
    assert manifest["config"]["reasoning_effort"] == "high"
    assert manifest["config"]["provider"] == "xai"
    assert manifest["policy_version"] == xai_reasoner.POLICY_VERSION
    assert manifest["scope"] == SCOPE
    assert manifest["scopes"] == list(SCOPES)


# --- secrets and leakage ----------------------------------------------------------------


def test_artifacts_contain_no_secret_and_no_tracked_description_in_prompts_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_dir(tmp_path)
    write_post_run_artifacts(out, _fake_run())

    for name in (*PRE_RUN_FILES, *POST_RUN_FILES):
        text = (out / name).read_text(encoding="utf-8")
        assert FAKE_KEY not in text, name
        assert "xai-" not in text, name
        if name.endswith(".json"):
            for value in _walk_strings(_load(out / name)):
                assert value != FAKE_KEY
                assert not value.startswith("xai-")

    manifest = _load(out / "manifest.json")
    assert "prompts" in manifest
    prompts_text = json.dumps(manifest["prompts"], sort_keys=True)
    manifest_text = json.dumps(manifest, sort_keys=True)
    for locus in TRACKED_LOCI:
        assert locus.description.lower() not in prompts_text.lower()
        assert locus.description.lower() not in manifest_text.lower()
    for expectation in EXPECTATIONS:
        assert expectation.text not in manifest_text
    assert manifest["prompts"]["system_instruction_sha256"] == system_instruction_sha256()


def test_write_redacts_a_secret_shaped_token_so_a_failure_is_still_preserved(
    tmp_path: Path,
) -> None:
    out = _sealed_dir(tmp_path)
    run = _fake_run(failure="RuntimeError: header xai-abcdef0123456789 rejected")
    write_post_run_artifacts(out, run)
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)
    for name in POST_RUN_FILES:
        assert "xai-" not in (out / name).read_text(encoding="utf-8"), name
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "RuntimeError: header [REDACTED] rejected" in report


# --- overwrite refusal --------------------------------------------------------------------


def test_write_refuses_overwrite(tmp_path: Path) -> None:
    out = _sealed_dir(tmp_path)
    before = {name: (out / name).read_bytes() for name in PRE_RUN_FILES}
    manifest, expectations = _pre_run()
    with pytest.raises(FileExistsError):
        write_pre_run_artifacts(out, manifest, build_expectations_document(expectations))
    assert {name: (out / name).read_bytes() for name in PRE_RUN_FILES} == before

    # One pre-existing post-run file refuses the whole set: nothing else is written.
    (out / "verdicts.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_post_run_artifacts(out, _fake_run())
    assert _files(out) == set(PRE_RUN_FILES) | {"verdicts.json"}
    assert (out / "verdicts.json").read_text(encoding="utf-8") == "{}\n"
    assert not any(p.name.endswith(".tmp") for p in out.rglob("*"))

    (out / "verdicts.json").unlink()
    write_post_run_artifacts(out, _fake_run())
    with pytest.raises(FileExistsError):
        write_post_run_artifacts(out, _fake_run())


def test_fill_t1_designation_updates_expectations_once_and_keeps_the_seal(
    tmp_path: Path,
) -> None:
    out = _sealed_dir(tmp_path)
    sealed = _load(out / "manifest.json")["expectations_sha256"]
    run = _fake_run()
    assert run.f is not None

    fill_t1_designation(out, run.f.designations[:3])

    document = _load(out / "expectations.json")
    slot = document["t1_locus_designation"]
    assert slot is not None
    assert [d["track"] for d in slot["designations"]] == ["A", "B", "CONTROL"]
    assert "persistent/result.json" in slot["note"]
    assert all("ledger_sequence_at_designation" in d for d in slot["designations"])
    assert slot["filled_from"] == "ArmFResult.designations"
    assert seal(ExpectationManifest.model_validate(document)) == sealed
    for locus in TRACKED_LOCI:
        assert locus.description not in json.dumps(slot)

    with pytest.raises(ValueError, match="already filled"):
        fill_t1_designation(out, run.f.designations[:3])
    assert _load(out / "expectations.json") == document

    with pytest.raises(ValueError, match="no designations"):
        fill_t1_designation(tmp_path / "elsewhere", ())
    # Track C is never written to the slot (R16-a): a C designation is refused.
    with pytest.raises(ValueError, match="T1"):
        fill_t1_designation(_sealed_dir(tmp_path / "with-c"), run.f.designations)


# --- run bundle and report ----------------------------------------------------------------


def test_run_bundle_records_verbatim_proposals_and_null_architect_verdicts(
    tmp_path: Path,
) -> None:
    out = _sealed_dir(tmp_path)
    run = _fake_run()
    assert run.status == "COMPLETED"
    assert run.failure is None
    assert run.f is not None
    write_post_run_artifacts(out, run)

    authorizations = _load(out / "authorizations.json")
    assert authorizations["budget"] == {"per_track": 1, "total": 3}
    (record,) = authorizations["records"]
    assert record["t"] == 2
    assert record["record"]["decision"] == "AGREE"
    assert record["record"]["track"] == "A"
    assert record["record"]["pending_judgment_id"] == J_SUPERSEDE_A
    assert record["proposal"]["judgment_id"] == J_SUPERSEDE_A
    assert record["proposal"]["proposal"]["target_judgment_id"] == J_CLAIM_A
    assert record["proposal"]["proposal"]["reason"] == "Corrected."

    verdicts = _load(out / "verdicts.json")
    by_id = {v["id"]: v for v in verdicts["verdicts"]}
    assert list(by_id) == [e.id for e in EXPECTATIONS]
    for expectation in EXPECTATIONS:
        entry = by_id[expectation.id]
        assert entry["adjudicator"] == expectation.adjudicator
        if expectation.adjudicator == "architect":
            assert entry["verdict"] is None
        else:
            assert entry["verdict"] is not None
            assert entry["verdict"]["id"] == expectation.id
    assert verdicts["decision"] is None
    assert verdicts["declined_any"] is False
    assert verdicts["run_status"] == "COMPLETED"

    persistent = _load(out / "persistent/result.json")
    assert [s["status"] for s in persistent["result"]["steps"]] == ["COMPLETED"] * 4
    ledger = _load(out / "persistent/ledger.json")
    assert ledger["project_id"] == PROJECT_ID
    assert ledger["event_count"] == len(ledger["events"]) == run.f.final_state_revision
    for t in (1, 2, 3, 4):
        step = _load(out / f"reconstruction/T{t}-result.json")
        assert step["result"]["t"] == t
        assert step["result"]["status"] == "COMPLETED"
        t_ledger = _load(out / f"reconstruction/T{t}-ledger.json")
        assert t_ledger["project_id"] == f"PROJ-9P-R-T{t}"
        assert t_ledger["event_count"] == len(t_ledger["events"]) > 0

    report = (out / "report.md").read_text(encoding="utf-8")
    assert report == render_report(run)
    assert "COMPLETED" in report
    for expectation in EXPECTATIONS:
        assert f"| {expectation.id} |" in report
    assert "| E1 | architect | null |" in report
    assert "| E11 | deterministic | PASS |" in report
    for t in (1, 2, 3, 4):
        assert f"| F | T{t} |" in report
        assert f"| R | T{t} |" in report
    assert "intent-engine" in report and "constitution" in report


def test_run_bundle_status_is_failed_when_a_step_failed_or_the_run_raised() -> None:
    raised = _fake_run(failure="RuntimeError: boom")
    assert raised.status == "FAILED"
    assert raised.failure == "RuntimeError: boom"

    bare = assemble_run(
        frozen_code_sha=FROZEN_SHA,
        run_head_sha=FROZEN_SHA,
        f=None,
        r=(),
        metrics=None,
        verdicts=(),
        failure="RuntimeError: T0 failed",
    )
    assert bare.status == "FAILED"
    assert bare.authorizations == ()
    assert "FAILED" in render_report(bare)


# --- the entry point ------------------------------------------------------------------------


def _main(
    out: Path,
    *,
    git: FakeGit,
    stdin: str | io.TextIOBase = "",
    reasoner: ScriptedReasoner | None = None,
    seal_mode: bool = False,
) -> tuple[int, str, list[tuple[str, Any]]]:
    stdout = io.StringIO()
    built: list[tuple[str, Any]] = []
    stdin_stream = io.StringIO(stdin) if isinstance(stdin, str) else stdin

    def factory(api_key: str, config: Any) -> ScriptedReasoner:
        built.append((api_key, config))
        assert reasoner is not None, "the reasoner factory must not be called in this test"
        return reasoner

    argv = ["--frozen-sha", FROZEN_SHA, "--out", str(out), "--repo-root", "/nowhere"]
    if seal_mode:
        argv.append("--seal")
    code = script.main(
        argv,
        stdin=stdin_stream,
        stdout=stdout,
        reasoner_factory=factory,
        git_factory=lambda _root: git,
    )
    return code, stdout.getvalue(), built


def test_script_stops_before_reasoner_construction_on_failed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _never_construct_the_adapter: list[str]
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_dir(tmp_path)
    stdout = io.StringIO()

    code = script.main(
        ["--frozen-sha", FROZEN_SHA, "--out", str(out)],
        stdin=io.StringIO(""),
        stdout=stdout,
        git_factory=lambda _root: FakeGit(_blobs(), head="0" * 40),
    )

    text = stdout.getvalue()
    assert code == 2
    assert _never_construct_the_adapter == []
    assert "head_equals_frozen_sha" in text and "FAIL" in text
    assert FAKE_KEY not in text
    assert _files(out) == set(PRE_RUN_FILES)


def test_script_stops_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _never_construct_the_adapter: list[str]
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    out = _sealed_dir(tmp_path)
    stdout = io.StringIO()

    code = script.main(
        ["--frozen-sha", FROZEN_SHA, "--out", str(out)],
        stdin=io.StringIO(""),
        stdout=stdout,
        git_factory=lambda _root: FakeGit(_blobs()),
    )

    assert code == 2
    assert "XAI_API_KEY_NOT_AVAILABLE" in stdout.getvalue()
    assert _never_construct_the_adapter == []
    assert _files(out) == set(PRE_RUN_FILES)

    monkeypatch.setenv("XAI_API_KEY", "")
    code = script.main(
        ["--frozen-sha", FROZEN_SHA, "--out", str(out)],
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        git_factory=lambda _root: FakeGit(_blobs()),
    )
    assert code == 2
    assert _never_construct_the_adapter == []


def test_script_refuses_when_pre_run_files_are_missing_or_post_run_files_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    empty = tmp_path / "empty"
    code, text, built = _main(empty, git=FakeGit(_blobs()))
    assert code == 2 and built == []
    assert "manifest.json" in text

    out = _sealed_dir(tmp_path)
    (out / "report.md").write_text("recorded\n", encoding="utf-8")
    code, text, built = _main(out, git=FakeGit(_blobs()))
    assert code == 2 and built == []
    assert "report.md" in text

    # A pre-filled designation slot is not a sealed pre-run either.
    filled = _sealed_dir(tmp_path / "filled")
    run = _fake_run()
    assert run.f is not None
    fill_t1_designation(filled, run.f.designations[:3])
    code, text, built = _main(filled, git=FakeGit(_blobs()))
    assert code == 2 and built == []
    assert "already filled" in text


def test_script_fake_end_to_end_writes_artifacts_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _never_construct_the_adapter: list[str]
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_dir(tmp_path)
    slot_at_call: dict[int, Any] = {}

    def spy(call: int, _request: ReasoningRequest) -> None:
        slot_at_call[call] = _load(out / "expectations.json")["t1_locus_designation"]

    reasoner = ScriptedReasoner([*_f_script(), *_r_script()], on_call=spy)
    # Selections after T1 (A, B, CONTROL): an unknown id and a blank line are re-prompted.
    # The authorizer sees lowercase, a sentence and a blank line before an exact AGREE.
    stdin = "\n".join(
        [
            "ADDR-unknown",
            ADDR_A,
            "",
            ADDR_B,
            ADDR_N,
            "agree",
            "yes please",
            "",
            "AGREE",
            ADDR_C,
            "",
        ]
    )

    code, text, built = _main(out, git=FakeGit(_blobs()), stdin=stdin, reasoner=reasoner)

    assert code == 0, text
    assert _never_construct_the_adapter == []
    assert [key for key, _ in built] == [FAKE_KEY]
    assert built[0][1].model == "grok-4.6" and built[0][1].reasoning_effort == "high"
    assert FAKE_KEY not in text
    assert len(reasoner.requests) == 16
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)

    # The selector printed the active descriptors with ids and re-prompted on unknown ids.
    assert ADDR_A in text and ADDR_B in text and ADDR_N in text and ADDR_C in text
    assert "unknown address id" in text
    # The authorizer printed the verbatim proposal and only accepted an exact AGREE.
    assert '"target_judgment_id": "J-T1-claim-A"' in text
    assert text.count("AGREE or DECLINE") >= 4

    authorizations = _load(out / "authorizations.json")
    (record,) = authorizations["records"]
    assert record["record"]["decision"] == "AGREE"
    assert record["proposal"]["judgment_id"] == J_SUPERSEDE_A

    # R16-a: the slot was filled live, after T1 and before the first T2 request (call 3),
    # and holds the T1 three only; Track C stays in persistent/result.json.
    assert slot_at_call[1] is None and slot_at_call[2] is None
    assert slot_at_call[3] is not None
    assert [d["track"] for d in slot_at_call[3]["designations"]] == ["A", "B", "CONTROL"]
    slot = _load(out / "expectations.json")["t1_locus_designation"]
    assert slot == slot_at_call[3]
    assert [d["address_id"] for d in slot["designations"]] == [ADDR_A, ADDR_B, ADDR_N]
    result_designations = _load(out / "persistent/result.json")["result"]["designations"]
    assert [d["track"] for d in result_designations] == ["A", "B", "CONTROL", "C"]
    assert result_designations[3]["address_id"] == ADDR_C
    first_t2_ingest = min(
        e["sequence"]
        for e in _load(out / "persistent/ledger.json")["events"]
        if e["event"]["event_type"] == "EVIDENCE_INGESTED"
        and e["event"]["payload"]["evidence"]["evidence_id"].startswith("EV-T2-")
    )
    assert all(d["ledger_sequence_at_designation"] < first_t2_ingest for d in slot["designations"])
    sealed = _load(out / "manifest.json")["expectations_sha256"]
    assert seal(ExpectationManifest.model_validate(_load(out / "expectations.json"))) == sealed

    verdicts = _load(out / "verdicts.json")
    assert verdicts["run_status"] == "COMPLETED"
    assert "run_status: COMPLETED" in text


def test_script_writes_failure_artifacts_and_exits_nonzero_when_a_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_dir(tmp_path)
    batches: list[Batch] = [*_f_script(), *_r_script()]
    batches[4] = RuntimeError("model refused: header xai-deadbeef00 not accepted")
    reasoner = ScriptedReasoner(batches)
    stdin = "\n".join([ADDR_A, ADDR_B, ADDR_N, "AGREE", ""])

    code, text, _built = _main(out, git=FakeGit(_blobs()), stdin=stdin, reasoner=reasoner)

    assert code == 1, text
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)
    assert "xai-deadbeef00" not in text
    persistent = _load(out / "persistent/result.json")
    assert [s["status"] for s in persistent["result"]["steps"]] == [
        "COMPLETED",
        "COMPLETED",
        "FAILED",
        "NOT_RUN",
    ]
    assert "xai-deadbeef00" not in (out / "persistent/result.json").read_text(encoding="utf-8")
    assert _load(out / "verdicts.json")["run_status"] == "FAILED"
    slot = _load(out / "expectations.json")["t1_locus_designation"]
    assert [d["track"] for d in slot["designations"]] == ["A", "B", "CONTROL"]


def test_script_writes_failure_artifacts_when_the_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_dir(tmp_path)

    def explode(**_kwargs: Any) -> Any:
        raise RuntimeError("authority record refused")

    monkeypatch.setattr(script, "run_arm_f", explode)
    code, text, _built = _main(out, git=FakeGit(_blobs()), stdin="", reasoner=ScriptedReasoner([]))

    assert code == 1
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)
    verdicts = _load(out / "verdicts.json")
    assert verdicts["run_status"] == "FAILED"
    assert "authority record refused" in text
    assert _load(out / "persistent/result.json")["result"] is None
    assert _load(out / "expectations.json")["t1_locus_designation"] is None


def test_script_seal_mode_writes_the_pre_run_artifacts_without_a_reasoner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _never_construct_the_adapter: list[str]
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    out = tmp_path / EXPERIMENT_DIR_NAME

    code, text, built = _main(out, git=FakeGit(_blobs()), seal_mode=True)

    assert code == 0, text
    assert built == [] and _never_construct_the_adapter == []
    assert _files(out) == set(PRE_RUN_FILES)
    manifest = _load(out / "manifest.json")
    document = _load(out / "expectations.json")
    assert manifest["frozen_code_sha"] == FROZEN_SHA
    assert seal(ExpectationManifest.model_validate(document)) == manifest["expectations_sha256"]
    assert manifest["timeline_hashes"] == [dict(h) for h in evidence_hashes(_timeline())]

    # Sealing twice is refused; sealing from the wrong HEAD is refused.
    code, _text, _built = _main(out, git=FakeGit(_blobs()), seal_mode=True)
    assert code == 2
    code, _text, _built = _main(
        tmp_path / "other", git=FakeGit(_blobs(), head="0" * 40), seal_mode=True
    )
    assert code == 2
    assert not (tmp_path / "other").exists()


def test_artifacts_module_never_reads_the_api_key() -> None:
    source = Path(artifacts.__file__).read_text(encoding="utf-8")
    assert "XAI_API_KEY" not in source
    assert "environ" not in source


# --- review round: console redaction, interrupts, readiness columns, seal guard ----------


def test_script_redacts_secret_shaped_tokens_in_every_console_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    token = "xai-deadbeefcafe0001"

    # A run-raised failure that echoes a token.
    out = _sealed_dir(tmp_path / "raised")

    def explode(**_kwargs: Any) -> Any:
        raise RuntimeError(f"provider rejected header {token}")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(script, "run_arm_f", explode)
        code, text, _built = _main(out, git=FakeGit(_blobs()), reasoner=ScriptedReasoner([]))
    assert code == 1
    assert token not in text and "xai-" not in text
    assert "run raised: RuntimeError: provider rejected header [REDACTED]" in text

    # A gate detail that echoes a token (a dirty worktree line) and the STOP line.
    out = _sealed_dir(tmp_path / "gate")
    code, text, _built = _main(out, git=FakeGit(_blobs(), dirty=f"?? {token}.txt"))
    assert code == 2
    assert token not in text and "xai-" not in text
    assert "worktree_clean: FAIL" in text and "[REDACTED]" in text


class _InterruptingStdin(io.StringIO):
    """Answers the scripted lines, then raises ``KeyboardInterrupt`` at the next prompt."""

    def readline(self, size: int = -1) -> str:  # type: ignore[override]
        line = super().readline(size)
        if line == "":
            raise KeyboardInterrupt
        return line


def test_script_preserves_the_run_when_the_human_interrupts_at_a_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_dir(tmp_path)
    reasoner = ScriptedReasoner([*_f_script(), *_r_script()])
    # Three selections answered; Ctrl-C at the first authorizer prompt (T2).
    stdin = _InterruptingStdin("\n".join([ADDR_A, ADDR_B, ADDR_N, ""]))

    code, text, _built = _main(out, git=FakeGit(_blobs()), stdin=stdin, reasoner=reasoner)

    assert code == 1, text
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)
    assert "INTERRUPTED: KeyboardInterrupt" in text
    # T1 and T2's calls were made; nothing after the interrupt (no Arm R call).
    assert len(reasoner.requests) == 4
    persistent = _load(out / "persistent/result.json")
    assert [s["status"] for s in persistent["result"]["steps"]] == [
        "COMPLETED",
        "FAILED",
        "NOT_RUN",
        "NOT_RUN",
    ]
    assert "INTERRUPTED: KeyboardInterrupt" in persistent["result"]["steps"][1]["error"]
    verdicts = _load(out / "verdicts.json")
    assert verdicts["run_status"] == "FAILED"
    assert _load(out / "reconstruction/T1-result.json")["result"] is None
    slot = _load(out / "expectations.json")["t1_locus_designation"]
    assert [d["track"] for d in slot["designations"]] == ["A", "B", "CONTROL"]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "INTERRUPTED: KeyboardInterrupt" in report

    # EOF at a prompt is preserved the same way.
    out = _sealed_dir(tmp_path / "eof")
    reasoner = ScriptedReasoner([*_f_script(), *_r_script()])
    code, text, _built = _main(
        out,
        git=FakeGit(_blobs()),
        stdin="\n".join([ADDR_A, ADDR_B, ADDR_N, ""]),
        reasoner=reasoner,
    )
    assert code == 1
    assert "INTERRUPTED: EOFError" in text
    assert len(reasoner.requests) == 4
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)


def _readiness_rows(report: str) -> dict[tuple[str, str], list[str]]:
    rows: dict[tuple[str, str], list[str]] = {}
    for line in report.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 9 and cells[0].startswith("T") and cells[1] in SCOPES:
            rows[(cells[0], cells[1])] = cells
    return rows


def test_report_readiness_table_shows_closure_and_semantic_blockers_per_scope() -> None:
    header = (
        "| T | scope | ready | closure_closed | semantic_blockers_clear | stale "
        "| pending material | disputed | open |"
    )
    agreed = render_report(_fake_run())
    assert header in agreed

    declined = render_report(
        _fake_run(authorizer=ScriptedAuthorizer([AuthorizationDecision.DECLINE]))
    )
    assert header in declined
    rows = _readiness_rows(declined)
    affected = rows[("T2", "intent-engine")]
    unaffected = rows[("T2", "constitution")]
    # Same closure state, different semantic blockers: the E7 distinction is visible.
    assert affected[3] == unaffected[3]
    assert affected[4] == "False" and unaffected[4] == "True"
    assert affected[6] == "1" and unaffected[6] == "0"
    agreed_rows = _readiness_rows(agreed)
    assert agreed_rows[("T2", "intent-engine")][4] == "False"
    assert agreed_rows[("T2", "constitution")][4] == "True"


def test_seal_mode_refuses_when_timeline_evidence_carries_a_secret_shaped_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    blobs = _blobs()
    blobs[(T2, SPEC)] = b"spec v2 with key xai-abcdef0123456789 inside\n"
    out = tmp_path / EXPERIMENT_DIR_NAME

    code, text, built = _main(out, git=FakeGit(blobs), seal_mode=True)

    assert code == 2
    assert built == []
    assert not out.exists()
    assert "STOP" in text and "secret-shaped" in text
    assert "xai-abcdef" not in text


def test_script_reuses_the_api_key_env_name_and_states_the_lazy_binding_precisely() -> None:
    source = Path(script.__file__).read_text(encoding="utf-8")
    assert 'API_KEY_ENV = "XAI_API_KEY"' not in source
    assert "import API_KEY_ENV" in source or "API_KEY_ENV,\n" in source
    assert "never bound or constructed before the gates" in source
    assert "never imported" not in source
