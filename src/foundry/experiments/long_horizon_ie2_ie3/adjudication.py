"""Independent adjudication packets and the single all-or-nothing standing (design §14, §16).

Each sealed question gets one frozen packet built from the run at exactly the question's turn
and timepoint:

* an IE2 locus question: the section text of that locus at that version, and the claims at
  its designated address after the IE2 call and the authority step (live, with the version
  that asserted them, and no-longer-live);
* an IE2 accounting question: the sentences the Call 2 had to account for, and the
  propositions and non-operative sentences the model returned;
* an IE3 locus question: that locus's live claims and the graph objects grounded on its
  claims after that turn's graph synthesis (current and retired, with kind, text and basis).

IE2 and IE3 answers are kept apart. The adjudicator answers YES or NO with a reason; YES is
a pass for every question. Nothing here edits a question or an expectation.
"""

from __future__ import annotations

import json
from typing import Any, Final, Literal

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_view import derive_view
from foundry.experiments.long_horizon_ie2_ie3 import corpus, protocol
from foundry.experiments.long_horizon_ie2_ie3.evaluation import (
    CheckResult,
    _current,
    _derived_from,
    _graph_objects,
    _Run,
)
from foundry.experiments.long_horizon_ie2_ie3.expectations import (
    ADJUDICATION_QUESTIONS,
    AdjudicationQuestion,
)
from foundry.experiments.long_horizon_ie2_ie3.runner import RunRecord

__all__ = ["STANDINGS", "Standing", "adjudication_bundle", "standing"]

STANDINGS: Final = ("LONG_HORIZON_IE2_IE3_VALIDATED", "LONG_HORIZON_IE2_IE3_NOT_VALIDATED")


def _claims_packet(r: _Run, seq: int, address: str | None) -> dict[str, Any]:
    state = r.state(seq)
    live = set(derive_view(state.semantic).effective_evidence)
    rows = []
    for cid, claim in sorted(state.semantic.claims.items()):
        if claim.address_id != address:
            continue
        judgment = state.semantic.judgments.get(claim.created_by_judgment_id)
        rows.append(
            {
                "claim_id": cid,
                "live": cid in live,
                "predicate": claim.predicate,
                "value": claim.value.model_dump(mode="json"),
                "asserted_citing": list(judgment.visible_evidence_ids) if judgment else [],
            }
        )
    subject = (
        state.semantic.addresses[address].subject
        if address is not None and address in state.semantic.addresses
        else None
    )
    return {"address_id": address, "subject": subject, "claims": rows}


def _graph_packet(r: _Run, seq: int, locus: str) -> dict[str, Any]:
    state = r.state(seq)
    address = r.designated.get(locus)
    locus_claims = {c for c, x in state.semantic.claims.items() if x.address_id == address}
    live = set(derive_view(state.semantic).effective_evidence)
    rows = []
    for oid, obj in sorted(_graph_objects(state).items()):
        basis = _derived_from(obj)
        if not set(basis) & locus_claims:
            continue
        text = getattr(obj, "statement", None) or getattr(obj, "mission", None)
        rows.append(
            {
                "object_id": oid,
                "kind": obj.kind.value,
                "current": _current(obj),
                "text": text,
                "derived_from": list(basis),
            }
        )
    return {
        "locus_live_claims": [
            {"claim_id": c, "value": state.semantic.claims[c].value.model_dump(mode="json")}
            for c in sorted(locus_claims & live)
        ],
        "graph_objects": rows,
    }


def _packet(r: _Run, q: AdjudicationQuestion) -> dict[str, Any]:
    turn = next((x for x in r.run.turns if x.t == q.t), None)
    if turn is None:
        return {"unavailable": f"T{q.t} NOT_RUN"}
    if turn.status != "COMPLETED":
        return {"unavailable": f"T{q.t} {turn.status}"}
    if q.timepoint == "IE2_CALL_2":
        calls = [c for c in (turn.ie2.calls if turn.ie2 else ()) if c.call == 2]
        if not calls:
            return {"unavailable": "no Call 2"}
        rendered = json.loads(calls[0].rendered_request)
        return {
            "sentences_to_account": rendered.get("sentences_to_account", []),
            "model_payload": calls[0].model_payload,
            "refusal_findings": list(calls[0].refusal_findings),
        }
    assert q.locus is not None
    if q.timepoint == "AFTER_IE2_AND_AUTHORITY":
        assert turn.seq_after_authority is not None
        return {
            "source_section": corpus.section_text(q.t, q.locus),
            **_claims_packet(r, turn.seq_after_authority, r.designated.get(q.locus)),
        }
    assert turn.seq_after_ie3 is not None
    return {
        "source_section": corpus.section_text(q.t, q.locus),
        **_graph_packet(r, turn.seq_after_ie3, q.locus),
    }


def adjudication_bundle(run: RunRecord) -> dict[str, Any]:
    r = _Run(run)
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "items": [
            {**q.model_dump(mode="json"), "packet": _packet(r, q)} for q in ADJUDICATION_QUESTIONS
        ],
    }


class Standing(FrozenModel):
    standing: Literal["LONG_HORIZON_IE2_IE3_VALIDATED", "LONG_HORIZON_IE2_IE3_NOT_VALIDATED"]
    failed_checks: tuple[str, ...]
    failed_ie2_questions: tuple[str, ...]
    failed_ie3_questions: tuple[str, ...]
    unanswered: tuple[str, ...]
    ie2_mechanical_passed: bool
    ie3_mechanical_passed: bool
    ie2_semantic_passed: bool
    ie3_semantic_passed: bool


def standing(checks: dict[str, CheckResult], answers: dict[str, str]) -> Standing:
    failed = tuple(sorted(n for n, c in checks.items() if not c.passed))
    unanswered = tuple(q.id for q in ADJUDICATION_QUESTIONS if q.id not in answers)
    no = {qid for qid, a in answers.items() if a.strip().upper() != "YES"}
    ie2_no = tuple(q.id for q in ADJUDICATION_QUESTIONS if q.layer == "IE2" and q.id in no)
    ie3_no = tuple(q.id for q in ADJUDICATION_QUESTIONS if q.layer == "IE3" and q.id in no)
    ok = not failed and not unanswered and not ie2_no and not ie3_no
    return Standing(
        standing=STANDINGS[0] if ok else STANDINGS[1],
        failed_checks=failed,
        failed_ie2_questions=ie2_no,
        failed_ie3_questions=ie3_no,
        unanswered=unanswered,
        ie2_mechanical_passed=not any(n.endswith("IE2") for n in failed),
        ie3_mechanical_passed=not any(n.endswith("IE3") for n in failed),
        ie2_semantic_passed=not ie2_no,
        ie3_semantic_passed=not ie3_no,
    )
