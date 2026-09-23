"""T7 — the bounded request/context layer.

T7 decides deterministically what an ``IntentSynthesizer`` may see, and validates what
it returns **against that exact snapshot**. No events, no routing, no provider call, no
state mutation.

Two laws carry most of the weight here:

* **the model cannot cite invisible state** — a claim that exists in ``state.semantic``
  but was not shown in this request is illegal, and the whole result is refused;
* **stale derived intent must not block the locus that would reconcile it** — locus
  staleness means the locus' CURRENT issue head is stale, never that some downstream
  object derived from it is. Defining it the other way deadlocks reconciliation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from _t7_fixtures import (  # noqa: E402
    SCOPE,
    address,
    assert_judgment,
    claim,
    conflict_judgment,
    equivalent_judgment,
    evidence,
    intent_state,
    object_of_kind,
    requirement,
    semantic_state,
    simple_locus_state,
    supersede_judgment,
    version,
)

from foundry.application.context_errors import ContextUnsupported  # noqa: E402
from foundry.application.intent_synthesis_context import (  # noqa: E402
    KNOWN_INTENT_OBJECT_THRESHOLD,
    MAX_KNOWN_INTENT_CONTEXT_CHARS,
    IntentSynthesisContext,
    IntentSynthesisResultError,
    ValidatedSynthesisProposal,
    compile_intent_synthesis_context,
    known_intent_context_character_count,
    known_intent_context_json,
    validate_intent_synthesis_result,
)
from foundry.domain.common import Authority, LifecycleStatus, Materiality, SourceKind  # noqa: E402
from foundry.domain.gaps import GapKind  # noqa: E402
from foundry.domain.intent_synthesis import (  # noqa: E402
    IntentDisposition,
    IntentSynthesisResult,
    RequirementSynthesisProposal,
)
from foundry.domain.semantic import SemanticKind  # noqa: E402
from foundry.domain.semantic_identity import ClaimValueKind, IssueEpistemicState  # noqa: E402
from foundry.ports.intent_synthesizer import (  # noqa: E402
    BasisClaim,
    IntentSynthesisRequest,
    IntentSynthesizer,
    LocusBasis,
)

REQUIREMENT_ONLY = frozenset({SemanticKind.REQUIREMENT})


def _compile(state, scope: str = SCOPE) -> IntentSynthesisContext:  # type: ignore[no-untyped-def]
    return compile_intent_synthesis_context(state, scope=scope)


def _proposal(
    *,
    basis_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    disposition: IntentDisposition = IntentDisposition.NEW,
    relates_to_object_id: str | None = None,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id="p1",
        disposition=disposition,
        statement="Revocation is immediate.",
        rationale="r",
        basis_claim_ids=basis_claim_ids,
        relates_to_object_id=relates_to_object_id,
    )


# --- port shapes ------------------------------------------------------------------------


def test_the_request_models_are_frozen_and_forbid_extras() -> None:
    from pydantic import ValidationError

    ctx = _compile(simple_locus_state())
    assert ctx.request is not None
    with pytest.raises(ValidationError):
        ctx.request.scope = "other"
    with pytest.raises(ValidationError):
        IntentSynthesisRequest.model_validate(
            {**ctx.request.model_dump(mode="json"), "smuggled": 1}
        )


def test_basis_minimum_lengths_are_enforced() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BasisClaim(
            claim_id="",
            predicate="p",
            value={"kind": "TEXT", "text": "t"},  # type: ignore[arg-type]
            effective_evidence_ids=("EV-1",),
            authority=Authority.INFERRED,
            source_kinds=(SourceKind.DOCUMENT,),
        )
    for field, bad in (("effective_evidence_ids", ()), ("source_kinds", ())):
        with pytest.raises(ValidationError):
            BasisClaim.model_validate(
                {
                    "claim_id": "CLAIM-1",
                    "predicate": "p",
                    "value": {"kind": "TEXT", "text": "t"},
                    "effective_evidence_ids": ("EV-1",),
                    "authority": "INFERRED",
                    "source_kinds": ("DOCUMENT",),
                    field: bad,
                }
            )


@pytest.mark.parametrize("state", [IssueEpistemicState.OPEN, IssueEpistemicState.DISPUTED])
def test_a_locus_basis_may_only_be_claimed_or_settled(state: IssueEpistemicState) -> None:
    """OPEN and DISPUTED are filtered before model context exists."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LocusBasis(
            locus_representative_id="ADDR-1",
            address_ids=("ADDR-1",),
            subject="s",
            facet="f",
            live_claims=(
                BasisClaim(
                    claim_id="CLAIM-1",
                    predicate="p",
                    value={"kind": "TEXT", "text": "t"},  # type: ignore[arg-type]
                    effective_evidence_ids=("EV-1",),
                    authority=Authority.INFERRED,
                    source_kinds=(SourceKind.DOCUMENT,),
                ),
            ),
            epistemic_state=state,
        )


def test_slice_one_allows_exactly_requirement() -> None:
    ctx = _compile(simple_locus_state())
    assert ctx.request is not None
    assert ctx.request.allowed_target_kinds == REQUIREMENT_ONLY


def test_the_synthesizer_protocol_is_provider_neutral() -> None:
    assert hasattr(IntentSynthesizer, "synthesize")
    source = Path("src/foundry/ports/intent_synthesizer.py").read_text(encoding="utf-8")
    for forbidden in ("xai", "openai", "anthropic", "httpx", "requests"):
        assert forbidden not in source.lower()


# --- trust boundary ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "assigned_authority",
        "object_id",
        "proposal_instance_id",
        "event_id",
        "created_at",
        "provenance",
        "relations",
        "author",
        "origin",
    ],
)
def test_the_request_cannot_express_runtime_owned_output_facts(field: str) -> None:
    from pydantic import ValidationError

    ctx = _compile(simple_locus_state())
    assert ctx.request is not None
    with pytest.raises(ValidationError):
        IntentSynthesisRequest.model_validate(
            {**ctx.request.model_dump(mode="json"), field: "smuggled"}
        )


def test_the_request_exposes_no_state_or_evidence_content() -> None:
    ctx = _compile(simple_locus_state())
    assert ctx.request is not None
    rendered = json.dumps(ctx.request.model_dump(mode="json"))
    assert "content of EV-1" not in rendered
    assert "rationale" not in rendered
    forbidden = {"semantic", "objects", "judgments", "evidence", "event_id"}
    assert not forbidden & set(IntentSynthesisRequest.model_fields)


# --- live basis -------------------------------------------------------------------------


def test_only_live_claims_reach_the_request() -> None:
    """A superseded ASSERT_CLAIM's claim is absent; liveness is not reinterpreted."""
    state = simple_locus_state(extra_claims={"CLAIM-2": "JDG-2"})
    sem = state.semantic
    sup = supersede_judgment("JDG-SUP", "JDG-2")
    sem = sem.model_copy(
        update={
            "judgments": {**dict(sem.judgments), "JDG-SUP": sup},
            "applied_judgment_ids": (*sem.applied_judgment_ids, "JDG-SUP"),
            "supersessions": (
                *sem.supersessions,
                __import__(
                    "foundry.domain.semantic_state", fromlist=["SupersessionRecord"]
                ).SupersessionRecord(
                    target_judgment_id="JDG-2",
                    superseding_judgment_id="JDG-SUP",
                    recorded_by_event_id="EVT-sup",
                ),
            ),
        }
    )
    ctx = _compile(intent_state(sem))
    assert ctx.request is not None
    shown = {c.claim_id for b in ctx.request.basis for c in b.live_claims}
    assert shown == {"CLAIM-1"}


def test_source_kinds_are_derived_from_effective_evidence() -> None:
    sem = simple_locus_state().semantic
    sem = sem.model_copy(
        update={
            "evidence": {
                "EV-1": evidence("EV-1", SourceKind.DOCUMENT),
                "EV-2": evidence("EV-2", SourceKind.RESEARCH),
            },
            "claims": {
                "CLAIM-1": claim(
                    "CLAIM-1", "ADDR-1", judgment_id="JDG-1", evidence_ids=("EV-2", "EV-1")
                )
            },
        }
    )
    ctx = _compile(intent_state(sem))
    assert ctx.request is not None
    basis_claim = ctx.request.basis[0].live_claims[0]
    assert basis_claim.effective_evidence_ids == ("EV-1", "EV-2")
    assert basis_claim.source_kinds == (SourceKind.DOCUMENT, SourceKind.RESEARCH)


def test_a_missing_effective_evidence_item_fails_structurally() -> None:
    sem = simple_locus_state().semantic
    sem = sem.model_copy(update={"evidence": {}})
    with pytest.raises(ValueError, match="EV-1"):
        _compile(intent_state(sem))


# --- scope ------------------------------------------------------------------------------


def test_an_out_of_scope_locus_is_completely_absent() -> None:
    ctx = _compile(simple_locus_state(address_scope=("relay",)))
    assert ctx.request is None
    assert ctx.blockers == ()


def test_a_project_wide_locus_is_included() -> None:
    ctx = _compile(simple_locus_state(address_scope=()))
    assert ctx.request is not None
    assert len(ctx.request.basis) == 1


def test_two_equivalent_addresses_yield_exactly_one_locus_basis() -> None:
    """I12: one commitment must not become two bases."""
    a, b = address("ADDR-A"), address("ADDR-B", subject="B-SUBJ", facet="B-FACET?")
    ja, jb = assert_judgment("JDG-A", "ADDR-A"), assert_judgment("JDG-B", "ADDR-B")
    eq = equivalent_judgment("JDG-EQ", "ADDR-A", "ADDR-B")
    sem = semantic_state(
        evidence={"EV-1": evidence("EV-1")},
        addresses={"ADDR-A": a, "ADDR-B": b},
        claims={
            "CLAIM-A": claim("CLAIM-A", "ADDR-A", judgment_id="JDG-A"),
            "CLAIM-B": claim("CLAIM-B", "ADDR-B", judgment_id="JDG-B"),
        },
        judgments={"JDG-A": ja, "JDG-B": jb, "JDG-EQ": eq},
        applied_judgment_ids=("JDG-A", "JDG-B", "JDG-EQ"),
        equivalences=(
            __import__(
                "foundry.domain.semantic_state", fromlist=["EquivalenceRecord"]
            ).EquivalenceRecord(judgment_id="JDG-EQ", address_a="ADDR-A", address_b="ADDR-B"),
        ),
        issue_versions={
            "V-A": version("V-A", "ADDR-A", ("CLAIM-A",), "JDG-A"),
            "V-B": version("V-B", "ADDR-B", ("CLAIM-B",), "JDG-B"),
        },
        issue_heads={"ADDR-A": "V-A", "ADDR-B": "V-B"},
    )
    ctx = _compile(intent_state(sem))
    assert ctx.request is not None
    assert len(ctx.request.basis) == 1
    basis = ctx.request.basis[0]
    assert basis.locus_representative_id == "ADDR-A"
    assert basis.address_ids == ("ADDR-A", "ADDR-B")
    assert {c.claim_id for c in basis.live_claims} == {"CLAIM-A", "CLAIM-B"}


def test_merged_locus_descriptors_come_from_the_representative_address() -> None:
    """C22: never whichever member address happens to appear first."""
    a = address("ADDR-A", subject="REPRESENTATIVE-SUBJ", facet="REPRESENTATIVE-FACET?")
    b = address("ADDR-B", subject="OTHER-SUBJ", facet="OTHER-FACET?")
    ja, jb = assert_judgment("JDG-A", "ADDR-A"), assert_judgment("JDG-B", "ADDR-B")
    sem = semantic_state(
        evidence={"EV-1": evidence("EV-1")},
        addresses={"ADDR-B": b, "ADDR-A": a},
        claims={
            "CLAIM-A": claim("CLAIM-A", "ADDR-A", judgment_id="JDG-A"),
            "CLAIM-B": claim("CLAIM-B", "ADDR-B", judgment_id="JDG-B"),
        },
        judgments={
            "JDG-A": ja,
            "JDG-B": jb,
            "JDG-EQ": equivalent_judgment("JDG-EQ", "ADDR-A", "ADDR-B"),
        },
        applied_judgment_ids=("JDG-A", "JDG-B", "JDG-EQ"),
        equivalences=(
            __import__(
                "foundry.domain.semantic_state", fromlist=["EquivalenceRecord"]
            ).EquivalenceRecord(judgment_id="JDG-EQ", address_a="ADDR-A", address_b="ADDR-B"),
        ),
        issue_versions={
            "V-A": version("V-A", "ADDR-A", ("CLAIM-A",), "JDG-A"),
            "V-B": version("V-B", "ADDR-B", ("CLAIM-B",), "JDG-B"),
        },
        issue_heads={"ADDR-A": "V-A", "ADDR-B": "V-B"},
    )
    basis = _compile(intent_state(sem)).request.basis[0]  # type: ignore[union-attr]
    assert basis.subject == "REPRESENTATIVE-SUBJ"
    assert basis.facet == "REPRESENTATIVE-FACET?"


# --- blockers ---------------------------------------------------------------------------


def test_an_open_locus_is_omitted_with_no_blocker() -> None:
    """Spec §16: nothing to synthesize, and no gap either."""
    sem = semantic_state(
        addresses={"ADDR-1": address("ADDR-1")},
        judgments={},
        applied_judgment_ids=(),
    )
    ctx = _compile(intent_state(sem))
    assert ctx.request is None
    assert ctx.blockers == ()


def test_a_disputed_locus_produces_a_contradiction_blocker() -> None:
    state = simple_locus_state(extra_claims={"CLAIM-2": "JDG-2"})
    sem = state.semantic
    conflict = conflict_judgment("JDG-CONF", "CLAIM-1", "CLAIM-2")
    sem = sem.model_copy(
        update={
            "judgments": {**dict(sem.judgments), "JDG-CONF": conflict},
            "applied_judgment_ids": (*sem.applied_judgment_ids, "JDG-CONF"),
            "conflicts": (
                __import__(
                    "foundry.domain.semantic_state", fromlist=["ConflictRecord"]
                ).ConflictRecord(judgment_id="JDG-CONF", claim_a="CLAIM-1", claim_b="CLAIM-2"),
            ),
        }
    )
    ctx = _compile(intent_state(sem))
    assert ctx.request is None
    assert [b.gap_kind for b in ctx.blockers] == [GapKind.CONTRADICTION]
    assert ctx.blockers[0].locus_representative_id == "ADDR-1"


def test_pending_material_governance_produces_missing_authority() -> None:
    """A held judgment bearing on the locus blocks it, via the existing attribution law.

    Built by recording a SUPERSEDE whose latest admission is REQUIRE_HUMAN and which was
    never applied, so ``derive_view`` reports it as pending rather than active.
    """
    from foundry.domain.events import SemanticAdmissionPayload
    from foundry.domain.semantic_judgment import AdmissionRoute

    state = simple_locus_state(extra_claims={"CLAIM-2": "JDG-2"})
    sem = state.semantic
    held = supersede_judgment("JDG-HELD", "JDG-2")
    sem = sem.model_copy(
        update={
            "judgments": {**dict(sem.judgments), "JDG-HELD": held},
            "admissions": {
                **dict(sem.admissions),
                "JDG-HELD": SemanticAdmissionPayload(
                    judgment_id="JDG-HELD",
                    route=AdmissionRoute.REQUIRE_HUMAN,
                    reasons=("AUTHORITY_UNRESOLVED",),
                ),
            },
        }
    )
    view = __import__("foundry.domain.semantic_view", fromlist=["derive_view"]).derive_view(sem)
    assert "JDG-HELD" in view.pending_judgment_ids, "the judgment must be pending to bite"

    ctx = _compile(intent_state(sem))
    assert ctx.request is None
    assert GapKind.MISSING_AUTHORITY in {b.gap_kind for b in ctx.blockers}


def test_an_undecided_claim_value_produces_missing_information() -> None:
    ctx = _compile(simple_locus_state(claim_kind=ClaimValueKind.UNDECIDED))
    assert ctx.request is None
    assert [b.gap_kind for b in ctx.blockers] == [GapKind.MISSING_INFORMATION]


def test_a_stale_current_head_produces_stale_evidence() -> None:
    """The locus still has a LIVE claim, but its current head version is stale.

    The head was minted by a judgment that has since been superseded, while a second
    claim keeps the locus non-OPEN — otherwise the locus would be filtered as OPEN
    before blockers are considered, and this rule would never be reached.
    """
    from foundry.domain.semantic_state import SupersessionRecord

    state = simple_locus_state(extra_claims={"CLAIM-2": "JDG-2"})
    sem = state.semantic
    sup = supersede_judgment("JDG-SUP", "JDG-1")
    sem = sem.model_copy(
        update={
            "judgments": {**dict(sem.judgments), "JDG-SUP": sup},
            "applied_judgment_ids": (*sem.applied_judgment_ids, "JDG-SUP"),
            "supersessions": (
                SupersessionRecord(
                    target_judgment_id="JDG-1",
                    superseding_judgment_id="JDG-SUP",
                    recorded_by_event_id="EVT-sup",
                ),
            ),
        }
    )
    view = __import__("foundry.domain.semantic_view", fromlist=["derive_view"]).derive_view(sem)
    assert "VER-1" in view.stale_ids, "the current head must be stale for this test to bite"
    assert view.loci[0].claim_ids == ("CLAIM-2",), "a live claim keeps the locus non-OPEN"

    ctx = _compile(intent_state(sem))
    assert ctx.request is None
    assert GapKind.STALE_EVIDENCE in {b.gap_kind for b in ctx.blockers}


def test_several_independent_blockers_are_all_represented_deterministically() -> None:
    """Evidence of additional blocking conditions is never silently discarded."""
    state = simple_locus_state(
        claim_kind=ClaimValueKind.UNDECIDED, extra_claims={"CLAIM-2": "JDG-2"}
    )
    sem = state.semantic
    conflict = conflict_judgment("JDG-CONF", "CLAIM-1", "CLAIM-2")
    sem = sem.model_copy(
        update={
            "judgments": {**dict(sem.judgments), "JDG-CONF": conflict},
            "applied_judgment_ids": (*sem.applied_judgment_ids, "JDG-CONF"),
            "conflicts": (
                __import__(
                    "foundry.domain.semantic_state", fromlist=["ConflictRecord"]
                ).ConflictRecord(judgment_id="JDG-CONF", claim_a="CLAIM-1", claim_b="CLAIM-2"),
            ),
        }
    )
    ctx = _compile(intent_state(sem))
    kinds = [b.gap_kind for b in ctx.blockers]
    assert len(kinds) >= 2
    assert kinds == sorted(kinds, key=lambda k: k.value)
    assert len(kinds) == len(set(kinds))


# --- the reconciliation negative control -------------------------------------------------


def test_a_stale_derived_requirement_does_not_block_the_locus_that_reconciles_it() -> None:
    """The load-bearing distinction: stale DOWNSTREAM intent must not deadlock context.

    If "stale locus" meant "something derived from this locus is stale", a corrected
    claim could never be offered to the synthesizer and the stale Requirement could
    never be reconciled.
    """
    from foundry.domain.derivation import DerivationEdge
    from foundry.domain.semantic_state import SupersessionRecord

    addr = address("ADDR-1")
    old_j = assert_judgment("JDG-OLD", "ADDR-1")
    new_j = assert_judgment("JDG-NEW", "ADDR-1")
    sup = supersede_judgment("JDG-SUP", "JDG-OLD")
    stale_req = requirement("REQ-old", basis_claim_ids=("CLAIM-OLD",))
    sem = semantic_state(
        evidence={"EV-1": evidence("EV-1")},
        addresses={"ADDR-1": addr},
        claims={
            "CLAIM-OLD": claim("CLAIM-OLD", "ADDR-1", judgment_id="JDG-OLD"),
            "CLAIM-NEW": claim("CLAIM-NEW", "ADDR-1", judgment_id="JDG-NEW"),
        },
        judgments={"JDG-OLD": old_j, "JDG-NEW": new_j, "JDG-SUP": sup},
        applied_judgment_ids=("JDG-OLD", "JDG-NEW", "JDG-SUP"),
        supersessions=(
            SupersessionRecord(
                target_judgment_id="JDG-OLD",
                superseding_judgment_id="JDG-SUP",
                recorded_by_event_id="EVT-sup",
            ),
        ),
        derivations=(
            DerivationEdge(child_id="REQ-old", parent_id="JDG-OLD", recorded_by_event_id="EVT-syn"),
        ),
        # The CURRENT head was minted by the surviving judgment, so the locus is fresh.
        issue_versions={"V-NEW": version("V-NEW", "ADDR-1", ("CLAIM-NEW",), "JDG-NEW")},
        issue_heads={"ADDR-1": "V-NEW"},
    )
    state = intent_state(sem, {"REQ-old": stale_req})
    ctx = _compile(state)

    assert ctx.request is not None, "the corrected locus must remain eligible"
    assert GapKind.STALE_EVIDENCE not in {b.gap_kind for b in ctx.blockers}
    shown = {c.claim_id for b in ctx.request.basis for c in b.live_claims}
    assert shown == {"CLAIM-NEW"}
    known = {k.object_id: k for k in ctx.request.known_intent_objects}
    assert known["REQ-old"].is_stale is True
    assert known["REQ-old"].lifecycle is LifecycleStatus.ACTIVE


# --- known intent objects ------------------------------------------------------------------


def test_only_current_in_scope_intent_bearing_objects_appear() -> None:
    objs = {
        "REQ-ok": requirement("REQ-ok"),
        "REQ-rejected": requirement("REQ-rejected", authority=Authority.REJECTED),
        "REQ-superseded": requirement("REQ-superseded", lifecycle=LifecycleStatus.SUPERSEDED),
        "REQ-elsewhere": requirement("REQ-elsewhere", scope=("relay",)),
    }
    ctx = _compile(simple_locus_state(objects=objs))
    assert ctx.request is not None
    assert {k.object_id for k in ctx.request.known_intent_objects} == {"REQ-ok"}


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (SemanticKind.INTENT, "THE MISSION"),
        (SemanticKind.GOAL, "GOAL-S"),
        (SemanticKind.OUTCOME, "OUTCOME-S"),
        (SemanticKind.REQUIREMENT, "REQ-S"),
        (SemanticKind.CONSTRAINT, "CONSTR-S"),
        (SemanticKind.NON_GOAL, "NONGOAL-S"),
        (SemanticKind.PREFERENCE, "PREF-S"),
        (SemanticKind.DECISION, "DEC-S"),
        (SemanticKind.ASSUMPTION, "ASSUM-S"),
        (SemanticKind.CONTRACT, "CONTR-S"),
    ],
)
def test_statement_extraction_for_every_intent_bearing_kind(
    kind: SemanticKind, expected: str
) -> None:
    obj = object_of_kind(kind)
    ctx = _compile(simple_locus_state(objects={obj.id: obj}))
    assert ctx.request is not None
    known = ctx.request.known_intent_objects[0]
    assert known.kind is kind
    assert known.statement == expected


def test_a_decision_exposes_its_statement_never_its_rationale() -> None:
    obj = object_of_kind(SemanticKind.DECISION)
    ctx = _compile(simple_locus_state(objects={obj.id: obj}))
    assert ctx.request is not None
    rendered = json.dumps(ctx.request.model_dump(mode="json"))
    assert "DEC-RATIONALE" not in rendered


def test_materiality_is_exposed_only_for_requirements() -> None:
    req = object_of_kind(SemanticKind.REQUIREMENT, "OBJ-R")
    goal = object_of_kind(SemanticKind.GOAL, "OBJ-G")
    ctx = _compile(simple_locus_state(objects={req.id: req, goal.id: goal}))
    assert ctx.request is not None
    by_id = {k.object_id: k for k in ctx.request.known_intent_objects}
    assert by_id["OBJ-R"].materiality is Materiality.HIGH
    assert by_id["OBJ-G"].materiality is None


def test_a_legacy_object_with_no_v2_claim_basis_exposes_empty_basis_fields() -> None:
    """A DERIVED_FROM target that is not a v2 SemanticClaim is never treated as one."""
    legacy = requirement("REQ-legacy", basis_claim_ids=("NOT-A-CLAIM",))
    ctx = _compile(simple_locus_state(objects={legacy.id: legacy}))
    assert ctx.request is not None
    known = ctx.request.known_intent_objects[0]
    assert known.basis_claim_ids == ()
    assert known.basis_locus_ids == ()


def test_basis_locus_ids_are_derived_from_real_claims() -> None:
    derived = requirement("REQ-derived", basis_claim_ids=("CLAIM-1",))
    ctx = _compile(simple_locus_state(objects={derived.id: derived}))
    assert ctx.request is not None
    known = ctx.request.known_intent_objects[0]
    assert known.basis_claim_ids == ("CLAIM-1",)
    assert known.basis_locus_ids == ("ADDR-1",)


# --- D9 bounds -------------------------------------------------------------------------------


def test_exactly_the_threshold_is_legal_and_one_more_refuses() -> None:
    at_cap = {
        f"REQ-{i:04d}": requirement(f"REQ-{i:04d}") for i in range(KNOWN_INTENT_OBJECT_THRESHOLD)
    }
    ctx = _compile(simple_locus_state(objects=at_cap))
    assert ctx.request is not None
    assert len(ctx.request.known_intent_objects) == KNOWN_INTENT_OBJECT_THRESHOLD

    over = {**at_cap, "REQ-9999": requirement("REQ-9999")}
    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_ABOVE_THRESHOLD"):
        _compile(simple_locus_state(objects=over))


def test_the_character_cap_refuses_rather_than_truncating() -> None:
    huge = {f"REQ-{i:03d}": requirement(f"REQ-{i:03d}", statement="x" * 4000) for i in range(60)}
    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_KNOWN_INTENT_CONTEXT"):
        _compile(simple_locus_state(objects=huge))


def test_the_canonical_rendering_helpers_agree() -> None:
    ctx = _compile(simple_locus_state(objects={"REQ-1": requirement("REQ-1")}))
    assert ctx.request is not None
    objects = ctx.request.known_intent_objects
    rendered = known_intent_context_json(objects)
    assert rendered == json.dumps(
        [o.model_dump(mode="json") for o in objects],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert known_intent_context_character_count(objects) == len(rendered)


def test_the_bounds_reuse_the_existing_constants() -> None:
    from foundry.application.assimilation_context import CANDIDATE_ADDRESS_THRESHOLD
    from foundry.application.contrastive_context import MAX_COMPARISON_CONTEXT_CHARS as CHARS

    assert KNOWN_INTENT_OBJECT_THRESHOLD == CANDIDATE_ADDRESS_THRESHOLD == 200
    assert MAX_KNOWN_INTENT_CONTEXT_CHARS == CHARS == 131_072


# --- determinism -------------------------------------------------------------------------------


def test_compilation_is_deterministic_and_leaves_state_untouched() -> None:
    state = simple_locus_state(
        objects={"REQ-b": requirement("REQ-b"), "REQ-a": requirement("REQ-a")}
    )
    before = state.model_dump(mode="json")
    first = _compile(state)
    second = _compile(state)
    assert first == second
    assert state.model_dump(mode="json") == before
    assert first.request is not None
    assert [k.object_id for k in first.request.known_intent_objects] == ["REQ-a", "REQ-b"]


# --- result validation ----------------------------------------------------------------------------


def _request(state) -> IntentSynthesisRequest:  # type: ignore[no-untyped-def]
    ctx = _compile(state)
    assert ctx.request is not None
    return ctx.request


def test_a_proposal_citing_a_shown_claim_is_accepted() -> None:
    state = simple_locus_state()
    request = _request(state)
    validated = validate_intent_synthesis_result(
        state=state, request=request, result=IntentSynthesisResult(proposals=(_proposal(),))
    )
    assert len(validated) == 1
    assert isinstance(validated[0], ValidatedSynthesisProposal)
    assert validated[0].basis_locus_ids == ("ADDR-1",)


def test_a_claim_in_state_but_absent_from_the_request_is_refused() -> None:
    """The model cannot cite invisible state."""
    state = simple_locus_state(address_scope=(SCOPE,))
    request = _request(state)
    # CLAIM-HIDDEN exists in state but at an out-of-scope address, so was never shown.
    sem = state.semantic
    hidden_addr = address("ADDR-HID", scope=("relay",))
    sem = sem.model_copy(
        update={
            "addresses": {**dict(sem.addresses), "ADDR-HID": hidden_addr},
            "claims": {
                **dict(sem.claims),
                "CLAIM-HIDDEN": claim("CLAIM-HIDDEN", "ADDR-HID", judgment_id="JDG-H"),
            },
            "judgments": {
                **dict(sem.judgments),
                "JDG-H": assert_judgment("JDG-H", "ADDR-HID"),
            },
            "applied_judgment_ids": (*sem.applied_judgment_ids, "JDG-H"),
        }
    )
    state2 = intent_state(sem)
    with pytest.raises(IntentSynthesisResultError, match="CLAIM-HIDDEN"):
        validate_intent_synthesis_result(
            state=state2,
            request=request,
            result=IntentSynthesisResult(proposals=(_proposal(basis_claim_ids=("CLAIM-HIDDEN",)),)),
        )


def test_a_target_kind_outside_the_allowed_set_refuses_the_whole_result() -> None:
    state = simple_locus_state()
    request = _request(state).model_copy(update={"allowed_target_kinds": frozenset()})
    with pytest.raises(IntentSynthesisResultError, match="target kind|REQUIREMENT"):
        validate_intent_synthesis_result(
            state=state, request=request, result=IntentSynthesisResult(proposals=(_proposal(),))
        )


def test_one_bad_proposal_refuses_the_whole_result() -> None:
    state = simple_locus_state()
    request = _request(state)
    good = _proposal()
    bad = RequirementSynthesisProposal(
        model_proposal_id="p2",
        disposition=IntentDisposition.NEW,
        statement="s",
        rationale="r",
        basis_claim_ids=("CLAIM-INVISIBLE",),
    )
    with pytest.raises(IntentSynthesisResultError):
        validate_intent_synthesis_result(
            state=state, request=request, result=IntentSynthesisResult(proposals=(good, bad))
        )


def test_an_unrelated_same_locus_claim_is_not_auto_added() -> None:
    """I17: citing CLAIM-1 must not silently acquire CLAIM-2 from the same locus."""
    state = simple_locus_state(extra_claims={"CLAIM-2": "JDG-2"})
    request = _request(state)
    shown = {c.claim_id for b in request.basis for c in b.live_claims}
    assert shown == {"CLAIM-1", "CLAIM-2"}
    validated = validate_intent_synthesis_result(
        state=state,
        request=request,
        result=IntentSynthesisResult(proposals=(_proposal(basis_claim_ids=("CLAIM-1",)),)),
    )
    assert validated[0].proposal.basis_claim_ids == ("CLAIM-1",)
    assert "CLAIM-2" not in validated[0].proposal.basis_claim_ids


def test_basis_locus_ids_cover_only_the_cited_loci() -> None:
    """I17 at locus level: citing one locus must not acquire the other.

    Two independent loci are shown; the proposal cites a claim from only one. The
    derived ``basis_locus_ids`` must name that locus alone — widening it would wire an
    unrelated locus into the blast radius and cause false-positive staleness later.
    """
    a = address("ADDR-A", subject="A", facet="A?")
    b = address("ADDR-B", subject="B", facet="B?")
    sem = semantic_state(
        evidence={"EV-1": evidence("EV-1")},
        addresses={"ADDR-A": a, "ADDR-B": b},
        claims={
            "CLAIM-A": claim("CLAIM-A", "ADDR-A", judgment_id="JDG-A"),
            "CLAIM-B": claim("CLAIM-B", "ADDR-B", judgment_id="JDG-B"),
        },
        judgments={
            "JDG-A": assert_judgment("JDG-A", "ADDR-A"),
            "JDG-B": assert_judgment("JDG-B", "ADDR-B"),
        },
        applied_judgment_ids=("JDG-A", "JDG-B"),
        issue_versions={
            "V-A": version("V-A", "ADDR-A", ("CLAIM-A",), "JDG-A"),
            "V-B": version("V-B", "ADDR-B", ("CLAIM-B",), "JDG-B"),
        },
        issue_heads={"ADDR-A": "V-A", "ADDR-B": "V-B"},
    )
    state = intent_state(sem)
    request = _request(state)
    assert len(request.basis) == 2, "both loci must be shown for this test to bite"

    validated = validate_intent_synthesis_result(
        state=state,
        request=request,
        result=IntentSynthesisResult(proposals=(_proposal(basis_claim_ids=("CLAIM-A",)),)),
    )
    assert validated[0].basis_locus_ids == ("ADDR-A",)
    assert "ADDR-B" not in validated[0].basis_locus_ids


def test_target_scope_is_derived_from_the_cited_addresses() -> None:
    state = simple_locus_state()
    validated = validate_intent_synthesis_result(
        state=state,
        request=_request(state),
        result=IntentSynthesisResult(proposals=(_proposal(),)),
    )
    assert validated[0].target_scope == (SCOPE,)


def test_a_project_wide_address_yields_a_project_wide_target_scope() -> None:
    """``()`` is never replaced by the request scope; structural truth is runtime-owned."""
    state = simple_locus_state(address_scope=())
    validated = validate_intent_synthesis_result(
        state=state,
        request=_request(state),
        result=IntentSynthesisResult(proposals=(_proposal(),)),
    )
    assert validated[0].target_scope == ()


# --- disposition snapshot legality (R1) -----------------------------------------------------------


def _with_known(is_stale: bool) -> tuple:  # type: ignore[type-arg]
    """A state whose known snapshot holds one object, stale or not."""
    from foundry.domain.derivation import DerivationEdge
    from foundry.domain.semantic_state import SupersessionRecord

    obj = requirement("REQ-known", basis_claim_ids=("CLAIM-1",))
    state = simple_locus_state(objects={obj.id: obj})
    if not is_stale:
        return state, _request(state)
    sem = state.semantic
    sup = supersede_judgment("JDG-SUP", "JDG-1")
    extra = assert_judgment("JDG-2", "ADDR-1")
    sem = sem.model_copy(
        update={
            "claims": {
                **dict(sem.claims),
                "CLAIM-2": claim("CLAIM-2", "ADDR-1", judgment_id="JDG-2"),
            },
            "judgments": {**dict(sem.judgments), "JDG-SUP": sup, "JDG-2": extra},
            "applied_judgment_ids": (*sem.applied_judgment_ids, "JDG-2", "JDG-SUP"),
            "supersessions": (
                SupersessionRecord(
                    target_judgment_id="JDG-1",
                    superseding_judgment_id="JDG-SUP",
                    recorded_by_event_id="EVT-sup",
                ),
            ),
            "derivations": (
                DerivationEdge(
                    child_id="REQ-known", parent_id="JDG-1", recorded_by_event_id="EVT-syn"
                ),
            ),
            "issue_versions": {"V-2": version("V-2", "ADDR-1", ("CLAIM-2",), "JDG-2")},
            "issue_heads": {"ADDR-1": "V-2"},
        }
    )
    state2 = intent_state(sem, {obj.id: obj})
    return state2, _request(state2)


def test_existing_unchanged_accepts_a_current_object() -> None:
    state, request = _with_known(is_stale=False)
    validated = validate_intent_synthesis_result(
        state=state,
        request=request,
        result=IntentSynthesisResult(
            proposals=(
                _proposal(
                    disposition=IntentDisposition.EXISTING_UNCHANGED,
                    relates_to_object_id="REQ-known",
                ),
            )
        ),
    )
    assert validated[0].proposal.relates_to_object_id == "REQ-known"


def test_existing_unchanged_on_a_stale_object_is_refused() -> None:
    state, request = _with_known(is_stale=True)
    assert {k.object_id: k.is_stale for k in request.known_intent_objects}["REQ-known"] is True
    with pytest.raises(IntentSynthesisResultError, match="stale"):
        validate_intent_synthesis_result(
            state=state,
            request=request,
            result=IntentSynthesisResult(
                proposals=(
                    _proposal(
                        basis_claim_ids=("CLAIM-2",),
                        disposition=IntentDisposition.EXISTING_UNCHANGED,
                        relates_to_object_id="REQ-known",
                    ),
                )
            ),
        )


def test_replaces_stale_requires_a_stale_target() -> None:
    state, request = _with_known(is_stale=False)
    with pytest.raises(IntentSynthesisResultError, match="stale"):
        validate_intent_synthesis_result(
            state=state,
            request=request,
            result=IntentSynthesisResult(
                proposals=(
                    _proposal(
                        disposition=IntentDisposition.REPLACES_STALE,
                        relates_to_object_id="REQ-known",
                    ),
                )
            ),
        )


def test_replaces_stale_accepts_a_stale_target() -> None:
    state, request = _with_known(is_stale=True)
    validated = validate_intent_synthesis_result(
        state=state,
        request=request,
        result=IntentSynthesisResult(
            proposals=(
                _proposal(
                    basis_claim_ids=("CLAIM-2",),
                    disposition=IntentDisposition.REPLACES_STALE,
                    relates_to_object_id="REQ-known",
                ),
            )
        ),
    )
    assert validated[0].proposal.relates_to_object_id == "REQ-known"


def test_a_related_object_absent_from_the_snapshot_is_refused() -> None:
    """Exactly the id proposed; never a stale sibling or 'the latest equivalent'."""
    state, request = _with_known(is_stale=True)
    with pytest.raises(IntentSynthesisResultError, match="REQ-elsewhere"):
        validate_intent_synthesis_result(
            state=state,
            request=request,
            result=IntentSynthesisResult(
                proposals=(
                    _proposal(
                        basis_claim_ids=("CLAIM-2",),
                        disposition=IntentDisposition.REPLACES_STALE,
                        relates_to_object_id="REQ-elsewhere",
                    ),
                )
            ),
        )


def test_gap_proposals_are_preserved_verbatim_and_never_become_durable() -> None:
    state = simple_locus_state()
    result = IntentSynthesisResult(proposals=(_proposal(),))
    validated = validate_intent_synthesis_result(
        state=state, request=_request(state), result=result
    )
    assert result.gap_proposals == ()
    assert all(not hasattr(v, "gap_id") for v in validated)


# --- no second ledger -----------------------------------------------------------------------------


def test_the_context_models_are_not_durable_truth() -> None:
    from foundry.domain.events import EventPayload
    from foundry.domain.intent_synthesis_state import IntentSynthesisState
    from foundry.domain.state import IntentState

    context_types = {
        "IntentSynthesisRequest",
        "KnownIntentObject",
        "LocusBasis",
        "BasisClaim",
        "SynthesisContextBlocker",
        "IntentSynthesisContext",
        "ValidatedSynthesisProposal",
    }
    payload_names = {t.__name__ for t in EventPayload.__value__.__args__}  # type: ignore[attr-defined]
    assert not context_types & payload_names
    assert not context_types & set(IntentState.model_fields)
    assert not context_types & set(IntentSynthesisState.model_fields)
    for field in ("known_intent_objects", "basis", "blockers"):
        assert field not in IntentState.model_fields
        assert field not in IntentSynthesisState.model_fields
