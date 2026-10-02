"""Offline preflight of live end-to-end validation v2. No model is called.

The real v2 runner walks the sealed Larkspur sequence with scripted ports that reproduce what the
live v1 run actually did -- Grok's own concern labels, and the handbook's 3-day hold written as a
correction of the 2-day claim with no conflict declared -- plus a scripted v5 verifier that
judges that replacement CONFLICTING_EVIDENCE, a scripted IE3 and a scripted adjudicator. Under
the v2 laws every founder decision lands, the contradiction is held visibly, and the sealed
scorer finds nothing: PASS. The v1 lineage is untouched.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

import ast
import json
import subprocess
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.completeness_verifier import (
    ADMISSION_V4_CONTRACT,
    ADMISSION_V5_CONTRACT,
    ADMISSION_V5_SYSTEM_INSTRUCTION,
    ModelRuntimeAdmissionVerifierV5,
)
from foundry.experiments.intent_engine_e2e.expectations import EXPECTED, ExpectedOutcome
from foundry.experiments.intent_engine_e2e.outcome import DefectCategory, FinalOutcome
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v2 import protocol, roles
from foundry.experiments.intent_engine_live_v2.runner import LiveRunRecord, run_live
from tests.unit.test_intent_engine_live_v1 import LarkspurIE3, ScriptedAdjudicator
from tests.unit.test_intent_engine_live_v2_routing import (
    GROK_LABELS,
    MISLABELLED_T07,
    LabelledWriter,
    larkspur_v5,
)

AT = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
D = DefectCategory
V1_DIR = Path("docs/superpowers/experiments/2026-10-02-intent-engine-live-e2e-v1")


def _live(
    writer: Any = None,
    *,
    verifier: Any = None,
    adjudicator: Any = None,
    oracle: Any = lambda: EXPECTED,
) -> LiveRunRecord:
    ids = count(1)
    return run_live(
        writer=writer or LabelledWriter(MISLABELLED_T07, GROK_LABELS),
        verifier=verifier or larkspur_v5(),
        ie3_synthesizer=LarkspurIE3(),
        adjudicator=adjudicator or ScriptedAdjudicator(),
        oracle=oracle,
        clock=lambda: AT,
        id_factory=lambda p: f"{p}-{next(ids):05d}",
    )


@pytest.fixture(scope="module")
def replayed_v1() -> LiveRunRecord:
    """The live v1 shapes (Grok labels, T07 written as a correction), under the v2 laws."""
    return _live()


def test_the_live_v1_shapes_pass_under_the_v2_laws(replayed_v1: LiveRunRecord) -> None:
    report = replayed_v1.report
    assert report.verdict == "PASS", [d.model_dump() for d in report.defects]
    assert all(n == 0 for n in report.counts.values()) and report.ie3_evaluated
    assert replayed_v1.routing_stop is None and len(replayed_v1.steps) == 18


def test_every_founder_decision_landed_or_lawfully_had_nothing(replayed_v1: LiveRunRecord) -> None:
    decided = {s.step_id: s.decision_status for s in replayed_v1.steps if s.decision_status}
    assert decided == {
        "T03-loan": "AGREED", "T04-late": "AGREED", "T05-deposit": "DECLINED",
        "T06-damage": "AGREED", "T09-loan": "AGREED", "T11-membership": "AGREED",
        "T12-deposit": "NO_WORK: REFUSED (CORRECTION_DECLINED)",
    }  # fmt: skip


def test_the_t07_replacement_is_held_as_the_one_open_contradiction(
    replayed_v1: LiveRunRecord,
) -> None:
    final = FinalOutcome.model_validate(replayed_v1.final_outcome)
    open_holds = [g for g in final.gaps if g.hold_cause is not None and g.status == "OPEN"]
    assert [(g.kind, g.hold_cause) for g in open_holds] == [("CONTRADICTION", "CONFLICT")]
    assert final.closure_closed is False
    current = {c.predicate: c.value for c in final.claims if c.current}
    assert current["hold_period"] == "2 days" and "hold_period_handbook" not in current
    assert [s.status for s in final.correction_sets].count("PENDING") == 0


def test_the_faithful_writer_also_passes() -> None:
    from tests.unit.test_intent_engine_e2e_harness import FAITHFUL

    assert _live(LabelledWriter(FAITHFUL)).report.verdict == "PASS"


def test_a_routing_stop_is_not_validated_and_never_scored() -> None:
    original = protocol.ADMISSION_POLICY
    calls: list[str] = []

    def oracle() -> ExpectedOutcome:
        calls.append("oracle")
        return EXPECTED

    protocol.ADMISSION_POLICY = {"canonical_facets": True, "correction_sets": False}  # type: ignore[misc]
    try:
        record = _live(oracle=oracle)
    finally:
        protocol.ADMISSION_POLICY = original  # type: ignore[misc]
    assert record.report.verdict == "NOT_VALIDATED" and record.routing_stop
    assert record.report.adjudication_issues[0].startswith("ROUTING_STOP: RoutingUnexplained")
    assert record.ie3_status == "NOT_RUN" and record.ie3_calls == () and calls == []


def test_a_blind_v5_verifier_lets_the_mislabelled_contradiction_through_and_is_caught() -> None:
    """If the verifier wrongly judged the handbook a supported replacement, the founder has no
    T07 decision: the 3-day correction stays pending, and the oracle's expected open
    contradiction is missing -- the scorer catches it."""
    from tests.unit.test_semantic_admission_v5 import admission5

    record = _live(verifier=_supported_everywhere(admission5))
    categories = {d.category for d in record.report.defects}
    assert record.report.verdict == "FAIL"
    assert {D.SILENT_GAP, D.INCORRECT_CLOSURE} <= categories


def _supported_everywhere(admission5: Any) -> Any:
    base = larkspur_v5()
    inner = base._answer

    def answer(request: Any) -> Any:
        report: Any = inner(request)
        return report.model_copy(update={"verdicts": tuple(
            v.model_copy(update={"replacements": tuple(
                r.model_copy(update={"judgement": "SUPPORTED_REPLACEMENT"})
                for r in v.replacements)})
            for v in report.verdicts)})  # fmt: skip

    base._answer = answer
    return base


def test_the_v5_silent_gap_rule() -> None:
    from foundry.experiments.intent_engine_e2e.outcome import CompletenessView
    from foundry.experiments.intent_engine_live_v2.runner import evaluate_v2

    final = FinalOutcome.model_validate(_live().final_outcome)
    broken = final.model_copy(update={"completeness": (*final.completeness, CompletenessView(
        verification_id="VER-X", policy_version="ie2-semantic-admission-v5", outcome="FAIL",
        held_proposition_ids=("p1",), gap_ids=()))})  # fmt: skip
    report = evaluate_v2(broken, EXPECTED, ScriptedAdjudicator())
    assert report.verdict == "FAIL" and report.counts["SILENT_GAP"] == 1


# --- oracle isolation ----------------------------------------------------------------------------


_ORACLE_ONLY = tuple(
    t.statement for t in EXPECTED.truths if not any(t.statement in s.text for s in SCENARIO.steps)
)


def test_the_oracle_never_reaches_writer_verifier_or_ie3(replayed_v1: LiveRunRecord) -> None:
    requests = json.dumps(
        [c["request"] for c in replayed_v1.writer_calls + replayed_v1.verifier_calls
         + replayed_v1.ie3_calls]
    )  # fmt: skip
    for statement in _ORACLE_ONLY:
        assert statement not in requests, statement
    for token in ('"HELD"', '"NEVER"', "open_contradictions", "contested_pairs", "truth_id"):
        assert token not in requests, token


def test_no_request_path_module_imports_the_oracle_or_the_scorer() -> None:
    from foundry.experiments.intent_engine_live_v2 import seal

    assert seal.leakage_findings() == ()
    for path in seal.REQUEST_PATH_MODULES:
        tree = ast.parse(Path(path).read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(m.endswith((".expectations", ".outcome", ".adjudicator")) for m in imported)


# --- identities, roles, seal ---------------------------------------------------------------------


def test_the_protocol_identities_are_the_code() -> None:
    import hashlib

    assert ModelRuntimeAdmissionVerifierV5.__name__ == protocol.VERIFIER_ADAPTER_CLASS
    assert ADMISSION_V5_CONTRACT.policy_version == protocol.VERIFIER_POLICY_VERSION
    assert hashlib.sha256(ADMISSION_V5_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        protocol.VERIFIER_INSTRUCTION_SHA256
    )
    from foundry.experiments.intent_engine_live_v2.harness import ROUTING_LAW

    assert protocol.ROUTING_LAW.startswith(ROUTING_LAW)
    assert protocol.EXPERIMENT_VERSION == "intent-engine-live-e2e-v2"
    assert protocol.EXPERIMENT_ARTIFACT_DIR.endswith("intent-engine-live-e2e-v2/")


def test_the_v2_registries_certify_exactly_the_v5_contract() -> None:
    from foundry.experiments.intent_engine_live_v2.live import verifier_registry

    binding = roles.RoleBinding(
        decided_by=protocol.FOUNDER,
        writer=roles.BoundModel(provider="xai", model="grok-4.6"), writer_reasoning_effort="high",
        verifier=roles.BoundModel(provider="openai", model="gpt-6-astra"),
        verifier_authorization="experiment-scoped",
        adjudicator=roles.BoundModel(provider="anthropic", model="claude-opus-5-5"),
        adjudicator_authorization="experiment-scoped",
    )  # fmt: skip
    assert roles.binding_findings(binding) == ()
    (descriptor,) = verifier_registry(binding).descriptors
    contracts = {c.contract for c in descriptor.certified_contracts}
    assert contracts == {ADMISSION_V5_CONTRACT} and ADMISSION_V4_CONTRACT not in contracts


def test_the_v2_manifest_pins_both_lessons() -> None:
    from foundry.experiments.intent_engine_live_v2 import seal

    one = seal.manifest(harness_commit="abc")
    assert one == seal.manifest(harness_commit="abc")
    assert one["experiment_version"] == "intent-engine-live-e2e-v2"
    assert one["routing"]["law"] == protocol.ROUTING_LAW
    assert one["replacement"]["law"] == protocol.REPLACEMENT_LAW
    assert one["identities"]["verifier"]["policy_version"] == "ie2-semantic-admission-v5"
    assert one["authority_decisions"] == [
        {"step_id": s.step_id, "decision": s.decision} for s in SCENARIO.steps if s.decision
    ]
    assert one["budget"] == {
        "writer_calls_max": 36, "verifier_calls_max": 18, "ie3_calls_max": 1,
        "adjudicator_calls_max": 1, "writer_cost_usd_max": 25.0,
    }  # fmt: skip
    oracle = seal.oracle_document()
    assert oracle["experiment_version"] == "intent-engine-live-e2e-v2"
    assert oracle["oracle"] == EXPECTED.model_dump(mode="json"), "the same oracle meaning"


def test_each_v2_preflight_gate_refuses_its_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foundry.experiments.intent_engine_live_v2 import seal

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
        verifier=roles.BoundModel(provider="openai", model="gpt-6-astra"),
        verifier_authorization="experiment-scoped",
        adjudicator=roles.BoundModel(provider="anthropic", model="claude-opus-5-5"),
        adjudicator_authorization="experiment-scoped",
    )  # fmt: skip
    (tmp_path / protocol.ROLE_BINDING_FILE).write_text(binding.model_dump_json())
    assert all(ok for ok, _ in seal.preflight_gates(environ=keys, worktree_clean=True).values())
    (tmp_path / "run.json").write_text("{}")
    assert not seal.preflight_gates(environ=keys, worktree_clean=True)["UNCONSUMED"][0]


# --- live e2e v1 is frozen -----------------------------------------------------------------------


def test_live_e2e_v1_is_untouched_and_stays_fail() -> None:
    assert json.loads((V1_DIR / "report.json").read_text())["verdict"] == "FAIL"
    changed = subprocess.run(
        ["git", "diff", "--name-only", "52fc54a", "--", str(V1_DIR),
         "src/foundry/experiments/intent_engine_live_v1",
         "src/foundry/experiments/intent_engine_e2e"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert changed == "", changed
