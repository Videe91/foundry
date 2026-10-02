"""Offline preflight of the live end-to-end Intent Engine validation. No model is called.

The real runner walks the sealed Larkspur sequence through the frozen runtime with scripted
ports: the faithful writer, a scripted semantic-admission (v4) verifier, a scripted IE3 graph
synthesizer and a scripted outcome adjudicator. The real scorer judges the final state. These
tests prove what the seal claims before anything live runs: the faithful run PASSES, the oracle
reaches only the adjudicator and only at evaluation time, harmless variation changes nothing,
every material fault is caught, the expected open contradiction is not a defect, and nothing
unadjudicated can pass.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.completeness_verifier import (
    ADMISSION_SYSTEM_INSTRUCTION,
    ModelRuntimeAdmissionVerifier,
)
from foundry.adapters.semantics.xai_reasoner import (
    CONFLICT_SYSTEM_INSTRUCTION,
    XAIConflictSemanticReasoner,
    conflict_accounted_output_schema_sha256,
)
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.experiments.intent_engine_e2e.expectations import EXPECTED, ExpectedOutcome
from foundry.experiments.intent_engine_e2e.outcome import (
    Adjudication,
    AdjudicationPacket,
    ClaimReading,
    DefectCategory,
    GraphReading,
)
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v1 import protocol, roles
from foundry.experiments.intent_engine_live_v1.adjudicator import (
    ADJUDICATOR_INSTRUCTION,
    ADJUDICATOR_INSTRUCTION_SHA256,
)
from foundry.experiments.intent_engine_live_v1.runner import LiveRunRecord, run_live
from foundry.experiments.long_horizon_ie2_ie3 import protocol as lh
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest
from tests.unit.test_intent_engine_e2e_harness import (
    FAITHFUL,
    TRUTH_OF,
    WRITER_MISSES_T07,
    ScenarioWriter,
    _admission_verifier,
)

AT = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
D = DefectCategory


# --- scripted IE3 and adjudicator -------------------------------------------------------------


class LarkspurIE3:
    """A scripted graph synthesizer: one root Intent and one Requirement per concern, derived
    from every live claim of that concern. The statement lists the claims' predicates, which is
    how the scripted adjudicator reads it (a live one reads meaning)."""

    fingerprint = ReasonerFingerprint(
        provider=lh.IE3_PROVIDER, model=lh.IE3_MODEL, policy_version=lh.IE3_POLICY_VERSION
    )

    def __init__(self, drop_concern: str | None = None) -> None:
        self.requests: list[IntentGraphSynthesisRequest] = []
        self.drop_concern = drop_concern

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
        self.requests.append(request)
        claims = sorted(c.claim_id for b in request.basis for c in b.live_claims)
        nodes: list[dict[str, Any]] = [
            {"local_id": {"local_id": "root"}, "kind": "INTENT",
             "mission": "Run the Larkspur Tool Library by its rules.",
             "proposal_rationale": "scripted"},
        ]  # fmt: skip
        relations: list[dict[str, Any]] = [_edge("root", "DERIVED_FROM", claims[0])]
        for i, basis in enumerate(sorted(request.basis, key=lambda b: b.subject)):
            if basis.subject == self.drop_concern:
                continue
            local = f"req-{i}"
            predicates = "; ".join(sorted(c.predicate for c in basis.live_claims))
            nodes.append(
                {"local_id": {"local_id": local}, "kind": "REQUIREMENT",
                 "statement": f"[{basis.subject}] {predicates}", "proposal_rationale": "scripted"}
            )  # fmt: skip
            relations += [_edge(local, "DERIVED_FROM", c.claim_id) for c in basis.live_claims]
            relations.append(
                {"source": {"local_id": local}, "relation_type": "SERVES",
                 "target": {"namespace": "local", "local_id": "root"}}
            )  # fmt: skip
        return IntentGraphSynthesisResult.model_validate(
            {"nodes": nodes, "relations": relations, "gaps": []}
        )


def _edge(source: str, relation: str, claim_id: str) -> dict[str, Any]:
    return {
        "source": {"local_id": source},
        "relation_type": relation,
        "target": {"namespace": "basis", "claim_id": claim_id},
    }


class ScriptedAdjudicator:
    """Maps each claim by the scripted writer's predicate table, and each graph object by the
    predicates its statement lists. Records when it was asked (after everything else)."""

    def __init__(self, truth_of: dict[str, str] | None = None) -> None:
        self.truth_of = truth_of or TRUTH_OF
        self.packets: list[AdjudicationPacket] = []

    def adjudicate(self, packet: AdjudicationPacket) -> Adjudication:
        self.packets.append(packet)
        held = {"R2"}
        current = [c for c in packet.claims if c.current]
        readings = tuple(
            ClaimReading(claim_id=c.claim_id, truth_id=self.truth_of.get(c.predicate),
                         faithful=True)
            for c in packet.claims
        )  # fmt: skip
        contradictions = tuple(
            (a.claim_id, b.claim_id)
            for i, a in enumerate(current) for b in current[i + 1:]
            if {self.truth_of.get(a.predicate), self.truth_of.get(b.predicate)} == {"R1", "R2"}
        )  # fmt: skip
        graph = tuple(
            GraphReading(
                object_id=o.object_id,
                truth_ids=tuple(sorted(
                    t for p in o.text.split("] ", 1)[-1].split("; ")
                    if (t := self.truth_of.get(p)) and t not in held
                )),
                faithful=True,
            )
            for o in packet.graph_objects
        )  # fmt: skip
        return Adjudication(readings=readings, contradictions=contradictions,
                            graph_readings=graph)  # fmt: skip


def _live(
    script: dict[str, Any] = FAITHFUL,
    *,
    verifier: Any = None,
    ie3: Any = None,
    adjudicator: Any = None,
    oracle: Callable[[], ExpectedOutcome] = lambda: EXPECTED,
) -> LiveRunRecord:
    ids = count(1)
    return run_live(
        writer=ScenarioWriter(script),
        verifier=verifier if verifier is not None else _admission_verifier(),
        ie3_synthesizer=ie3 if ie3 is not None else LarkspurIE3(),
        adjudicator=adjudicator if adjudicator is not None else ScriptedAdjudicator(),
        oracle=oracle,
        clock=lambda: AT,
        id_factory=lambda p: f"{p}-{next(ids):05d}",
    )


@pytest.fixture(scope="module")
def faithful() -> LiveRunRecord:
    return _live()


# --- the faithful run -------------------------------------------------------------------------


def test_the_faithful_scripted_run_passes(faithful: LiveRunRecord) -> None:
    report = faithful.report
    assert report.verdict == "PASS", [d.model_dump() for d in report.defects]
    assert report.defects == () and report.ie3_evaluated
    assert faithful.ie3_status == "APPLIED"
    assert len(faithful.steps) == len(SCENARIO.steps) == 18


def test_the_expected_open_contradiction_is_correct_not_a_defect(faithful: LiveRunRecord) -> None:
    gaps = faithful.final_outcome["gaps"]
    holds = [g for g in gaps if g["hold_cause"] is not None]
    assert [(g["hold_cause"], g["status"]) for g in holds if g["status"] == "OPEN"] == [
        ("CONFLICT", "OPEN")
    ]
    assert faithful.final_outcome["closure_closed"] is False
    assert faithful.report.counts["CONTRADICTORY_CURRENT_TRUTHS"] == 0
    assert faithful.report.counts["INCORRECT_CLOSURE"] == 0


def test_every_step_is_recorded_with_its_state_digest(faithful: LiveRunRecord) -> None:
    assert [s.step_id for s in faithful.steps] == [s.step_id for s in SCENARIO.steps]
    sequences = [s.last_sequence for s in faithful.steps]
    assert sequences == sorted(sequences) and len(set(s.state_sha256 for s in faithful.steps)) > 1
    assert len(faithful.writer_calls) <= protocol.MAX_WRITER_CALLS_PER_STEP * 18
    assert len(faithful.verifier_calls) <= 18 and len(faithful.ie3_calls) == 1
    assert faithful.events and faithful.final_state_sha256


def test_the_repeated_declined_change_is_refused_by_the_runtime(faithful: LiveRunRecord) -> None:
    (t12,) = [s for s in faithful.steps if s.step_id == "T12-deposit"]
    assert t12.decision_status == "NOT_DECIDED: 0 pending correction sets at Deposits"
    reasons = [
        r
        for e in faithful.events
        if e["event"]["event_type"] == "SEMANTIC_ADMISSION_DECIDED"
        for r in e["event"]["payload"]["reasons"]
    ]
    assert reasons.count("CORRECTION_DECLINED") == 3, "the earlier decline refuses the repeat"


# --- oracle isolation -------------------------------------------------------------------------


_ORACLE_ONLY = tuple(
    t.statement for t in EXPECTED.truths if not any(t.statement in s.text for s in SCENARIO.steps)
)


def _texts(items: list[Any]) -> str:
    return " ".join(i.model_dump_json() for i in items)


def test_the_oracle_never_reaches_writer_verifier_or_ie3() -> None:
    writer, verifier, ie3 = ScenarioWriter(FAITHFUL), _admission_verifier(), LarkspurIE3()
    seen: list[Any] = []
    original = writer.propose_accounted

    def spy(request: Any) -> Any:
        seen.append(request)
        return original(request)

    writer.propose_accounted = spy  # type: ignore[method-assign]
    ids = count(1)
    run_live(writer=writer, verifier=verifier, ie3_synthesizer=ie3,
             adjudicator=ScriptedAdjudicator(), oracle=lambda: EXPECTED, clock=lambda: AT,
             id_factory=lambda p: f"{p}-{next(ids):05d}")  # fmt: skip
    assert _ORACLE_ONLY, "the oracle states meaning in its own words"
    for label, text in (
        ("writer", _texts(seen)),
        ("verifier", _texts(verifier.requests)),
        ("ie3", _texts(ie3.requests)),
    ):
        for statement in _ORACLE_ONLY:
            assert statement not in text, (label, statement)
        for token in ('"HELD"', '"NEVER"', "open_contradictions", "contested_pairs", "truth_id"):
            assert token not in text, (label, token)


def test_the_oracle_is_loaded_only_after_ie3_and_shown_only_to_the_adjudicator() -> None:
    order: list[str] = []

    class OrderIE3(LarkspurIE3):
        def synthesize(self, request: Any) -> Any:
            order.append("ie3")
            return super().synthesize(request)

    def oracle() -> ExpectedOutcome:
        order.append("oracle")
        return EXPECTED

    adjudicator = ScriptedAdjudicator()
    _live(ie3=OrderIE3(), adjudicator=adjudicator, oracle=oracle)
    assert order == ["ie3", "oracle"]
    (packet,) = adjudicator.packets
    assert {t.truth_id for t in packet.truths} == {t.truth_id for t in EXPECTED.truths}


def test_no_request_path_module_imports_the_oracle_or_the_scorer() -> None:
    for path in (
        "src/foundry/experiments/intent_engine_e2e/scenario.py",
        "src/foundry/experiments/intent_engine_e2e/harness.py",
        "src/foundry/experiments/intent_engine_live_v1/recording.py",
        "src/foundry/experiments/intent_engine_live_v1/protocol.py",
    ):
        tree = ast.parse(Path(path).read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(m.endswith((".expectations", ".outcome", ".adjudicator")) for m in imported)


# --- harmless variation -----------------------------------------------------------------------


def _renamed(script: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Every predicate renamed, and the membership fee split into two claims."""

    def rn(p: str) -> str:
        return f"rule.{p[::-1]}"

    out: dict[str, Any] = {}
    for step, props in script.items():
        out[step] = tuple(
            (pid, n, f"another statement of {pid}",
             tuple((d[0], rn(d[1]), *d[2:]) for d in drafts))
            for pid, n, _, drafts in props
        )  # fmt: skip
    return out, {rn(p): t for p, t in TRUTH_OF.items()}


def test_equivalent_wording_and_decomposition_do_not_change_the_result() -> None:
    script, truth_of = _renamed(FAITHFUL)
    script["T13-opening"] = (
        ("p1", (1,), "open on Saturdays", (("ASSERT", "rule.sat_open", "Saturday"),
                                           ("ASSERT", "rule.sat_hours", "10:00-14:00"))),
        ("p2", (2,), "collection", (("ASSERT", "rule.collect", "only when open"),)),
    )  # fmt: skip
    truth_of |= {"rule.sat_open": "O1", "rule.sat_hours": "O1", "rule.collect": "O2"}
    verifier = _admission_verifier_renamed()
    report = _live(script, verifier=verifier, adjudicator=ScriptedAdjudicator(truth_of)).report
    assert report.verdict == "PASS", [d.model_dump() for d in report.defects]


def _admission_verifier_renamed() -> Any:
    """The scripted v4 verifier of the harness keyed on the renamed predicates."""
    from tests.unit import test_intent_engine_e2e_harness as h

    base = h._admission_verifier()
    inner = base._answer

    def answer(request: Any) -> Any:
        mapped = request.model_copy(
            update={
                "current_claims": tuple(
                    c.model_copy(update={"predicate": c.predicate.removeprefix("rule.")[::-1]})
                    for c in request.current_claims
                ),
                "propositions": tuple(
                    p.model_copy(update={"claims": tuple(
                        c.model_copy(update={"predicate": c.predicate.removeprefix("rule.")[::-1]})
                        for c in p.claims
                    )})
                    for p in request.propositions
                ),
            }
        )  # fmt: skip
        return inner(mapped)

    base._answer = answer
    return base


# --- material faults are caught ---------------------------------------------------------------


def _categories(record: LiveRunRecord) -> set[DefectCategory]:
    return {d.category for d in record.report.defects}


def test_fault_missing_truth() -> None:
    script = dict(FAITHFUL)
    script["T13-opening"] = (
        FAITHFUL["T13-opening"][0],
        ("p2", (2,), "collection", (("SUPPORT", "opening_hours"),)),
    )
    assert D.MISSING_TRUTH in _categories(_live(script))


def test_fault_invented_truth() -> None:
    script = dict(FAITHFUL)
    script["T13-opening"] = (
        ("p1", (1,), "open Saturdays", (("ASSERT", "opening_hours", "Saturdays 10:00-14:00"),
                                        ("ASSERT", "invented_rule", "members get free coffee"))),
        FAITHFUL["T13-opening"][1],
    )  # fmt: skip
    assert D.INVENTED_TRUTH in _categories(_live(script))


def test_fault_stale_truth() -> None:
    script = dict(FAITHFUL)
    script["T03-loan"] = (
        ("p1", (1,), "14 days", (("ASSERT", "loan_period_v2", "14 days"),)),
        FAITHFUL["T03-loan"][1],
    )
    assert D.STALE_TRUTH in _categories(_live(script))


def test_fault_accepted_contradiction() -> None:
    report = _live(WRITER_MISSES_T07, verifier=_blind_v4()).report
    assert D.CONTRADICTORY_CURRENT_TRUTHS in {d.category for d in report.defects}


def _blind_v4() -> Any:
    """A v4 verifier that never finds a conflict (it still catches the lost fee)."""
    from tests.unit import test_intent_engine_e2e_harness as h

    base = h._admission_verifier()
    inner = base._answer

    def answer(request: Any) -> Any:
        report = inner(request)
        return report.model_copy(
            update={
                "verdicts": tuple(
                    v.model_copy(update={"consistency": "NO_CONFLICT", "conflicting_claim_ids": ()})
                    for v in report.verdicts
                )
            }
        )

    base._answer = answer
    return base


def test_fault_declined_change_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    steps = tuple(
        s.model_copy(update={"decision": "AGREE"}) if s.step_id == "T05-deposit" else s
        for s in SCENARIO.steps
    )
    monkeypatch.setattr(
        "foundry.experiments.intent_engine_live_v1.runner.SCENARIO",
        SCENARIO.model_copy(update={"steps": steps}),
    )
    assert D.DECLINED_CHANGE_APPLIED in _categories(_live())


def test_fault_authority_bypass(faithful: LiveRunRecord) -> None:
    """The frozen runtime offers no path around founder authority (with correction sets off,
    the supersessions still wait for a human), so the fault is injected into the final state:
    an agreed correction recorded as still PENDING while its members are applied."""
    final, adjudication = _faithful_final(faithful)
    sets = tuple(
        s.model_copy(update={"status": "PENDING"}) if i == 0 else s
        for i, s in enumerate(s for s in final.correction_sets if s.status == "AGREED")
    ) + tuple(s for s in final.correction_sets if s.status != "AGREED")
    bypassed = final.model_copy(update={"correction_sets": sets})
    assert D.AUTHORITY_BYPASS in _scored(bypassed, adjudication)


def _faithful_final(record: LiveRunRecord) -> tuple[Any, Adjudication]:
    from foundry.experiments.intent_engine_e2e.outcome import FinalOutcome, adjudication_packet

    final = FinalOutcome.model_validate(record.final_outcome)
    return final, ScriptedAdjudicator().adjudicate(adjudication_packet(final, EXPECTED))


def _scored(final: Any, adjudication: Adjudication) -> set[DefectCategory]:
    from foundry.experiments.intent_engine_e2e.outcome import score

    return {d.category for d in score(final, EXPECTED, adjudication).defects}


def test_fault_silent_unresolved_gap() -> None:
    class Crashing:
        checks_consistency = True

        def __init__(self) -> None:
            self.inner = _admission_verifier()

        def verify(self, request: Any) -> Any:
            if any(c.predicate == "opening_hours" for p in request.propositions
                   for c in p.claims):  # fmt: skip
                raise RuntimeError("verifier crashed")
            return self.inner.verify(request)

    assert D.SILENT_GAP in _categories(_live(verifier=Crashing()))


def test_fault_incorrect_gap_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolution the law never granted: the open contradiction hold is closed by fiat while
    its conflicting claim is still current."""
    from foundry.application.intent_graph_synthesis import synthesize_intent_graph
    from foundry.application.semantic_governance import SemanticGovernor
    from foundry.domain.admission import AdmissionPolicy
    from foundry.domain.semantic_holds import SemanticHoldGap

    def resolve_then_synthesize(store: Any, **kwargs: Any) -> Any:
        governor = SemanticGovernor(store=store, project_id=kwargs["project_id"],
                                    policy=AdmissionPolicy(), clock=lambda: AT,
                                    id_factory=lambda p: f"{p}-FORGED")  # fmt: skip
        (gap,) = [g for g in governor.state().gaps.values()
                  if isinstance(g, SemanticHoldGap) and g.cause == "CONFLICT"]  # fmt: skip
        governor.resolve_hold_gap(gap.id)
        return synthesize_intent_graph(store, **kwargs)

    monkeypatch.setattr(
        "foundry.experiments.intent_engine_live_v1.runner.synthesize_intent_graph",
        resolve_then_synthesize,
    )
    assert D.INCORRECT_GAP_RESOLUTION in _categories(_live())


def test_fault_ie3_mismatch() -> None:
    assert D.IE2_IE3_SEMANTIC_MISMATCH in _categories(_live(ie3=LarkspurIE3("Damage")))


def test_fault_false_closure_is_caught_by_the_scorer(faithful: LiveRunRecord) -> None:
    final, adjudication = _faithful_final(faithful)
    falsely_closed = final.model_copy(update={"closure_closed": True, "closure_gap_blockers": ()})
    assert D.INCORRECT_CLOSURE in _scored(falsely_closed, adjudication)


# --- nothing unadjudicated passes ---------------------------------------------------------------


def test_an_uncovered_or_uncertain_or_failed_adjudication_is_not_validated() -> None:
    class Omits(ScriptedAdjudicator):
        def adjudicate(self, packet: AdjudicationPacket) -> Adjudication:
            full = super().adjudicate(packet)
            return full.model_copy(update={"readings": full.readings[1:]})

    class Unsure(ScriptedAdjudicator):
        def adjudicate(self, packet: AdjudicationPacket) -> Adjudication:
            full = super().adjudicate(packet)
            first = full.readings[0].model_copy(update={"certain": False})
            return full.model_copy(update={"readings": (first, *full.readings[1:])})

    class Fails(ScriptedAdjudicator):
        def adjudicate(self, packet: AdjudicationPacket) -> Adjudication:
            raise RuntimeError("adjudicator unreachable")

    for adjudicator in (Omits(), Unsure(), Fails()):
        assert _live(adjudicator=adjudicator).report.verdict == "NOT_VALIDATED"


# --- the sealed identities are the code's -----------------------------------------------------


def test_the_protocol_identities_are_the_frozen_code() -> None:
    assert XAIConflictSemanticReasoner.policy_version == protocol.WRITER_POLICY_VERSION
    assert type.__name__ and XAIConflictSemanticReasoner.__name__ == protocol.WRITER_REASONER_CLASS
    assert hashlib.sha256(CONFLICT_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        protocol.WRITER_PROMPT_SHA256
    )
    assert conflict_accounted_output_schema_sha256() == protocol.WRITER_OUTPUT_SCHEMA_SHA256
    assert ModelRuntimeAdmissionVerifier.__name__ == protocol.VERIFIER_ADAPTER_CLASS
    assert hashlib.sha256(ADMISSION_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        protocol.VERIFIER_INSTRUCTION_SHA256
    )
    assert hashlib.sha256(ADJUDICATOR_INSTRUCTION.encode()).hexdigest() == (
        ADJUDICATOR_INSTRUCTION_SHA256
    )
    certificate = Path(lh.IE3_CERTIFICATE_PATH).read_bytes()
    assert hashlib.sha256(certificate).hexdigest() == lh.IE3_CERTIFICATE_SHA256
    assert protocol.IE3_CERTIFICATE_PATH == lh.IE3_CERTIFICATE_PATH


def test_a_binding_must_respect_every_role_requirement() -> None:
    ok = roles.RoleBinding(
        decided_by=protocol.FOUNDER,
        writer=roles.BoundModel(provider="xai", model="grok-4.6"),
        writer_reasoning_effort="high",
        verifier=roles.BoundModel(provider="anthropic", model="claude-opus-5-5"),
        verifier_authorization="experiment-scoped use of an uncertified v4 verifier",
        adjudicator=roles.BoundModel(provider="anthropic", model="claude-fable-5-1"),
        adjudicator_authorization="experiment-scoped evaluation only",
    )
    assert roles.binding_findings(ok) == ()
    bad = ok.model_copy(
        update={
            "verifier": roles.BoundModel(provider="xai", model="grok-4.6"),
            "adjudicator": roles.BoundModel(provider="openai", model="gpt-6-astra"),
            "decided_by": "human://someone-else",
        }
    )
    findings = roles.binding_findings(bad)
    assert "VERIFIER_NOT_INDEPENDENT_OF_WRITER" in findings
    assert "ADJUDICATOR_IS_THE_IE3_MODEL" in findings
    assert any(f.startswith("NOT_A_SEALED_CANDIDATE: VERIFIER") for f in findings)
    assert any(f.startswith("NOT_DECIDED_BY_THE_FOUNDER") for f in findings)
    statuses = {(c.role, c.status) for c in roles.CANDIDATES}
    assert ("VERIFIER", "CERTIFIED") not in statuses, "no model holds the v4 contract"
    assert ("IE3", "CERTIFIED") in statuses


# --- the seal and its gates ---------------------------------------------------------------------


def test_the_manifest_is_deterministic_and_seals_what_the_run_depends_on() -> None:
    from foundry.experiments.intent_engine_live_v1 import seal

    one, two = seal.manifest(harness_commit="abc"), seal.manifest(harness_commit="abc")
    assert one == two
    assert [s["step_id"] for s in one["corpus"]["steps"]] == [s.step_id for s in SCENARIO.steps]
    assert one["authority_decisions"] == [
        {"step_id": s.step_id, "decision": s.decision} for s in SCENARIO.steps if s.decision
    ]
    assert one["scorer"]["categories"] == [c.value for c in DefectCategory]
    assert len(one["scorer"]["categories"]) == 12
    assert one["identities"]["runtime"]["execution_mode"] == "EXPERIMENT"
    assert one["budget"] == {
        "writer_calls_max": 36, "verifier_calls_max": 18, "ie3_calls_max": 1,
        "adjudicator_calls_max": 1, "writer_cost_usd_max": 25.0,
    }  # fmt: skip
    oracle_text = seal.sealed_json(seal.oracle_document())
    manifest_text = seal.sealed_json(one)
    for t in EXPECTED.truths:
        if t.statement in _ORACLE_ONLY:
            assert t.statement not in manifest_text, "the manifest seals the oracle by digest"
            assert t.statement in oracle_text
    assert seal.leakage_findings() == ()


def test_each_preflight_gate_refuses_its_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from foundry.experiments.intent_engine_live_v1 import seal

    monkeypatch.setattr(protocol, "EXPERIMENT_ARTIFACT_DIR", str(tmp_path) + "/")
    keys = {"XAI_API_KEY": "x", "OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a"}
    refused = seal.preflight_gates(environ={}, worktree_clean=False)
    assert {n for n, (ok, _) in refused.items() if not ok} == {
        "SEAL_INTACT", "ORACLE_INTACT", "ROLE_BINDING_LAWFUL", "CREDENTIALS_PRESENT",
        "WORKTREE_CLEAN",
    }  # fmt: skip
    seal.write_seal(harness_commit="abc")
    binding = roles.RoleBinding(
        decided_by=protocol.FOUNDER,
        writer=roles.BoundModel(provider="xai", model="grok-4.6"), writer_reasoning_effort="high",
        verifier=roles.BoundModel(provider="anthropic", model="claude-opus-5-5"),
        verifier_authorization="experiment-scoped",
        adjudicator=roles.BoundModel(provider="anthropic", model="claude-fable-5-1"),
        adjudicator_authorization="experiment-scoped",
    )  # fmt: skip
    (tmp_path / protocol.ROLE_BINDING_FILE).write_text(binding.model_dump_json())
    gates = seal.preflight_gates(environ=keys, worktree_clean=True)
    assert all(ok for ok, _ in gates.values()), gates
    oracle = json.loads((tmp_path / "oracle.json").read_text())
    oracle["oracle"]["truths"][0]["final"] = "RETIRED"
    (tmp_path / "oracle.json").write_text(json.dumps(oracle))
    assert not seal.preflight_gates(environ=keys, worktree_clean=True)["ORACLE_INTACT"][0]
    seal.write_seal(harness_commit="abc")
    (tmp_path / "run.json").write_text("{}")
    assert not seal.preflight_gates(environ=keys, worktree_clean=True)["UNCONSUMED"][0]


def test_the_experiment_scoped_registries_certify_exactly_one_thing() -> None:
    from foundry.adapters.semantics.completeness_verifier import (
        ADMISSION_V4_CONTRACT,
        COMPLETENESS_V3_CONTRACT,
    )
    from foundry.experiments.intent_engine_live_v1.live import (
        adjudicator_registry,
        verifier_registry,
    )
    from foundry.model_runtime.domain import ModelTask

    binding = roles.RoleBinding(
        decided_by=protocol.FOUNDER,
        writer=roles.BoundModel(provider="xai", model="grok-4.6"), writer_reasoning_effort="high",
        verifier=roles.BoundModel(provider="openai", model="gpt-6-astra"),
        verifier_authorization="experiment-scoped",
        adjudicator=roles.BoundModel(provider="anthropic", model="claude-opus-5-5"),
        adjudicator_authorization="experiment-scoped",
    )  # fmt: skip
    (verifier,) = verifier_registry(binding).descriptors
    assert verifier.certified_tasks == frozenset({ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION})
    assert {c.contract for c in verifier.certified_contracts} == {ADMISSION_V4_CONTRACT}
    assert COMPLETENESS_V3_CONTRACT not in {c.contract for c in verifier.certified_contracts}
    (adjudicator,) = adjudicator_registry(binding).descriptors
    assert adjudicator.certified_tasks == frozenset({ModelTask.EVALUATION})
    assert not adjudicator.certified_contracts
