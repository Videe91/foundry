"""The held-out Larkspur Tool Library project: the evidence an executor sees, step by step.

A community tool library's founder writes a dense spec (six sections), then revises it over
time: a restatement, corrections of every cardinality (1:1, N:1, 1:N, N:M), a second source
that contradicts the spec, a correction the board rejected, a correction that is changed
again, a revision whose first proposal is incomplete, the declined deposit change proposed
again, and ordinary new information (a new concern). After some steps the founder decides
the pending correction set of that concern (AGREE or DECLINE): that is human input, not an
expectation. What the final state must be lives in ``expectations`` and is never shown to an
executor.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel

__all__ = ["SCENARIO", "SCENARIO_ID", "SCOPE", "Scenario", "Step"]

SCENARIO_ID: Final = "larkspur-tool-library-e2e-v1"
SCOPE: Final = "larkspur"


class Step(FrozenModel):
    step_id: str = Field(min_length=1)
    concern: str = Field(min_length=1)
    """The section the document is about (the subject an executor may bind or create)."""
    artifact: str = Field(min_length=1)
    text: str = Field(min_length=1)
    supersedes_step: str | None = None
    """The earlier step whose document this one revises (evidence lineage), if any."""
    decision: Literal["AGREE", "DECLINE"] | None = None
    """The founder's decision on the concern's pending correction set after this step."""


class Scenario(FrozenModel):
    scenario_id: str
    scope: str
    steps: tuple[Step, ...]


def _spec(concern: str, *rules: str) -> str:
    lines = "".join(f"{n}. {rule}\n" for n, rule in enumerate(rules, 1))
    return f"## {concern}\n\nRules\n{lines}"


_MEMBERSHIP_T1 = _spec(
    "Membership",
    "Members must be 18 or older.",
    "The annual membership fee is 20 EUR.",
    "Proof of address is required to join.",
)
_MEMBERSHIP_T10 = _spec(
    "Membership",
    "Members must be 18 or older.",
    "The annual membership fee is 25 EUR; members under 25 pay 10 EUR.",
    "Proof of address is required to join.",
)
_LOAN_T1 = _spec(
    "Loan period",
    "Tools are lent for 7 days.",
    "One renewal of 7 days is allowed when nobody has reserved the tool.",
)
_LOAN_T3 = _spec(
    "Loan period",
    "Tools are lent for 14 days.",
    "One renewal of 7 days is allowed when nobody has reserved the tool.",
)
_LOAN_T8 = _spec(
    "Loan period",
    "Tools are lent for 14 days.",
    "One renewal of 7 days is allowed when nobody has reserved the tool.",
    "The board rejected the proposal to shorten the loan period to 5 days.",
)
_LOAN_T9 = _spec(
    "Loan period",
    "Tools are lent for 10 days.",
    "One renewal of 7 days is allowed when nobody has reserved the tool.",
)

SCENARIO: Final = Scenario(
    scenario_id=SCENARIO_ID,
    scope=SCOPE,
    steps=(
        # T1: the dense founding spec, one evidence item per section.
        Step(step_id="T01-membership", concern="Membership", artifact="spec/larkspur.md",
             text=_MEMBERSHIP_T1),
        Step(step_id="T01-loan", concern="Loan period", artifact="spec/larkspur.md",
             text=_LOAN_T1),
        Step(step_id="T01-late", concern="Late returns", artifact="spec/larkspur.md",
             text=_spec("Late returns",
                        "A late return costs 1 EUR per day.",
                        "A member with three late returns is suspended for 30 days.")),
        Step(step_id="T01-deposit", concern="Deposits", artifact="spec/larkspur.md",
             text=_spec("Deposits",
                        "Power tools require a deposit of 50 EUR, refunded when the tool is "
                        "returned.")),
        Step(step_id="T01-damage", concern="Damage", artifact="spec/larkspur.md",
             text=_spec("Damage",
                        "The borrower pays the repair cost of a tool damaged on loan.",
                        "Damage must be reported within 24 hours of the return.")),
        Step(step_id="T01-reservations", concern="Reservations", artifact="spec/larkspur.md",
             text=_spec("Reservations",
                        "A reserved tool is held for 2 days after it becomes available.")),
        # T2: restatement, nothing changes.
        Step(step_id="T02-loan", concern="Loan period", artifact="spec/larkspur.md",
             text=_LOAN_T1, supersedes_step="T01-loan"),
        # T3: 1:1 correction, approved.
        Step(step_id="T03-loan", concern="Loan period", artifact="spec/larkspur.md",
             text=_LOAN_T3, supersedes_step="T02-loan", decision="AGREE"),
        # T4: N:1 correction, approved.
        Step(step_id="T04-late", concern="Late returns", artifact="spec/larkspur.md",
             text=_spec("Late returns",
                        "A member with a late return cannot borrow again until the tool is "
                        "back; there is no fee and no suspension."),
             supersedes_step="T01-late", decision="AGREE"),
        # T5: 1:N correction, declined by the founder.
        Step(step_id="T05-deposit", concern="Deposits", artifact="spec/larkspur.md",
             text=_spec("Deposits",
                        "Hand-held power tools require a deposit of 30 EUR.",
                        "Stationary machines require a deposit of 80 EUR."),
             supersedes_step="T01-deposit", decision="DECLINE"),
        # T6: N:M correction, approved.
        Step(step_id="T06-damage", concern="Damage", artifact="spec/larkspur.md",
             text=_spec("Damage",
                        "The borrower pays for a tool damaged on loan, up to its replacement "
                        "value.",
                        "Damage is reported at the return desk when the tool is returned."),
             supersedes_step="T01-damage", decision="AGREE"),
        # T7: a second source contradicts the spec; neither revises the other.
        Step(step_id="T07-reservations", concern="Reservations",
             artifact="handbook/volunteers.md",
             text=_spec("Reservations",
                        "A reserved tool is held for 3 days after it becomes available.")),
        # T8: a rejected correction; the loan period stays as it is.
        Step(step_id="T08-loan", concern="Loan period", artifact="spec/larkspur.md",
             text=_LOAN_T8, supersedes_step="T03-loan"),
        # T9: the corrected value is changed again, approved.
        Step(step_id="T09-loan", concern="Loan period", artifact="spec/larkspur.md",
             text=_LOAN_T9, supersedes_step="T08-loan", decision="AGREE"),
        # T10: a revision whose first proposal may lose meaning (the verifier must catch it).
        Step(step_id="T10-membership", concern="Membership", artifact="spec/larkspur.md",
             text=_MEMBERSHIP_T10, supersedes_step="T01-membership"),
        # T11: the same revision re-sent, decided by the founder.
        Step(step_id="T11-membership", concern="Membership", artifact="spec/larkspur.md",
             text=_MEMBERSHIP_T10, supersedes_step="T10-membership", decision="AGREE"),
        # T12: the declined deposit change is proposed again; the founder declines again.
        Step(step_id="T12-deposit", concern="Deposits", artifact="spec/larkspur.md",
             text=_spec("Deposits",
                        "Hand-held power tools require a deposit of 30 EUR.",
                        "Stationary machines require a deposit of 80 EUR."),
             supersedes_step="T05-deposit", decision="DECLINE"),
        # T13: ordinary new information about a concern not yet stated.
        Step(step_id="T13-opening", concern="Opening hours", artifact="spec/larkspur.md",
             text=_spec("Opening hours",
                        "The library is open on Saturdays from 10:00 to 14:00.",
                        "Tools can only be collected during opening hours.")),
    ),
)  # fmt: skip
