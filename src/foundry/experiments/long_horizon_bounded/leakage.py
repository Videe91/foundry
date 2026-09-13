"""Typed leakage gate for the 9P3 long-horizon bounded-memory experiment (spec §15,
§15.1; T5 brief).

The gate proves that no sealed grading needle appears in HARNESS-AUTHORED,
model-visible text. It scans the two frozen system instructions and nine
structurally representative request skeletons (``SKELETON_IDS``) rendered through the
real assembly functions (``assemble_assimilation_request`` / ``assemble_claim_request``
for F and R, the reused 9P2 ``assemble_ablation_call1`` / ``assemble_ablation_call2``
for A) and the real frozen ``render_request`` -- five-key with ``comparison_context``
for F/R, historical four-key for A -- over a deterministic fixture built through a real
``SemanticGovernor`` on an ``InMemoryEventStore``. The haystack of a skeleton is
``system_instruction + "\\n" + rendered_request`` (the 9P2 shape).

Evidence content versus harness text. Evidence bytes are model-state the model must
see; a needle inside them is the evidence, not a leak. The fixture therefore carries
the REAL Orion evidence ids, artifact refs, source refs, scopes, timestamps and
supersession lineage from ``timeline`` (all structural) with every ``content``
replaced by the opaque stand-in ``<EVIDENCE:<id>>``, so the real diff code still
produces real diff headers and edges. Before scanning, every evidence item's content
(JSON-escaped as ``render_request`` emits it, whole and line by line so diff bodies
are covered) is substituted back to ``<EVIDENCE:<id>>``; with the default stand-in
content that substitution is the identity. There is NO evidence-id substitution:
evidence ids, lineage refs, request keys, edges and diff headers stay in the
haystack. Address descriptors and claim fields are opaque (``SUBJECT_ALPHA``,
``FACET_ALPHA``, ``PREDICATE_ALPHA``, ``CLAIM_VALUE_ALPHA``); no Orion section text
and no answer-key wording ever enters a skeleton.

Typed matching law (spec §15.1). Every needle carries exactly one ``NeedleKind`` and
is matched ONLY by that kind's matcher:

* ``PROSE`` -- answer-key sentences (checkpoint expected meanings and requirement
  lines, baseline and per-version hidden meanings, R grading rules): the exact 9P2 C1
  normalization ``normalize_leakage_text`` (casefold, ASCII-whitespace collapse, strip)
  on BOTH sides, then substring containment.
* ``CANONICAL_LABEL`` -- the five transition-class labels, ``DECISION_NAMES``,
  ``I1``..``I15`` and ``errors_F``/``errors_A``/``errors_R``: an exact, case-SENSITIVE
  standalone identifier token on the RAW haystack, boundary
  ``(?<![A-Za-z0-9_-])...(?![A-Za-z0-9_-])``. Never casefolded: the English words
  ``restatement`` / ``correction`` in the frozen prompts are not matches; the canonical
  tokens ``RESTATEMENT`` / ``CORRECTION`` are.
* ``CHECKPOINT_LABEL`` -- ``C02``..``C16``: the same case-sensitive standalone
  identifier token rule, so the frozen evidence id ``EV-O-C02`` and ``prefix-C02`` /
  ``C02_suffix`` are not matches while ``checkpoint C02 failed`` is.

``needle_set_sha256`` commits to BOTH the unnormalized value and its kind: the entry
``f"{kind}\\x00{value}"`` for every typed needle, sorted by code point, joined with
``"\\x1e"``, SHA-256 of the UTF-8 bytes. ``needles()`` is the complete value
inventory (``tuple(n.value for n in typed_needles())``), kept for artifact
compatibility; the kind lives in ``typed_needles()``.

Law of this module: it may import ``expectations`` because it never enters the
provider request path; it decides nothing semantic -- a needle either matches under
its kind's matcher or it does not, and no other matcher (no fuzzy, lexical, similarity
or ranking logic) exists here. It fails closed on the FIRST match, naming the exact
needle, its kind and the skeleton. ``request_path_import_gate`` is the static AST gate
that proves no request-path module imports the answer key in any form.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Callable, Mapping
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
from foundry.experiments.contrastive_unseen.leakage import normalize_leakage_text
from foundry.experiments.long_horizon_bounded import expectations as expectations_module
from foundry.experiments.long_horizon_bounded.expectations import (
    BASELINE_MEANINGS,
    CHECKPOINTS,
    CURRENT_MEANING_BY_T,
    DECISION_NAMES,
    R_GRADING_RULES,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    PROJECT_ID,
    SCOPE,
    TIMELINE,
    VERSION_COUNT,
    evidence_id,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

__all__ = [
    "EXTRA_HARNESS_TEXT_PREFIX",
    "REQUEST_PATH_MODULES",
    "SKELETON_IDS",
    "EvidenceContent",
    "LeakageNeedle",
    "LeakageResult",
    "NeedleKind",
    "SkeletonRecord",
    "SkeletonText",
    "build_skeletons",
    "matches",
    "needle_set_sha256",
    "needles",
    "placeholder_evidence_content",
    "render_skeletons",
    "request_path_import_gate",
    "run_leakage_gate",
    "scan_skeletons",
    "typed_needles",
]

SkeletonArm = Literal["F", "A", "R"]
NeedleKind = Literal["PROSE", "CANONICAL_LABEL", "CHECKPOINT_LABEL"]
EvidenceContent = Callable[[str], str]
"""Maps an evidence id to the content the skeleton fixture carries for it."""

SKELETON_IDS: Final[tuple[str, ...]] = (
    "F_T1_CALL1",
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

REQUEST_PATH_MODULES: Final[tuple[str, ...]] = (
    "timeline.py",
    "protocol.py",
    "designation.py",
    "authority.py",
    "measurements.py",
    "runner.py",
)
"""The six 9P3 request-path modules the import gate requires and scans."""

TRANSITION_CLASS_LABELS: Final[tuple[str, ...]] = (
    "RESTATEMENT",
    "CORRECTION",
    "REVERT",
    "COMPATIBLE_EXTENSION",
    "SEMANTIC_NO_OP",
)
"""The five ``TransitionClass`` literals (spec §6), restated as canonical tokens."""

_R_SKELETON_T: Final[int] = 4
"""The cumulative corpus version the R skeletons carry (T >= 2 so ``EV-O-C02``.. are
present in the haystack; 9P2 used T4 as well)."""

_IDENTIFIER_BOUNDARY_BEFORE: Final = r"(?<![A-Za-z0-9_-])"
_IDENTIFIER_BOUNDARY_AFTER: Final = r"(?![A-Za-z0-9_-])"

_EXPECTATIONS_MODULE: Final = "foundry.experiments.long_horizon_bounded.expectations"
_PACKAGE_MODULE: Final = "foundry.experiments.long_horizon_bounded"
_PACKAGE_LEAF: Final = "long_horizon_bounded"
_GRADING_HELPER_NAMES: Final[frozenset[str]] = frozenset(expectations_module.__all__)

_SKELETON_CLOCK: Final = datetime(2000, 1, 1, tzinfo=UTC)
_SKELETON_FINGERPRINT: Final = ReasonerFingerprint(
    provider="skeleton", model="skeleton", policy_version="skeleton"
)
_SUBJECT: Final = "SUBJECT_ALPHA"
_FACET: Final = "FACET_ALPHA"
_PREDICATE: Final = "PREDICATE_ALPHA"
_CLAIM_VALUE: Final = ClaimValue(kind=ClaimValueKind.TEXT, text="CLAIM_VALUE_ALPHA")
_RATIONALE: Final = "RATIONALE_ALPHA"

_EV_A01: Final = evidence_id(1, "A")
_EV_A02: Final = evidence_id(2, "A")
_EV_A03: Final = evidence_id(3, "A")


# --------------------------------------------------------------------------- needles


class LeakageNeedle(FrozenModel):
    """One sealed needle: its UNNORMALIZED value and the one matcher kind that applies."""

    value: str = Field(min_length=1)
    kind: NeedleKind


def typed_needles() -> tuple[LeakageNeedle, ...]:
    """The sealed inventory with its matcher kind, sorted by ``(kind, value)``.

    ``PROSE``: every ``Checkpoint.expected_current_meaning``, every entry of every
    ``Checkpoint.requirements``, every ``BASELINE_MEANINGS`` value, every
    ``CURRENT_MEANING_BY_T[t][locus]`` value and every ``R_GRADING_RULES`` entry
    (identical strings deduplicated). ``CANONICAL_LABEL``: the five transition-class
    labels, ``DECISION_NAMES``, ``I1``..``I15``, ``errors_F``/``errors_A``/``errors_R``.
    ``CHECKPOINT_LABEL``: ``C02``..``C16``. Every value carries exactly one kind.
    """
    prose: set[str] = set()
    for checkpoint in CHECKPOINTS:
        prose.add(checkpoint.expected_current_meaning)
        prose.update(checkpoint.requirements)
    prose.update(BASELINE_MEANINGS.values())
    for by_locus in CURRENT_MEANING_BY_T.values():
        prose.update(by_locus.values())
    prose.update(R_GRADING_RULES)
    canonical: set[str] = {
        *TRANSITION_CLASS_LABELS,
        *DECISION_NAMES,
        *(f"I{n}" for n in range(1, 16)),
        "errors_F",
        "errors_A",
        "errors_R",
    }
    checkpoint_labels: set[str] = {f"C{t:02d}" for t in range(2, VERSION_COUNT + 1)}
    inventory: list[LeakageNeedle] = [
        *(LeakageNeedle(value=value, kind="PROSE") for value in prose),
        *(LeakageNeedle(value=value, kind="CANONICAL_LABEL") for value in canonical),
        *(LeakageNeedle(value=value, kind="CHECKPOINT_LABEL") for value in checkpoint_labels),
    ]
    return tuple(sorted(inventory, key=lambda needle: (needle.kind, needle.value)))


def needles() -> tuple[str, ...]:
    """The complete deterministic value inventory (artifact compatibility)."""
    return tuple(needle.value for needle in typed_needles())


def needle_set_sha256() -> str:
    """Spec §15.1 recipe: ``f"{kind}\\x00{value}"`` over UNNORMALIZED values, sorted by
    code point, joined with ``"\\x1e"``, SHA-256 of the UTF-8 bytes."""
    entries = sorted(f"{needle.kind}\x00{needle.value}" for needle in typed_needles())
    return hashlib.sha256("\x1e".join(entries).encode("utf-8")).hexdigest()


def _standalone_token(value: str, haystack: str) -> bool:
    pattern = _IDENTIFIER_BOUNDARY_BEFORE + re.escape(value) + _IDENTIFIER_BOUNDARY_AFTER
    return re.search(pattern, haystack) is not None


def matches(needle: LeakageNeedle, haystack: str) -> bool:
    """Match ``needle`` against the RAW ``haystack`` by its kind's matcher only."""
    if needle.kind == "PROSE":
        return normalize_leakage_text(needle.value) in normalize_leakage_text(haystack)
    return _standalone_token(needle.value, haystack)


def placeholder_evidence_content(evidence_id: str) -> str:
    """The opaque stand-in for evidence bytes in every skeleton."""
    return f"<EVIDENCE:{evidence_id}>"


# --------------------------------------------------------------------------- models


class SkeletonText(FrozenModel):
    """One rendered skeleton: what the model would see, and what the gate scans."""

    skeleton_id: str = Field(min_length=1)
    arm: SkeletonArm
    model_visible_text: str
    """System instruction + ``"\\n"`` + the exact ``render_request`` output."""
    harness_text: str
    """``model_visible_text`` with evidence CONTENT substituted out; otherwise raw
    (the typed matchers normalize ``PROSE`` at match time and nothing else)."""


class SkeletonRecord(FrozenModel):
    skeleton_id: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    chars: int = Field(ge=0)


class LeakageResult(FrozenModel):
    """The gate's record. ``matched_*`` are all ``None`` iff ``passed``."""

    passed: bool
    needle_set_sha256: str = Field(min_length=64, max_length=64)
    skeletons: tuple[SkeletonRecord, ...]
    fr_prompt_sha256: str = Field(min_length=64, max_length=64)
    a_prompt_sha256: str = Field(min_length=64, max_length=64)
    matched_needle: str | None
    matched_needle_kind: NeedleKind | None
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
    """Deterministic Orion-shaped lineage (real ids, refs, timestamps, scope, lineage)
    with opaque content."""

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
        """Ingest A01; create one address from it; assert one claim at it citing A01."""
        governor.ingest(self.item(_EV_A01))
        candidate = SemanticCandidate(
            candidate_id="CAND-ALPHA",
            subject=_SUBJECT,
            facet=_FACET,
            scope=(SCOPE,),
            evidence_ids=(_EV_A01,),
        )
        _submit_applied(
            governor,
            _judgment("J-CREATE-ALPHA", CreateAddressProposal(candidate=candidate), _EV_A01),
        )
        (address_id,) = governor.state().semantic.addresses
        claim = AssertClaimProposal(
            address_id=address_id,
            predicate=_PREDICATE,
            value=_CLAIM_VALUE,
            evidence_ids=(_EV_A01,),
            authority=Authority.OBSERVED,
        )
        _submit_applied(governor, _judgment("J-CLAIM-ALPHA", claim, _EV_A01))
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
    line so diff bodies are covered) with its ``<EVIDENCE:id>`` stand-in. Evidence ids
    are never substituted."""
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
        harness_text=_substitute_evidence_content(model_visible, items),
    )


def render_skeletons(
    *, evidence_content: EvidenceContent = placeholder_evidence_content
) -> tuple[SkeletonText, ...]:
    """Render the nine ``SKELETON_IDS`` through real assembly and rendering.

    ``evidence_content`` exists so a test can prove the evidence/harness distinction;
    the gate itself always uses ``placeholder_evidence_content``.
    """
    fixture = _Fixture(evidence_content)
    skeletons: list[SkeletonText] = []

    # T1 (F Call 1 over an empty ledger; twelve items, no predecessor).
    governor = _governor()
    t1 = fixture.items(persistent_delta(1, project_id=PROJECT_ID))
    for item in t1:
        governor.ingest(item)
    request = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=t1, state=governor.state(), scope=SCOPE
    )
    skeletons.append(_skeleton("F_T1_CALL1", "F", request, t1))

    # Correction-shaped lineage: A02 supersedes A01, and a live claim cites A01 directly.
    governor = _governor()
    address_id, _claim_id = fixture.seed_address_and_claim(governor)
    a02 = fixture.item(_EV_A02)
    governor.ingest(a02)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=(a02,), state=state, scope=SCOPE
    )
    skeletons.append(_skeleton("F_CORRECTION_CALL1_TOUCHED", "F", call1, state_items))
    call2 = assemble_claim_request(
        project_id=PROJECT_ID, delta=(a02,), state=state, neighborhood=(address_id,)
    )
    skeletons.append(_skeleton("F_CORRECTION_CALL2_TOUCHED", "F", call2, state_items))

    # Restatement-shaped lineage: A03 supersedes A02, and the live claim is reached only
    # through an ACTIVE SUPPORTS_CLAIM link from A02 (never its asserting evidence).
    governor = _governor()
    address_id, claim_id = fixture.seed_address_and_claim(governor)
    governor.ingest(fixture.item(_EV_A02))
    _submit_applied(
        governor,
        _judgment(
            "J-SUPPORT-ALPHA",
            SupportsClaimProposal(claim_id=claim_id, evidence_ids=(_EV_A02,)),
            _EV_A02,
        ),
    )
    a03 = fixture.item(_EV_A03)
    governor.ingest(a03)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_assimilation_request(
        project_id=PROJECT_ID, delta=(a03,), state=state, scope=SCOPE
    )
    skeletons.append(_skeleton("F_RESTATEMENT_CALL1_TOUCHED", "F", call1, state_items))
    call2 = assemble_claim_request(
        project_id=PROJECT_ID, delta=(a03,), state=state, neighborhood=(address_id,)
    )
    skeletons.append(_skeleton("F_RESTATEMENT_CALL2_TOUCHED", "F", call2, state_items))

    # Arm A over the correction-shaped state: Call 1 never sees claims or context;
    # Call 2 sees the neighbourhood's live claims and still no context.
    governor = _governor()
    address_id, _claim_id = fixture.seed_address_and_claim(governor)
    a02 = fixture.item(_EV_A02)
    governor.ingest(a02)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_ablation_call1(project_id=PROJECT_ID, delta=(a02,), state=state, scope=SCOPE)
    skeletons.append(_skeleton("A_CALL1_NO_CLAIMS", "A", call1, state_items))
    call2 = assemble_ablation_call2(
        project_id=PROJECT_ID, delta=(a02,), state=state, neighborhood=(address_id,)
    )
    skeletons.append(_skeleton("A_CALL2_WITH_CLAIMS_NO_CONTEXT", "A", call2, state_items))

    # Arm R at T4: a fresh ledger holding the whole cumulative corpus, no judgments.
    governor = _governor()
    corpus = fixture.items(reconstruction_corpus(_R_SKELETON_T, project_id=PROJECT_ID))
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


def build_skeletons() -> dict[str, str]:
    """``skeleton_id -> model-visible text`` for the nine default skeletons."""
    return {skeleton.skeleton_id: skeleton.model_visible_text for skeleton in render_skeletons()}


# --------------------------------------------------------------------------- gate


def scan_skeletons(
    skeletons: tuple[SkeletonText, ...], *, extra_harness_text: tuple[str, ...] = ()
) -> LeakageResult:
    """Scan every skeleton's harness text (plus any injected static harness text) for
    every typed needle. Fails closed on the FIRST match, naming needle, kind and
    skeleton."""
    haystacks: list[tuple[str, str, str]] = [
        (s.skeleton_id, s.model_visible_text, s.harness_text) for s in skeletons
    ]
    for index, text in enumerate(extra_harness_text):
        haystacks.append((f"{EXTRA_HARNESS_TEXT_PREFIX}{index}", text, text))
    records = tuple(
        SkeletonRecord(skeleton_id=skeleton_id, sha256=_sha256(visible), chars=len(visible))
        for skeleton_id, visible, _ in haystacks
    )
    matched: LeakageNeedle | None = None
    matched_skeleton_id: str | None = None
    inventory = typed_needles()
    for skeleton_id, _, harness in haystacks:
        for needle in inventory:
            if matches(needle, harness):
                matched, matched_skeleton_id = needle, skeleton_id
                break
        if matched is not None:
            break
    return LeakageResult(
        passed=matched is None,
        needle_set_sha256=needle_set_sha256(),
        skeletons=records,
        fr_prompt_sha256=_sha256(CONTRASTIVE_SYSTEM_INSTRUCTION),
        a_prompt_sha256=_sha256(SYSTEM_INSTRUCTION),
        matched_needle=matched.value if matched is not None else None,
        matched_needle_kind=matched.kind if matched is not None else None,
        matched_skeleton_id=matched_skeleton_id,
    )


def run_leakage_gate(*, extra_harness_text: tuple[str, ...] = ()) -> LeakageResult:
    """The spec §15 gate over the frozen prompts and the nine stand-in skeletons.

    ``extra_harness_text`` lets a caller add static harness-authored text (the
    regression tests inject hidden phrases through it); each entry is scanned exactly
    like a skeleton, never as evidence content.
    """
    return scan_skeletons(render_skeletons(), extra_harness_text=extra_harness_text)


# --------------------------------------------------------------------------- import gate


def _forbidden_import(node: ast.Import | ast.ImportFrom) -> str | None:
    """The offending import statement text, or ``None`` when the import is clean."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == _EXPECTATIONS_MODULE or alias.name.startswith(
                _EXPECTATIONS_MODULE + "."
            ):
                return f"import {alias.name}"
        return None
    module = node.module or ""
    names = [alias.name for alias in node.names]
    if node.level == 0:
        is_expectations = module == _EXPECTATIONS_MODULE
        is_package = module == _PACKAGE_MODULE
    else:
        is_expectations = module == "expectations" or module.endswith(".expectations")
        is_package = module == "" or module == _PACKAGE_LEAF or module.endswith("." + _PACKAGE_LEAF)
    if is_expectations:
        return f"from {'.' * node.level}{module} import {', '.join(names)}"
    if is_package:
        offenders = [n for n in names if n == "expectations" or n in _GRADING_HELPER_NAMES]
        if offenders:
            return f"from {'.' * node.level}{module} import {', '.join(offenders)}"
    return None


def request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]:
    """Every ``REQUEST_PATH_MODULES`` key must be supplied and parsable, and no supplied
    source (extra keys included) may import the answer key in any form: the
    ``expectations`` module by absolute or relative path, ``expectations`` from the
    package, or any public grading helper by name from the package."""
    missing = [name for name in REQUEST_PATH_MODULES if name not in sources]
    if missing:
        return False, f"request-path sources missing: {missing}"
    offenders: list[str] = []
    for name in sorted(sources):
        try:
            tree = ast.parse(sources[name])
        except SyntaxError as exc:
            offenders.append(f"{name}: unparsable ({exc.msg} at line {exc.lineno})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                offending = _forbidden_import(node)
                if offending is not None:
                    offenders.append(f"{name}: {offending}")
    if offenders:
        return False, "answer-key import in request path: " + "; ".join(offenders)
    return True, f"no answer-key import in {sorted(sources)}"
