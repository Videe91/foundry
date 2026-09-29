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
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Final

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import JudgmentKind

__all__ = [
    "VALID_DISPOSITIONS",
    "AccountedProposition",
    "NonOperativeSentence",
    "PropositionDisposition",
    "accounting_findings",
]


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


VALID_DISPOSITIONS: Final[frozenset[tuple[JudgmentKind, ...]]] = frozenset(
    {
        (JudgmentKind.SUPPORTS_CLAIM,),
        (JudgmentKind.ASSERT_CLAIM,),
        (JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE),
    }
)
"""Each proposition's drafts, as a sorted tuple of kinds, must be exactly one of these."""


def accounting_findings(
    *,
    sentence_evidence: Mapping[str, str],
    propositions: Iterable[AccountedProposition],
    non_operative: Iterable[NonOperativeSentence],
    dispositions: Iterable[PropositionDisposition],
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
        elif got not in VALID_DISPOSITIONS:
            findings.append(f"CONFLICTING_DISPOSITION: {pid} ({', '.join(k.value for k in got)})")
    return tuple(findings)
