"""Typed leakage gate of the locus-validation experiment (spec §9; gate 14 of §8).

The gate proves that no sealed grading needle appears in HARNESS-AUTHORED,
model-visible text. It scans the frozen locus system instruction and eight
structurally representative request skeletons (``SKELETON_IDS``: the seed and the
revision delta, both calls, for each ledger) rendered through the REAL
``SemanticGovernor`` on an ``InMemoryEventStore``, the real
``assemble_assimilation_request`` / ``assemble_claim_request`` and the real
``render_request`` with ``include_comparison_context=True``. The haystack of a
skeleton is ``LOCUS_SYSTEM_INSTRUCTION + "\\n" + rendered_request`` after
evidence-content substitution.

Evidence content versus harness text. Evidence bytes are model-state the model must
see; a needle inside them is the evidence, not a leak. The fixture therefore carries
the REAL corpus evidence ids, artifact refs, source refs, scopes, timestamps and
supersession lineage from ``corpus`` (all structural) with every ``content`` replaced
by the opaque stand-in ``<EVIDENCE:<id>>``, built through ``evidence_item`` so the
real diff code still produces real diff headers and edges. Before scanning, every
evidence item's content (JSON-escaped as ``render_request`` emits it; whole, then line
by line so diff bodies are covered) is substituted with ``""``; with the default
stand-in content that removes exactly the ``<EVIDENCE:…>`` stand-ins. There is NO
evidence-id substitution: evidence ids, lineage refs, request keys, edges and diff
headers stay in the haystack. Address descriptors and claim fields are opaque
(``SUBJECT-<doc>``, ``FACET-<doc>``, ``PREDICATE-<doc>``, ``<CLAIM:<doc>>``); no
corpus section text and no answer-key wording ever enters a skeleton.

Skeleton construction (per ledger, in ``SKELETON_IDS`` order). Seed: a fresh governor
ingests the four opaque T1 items; Call 1 over that state is ``SEED_CALL1``; four
scripted ``CREATE_ADDRESS`` judgments (one per item, opaque descriptors, a
non-provider fingerprint) and four ``ASSERT_CLAIM`` judgments (one per created
address, opaque predicate, TEXT value) are submitted through ``governor.submit`` and
must route ``APPLY``; Call 2 with the four created addresses as neighbourhood is
``SEED_CALL2``. Revision: on that seeded state the four opaque T2 items (each
superseding its T1 item) are ingested; Call 1 is ``REVISION_CALL1`` (the comparison
context compiles the four transitions from ids and lineage alone); four scripted
``BIND_TO_ADDRESS`` judgments (each T2 item to its own T1 address) are applied; Call 2
with the same four addresses is ``REVISION_CALL2``. No skeleton states which class or
action any item calls for.

Typed matching law (spec §9; the 9P3 matcher, reused by import). Every needle carries
exactly one ``NeedleKind`` and is matched ONLY by that kind's matcher:

* ``PROSE`` -- answer-key sentences: the exact C1 normalization
  ``normalize_leakage_text`` (casefold, ASCII-whitespace collapse, strip) on BOTH
  sides, then substring containment.
* ``CANONICAL_LABEL`` -- ``OUTCOMES``, ``FAILURE_TAGS``, the four class tokens
  ``RESTATEMENT`` / ``COMPATIBLE_EXTENSION`` / ``CORRECTION`` / ``DISTINCT_LOCUS``, the
  verdict ids ``L1``..``L9`` and ``SEMANTIC_ASSERTION_IDS``: an exact, case-SENSITIVE
  standalone identifier token on the RAW haystack, boundary
  ``(?<![A-Za-z0-9_-])...(?![A-Za-z0-9_-])``. Never casefolded: the production
  prompt's lower-case lifecycle words ``restatement`` / ``correction`` / ``compatible
  extension`` / ``distinct locus`` are not matches; the upper-case tokens are.
* ``CHECKPOINT_LABEL`` -- ``CASE_IDS`` (``S01``, ``V01``..``V05``): the same
  case-sensitive standalone identifier token rule, so the evidence id
  ``EV-LV-A3-T1`` and ``prefix-V03`` / ``V03_suffix`` are not matches while
  ``case V03 failed`` is.

PROSE derivation (the exact rule the manifest's ``needle_set_sha256`` commits to).
Sources: every value of ``HYPOTHESES``, ``EXPECTED_STATE``, ``ASSERTION_TEXT`` and
``SEMANTIC_QUESTIONS`` (verbatim spec prose with markdown). For each source text:
(1) remove the markdown markers ``**``, ``*``, backtick and the table pipe ``|``;
(2) split into fragments on every newline and on every ``.`` or ``;`` that is
followed by whitespace; (3) strip each fragment of surrounding whitespace, of a
leading list marker ``- `` and of trailing ``.``, ``;``, ``:``, ``?``, ``!``;
(4) keep every fragment with at least six whitespace-separated words; (5) deduplicate
across all sources. Nothing else is derived: no synonym, stem, lexical or similarity
expansion exists.

``needle_set_sha256`` (the 9P3 §15.1 recipe, implemented locally over THIS set)
commits to BOTH the unnormalized value and its kind: the entry
``f"{kind}\\x00{value}"`` for every typed needle, sorted by code point, joined with
``"\\x1e"``, SHA-256 of the UTF-8 bytes. ``needles()`` is the complete value
inventory; the kind lives in ``typed_needles()``.

Law of this module: it may import ``expectations`` because it never enters the
provider request path; it decides nothing semantic -- a needle either matches under
its kind's matcher or it does not, and no other matcher (no fuzzy, lexical, similarity
or ranking logic) exists here. It fails closed on the FIRST match, naming the exact
needle, its kind and the skeleton. It never constructs a provider adapter, never reads
the environment and makes no network call. ``request_path_import_gate`` is the static
AST gate that proves no request-path module imports the answer key, the evaluator, this
gate, the integrity gates or the artifact writer in any form.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import LOCUS_SYSTEM_INSTRUCTION, render_request
from foundry.application.assimilation_context import (
    assemble_assimilation_request,
    assemble_claim_request,
)
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.locus_validation.corpus import (
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    Ledger,
    delta,
)
from foundry.experiments.locus_validation.expectations import (
    ASSERTION_TEXT,
    CASE_IDS,
    EXPECTED_STATE,
    FAILURE_TAGS,
    HYPOTHESES,
    OUTCOMES,
    SEMANTIC_ASSERTION_IDS,
    SEMANTIC_QUESTIONS,
)
from foundry.experiments.locus_validation.protocol import PROMPT_SHA256_FROZEN
from foundry.experiments.long_horizon_bounded.leakage import LeakageNeedle, NeedleKind, matches
from foundry.ports.semantic_reasoner import ReasoningRequest

__all__ = [
    "ANSWER_KEY_MODULES",
    "CLASS_TOKENS",
    "EXTRA_HARNESS_TEXT_PREFIX",
    "REQUEST_PATH_MODULES",
    "SKELETON_IDS",
    "VERDICT_IDS",
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

EvidenceContent = Callable[[str], str]
"""Maps an evidence id to the content the skeleton fixture carries for it."""

SKELETON_IDS: Final[tuple[str, ...]] = (
    "ALPHA_SEED_CALL1",
    "ALPHA_SEED_CALL2",
    "ALPHA_REVISION_CALL1",
    "ALPHA_REVISION_CALL2",
    "BETA_SEED_CALL1",
    "BETA_SEED_CALL2",
    "BETA_REVISION_CALL1",
    "BETA_REVISION_CALL2",
)

EXTRA_HARNESS_TEXT_PREFIX: Final = "EXTRA-"
"""Skeleton id prefix for injected static harness text: ``EXTRA-<n>``, ``n`` from 0."""

REQUEST_PATH_MODULES: Final[tuple[str, ...]] = (
    "corpus.py",
    "protocol.py",
    "recording.py",
    "runner.py",
)
"""The four request-path modules the import gate requires and scans."""

ANSWER_KEY_MODULES: Final[tuple[str, ...]] = (
    "expectations",
    "evaluation",
    "leakage",
    "integrity",
    "artifacts",
)
"""The package modules no request-path module may import in any form."""

CLASS_TOKENS: Final[tuple[str, ...]] = (
    "RESTATEMENT",
    "COMPATIBLE_EXTENSION",
    "CORRECTION",
    "DISTINCT_LOCUS",
)
"""The four semantic-class tokens of spec §3, restated as canonical labels."""

VERDICT_IDS: Final[tuple[str, ...]] = tuple(f"L{n}" for n in range(1, 10))
"""The post-run verdict ids ``L1``..``L9`` (spec §8; the integrity module defines the
same tuple)."""

_PACKAGE_MODULE: Final = "foundry.experiments.locus_validation"
_PACKAGE_LEAF: Final = "locus_validation"
_DYNAMIC_IMPORT_NAMES: Final[frozenset[str]] = frozenset({"import_module", "__import__"})

_MARKDOWN_MARKERS: Final = re.compile(r"\*\*|\*|`|\|")
_FRAGMENT_BOUNDARY: Final = re.compile(r"[.;]\s+|\n")
_LIST_MARKER: Final = "- "
_TRAILING_PUNCTUATION: Final = ".;:?!"
_MIN_PROSE_WORDS: Final = 6

_SKELETON_CLOCK: Final = datetime(2000, 1, 1, tzinfo=UTC)
_SKELETON_FINGERPRINT: Final = ReasonerFingerprint(
    provider="skeleton", model="skeleton", policy_version="skeleton"
)
_RATIONALE: Final = "RATIONALE-SKELETON"


# --------------------------------------------------------------------------- needles


def _prose_fragments(text: str) -> list[str]:
    """The documented PROSE derivation for one source text (module docstring)."""
    stripped = _MARKDOWN_MARKERS.sub("", text)
    fragments: list[str] = []
    for raw in _FRAGMENT_BOUNDARY.split(stripped):
        fragment = raw.strip().removeprefix(_LIST_MARKER).strip()
        fragment = fragment.rstrip(_TRAILING_PUNCTUATION).strip()
        if len(fragment.split()) >= _MIN_PROSE_WORDS:
            fragments.append(fragment)
    return fragments


def typed_needles() -> tuple[LeakageNeedle, ...]:
    """The sealed inventory with its matcher kind, sorted by ``(kind, value)``.

    ``PROSE``: the derived fragments of every ``HYPOTHESES``, ``EXPECTED_STATE``,
    ``ASSERTION_TEXT`` and ``SEMANTIC_QUESTIONS`` value. ``CANONICAL_LABEL``:
    ``OUTCOMES``, ``FAILURE_TAGS``, ``CLASS_TOKENS``, ``VERDICT_IDS`` and
    ``SEMANTIC_ASSERTION_IDS``. ``CHECKPOINT_LABEL``: ``CASE_IDS``. Every value carries
    exactly one kind.
    """
    prose: set[str] = set()
    for source in (HYPOTHESES, EXPECTED_STATE, ASSERTION_TEXT, SEMANTIC_QUESTIONS):
        for text in source.values():
            prose.update(_prose_fragments(text))
    canonical: set[str] = {
        *OUTCOMES,
        *FAILURE_TAGS,
        *CLASS_TOKENS,
        *VERDICT_IDS,
        *SEMANTIC_ASSERTION_IDS,
    }
    checkpoint_labels: set[str] = set(CASE_IDS)
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
    """9P3 §15.1 recipe over THIS set: ``f"{kind}\\x00{value}"`` over UNNORMALIZED
    values, sorted by code point, joined with ``"\\x1e"``, SHA-256 of the UTF-8 bytes."""
    entries = sorted(f"{needle.kind}\x00{needle.value}" for needle in typed_needles())
    return hashlib.sha256("\x1e".join(entries).encode("utf-8")).hexdigest()


def placeholder_evidence_content(evidence_id: str) -> str:
    """The opaque stand-in for evidence bytes in every skeleton."""
    return f"<EVIDENCE:{evidence_id}>"


# --------------------------------------------------------------------------- models


class SkeletonText(FrozenModel):
    """One rendered skeleton: what the model would see, and what the gate scans."""

    skeleton_id: str = Field(min_length=1)
    ledger: Ledger
    model_visible_text: str
    """``LOCUS_SYSTEM_INSTRUCTION`` + ``"\\n"`` + the exact ``render_request`` output."""
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
    prompt_sha256: str = Field(min_length=64, max_length=64)
    matched_needle: str | None
    matched_needle_kind: NeedleKind | None
    matched_skeleton_id: str | None


# --------------------------------------------------------------------------- fixture


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _opaque_item(item: EvidenceItem, content: EvidenceContent) -> EvidenceItem:
    """The corpus item with its content substituted; every structural field is kept."""
    return evidence_item(
        evidence_id=item.evidence_id,
        project_id=item.project_id,
        source_kind=item.source_kind,
        source_ref=item.source_ref,
        content=content(item.evidence_id),
        observed_at=item.observed_at,
        scope=item.scope,
        artifact_ref=item.artifact_ref,
        supersedes_evidence_id=item.supersedes_evidence_id,
    )


def _governor(ledger: Ledger) -> SemanticGovernor:
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT_IDS[ledger],
        policy=AdmissionPolicy(),
        clock=lambda: _SKELETON_CLOCK,
    )


def _judgment(
    ledger: Ledger, judgment_id: str, proposal: JudgmentProposal, evidence_id: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT_IDS[ledger],
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


def _candidate(ledger: Ledger, document: str, t: int, evidence_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=f"CAND-{document}-T{t}",
        subject=f"SUBJECT-{document}",
        facet=f"FACET-{document}",
        scope=(SCOPES[ledger],),
        evidence_ids=(evidence_id,),
    )


def _address_minted_by(governor: SemanticGovernor, judgment_id: str) -> str:
    for address_id, address in governor.state().semantic.addresses.items():
        if address.created_by_judgment_id == judgment_id:
            return address_id
    raise RuntimeError(f"SKELETON_FIXTURE_NO_ADDRESS: {judgment_id}")


def _seed_addresses_and_claims(
    governor: SemanticGovernor, ledger: Ledger, t1: tuple[EvidenceItem, ...]
) -> dict[str, str]:
    """Four scripted ``CREATE_ADDRESS`` then four ``ASSERT_CLAIM`` judgments, opaque
    descriptors only; returns ``document -> address_id``."""
    addresses: dict[str, str] = {}
    for document, item in zip(DOCUMENTS[ledger], t1, strict=True):
        judgment_id = f"J-CREATE-{document}"
        candidate = _candidate(ledger, document, 1, item.evidence_id)
        _submit_applied(
            governor,
            _judgment(
                ledger, judgment_id, CreateAddressProposal(candidate=candidate), item.evidence_id
            ),
        )
        addresses[document] = _address_minted_by(governor, judgment_id)
    for document, item in zip(DOCUMENTS[ledger], t1, strict=True):
        claim = AssertClaimProposal(
            address_id=addresses[document],
            predicate=f"PREDICATE-{document}",
            value=ClaimValue(kind=ClaimValueKind.TEXT, text=f"<CLAIM:{document}>"),
            evidence_ids=(item.evidence_id,),
            authority=Authority.OBSERVED,
        )
        _submit_applied(governor, _judgment(ledger, f"J-CLAIM-{document}", claim, item.evidence_id))
    return addresses


def _bind_revisions(
    governor: SemanticGovernor,
    ledger: Ledger,
    t2: tuple[EvidenceItem, ...],
    addresses: Mapping[str, str],
) -> None:
    """Four scripted ``BIND_TO_ADDRESS`` judgments: each T2 item to its own T1 address."""
    for document, item in zip(DOCUMENTS[ledger], t2, strict=True):
        proposal = BindToAddressProposal(
            candidate=_candidate(ledger, document, 2, item.evidence_id),
            address_id=addresses[document],
        )
        _submit_applied(
            governor, _judgment(ledger, f"J-BIND-{document}", proposal, item.evidence_id)
        )


def _substitute_evidence_content(text: str, items: tuple[EvidenceItem, ...]) -> str:
    """Remove every evidence item's content (JSON-escaped as rendered; whole, then per
    line so diff bodies are covered). Evidence ids are never substituted."""
    for item in items:
        escaped = json.dumps(item.content, ensure_ascii=False)[1:-1]
        if escaped:
            text = text.replace(escaped, "")
        for line in item.content.splitlines():
            escaped_line = json.dumps(line, ensure_ascii=False)[1:-1]
            if escaped_line:
                text = text.replace(escaped_line, "")
    return text


def _skeleton(
    skeleton_id: str,
    ledger: Ledger,
    request: ReasoningRequest,
    state_items: tuple[EvidenceItem, ...],
) -> SkeletonText:
    model_visible = (
        LOCUS_SYSTEM_INSTRUCTION + "\n" + render_request(request, include_comparison_context=True)
    )
    items = tuple({i.evidence_id: i for i in (*state_items, *request.evidence)}.values())
    return SkeletonText(
        skeleton_id=skeleton_id,
        ledger=ledger,
        model_visible_text=model_visible,
        harness_text=_substitute_evidence_content(model_visible, items),
    )


def _render_ledger(ledger: Ledger, content: EvidenceContent) -> tuple[SkeletonText, ...]:
    project_id = PROJECT_IDS[ledger]
    scope = SCOPES[ledger]
    prefix = ledger.upper()
    governor = _governor(ledger)

    # Seed: Call 1 over the four opaque T1 items and an empty ledger.
    t1 = tuple(_opaque_item(item, content) for item in delta(ledger, 1))
    for item in t1:
        governor.ingest(item)
    state = governor.state()
    call1 = assemble_assimilation_request(project_id=project_id, delta=t1, state=state, scope=scope)
    seed_call1 = _skeleton(f"{prefix}_SEED_CALL1", ledger, call1, t1)

    # Seed: four scripted creates and four asserts, then Call 2 over the four addresses.
    addresses = _seed_addresses_and_claims(governor, ledger, t1)
    neighborhood = tuple(sorted(addresses.values()))
    state = governor.state()
    call2 = assemble_claim_request(
        project_id=project_id, delta=t1, state=state, neighborhood=neighborhood
    )
    seed_call2 = _skeleton(f"{prefix}_SEED_CALL2", ledger, call2, t1)

    # Revision: the four opaque T2 items supersede their T1 items; Call 1 over the seeded state.
    t2 = tuple(_opaque_item(item, content) for item in delta(ledger, 2))
    for item in t2:
        governor.ingest(item)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call1 = assemble_assimilation_request(project_id=project_id, delta=t2, state=state, scope=scope)
    revision_call1 = _skeleton(f"{prefix}_REVISION_CALL1", ledger, call1, state_items)

    # Revision: four scripted binds, then Call 2 over the same four addresses.
    _bind_revisions(governor, ledger, t2, addresses)
    state = governor.state()
    state_items = tuple(state.semantic.evidence.values())
    call2 = assemble_claim_request(
        project_id=project_id, delta=t2, state=state, neighborhood=neighborhood
    )
    revision_call2 = _skeleton(f"{prefix}_REVISION_CALL2", ledger, call2, state_items)

    return (seed_call1, seed_call2, revision_call1, revision_call2)


def render_skeletons(
    *, evidence_content: EvidenceContent = placeholder_evidence_content
) -> tuple[SkeletonText, ...]:
    """Render the eight ``SKELETON_IDS`` through the real governor, assembly and rendering.

    ``evidence_content`` exists so a test can prove the evidence/harness distinction;
    the gate itself always uses ``placeholder_evidence_content``.
    """
    return tuple(
        skeleton for ledger in LEDGERS for skeleton in _render_ledger(ledger, evidence_content)
    )


def build_skeletons() -> dict[str, str]:
    """``skeleton_id -> model-visible text`` for the eight default skeletons."""
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
        prompt_sha256=PROMPT_SHA256_FROZEN,
        matched_needle=matched.value if matched is not None else None,
        matched_needle_kind=matched.kind if matched is not None else None,
        matched_skeleton_id=matched_skeleton_id,
    )


def run_leakage_gate(*, extra_harness_text: tuple[str, ...] = ()) -> LeakageResult:
    """The spec §9 gate over the frozen locus prompt and the eight stand-in skeletons.

    ``extra_harness_text`` lets a caller add static harness-authored text (the
    regression tests inject hidden phrases through it); each entry is scanned exactly
    like a skeleton, never as evidence content.
    """
    return scan_skeletons(render_skeletons(), extra_harness_text=extra_harness_text)


# --------------------------------------------------------------------------- import gate


def _is_answer_key_module(dotted: str) -> bool:
    """``dotted`` names one of ``ANSWER_KEY_MODULES`` of this package: absolute
    (``foundry.experiments.locus_validation.<m>``), relative (``.<m>``, ``..locus_validation.<m>``)
    or bare (``<m>``, as ``importlib.import_module(".<m>", package)`` would resolve)."""
    leaf = dotted.rstrip(".").rsplit(".", 1)[-1]
    if leaf not in ANSWER_KEY_MODULES:
        return False
    head = dotted[: -len(leaf)].strip(".")
    return head in ("", _PACKAGE_MODULE, _PACKAGE_LEAF) or head.endswith("." + _PACKAGE_LEAF)


def _is_this_package(module: str, level: int) -> bool:
    if level == 0:
        return module == _PACKAGE_MODULE
    return module == "" or module == _PACKAGE_LEAF or module.endswith("." + _PACKAGE_LEAF)


def _forbidden_import(node: ast.Import | ast.ImportFrom) -> str | None:
    """The offending import statement text, or ``None`` when the import is clean."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if _is_answer_key_module(alias.name) and alias.name.startswith(_PACKAGE_MODULE + "."):
                return f"import {alias.name}"
        return None
    module = node.module or ""
    names = [alias.name for alias in node.names]
    dots = "." * node.level
    if node.level == 0 and _is_answer_key_module(module):
        return f"from {module} import {', '.join(names)}"
    if node.level > 0 and _is_answer_key_module(dots + module):
        return f"from {dots}{module} import {', '.join(names)}"
    if _is_this_package(module, node.level):
        offenders = [name for name in names if name in ANSWER_KEY_MODULES]
        if offenders:
            return f"from {dots}{module} import {', '.join(offenders)}"
    return None


def _forbidden_dynamic_import(node: ast.Call) -> str | None:
    """A ``importlib.import_module`` / ``__import__`` call naming an answer-key module."""
    callee = node.func
    if isinstance(callee, ast.Attribute):
        name = callee.attr
    elif isinstance(callee, ast.Name):
        name = callee.id
    else:
        return None
    if name not in _DYNAMIC_IMPORT_NAMES:
        return None
    for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
        if (
            isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and _is_answer_key_module(argument.value)
        ):
            return f"{name}({argument.value!r})"
    return None


def request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]:
    """Every ``REQUEST_PATH_MODULES`` key must be supplied and parsable, and no supplied
    source (extra keys included) may import ``expectations``, ``evaluation``,
    ``leakage``, ``integrity`` or ``artifacts`` of this package in any form: absolute or
    relative ``import`` / ``from … import``, the module name from the package, or a
    dynamic ``importlib.import_module`` / ``__import__`` naming it."""
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
            offending: str | None = None
            if isinstance(node, ast.Import | ast.ImportFrom):
                offending = _forbidden_import(node)
            elif isinstance(node, ast.Call):
                offending = _forbidden_dynamic_import(node)
            if offending is not None:
                offenders.append(f"{name}: {offending}")
    if offenders:
        return False, "answer-key import in request path: " + "; ".join(offenders)
    return True, f"no answer-key import in {sorted(sources)}"
