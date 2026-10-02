"""What the Larkspur project's final understanding must be. Judge-side only.

Never shown to an executor (writer or verifier): only the adjudicator and the scorer read it.
It states final outcomes, never wording, decomposition or explanations: which truths must be
current, which must have been retired, which must never become current (declined or rejected
changes), which pairs must stay explicitly contested, and how many blocking gaps may remain.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO_ID

__all__ = [
    "EXPECTED",
    "ExpectedCorrection",
    "ExpectedOutcome",
    "ExpectedTruth",
    "TruthStatus",
]

TruthStatus = Literal["CURRENT", "RETIRED", "NEVER", "HELD"]
"""CURRENT: must be current. RETIRED: was current, must no longer be. NEVER: proposed but
declined or rejected; must never be current. HELD: stated by a source that contradicts a
current truth, with the contradiction unresolved; must not be current (the runtime holds it
in an open blocking ``CONTRADICTION`` gap; which source is right is a later decision)."""


class ExpectedTruth(FrozenModel):
    truth_id: str = Field(min_length=1)
    concern: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    final: TruthStatus


class ExpectedCorrection(FrozenModel):
    correction_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    cardinality: Literal["1:1", "N:1", "1:N", "N:M"]
    retires: tuple[str, ...] = Field(min_length=1)
    introduces: tuple[str, ...] = Field(min_length=1)
    decision: Literal["AGREE", "DECLINE"]


class ExpectedOutcome(FrozenModel):
    scenario_id: str
    truths: tuple[ExpectedTruth, ...]
    corrections: tuple[ExpectedCorrection, ...]
    contested_pairs: tuple[tuple[str, str], ...]
    """Truth pairs that contradict each other: never both current."""
    open_contradictions: tuple[tuple[str, str], ...] = ()
    """(current side, held side) of each contradiction that must END unresolved: a visible,
    OPEN contradiction hold naming the current side's claim must exist (correct), while the
    held side never becomes current (else contradictory current truths)."""
    closure_closed: bool = False
    """Whether the project may claim closure at the end. With an open contradiction: never."""
    open_blocking_gap_kinds: tuple[str, ...]
    """The kinds of the blocking gaps that must remain open at the end, sorted. The incomplete
    proposal is later delivered complete, so its gap must close; the unresolved contradiction
    must stay open, so project closure must stay false."""
    ie3_required: bool = True


def _t(truth_id: str, concern: str, final: TruthStatus, statement: str) -> ExpectedTruth:
    return ExpectedTruth(truth_id=truth_id, concern=concern, statement=statement, final=final)


EXPECTED: Final = ExpectedOutcome(
    scenario_id=SCENARIO_ID,
    truths=(
        _t("M1", "Membership", "CURRENT", "Members must be 18 or older."),
        _t("M2", "Membership", "RETIRED", "The annual membership fee is 20 EUR."),
        _t("M3", "Membership", "CURRENT", "Proof of address is required to join."),
        _t("M4", "Membership", "CURRENT", "The annual membership fee is 25 EUR."),
        _t("M5", "Membership", "CURRENT", "Members under 25 pay an annual fee of 10 EUR."),
        _t("L1", "Loan period", "RETIRED", "Tools are lent for 7 days."),
        _t("L2", "Loan period", "CURRENT",
           "One renewal of 7 days is allowed when nobody has reserved the tool."),
        _t("L3", "Loan period", "RETIRED", "Tools are lent for 14 days."),
        _t("L4", "Loan period", "CURRENT", "Tools are lent for 10 days."),
        _t("L5", "Loan period", "NEVER", "Tools are lent for 5 days."),
        _t("F1", "Late returns", "RETIRED", "A late return costs 1 EUR per day."),
        _t("F2", "Late returns", "RETIRED",
           "A member with three late returns is suspended for 30 days."),
        _t("F3", "Late returns", "CURRENT",
           "A member with a late return cannot borrow again until the tool is back."),
        _t("D1", "Deposits", "CURRENT",
           "Power tools require a 50 EUR deposit, refunded when the tool is returned."),
        _t("D2", "Deposits", "NEVER", "Hand-held power tools require a 30 EUR deposit."),
        _t("D3", "Deposits", "NEVER", "Stationary machines require an 80 EUR deposit."),
        _t("X1", "Damage", "RETIRED", "The borrower pays the repair cost of a damaged tool."),
        _t("X2", "Damage", "RETIRED", "Damage must be reported within 24 hours of the return."),
        _t("X3", "Damage", "CURRENT",
           "The borrower pays for a damaged tool up to its replacement value."),
        _t("X4", "Damage", "CURRENT",
           "Damage is reported at the return desk when the tool is returned."),
        _t("R1", "Reservations", "CURRENT", "A reserved tool is held for 2 days."),
        _t("R2", "Reservations", "HELD", "A reserved tool is held for 3 days."),
        _t("O1", "Opening hours", "CURRENT", "The library is open on Saturdays, 10:00-14:00."),
        _t("O2", "Opening hours", "CURRENT",
           "Tools can be collected only while the library is open."),
    ),
    corrections=(
        ExpectedCorrection(correction_id="C1", step_id="T03-loan", cardinality="1:1",
                           retires=("L1",), introduces=("L3",), decision="AGREE"),
        ExpectedCorrection(correction_id="C2", step_id="T04-late", cardinality="N:1",
                           retires=("F1", "F2"), introduces=("F3",), decision="AGREE"),
        ExpectedCorrection(correction_id="C3", step_id="T05-deposit", cardinality="1:N",
                           retires=("D1",), introduces=("D2", "D3"), decision="DECLINE"),
        ExpectedCorrection(correction_id="C4", step_id="T06-damage", cardinality="N:M",
                           retires=("X1", "X2"), introduces=("X3", "X4"), decision="AGREE"),
        ExpectedCorrection(correction_id="C5", step_id="T09-loan", cardinality="1:1",
                           retires=("L3",), introduces=("L4",), decision="AGREE"),
        ExpectedCorrection(correction_id="C6", step_id="T11-membership", cardinality="1:N",
                           retires=("M2",), introduces=("M4", "M5"), decision="AGREE"),
        ExpectedCorrection(correction_id="C7", step_id="T12-deposit", cardinality="1:N",
                           retires=("D1",), introduces=("D2", "D3"), decision="DECLINE"),
    ),
    contested_pairs=(("R1", "R2"),),
    open_contradictions=(("R1", "R2"),),
    open_blocking_gap_kinds=("CONTRADICTION",),
    closure_closed=False,
)  # fmt: skip
