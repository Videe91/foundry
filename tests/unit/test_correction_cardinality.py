"""The correction cardinality law (design 2026-09-30, ``intent-v2-locus-v6``).

A correcting proposition is ASSERT_CLAIM plus one SUPERSEDE for EACH current claim it makes
obsolete (a target set). Every proposition still has exactly one disposition; the set of
superseded claims is the second, explicit side of the correction. Each current claim is
superseded at most once per response, and only at the address of the ASSERT that supersedes
it. The historical one-target law (``ONE_TARGET``, every policy up to ``intent-v2-locus-v5``)
is unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest

from foundry.domain.proposition_accounting import (
    AccountedProposition,
    CorrectionEdge,
    NonOperativeSentence,
    PropositionDisposition,
    accounting_findings,
    correction_edge_findings,
)
from foundry.domain.semantic_judgment import JudgmentKind

A, S, X = JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPPORTS_CLAIM, JudgmentKind.SUPERSEDE
EV = "EV-1"


def _props(*pids: str) -> list[AccountedProposition]:
    return [
        AccountedProposition(proposition_id=p, sentence_ids=(f"{EV}#S{i}",), statement=p)
        for i, p in enumerate(pids, 1)
    ]


def _d(pid: str, kind: JudgmentKind, target: str | None = None) -> PropositionDisposition:
    return PropositionDisposition(
        proposition_id=pid,
        kind=kind,
        evidence_ids=() if kind is X else (EV,),
        target_judgment_id=target,
    )


def _findings(
    pids: tuple[str, ...], drafts: list[PropositionDisposition], law: Any
) -> tuple[str, ...]:
    return accounting_findings(
        sentence_evidence={f"{EV}#S{i}": EV for i in range(1, len(pids) + 1)},
        propositions=_props(*pids),
        non_operative=[],
        dispositions=drafts,
        correction_law=law,
    )


def _codes(findings: tuple[str, ...]) -> set[str]:
    return {f.split(":", 1)[0] for f in findings}


# --------------------------------------------------------------------------- lawful shapes


def test_one_old_to_one_new() -> None:
    assert _findings(("P1",), [_d("P1", A), _d("P1", X, "J-old")], "TARGET_SET") == ()


def test_many_old_to_one_new() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-a"), _d("P1", X, "J-b"), _d("P1", X, "J-c")]
    assert _findings(("P1",), drafts, "TARGET_SET") == ()


def test_one_old_to_many_new_carries_its_supersede_once() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-old"), _d("P2", A)]
    assert _findings(("P1", "P2"), drafts, "TARGET_SET") == ()


def test_many_old_to_many_new_the_frozen_t8_shape() -> None:
    """T8: {2 s first wait, 30 s cap} -> 5 s wait; {doubling} -> fixed; measurement supported."""
    drafts = [
        _d("P-B-wait", A),
        _d("P-B-wait", X, "JDG-cf225a3b"),
        _d("P-B-wait", X, "JDG-6dc43a9d"),
        _d("P-B-meas", S),
        _d("P-B-fixed", A),
        _d("P-B-fixed", X, "JDG-e1da6031"),
    ]
    assert _findings(("P-B-wait", "P-B-meas", "P-B-fixed"), drafts, "TARGET_SET") == ()


# --------------------------------------------------------------------------- refusals


def test_the_same_target_twice_is_refused() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-old"), _d("P2", A), _d("P2", X, "J-old")]
    found = _findings(("P1", "P2"), drafts, "TARGET_SET")
    assert "DUPLICATE_SUPERSEDE_TARGET" in _codes(found)
    assert any("J-old" in f and "P1" in f and "P2" in f for f in found)


def test_the_same_target_twice_on_one_proposition_is_refused() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-old"), _d("P1", X, "J-old")]
    assert "DUPLICATE_SUPERSEDE_TARGET" in _codes(_findings(("P1",), drafts, "TARGET_SET"))


@pytest.mark.parametrize(
    "kinds",
    [(X,), (X, X), (S, X), (A, A), (A, A, X), (S, S), (A, S)],
    ids=["supersede-alone", "supersedes-alone", "support-plus-supersede", "two-asserts",
         "two-asserts-plus-supersede", "two-supports", "assert-plus-support"],
)  # fmt: skip
def test_every_proposition_still_has_exactly_one_disposition(
    kinds: tuple[JudgmentKind, ...],
) -> None:
    drafts = [_d("P1", k, f"J-{i}" if k is X else None) for i, k in enumerate(kinds)]
    assert "CONFLICTING_DISPOSITION" in _codes(_findings(("P1",), drafts, "TARGET_SET"))


def test_an_omitted_proposition_is_refused() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-old")]
    assert "UNACCOUNTED_PROPOSITION" in _codes(_findings(("P1", "P2"), drafts, "TARGET_SET"))


def test_a_supersede_without_a_target_is_refused() -> None:
    drafts = [_d("P1", A), _d("P1", X, None)]
    assert "UNTARGETED_SUPERSEDE" in _codes(_findings(("P1",), drafts, "TARGET_SET"))


# --------------------------------------------------------------------------- the historical law


def test_the_one_target_law_is_unchanged() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-a"), _d("P1", X, "J-b")]
    found = _findings(("P1",), drafts, "ONE_TARGET")
    assert found == ("CONFLICTING_DISPOSITION: P1 (ASSERT_CLAIM, SUPERSEDE, SUPERSEDE)",)
    assert _findings(("P1",), [_d("P1", A), _d("P1", X, "J-a")], "ONE_TARGET") == ()


def test_the_default_law_is_the_historical_one() -> None:
    drafts = [_d("P1", A), _d("P1", X, "J-a"), _d("P1", X, "J-b")]
    found = accounting_findings(
        sentence_evidence={f"{EV}#S1": EV},
        propositions=_props("P1"),
        non_operative=[],
        dispositions=drafts,
    )
    assert _codes(found) == {"CONFLICTING_DISPOSITION"}


def test_source_accounting_is_unchanged_under_either_law() -> None:
    for law in ("ONE_TARGET", "TARGET_SET"):
        found = accounting_findings(
            sentence_evidence={f"{EV}#S1": EV, f"{EV}#S2": EV},
            propositions=_props("P1"),
            non_operative=[NonOperativeSentence(sentence_id=f"{EV}#S1", reason="x")],
            dispositions=[_d("P1", A)],
            correction_law=law,  # type: ignore[arg-type]
        )
        assert _codes(found) == {"DOUBLE_ACCOUNTED_SENTENCE", "UNACCOUNTED_SENTENCE"}


# --------------------------------------------------------------------------- edges


def _edge(
    pid: str, target: str, prop_addresses: tuple[str, ...], target_address: str | None
) -> CorrectionEdge:
    return CorrectionEdge(
        proposition_id=pid,
        target_judgment_id=target,
        proposition_address_ids=prop_addresses,
        target_address_id=target_address,
    )


def test_a_target_at_the_asserting_address_is_lawful() -> None:
    assert correction_edge_findings([_edge("P1", "J-a", ("ADDR-1",), "ADDR-1")]) == ()


def test_a_cross_address_target_is_refused() -> None:
    found = correction_edge_findings([_edge("P1", "J-a", ("ADDR-1",), "ADDR-2")])
    assert _codes(found) == {"CROSS_ADDRESS_SUPERSEDE"}


def test_a_target_the_response_was_not_shown_is_refused() -> None:
    found = correction_edge_findings([_edge("P1", "J-ghost", ("ADDR-1",), None)])
    assert _codes(found) == {"UNKNOWN_SUPERSEDE_TARGET"}


def test_a_supersede_on_a_proposition_asserted_nowhere_is_refused() -> None:
    found = correction_edge_findings([_edge("P1", "J-a", (), "ADDR-1")])
    assert _codes(found) == {"CROSS_ADDRESS_SUPERSEDE"}
