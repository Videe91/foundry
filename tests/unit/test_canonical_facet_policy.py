"""The canonical-facet policy ``intent-v2-locus-v3`` (IE2 v2 design §7.1.2).

Its identity is frozen by pasted literals; every historical identity (9P, 9P2, locus-v1,
locus-v2 and the shared output schema) is byte-identical; the model is told it never writes a
facet and the contract offers none; the projection is deterministic, injective and
inference-free; admission refuses a non-canonical facet (``NON_CANONICAL_FACET``) only when
the policy asks for it, so historical ledgers route exactly as before; and the source
coverage check catches the v3 answer-key omission.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics import xai_reasoner as mod
from foundry.adapters.semantics.xai_reasoner import (
    CANONICAL_FACET_POLICY_VERSION,
    CANONICAL_FACET_SYSTEM_INSTRUCTION,
    CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256,
    CONCERN_OUTPUT_SCHEMA_SHA256,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    GOVERNED_CONCERN_SYSTEM_INSTRUCTION,
    GOVERNED_CONCERN_SYSTEM_INSTRUCTION_SHA256,
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    ConcernDraftPayload,
    SemanticDraftPayload,
    XAICanonicalFacetSemanticReasoner,
    XAIContrastiveSemanticReasoner,
    XAIGovernedConcernSemanticReasoner,
    XAILocusSemanticReasoner,
    XAISemanticReasoner,
    concern_output_schema_sha256,
    semantic_output_schema_sha256,
)
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_identity import (
    CANONICAL_FACET_PREFIX,
    SemanticCandidate,
    canonical_facet,
)
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.locus_formation.source_coverage import (
    SentenceAccount,
    coverage_findings,
    source_sentences,
)
from foundry.experiments.long_horizon_bounded.timeline import SECTION_TEXT
from tests.unit.test_xai_semantic_reasoner import FakeHarness

AT = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-FACET-POLICY"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ identity


def test_the_new_policy_has_its_own_frozen_identity() -> None:
    assert CANONICAL_FACET_POLICY_VERSION == "intent-v2-locus-v3"
    assert _sha(CANONICAL_FACET_SYSTEM_INSTRUCTION) == CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256
    assert CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256 == (
        "83a717a9e11d26841b0538bcb781eb766b07bdfc94873213da0965be5ac2d803"
    )
    assert (
        concern_output_schema_sha256()
        == CONCERN_OUTPUT_SCHEMA_SHA256
        == ("08d881db080f87b45abebc3fb79ce53229ccf490b1ba331f75744efb55051b79")
    )
    cls = XAICanonicalFacetSemanticReasoner
    assert cls.policy_version == CANONICAL_FACET_POLICY_VERSION
    assert cls.system_instruction == CANONICAL_FACET_SYSTEM_INSTRUCTION
    assert cls.draft_payload is ConcernDraftPayload
    assert cls.include_comparison_context is True


def test_every_historical_identity_is_byte_identical() -> None:
    assert (
        semantic_output_schema_sha256()
        == SEMANTIC_OUTPUT_SCHEMA_SHA256
        == ("ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851")
    )
    assert _sha(GOVERNED_CONCERN_SYSTEM_INSTRUCTION) == GOVERNED_CONCERN_SYSTEM_INSTRUCTION_SHA256
    assert GOVERNED_CONCERN_SYSTEM_INSTRUCTION_SHA256 == (
        "77a20f3b1d39787b351aedaf031176c61c295dc8cab526ffa08373da79a801cd"
    )
    assert _sha(LOCUS_SYSTEM_INSTRUCTION) == LOCUS_SYSTEM_INSTRUCTION_SHA256
    for cls in (
        XAISemanticReasoner,
        XAIContrastiveSemanticReasoner,
        XAILocusSemanticReasoner,
        XAIGovernedConcernSemanticReasoner,
    ):
        assert cls.draft_payload is SemanticDraftPayload, cls.__name__


# ------------------------------------------------------------------ the prompt


def test_only_the_two_facet_passages_moved() -> None:
    old = GOVERNED_CONCERN_SYSTEM_INSTRUCTION.splitlines()
    new = CANONICAL_FACET_SYSTEM_INSTRUCTION.splitlines()
    removed = [line for line in old if line not in new]
    assert all("facet" in line or "descriptor" in line or "proposition you read" in line
               for line in removed), removed  # fmt: skip
    assert CANONICAL_FACET_SYSTEM_INSTRUCTION.startswith(CONTRASTIVE_SYSTEM_INSTRUCTION[:200])


def test_the_model_is_told_it_never_writes_a_facet() -> None:
    text = CANONICAL_FACET_SYSTEM_INSTRUCTION
    assert "You never write a facet: Foundry derives it" in text
    assert "facet asks" not in text and "A facet never" not in text
    assert [line for line in text.splitlines() if "facet" in line.lower()] == [
        "a whole. subject names the concern. You never write a facet: Foundry derives it"
    ]
    assert text.count("A semantic address is") == 1


def test_the_subject_carries_the_whole_concern_rule() -> None:
    text = CANONICAL_FACET_SYSTEM_INSTRUCTION
    assert "subject names the governed concern itself, specifically enough" in text
    assert "never one dimension of the concern, never a generic word" in text
    assert "The\ndimensions of a concern are claims at its one address" in text


# ------------------------------------------------------------------ the contract


def test_the_create_and_bind_drafts_have_no_facet_field() -> None:
    schema = ConcernDraftPayload.model_json_schema()
    defs = schema["$defs"]
    for name in ("ConcernCreateAddressDraft", "ConcernBindToAddressDraft"):
        assert "facet" not in defs[name]["properties"], name
        assert "subject" in defs[name]["required"], name
    assert '"facet"' not in json.dumps(schema)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeHarness]:
    fake = FakeHarness()
    monkeypatch.setattr(mod, "Client", fake.client_cls)
    yield fake


def _request(**overrides: Any) -> Any:
    from foundry.domain.semantic_judgment import JudgmentKind
    from foundry.ports.semantic_reasoner import ReasoningRequest

    item = evidence_item(
        evidence_id="EV-1",
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref="doc://EV-1",
        content="An operator may cancel a job.",
        observed_at=AT,
        scope=("jobs",),
    )
    fields: dict[str, Any] = {
        "project_id": PROJECT,
        "evidence": (item,),
        "known_addresses": (),
        "known_claims": (),
        "allowed_judgment_kinds": frozenset({JudgmentKind.CREATE_ADDRESS}),
    }
    fields.update(overrides)
    return ReasoningRequest(**fields)


def _reasoner(cls: type[XAISemanticReasoner]) -> XAISemanticReasoner:
    ticks = count(1)
    return cls(api_key="k", clock=lambda: AT, id_factory=lambda p: f"{p}-{next(ticks):03d}")


def test_the_adapter_sends_the_concern_contract_and_projects_the_facet(
    harness: FakeHarness,
) -> None:
    harness.content = json.dumps(
        {
            "drafts": [
                {
                    "kind": "CREATE_ADDRESS",
                    "subject": "Job cancellation",
                    "evidence_ids": ["EV-1"],
                    "rationale": "one governed concern",
                }
            ]
        }
    )
    (judgment,) = _reasoner(XAICanonicalFacetSemanticReasoner).propose(_request())
    assert harness.create_kwargs[-1]["response_format"] is ConcernDraftPayload
    proposal = judgment.proposal
    assert isinstance(proposal, CreateAddressProposal)
    assert proposal.candidate.subject == "Job cancellation"
    assert proposal.candidate.facet == "Rules governing Job cancellation"
    assert judgment.reasoner.policy_version == "intent-v2-locus-v3"


def test_the_governed_concern_policy_still_sends_the_historical_contract(
    harness: FakeHarness,
) -> None:
    harness.content = json.dumps(
        {
            "drafts": [
                {
                    "kind": "CREATE_ADDRESS",
                    "subject": "Job cancellation",
                    "facet": "Who may cancel?",
                    "evidence_ids": ["EV-1"],
                    "rationale": "x",
                }
            ]
        }
    )
    (judgment,) = _reasoner(XAIGovernedConcernSemanticReasoner).propose(_request())
    assert harness.create_kwargs[-1]["response_format"] is SemanticDraftPayload
    assert isinstance(judgment.proposal, CreateAddressProposal)
    assert judgment.proposal.candidate.facet == "Who may cancel?"


# ------------------------------------------------------------------ the projection


def test_the_projection_is_a_fixed_prefix_and_the_exact_subject() -> None:
    assert CANONICAL_FACET_PREFIX == "Rules governing "
    for subject in ("Job cancellation", "late-delivery compensation", " Orion  job ", "Ä/ß"):
        assert canonical_facet(subject) == "Rules governing " + subject
        assert canonical_facet(subject) == canonical_facet(subject)
        assert canonical_facet(subject).removeprefix(CANONICAL_FACET_PREFIX) == subject


def test_the_projection_is_injective_it_never_merges_two_subjects() -> None:
    subjects = [
        "Job cancellation",
        "job cancellation",
        "Job audit record deletion",
        "Late-delivery compensation",
        "Damaged parcel compensation",
        "Compensation request",
        "Daily bank settlement",
        "Customer refund",
        "Supplier overpayment refund",
    ]
    assert len({canonical_facet(s) for s in subjects}) == len(subjects)


# ------------------------------------------------------------------ admission


def _governor(policy: AdmissionPolicy) -> SemanticGovernor:
    ids = count(1)
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=policy,
        clock=lambda: AT,
        id_factory=lambda prefix: f"{prefix}-{next(ids):04d}",
    )


def _judgment(jid: str, proposal: JudgmentProposal) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=jid,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        rationale="r",
        reasoner=ReasonerFingerprint(provider="xai", model="m", policy_version="p"),
        invocation_id=f"INV-{jid}",
        proposed_at=AT,
    )


def _candidate(cid: str, subject: str, facet: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=cid, subject=subject, facet=facet, scope=("jobs",), evidence_ids=("EV-1",)
    )


def _ingest(governor: SemanticGovernor) -> None:
    governor.ingest(
        evidence_item(
            evidence_id="EV-1",
            project_id=PROJECT,
            source_kind=SourceKind.DOCUMENT,
            source_ref="doc://EV-1",
            content="An operator may cancel a job.",
            observed_at=AT,
            scope=("jobs",),
        )
    )


@pytest.mark.parametrize(
    "facet",
    [
        "Who may cancel?",
        "When can compensation be requested?",
        "Sender refund entitlement",
        "How it is governed",
        "Governance",
        "Lifecycle",
        "Rules governing job cancellation",  # a different subject's projection
    ],
)
def test_a_non_canonical_create_is_refused(facet: str) -> None:
    governor = _governor(AdmissionPolicy(canonical_facets=True))
    _ingest(governor)
    decision = governor.submit(
        _judgment(
            "J-1", CreateAddressProposal(candidate=_candidate("C-1", "Job cancellation", facet))
        )
    )
    assert decision.route is AdmissionRoute.REJECT
    assert any(r.startswith("STRUCTURAL: NON_CANONICAL_FACET") for r in decision.reasons)
    assert governor.state().semantic.addresses == {}


def test_the_canonical_create_and_bind_are_admitted_and_a_non_canonical_bind_refused() -> None:
    governor = _governor(AdmissionPolicy(canonical_facets=True))
    _ingest(governor)
    facet = canonical_facet("Job cancellation")
    created = governor.submit(
        _judgment(
            "J-1", CreateAddressProposal(candidate=_candidate("C-1", "Job cancellation", facet))
        )
    )
    assert created.route is AdmissionRoute.APPLY
    (address_id,) = governor.state().semantic.addresses
    assert governor.state().semantic.addresses[address_id].facet == facet
    bad = governor.submit(
        _judgment(
            "J-2",
            BindToAddressProposal(
                candidate=_candidate("C-2", "Job cancellation", "Repeated cancellation"),
                address_id=address_id,
            ),
        )
    )
    assert bad.route is AdmissionRoute.REJECT
    assert any("NON_CANONICAL_FACET" in r for r in bad.reasons)
    good = governor.submit(
        _judgment(
            "J-3",
            BindToAddressProposal(
                candidate=_candidate("C-3", "Job cancellation", facet), address_id=address_id
            ),
        )
    )
    assert good.route is not AdmissionRoute.REJECT


def test_without_the_flag_historical_facets_are_admitted_unchanged() -> None:
    assert AdmissionPolicy().canonical_facets is False
    governor = _governor(AdmissionPolicy())
    _ingest(governor)
    decision = governor.submit(
        _judgment(
            "J-1",
            CreateAddressProposal(
                candidate=_candidate("C-1", "Job cancellation", "Who may cancel?")
            ),
        )
    )
    assert decision.route is AdmissionRoute.APPLY


# ------------------------------------------------------------------ source coverage (v3 lesson)


def _v3_inventory_accounts() -> list[SentenceAccount]:
    """What v3's inventory accounted for in 9P3 H-T9: the numbered rules and the opening
    restatement, nothing else."""
    return [
        SentenceAccount(
            sentence="Producers and operators can cancel jobs.", propositions=("H-1R",)
        ),
        SentenceAccount(
            sentence="After a job is cancelled, no future execution attempt of that job may be "
            "started.",
            propositions=("H-2R",),
        ),
        SentenceAccount(
            sentence="Cancellation must not interrupt an execution attempt that is already "
            "running; that attempt runs to its own completion, failure or timeout.",
            propositions=("H-3R",),
        ),
        SentenceAccount(
            sentence="If Orion receives a cancellation for a job that is already cancelled, the "
            "job must remain cancelled and the repeated cancellation must not otherwise change "
            "the job's state.",
            propositions=("H-4",),
        ),
    ]


def test_the_v3_inventory_would_now_be_caught() -> None:
    text = SECTION_TEXT[(9, "H")]
    findings = coverage_findings(text, _v3_inventory_accounts())
    unaccounted = [f for f in findings if f.startswith("UNACCOUNTED_SENTENCE")]
    assert any("simply acknowledged" in f for f in unaccounted), findings


def test_a_complete_account_of_h_t9_passes() -> None:
    text = SECTION_TEXT[(9, "H")]
    accounts = {a.sentence: a for a in _v3_inventory_accounts()}
    for sentence in source_sentences(text):
        if sentence in accounts:
            continue
        if "simply acknowledged" in sentence:
            accounts[sentence] = SentenceAccount(sentence=sentence, propositions=("H-4", "H-5"))
        else:
            accounts[sentence] = SentenceAccount(
                sentence=sentence, non_operative_reason="rationale or example restating rules"
            )
    assert coverage_findings(text, accounts.values()) == ()


def test_an_omission_needs_a_reason_and_an_account_needs_a_real_sentence() -> None:
    text = "## T\n\nRules\n1. A job may be cancelled.\n2. Nothing else changes."
    assert source_sentences(text) == ("A job may be cancelled.", "Nothing else changes.")
    findings = coverage_findings(
        text,
        [
            SentenceAccount(sentence="A job may be cancelled."),
            SentenceAccount(sentence="An invented sentence.", propositions=("P",)),
        ],
    )
    assert "UNJUSTIFIED_OMISSION: 'A job may be cancelled.'" in findings
    assert "UNKNOWN_SENTENCE: 'An invented sentence.'" in findings
    assert "UNACCOUNTED_SENTENCE: 'Nothing else changes.'" in findings


def test_labels_and_headings_carry_no_sentence() -> None:
    assert source_sentences("## Heading\n\nRules\nNormative rule\nExample\n") == ()


def test_an_abbreviation_inside_a_sentence_does_not_split_it() -> None:
    text = "1. Pickups booked at 2 p.m. local time or later are collected tomorrow. Next rule."
    assert source_sentences(text) == (
        "Pickups booked at 2 p.m. local time or later are collected tomorrow.",
        "Next rule.",
    )
