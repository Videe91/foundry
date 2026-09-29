"""Deterministic evaluation of the long-horizon run (design §7-§13). No wording is read.

Every boundary state is the ledger prefix up to that turn's recorded sequence, replayed. Per
turn, one IE2 check-set (``T<nn>-IE2``) and one IE3 check-set (``T<nn>-IE3``); each passes
only with no finding. Run-wide: ``RUN-INTEGRITY`` and ``SOURCE-COVERAGE``. Wording questions
belong to the independent adjudication, never to this module.

IE2 tags: ``IE2_REFUSED`` ``IE2_FAILED`` ``CALL_SHAPE`` ``ACCOUNTING_RECOMPUTED``
``UNRECORDED_PAYLOAD`` ``OVER_SPLIT`` ``UNDER_SPLIT`` ``UNDESIGNATED`` ``WRONG_BIND``
``MISSING_BIND`` ``CLAIM_COUNT`` ``FOREIGN_CLAIM`` ``CONTROL_CLAIM_REMOVED``
``UNEXPECTED_SUPERSEDE`` ``MISSING_SUPERSEDE`` ``WRONG_SUPERSEDE`` ``PENDING_LEFT``
``UNEXPECTED_CONFLICT`` ``REJECTED_ADMISSION`` ``NON_CANONICAL_FACET`` ``REVERT_REVIVED``
``EXISTING_CANCELLATION_LOST``.

IE3 tags: ``IE3_REFUSED`` ``IE3_NO_CALL`` ``CALL_SHAPE`` ``ROOT_COUNT`` ``ROOT_CHANGED``
``ROOT_NOT_PROPOSED`` ``ROOT_STALE`` ``ROOT_PROVENANCE`` ``ROOT_UNGROUNDED`` ``UNCOVERED_CLAIM``
``STALE_RETAINED`` ``DUPLICATE_OBJECT`` ``UNAFFECTED_CHANGED`` ``FALSE_NEW``
``WRONG_REPLACEMENT`` ``INCORRECT_GAP`` ``UNLAWFUL_KIND`` ``NO_SERVING_PATH``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from functools import cache
from typing import Any, Final

from foundry.application.replay import replay
from foundry.domain.common import FrozenModel, LifecycleStatus, RelationType
from foundry.domain.intent_graph import IE3_GRAPH_NODE_KINDS
from foundry.domain.intent_view import derive_intent_view
from foundry.domain.proposition_accounting import (
    AccountedProposition,
    NonOperativeSentence,
    PropositionDisposition,
    accounting_findings,
)
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_identity import canonical_facet
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentKind,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.experiments.long_horizon_bounded.authority import AuthorizationOutcome
from foundry.experiments.long_horizon_bounded.timeline import LOCI
from foundry.experiments.long_horizon_ie2_ie3 import protocol
from foundry.experiments.long_horizon_ie2_ie3.expectations import (
    LAWFUL_NODE_KINDS,
    TURNS,
    source_coverage_findings,
)
from foundry.experiments.long_horizon_ie2_ie3.recording import IE2CallRecord
from foundry.experiments.long_horizon_ie2_ie3.runner import RunRecord, TurnRecord

__all__ = ["CheckResult", "Evaluation", "evaluate", "first_divergence", "turn_metrics"]

_GRAPH_KINDS: Final = frozenset(k for k in IE3_GRAPH_NODE_KINDS if k is not SemanticKind.INTENT)


class CheckResult(FrozenModel):
    name: str
    passed: bool
    findings: tuple[str, ...]


class Evaluation(FrozenModel):
    checks: dict[str, CheckResult]
    metrics: tuple[dict[str, Any], ...]
    root_id: str | None
    first_divergence: dict[str, Any] | None


class _Out:
    def __init__(self) -> None:
        self.by: dict[str, list[str]] = defaultdict(list)

    def add(self, name: str, tag: str, detail: str) -> None:
        self.by[name].append(f"{tag}: {detail}")


class _Run:
    """Replayed boundary states and structural lookups over one run."""

    def __init__(self, run: RunRecord) -> None:
        self.run = run
        self.address_locus: dict[str, str] = {
            d.address_id: locus
            for locus, d in run.designations.items()
            if d.status == "DESIGNATED" and d.address_id is not None
        }
        self.designated: dict[str, str] = {
            locus: d.address_id
            for locus, d in run.designations.items()
            if d.status == "DESIGNATED" and d.address_id is not None
        }

    @cache  # noqa: B019 - one evaluation, a handful of sequences
    def state(self, seq: int) -> IntentState:
        return replay(self.run.project_id, [e for e in self.run.events if e.sequence <= seq])


def _live_claims(state: IntentState) -> frozenset[str]:
    return frozenset(derive_view(state.semantic).effective_evidence)


def _locus_of_evidence(evidence_id: str) -> str:
    return evidence_id[5] if evidence_id.startswith("EV-O-") else "?"


def _graph_objects(state: IntentState) -> dict[str, Any]:
    return {
        oid: o
        for oid, o in state.objects.items()
        if o.kind in IE3_GRAPH_NODE_KINDS and o.project_id == protocol.PROJECT_ID
    }


def _current(obj: Any) -> bool:
    return bool(
        obj.lifecycle is LifecycleStatus.ACTIVE
        and obj.authority.value
        not in (
            "REJECTED",
            "SUPERSEDED",
        )
    )


def _derived_from(obj: Any) -> tuple[str, ...]:
    return tuple(r.target_id for r in obj.relations if r.relation_type is RelationType.DERIVED_FROM)


def _serves(obj: Any) -> tuple[str, ...]:
    return tuple(r.target_id for r in obj.relations if r.relation_type is RelationType.SERVES)


def recompute_accounting(call: IE2CallRecord) -> tuple[str, ...]:
    """The production accounting law over what one Call 2 was shown and returned."""
    rendered = json.loads(call.rendered_request)
    sentences = {
        s["sentence_id"]: s["evidence_id"] for s in rendered.get("sentences_to_account", ())
    }
    payload = call.model_payload or {}
    return accounting_findings(
        sentence_evidence=sentences,
        propositions=[
            AccountedProposition.model_validate(p) for p in payload.get("propositions", ())
        ],
        non_operative=[
            NonOperativeSentence.model_validate(n) for n in payload.get("non_operative", ())
        ],
        dispositions=[
            PropositionDisposition(
                proposition_id=d["proposition_id"],
                kind=JudgmentKind(d["kind"]),
                evidence_ids=tuple(d.get("evidence_ids", ())),
            )
            for d in payload.get("drafts", ())
            if "proposition_id" in d
        ],
    )


# --------------------------------------------------------------------------- IE2


def _ie2(r: _Run, turn: TurnRecord, out: _Out) -> None:
    name = f"T{turn.t:02d}-IE2"
    expect = TURNS[turn.t - 1]
    ie2 = turn.ie2
    if ie2 is None or turn.seq_after_authority is None:
        out.add(name, "IE2_FAILED", f"T{turn.t} produced no IE2 record")
        return
    if ie2.status == "REFUSED":
        out.add(name, "IE2_REFUSED", ie2.error or "structural refusal")
    elif ie2.status != "COMPLETED":
        out.add(name, "IE2_FAILED", ie2.error or ie2.status)
    if tuple(c.call for c in ie2.calls) != (1, 2):
        out.add(name, "CALL_SHAPE", f"calls {[c.call for c in ie2.calls]}")
    for c in ie2.calls:
        if c.refusal_findings:
            continue
        if c.call == 2:
            if c.model_payload is None:
                out.add(name, "UNRECORDED_PAYLOAD", "call 2")
            else:
                for finding in recompute_accounting(c):
                    out.add(name, "ACCOUNTING_RECOMPUTED", finding)
    before = r.state(turn.seq_start)
    after = r.state(turn.seq_after_authority)
    for d in (*ie2.call_1, *ie2.call_2):
        if d.route == "REJECT":
            out.add(name, "REJECTED_ADMISSION", f"{d.judgment_id} {d.reasons}")

    # addresses and bindings
    new_addresses = set(after.semantic.addresses) - set(before.semantic.addresses)
    judgments = after.semantic.judgments
    placed: dict[str, set[str]] = defaultdict(set)  # address -> loci of evidence placed there
    bound_items: set[str] = set()
    for d in ie2.call_1:
        if d.route != "APPLY":
            continue
        proposal = judgments[d.judgment_id].proposal
        if isinstance(proposal, CreateAddressProposal):
            address: str = next(
                a
                for a, x in after.semantic.addresses.items()
                if x.created_by_judgment_id == d.judgment_id
            )
        elif isinstance(proposal, BindToAddressProposal):
            address = proposal.address_id
        else:
            continue
        for ev in proposal.candidate.evidence_ids:
            placed[address].add(_locus_of_evidence(ev))
            bound_items.add(ev)
    for held, loci in sorted(placed.items()):
        if len(loci) > 1:
            out.add(name, "UNDER_SPLIT", f"address {held} holds loci {sorted(loci)}")
    if turn.t == 1:
        if len(new_addresses) != 12:
            out.add(name, "OVER_SPLIT" if len(new_addresses) > 12 else "UNDER_SPLIT",
                    f"{len(new_addresses)} addresses formed at T1")  # fmt: skip
        undesignated = [x for x in LOCI if x not in r.designated]
        if undesignated or len(set(r.designated.values())) != len(r.designated):
            out.add(name, "UNDESIGNATED", f"undesignated {undesignated}")
    else:
        for new_id in sorted(new_addresses):
            out.add(name, "OVER_SPLIT", f"new address {new_id} at T{turn.t}")
        for held, loci in sorted(placed.items()):
            for locus in loci:
                if r.designated.get(locus) != held:
                    out.add(name, "WRONG_BIND", f"locus {locus} placed at {held}")
    items = {f"EV-O-{locus}{turn.t:02d}" for locus in LOCI}
    for missing in sorted(items - bound_items):
        out.add(name, "MISSING_BIND", missing)

    # claims
    live_before, live_after = _live_claims(before), _live_claims(after)
    created = set(after.semantic.claims) - set(before.semantic.claims)
    per_locus: dict[str, int] = defaultdict(int)
    for cid in created:
        at = r.address_locus.get(after.semantic.claims[cid].address_id)
        if at is None:
            out.add(name, "FOREIGN_CLAIM", f"{cid} at undesignated address")
            continue
        per_locus[at] += 1
    for locus in LOCI:
        lo, hi = expect.new_claims[locus]
        n = per_locus.get(locus, 0)
        if not lo <= n <= hi:
            out.add(name, "CLAIM_COUNT", f"locus {locus}: {n} new claims, expected {lo}..{hi}")
    removed = live_before - live_after
    for cid in sorted(removed):
        at = r.address_locus.get(after.semantic.claims[cid].address_id)
        if at != expect.target_locus or not expect.supersession_required:
            out.add(name, "CONTROL_CLAIM_REMOVED", f"{cid} at locus {at}")

    # supersession and conflicts
    supersedes = [
        d for d in ie2.call_2 if isinstance(judgments[d.judgment_id].proposal, SupersedeProposal)
    ]
    if not expect.supersession_required:
        for d in supersedes:
            out.add(name, "UNEXPECTED_SUPERSEDE", f"{d.judgment_id} routed {d.route}")
    else:
        agreed = [a for a in ie2.authority if a.outcome is AuthorizationOutcome.AGREED]
        wrong = [
            a
            for a in ie2.authority
            if a.outcome
            in (
                AuthorizationOutcome.AMBIGUOUS_PROPOSALS,
                AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED,
            )
        ]
        if not agreed:
            out.add(name, "MISSING_SUPERSEDE", f"no eligible supersession at {expect.target_locus}")
        for a in wrong:
            out.add(name, "WRONG_SUPERSEDE", f"{a.outcome.value} target {a.target_judgment_id}")
    pending = derive_view(after.semantic).pending_judgment_ids
    if pending:
        out.add(name, "PENDING_LEFT", f"{list(pending)}")
    for d in (*ie2.call_1, *ie2.call_2):
        if isinstance(judgments[d.judgment_id].proposal, ConflictsWithProposal):
            out.add(name, "UNEXPECTED_CONFLICT", d.judgment_id)
    for new_id in sorted(new_addresses):
        formed = after.semantic.addresses[new_id]
        if formed.facet != canonical_facet(formed.subject):
            out.add(name, "NON_CANONICAL_FACET", f"{new_id}: {formed.facet!r}")

    # historical invariants
    if turn.t == 8 and "B" in r.designated:
        b = r.designated["B"]
        t1_claims = [
            cid
            for cid in r.state(r.run.turns[0].seq_after_authority or 0).semantic.claims
            if r.state(r.run.turns[0].seq_after_authority or 0).semantic.claims[cid].address_id == b
        ]
        revived = [cid for cid in t1_claims if cid in live_after]
        if revived:
            out.add(name, "REVERT_REVIVED", f"T1 claims live again: {revived}")
    if turn.t == 9 and "H" in r.designated:
        h = r.designated["H"]
        lost = [
            cid
            for cid in live_before
            if before.semantic.claims[cid].address_id == h and cid not in live_after
        ]
        if lost:
            out.add(name, "EXISTING_CANCELLATION_LOST", f"{lost}")
    for cid in created:
        judgment = judgments.get(after.semantic.claims[cid].created_by_judgment_id)
        if judgment is not None and not isinstance(judgment.proposal, AssertClaimProposal):
            out.add(name, "FOREIGN_CLAIM", f"{cid} not asserted by ASSERT_CLAIM")


# --------------------------------------------------------------------------- IE3


def _reaches(objects: dict[str, Any], start: str, root: str) -> bool:
    seen: set[str] = set()
    frontier = [start]
    while frontier:
        oid = frontier.pop()
        if oid == root:
            return True
        if oid in seen or oid not in objects or not _current(objects[oid]):
            continue
        seen.add(oid)
        frontier.extend(_serves(objects[oid]))
    return False


def _loci(r: _Run, state: IntentState, claim_ids: Iterable[str]) -> set[str]:
    return {
        r.address_locus.get(state.semantic.claims[c].address_id, "?")
        for c in claim_ids
        if c in state.semantic.claims
    }


def _ie3(r: _Run, turn: TurnRecord, out: _Out, root: dict[str, Any]) -> None:
    name = f"T{turn.t:02d}-IE3"
    ie3 = turn.ie3
    if ie3 is None or turn.seq_after_ie3 is None or turn.seq_after_authority is None:
        out.add(name, "IE3_NO_CALL", f"T{turn.t} produced no IE3 record")
        return
    if ie3.status != "APPLIED":
        out.add(name, "IE3_REFUSED" if ie3.status == "REFUSED" else "IE3_NO_CALL",
                f"{ie3.status}: {ie3.error}")  # fmt: skip
    if len(ie3.calls) != 1:
        out.add(name, "CALL_SHAPE", f"{len(ie3.calls)} provider executions")
    for c in ie3.calls:
        if (c.provider, c.model, c.task, c.tier) != (
            protocol.IE3_PROVIDER,
            protocol.IE3_MODEL,
            protocol.IE3_TASK,
            "REASONER",
        ):
            out.add(name, "CALL_SHAPE", f"executed {c.provider}/{c.model} {c.task} {c.tier}")
    before = r.state(turn.seq_after_authority)
    after = r.state(turn.seq_after_ie3)
    turn_start = r.state(turn.seq_start)
    objs_before, objs_after = _graph_objects(before), _graph_objects(after)
    current = {oid: o for oid, o in objs_after.items() if _current(o)}
    intents = [oid for oid, o in current.items() if o.kind is SemanticKind.INTENT]
    view = derive_intent_view(after)
    stale = frozenset(view.stale_ids)

    # root lifecycle
    if len(intents) != 1:
        out.add(name, "ROOT_COUNT", f"{len(intents)} current Intents: {intents}")
    if turn.t == 1 and len(intents) == 1:
        root["id"] = intents[0]
        root["edges"] = {
            e.parent_id for e in after.semantic.derivations if e.child_id == intents[0]
        }
    root_id = root.get("id")
    if root_id is not None:
        if intents != [root_id]:
            out.add(name, "ROOT_CHANGED", f"current Intents {intents}, T1 root {root_id}")
        obj = objs_after.get(root_id)
        if obj is None or not _current(obj):
            out.add(name, "ROOT_CHANGED", f"T1 root {root_id} is not current")
        elif obj.authority.value != "PROPOSED":
            out.add(name, "ROOT_NOT_PROPOSED", obj.authority.value)
        if root_id in stale:
            out.add(name, "ROOT_STALE", f"{root_id} is stale in the bounded view")
        edges = {e.parent_id for e in after.semantic.derivations if e.child_id == root_id}
        if edges != root["edges"]:
            out.add(name, "ROOT_PROVENANCE", f"edges {sorted(edges)} != T1 {sorted(root['edges'])}")
        if not root["edges"]:
            out.add(name, "ROOT_UNGROUNDED", f"{root_id} derives from nothing")
        if any(r.retired_object_id == root_id for r in after.intent_synthesis.retirements):
            out.add(name, "ROOT_CHANGED", "the root was retired")

    # coverage, staleness, duplicates, kinds, serving path
    live = _live_claims(after)
    nodes = {oid: o for oid, o in current.items() if o.kind is not SemanticKind.INTENT}
    for cid in sorted(live):
        if not any(cid in _derived_from(o) for o in nodes.values()):
            out.add(name, "UNCOVERED_CLAIM", f"{cid} (locus {_loci(r, after, [cid])})")
    for oid in sorted(nodes):
        if oid in stale:
            out.add(name, "STALE_RETAINED", f"{oid} ({nodes[oid].kind.value}) is current and stale")
        if nodes[oid].kind.value not in LAWFUL_NODE_KINDS:
            out.add(name, "UNLAWFUL_KIND", f"{oid} is a {nodes[oid].kind.value}")
        if root_id is not None and not _reaches(current, oid, root_id):
            out.add(name, "NO_SERVING_PATH", f"{oid} does not reach the root through current nodes")
    by_claim_kind: dict[tuple[str, str], list[str]] = defaultdict(list)
    for oid, o in nodes.items():
        for cid in _derived_from(o):
            if cid in live:
                by_claim_kind[(cid, o.kind.value)].append(oid)
    for (cid, kind), oids in sorted(by_claim_kind.items()):
        if len(oids) > 1:
            out.add(name, "DUPLICATE_OBJECT", f"{len(oids)} current {kind}s derive from {cid}")

    # preservation, false NEW, replacements, gaps (turn deltas)
    stale_before = frozenset(derive_intent_view(before).stale_ids)
    for oid, o in objs_before.items():
        if _current(o) and oid not in stale_before and objs_after.get(oid) != o:
            out.add(name, "UNAFFECTED_CHANGED", f"{oid} changed or retired while not stale")
    retirements = [
        x
        for x in after.intent_synthesis.retirements
        if x not in before.intent_synthesis.retirements
    ]
    replaced_by = {x.replaced_by_object_id for x in retirements}
    claims_new = set(after.semantic.claims) - set(turn_start.semantic.claims)
    created = [oid for oid in objs_after if oid not in objs_before]
    if turn.t > 1:
        for oid in created:
            o = objs_after[oid]
            if o.kind is SemanticKind.INTENT:
                continue
            if oid in replaced_by:
                continue
            if not set(_derived_from(o)) & claims_new:
                out.add(name, "FALSE_NEW", f"{oid} ({o.kind.value}) grounds on no new claim")
    for x in retirements:
        old, new = objs_after.get(x.retired_object_id), objs_after.get(x.replaced_by_object_id)
        if old is None or new is None:
            out.add(
                name, "WRONG_REPLACEMENT", f"{x.retired_object_id} -> {x.replaced_by_object_id}"
            )
            continue
        old_loci = _loci(r, after, _derived_from(old))
        new_loci = _loci(r, after, _derived_from(new))
        if not new_loci <= old_loci:
            out.add(name, "WRONG_REPLACEMENT", f"{x.retired_object_id} ({sorted(old_loci)}) "
                    f"replaced by {x.replaced_by_object_id} ({sorted(new_loci)})")  # fmt: skip
    for gid in sorted(set(after.gaps) - set(before.gaps)):
        out.add(name, "INCORRECT_GAP", f"{gid}: {after.gaps[gid].description[:160]!r}")


# --------------------------------------------------------------------------- metrics


def turn_metrics(r: _Run, turn: TurnRecord, root_id: str | None) -> dict[str, Any]:
    m: dict[str, Any] = {"t": turn.t, "status": turn.status}
    if turn.seq_after_ie3 is None or turn.seq_after_authority is None or turn.ie2 is None:
        return m
    start, mid, end = (
        r.state(turn.seq_start),
        r.state(turn.seq_after_authority),
        r.state(turn.seq_after_ie3),
    )
    judgments = mid.semantic.judgments
    kinds = [judgments[d.judgment_id].proposal.kind.value for d in turn.ie2.call_2]
    live = _live_claims(mid)
    m["ie2"] = {
        "status": turn.ie2.status,
        "addresses": len(mid.semantic.addresses),
        "addresses_created": len(set(mid.semantic.addresses) - set(start.semantic.addresses)),
        "bindings": sum(
            1
            for d in turn.ie2.call_1
            if isinstance(judgments[d.judgment_id].proposal, BindToAddressProposal)
        ),
        "live_claims": len(live),
        "not_live_claims": len(set(mid.semantic.claims) - live),
        "supports": kinds.count("SUPPORTS_CLAIM"),
        "asserts": kinds.count("ASSERT_CLAIM"),
        "supersedes": kinds.count("SUPERSEDE"),
        "conflicts": kinds.count("CONFLICTS_WITH"),
        "agreed": sum(1 for a in turn.ie2.authority if a.outcome is AuthorizationOutcome.AGREED),
        "call_ms": [c.wall_clock_ms for c in turn.ie2.calls],
        "request_chars": [len(c.rendered_request) for c in turn.ie2.calls],
        "refused": bool(any(c.refusal_findings for c in turn.ie2.calls)),
    }
    objs = _graph_objects(end)
    current = {oid: o for oid, o in objs.items() if _current(o)}
    before_objs = _graph_objects(mid)
    retirements = [
        x for x in end.intent_synthesis.retirements if x not in mid.intent_synthesis.retirements
    ]
    ie3 = turn.ie3
    result = ie3.result if ie3 is not None else None
    counts: dict[str, int] = defaultdict(int)
    for o in current.values():
        counts[o.kind.value] += 1
    call = ie3.calls[0] if ie3 is not None and ie3.calls else None
    m["ie3"] = {
        "status": ie3.status if ie3 is not None else None,
        "route": ie3.route if ie3 is not None else None,
        "objects_total": len(objs),
        "objects_current": len(current),
        "objects_retired": len(objs) - len(current),
        "root_count": counts.get("INTENT", 0),
        "created": len(set(objs) - set(before_objs)),
        "witnesses": len(result.get("unchanged_object_refs", ())) if result else 0,
        "replacements": len(retirements),
        "gaps_new": len(set(end.gaps) - set(mid.gaps)),
        "contradiction_gaps_new": sum(
            1 for g in set(end.gaps) - set(mid.gaps) if end.gaps[g].kind.value == "CONTRADICTION"
        ),
        "kinds_current": dict(sorted(counts.items())),
        "root_stale_bounded": bool(root_id and root_id in derive_intent_view(end).stale_ids),
        "root_stale_raw_plane": bool(root_id and root_id in derive_view(end.semantic).stale_ids),
        "request_chars": len(json.dumps(ie3.request)) if ie3 is not None and ie3.request else 0,
        "input_tokens": call.input_tokens if call else None,
        "output_tokens": call.output_tokens if call else None,
        "wall_clock_ms": call.wall_clock_ms if call else None,
        "refused": ie3.status == "REFUSED" if ie3 is not None else None,
    }
    return m


# --------------------------------------------------------------------------- entry point


def first_divergence(checks: dict[str, CheckResult]) -> dict[str, Any] | None:
    for t in range(1, 17):
        for layer in ("IE2", "IE3"):
            c = checks.get(f"T{t:02d}-{layer}")
            if c is not None and not c.passed:
                return {"t": t, "layer": layer, "finding": c.findings[0]}
    return None


def evaluate(run: RunRecord) -> Evaluation:
    r = _Run(run)
    out = _Out()
    if run.status != "COMPLETED":
        out.add("RUN-INTEGRITY", "ABORTED", run.error or run.status)
    if run.replay_matches is not True:
        out.add("RUN-INTEGRITY", "REPLAY", "the final ledger does not replay to the final state")
    if run.ie2_calls > protocol.MAX_IE2_CALLS or run.ie3_calls > protocol.MAX_IE3_CALLS:
        out.add("RUN-INTEGRITY", "BUDGET", f"{run.ie2_calls} IE2 / {run.ie3_calls} IE3 calls")
    completed = [t for t in run.turns if t.status == "COMPLETED"]
    if len(completed) != 16:
        out.add("RUN-INTEGRITY", "INCOMPLETE", f"{len(completed)} of 16 turns completed")
    for finding in source_coverage_findings():
        out.add("SOURCE-COVERAGE", "SOURCE_COVERAGE", finding)
    root: dict[str, Any] = {}
    metrics: list[dict[str, Any]] = []
    for turn in run.turns:
        if turn.status == "NOT_RUN":
            out.add(f"T{turn.t:02d}-IE2", "NOT_RUN", "the walk stopped earlier")
            out.add(f"T{turn.t:02d}-IE3", "NOT_RUN", "the walk stopped earlier")
            metrics.append({"t": turn.t, "status": "NOT_RUN"})
            continue
        _ie2(r, turn, out)
        _ie3(r, turn, out, root)
        metrics.append(turn_metrics(r, turn, root.get("id")))
    recorded = {turn.t for turn in run.turns}
    for t in range(1, 17):
        if t not in recorded:
            out.add(f"T{t:02d}-IE2", "NOT_RUN", "no record of this turn")
            out.add(f"T{t:02d}-IE3", "NOT_RUN", "no record of this turn")
    names = (
        *(f"T{t:02d}-{layer}" for t in range(1, 17) for layer in ("IE2", "IE3")),
        "RUN-INTEGRITY",
        "SOURCE-COVERAGE",
    )
    checks = {
        n: CheckResult(name=n, passed=not out.by.get(n), findings=tuple(out.by.get(n, ())))
        for n in names
    }
    return Evaluation(
        checks=checks,
        metrics=tuple(metrics),
        root_id=root.get("id"),
        first_divergence=first_divergence(checks),
    )
