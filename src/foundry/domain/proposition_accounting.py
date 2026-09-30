"""Proposition accounting at the claim-writing boundary (IE2 v2 design §7.1.3).

Locus validation v4 showed that Call 2 can silently drop propositions of evidence that Call 1
correctly bound: one draft left out a proposition its own rationale named, and one response
returned no draft at all for a bound document. Nothing deterministic could notice, because no
proposition existed anywhere as an object. This module is the bookkeeping law that makes
silence impossible. It reads no meaning:

* **Source accounting.** Every sentence of every accountable evidence item (Foundry's own
  ``numbered_sentences``) is carried by at least one proposition of the response, or declared
  non-operative once, with a reason. Never both.
* **Claim accounting.** Every proposition of the response receives exactly one disposition,
  taken from the existing IE2 claim laws: SUPPORTS_CLAIM (restatement), ASSERT_CLAIM
  (compatible extension or a different concern), or ASSERT_CLAIM plus SUPERSEDE (correction).
  CONFLICTS_WITH relates two existing claims and disposes of no proposition.

Which disposition is right, what a proposition means and which claim it restates remain the
reasoner's judgments; admission still decides every one. A response with any finding is
refused whole and nothing reaches state: no disposition is ever supplied by Foundry.

Findings (each names the ids at fault): ``UNACCOUNTED_SENTENCE``, ``UNKNOWN_SENTENCE``,
``DOUBLE_ACCOUNTED_SENTENCE``, ``DUPLICATE_PROPOSITION``, ``UNACCOUNTED_PROPOSITION``,
``UNKNOWN_PROPOSITION``, ``CONFLICTING_DISPOSITION``, ``PROPOSITION_EVIDENCE_MISMATCH``.

**Correction cardinality (design 2026-09-30).** Two questions are kept apart: what happened to
an incoming proposition (exactly one disposition), and which current claims its correction
makes obsolete (the target set). Under ``ONE_TARGET`` (every policy up to
``intent-v2-locus-v5``) a correction carries exactly one SUPERSEDE. Under ``TARGET_SET``
(``intent-v2-locus-v6``) it carries one SUPERSEDE per obsolete claim, so a many-to-fewer,
one-to-many or many-to-many restructuring is expressible, and three further laws hold:
every SUPERSEDE names a target (``UNTARGETED_SUPERSEDE``); each target is superseded at most
once in the whole response (``DUPLICATE_SUPERSEDE_TARGET``), so authority always sees one
proposal per old claim; and ``correction_edge_findings`` refuses a target the response was not
shown (``UNKNOWN_SUPERSEDE_TARGET``) or one outside the address the correcting proposition is
asserted at (``CROSS_ADDRESS_SUPERSEDE``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import JudgmentKind

__all__ = [
    "VALID_DISPOSITIONS",
    "AccountedProposition",
    "CorrectionEdge",
    "CorrectionLaw",
    "NonOperativeSentence",
    "PropositionDisposition",
    "accounting_findings",
    "correction_edge_findings",
]

CorrectionLaw = Literal["ONE_TARGET", "TARGET_SET"]


class AccountedProposition(FrozenModel):
    """One proposition the response states it found, and the sentences that carry it."""

    proposition_id: str = Field(min_length=1)
    sentence_ids: tuple[str, ...] = Field(min_length=1)
    statement: str = Field(min_length=1)


class NonOperativeSentence(FrozenModel):
    """A sentence the response declares carries no proposition, and why."""

    sentence_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class PropositionDisposition(FrozenModel):
    """One draft's claim that it disposes of one proposition (bookkeeping only)."""

    proposition_id: str = Field(min_length=1)
    kind: JudgmentKind
    evidence_ids: tuple[str, ...] = ()
    """The evidence the draft cites, when its kind cites any (SUPERSEDE cites none)."""
    target_judgment_id: str | None = None
    """A SUPERSEDE draft's target. Read only under ``TARGET_SET``."""


VALID_DISPOSITIONS: Final[frozenset[tuple[JudgmentKind, ...]]] = frozenset(
    {
        (JudgmentKind.SUPPORTS_CLAIM,),
        (JudgmentKind.ASSERT_CLAIM,),
        (JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE),
    }
)
"""Under ``ONE_TARGET``, each proposition's drafts, as a sorted tuple of kinds, must be exactly
one of these. Under ``TARGET_SET`` the correction disposition is ASSERT_CLAIM plus one or more
SUPERSEDE (``_is_valid``)."""


def _is_valid(kinds: tuple[JudgmentKind, ...], law: CorrectionLaw) -> bool:
    if law == "ONE_TARGET":
        return kinds in VALID_DISPOSITIONS
    counts = Counter(kinds)
    if counts == Counter({JudgmentKind.SUPPORTS_CLAIM: 1}):
        return True
    return counts[JudgmentKind.ASSERT_CLAIM] == 1 and set(counts) <= {
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
    }


class CorrectionEdge(FrozenModel):
    """One SUPERSEDE of a correction: the proposition it belongs to and where both sides live."""

    proposition_id: str = Field(min_length=1)
    target_judgment_id: str = Field(min_length=1)
    proposition_address_ids: tuple[str, ...]
    """The addresses the proposition's ASSERT_CLAIM places it at (one, when well formed)."""
    target_address_id: str | None
    """The address of the shown claim the target created; ``None`` when no shown claim has it."""


def correction_edge_findings(edges: Iterable[CorrectionEdge]) -> tuple[str, ...]:
    """Every edge must retire a shown claim at the address its proposition is asserted at."""
    findings: list[str] = []
    for e in edges:
        if e.target_address_id is None:
            findings.append(
                f"UNKNOWN_SUPERSEDE_TARGET: {e.proposition_id} -> {e.target_judgment_id} "
                "(no claim shown to this response was created by it)"
            )
        elif e.target_address_id not in e.proposition_address_ids:
            findings.append(
                f"CROSS_ADDRESS_SUPERSEDE: {e.proposition_id} -> {e.target_judgment_id} "
                f"(target at {e.target_address_id}, proposition asserted at "
                f"{sorted(e.proposition_address_ids)})"
            )
    return tuple(findings)


def accounting_findings(
    *,
    sentence_evidence: Mapping[str, str],
    propositions: Iterable[AccountedProposition],
    non_operative: Iterable[NonOperativeSentence],
    dispositions: Iterable[PropositionDisposition],
    correction_law: CorrectionLaw = "ONE_TARGET",
) -> tuple[str, ...]:
    """Every accounting defect of one response; ``()`` when it accounts for everything.

    ``sentence_evidence`` maps every accountable sentence id to its evidence id: it is the
    complete set the response must account for (empty when nothing is accountable).
    """
    props = tuple(propositions)
    silent = tuple(non_operative)
    drafts = tuple(dispositions)
    findings: list[str] = []

    # source accounting
    carried: Counter[str] = Counter(sid for p in props for sid in set(p.sentence_ids))
    declared: Counter[str] = Counter(n.sentence_id for n in silent)
    for sid in sorted(set(carried) | set(declared)):
        if sid not in sentence_evidence:
            findings.append(f"UNKNOWN_SENTENCE: {sid}")
    for sid in sentence_evidence:
        if not carried[sid] and not declared[sid]:
            findings.append(f"UNACCOUNTED_SENTENCE: {sid}")
        elif (carried[sid] and declared[sid]) or declared[sid] > 1:
            findings.append(f"DOUBLE_ACCOUNTED_SENTENCE: {sid}")

    # claim accounting
    counts = Counter(p.proposition_id for p in props)
    for pid, n in sorted(counts.items()):
        if n > 1:
            findings.append(f"DUPLICATE_PROPOSITION: {pid}")
    by_id = {p.proposition_id: p for p in props}
    kinds: defaultdict[str, list[JudgmentKind]] = defaultdict(list)
    for d in drafts:
        if d.proposition_id not in by_id:
            findings.append(f"UNKNOWN_PROPOSITION: {d.proposition_id}")
            continue
        kinds[d.proposition_id].append(d.kind)
        required = {
            sentence_evidence[sid]
            for sid in by_id[d.proposition_id].sentence_ids
            if sid in sentence_evidence
        }
        if d.kind is not JudgmentKind.SUPERSEDE and not required <= set(d.evidence_ids):
            findings.append(
                f"PROPOSITION_EVIDENCE_MISMATCH: {d.proposition_id} ({d.kind.value} cites "
                f"{sorted(d.evidence_ids)}, its sentences come from {sorted(required)})"
            )
    for pid in by_id:
        got = tuple(sorted(kinds.get(pid, ()), key=lambda k: k.value))
        if not got:
            findings.append(f"UNACCOUNTED_PROPOSITION: {pid}")
        elif not _is_valid(got, correction_law):
            findings.append(f"CONFLICTING_DISPOSITION: {pid} ({', '.join(k.value for k in got)})")

    # correction targets (TARGET_SET only; ONE_TARGET is the historical law, unchanged)
    if correction_law == "TARGET_SET":
        by_target: defaultdict[str, list[str]] = defaultdict(list)
        for d in drafts:
            if d.kind is not JudgmentKind.SUPERSEDE:
                continue
            if d.target_judgment_id is None:
                findings.append(f"UNTARGETED_SUPERSEDE: {d.proposition_id}")
                continue
            by_target[d.target_judgment_id].append(d.proposition_id)
        for target, pids in sorted(by_target.items()):
            if len(pids) > 1:
                findings.append(
                    f"DUPLICATE_SUPERSEDE_TARGET: {target} superseded {len(pids)} times "
                    f"({', '.join(sorted(pids))})"
                )
    return tuple(findings)
