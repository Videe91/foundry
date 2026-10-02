"""The seal of live end-to-end validation v2: what is frozen, and the gates before a live call.

A new lineage; the v1 seal is untouched. Beyond v1's contents, the manifest pins the provenance
routing law (and the harness module that implements it), the v5 replacement law and contract,
and the runner module (which adds the v5 silent-gap rule to the unchanged scorer).

``manifest`` states, by digest, everything the run depends on: the corpus and its ordered steps,
the preregistered founder decisions, the hidden oracle (sealed in its own file), the scorer and
its pass law, the adjudicator's schema and instruction, the role requirements and candidates,
every runtime and policy identity, the retry law and the call budget. ``preflight_gates`` refuse a
live run unless the seal on disk is exactly what the code would seal now, the oracle file is
intact, the founder's role binding is present and lawful, the provider keys are present, the
worktree is clean and the experiment has not run before. Nothing here calls a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from foundry.adapters.semantics.completeness_verifier import ADMISSION_V5_CONTRACT
from foundry.experiments.intent_engine_e2e.expectations import EXPECTED, ExpectedOutcome
from foundry.experiments.intent_engine_e2e.outcome import DefectCategory
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v1.adjudicator import (
    ADJUDICATOR_INSTRUCTION_SHA256,
    adjudicator_output_schema_sha256,
)
from foundry.experiments.intent_engine_live_v2 import protocol
from foundry.experiments.intent_engine_live_v2.roles import (
    CANDIDATES,
    ROLE_REQUIREMENTS,
    RoleBinding,
    binding_findings,
)
from foundry.experiments.intent_engine_live_v2.runner import LiveRunRecord
from foundry.experiments.long_horizon_ie2_ie3 import protocol as lh

__all__ = [
    "PASS_LAW",
    "REQUEST_PATH_MODULES",
    "leakage_findings",
    "load_oracle",
    "manifest",
    "oracle_document",
    "preflight_gates",
    "sealed_json",
    "write_raw",
    "write_seal",
]

PASS_LAW: Final = (
    "PASS only if every defect count is 0 (missing, invented, wrong current, stale, wrong "
    "correction target, contradictory current truths, authority bypass, declined change "
    "applied, silent gap, incorrect gap resolution, IE2->IE3 semantic mismatch, incorrect "
    "closure), IE3 was evaluated, and the adjudication covers the final state completely and "
    "certainly. An incomplete, uncertain, malformed or failed adjudication is NOT_VALIDATED; a "
    "structural defect is FAIL whatever the adjudication. The expected open contradiction gap "
    "(T07) is correct and keeps closure false; two contradictory current truths are a defect. "
    "Post-run human review is diagnostic only and never changes the sealed verdict. "
    "v2 adds one structural rule: a FAILED v5 completeness record must name recorded gaps. "
    "A routing stop (ambiguous or unexplained founder-decision routing) is NOT_VALIDATED."
)

REQUEST_PATH_MODULES: Final = (
    "src/foundry/experiments/intent_engine_e2e/scenario.py",
    "src/foundry/experiments/intent_engine_live_v2/harness.py",
    "src/foundry/experiments/intent_engine_live_v2/protocol.py",
    "src/foundry/experiments/intent_engine_live_v1/recording.py",
)
"""Everything the writer, verifier and IE3 can be reached through. None may import the oracle,
the scorer or the adjudicator."""

_FORBIDDEN_IMPORTS: Final = (
    "intent_engine_e2e.expectations",
    "intent_engine_e2e.outcome",
    "intent_engine_live_v1.adjudicator",
    "intent_engine_live_v1.seal",
    "intent_engine_live_v2.seal",
    "intent_engine_live_v2.runner",
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sealed_json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def oracle_document() -> dict[str, Any]:
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "oracle": EXPECTED.model_dump(mode="json"),
    }


def load_oracle() -> ExpectedOutcome:
    """The sealed oracle, read from its own file at evaluation time (never before)."""
    path = Path(protocol.EXPERIMENT_ARTIFACT_DIR) / "oracle.json"
    return ExpectedOutcome.model_validate(json.loads(path.read_text())["oracle"])


def _file_sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(*, harness_commit: str, fixes_commit: str = "") -> dict[str, Any]:
    corpus = SCENARIO.model_dump(mode="json")
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "artifact_format_version": protocol.ARTIFACT_FORMAT_VERSION,
        "fixes_commit": fixes_commit,
        "predecessor": protocol.PREDECESSOR,
        "routing": {
            "law": protocol.ROUTING_LAW,
            "module": "src/foundry/experiments/intent_engine_live_v2/harness.py",
            "module_sha256": _file_sha("src/foundry/experiments/intent_engine_live_v2/harness.py"),
        },
        "replacement": {"law": protocol.REPLACEMENT_LAW},
        "harness_commit": harness_commit,
        "question": (
            "After realistic requirements and changes over time, does Foundry end with the "
            "correct canonical understanding of what must become true?"
        ),
        "corpus": {
            "scenario_id": SCENARIO.scenario_id,
            "scope": SCENARIO.scope,
            "corpus_sha256": _sha(json.dumps(corpus, sort_keys=True, separators=(",", ":"))),
            "steps": [
                {
                    "position": i,
                    "step_id": s.step_id,
                    "concern": s.concern,
                    "artifact": s.artifact,
                    "supersedes_step": s.supersedes_step,
                    "text_sha256": _sha(s.text),
                }
                for i, s in enumerate(SCENARIO.steps, start=1)
            ],
        },
        "authority_decisions": [
            {"step_id": s.step_id, "decision": s.decision}
            for s in SCENARIO.steps
            if s.decision is not None
        ],
        "oracle": {
            "file": "oracle.json",
            "oracle_sha256": _sha(sealed_json(oracle_document())),
            "truths": len(EXPECTED.truths),
            "visible_to": ["OUTCOME_ADJUDICATOR at evaluation time only"],
        },
        "scorer": {
            "module": "src/foundry/experiments/intent_engine_e2e/outcome.py",
            "module_sha256": _file_sha("src/foundry/experiments/intent_engine_e2e/outcome.py"),
            "categories": [c.value for c in DefectCategory],
            "pass_law": PASS_LAW,
            "runner_module": "src/foundry/experiments/intent_engine_live_v2/runner.py",
            "runner_module_sha256": _file_sha(
                "src/foundry/experiments/intent_engine_live_v2/runner.py"
            ),
        },
        "adjudicator": {
            "policy_id": protocol.ADJUDICATOR_POLICY_ID,
            "policy_version": protocol.ADJUDICATOR_POLICY_VERSION,
            "task": protocol.ADJUDICATOR_TASK,
            "instruction_sha256": ADJUDICATOR_INSTRUCTION_SHA256,
            "output_schema": "OutcomeAdjudicationAnswer",
            "output_schema_sha256": adjudicator_output_schema_sha256(),
            "authority": "none: evaluation only",
        },
        "roles": {
            "requirements": [r.model_dump(mode="json") for r in ROLE_REQUIREMENTS],
            "candidates": [c.model_dump(mode="json") for c in CANDIDATES],
            "binding_file": protocol.ROLE_BINDING_FILE,
            "binding_decided_by": protocol.FOUNDER,
        },
        "identities": {
            "writer": {
                "policy_version": protocol.WRITER_POLICY_VERSION,
                "reasoner_class": protocol.WRITER_REASONER_CLASS,
                "prompt_sha256": protocol.WRITER_PROMPT_SHA256,
                "output_schema": protocol.WRITER_OUTPUT_SCHEMA,
                "output_schema_sha256": protocol.WRITER_OUTPUT_SCHEMA_SHA256,
                "correction_law": protocol.WRITER_CORRECTION_LAW,
            },
            "verifier": {
                "task": protocol.VERIFIER_TASK,
                "policy_id": ADMISSION_V5_CONTRACT.policy_id,
                "policy_version": ADMISSION_V5_CONTRACT.policy_version,
                "adapter_class": protocol.VERIFIER_ADAPTER_CLASS,
                "instruction_sha256": ADMISSION_V5_CONTRACT.instruction_sha256,
                "output_schema_sha256": ADMISSION_V5_CONTRACT.output_schema_sha256,
            },
            "ie3": {
                "provider": lh.IE3_PROVIDER,
                "model": lh.IE3_MODEL,
                "policy_id": lh.IE3_POLICY_ID,
                "policy_version": lh.IE3_POLICY_VERSION,
                "prompt_sha256": lh.IE3_PROMPT_SHA256,
                "canonical_schema_sha256": lh.IE3_CANONICAL_SCHEMA_SHA256,
                "wire_schema_sha256": lh.IE3_WIRE_SCHEMA_SHA256,
                "wire_schema_compiler": lh.IE3_WIRE_SCHEMA_COMPILER,
                "certificate": lh.IE3_CERTIFICATE_PATH,
                "certificate_sha256": lh.IE3_CERTIFICATE_SHA256,
            },
            "runtime": {
                "execution_mode": protocol.EXECUTION_MODE.value,
                "pipeline": protocol.PIPELINE,
                "hold_protocol": protocol.HOLD_PROTOCOL,
                "authority_protocol": protocol.AUTHORITY_PROTOCOL,
                "admission_policy": protocol.ADMISSION_POLICY,
                "project_id": protocol.PROJECT_ID,
                "founder": protocol.FOUNDER,
            },
        },
        "retry_law": protocol.RETRY_LAW,
        "budget": {
            "writer_calls_max": protocol.MAX_WRITER_CALLS_PER_STEP * len(SCENARIO.steps),
            "verifier_calls_max": protocol.MAX_VERIFIER_CALLS_PER_STEP * len(SCENARIO.steps),
            "ie3_calls_max": protocol.MAX_IE3_CALLS,
            "adjudicator_calls_max": protocol.MAX_ADJUDICATOR_CALLS,
            "writer_cost_usd_max": protocol.MAX_WRITER_COST_USD,
        },
        "preflight_tests": [
            "tests/unit/test_intent_engine_live_v2.py",
            "tests/unit/test_intent_engine_live_v2_routing.py",
            "tests/unit/test_semantic_admission_v5.py",
            "tests/unit/test_intent_engine_e2e_outcome.py",
            "tests/unit/test_intent_engine_e2e_harness.py",
        ],
    }


def leakage_findings() -> tuple[str, ...]:
    import ast

    out: list[str] = []
    for path in REQUEST_PATH_MODULES:
        tree = ast.parse(Path(path).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.endswith(_FORBIDDEN_IMPORTS)
            ):
                out.append(f"{path} imports {node.module}")
    return tuple(out)


def write_seal(*, harness_commit: str, fixes_commit: str = "") -> None:
    out = Path(protocol.EXPERIMENT_ARTIFACT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    (out / "oracle.json").write_text(sealed_json(oracle_document()))
    (out / "manifest.json").write_text(
        sealed_json(manifest(harness_commit=harness_commit, fixes_commit=fixes_commit))
    )


def write_raw(record: LiveRunRecord) -> None:  # pragma: no cover - live only
    out = Path(protocol.EXPERIMENT_ARTIFACT_DIR)
    (out / "run.json").write_text(sealed_json(record.model_dump(mode="json")))
    (out / "report.json").write_text(sealed_json(record.report.model_dump(mode="json")))


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def preflight_gates(
    *,
    environ: Mapping[str, str] | None = None,
    worktree_clean: bool | None = None,
) -> dict[str, tuple[bool, str]]:
    env = os.environ if environ is None else environ
    out = Path(protocol.EXPERIMENT_ARTIFACT_DIR)
    gates: dict[str, tuple[bool, str]] = {}
    sealed = out / "manifest.json"
    if sealed.exists():
        on_disk = json.loads(sealed.read_text())
        now = manifest(
            harness_commit=on_disk.get("harness_commit", ""),
            fixes_commit=on_disk.get("fixes_commit", ""),
        )
        gates["SEAL_INTACT"] = (on_disk == now, "the sealed manifest equals what the code seals")
    else:
        gates["SEAL_INTACT"] = (False, "no sealed manifest")
    oracle = out / "oracle.json"
    gates["ORACLE_INTACT"] = (
        oracle.exists() and oracle.read_text() == sealed_json(oracle_document()),
        "the sealed oracle equals the judge-only expectations",
    )
    leaks = leakage_findings()
    gates["NO_ORACLE_LEAK"] = (not leaks, "; ".join(leaks) or "request path is oracle-free")
    binding_path = out / protocol.ROLE_BINDING_FILE
    if binding_path.exists():
        findings = binding_findings(RoleBinding.model_validate_json(binding_path.read_text()))
        gates["ROLE_BINDING_LAWFUL"] = (not findings, "; ".join(findings) or "lawful")
    else:
        gates["ROLE_BINDING_LAWFUL"] = (False, "no founder role binding")
    missing = [k for k in ("XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY") if not env.get(k)]
    gates["CREDENTIALS_PRESENT"] = (not missing, ", ".join(missing) or "present")
    clean = (_git("status", "--porcelain") == "") if worktree_clean is None else worktree_clean
    gates["WORKTREE_CLEAN"] = (clean, "committed")
    gates["UNCONSUMED"] = (
        not any((out / name).exists() for name in protocol.RAW_FILE_NAMES),
        "the experiment has not run",
    )
    return gates
