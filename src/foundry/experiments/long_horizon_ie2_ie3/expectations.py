"""The hidden answer key of the IE2 + IE3 long-horizon experiment (design §7-§11, §14).

Sealed as ``expectations.json`` before any live call; never edited afterwards; never
model-visible (the request path never imports it; a gate enforces that). Everything here is
derived from the historical 9P3 answer key (``long_horizon_bounded.expectations``: the
baseline meanings, the per-version meaning changes and the checkpoint classes), never from
any historical model output. It holds:

* the **proposition inventory**: per locus, REQUIRED propositions (the normative rules the
  historical key names) and OPTIONAL propositions (descriptive or rationale statements a
  model may state as claims or set aside, neither being an error);
* the **source-coverage map**: every sentence of each of the 38 distinct section texts,
  accounted for by proposition ids or as an example;
* the **per-turn IE2 expectations**: transition class, target locus, claim-count range per
  locus, whether a governed supersession is required, the current, no-longer-current and
  optional-compatible propositions of every locus after the turn;
* the **per-turn IE3 expectations**: the graph behaviour class the turn requires, the lawful
  node kinds and the root-lifecycle laws (evaluated mechanically by ``evaluation``);
* the **independent adjudication questions**, each naming its layer, turn and timepoint.
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_formation.source_coverage import (
    SentenceAccount,
    coverage_findings,
    source_sentences,
)
from foundry.experiments.long_horizon_bounded import timeline
from foundry.experiments.long_horizon_bounded.expectations import CHECKPOINTS, TransitionClass
from foundry.experiments.long_horizon_bounded.timeline import LOCI, Locus
from foundry.experiments.long_horizon_ie2_ie3.protocol import EXPERIMENT_VERSION

__all__ = [
    "ADJUDICATION_QUESTIONS",
    "CORRECTION_TURNS",
    "LAWFUL_NODE_KINDS",
    "PROPOSITIONS",
    "SOURCE_COVERAGE",
    "TEXT_KEY",
    "TURNS",
    "AdjudicationQuestion",
    "Proposition",
    "TurnExpectation",
    "adjudication_questions_sha256",
    "expectations_document",
    "expectations_sha256",
    "source_coverage_findings",
]

Tier = Literal["REQUIRED", "OPTIONAL"]
Behaviour = Literal["GRAPH_FORMATION", "NO_GRAPH_CHANGE", "REPLACE_STALE", "EXTEND"]


class Proposition(FrozenModel):
    id: str
    locus: Locus
    tier: Tier
    statement: str


def _r(pid: str, statement: str) -> Proposition:
    return Proposition(id=pid, locus=pid[0], tier="REQUIRED", statement=statement)  # type: ignore[arg-type]


def _o(pid: str, statement: str) -> Proposition:
    return Proposition(id=pid, locus=pid[0], tier="OPTIONAL", statement=statement)  # type: ignore[arg-type]


PROPOSITIONS: Final[tuple[Proposition, ...]] = (
    _r("A-1", "a job is executed at most three times in total"),
    _r("A-2", "the first execution counts as one of the three"),
    _r("A-3", "after the third execution ends without success no further execution of the job "
       "may start"),
    _r("A-4", "each job begins with one initial execution"),
    _r("A-5", "if the initial execution does not succeed, up to three retry executions of the "
       "job may be performed (at most four executions in total)"),
    _r("A-6", "after the third retry ends without success no further execution of the job may "
       "start"),
    _o("A-o1", "every job is executed by being delivered to a worker"),
    _o("A-o2", "an execution (attempt) is one delivery of the job to a worker that ends in "
       "success, failure or timeout"),
    _r("B-1", "before every retry the worker waits exactly five seconds, measured from the end "
       "of the failed attempt"),
    _r("B-2", "the wait is not shortened or lengthened based on the attempt number"),
    _r("B-3", "before the first retry the worker waits two seconds, measured from the end of the "
       "failed execution"),
    _r("B-4", "before each later retry the worker waits twice as long as before the previous "
       "retry"),
    _r("B-5", "the wait before any retry never exceeds thirty seconds"),
    _o("B-o1", "after a failed execution Orion waits before delivering the job again"),
    _o("B-o2", "the wait gives transient downstream faults time to clear"),
    _o("B-o3", "a growing pause made recovery times unpredictable for tenants"),
    _r("C-1", "each execution attempt may run for at most thirty seconds, after which it times "
       "out and is stopped"),
    _r("C-2", "an attempt that reaches the time limit is recorded as a failed attempt"),
    _o("C-o1", "workers can hang or stall"),
    _r("D-1", "while a job is active, a further delivery carrying the same job id is ignored"),
    _r("D-2", "ignoring a duplicate delivery does not change the state of the active job"),
    _r("D-3", "a job is not executed twice because of redelivery"),
    _r("D-4", "while a job is active, a further delivery is ignored only when it carries both "
       "the same job id and the same idempotency key as the active job"),
    _r("D-5", "a further delivery with the same job id but a different idempotency key is "
       "rejected as conflicting input and does not change the state of the active job"),
    _o("D-o1", "producers may deliver the same job more than once"),
    _o("D-o2", "a producer may reuse a job id for different payloads, so two deliveries that "
       "share a job id are not necessarily the same request"),
    _r("E-1", "each idempotency key is retained for twenty-four hours after it is first seen"),
    _r("E-2", "after the retention period the key may be forgotten and a later delivery with the "
       "same key is treated as new"),
    _o("E-o1", "a delivery may carry an idempotency key chosen by the producer"),
    _r("F-1", "a worker lease lasts sixty seconds from the moment the job is delivered to the "
       "worker"),
    _r("F-2", "when the lease expires without renewal or release, the job becomes available to "
       "other workers"),
    _r("F-3", "a worker lease lasts ninety seconds from the moment the job is delivered to the "
       "worker"),
    _o("F-o1", "a worker that receives a job holds a lease on it"),
    _o("F-o2", "the lease tells Orion the job is in hand and keeps other workers from taking it"),
    _o("F-o3", "sixty seconds was too short for workers that perform a cold start before their "
       "first renewal"),
    _r("G-1", "a worker may renew its lease every thirty seconds while work on the job is "
       "progressing"),
    _r("G-2", "a renewal extends the lease by the full lease duration from the moment of "
       "renewal"),
    _r("G-3", "a worker must renew its lease when twenty seconds of lease life remain, provided "
       "work on the job is progressing"),
    _r("G-4", "a worker never renews the same lease more often than once every fifteen seconds"),
    _o("G-o1", "a worker that is still progressing renews its lease so the job is not "
       "reassigned"),
    _r("H-1", "a producer or operator may cancel a job"),
    _r("H-2", "after a job is cancelled no future execution attempt of it may start"),
    _r("H-3", "cancellation does not interrupt an execution attempt that is already running; "
       "that attempt runs to its own completion, failure or timeout"),
    _r("H-4", "a cancellation received for an already-cancelled job leaves it cancelled and "
       "changes nothing else about its state"),
    _r("H-5", "a repeated cancellation (one received for an already-cancelled job) is "
       "acknowledged"),
    _r("I-1", "after the final unsuccessful execution attempt the job is automatically moved to "
       "the dead-letter queue"),
    _r("I-2", "a job in the dead-letter queue is not executed again unless explicitly "
       "resubmitted"),
    _r("I-3", "after the final unsuccessful execution attempt the job is left in the failed "
       "state"),
    _r("I-4", "a job in the failed state requires operator review before any further action is "
       "taken on it"),
    _r("I-5", "Orion does not automatically move a job to the dead-letter queue"),
    _o("I-o1", "when a job has used all its attempts without success Orion must decide what "
       "happens to it"),
    _o("I-o2", "automatic dead-lettering hid genuine faults from tenants"),
    _r("J-1", "an operator escalation is raised when three dead-letter events occur for the same "
       "tenant within one hour"),
    _r("J-2", "the one-hour window is measured from the first of the three events"),
    _r("J-3", "an operator escalation is raised when five dead-letter events occur for the same "
       "tenant within any rolling thirty-minute window"),
    _r("J-4", "the window is rolling: at each new dead-letter event the events for that tenant "
       "in the preceding thirty minutes, including the new one, are counted"),
    _o("J-o1", "many dead-letter events for one tenant in a short time usually indicate a "
       "systemic fault"),
    _o("J-o2", "the threshold is tuned so that a brief burst does not page an operator while a "
       "sustained fault does"),
    _r("K-1", "first-in-first-out execution order is guaranteed only among jobs in the same queue "
       "partition"),
    _r("K-2", "no ordering guarantee is made between jobs in different partitions"),
    _o("K-o1", "some producers depend on jobs executing in the order they were enqueued"),
    _o("K-o2", "producers that need strict sequencing place related jobs in one partition; others "
       "spread work across partitions for throughput"),
    _o("K-o3", "the ordering promise is limited so that a slow job in one partition never stalls "
       "the others"),
    _r("L-1", "audit events are retained for thirty days after they are recorded"),
    _r("L-2", "after thirty days an audit event may be deleted"),
    _o("L-o1", "every state change of a job is recorded as an audit event"),
    _o("L-o2", "audit events support incident investigation and tenant reporting"),
    _o("L-o3", "the retention period gives investigations a predictable window"),
)  # fmt: skip

_BY_ID: Final = {p.id: p for p in PROPOSITIONS}

# ------------------------------------------------------------------ source coverage


def _text_keys() -> dict[tuple[int, Locus], str]:
    first: dict[str, str] = {}
    keys: dict[tuple[int, Locus], str] = {}
    for t in range(1, timeline.VERSION_COUNT + 1):
        for locus in LOCI:
            text = timeline.SECTION_TEXT[(t, locus)]
            keys[(t, locus)] = first.setdefault(text, f"{locus}-T{t}")
    return keys


TEXT_KEY: Final[dict[tuple[int, Locus], str]] = _text_keys()
_TEXTS: Final[dict[str, str]] = {
    key: timeline.SECTION_TEXT[(t, locus)] for (t, locus), key in TEXT_KEY.items()
}
_EX: Final = "illustrative example that restates listed rules and adds none"
Entry = tuple[str, ...] | str


def _accounts(key: str, *entries: Entry) -> tuple[SentenceAccount, ...]:
    return tuple(
        SentenceAccount(sentence=s, propositions=e)
        if isinstance(e, tuple)
        else SentenceAccount(sentence=s, non_operative_reason=e)
        for s, e in zip(source_sentences(_TEXTS[key]), entries, strict=True)
    )


SOURCE_COVERAGE: Final[dict[str, tuple[SentenceAccount, ...]]] = {
    "A-T1": _accounts("A-T1", ("A-o1",), ("A-o2",), ("A-1",), ("A-1",), ("A-2",), ("A-3",), _EX,
                      _EX),
    "A-T3": _accounts("A-T3", ("A-o1",), ("A-o2",), ("A-5",), ("A-4",), ("A-5",), ("A-6",), _EX,
                      _EX, _EX),
    "A-T4": _accounts("A-T4", ("A-o1",), ("A-o2",), ("A-5",), ("A-4",), ("A-5",), ("A-6",), _EX,
                      _EX),
    "A-T6": _accounts("A-T6", ("A-o1",), ("A-o2",), ("A-5",), ("A-4", "A-5"), ("A-6",), _EX, _EX),
    "B-T1": _accounts("B-T1", ("B-o1",), ("B-o2",), ("B-1",), ("B-2",), _EX, _EX, _EX),
    "B-T4": _accounts("B-T4", ("B-o1", "B-o2"), ("B-1",), ("B-2",), _EX, _EX),
    "B-T5": _accounts("B-T5", ("B-o1", "B-o2"), ("B-4",), ("B-3",), ("B-4",), ("B-5",), _EX, _EX),
    "B-T8": _accounts("B-T8", ("B-o1", "B-o2"), ("B-2", "B-o3"), ("B-1",), ("B-2",), _EX),
    "C-T1": _accounts("C-T1", ("C-1", "C-o1"), ("C-1", "C-2"), ("C-1",), ("C-2",), _EX, _EX),
    "C-T2": _accounts("C-T2", ("C-1", "C-o1"), ("C-1", "C-2"), ("C-1",), ("C-2",), _EX, _EX),
    "C-T4": _accounts("C-T4", ("C-o1",), ("C-1", "C-2"), ("C-1",), ("C-2",), _EX),
    "D-T1": _accounts("D-T1", ("D-o1",), ("D-3",), ("D-1",), ("D-2",), _EX, _EX),
    "D-T4": _accounts("D-T4", ("D-o1",), ("D-1", "D-3"), ("D-1",), ("D-2",), _EX),
    "D-T10": _accounts("D-T10", ("D-o1", "D-o2"), ("D-4",), ("D-4",), ("D-5",), _EX, _EX, _EX),
    "E-T1": _accounts("E-T1", ("E-o1",), ("E-1",), ("E-1",), ("E-2",), _EX, _EX, _EX),
    "E-T4": _accounts("E-T4", ("E-o1",), ("E-1",), ("E-1",), ("E-2",), _EX),
    "F-T1": _accounts("F-T1", ("F-o1",), ("F-o2",), ("F-1",), ("F-2",), _EX, _EX),
    "F-T4": _accounts("F-T4", ("F-o1",), ("F-o2",), ("F-1",), ("F-2",), _EX, _EX),
    "F-T7": _accounts("F-T7", ("F-o1",), ("F-o2",), ("F-o3",), ("F-3",), ("F-2",), _EX, _EX),
    "F-T15": _accounts("F-T15", ("F-o1",), ("F-o2",), ("F-3",), ("F-2",), _EX, _EX),
    "G-T1": _accounts("G-T1", ("G-1", "G-2"), ("G-o1",), ("G-1",), ("G-2",), _EX),
    "G-T4": _accounts("G-T4", ("G-o1",), ("G-1",), ("G-2",), _EX),
    "G-T12": _accounts("G-T12", ("G-o1",), ("G-3", "G-4"), ("G-3",), ("G-4",), ("G-2",), _EX, _EX),
    "H-T1": _accounts("H-T1", ("H-1",), ("H-2", "H-3"), ("H-2",), ("H-3",), _EX, _EX),
    "H-T4": _accounts("H-T4", ("H-1",), ("H-2", "H-3"), ("H-2",), ("H-3",), _EX, _EX),
    "H-T9": _accounts("H-T9", ("H-1",), ("H-2", "H-3"), ("H-5",), ("H-2",), ("H-3",), ("H-4",),
                      _EX, _EX),
    "I-T1": _accounts("I-T1", ("I-o1",), ("I-1",), ("I-1",), ("I-2",), _EX, _EX),
    "I-T4": _accounts("I-T4", ("I-1",), ("I-1",), ("I-2",), _EX),
    "I-T16": _accounts("I-T16", ("I-4",), ("I-o2", "I-3", "I-4"), ("I-3",), ("I-4",), ("I-5",),
                       _EX, _EX),
    "J-T1": _accounts("J-T1", ("J-o1",), ("J-1",), ("J-1",), ("J-2",), _EX, _EX),
    "J-T4": _accounts("J-T4", ("J-o1",), ("J-1",), ("J-1",), ("J-2",), _EX),
    "J-T14": _accounts("J-T14", ("J-o1",), ("J-o2",), ("J-3",), ("J-4",), _EX, _EX),
    "K-T1": _accounts("K-T1", ("K-o1",), ("K-1",), ("K-1",), ("K-2",), _EX, _EX),
    "K-T4": _accounts("K-T4", ("K-o1",), ("K-1",), ("K-1",), ("K-2",), _EX, _EX),
    "K-T13": _accounts("K-T13", ("K-1",), ("K-o1", "K-o2"), ("K-o3",), ("K-1",), ("K-2",), _EX,
                       _EX),
    "L-T1": _accounts("L-T1", ("L-o1",), ("L-o2", "L-1"), ("L-1",), ("L-2",), _EX),
    "L-T4": _accounts("L-T4", ("L-o1", "L-o2"), ("L-1",), ("L-1",), ("L-2",), _EX),
    "L-T11": _accounts("L-T11", ("L-o1", "L-o2"), ("L-1", "L-o3"), ("L-1",), ("L-2",), _EX),
}  # fmt: skip
"""Every sentence of every distinct section text, accounted for. Sealed; ``prepare``
refuses a gap."""


def source_coverage_findings() -> tuple[str, ...]:
    findings: list[str] = []
    if set(SOURCE_COVERAGE) != set(_TEXTS):
        findings.append(f"coverage keys {sorted(set(_TEXTS) ^ set(SOURCE_COVERAGE))} differ")
    for key, accounts in SOURCE_COVERAGE.items():
        findings.extend(f"{key}: {f}" for f in coverage_findings(_TEXTS[key], accounts))
        for account in accounts:
            for pid in account.propositions:
                if pid not in _BY_ID or _BY_ID[pid].locus != key[0]:
                    findings.append(f"{key}: unknown or foreign proposition {pid}")
    return tuple(findings)


def _props_of(key: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(p for a in SOURCE_COVERAGE[key] for p in a.propositions))


# ------------------------------------------------------------------ per-turn expectations

_REQUIRED_CURRENT: Final[dict[Locus, tuple[tuple[int, tuple[str, ...]], ...]]] = {
    "A": ((1, ("A-1", "A-2", "A-3")), (3, ("A-4", "A-5", "A-6"))),
    "B": ((1, ("B-1", "B-2")), (5, ("B-3", "B-4", "B-5")), (8, ("B-1", "B-2"))),
    "C": ((1, ("C-1", "C-2")),),
    "D": ((1, ("D-1", "D-2", "D-3")), (10, ("D-4", "D-5"))),
    "E": ((1, ("E-1", "E-2")),),
    "F": ((1, ("F-1", "F-2")), (7, ("F-3", "F-2"))),
    "G": ((1, ("G-1", "G-2")), (12, ("G-2", "G-3", "G-4"))),
    "H": ((1, ("H-1", "H-2", "H-3")), (9, ("H-1", "H-2", "H-3", "H-4", "H-5"))),
    "I": ((1, ("I-1", "I-2")), (16, ("I-3", "I-4", "I-5"))),
    "J": ((1, ("J-1", "J-2")), (14, ("J-3", "J-4"))),
    "K": ((1, ("K-1", "K-2")),),
    "L": ((1, ("L-1", "L-2")),),
}
"""The required current propositions of each locus from the version they take effect, read
off the historical meanings (``BASELINE_MEANINGS`` and the §5 meaning of each transition)."""

_NO_LONGER_CURRENT: Final[dict[int, tuple[str, ...]]] = {
    3: ("A-1", "A-2", "A-3"),
    5: ("B-1", "B-2"),
    7: ("F-1",),
    8: ("B-3", "B-4", "B-5"),
    10: ("D-1",),
    12: ("G-1",),
    14: ("J-1", "J-2"),
    16: ("I-1",),
}
_COMPATIBLE_OPTIONAL: Final[dict[int, tuple[str, ...]]] = {10: ("D-2", "D-3"), 16: ("I-2",)}
"""Still-compatible, not restated: may stay current or be superseded (9P3 rubric: "any
still-compatible subclaim at the locus is not required to be superseded")."""

CORRECTION_TURNS: Final = tuple(sorted(_NO_LONGER_CURRENT))

LAWFUL_NODE_KINDS: Final = ("REQUIREMENT", "CONSTRAINT", "GOAL", "OUTCOME", "NON_GOAL")
"""Graph kinds a node grounded on Orion's operational claims may have. The contract (the
node-kind ontology certified by exam v6) does not decide REQUIREMENT against CONSTRAINT for
these rules, or whether "no ordering guarantee across partitions" is a NON_GOAL, so every one
of these is lawful; a DECISION, PREFERENCE, ASSUMPTION or second INTENT is not (nothing in the
corpus states a choice, a preference or an assumption)."""


def required_current(locus: Locus, t: int) -> tuple[str, ...]:
    current: tuple[str, ...] = ()
    for since, props in _REQUIRED_CURRENT[locus]:
        if since <= t:
            current = props
    return current


class TurnExpectation(FrozenModel):
    t: int
    transition: Literal["BASELINE"] | TransitionClass
    target_locus: Locus | None
    checkpoint: str | None
    new_claims: dict[Locus, tuple[int, int]]
    """Per locus: the inclusive range of claims newly asserted at its address in this turn."""
    supersession_required: bool
    required_current: dict[Locus, tuple[str, ...]]
    no_longer_current: tuple[str, ...]
    optional_compatible: tuple[str, ...]
    ie3_behaviour: Behaviour
    text_keys: dict[Locus, str]


def _new_optional(key: str, locus: Locus, t: int) -> int:
    earlier = {
        p
        for s in range(1, t)
        for p in _props_of(TEXT_KEY[(s, locus)])
        if _BY_ID[p].tier == "OPTIONAL"
    }
    return sum(1 for p in _props_of(key) if _BY_ID[p].tier == "OPTIONAL" and p not in earlier)


def _turn(t: int) -> TurnExpectation:
    checkpoint = next((c for c in CHECKPOINTS if c.t == t), None)
    transition = "BASELINE" if checkpoint is None else checkpoint.transition_class
    target = None if checkpoint is None else checkpoint.target_locus
    ranges: dict[Locus, tuple[int, int]] = {}
    for locus in LOCI:
        key = TEXT_KEY[(t, locus)]
        if t == 1:
            ranges[locus] = (1, len(_props_of(key)))
        elif locus != target:
            ranges[locus] = (0, 0)
        elif transition in ("CORRECTION", "REVERT"):
            ranges[locus] = (1, len(_props_of(key)))
        elif transition == "COMPATIBLE_EXTENSION":
            ranges[locus] = (1, 2)
        else:  # RESTATEMENT at the target: only genuinely new optional content may be stated
            ranges[locus] = (0, _new_optional(key, locus, t))
    behaviour: Behaviour = (
        "GRAPH_FORMATION"
        if t == 1
        else "REPLACE_STALE"
        if transition in ("CORRECTION", "REVERT")
        else "EXTEND"
        if transition == "COMPATIBLE_EXTENSION"
        else "NO_GRAPH_CHANGE"
    )
    return TurnExpectation(
        t=t,
        transition=transition,
        target_locus=target,
        checkpoint=None if checkpoint is None else checkpoint.id,
        new_claims=ranges,
        supersession_required=transition in ("CORRECTION", "REVERT"),
        required_current={locus: required_current(locus, t) for locus in LOCI},
        no_longer_current=_NO_LONGER_CURRENT.get(t, ()),
        optional_compatible=_COMPATIBLE_OPTIONAL.get(t, ()),
        ie3_behaviour=behaviour,
        text_keys={locus: TEXT_KEY[(t, locus)] for locus in LOCI},
    )


TURNS: Final[tuple[TurnExpectation, ...]] = tuple(_turn(t) for t in range(1, 17))

# ------------------------------------------------------------------ adjudication questions

Layer = Literal["IE2", "IE3"]
Timepoint = Literal["AFTER_IE2_AND_AUTHORITY", "AFTER_IE3", "IE2_CALL_2"]


class AdjudicationQuestion(FrozenModel):
    id: str
    layer: Layer
    t: int
    timepoint: Timepoint
    locus: Locus | None
    question: str
    propositions: tuple[str, ...]


def _statements(pids: tuple[str, ...]) -> str:
    return "; ".join(f"[{p}] {_BY_ID[p].statement}" for p in pids)


def _ie2_locus_question(t: int, locus: Locus, qid: str) -> AdjudicationQuestion:
    turn = TURNS[t - 1]
    required = turn.required_current[locus]
    stale = tuple(p for p in turn.no_longer_current if _BY_ID[p].locus == locus)
    compatible = tuple(p for p in turn.optional_compatible if _BY_ID[p].locus == locus)
    optional = tuple(p.id for p in PROPOSITIONS if p.locus == locus and p.tier == "OPTIONAL")
    text = (
        f"After T{t} (IE2 and the authority step), do the live claims at the address "
        f"designated for locus {locus} state every required proposition — {_statements(required)}"
        " — with no two live claims stating the same meaning, and no live claim stating a "
        "meaning that contradicts them, belongs to another locus, or was never in the source?"
    )
    if stale:
        text += f" None of these may still be current: {_statements(stale)}."
    if compatible:
        text += f" These may be current or not: {_statements(compatible)}."
    text += f" Optional descriptive statements may be present if faithful: {', '.join(optional)}."
    return AdjudicationQuestion(
        id=qid,
        layer="IE2",
        t=t,
        timepoint="AFTER_IE2_AND_AUTHORITY",
        locus=locus,
        question=text,
        propositions=required + stale + compatible,
    )


def _ie3_locus_question(t: int, locus: Locus, qid: str) -> AdjudicationQuestion:
    turn = TURNS[t - 1]
    required = turn.required_current[locus]
    stale = tuple(p for p in turn.no_longer_current if _BY_ID[p].locus == locus)
    text = (
        f"After T{t}'s graph synthesis, do the CURRENT graph objects grounded (DERIVED_FROM) on "
        f"locus {locus}'s live claims faithfully express those claims' meanings — in "
        f"particular {_statements(required)} — without inventing a rule, importing another "
        "locus's rule, or two current objects of the same kind stating the same meaning?"
    )
    if stale:
        text += f" No current object may still express: {_statements(stale)}."
    return AdjudicationQuestion(
        id=qid,
        layer="IE3",
        t=t,
        timepoint="AFTER_IE3",
        locus=locus,
        question=text,
        propositions=required + stale,
    )


def _accounting_question(t: int) -> AdjudicationQuestion:
    return AdjudicationQuestion(
        id=f"Q-IE2-T{t:02d}-ACCOUNT",
        layer="IE2",
        t=t,
        timepoint="IE2_CALL_2",
        locus=None,
        question=(
            f"In T{t}'s Call-2 accounting, is every REQUIRED proposition of every accountable "
            "section represented by the model's listed propositions (none silently lost by "
            "declaring the only sentence that states it non-operative), and does every listed "
            "proposition state something the section actually says?"
        ),
        propositions=(),
    )


def _questions() -> tuple[AdjudicationQuestion, ...]:
    out: list[AdjudicationQuestion] = []
    for locus in LOCI:
        out.append(_ie2_locus_question(1, locus, f"Q-IE2-T01-{locus}"))
    for turn in TURNS[1:]:
        if turn.t == 9:
            h: Locus = "H"
            out.append(
                AdjudicationQuestion(
                    id="Q-IE2-T09-H-EXISTING",
                    layer="IE2",
                    t=9,
                    timepoint="AFTER_IE2_AND_AUTHORITY",
                    locus=h,
                    question=(
                        "After T9, are the existing cancellation meanings still current and "
                        f"not superseded or duplicated — {_statements(('H-1', 'H-2', 'H-3'))}?"
                    ),
                    propositions=("H-1", "H-2", "H-3"),
                )
            )
            for pid in ("H-4", "H-5"):
                out.append(
                    AdjudicationQuestion(
                        id=f"Q-IE2-T09-{pid}",
                        layer="IE2",
                        t=9,
                        timepoint="AFTER_IE2_AND_AUTHORITY",
                        locus=h,
                        question=(
                            "After T9, does a live claim at the cancellation address state "
                            f"{_statements((pid,))}?"
                        ),
                        propositions=(pid,),
                    )
                )
        elif turn.target_locus is not None:
            out.append(
                _ie2_locus_question(turn.t, turn.target_locus, f"Q-IE2-T{turn.t:02d}-TARGET")
            )
    for turn in TURNS:
        out.append(_accounting_question(turn.t))
    for locus in LOCI:
        out.append(_ie3_locus_question(1, locus, f"Q-IE3-T01-{locus}"))
    for turn in TURNS[1:]:
        if turn.target_locus is not None:
            out.append(
                _ie3_locus_question(turn.t, turn.target_locus, f"Q-IE3-T{turn.t:02d}-TARGET")
            )
    return tuple(out)


ADJUDICATION_QUESTIONS: Final[tuple[AdjudicationQuestion, ...]] = _questions()


def adjudication_questions_sha256() -> str:
    return canonical_sha256(
        {"questions": [q.model_dump(mode="json") for q in ADJUDICATION_QUESTIONS]}
    )


def source_coverage_document() -> dict[str, object]:
    return {
        key: [a.model_dump(mode="json") for a in accounts]
        for key, accounts in sorted(SOURCE_COVERAGE.items())
    }


def expectations_document() -> dict[str, object]:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "derived_from": "long_horizon_bounded.expectations (9P3 answer key): BASELINE_MEANINGS, "
        "the §5 meaning of every transition and CHECKPOINTS",
        "propositions": [p.model_dump(mode="json") for p in PROPOSITIONS],
        "source_coverage": source_coverage_document(),
        "turns": [t.model_dump(mode="json") for t in TURNS],
        "correction_turns": list(CORRECTION_TURNS),
        "lawful_node_kinds": list(LAWFUL_NODE_KINDS),
        "adjudication_questions": [q.model_dump(mode="json") for q in ADJUDICATION_QUESTIONS],
    }


def expectations_sha256() -> str:
    return canonical_sha256(expectations_document())
