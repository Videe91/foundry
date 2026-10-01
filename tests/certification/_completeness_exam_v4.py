"""Certification exam v4 for SEMANTIC_COMPLETENESS_VERIFICATION (IE2 Call 3), test-only.

**Why v4 exists.** Exam v3 (``_completeness_exam_v3``, sat live once by ``openai/gpt-6-astra``:
NOT CERTIFIED 74/75, frozen) scored a missing ACTOR with an enumerated list of role phrases.
Its one failure, C05 attempt 1, answered "The permission to renew a loan is granted to a
member." -- a correct finding the list did not admit. The verifier policy
``ie2-semantic-completeness-v1``, its instruction, schema and runtime are unchanged; every
model-visible request, every semantic inventory and every non-ACTOR marker group is v3's,
carried by reference. Only the scoring of a missing ACTOR changes.

**The ACTOR law.** A missing ACTOR assertion is identified by one finding item that names, in
any order, voice or grammatical form, all three of: the actor concept, the governed action
family and the role / permission relation -- and that does not state the inverse relation
("may not", "denied", ...). For a restriction ("only members may reserve"), an item naming the
excluded complement ("non-members") with the governed action and the inverse relation states
the same rule and identifies it; affirming the complement never does. Actor and action alone
never identify an actor. Matching is v2's normalised whole-word / phrase matching, with v2's
keyword-stuffing and echo rules; nothing is fuzzy.

Everything else is v3's law: the semantic inventory, the derived verdict
(CONTRADICTORY > INCOMPLETE > OVERREACH > COMPLETE), every sealed assertion in the verdict's
region a required finding, several items jointly covering them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    PropositionReview,
    report_findings,
)
from foundry.model_runtime.domain import (
    ModelExecutionConstraints,
    ModelIdentity,
    ModelTask,
    ModelTier,
)
from tests.certification._certification_run import Contestant
from tests.certification._completeness_exam import (
    BINDING_FIELDS,
    CERTIFIED_CONFIGURATION,
    COMPLETENESS_ACCEPTANCE_RULE,
    COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
    COMPLETENESS_EXAM_ID,
    COMPLETENESS_RUNS_PER_CASE,
    EXPECTED_INSTRUCTION_SHA256,
    EXPECTED_VERIFIER_POLICY_ID,
    EXPECTED_VERIFIER_POLICY_VERSION,
    CompletenessObservation,
    MarkerGroup,
    PriorExam,
    ProviderConfiguration,
    _is_stuffed,
    _restates,
    attempt_evidence,
    certificate_binds,
    identifies,
    mentions,
    normalise,
    render_request,
    score_completeness_global_gates,
)
from tests.certification._completeness_exam import _region as region_items
from tests.certification._completeness_exam_v3 import (
    ACTOR_MEMBER,
    ASSERTION_KINDS,
    STATUSES,
    AssertionKind,
    DerivedExpectation,
    InventoryCase,
    PropositionInventory,
    Status,
    derive_verdict,
    executable,
    run_completeness_attempt,
)
from tests.certification._completeness_exam_v3 import CASES as V3_CASES
from tests.certification._completeness_exam_v3 import (
    COMPLETENESS_EXAM_VERSION as V3_EXAM_VERSION,
)
from tests.certification._completeness_exam_v3 import (
    EXPECTED_COMPLETENESS_EXAM_SHA256 as V3_EXAM_SHA256,
)
from tests.certification._completeness_exam_v3 import PRIOR_EXAMS as V3_PRIOR_EXAMS
from tests.certification._completeness_exam_v3 import OperativeAssertion as V3Assertion
from tests.certification._completeness_exam_v3 import RequiredFinding as V3Finding
from tests.certification._exam_identity import canonical_digest, code_closure
from tests.certification._schema_identity import schema_sha256

PROJECT: Final = "PROJ-A"

COMPLETENESS_EXAM_VERSION: Final = "ie2-semantic-completeness-exam-v4"
COMPLETENESS_EVIDENCE_NAMESPACE: Final = "semantic_completeness_verification_exam_v4"
"""Where an exam-v4 certification's evidence is written. Exams v2 and v3's namespaces are
history."""
HISTORICAL_EXAM_V3_NAMESPACE: Final = "semantic_completeness_verification_exam_v3"
"""Exam v3 under ``ie2-semantic-completeness-v1``: Astra NOT CERTIFIED 74/75. Immutable."""
HISTORICAL_V3_RECORD_SHA256: Final = (
    "0548fd47ae106b9592530e35776324bf0abe31bf2d90f713bdf07124c62a0319"
)
"""SHA-256 of exam v3's live record exactly as committed at 8db3ab8; never rewritten."""
COMPLETENESS_SEAL_PATH: Final = Path(
    "tests/certification/exam_manifests/ie2-semantic-completeness-exam-v4.seal.json"
)
COMPLETENESS_CALL_BUDGET: Final = 75
"""``len(CASES) * COMPLETENESS_RUNS_PER_CASE``, pasted and sealed before any live call."""
EXPECTED_COMPLETENESS_EXAM_SHA256: Final = (
    "415f142fdea1e1c64fc1b937155f244909abcda6d5f0992ea03856e0781a176f"
)
"""``completeness_exam_sha256()``, pasted, never computed at import."""


# --- the ACTOR law: the semantic role triple ACTOR -> ROLE -> GOVERNED ACTION ------------------


@dataclass(frozen=True)
class ActorRole:
    """The sealed groups of one scored ACTOR assertion; the engine below is generic."""

    actor: MarkerGroup
    action: MarkerGroup
    """The governed action as a verb (or light-verb phrase): renew, make a reservation."""
    action_noun: MarkerGroup
    """The governed action as a noun: renewal, reservation."""
    modal: MarkerGroup
    """Modals of the role relation: {actor} may / can {action}."""
    licensed: MarkerGroup
    """Licence predicates: {actor} is permitted / allowed / entitled to {action}."""
    grant: MarkerGroup
    """Grant attachments: {action} ... is granted / limited / restricted to {actor}."""
    complement: MarkerGroup | None = None
    """For a restriction only: the excluded actors, of whom the denied relation IS the rule
    ({complement} cannot {action}). A permission has no contrapositive."""


COPULAS: Final = ("is", "are", "was", "were", "be")
DETERMINERS: Final = ("a", "an", "the", "any", "all", "every", "each", "their", "its")
ACTOR_MODIFIERS: Final = ("with", "without", "who", "that", "whose", "over", "under", "aged")
"""A modifier of the actor ({actor} with no outstanding fines may ...): up to MODIFIER_SPAN."""
MODIFIER_SPAN: Final = 5
GAP_SPAN: Final = 6
"""How many tokens may separate an action from its grant attachment (an object, a copula)."""
SPAN_BREAKS: Final = (
    "not", "no", "never", "nor", "neither", "without", "cannot",
    "if", "when", "unless", "because", "but", "while", "where", "whereas", "although",
    "though", "provided", "except", "and", "or", "whether", "until",
)  # fmt: skip
"""Neither a negation nor a new clause may sit inside a bound span: polarity and attachment."""
BYSTANDER_QUALIFIERS: Final = ("other", "another", "else", "next", "non")
"""Defensive guard only: an actor so qualified is someone else, never the role holder."""
DENIED_MODALS: Final = ("cannot", "can not", "may not", "must not")


def _ends(tokens: list[str], i: int, phrases: tuple[str, ...]) -> list[int]:
    out = []
    for phrase in phrases:
        words = normalise(phrase).split()
        if words and tokens[i : i + len(words)] == words:
            out.append(i + len(words))
    return out


def _g(tokens: list[str], i: int, group: MarkerGroup) -> list[int]:
    return _ends(tokens, i, (*group.markers, *group.synonyms))


def _actor_ends(tokens: list[str], i: int, actor: MarkerGroup) -> list[int]:
    """The actor at ``i``, unless qualified as somebody else (the defensive guard)."""
    if i > 0 and tokens[i - 1] in BYSTANDER_QUALIFIERS:
        return []
    return _g(tokens, i, actor)


def _after_modifier(tokens: list[str], j: int) -> list[int]:
    """Where the role may start after an actor: at once, or past one actor modifier."""
    if j < len(tokens) and tokens[j] in ACTOR_MODIFIERS:
        return [j, *range(j + 2, min(j + 2 + MODIFIER_SPAN, len(tokens) + 1))]
    return [j]


def _skip(tokens: list[str], j: int, words: tuple[str, ...]) -> int:
    return j + 1 if j < len(tokens) and tokens[j] in words else j


def _licensed_to_act(tokens: list[str], k: int, role: ActorRole) -> bool:
    for licensed in _g(tokens, k, role.licensed):
        if tokens[licensed : licensed + 1] == ["to"] and _g(tokens, licensed + 1, role.action):
            return True
    return False


def _actor_then_role(tokens: list[str], role: ActorRole) -> bool:
    """{actor} [modifier] [only] {modal} {action}  |  {actor} is [only] {licensed} to {action}"""
    for i in range(len(tokens)):
        for e in _actor_ends(tokens, i, role.actor):
            for j in _after_modifier(tokens, e):
                j = _skip(tokens, j, ("only",))
                if any(_g(tokens, m, role.action) for m in _g(tokens, j, role.modal)):
                    return True
                copula = j < len(tokens) and tokens[j] in COPULAS
                if copula and _licensed_to_act(tokens, _skip(tokens, j + 1, ("only",)), role):
                    return True
    return False


def _role_then_actor(tokens: list[str], role: ActorRole) -> bool:
    """{action | action noun} ...gap... {grant} [determiner] {actor}"""
    for i in range(len(tokens)):
        for e in (*_g(tokens, i, role.action), *_g(tokens, i, role.action_noun)):
            for k in range(e, min(e + GAP_SPAN, len(tokens)) + 1):
                if any(t in SPAN_BREAKS for t in tokens[e:k]):
                    break
                for t in _g(tokens, k, role.grant):
                    if _actor_ends(tokens, _skip(tokens, t, DETERMINERS), role.actor):
                        return True
    return False


def _complement_denied(tokens: list[str], role: ActorRole) -> bool:
    """A restriction's contrapositive: {complement} cannot {action} | is not {licensed} to"""
    if role.complement is None:
        return False
    for i in range(len(tokens)):
        for e in _g(tokens, i, role.complement):
            for j in _after_modifier(tokens, e):
                if any(_g(tokens, d, role.action) for d in _ends(tokens, j, DENIED_MODALS)):
                    return True
                denied = (
                    tokens[j : j + 1] and tokens[j] in COPULAS and tokens[j + 1 : j + 2] == ["not"]
                )
                if denied and _licensed_to_act(tokens, j + 2, role):
                    return True
    return False


def identifies_actor(items: tuple[str, ...], role: ActorRole, statement: str) -> bool:
    """One item binding the triple: the relation governs the action and the actor fills the
    actor slot of that construction, with the sealed polarity. Co-occurrence never counts;
    neither does a bare list of markers or an echo of the whole proposition."""
    groups = (role.actor, role.action, role.action_noun, role.modal, role.licensed)
    for item in items:
        if _restates(item, statement) or _is_stuffed(item, groups):
            continue
        tokens = normalise(item).split()
        if (
            _actor_then_role(tokens, role)
            or _role_then_actor(tokens, role)
            or _complement_denied(tokens, role)
        ):
            return True
    return False


# --- the semantic inventory (v3's, with a structural ACTOR) -------------------------------------


@dataclass(frozen=True)
class OperativeAssertion(V3Assertion):
    """v3's assertion; a missing ACTOR carries its ``role`` instead of marker groups."""

    role: ActorRole | None = None


@dataclass(frozen=True)
class RequiredFinding(V3Finding):
    role: ActorRole | None = None


def _phrases(text: str | tuple[str, ...]) -> tuple[str, ...]:
    return (text,) if isinstance(text, str) else text


def held(
    kind: AssertionKind, stated: str | tuple[str, ...], claimed: str | tuple[str, ...], *by: str
) -> OperativeAssertion:
    return OperativeAssertion(kind, "REPRESENTED", _phrases(stated), _phrases(claimed), by)


def lost(
    kind: AssertionKind, stated: str | tuple[str, ...], *groups: MarkerGroup
) -> OperativeAssertion:
    return OperativeAssertion(kind, "MISSING", _phrases(stated), groups=groups)


def lost_actor(stated: str | tuple[str, ...], role: ActorRole) -> OperativeAssertion:
    return OperativeAssertion("ACTOR", "MISSING", _phrases(stated), role=role)


def added(
    kind: AssertionKind, claimed: str | tuple[str, ...], by: str, *groups: MarkerGroup
) -> OperativeAssertion:
    return OperativeAssertion(kind, "UNSUPPORTED", (), _phrases(claimed), (by,), groups)


def clash(
    kind: AssertionKind,
    stated: str | tuple[str, ...],
    claimed: str | tuple[str, ...],
    by: str,
    *groups: MarkerGroup,
) -> OperativeAssertion:
    return OperativeAssertion(
        kind, "CONTRADICTED", _phrases(stated), _phrases(claimed), (by,), groups
    )


def _claim_text(review: PropositionReview, refs: tuple[str, ...]) -> str:
    return " ".join(f"{c.subject} {c.predicate} {c.value}" for c in review.claims if c.ref in refs)


def _role(a: V3Assertion) -> ActorRole | None:
    return a.role if isinstance(a, OperativeAssertion) else None


def inventory_problems(
    review: PropositionReview, inventory: PropositionInventory
) -> tuple[str, ...]:
    """v3's coherence law, with one change: a scored (non-REPRESENTED) ACTOR assertion is
    identified by its ``role`` and seals no plain marker groups; nothing else has a role."""
    where = review.proposition_id
    refs = tuple(c.ref for c in review.claims)
    every_claim = _claim_text(review, refs)
    problems: list[str] = []
    if not any(a.status != "UNSUPPORTED" for a in inventory.assertions):
        problems.append(f"{where}: no operative assertion of the proposition is inventoried")
    for a in inventory.assertions:
        label = f"{where} {a.kind} {a.status}"
        role = _role(a)
        scored_actor = a.kind == "ACTOR" and a.status != "REPRESENTED"
        if a.kind not in ASSERTION_KINDS:
            problems.append(f"{label}: unknown kind")
        if a.status not in STATUSES:
            problems.append(f"{label}: unknown status")
        for ref in a.by:
            if ref not in refs:
                problems.append(f"{label}: {ref} is not a claim of {where}")
        if a.status in ("REPRESENTED", "UNSUPPORTED", "CONTRADICTED") and not a.by:
            problems.append(f"{label}: names no claim")
        if a.status == "REPRESENTED" and (a.groups or role is not None):
            problems.append(f"{label}: a represented assertion seals no finding")
        if scored_actor and (role is None or a.groups):
            problems.append(f"{label}: a missing actor is scored by its role alone")
        if not scored_actor and role is not None:
            problems.append(f"{label}: only a scored actor carries a role")
        if a.status != "REPRESENTED" and not scored_actor and not a.groups:
            problems.append(f"{label}: no finding markers")
        if a.status != "UNSUPPORTED" and not a.stated:
            problems.append(f"{label}: states nothing of the proposition")
        for phrase in a.stated:
            if not mentions(review.statement, phrase):
                problems.append(f"{label}: {phrase!r} is not in the proposition")
        for phrase in a.claimed:
            if not mentions(_claim_text(review, a.by), phrase):
                problems.append(f"{label}: {phrase!r} is not in its claims")
        if a.status == "MISSING":
            for phrase in a.stated:
                if mentions(every_claim, phrase):
                    problems.append(f"{label}: {phrase!r} is stated by a claim")
        if a.status == "UNSUPPORTED":
            for phrase in a.claimed:
                if mentions(review.statement, phrase):
                    problems.append(f"{label}: {phrase!r} is in the proposition")
    classified = {ref for a in inventory.assertions for ref in a.by}
    for ref in refs:
        if ref not in classified:
            problems.append(f"{where}: claim {ref} is unclassified")
    if inventory.forbidden and derive_verdict(inventory) == "COMPLETE":
        problems.append(f"{where}: a forbidden interpretation on a COMPLETE proposition")
    return tuple(problems)


_REGION_STATUS: Final[dict[str, Status]] = {
    "INCOMPLETE": "MISSING",
    "OVERREACH": "UNSUPPORTED",
    "CONTRADICTORY": "CONTRADICTED",
}


def expectation(inventory: PropositionInventory) -> DerivedExpectation:
    verdict = derive_verdict(inventory)
    region = _REGION_STATUS.get(verdict)
    findings = tuple(
        RequiredFinding(f"{a.kind} {' / '.join(a.stated or a.claimed)}", a.groups, _role(a))
        for a in inventory.assertions
        if a.status == region
    )
    return DerivedExpectation(inventory.proposition_id, verdict, findings, inventory.forbidden)


def inventory_case(
    number: int, category: str, *items: tuple[PropositionReview, PropositionInventory]
) -> InventoryCase:
    """Neutral model-visible ids only; refuses an incoherent inventory rather than build it."""
    for review, inventory in items:
        if review.proposition_id != inventory.proposition_id:
            raise ValueError("an inventory names its own proposition")
        problems = inventory_problems(review, inventory)
        if problems:
            raise ValueError(f"C{number:02d}: {'; '.join(problems)}")
    return InventoryCase(
        case_id=f"C{number:02d}",
        category=category,
        request=CompletenessRequest(
            project_id=PROJECT,
            subject_invocation_id=f"INV-{number:04d}",
            propositions=tuple(review for review, _ in items),
        ),
        inventory=tuple(inventory for _, inventory in items),
        expected=tuple(expectation(inventory) for _, inventory in items),
    )


# --- the actor roles ----------------------------------------------------------------------------

MAY: Final = MarkerGroup("may or can", ("may", "can"))
LICENSED: Final = MarkerGroup(
    "licensed",
    ("permitted", "allowed", "entitled"),
    ("authorised", "authorized", "able", "eligible"),
)
GRANTED: Final = MarkerGroup(
    "granted to",
    ("granted to", "limited to", "restricted to", "reserved for"),
    ("given to", "available to", "open to", "belongs to", "confined to"),
)
RENEWER_ROLE: Final = ActorRole(
    actor=ACTOR_MEMBER,
    action=MarkerGroup("renew", ("renew",), ("extend",)),
    action_noun=MarkerGroup(
        "renewal",
        ("renewal", "renewals", "renewing"),
        ("extension", "extensions", "extending"),
    ),
    modal=MAY,
    licensed=LICENSED,
    grant=GRANTED,
)
"""C05: "A member may renew a loan ..." -- a permission; it has no contrapositive."""
RESERVER_ROLE: Final = ActorRole(
    actor=ACTOR_MEMBER,
    action=MarkerGroup(
        "reserve",
        ("reserve", "make a reservation", "make reservations", "place a reservation"),
        ("place reservations", "place a hold", "book"),
    ),
    action_noun=MarkerGroup(
        "reservation",
        ("reservation", "reservations", "reserving"),
        ("holds", "booking", "bookings"),
    ),
    modal=MAY,
    licensed=LICENSED,
    grant=GRANTED,
    complement=MarkerGroup(
        "non-members",
        ("non member", "non members", "nonmember", "nonmembers"),
        ("not a member", "not members"),
    ),
)
"""C16: "Only members ... may reserve a book" -- a restriction; "non-members cannot reserve"
states the same rule."""

ACTOR_ROLES: Final[dict[str, ActorRole]] = {"C05": RENEWER_ROLE, "C16": RESERVER_ROLE}
"""Every scored ACTOR assertion of the corpus and its role; construction refuses any other."""


# --- the corpus: v3's, carried by reference -----------------------------------------------------


def _upgrade(case_id: str, a: V3Assertion) -> OperativeAssertion:
    """v3's assertion unchanged, except that a scored ACTOR is identified by its role."""
    if a.kind == "ACTOR" and a.status != "REPRESENTED":
        return OperativeAssertion(
            a.kind, a.status, a.stated, a.claimed, a.by, (), ACTOR_ROLES[case_id]
        )
    return OperativeAssertion(a.kind, a.status, a.stated, a.claimed, a.by, a.groups)


def _carried(case: InventoryCase) -> InventoryCase:
    return inventory_case(
        int(case.case_id[1:]),
        case.category,
        *(
            (
                review,
                PropositionInventory(
                    inventory.proposition_id,
                    tuple(_upgrade(case.case_id, a) for a in inventory.assertions),
                    inventory.forbidden,
                ),
            )
            for review, inventory in zip(case.request.propositions, case.inventory, strict=True)
        ),
    )


CASES: Final[tuple[InventoryCase, ...]] = tuple(_carried(case) for case in V3_CASES)


def case_by_id(case_id: str) -> InventoryCase:
    (case,) = [c for c in CASES if c.case_id == case_id]
    return case


# --- the scorer -------------------------------------------------------------------------------


def _identifies(items: tuple[str, ...], finding: V3Finding, statement: str) -> bool:
    role = finding.role if isinstance(finding, RequiredFinding) else None
    if role is not None:
        return identifies_actor(items, role, statement)
    return identifies(items, finding.groups, statement)


def score_completeness_report(
    case: InventoryCase, report: CompletenessReport | None
) -> tuple[str, ...]:
    """Every reason this report fails its case; empty means the attempt passes."""
    if report is None:
        return ("no parseable CompletenessReport",)
    problems = report_findings(case.request, report)
    if problems:
        return problems
    got = {v.proposition_id: v for v in report.verdicts}
    statements = {p.proposition_id: p.statement for p in case.request.propositions}
    failures: list[str] = []
    for expected in case.expected:
        verdict = got[expected.proposition_id]
        if verdict.verdict != expected.verdict:
            failures.append(
                f"{expected.proposition_id}: verdict {verdict.verdict}, sealed {expected.verdict}"
            )
            continue
        if expected.verdict == "COMPLETE":
            continue
        items = region_items(verdict)
        for finding in expected.findings:
            if not _identifies(items, finding, statements[expected.proposition_id]):
                failures.append(
                    f"{expected.proposition_id}: no finding identifies the sealed "
                    f"{finding.name} assertion"
                )
        stated = (*verdict.missing, *verdict.unsupported, *verdict.contradictory)
        for phrase in expected.forbidden:
            if any(mentions(item, phrase) for item in stated):
                failures.append(f"{expected.proposition_id}: forbidden interpretation {phrase!r}")
    return tuple(failures)


def score_completeness_attempt(
    observation: CompletenessObservation, case: InventoryCase, *, candidate: ModelIdentity
) -> tuple[str, ...]:
    return (
        *score_completeness_global_gates(observation, executable(case), candidate=candidate),
        *score_completeness_report(case, observation.report),
    )


def completeness_verdict(attempts: list[dict[str, Any]]) -> str:
    """PASS only when every case's every required run was recorded exactly once and passed."""
    required = {(c.case_id, n) for c in CASES for n in range(1, COMPLETENESS_RUNS_PER_CASE + 1)}
    recorded = [(a["case"], a["attempt"]) for a in attempts]
    complete = len(recorded) == len(required) == COMPLETENESS_CALL_BUDGET
    if not complete or set(recorded) != required:
        return "NOT CERTIFIED"
    return "PASS" if all(a["verdict"] == "PASS" for a in attempts) else "NOT CERTIFIED"


# --- exam identity ----------------------------------------------------------------------------

PRIOR_EXAMS: Final[tuple[PriorExam, ...]] = (
    *V3_PRIOR_EXAMS,
    PriorExam(
        exam_version=V3_EXAM_VERSION,
        exam_sha256=V3_EXAM_SHA256,
        status="LIVE_NOT_CERTIFIED",
        superseded_by=COMPLETENESS_EXAM_VERSION,
        defect="sat live by openai/gpt-6-astra: NOT CERTIFIED 74/75 (evidence 8db3ab8). Its "
        "one failure, C05 attempt 1 ('The permission to renew a loan is granted to a "
        "member.'), was a scorer defect: the enumerated AS_RENEWER role phrases did not admit "
        "a correct nominal / passive actor finding. Frozen unchanged; never re-scored",
    ),
)
"""Exams v1 (prepared), v2 and v3 (sat, not certified) are history, succeeded, never replaced."""


def _group_document(group: MarkerGroup | None) -> dict[str, Any] | None:
    if group is None:
        return None
    return {"name": group.name, "markers": list(group.markers), "synonyms": list(group.synonyms)}


def _role_document(role: ActorRole | None) -> dict[str, Any] | None:
    if role is None:
        return None
    return {
        "actor": _group_document(role.actor),
        "action": _group_document(role.action),
        "action_noun": _group_document(role.action_noun),
        "modal": _group_document(role.modal),
        "licensed": _group_document(role.licensed),
        "grant": _group_document(role.grant),
        "complement": _group_document(role.complement),
    }


def _case_document(case: InventoryCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "request": case.request.model_dump(mode="json"),
        "inventory": [
            {
                "proposition_id": i.proposition_id,
                "assertions": [
                    {
                        "kind": a.kind,
                        "status": a.status,
                        "stated": list(a.stated),
                        "claimed": list(a.claimed),
                        "by": list(a.by),
                        "groups": [_group_document(g) for g in a.groups],
                        "role": _role_document(_role(a)),
                    }
                    for a in i.assertions
                ],
                "forbidden": list(i.forbidden),
            }
            for i in case.inventory
        ],
        "expected": [
            {
                "proposition_id": e.proposition_id,
                "verdict": e.verdict,
                "findings": [
                    {
                        "name": f.name,
                        "groups": [_group_document(g) for g in f.groups],
                        "role": _role_document(f.role if isinstance(f, RequiredFinding) else None),
                    }
                    for f in e.findings
                ],
                "forbidden": list(e.forbidden),
            }
            for e in case.expected
        ],
    }


def _openai_wire() -> tuple[str, str]:
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider

    return (
        schema_sha256(OpenAIModelProvider.wire_schema(CompletenessReport)),
        OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )


def completeness_exam_manifest() -> dict[str, Any]:
    """Everything that decides what the exam asks, how each run executes and what passes."""
    wire, compiler = _openai_wire()
    return {
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "cases": [_case_document(case) for case in CASES],
        "code": code_closure(
            [
                inventory_case,
                inventory_problems,
                derive_verdict,
                expectation,
                identifies_actor,
                _carried,
                held,
                lost,
                lost_actor,
                added,
                clash,
                executable,
                render_request,
                run_completeness_attempt,
                score_completeness_report,
                score_completeness_attempt,
                attempt_evidence,
                completeness_verdict,
                certificate_binds,
                write_completeness_certification,
            ]
        ),
        "acceptance": {
            "rule": COMPLETENESS_ACCEPTANCE_RULE,
            "cases": [case.case_id for case in CASES],
            "runs_per_case": COMPLETENESS_RUNS_PER_CASE,
            "call_budget": COMPLETENESS_CALL_BUDGET,
        },
        "identity": {
            "task": ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION.value,
            "tier": ModelTier.REASONER.value,
            "verifier_policy_id": EXPECTED_VERIFIER_POLICY_ID,
            "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,
            "instruction_sha256": EXPECTED_INSTRUCTION_SHA256,
            "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
            "openai_wire_schema_sha256": wire,
            "openai_wire_schema_compiler": compiler,
            "configuration": {
                "reasoning_effort": CERTIFIED_CONFIGURATION.reasoning_effort,
                "reasoning_mode": CERTIFIED_CONFIGURATION.reasoning_mode,
                "timeout_seconds": CERTIFIED_CONFIGURATION.timeout_seconds,
                "output_guard": CERTIFIED_CONFIGURATION.output_guard,
            },
        },
        "binding_fields": list(BINDING_FIELDS),
        "prior_exams": [
            {
                "exam_version": p.exam_version,
                "exam_sha256": p.exam_sha256,
                "status": p.status,
                "superseded_by": p.superseded_by,
            }
            for p in PRIOR_EXAMS
        ],
    }


def completeness_exam_sha256() -> str:
    return canonical_digest(completeness_exam_manifest())


# --- the certificate --------------------------------------------------------------------------


def write_completeness_certification(
    contestant: Contestant,
    attempts: list[dict[str, Any]],
    *,
    frozen_production_base: str,
    configuration: ProviderConfiguration,
) -> dict[str, Any]:
    """The verdict record, bound to the task, verifier policy, contract and exam it was earned
    on. A separate task certificate: nothing is inherited from any other certification."""
    if contestant.wire_schema is None or contestant.wire_schema_compiler is None:
        raise ValueError("a completeness certification must bind the provider's wire schema")
    if contestant.task is not ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION:
        raise ValueError("the contestant must sit SEMANTIC_COMPLETENESS_VERIFICATION")
    if (contestant.reasoning_effort, contestant.timeout_seconds) != (
        configuration.reasoning_effort,
        configuration.timeout_seconds,
    ):
        raise ValueError("the recorded configuration is not the contestant's")
    passed = sum(1 for a in attempts if a["verdict"] == "PASS")
    payload: dict[str, Any] = {
        "record_format": COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "exam_sha256": completeness_exam_sha256(),
        "candidate": contestant.label,
        "provider": contestant.identity.provider,
        "model": contestant.identity.model,
        "task": contestant.task.value,
        "tier": ModelTier.REASONER.value,
        "verifier_policy_id": COMPLETENESS_POLICY_ID,
        "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,
        "instruction_sha256": hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest(),
        "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
        "wire_schema_sha256": schema_sha256(contestant.wire_schema(CompletenessReport)),
        "wire_schema_compiler": contestant.wire_schema_compiler,
        "reasoning_effort": configuration.reasoning_effort,
        "reasoning_mode": configuration.reasoning_mode,
        "timeout_seconds": configuration.timeout_seconds,
        "output_guard": configuration.output_guard,
        "request_constraints": ModelExecutionConstraints().model_dump(mode="json"),
        "frozen_production_base": frozen_production_base,
        "acceptance_rule": COMPLETENESS_ACCEPTANCE_RULE,
        "cases": [case.case_id for case in CASES],
        "runs_per_case": COMPLETENESS_RUNS_PER_CASE,
        "call_budget": COMPLETENESS_CALL_BUDGET,
        "required_attempts": COMPLETENESS_CALL_BUDGET,
        "recorded_attempts": len(attempts),
        "passed_attempts": passed,
        "verdict": completeness_verdict(attempts),
        "attempts": attempts,
    }
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    (contestant.evidence_dir / "certification.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    return payload


def current_completeness_identity(identity: ModelIdentity) -> dict[str, Any] | None:
    """The identity a certificate must bind today, or ``None`` for a provider with no adapter."""
    from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider
    from foundry.adapters.model_runtime.xai import XAIModelProvider

    providers: dict[str, Any] = {
        "xai": XAIModelProvider,
        "openai": OpenAIModelProvider,
        "anthropic": AnthropicModelProvider,
    }
    provider = providers.get(identity.provider)
    if provider is None:
        return None
    return {
        "identity": identity,
        "task": ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        "verifier_policy_id": COMPLETENESS_POLICY_ID,
        "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,
        "instruction_sha256": hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest(),
        "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
        "wire_schema_sha256": schema_sha256(provider.wire_schema(CompletenessReport)),
        "wire_schema_compiler": provider.WIRE_SCHEMA_COMPILER,
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "exam_sha256": completeness_exam_sha256(),
        "reasoning_effort": CERTIFIED_CONFIGURATION.reasoning_effort,
        "reasoning_mode": CERTIFIED_CONFIGURATION.reasoning_mode,
        "timeout_seconds": CERTIFIED_CONFIGURATION.timeout_seconds,
        "output_guard": CERTIFIED_CONFIGURATION.output_guard,
        "runs_per_case": COMPLETENESS_RUNS_PER_CASE,
        "call_budget": COMPLETENESS_CALL_BUDGET,
    }


def completeness_certificate_standing(record: dict[str, Any]) -> str:
    """``NOT_CERTIFIED`` (never PASS), ``CURRENT`` (binds every exam-v4 field), ``SUPERSEDED``
    (a PASS on a prior exam) or ``NOT_BINDING`` (any other PASS, including every record of
    another task or format)."""
    if record.get("verdict") != "PASS":
        return "NOT_CERTIFIED"
    if record.get("record_format") != COMPLETENESS_CERTIFICATION_RECORD_FORMAT:
        return "NOT_BINDING"
    current = current_completeness_identity(
        ModelIdentity(provider=str(record.get("provider")), model=str(record.get("model")))
    )
    if current is not None and certificate_binds(record, **current):
        return "CURRENT"
    prior = {(p.exam_version, p.exam_sha256) for p in PRIOR_EXAMS}
    if (record.get("exam_version"), record.get("exam_sha256")) in prior:
        return "SUPERSEDED"
    return "NOT_BINDING"


# --- evidence integrity -----------------------------------------------------------------------


def completeness_evidence_problems(record: dict[str, Any]) -> tuple[str, ...]:
    """Re-derive a record from its own attempts. Any disagreement is a problem, never fixed."""
    if record.get("record_format") != COMPLETENESS_CERTIFICATION_RECORD_FORMAT:
        return ("not a semantic completeness certification record",)
    if record.get("exam_sha256") != completeness_exam_sha256():
        return ("earned on a different exam; it cannot be re-scored against this one",)
    attempts: list[dict[str, Any]] = list(record.get("attempts") or [])
    problems: list[str] = []
    passed = sum(1 for a in attempts if a.get("verdict") == "PASS")
    if record.get("recorded_attempts") != len(attempts):
        problems.append("recorded_attempts disagrees with the attempts")
    if record.get("passed_attempts") != passed:
        problems.append("passed_attempts disagrees with the attempts")
    if record.get("required_attempts") != COMPLETENESS_CALL_BUDGET:
        problems.append("required_attempts is not the sealed budget")
    if record.get("verdict") != completeness_verdict(attempts):
        problems.append("the verdict does not follow from the attempts")
    cases = {case.case_id: case for case in CASES}
    for a in attempts:
        where = f"{a.get('case')}/{a.get('attempt')}"
        case = cases.get(str(a.get("case")))
        if case is None:
            problems.append(f"{where}: not an exam case")
            continue
        answered = a.get("request_json") is not None or a.get("verdict") == "PASS"
        if answered and a.get("request_json") != render_request(case.request):
            problems.append(f"{where}: the recorded request is not the sealed request")
        if a.get("verdict") != "PASS":
            continue
        if (a.get("provider"), a.get("model")) != (record.get("provider"), record.get("model")):
            problems.append(f"{where}: answered by another model")
        if a.get("instruction_sha256") != EXPECTED_INSTRUCTION_SHA256:
            problems.append(f"{where}: not the frozen instruction")
        if a.get("parsed_report") is None:
            problems.append(f"{where}: a PASS without a report")
            continue
        report = CompletenessReport.model_validate(a["parsed_report"])
        if CompletenessReport.model_validate(a.get("raw_output")) != report:
            problems.append(f"{where}: the parsed report is not the raw response")
        if score_completeness_report(case, report):
            problems.append(f"{where}: the recorded report does not pass its case")
    return tuple(problems)


# --- the seal ---------------------------------------------------------------------------------


def write_completeness_seal(path: Path, *, harness_sha: str) -> None:
    manifest = completeness_exam_manifest()
    document = {
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "exam_sha256": canonical_digest(manifest),
        "harness_sha": harness_sha,
        "manifest": manifest,
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def completeness_seal_problems(path: Path = COMPLETENESS_SEAL_PATH) -> tuple[str, ...]:
    """Nothing may be called until the committed seal is exactly the current exam."""
    if not path.exists():
        return (f"exam v4 is not sealed: {path} is absent",)
    document = json.loads(path.read_text())
    problems: list[str] = []
    if document.get("manifest") != completeness_exam_manifest():
        problems.append("the sealed manifest is not the current exam")
    if document.get("exam_sha256") != canonical_digest(document.get("manifest")):
        problems.append("the sealed hash is not the digest of the sealed manifest")
    if document.get("exam_sha256") != completeness_exam_sha256():
        problems.append("the sealed hash is not the current exam hash")
    if not re.fullmatch(r"[0-9a-f]{40}", str(document.get("harness_sha"))):
        problems.append("the seal names no harness commit")
    return tuple(problems)
