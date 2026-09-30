"""Counterfactual diagnostic over the recorded v6 run: DIAGNOSTIC / COUNTERFACTUAL ONLY.

It answers exactly one question: if the two DEMONSTRATED harness defects of the sealed v6
scorer were corrected, which recorded failures would remain? It is not a rescore: it reads the
frozen run and the frozen answers, runs the frozen scorer unchanged, writes nothing into the
experiment directory and never produces a standing.

The two corrections, and nothing else:

1. **Claim cardinality (oracle defect).** The sealed ranges allowed at most one claim per
   sealed proposition; production binds the model's OWN proposition inventory, and a source
   sentence may lawfully carry several model propositions. A ``CLAIM_COUNT`` / ``HELD_COUNT``
   finding that exceeds the upper bound is removed only when every guard holds:
   (a) every claim at the concern traces (claim -> creating judgment -> the model's draft ->
   its proposition -> its source sentences) to a sentence that carries a sealed proposition of
   that concern (no claim from an example, no cross-concern claim);
   (b) collapsing claims whose model propositions share a source sentence brings the count
   within the sealed bound (the surplus is a split of one sentence, not new material);
   (c) every sealed question at the claims' creating timepoint and at the finding's timepoint
   that lists a proposition of the split sentences is answered YES (semantic coverage was
   judged independently). A lower-bound (missing-claim) finding is never removed.

2. **Repeat after DECLINE (scorer defect).** The sealed check selected "drafts citing the
   redelivered document" through a SUPERSEDE's ``visible_evidence_ids``, which the production
   adapter fills with every evidence id of the request. The corrected law uses the identities
   production itself uses: drafts are selected by the address they bear on (an ASSERT's
   address; a SUPERSEDE's target claim's address); each must be refused
   ``CORRECTION_DECLINED`` naming the DECLINED set at that address; their recomputed
   equivalence key must equal that set's; and no new correction set may exist at the address.

The semantic answers stand as recorded, except where the audit rules a recorded YES wrong
(``AUDIT_RULINGS``); a NO is never turned into YES.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Final

from foundry.domain.common import FrozenModel
from foundry.domain.correction_set import CORRECTION_DECLINED, equivalence_key
from foundry.domain.evidence import sha256_of_content
from foundry.domain.semantic_judgment import AssertClaimProposal, SupersedeProposal
from foundry.domain.semantic_view import active_judgment_ids
from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS
from foundry.experiments.locus_validation_v6.evaluation import _Ledger, evaluate
from foundry.experiments.locus_validation_v6.expectations import (
    CASES,
    CORRECTIONS,
    PROPOSITIONS,
    SEMANTIC_QUESTIONS,
    SOURCE_COVERAGE,
    Timepoint,
)
from foundry.experiments.locus_validation_v6.recording import CallRecord
from foundry.experiments.locus_validation_v6.runner import LedgerRun, RunRecord

__all__ = [
    "AUDIT_RULINGS",
    "DIAGNOSTIC_LABEL",
    "Diagnostic",
    "Override",
    "Removed",
    "corrected_repeat_findings",
    "diagnose",
]

DIAGNOSTIC_LABEL: Final = (
    "DIAGNOSTIC / COUNTERFACTUAL ONLY - not a rescore of intent-v2-locus-validation-v6, whose "
    "sealed standing stays LOCUS_POLICY_NOT_VALIDATED"
)

AUDIT_RULINGS: Final[dict[str, str]] = {
    "K-CREDIT-4": "not stated by any live claim: the only candidate, "
    "claim_deadline_after_reservation_start = 48 hours, states the claim deadline (a "
    "condition on claiming); the refusal of a later claim is the consequence of missing it, a "
    "distinct operative proposition (G2 lists deadlines and effects as separate dimensions, "
    "and a claim is ONE proposition)",
}
"""Recorded YES answers the audit rules wrong. Each is applied to every claims-rule question
listing the proposition and answered YES; nothing is ever ruled from NO to YES."""

_CLAIMS_RULE_MARKER: Final = "is every one of these propositions stated by at least one live claim"
_COUNT: Final = re.compile(
    r"^CLAIM_COUNT: (\S+) has (\d+) live claims at (\S+), expected (\d+)-(\d+)$"
)
_HELD: Final = re.compile(r"^HELD_COUNT: (\d+) held assertions citing (\S+) at (\S+)$")
_Z4_SCORER: Final = "REOPENED: a repeated correction was routed"


class Removed(FrozenModel):
    case: str
    finding: str
    defect: str
    evidence: str


class Override(FrozenModel):
    question: str
    frozen: str
    to: str
    ruling: str


class Diagnostic(FrozenModel):
    label: str
    removed: tuple[Removed, ...]
    remaining_structural: dict[str, tuple[str, ...]]
    semantic_overrides: tuple[Override, ...]
    remaining_semantic_no: tuple[str, ...]
    remaining_failed_cases: tuple[str, ...]


# ------------------------------------------------------------------ provenance of a claim


def _state(run: LedgerRun, at: str):  # type: ignore[no-untyped-def]
    if at == "T1":
        return run.deltas[0].state_after
    if at == "T2":
        return run.deltas[1].state_after
    branch = "AGREE" if at in ("AGREED", "T3-AGREE") else "DECLINE"
    b = next(x for x in run.branches if x.branch == branch)
    if at in ("AGREED", "DECLINED"):
        return b.state_after_decisions
    assert b.t3 is not None
    return b.t3.state_after


def _sealed_of_sentence(evidence_id: str, text: str) -> tuple[str, ...]:
    doc = next(k for k, d in DOCUMENTS.items() if d.evidence_id == evidence_id)
    return next((a.propositions for a in SOURCE_COVERAGE[doc] if a.sentence == text), ())


def _provenance(run: LedgerRun, judgment_id: str) -> tuple[CallRecord, dict, set[str]] | None:  # type: ignore[type-arg]
    """The call, the model draft and the source sentence ids of a judgment's proposition."""
    for call in run.calls:
        if judgment_id not in call.returned_judgment_ids or call.model_payload is None:
            continue
        drafts = call.model_payload.get("drafts", [])
        index = call.returned_judgment_ids.index(judgment_id)
        if index >= len(drafts):
            return None
        draft = drafts[index]
        props = {p["proposition_id"]: p for p in call.model_payload.get("propositions", [])}
        prop = props.get(draft.get("proposition_id", ""))
        return call, draft, set(prop["sentence_ids"]) if prop else set()
    return None


def _sentence_text(call: CallRecord) -> dict[str, tuple[str, str]]:
    rendered = json.loads(call.rendered_request)
    return {
        s["sentence_id"]: (s["evidence_id"], s["text"])
        for s in rendered.get("sentences_to_account", ())
    }


def _timepoint_of(call: CallRecord) -> Timepoint:
    if call.t == 3:
        return "T3-AGREE" if call.branch == "AGREE" else "T3-DECLINE"
    return "T1" if call.t == 1 else "T2"


def _units(sentence_sets: list[set[str]]) -> int:
    """Claims whose source sentences overlap collapse into one unit."""
    groups: list[set[str]] = []
    for sentences in sentence_sets:
        merged = [g for g in groups if g & sentences]
        union = set(sentences).union(*merged) if merged else set(sentences)
        groups = [g for g in groups if g not in merged] + [union]
    return len(groups)


def _explain_surplus(
    lg: _Ledger,
    concern: str,
    judgment_ids: list[str],
    bound: int,
    at: str,
    answers: Mapping[str, str],
) -> str | None:
    """Why the surplus is a faithful split (``None`` when any guard fails)."""
    sentence_sets: list[set[str]] = []
    carried: set[str] = set()
    creating: set[Timepoint] = set()
    concern_props = {p.id for p in PROPOSITIONS if p.ledger == lg.ledger and p.concern == concern}
    for jid in judgment_ids:
        found = _provenance(lg.run, jid)
        if found is None:
            return None
        call, draft, sentences = found
        if draft.get("kind") != "ASSERT_CLAIM" or not sentences:
            return None
        text = _sentence_text(call)
        sealed = {p for sid in sentences if sid in text for p in _sealed_of_sentence(*text[sid])}
        if not sealed & concern_props:
            return None  # guard (a): the claim carries no sealed meaning of this concern
        sentence_sets.append(sentences)
        carried |= sealed & concern_props
        creating.add(_timepoint_of(call))
    if _units(sentence_sets) > bound:
        return None  # guard (b): more material than the sealed propositions allow
    gates = [
        q.id
        for q in SEMANTIC_QUESTIONS
        if q.ledger == lg.ledger
        and q.after in {*creating, at}
        and any(f"{p}:" in q.question for p in carried)
    ]
    if not gates or any(answers.get(g) != "YES" for g in gates):
        return None  # guard (c): coverage not independently judged complete
    return (
        f"{len(judgment_ids)} claims collapse to {_units(sentence_sets)} source units "
        f"(bound {bound}); gates {sorted(gates)} YES"
    )


def _count_removal(lg: _Ledger, finding: str, answers: Mapping[str, str]) -> str | None:
    m = _COUNT.match(finding)
    if m:
        concern, got, at, _, high = (
            m.group(1),
            int(m.group(2)),
            m.group(3),
            m.group(4),
            int(m.group(5)),
        )
        if got <= high or concern not in lg.addresses or at not in lg.states:
            return None  # a missing claim is never excused; another ledger's finding
        address = lg.addresses.get(concern)
        state = _state(lg.run, at).semantic
        active = active_judgment_ids(state)
        jids = [
            c.created_by_judgment_id
            for c in state.claims.values()
            if c.address_id == address and c.created_by_judgment_id in active
        ]
        return _explain_surplus(lg, concern, jids, high, at, answers)
    m = _HELD.match(finding)
    if m:
        got, doc, concern = int(m.group(1)), m.group(2), m.group(3)
        items = [
            g
            for g in CORRECTIONS
            if g.ledger == lg.ledger and g.document == doc and g.concern == concern
        ]
        if not items or concern not in lg.addresses:
            return None
        bound = len(items[0].replacements)
        if got <= bound:
            return None
        at = items[0].at
        state = _state(lg.run, at).semantic
        address = lg.addresses.get(concern)
        held = [
            j
            for r in state.correction_sets.values()
            if r.address_id == address and r.status == "PENDING"
            for j in r.assertion_judgment_ids
        ]
        return _explain_surplus(lg, concern, held, bound, at, answers)
    return None


# ------------------------------------------------------------------ the corrected repeat law


def corrected_repeat_findings(run: RunRecord) -> tuple[str, ...]:
    out: list[str] = []
    (ledger_run,) = [lg for lg in run.ledgers if lg.ledger == "dense"]
    lg = _Ledger(ledger_run)
    for g in CORRECTIONS:
        if g.outcome != "SUPPRESSED_AS_DECLINED":
            continue
        address = lg.addresses.get(g.concern)
        before = _state(ledger_run, "DECLINED" if g.at == "T3-DECLINE" else "AGREED").semantic
        state = _state(ledger_run, g.at)
        semantic = state.semantic
        declined = [
            r
            for r in before.correction_sets.values()
            if r.address_id == address and r.status == "DECLINED"
        ]
        new = [
            r
            for r in semantic.correction_sets.values()
            if r.address_id == address and r.correction_set_id not in before.correction_sets
        ]
        if new:
            out.append(f"REOPENED: {len(new)} new correction set(s) at {g.concern}")
        if len(declined) != 1:
            out.append(f"REOPENED: {len(declined)} declined sets at {g.concern}")
            continue
        record = declined[0]
        claims_by_judgment = {c.created_by_judgment_id: c for c in semantic.claims.values()}
        members: list[tuple[str, tuple[str, ...], object]] = []
        for d in (x for x in lg.drafts if x.at == g.at and x.call == 2):
            p = d.judgment.proposal
            if isinstance(p, AssertClaimProposal) and p.address_id == address:
                members.append((d.route, d.reasons, p))
            elif isinstance(p, SupersedeProposal):
                target = claims_by_judgment.get(p.target_judgment_id)
                if target is not None and target.address_id == address:
                    members.append((d.route, d.reasons, p))
        for route, reasons, _ in members:
            if reasons[:2] != (CORRECTION_DECLINED, record.correction_set_id):
                out.append(f"REOPENED: a repeated member was routed {route} {reasons[:2]}")
        asserts = [p for _, _, p in members if isinstance(p, AssertClaimProposal)]
        targets = [p.target_judgment_id for _, _, p in members if isinstance(p, SupersedeProposal)]
        if asserts and targets:
            hashes = {
                sha256_of_content(semantic.evidence[e].content)
                for p in asserts
                for e in p.evidence_ids
                if e in semantic.evidence
            }
            key = equivalence_key(state.project_id, str(address), targets, sorted(hashes))
            if key != record.equivalence_key:
                out.append(
                    f"REOPENED: repeat equivalence {key} != declined {record.equivalence_key}"
                )
    return tuple(out)


# ------------------------------------------------------------------ the diagnostic


def _overrides(answers: Mapping[str, str]) -> tuple[Override, ...]:
    out = []
    for q in SEMANTIC_QUESTIONS:
        if _CLAIMS_RULE_MARKER not in q.question or answers.get(q.id) != "YES":
            continue
        for pid, ruling in AUDIT_RULINGS.items():
            listed = q.question.split(_CLAIMS_RULE_MARKER, 1)[1]
            if f"{pid}:" in listed.split("]", 1)[0]:
                out.append(Override(question=q.id, frozen="YES", to="NO", ruling=f"{pid} {ruling}"))
    return tuple(out)


def diagnose(run: RunRecord, answers: Mapping[str, str]) -> Diagnostic:
    overrides = _overrides(answers)
    judged = dict(answers) | {o.question: o.to for o in overrides}
    results = evaluate(run)  # the frozen scorer, unchanged
    ledgers = {lg.ledger: _Ledger(lg) for lg in run.ledgers if lg.status == "COMPLETED"}
    removed: list[Removed] = []
    remaining: dict[str, tuple[str, ...]] = {}
    repeat = corrected_repeat_findings(run)
    for case, result in results.items():
        kept: list[str] = []
        for finding in result.findings:
            why = None
            defect = ""
            for lg in ledgers.values():
                why = _count_removal(lg, finding, judged)
                if why is not None:
                    defect = "CLAIM_CARDINALITY_ORACLE"
                    break
            if why is None and finding.startswith(_Z4_SCORER) and not repeat:
                why, defect = (
                    "the corrected repeat law finds no reopening",
                    "Z4_VISIBLE_EVIDENCE_SCORER",
                )
            if why is None:
                kept.append(finding)
            else:
                removed.append(Removed(case=case, finding=finding, defect=defect, evidence=why))
        if case == "Z4-REPEAT-SUPPRESSED":
            kept += list(repeat)
        if kept:
            remaining[case] = tuple(kept)
    no = tuple(sorted(q for q, a in judged.items() if a != "YES"))
    failed = sorted(
        c.id for c in CASES if c.id in remaining or any(judged.get(q) != "YES" for q in c.semantic)
    )
    return Diagnostic(
        label=DIAGNOSTIC_LABEL,
        removed=tuple(removed),
        remaining_structural=remaining,
        semantic_overrides=overrides,
        remaining_semantic_no=no,
        remaining_failed_cases=tuple(failed),
    )
