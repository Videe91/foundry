"""The semantic claim-coverage law for future validations (audit design, §3).

Score semantic coverage, not output claim cardinality. Production IE2 binds the MODEL's own
proposition inventory (each of its propositions gets exactly one disposition) and never the
sealed inventory, so one expected meaning may lawfully be stated by several claims. An
expectation is met when:

* every expected meaning is stated by at least one claim at its own concern
  (``MISSING_MEANING``, ``WRONG_CONCERN``);
* every claim states at least one expected meaning (``EXTRA_MEANING``);
* no claim states a meaning incompatible with the expectation (``INCOMPATIBLE_CLAIM``);
* no single claim is counted for two mutually incompatible expectations (``DOUBLE_COUNTED``).

Which meanings a claim ``states`` is a semantic judgement: an independent adjudicator's (or a
sealed, documented ruling's) input to this law. This module is the deterministic bookkeeping
over that input; it never decides meaning, and it does not weaken production accounting.
"""

from __future__ import annotations

from collections.abc import Iterable

from foundry.domain.common import FrozenModel

__all__ = ["ClaimCoverage", "ExpectedMeaning", "coverage_findings"]


class ExpectedMeaning(FrozenModel):
    id: str
    concern: str
    incompatible_with: tuple[str, ...] = ()
    """Expected meanings no single claim may state together with this one (an obsolete meaning
    and its replacement, say)."""


class ClaimCoverage(FrozenModel):
    claim_id: str
    concern: str
    states: tuple[str, ...]
    """The expected meanings this claim states (a semantic judgement, supplied)."""
    incompatible: bool = False
    """The claim states something incompatible with the expected meanings."""


def coverage_findings(
    expected: Iterable[ExpectedMeaning], claims: Iterable[ClaimCoverage]
) -> tuple[str, ...]:
    meanings = {m.id: m for m in expected}
    out: list[str] = []
    covered: set[str] = set()
    for claim in claims:
        if claim.incompatible:
            out.append(f"INCOMPATIBLE_CLAIM: {claim.claim_id}")
            continue
        stated = [m for m in claim.states if m in meanings]
        if not stated:
            out.append(f"EXTRA_MEANING: {claim.claim_id}")
            continue
        clash = False
        for i, a in enumerate(stated):
            for b in stated[i + 1 :]:
                if b in meanings[a].incompatible_with or a in meanings[b].incompatible_with:
                    out.append(f"DOUBLE_COUNTED: {claim.claim_id} states {a} and {b}")
                    clash = True
        if clash:
            continue  # a claim stating incompatible meanings credits neither
        for m in stated:
            if meanings[m].concern != claim.concern:
                out.append(
                    f"WRONG_CONCERN: {claim.claim_id} at {claim.concern} states {m} of "
                    f"{meanings[m].concern}"
                )
                continue
            covered.add(m)
    for m in meanings:
        if m not in covered:
            out.append(f"MISSING_MEANING: {m}")
    return tuple(out)
