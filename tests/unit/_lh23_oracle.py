"""Offline oracle reasoners for the IE2 + IE3 long-horizon harness (test-only).

They behave exactly as the sealed answer key says a correct system would, so a run driven by
them must pass every mechanical check; each mutation of the evaluator must then be caught.
They read the answer key, which no live path may: they exist only to prove the harness.

* ``OracleIE2``: Call 1 creates one address per locus at T1 (subject "Orion section <L>")
  and binds every later item to it; Call 2 asserts one claim per REQUIRED proposition that is
  not yet current, supports the current ones, supersedes exactly the no-longer-current ones,
  and returns a complete proposition-accounting payload over the rendered sentence index.
* ``OracleIE3``: one node per locus. T1: a root Intent plus one REQUIREMENT per locus. Later:
  every stale node is replaced by one node grounded on all live claims of its locus; live
  claims no current node covers get one NEW node; otherwise the current nodes are witnessed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import count
from typing import Any

from pydantic import BaseModel

from foundry.domain.common import Authority
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticCandidate,
    canonical_facet,
)
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.source_text import sentence_id
from foundry.experiments.long_horizon_ie2_ie3 import protocol
from foundry.experiments.long_horizon_ie2_ie3.expectations import (
    PROPOSITIONS,
    SOURCE_COVERAGE,
    TEXT_KEY,
    TURNS,
)
from foundry.experiments.long_horizon_ie2_ie3.recording import GraphCallRecord
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest
from foundry.ports.semantic_reasoner import ReasoningRequest

AT = datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
_IDS = count(1)
_BY_ID = {p.id: p for p in PROPOSITIONS}
_SUBJECT = "Orion section {}"


def _locus_of_subject(subject: str) -> str:
    return subject.rsplit(" ", 1)[-1]


class _Payload(BaseModel):
    propositions: list[dict[str, Any]]
    non_operative: list[dict[str, Any]]
    drafts: list[dict[str, Any]]


class OracleIE2:
    include_sentence_index = True
    fingerprint = ReasonerFingerprint(
        provider="fake", model="lh23-oracle-ie2", policy_version="oracle"
    )

    def __init__(
        self,
        *,
        skip_supersede_at: int | None = None,
        extra_claim_at: int | None = None,
        create_at: int | None = None,
        bad_accounting_at: int | None = None,
    ) -> None:
        self.draft_payloads: list[_Payload] = []
        self.receipts: list[Any] = []
        self._skip_supersede_at = skip_supersede_at
        self._extra_claim_at = extra_claim_at
        self._create_at = create_at
        self._bad_accounting_at = bad_accounting_at

    def _judgment(self, proposal: Any, evidence: tuple[str, ...]) -> SemanticJudgment:
        n = next(_IDS)
        return SemanticJudgment(
            judgment_id=f"JDG-ORACLE-{n:05d}",
            project_id=protocol.PROJECT_ID,
            proposal=proposal,
            visible_evidence_ids=evidence,
            rationale="oracle",
            reasoner=self.fingerprint,
            invocation_id=f"INV-ORACLE-{n:05d}",
            proposed_at=AT,
        )

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.ASSERT_CLAIM not in request.allowed_judgment_kinds:
            return self._call_1(request)
        return self._call_2(request)

    def _call_1(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        by_locus = {_locus_of_subject(a.subject): a for a in request.known_addresses}
        out = []
        for item in request.evidence:
            locus = item.evidence_id[5]
            subject = _SUBJECT.format(locus)
            candidate = SemanticCandidate(
                candidate_id=f"CAND-{item.evidence_id}",
                subject=subject,
                facet=canonical_facet(subject),
                scope=(protocol.PROJECT_ID and "orion-jobs",),
                evidence_ids=(item.evidence_id,),
            )
            known = by_locus.get(locus)
            if self._create_at == int(item.evidence_id[6:8]) and locus == "E":
                known = None  # a second address for a known concern: an over-split
            proposal: Any = (
                BindToAddressProposal(candidate=candidate, address_id=known.address_id)
                if known is not None
                else CreateAddressProposal(candidate=candidate)
            )
            out.append(self._judgment(proposal, (item.evidence_id,)))
        self.draft_payloads.append(_Payload(propositions=[], non_operative=[], drafts=[]))
        return tuple(out)

    def _call_2(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        address_of = {_locus_of_subject(a.subject): a.address_id for a in request.known_addresses}
        claims_at: dict[str, list[Any]] = {}
        for c in request.known_claims:
            claims_at.setdefault(c.address_id, []).append(c)
        out: list[SemanticJudgment] = []
        props: list[dict[str, Any]] = []
        non_op: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        for item in request.evidence:
            if item.evidence_id not in request.accountable_evidence_ids:
                continue
            eid, locus, t = item.evidence_id, item.evidence_id[5], int(item.evidence_id[6:8])
            turn = TURNS[t - 1]
            address = address_of[locus]
            existing = {
                re.match(r"^([A-L]-\w+):", c.value.text or "").group(1): c  # type: ignore[union-attr]
                for c in claims_at.get(address, [])
            }
            if self._extra_claim_at == t and locus == "E":
                existing.pop("E-1", None)  # restate E-1 as a new claim: a duplicate at a control
            target = set(turn.required_current[locus])
            accounts = SOURCE_COVERAGE[TEXT_KEY[(t, locus)]]
            supersede = [
                existing[p]
                for p in turn.no_longer_current
                if p in existing and _BY_ID[p].locus == locus
            ]
            if self._skip_supersede_at == t:
                supersede = []
            asserted_required = [
                p
                for p in dict.fromkeys(q for a in accounts for q in a.propositions)
                if _BY_ID[p].tier == "REQUIRED" and p in target and p not in existing
            ]
            carriers_needed = len(supersede) - len(asserted_required)
            claimed_optional = [
                p
                for p in dict.fromkeys(q for a in accounts for q in a.propositions)
                if _BY_ID[p].tier == "OPTIONAL" and p not in existing
            ][: max(carriers_needed, 0)]
            target = target | set(claimed_optional)
            sentences_of: dict[str, list[str]] = {}
            for n, account in enumerate(accounts, 1):
                stated = [
                    p
                    for p in account.propositions
                    if _BY_ID[p].tier == "REQUIRED" or p in claimed_optional or p in existing
                ]
                if not stated:
                    non_op.append({"sentence_id": sentence_id(eid, n), "reason": "background"})
                for p in stated:
                    sentences_of.setdefault(p, []).append(sentence_id(eid, n))
            asserted: list[str] = []
            for pid, sids in sentences_of.items():
                local = f"{eid}/{pid}"
                props.append(
                    {
                        "proposition_id": local,
                        "sentence_ids": sids,
                        "statement": _BY_ID[pid].statement,
                    }
                )
                if pid in existing:
                    claim = existing[pid]
                    out.append(
                        self._judgment(
                            SupportsClaimProposal(claim_id=claim.claim_id, evidence_ids=(eid,)),
                            (eid,),
                        )
                    )
                    drafts.append(
                        {"proposition_id": local, "kind": "SUPPORTS_CLAIM", "evidence_ids": [eid]}
                    )
                elif pid in target:
                    out.append(
                        self._judgment(
                            AssertClaimProposal(
                                address_id=address,
                                predicate=f"orion_{locus.lower()}",
                                value=ClaimValue(
                                    kind=ClaimValueKind.TEXT,
                                    text=f"{pid}: {_BY_ID[pid].statement}"
                                    + (
                                        " (restated)"
                                        if self._extra_claim_at == t and pid == "E-1"
                                        else ""
                                    ),
                                ),
                                evidence_ids=(eid,),
                                authority=Authority.INFERRED,
                            ),
                            (eid,),
                        )
                    )
                    drafts.append(
                        {"proposition_id": local, "kind": "ASSERT_CLAIM", "evidence_ids": [eid]}
                    )
                    asserted.append(local)
                else:
                    raise AssertionError(f"oracle cannot place {pid} at T{t}")
            if len(supersede) > len(asserted):
                raise AssertionError(f"oracle has no carrier for every SUPERSEDE at T{t} {locus}")
            for carrier, claim in zip(asserted, supersede, strict=False):
                out.append(
                    self._judgment(
                        SupersedeProposal(
                            target_judgment_id=claim.created_by_judgment_id, reason="corrected"
                        ),
                        (eid,),
                    )
                )
                drafts.append({"proposition_id": carrier, "kind": "SUPERSEDE", "evidence_ids": []})
        if (
            non_op
            and self._bad_accounting_at is not None
            and any(int(e.evidence_id[6:8]) == self._bad_accounting_at for e in request.evidence)
        ):
            non_op = non_op[1:]  # one sentence silently unaccounted
        self.draft_payloads.append(
            _Payload(propositions=props, non_operative=non_op, drafts=drafts)
        )
        return tuple(out)


class OracleIE3:
    fingerprint = ReasonerFingerprint(
        provider=protocol.IE3_PROVIDER,
        model=protocol.IE3_MODEL,
        policy_version=protocol.IE3_POLICY_VERSION,
    )

    def __init__(
        self,
        *,
        second_root_at: int | None = None,
        root_gap_at: int | None = None,
        no_replace_at: int | None = None,
        dup_at: int | None = None,
        no_root: bool = False,
    ) -> None:
        self.calls: list[GraphCallRecord] = []
        self._t = 0
        self._second_root_at = second_root_at
        self._root_gap_at = root_gap_at
        self._no_replace_at = no_replace_at
        self._dup_at = dup_at
        self._no_root = no_root

    def records(self) -> tuple[GraphCallRecord, ...]:
        return tuple(self.calls)

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
        self._t += 1
        self.calls.append(
            GraphCallRecord(
                provider="openai",
                model="gpt-6-astra",
                task="INTENT_GRAPH_SYNTHESIS",
                tier="REASONER",
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                wall_clock_ms=None,
                finish_reason=None,
                output=None,
            )
        )
        claims_by_locus: dict[str, list[str]] = {}
        for basis in request.basis:
            locus = _locus_of_subject(basis.subject)
            claims_by_locus.setdefault(locus, []).extend(c.claim_id for c in basis.live_claims)
        live = {c for cs in claims_by_locus.values() for c in cs}
        root = next((o.object_id for o in request.known_objects if o.kind.value == "INTENT"), None)
        nodes: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        root_ref: dict[str, Any] = (
            {"namespace": "existing", "object_id": root}
            if root
            else {"namespace": "local", "local_id": "root"}
        )
        if root is None and self._no_root:
            root_ref = {"namespace": "local", "local_id": "goal"}
            nodes.append(
                {
                    "local_id": {"local_id": "goal"},
                    "kind": "GOAL",
                    "statement": "Run jobs.",
                    "proposal_rationale": "oracle",
                }
            )
            relations.append(
                _edge("goal", "DERIVED_FROM", {"namespace": "basis", "claim_id": sorted(live)[0]})
            )
        elif root is None:
            nodes.append(
                {
                    "local_id": {"local_id": "root"},
                    "kind": "INTENT",
                    "mission": "Operate the Orion job service under its governing rules.",
                    "proposal_rationale": "oracle",
                }
            )
            first = sorted(live)[0]
            relations.append(
                _edge("root", "DERIVED_FROM", {"namespace": "basis", "claim_id": first})
            )
        covered = {
            c
            for o in request.known_objects
            if not o.is_stale and o.kind.value != "INTENT"
            for c in o.basis_claim_ids
        }
        stale_by_locus = {
            o.text[1]: o.object_id
            for o in request.known_objects
            if o.is_stale and o.kind.value != "INTENT"
        }
        if self._no_replace_at == self._t:
            claims_by_locus = {}
        if self._dup_at == self._t:
            k = claims_by_locus.get("K", [])
            if k:
                nodes.append(
                    {
                        "local_id": {"local_id": "dup-k"},
                        "kind": "REQUIREMENT",
                        "statement": "[K] again",
                        "proposal_rationale": "oracle",
                    }
                )
                relations.append(
                    _edge("dup-k", "DERIVED_FROM", {"namespace": "basis", "claim_id": k[0]})
                )
                relations.append(_edge("dup-k", "SERVES", root_ref))
        for locus, claims in sorted(claims_by_locus.items()):
            local = f"n-{locus.lower()}-{self._t}"
            if locus in stale_by_locus:
                nodes.append(
                    {
                        "local_id": {"local_id": local},
                        "kind": "REQUIREMENT",
                        "statement": f"[{locus}] rules, as currently stated",
                        "disposition": "REPLACES_STALE",
                        "proposal_rationale": "oracle",
                        "replaces": {"namespace": "existing", "object_id": stale_by_locus[locus]},
                    }
                )
                grounds = claims
            else:
                grounds = [c for c in claims if c not in covered]
                if not grounds:
                    continue
                nodes.append(
                    {
                        "local_id": {"local_id": local},
                        "kind": "REQUIREMENT",
                        "statement": f"[{locus}] rules",
                        "proposal_rationale": "oracle",
                    }
                )
            for c in grounds:
                relations.append(
                    _edge(local, "DERIVED_FROM", {"namespace": "basis", "claim_id": c})
                )
            relations.append(_edge(local, "SERVES", root_ref))
        if self._second_root_at == self._t:
            nodes.append(
                {
                    "local_id": {"local_id": "root2"},
                    "kind": "INTENT",
                    "mission": "Another.",
                    "proposal_rationale": "oracle",
                }
            )
            relations.append(
                _edge("root2", "DERIVED_FROM", {"namespace": "basis", "claim_id": sorted(live)[0]})
            )
        gaps: list[dict[str, Any]] = []
        if self._root_gap_at == self._t and root:
            gaps.append(
                {
                    "local_gap_id": "g-root",
                    "kind": "MISSING_INFORMATION",
                    "description": "the root may be stale",
                    "missing_need": "UNDETERMINED",
                    "blocking": True,
                    "anchors": [{"namespace": "existing", "object_id": root}],
                }
            )
        if not nodes and not gaps:
            refs = [
                {"namespace": "existing", "object_id": o.object_id}
                for o in request.known_objects
                if o.kind.value != "INTENT" and not o.is_stale
            ]
            return IntentGraphSynthesisResult.model_validate({"unchanged_object_refs": refs})
        return IntentGraphSynthesisResult.model_validate(
            {"nodes": nodes, "relations": relations, "gaps": gaps}
        )


def _edge(source: str, relation: str, target: dict[str, Any]) -> dict[str, Any]:
    return {"source": {"local_id": source}, "relation_type": relation, "target": target}


def oracle_run(**kwargs: Any) -> Any:
    from foundry.experiments.long_horizon_ie2_ie3.recording import RunBudget
    from foundry.experiments.long_horizon_ie2_ie3.runner import run_experiment

    ie2_kwargs = {k: v for k, v in kwargs.items() if k in ("skip_supersede_at",)}
    ie3_kwargs = {k: v for k, v in kwargs.items() if k in ("second_root_at", "root_gap_at")}
    ie3 = OracleIE3(**ie3_kwargs)
    ids = count(1)
    return run_experiment(
        ie2=OracleIE2(**ie2_kwargs),
        ie3_synthesizer=ie3,
        ie3_calls=ie3.records,
        budget=RunBudget(),
        guard_identity=False,
        clock=lambda: AT,
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )
