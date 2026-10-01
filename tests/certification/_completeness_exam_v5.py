"""Certification exam v5 for SEMANTIC_COMPLETENESS_VERIFICATION (IE2 Call 3), test-only.

**Why v5 exists.** Exam v4 (``_completeness_exam_v4``, sat live once by ``openai/gpt-6-astra``:
NOT CERTIFIED 72/75, frozen) returned no wrong verdict, no protocol and no infrastructure
failure; its three failures were correct answers its deterministic scorer rejected. v5 is a
certification-scorer correction only: the verifier policy ``ie2-semantic-completeness-v1``, its
instruction, schema and runtime are unchanged, and every model-visible request, inventory and
marker group is v4's, carried by reference.

**Correction 1 -- the appositive role noun.** v4's ACTOR law (the role triple ACTOR -> ROLE ->
GOVERNED ACTION, bound in one item, never co-occurrence) stands. Its licence construction now
admits one appositive role noun after the copula: ``{actor} is/are [only] [the] {role noun}
{licence} to {action}`` -- "a member is the actor permitted to renew the loan". The noun names
the role holder; the binding, polarity, clause-break and bystander rules are unchanged.

**Correction 2 -- the echo law.** v2's rule refused any finding item that contained the whole
proposition, even one that went on to name the defect. v5 discounts the echoed proposition:
each item is split at every occurrence of the proposition's text, and only the remaining
segments may identify the sealed region, each segment on its own (the text either side of an
echo is never joined). A pure echo leaves nothing and identifies nothing. A contradiction must
also name the claim's side of the conflict (a sealed claim-side group), so restating the
proposition's own value never identifies a contradiction.

**The pre-seal replay gate.** Every recorded Astra finding of exams v2, v3 and v4 is replayed
through the v5 scorer. Each must keep the result its own exam's scorer gave it, except the four
demonstrated scorer false negatives v5 exists to correct; any other change refuses the seal.
The replay is diagnostic: no historical standing changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NamedTuple

import tests.certification._completeness_exam as v2
import tests.certification._completeness_exam_v3 as v3
import tests.certification._completeness_exam_v4 as v4
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
from tests.certification._certification_run import EVIDENCE_ROOT, Contestant
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
    HISTORICAL_EXAM_V2_NAMESPACE,
    HISTORICAL_V2_RECORD_SHA256,
    DerivedExpectation,
    InventoryCase,
    PropositionInventory,
    Status,
    derive_verdict,
    executable,
    run_completeness_attempt,
)
from tests.certification._completeness_exam_v4 import CASES as V4_CASES
from tests.certification._completeness_exam_v4 import (
    COMPLETENESS_EXAM_VERSION as V4_EXAM_VERSION,
)
from tests.certification._completeness_exam_v4 import (
    COPULAS,
    DETERMINERS,
    HISTORICAL_EXAM_V3_NAMESPACE,
    HISTORICAL_V3_RECORD_SHA256,
    RENEWER_ROLE,
    RESERVER_ROLE,
    ActorRole,
    _actor_ends,
    _after_modifier,
    _claim_text,
    _complement_denied,
    _g,
    _licensed_to_act,
    _role_then_actor,
    _skip,
)
from tests.certification._completeness_exam_v4 import (
    EXPECTED_COMPLETENESS_EXAM_SHA256 as V4_EXAM_SHA256,
)
from tests.certification._completeness_exam_v4 import PRIOR_EXAMS as V4_PRIOR_EXAMS
from tests.certification._completeness_exam_v4 import OperativeAssertion as V4Assertion
from tests.certification._completeness_exam_v4 import RequiredFinding as V4Finding
from tests.certification._completeness_exam_v4 import inventory_problems as v4_inventory_problems
from tests.certification._exam_identity import canonical_digest, code_closure
from tests.certification._schema_identity import schema_sha256

__all__ = ["RENEWER_ROLE", "RESERVER_ROLE"]

PROJECT: Final = "PROJ-A"

COMPLETENESS_EXAM_VERSION: Final = "ie2-semantic-completeness-exam-v5"
COMPLETENESS_EVIDENCE_NAMESPACE: Final = "semantic_completeness_verification_exam_v5"
"""Where an exam-v5 certification's evidence is written. Exams v2-v4's namespaces are history."""
HISTORICAL_EXAM_V4_NAMESPACE: Final = "semantic_completeness_verification_exam_v4"
"""Exam v4 under ``ie2-semantic-completeness-v1``: Astra NOT CERTIFIED 72/75. Immutable."""
HISTORICAL_V4_RECORD_SHA256: Final = (
    "e1285e6d2ae6add059d20ed9386721b807d90746ccc422aae6f5d4624a641e06"
)
"""SHA-256 of exam v4's live record exactly as committed at d02646f; never rewritten."""
COMPLETENESS_SEAL_PATH: Final = Path(
    "tests/certification/exam_manifests/ie2-semantic-completeness-exam-v5.seal.json"
)
COMPLETENESS_CALL_BUDGET: Final = 75
"""``len(CASES) * COMPLETENESS_RUNS_PER_CASE``, pasted and sealed before any live call."""
EXPECTED_COMPLETENESS_EXAM_SHA256: Final = (
    "88b69c45dd7f508c4068f753b3942febe2d39f4548fc1e30995dfbb8cd9ed99a"
)
"""``completeness_exam_sha256()``, pasted, never computed at import."""


# --- correction 1: the appositive role noun ---------------------------------------------------

ROLE_NOUNS: Final = ("actor", "actors", "one", "ones", "person", "people", "party", "parties")
"""An appositive naming the role holder: {actor} is the actor / the one / the people ..."""


def _appositive(tokens: list[str], k: int) -> list[int]:
    """Where the licence may start after a copula: at once, or past [the] {role noun}."""
    d = _skip(tokens, k, DETERMINERS)
    if d < len(tokens) and tokens[d] in ROLE_NOUNS:
        return [k, d + 1]
    return [k]


def _actor_then_role(tokens: list[str], role: ActorRole) -> bool:
    """{actor} [modifier] [only] {modal} {action}  |
    {actor} is [only] [[the] {role noun}] {licensed} to {action}"""
    for i in range(len(tokens)):
        for e in _actor_ends(tokens, i, role.actor):
            for j in _after_modifier(tokens, e):
                j = _skip(tokens, j, ("only",))
                if any(_g(tokens, m, role.action) for m in _g(tokens, j, role.modal)):
                    return True
                if j < len(tokens) and tokens[j] in COPULAS:
                    k = _skip(tokens, j + 1, ("only",))
                    if any(_licensed_to_act(tokens, a, role) for a in _appositive(tokens, k)):
                        return True
    return False


# --- correction 2: the echo law ----------------------------------------------------------------


def echo_segments(item: str, statement: str) -> tuple[str, ...]:
    """``item`` with every occurrence of the proposition removed, as the separate segments
    either side of it. A segment never spans an echo, so no phrase forms across one."""
    tokens, echo = normalise(item).split(), normalise(statement).split()
    segments: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        if echo and tokens[i : i + len(echo)] == echo:
            segments.append([])
            i += len(echo)
        else:
            segments[-1].append(tokens[i])
            i += 1
    return tuple(" ".join(s) for s in segments if s)


def _segments(items: tuple[str, ...], statement: str) -> tuple[str, ...]:
    return tuple(s for item in items for s in echo_segments(item, statement))


def identifies_actor(items: tuple[str, ...], role: ActorRole, statement: str) -> bool:
    """v4's role triple, bound in one non-echo segment, now admitting an appositive role noun."""
    groups = (role.actor, role.action, role.action_noun, role.modal, role.licensed)
    for segment in _segments(items, statement):
        if _restates(segment, statement) or _is_stuffed(segment, groups):
            continue
        tokens = segment.split()
        if (
            _actor_then_role(tokens, role)
            or _role_then_actor(tokens, role)
            or _complement_denied(tokens, role)
        ):
            return True
    return False


def identifies_region(
    items: tuple[str, ...], groups: tuple[MarkerGroup, ...], statement: str
) -> bool:
    """v2's matcher (every group, no stuffing) over the non-echo segments only."""
    return identifies(_segments(items, statement), groups, statement)


# --- the inventory: v4's, with the claim side of a contradiction ---------------------------------


@dataclass(frozen=True)
class OperativeAssertion(V4Assertion):
    """v4's assertion; a CONTRADICTED one also seals the claim's side of the conflict."""

    claim_side: MarkerGroup | None = None


@dataclass(frozen=True)
class RequiredFinding(V4Finding):
    claim_side: MarkerGroup | None = None


CLAIM_SIDES: Final[dict[tuple[str, str], MarkerGroup]] = {
    ("C11", "p1"): MarkerGroup("the claim's cap", ("15", "fifteen")),
    ("C17", "p2"): MarkerGroup(
        "the claim's loan length", ("21 days", "21", "three weeks", "3 weeks")
    ),
    ("C23", "p1"): MarkerGroup(
        "the claim's branch",
        ("issuing branch", "issuing", "issued", "same branch", "branch that issued"),
        ("original branch", "home branch", "lending branch", "one branch", "that branch"),
    ),
}
"""For every contradiction: what names the claim's side, never the proposition's."""


def _claim_side(a: Any) -> MarkerGroup | None:
    return a.claim_side if isinstance(a, OperativeAssertion) else None


def inventory_problems(
    review: PropositionReview, inventory: PropositionInventory
) -> tuple[str, ...]:
    """v4's coherence law, plus: a CONTRADICTED assertion (and only one) seals a claim side,
    which the contradicting claims state and the proposition never does."""
    problems = list(v4_inventory_problems(review, inventory))
    where = review.proposition_id
    for a in inventory.assertions:
        label = f"{where} {a.kind} {a.status}"
        side = _claim_side(a)
        if a.status == "CONTRADICTED" and side is None:
            problems.append(f"{label}: a contradiction seals the claim's side")
        if a.status != "CONTRADICTED" and side is not None:
            problems.append(f"{label}: only a contradiction seals a claim side")
        if side is None:
            continue
        phrases = (*side.markers, *side.synonyms)
        if not any(mentions(_claim_text(review, a.by), p) for p in phrases):
            problems.append(f"{label}: the claim side is not in its claims")
        for phrase in phrases:
            if mentions(review.statement, phrase):
                problems.append(f"{label}: claim side {phrase!r} is in the proposition")
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
        RequiredFinding(
            f"{a.kind} {' / '.join(a.stated or a.claimed)}",
            a.groups,
            a.role if isinstance(a, V4Assertion) else None,
            _claim_side(a),
        )
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


def _upgrade(case_id: str, pid: str, a: Any) -> OperativeAssertion:
    side = CLAIM_SIDES[(case_id, pid)] if a.status == "CONTRADICTED" else None
    return OperativeAssertion(a.kind, a.status, a.stated, a.claimed, a.by, a.groups, a.role, side)


def _carried(case: InventoryCase) -> InventoryCase:
    """v4's case: the same reviews, the same assertions and groups, by reference."""
    return inventory_case(
        int(case.case_id[1:]),
        case.category,
        *(
            (
                review,
                PropositionInventory(
                    inventory.proposition_id,
                    tuple(
                        _upgrade(case.case_id, inventory.proposition_id, a)
                        for a in inventory.assertions
                    ),
                    inventory.forbidden,
                ),
            )
            for review, inventory in zip(case.request.propositions, case.inventory, strict=True)
        ),
    )


CASES: Final[tuple[InventoryCase, ...]] = tuple(_carried(case) for case in V4_CASES)


def case_by_id(case_id: str) -> InventoryCase:
    (case,) = [c for c in CASES if c.case_id == case_id]
    return case


# --- the scorer -------------------------------------------------------------------------------


def _identifies(items: tuple[str, ...], finding: Any, statement: str) -> bool:
    role = finding.role if isinstance(finding, V4Finding) else None
    if role is not None:
        return identifies_actor(items, role, statement)
    side = finding.claim_side if isinstance(finding, RequiredFinding) else None
    groups = (*finding.groups, side) if side is not None else finding.groups
    return identifies_region(items, groups, statement)


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


# --- the pre-seal historical replay -------------------------------------------------------------


class HistoricalRecord(NamedTuple):
    exam: str
    namespace: str
    sha256: str


HISTORICAL_RECORDS: Final[tuple[HistoricalRecord, ...]] = (
    HistoricalRecord("v2", HISTORICAL_EXAM_V2_NAMESPACE, HISTORICAL_V2_RECORD_SHA256),
    HistoricalRecord("v3", HISTORICAL_EXAM_V3_NAMESPACE, HISTORICAL_V3_RECORD_SHA256),
    HistoricalRecord("v4", HISTORICAL_EXAM_V4_NAMESPACE, HISTORICAL_V4_RECORD_SHA256),
)
NOT_REPLAYABLE: Final = frozenset(("v2", c) for c in ("C02", "C04", "C10", "C22", "C24"))
"""Exam-v2 payloads exam v3 replaced: no v5 proposition or inventory corresponds to them."""
EXPECTED_REPLAY_CHANGES: Final = frozenset(
    {
        ("v3", "C05", 1, "p1"),
        ("v4", "C05", 2, "p1"),
        ("v4", "C05", 3, "p1"),
        ("v4", "C17", 1, "p2"),
    }
)
"""The demonstrated scorer false negatives v5 corrects, FAIL -> PASS. Nothing else may move."""


class ReplayRow(NamedTuple):
    exam: str
    case: str
    attempt: int
    proposition_id: str
    recorded_verdict: str
    returned_verdict: str
    findings: tuple[str, ...]
    historical: str
    v5: str
    same_request: bool
    reason: str


def _own_scorer(exam: str, case_id: str, report: CompletenessReport | None) -> tuple[str, ...]:
    if exam == "v2":
        return v2.score_completeness_report(v2.case_by_id(case_id), report)
    if exam == "v3":
        return v3.score_completeness_report(v3.case_by_id(case_id), report)
    return v4.score_completeness_report(v4.case_by_id(case_id), report)


def _about(failures: tuple[str, ...], pid: str) -> list[str]:
    """The failures of one proposition; a structural failure concerns every proposition."""
    return [f for f in failures if f.startswith(f"{pid}:") or not re.match(r"p\d+:", f)]


def historical_replay() -> tuple[ReplayRow, ...]:
    """Every replayable recorded attempt of exams v2-v4, per proposition: the result its own
    exam's scorer gives it and the result the v5 scorer gives it. Reads; never writes."""
    rows: list[ReplayRow] = []
    for record in HISTORICAL_RECORDS:
        path = EVIDENCE_ROOT / f"openai/gpt-6-astra/{record.namespace}/certification.json"
        for a in json.loads(path.read_text())["attempts"]:
            if (record.exam, a["case"]) in NOT_REPLAYABLE:
                continue
            case = case_by_id(a["case"])
            parsed = a.get("parsed_report")
            report = CompletenessReport.model_validate(parsed) if parsed else None
            own = _own_scorer(record.exam, a["case"], report)
            new = score_completeness_report(case, report)
            returned = {v.proposition_id: v for v in report.verdicts} if report else {}
            for p in case.request.propositions:
                pid = p.proposition_id
                then, now = _about(own, pid), _about(new, pid)
                verdict = returned.get(pid)
                rows.append(
                    ReplayRow(
                        exam=record.exam,
                        case=a["case"],
                        attempt=a["attempt"],
                        proposition_id=pid,
                        recorded_verdict=a["verdict"],
                        returned_verdict=verdict.verdict if verdict else "NONE",
                        findings=(
                            (*verdict.missing, *verdict.unsupported, *verdict.contradictory)
                            if verdict
                            else ()
                        ),
                        historical="FAIL" if then else "PASS",
                        v5="FAIL" if now else "PASS",
                        same_request=a.get("request_json") == render_request(case.request),
                        reason="; ".join(then + now),
                    )
                )
    return tuple(rows)


def replay_problems(rows: tuple[ReplayRow, ...]) -> tuple[str, ...]:
    """Every way the replay departs from the sealed expectation; empty means the gate passes."""
    problems: list[str] = []
    seen: set[tuple[str, str, int, str]] = set()
    for r in rows:
        key = (r.exam, r.case, r.attempt, r.proposition_id)
        seen.add(key)
        where = f"{r.exam} {r.case}/{r.attempt} {r.proposition_id}"
        if not r.same_request:
            problems.append(f"{where}: the recorded request is not the v5 request")
        if key in EXPECTED_REPLAY_CHANGES:
            if (r.historical, r.v5) != ("FAIL", "PASS"):
                problems.append(f"{where}: expected FAIL -> PASS, got {r.historical} -> {r.v5}")
        elif r.historical != r.v5:
            problems.append(f"{where}: unexpected {r.historical} -> {r.v5} ({r.reason})")
    for key in sorted(EXPECTED_REPLAY_CHANGES - seen):
        problems.append(f"{key}: an expected change was never replayed")
    return tuple(problems)


# --- exam identity ----------------------------------------------------------------------------

PRIOR_EXAMS: Final[tuple[PriorExam, ...]] = (
    *V4_PRIOR_EXAMS,
    PriorExam(
        exam_version=V4_EXAM_VERSION,
        exam_sha256=V4_EXAM_SHA256,
        status="LIVE_NOT_CERTIFIED",
        superseded_by=COMPLETENESS_EXAM_VERSION,
        defect="sat live by openai/gpt-6-astra: NOT CERTIFIED 72/75 (evidence d02646f), with no "
        "wrong verdict. Its three failures were scorer defects: C05 attempts 2-3 ('the member is "
        "the actor permitted to renew the loan') -- no appositive role noun admitted; C17 "
        "attempt 1 -- the echo rule refused an item quoting the proposition before naming the "
        "conflicting 21 days. Frozen unchanged; never re-scored",
    ),
)
"""Exams v1 (prepared), v2, v3 and v4 (sat, not certified) are history: succeeded, never
replaced."""


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
        "request_sha256": hashlib.sha256(render_request(case.request).encode()).hexdigest(),
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
                        "role": _role_document(a.role if isinstance(a, V4Assertion) else None),
                        "claim_side": _group_document(_claim_side(a)),
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
                        "role": _role_document(f.role if isinstance(f, V4Finding) else None),
                        "claim_side": _group_document(
                            f.claim_side if isinstance(f, RequiredFinding) else None
                        ),
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
                identifies_region,
                echo_segments,
                _carried,
                executable,
                render_request,
                run_completeness_attempt,
                score_completeness_report,
                score_completeness_attempt,
                attempt_evidence,
                completeness_verdict,
                certificate_binds,
                write_completeness_certification,
                historical_replay,
                replay_problems,
                write_completeness_seal,
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
        "historical_replay": {
            "records": [list(r) for r in HISTORICAL_RECORDS],
            "not_replayable": sorted(list(k) for k in NOT_REPLAYABLE),
            "expected_changes": sorted(list(k) for k in EXPECTED_REPLAY_CHANGES),
        },
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
    """``NOT_CERTIFIED`` (never PASS), ``CURRENT`` (binds every exam-v5 field), ``SUPERSEDED``
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
    """Refuses to seal while the historical replay gate fails."""
    problems = replay_problems(historical_replay())
    if problems:
        raise RuntimeError(f"historical replay gate failed: {'; '.join(problems)}")
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
    """Nothing may be called until the committed seal is exactly the current exam and the
    historical replay gate passes."""
    if not path.exists():
        return (f"exam v5 is not sealed: {path} is absent",)
    document = json.loads(path.read_text())
    problems: list[str] = list(replay_problems(historical_replay()))
    if document.get("manifest") != completeness_exam_manifest():
        problems.append("the sealed manifest is not the current exam")
    if document.get("exam_sha256") != canonical_digest(document.get("manifest")):
        problems.append("the sealed hash is not the digest of the sealed manifest")
    if document.get("exam_sha256") != completeness_exam_sha256():
        problems.append("the sealed hash is not the current exam hash")
    if not re.fullmatch(r"[0-9a-f]{40}", str(document.get("harness_sha"))):
        problems.append("the seal names no harness commit")
    return tuple(problems)
