"""9P2 five-key leakage gate for the unseen-lifecycle experiment (spec §14; C1).

The gate proves that no sealed grading needle appears in HARNESS-AUTHORED, model-visible
text. It scans the two frozen system instructions and nine structurally representative
request skeletons (spec §14.3) rendered through the real assembly functions
(``assemble_assimilation_request`` / ``assemble_claim_request`` for F and R,
``assemble_ablation_call1`` / ``assemble_ablation_call2`` for A) and the real frozen
``render_request`` -- five-key with ``comparison_context`` for F/R, historical four-key
for A -- over a deterministic synthetic fixture built through a real ``SemanticGovernor``
on an ``InMemoryEventStore``.

Evidence content versus harness text (spec §14.4). Evidence bytes are model-state the
model must see; a needle inside them is the evidence, not a leak. The fixture therefore
carries the REAL Kestrel evidence ids, artifact refs, source refs, scopes, timestamps
and supersession lineage (all structural) with every ``content`` replaced by the opaque
placeholder ``<EVIDENCE:<id>>``, so the real diff code still produces real diff
headers and edges. Before scanning, every evidence item's content string (JSON-escaped
as ``render_request`` emits it, both whole and line by line so diff bodies are covered)
is substituted back to ``<EVIDENCE:<id>>``; with the default placeholder content that
substitution is the identity, which ``build_skeletons(evidence_content=...)`` lets a
test prove by injecting a needle into evidence content and observing that the gate
still passes. Address descriptors and claim fields are opaque (``SUBJECT_ALPHA``,
``FACET_ALPHA``, ``PREDICATE_ALPHA``, ``CLAIM_VALUE_ALPHA``).

Needles (spec §14.5): every ``GRADING_LABELS`` item, matched word-bounded after case
folding; every full answer-key sentence; the four normalized conclusions. Nothing from
the evidence. ``needle_set_sha256`` is the sha256 of the canonical JSON of the sorted
tuple of UNNORMALIZED needle strings (C1). Matching uses ``normalize_leakage_text``
(case fold + collapse of consecutive ASCII whitespace, nothing else) on both sides.

Law of this module: it may import ``expectations`` because it never enters the provider
request path; it decides nothing semantic -- a needle either occurs as a normalized
substring (or word-bounded label) or it does not. It fails closed: any match fails the
gate and the result names the exact needle and skeleton.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    render_request,
)
from foundry.application.assimilation_context import (
    assemble_assimilation_request,
    assemble_claim_request,
)
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.evidence import EvidenceItem, sha256_of_content
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupportsClaimProposal,
)
from foundry.experiments.contrastive_unseen.ablation import (
    assemble_ablation_call1,
    assemble_ablation_call2,
)
from foundry.experiments.contrastive_unseen.expectations import (
    ANSWER_KEY_SENTENCES,
    GRADING_LABELS,
    NORMALIZED_CONCLUSIONS,
)
from foundry.experiments.contrastive_unseen.timeline import (
    PROJECT_ID,
    SCOPE,
    TIMELINE,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

__all__ = [
    "EXTRA_HARNESS_TEXT_PREFIX",
    "SKELETON_IDS",
    "EvidenceContent",
    "LeakageResult",
    "SkeletonRecord",
    "SkeletonText",
    "build_skeletons",
    "needle_set_sha256",
    "needle_strings",
    "normalize_leakage_text",
    "placeholder_evidence_content",
    "run_leakage_gate",
    "scan_skeletons",
]

SkeletonArm = Literal["F", "A", "R"]
EvidenceContent = Callable[[str], str]
"""Maps an evidence id to the content the skeleton fixture carries for it."""

SKELETON_IDS: Final[tuple[str, ...]] = (
    "F_T1_CALL1_NO_PREDECESSOR",
    "F_CORRECTION_CALL1_TOUCHED",
    "F_CORRECTION_CALL2_TOUCHED",
    "F_RESTATEMENT_CALL1_TOUCHED",
    "F_RESTATEMENT_CALL2_TOUCHED",
    "A_CALL1_NO_CLAIMS",
    "A_CALL2_WITH_CLAIMS_NO_CONTEXT",
    "R_CUMULATIVE_CALL1",
    "R_CUMULATIVE_CALL2",
)

EXTRA_HARNESS_TEXT_PREFIX: Final = "EXTRA_HARNESS_TEXT_"
"""Skeleton id prefix for injected static harness text (mutation tests, CLI notes)."""

_ASCII_WHITESPACE_RE: Final = re.compile(r"[\t\n\v\f\r ]+")

_SKELETON_CLOCK: Final = datetime(2000, 1, 1, tzinfo=UTC)
_SKELETON_FINGERPRINT: Final = ReasonerFingerprint(
    provider="skeleton", model="skeleton", policy_version="skeleton"
)
_SUBJECT: Final = "SUBJECT_ALPHA"
_FACET: Final = "FACET_ALPHA"
_PREDICATE: Final = "PREDICATE_ALPHA"
_CLAIM_VALUE: Final = ClaimValue(kind=ClaimValueKind.TEXT, text="CLAIM_VALUE_ALPHA")
_RATIONALE: Final = "RATIONALE_ALPHA"

_EV_A1: Final = "EV-K-A1"
_EV_A2: Final = "EV-K-A2"
_EV_A3: Final = "EV-K-A3"


# --------------------------------------------------------------------------- C1


def normalize_leakage_text(text: str) -> str:
    """Case fold, then collapse runs of ASCII whitespace to one space; strip (C1)."""
    return _ASCII_WHITESPACE_RE.sub(" ", text.casefold()).strip()


def placeholder_evidence_content(evidence_id: str) -> str:
    """The opaque stand-in for evidence bytes in every skeleton (spec §14.4)."""
    return f"<EVIDENCE:{evidence_id}>"


# --------------------------------------------------------------------------- needles


def needle_strings() -> tuple[str, ...]:
    """The sorted, deduplicated, UNNORMALIZED sealed needle strings."""
    return tuple(sorted({*GRADING_LABELS, *ANSWER_KEY_SENTENCES, *NORMALIZED_CONCLUSIONS}))


def needle_set_sha256() -> str:
    canonical = json.dumps(
        list(needle_strings()), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_LABELS: Final[frozenset[str]] = frozenset(GRADING_LABELS)


def _needle_matches(needle: str, haystack: str) -> bool:
    """``haystack`` is already normalized. Labels are word-bounded; sentences and
    conclusions are normalized substrings."""
    if needle in _LABELS:
        pattern = rf"\b{re.escape(needle.casefold())}\b"
        return re.search(pattern, haystack) is not None
    return normalize_leakage_text(needle) in haystack


# --------------------------------------------------------------------------- models


class SkeletonText(FrozenModel):
    """One rendered skeleton: what the model would see, and what the gate scans."""

    skeleton_id: str = Field(min_length=1)
    arm: SkeletonArm
    model_visible_text: str
    """System instruction + ``"\\n"`` + the exact ``render_request`` output."""
    harness_text: str
    """``model_visible_text`` with evidence content substituted out, then normalized."""


class SkeletonRecord(FrozenModel):
    skeleton_id: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    chars: int = Field(ge=0)


class LeakageResult(FrozenModel):
    """Spec §14.6 record. ``matched_*`` are ``None`` iff ``passed``."""

    passed: bool
    needle_set_sha256: str = Field(min_length=64, max_length=64)
    skeletons: tuple[SkeletonRecord, ...]
    fr_prompt_sha256: str = Field(min_length=64, max_length=64)
    a_prompt_sha256: str = Field(min_length=64, max_length=64)
    matched_needle: str | None
    matched_skeleton_id: str | None


# --------------------------------------------------------------------------- fixture


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _with_content(item: EvidenceItem, content: str) -> EvidenceItem:
    return item.model_copy(
        update={"content": content, "content_sha256": sha256_of_content(content)}
    )


def _governor() -> SemanticGovernor:
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT_ID,
        policy=AdmissionPolicy(),
        clock=lambda: _SKELETON_CLOCK,
    )


def _judgment(judgment_id: str, proposal: JudgmentProposal, evidence_id: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT_ID,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=_RATIONALE,
        reasoner=_SKELETON_FINGERPRINT,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=_SKELETON_CLOCK,
    )


def _submit_applied(governor: SemanticGovernor, judgment: SemanticJudgment) -> None:
    decision = governor.submit(judgment)
    if decision.route is not AdmissionRoute.APPLY:
        raise RuntimeError(
            f"SKELETON_FIXTURE_NOT_APPLIED: {judgment.judgment_id} routed {decision.route}"
        )


class _Fixture:
    """Deterministic synthetic Kestrel-shaped lineage with opaque content."""

    def __init__(self, evidence_content: EvidenceContent) -> None:
        self._content = evidence_content

    def item(self, evidence_id: str) -> EvidenceItem:
        for lifecycle in TIMELINE:
            if lifecycle.item.evidence_id == evidence_id:
                return _with_content(lifecycle.item, self._content(evidence_id))
        raise KeyError(evidence_id)

    def items(self, items: tuple[EvidenceItem, ...]) -> tuple[EvidenceItem, ...]:
        return tuple(_with_content(i, self._content(i.evidence_id)) for i in items)

    def seed_address_and_claim(self, governor: SemanticGovernor) -> tuple[str, str]:
        """Ingest A1; create one address from it; assert one claim at it citing A1."""
        governor.ingest(self.item(_EV_A1))
        candidate = SemanticCandidate(
            candidate_id="CAND-ALPHA",
            subject=_SUBJECT,
            facet=_FACET,
            scope=(SCOPE,),
            evidence_ids=(_EV_A1,),
        )
        _submit_applied(
            governor,
            _judgment("J-CREATE-ALPHA", CreateAddressProposal(candidate=candidate), _EV_A1),
        )
        (address_id,) = governor.state().semantic.addresses
        claim = AssertClaimProposal(
            address_id=address_id,
            predicate=_PREDICATE,
            value=_CLAIM_VALUE,
            evidence_ids=(_EV_A1,),
            authority=Authority.OBSERVED,
        )
        _submit_applied(governor, _judgment("J-CLAIM-ALPHA", claim, _EV_A1))
        (claim_id,) = governor.state().semantic.claims
        return address_id, claim_id


def _render(arm: SkeletonArm, request: ReasoningRequest) -> str:
    if arm == "A":
        return SYSTEM_INSTRUCTION + "\n" + render_request(request, include_comparison_context=False)
    return (
        CONTRASTIVE_SYSTEM_INSTRUCTION
        + "\n"
        + render_request(request, include_comparison_context=True)
    )


def _substitute_evidence_content(text: str, items: tuple[EvidenceItem, ...]) -> str:
    """Replace every evidence item's content (JSON-escaped as rendered; whole, then per
    line so diff bodies are covered) with its ``<EVIDENCE:id>`` placeholder."""
    for item in items:
        placeholder = placeholder_evidence_content(item.evidence_id)
        escaped = json.dumps(item.content, ensure_ascii=False)[1:-1]
        text = text.replace(escaped, placeholder)
        for line in item.content.splitlines():
            escaped_line = json.dumps(line, ensure_ascii=False)[1:-1]
            if escaped_line:
                text = text.replace(escaped_line, placeholder)
    return text


def _skeleton(
    skeleton_id: str,
    arm: SkeletonArm,
    request: ReasoningRequest,
    state_items: tuple[EvidenceItem, ...],
) -> SkeletonText:
    model_visible = _render(arm, request)
    items = tuple({i.evidence_id: i for i in (*state_items, *request.evidence)}.values())
    return SkeletonText(
        skeleton_id=skeleton_id,
        arm=arm,
        model_visible_text=model_visible,
        harness_text=normalize_leakage_text(_substitute_evidence_content(model_visible, items)),
    )


def build_skeletons(
    *, evidence_content: EvidenceContent = placeholder_evidence_content
) -> tuple[SkeletonText, ...]:
    """Render the nine spec §14.3 skeletons through real assembly and rendering.

    ``evidence_content`` exists so a test can prove the evidence/harness distinction;
    the gate itself always uses ``placeholder_evidence_content``.
    """
    fixture = _Fixture(evidence_content)
    skeletons: list[SkeletonText] = []

    # T1 with no predecessor transition (F Call 1 over an empty ledger).
    governor = _governor()
    t1 = fixture.items(persistent_delta(1, project_id=PROJECT_ID))
    for item in t1:
        governor.ingest(item)
    request = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=t1, state=governor.state(), scope=SCOPE
    )
    skeletons.append(_skeleton("F_T1_CALL1_NO_PREDECESSOR", "F", request, t1))

    # Correction-shaped lineage: A2 supersedes A1, and a live claim cites A1 directly.
    governor = _governor()
    address_id, _claim_id = fixture.seed_address_and_claim(governor)
    a2 = fixture.item(_EV_A2)
    governor.ingest(a2)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=(a2,), state=state, scope=SCOPE
    )
    skeletons.append(_skeleton("F_CORRECTION_CALL1_TOUCHED", "F", call1, state_items))
    call2 = assemble_claim_request(
        project_id=PROJECT_ID, delta=(a2,), state=state, neighborhood=(address_id,)
    )
    skeletons.append(_skeleton("F_CORRECTION_CALL2_TOUCHED", "F", call2, state_items))

    # Restatement-shaped lineage: A3 supersedes A2, and the live claim is reached only
    # through an ACTIVE SUPPORTS_CLAIM link from A2 (never its asserting evidence).
    governor = _governor()
    address_id, claim_id = fixture.seed_address_and_claim(governor)
    governor.ingest(fixture.item(_EV_A2))
    _submit_applied(
        governor,
        _judgment(
            "J-SUPPORT-ALPHA",
            SupportsClaimProposal(claim_id=claim_id, evidence_ids=(_EV_A2,)),
            _EV_A2,
        ),
    )
    a3 = fixture.item(_EV_A3)
    governor.ingest(a3)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=(a3,), state=state, scope=SCOPE
    )
    skeletons.append(_skeleton("F_RESTATEMENT_CALL1_TOUCHED", "F", call1, state_items))
    call2 = assemble_claim_request(
        project_id=PROJECT_ID, delta=(a3,), state=state, neighborhood=(address_id,)
    )
    skeletons.append(_skeleton("F_RESTATEMENT_CALL2_TOUCHED", "F", call2, state_items))

    # Arm A over the correction-shaped state: Call 1 never sees claims or context;
    # Call 2 sees the neighbourhood's live claims and still no context.
    governor = _governor()
    address_id, _claim_id = fixture.seed_address_and_claim(governor)
    a2 = fixture.item(_EV_A2)
    governor.ingest(a2)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_ablation_call1(project_id=PROJECT_ID, delta=(a2,), state=state, scope=SCOPE)
    skeletons.append(_skeleton("A_CALL1_NO_CLAIMS", "A", call1, state_items))
    call2 = assemble_ablation_call2(
        project_id=PROJECT_ID, delta=(a2,), state=state, neighborhood=(address_id,)
    )
    skeletons.append(_skeleton("A_CALL2_WITH_CLAIMS_NO_CONTEXT", "A", call2, state_items))

    # Arm R at T4: a fresh ledger holding the whole cumulative corpus, no judgments.
    governor = _governor()
    corpus = fixture.items(reconstruction_corpus(4, project_id=PROJECT_ID))
    for item in corpus:
        governor.ingest(item)
    state = governor.state()
    call1 = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=corpus, state=state, scope=SCOPE
    )
    skeletons.append(_skeleton("R_CUMULATIVE_CALL1", "R", call1, corpus))
    call2 = assemble_claim_request(
        project_id=PROJECT_ID, delta=corpus, state=state, neighborhood=()
    )
    skeletons.append(_skeleton("R_CUMULATIVE_CALL2", "R", call2, corpus))

    return tuple(skeletons)


# --------------------------------------------------------------------------- gate


def scan_skeletons(
    skeletons: tuple[SkeletonText, ...], *, extra_harness_text: tuple[str, ...] = ()
) -> LeakageResult:
    """Scan every skeleton's harness text (plus any injected static harness text) for
    every needle. Fails closed on the first match, naming needle and skeleton."""
    haystacks: list[tuple[str, str, str]] = [
        (s.skeleton_id, s.model_visible_text, s.harness_text) for s in skeletons
    ]
    for index, text in enumerate(extra_harness_text):
        haystacks.append(
            (f"{EXTRA_HARNESS_TEXT_PREFIX}{index}", text, normalize_leakage_text(text))
        )
    records = tuple(
        SkeletonRecord(skeleton_id=skeleton_id, sha256=_sha256(visible), chars=len(visible))
        for skeleton_id, visible, _ in haystacks
    )
    matched_needle: str | None = None
    matched_skeleton_id: str | None = None
    needles = needle_strings()
    for skeleton_id, _, harness in haystacks:
        for needle in needles:
            if _needle_matches(needle, harness):
                matched_needle, matched_skeleton_id = needle, skeleton_id
                break
        if matched_needle is not None:
            break
    return LeakageResult(
        passed=matched_needle is None,
        needle_set_sha256=needle_set_sha256(),
        skeletons=records,
        fr_prompt_sha256=_sha256(CONTRASTIVE_SYSTEM_INSTRUCTION),
        a_prompt_sha256=_sha256(SYSTEM_INSTRUCTION),
        matched_needle=matched_needle,
        matched_skeleton_id=matched_skeleton_id,
    )


def run_leakage_gate(*, extra_harness_text: tuple[str, ...] = ()) -> LeakageResult:
    """The spec §14 gate over the frozen prompts and the nine placeholder skeletons.

    ``extra_harness_text`` lets a caller add static harness-authored text (the mutation
    tests inject a hidden phrase through it); it is scanned exactly like a skeleton.
    """
    return scan_skeletons(build_skeletons(), extra_harness_text=extra_harness_text)
