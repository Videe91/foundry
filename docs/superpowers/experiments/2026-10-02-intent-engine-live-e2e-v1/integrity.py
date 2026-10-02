"""Post-run integrity checks of intent-engine-live-e2e-v1 (offline; reads the evidence only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foundry.application.replay import replay
from foundry.domain.events import StoredEvent
from foundry.experiments.intent_engine_e2e.outcome import FinalOutcome, OutcomeReport, score
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v1 import protocol
from foundry.experiments.intent_engine_live_v1.adjudicator import (
    OutcomeAdjudicationAnswer,
    to_adjudication,
)
from foundry.experiments.intent_engine_live_v1.runner import state_sha256
from foundry.experiments.intent_engine_live_v1.seal import load_oracle, preflight_gates

OUT = Path(protocol.EXPERIMENT_ARTIFACT_DIR)


def main() -> dict[str, Any]:
    run = json.loads((OUT / "run.json").read_text())
    meta = json.loads((OUT / "call_metadata.json").read_text())
    report = OutcomeReport.model_validate_json((OUT / "report.json").read_text())
    oracle = load_oracle()
    checks: dict[str, Any] = {}

    steps = [s["step_id"] for s in run["steps"]]
    checks["ordered_steps"] = steps == [s.step_id for s in SCENARIO.steps] and len(steps) == 18
    checks["calls"] = {
        "writer": len(run["writer_calls"]),
        "verifier": len(run["verifier_calls"]),
        "ie3": len(run["ie3_calls"]),
        "adjudicator": len(meta["adjudicator_provider_records"]),
    }
    checks["within_budget"] = (
        checks["calls"]["writer"] <= 36
        and checks["calls"]["verifier"] <= 18
        and checks["calls"]["ie3"] == 1
        and checks["calls"]["adjudicator"] == 1
    )
    checks["no_call_errors"] = not any(
        c["error"] for c in run["writer_calls"] + run["verifier_calls"] + run["ie3_calls"]
    )
    checks["models"] = {
        "writer_requested": sorted({r["model"] for r in meta["writer_receipts"]}),
        "verifier_executed": sorted(
            {
                f"{c['answer']['verifier']['provider']}/{c['answer']['verifier']['model']}"
                for c in run["verifier_calls"]
            }
        ),
        "verifier_policy": sorted(
            {c["answer"]["verifier"]["policy_version"] for c in run["verifier_calls"]}
        ),
        "ie3_executed": sorted(
            {f"{r['provider']}/{r['model']}" for r in meta["ie3_provider_records"]}
        ),
        "adjudicator_executed": sorted(
            {f"{r['provider']}/{r['model']}" for r in meta["adjudicator_provider_records"]}
        ),
    }
    oracle_only = [
        t.statement for t in oracle.truths if not any(t.statement in s.text for s in SCENARIO.steps)
    ]
    # A model input may repeat text a model itself wrote earlier (a writer's proposition
    # statement is shown to the verifier). That is not a leak. A leak is oracle-only text in a
    # model input that no model ever authored.
    authored = json.dumps([c["answer"] for c in run["writer_calls"]])
    leaks, coincidences = [], []
    for role in ("writer_calls", "verifier_calls", "ie3_calls"):
        for call in run[role]:
            text = json.dumps(call["request"])
            for statement in oracle_only:
                if statement in text:
                    hit = {"role": role, "call": call["call"], "statement": statement}
                    (coincidences if statement in authored else leaks).append(hit)
    checks["oracle_isolated_from_model_inputs"] = not leaks
    checks["oracle_leaks"] = leaks
    checks["writer_authored_text_equal_to_an_oracle_statement"] = coincidences

    events = [StoredEvent.model_validate(e) for e in run["events"]]
    final = replay(run["project_id"], events)
    checks["replay_final_state_equal"] = state_sha256(final) == run["final_state_sha256"]
    checks["replay_every_step_digest_equal"] = all(
        state_sha256(
            replay(run["project_id"], [e for e in events if e.sequence <= s["last_sequence"]])
        )
        == s["state_sha256"]
        for s in run["steps"]
    )
    outcome = FinalOutcome.model_validate(run["final_outcome"])
    answer = OutcomeAdjudicationAnswer.model_validate(
        meta["adjudicator_provider_records"][0]["output"]
    )
    rescored = score(outcome, oracle, to_adjudication(answer))
    checks["rescore_equals_sealed_report"] = rescored == report
    gates = preflight_gates(
        environ={"XAI_API_KEY": "-", "OPENAI_API_KEY": "-", "ANTHROPIC_API_KEY": "-"}
    )
    checks["seal_intact"] = gates["SEAL_INTACT"][0]
    checks["oracle_intact"] = gates["ORACLE_INTACT"][0]
    checks["consumed"] = not gates["UNCONSUMED"][0]
    usage = {
        "writer_input_tokens": sum(r["input_tokens"] for r in meta["writer_receipts"]),
        "writer_output_tokens": sum(r["output_tokens"] for r in meta["writer_receipts"]),
        "writer_cost_usd": round(sum(r["cost_usd"] for r in meta["writer_receipts"]), 4),
        "verifier_input_tokens": sum(
            c["answer"]["input_tokens"] or 0 for c in run["verifier_calls"]
        ),
        "verifier_output_tokens": sum(
            c["answer"]["output_tokens"] or 0 for c in run["verifier_calls"]
        ),
        "ie3_input_tokens": sum(r["input_tokens"] or 0 for r in meta["ie3_provider_records"]),
        "ie3_output_tokens": sum(r["output_tokens"] or 0 for r in meta["ie3_provider_records"]),
        "adjudicator_input_tokens": meta["adjudicator_provider_records"][0]["input_tokens"],
        "adjudicator_output_tokens": meta["adjudicator_provider_records"][0]["output_tokens"],
        "total_wall_clock_s": round(meta["total_wall_clock_s"], 1),
    }
    return {"checks": checks, "usage": usage}


if __name__ == "__main__":
    result = main()
    (OUT / "integrity.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
