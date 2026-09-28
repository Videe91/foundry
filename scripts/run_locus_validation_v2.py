"""Locus validation v2 entry point (design §10).

    uv run python scripts/run_locus_validation_v2.py prepare
    GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation_v2.py preflight
    GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation_v2.py live
    uv run python scripts/run_locus_validation_v2.py evaluate
    uv run python scripts/run_locus_validation_v2.py finalize --adjudication <file>

``prepare`` writes the two sealed files into an empty experiment directory (clean tree
required; the manifest records HEAD as ``harness_sha``). The seal is the commit that adds
exactly those two files. ``preflight`` evaluates every gate and writes nothing. ``live``
re-runs the full preflight, refuses a consumed identity, reads ``XAI_API_KEY`` only after
every gate passed (never printing it), confirms ``grok-4.6`` by model metadata, guards the
reasoner's identity, then writes ``preflight.json`` (the consuming write) and runs the four
ledgers once; ``run.json`` is written exactly once. ``evaluate`` computes the structural
verdicts from ``run.json`` and writes the questions for the independent adjudicator.
``finalize`` records the adjudicator's answers and the single standing.

Exit codes: 0 ok; 2 refused (nothing written, not consumed); 3 a gate failed; 4 aborted
after consumption.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from foundry.adapters.semantics.xai_reasoner import XAILocusSemanticReasoner
from foundry.experiments.locus_validation_v2 import protocol
from foundry.experiments.locus_validation_v2.evaluation import evaluate
from foundry.experiments.locus_validation_v2.expectations import (
    CASES,
    SEMANTIC_QUESTIONS,
    expectations_document,
)
from foundry.experiments.locus_validation_v2.runner import RunRecord, run_validation
from foundry.experiments.locus_validation_v2.seal import (
    GitFacts,
    build_manifest,
    preflight_gates,
    sealed_json,
)
from foundry.experiments.longitudinal.artifacts import redact_secrets

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / protocol.EXPERIMENT_ARTIFACT_DIR
PACKAGE = ROOT / "src/foundry/experiments/locus_validation_v2"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_facts() -> GitFacts:
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD^")
    added = tuple(
        p for p in _git("diff", "--name-only", "--diff-filter=A", "HEAD^", "HEAD").splitlines() if p
    )
    changed = tuple(p for p in _git("diff", "--name-only", "HEAD^", "HEAD").splitlines() if p)
    return GitFacts(
        head_sha=head,
        head_parent_sha=parent,
        head_added_files=added,
        head_changed_files=changed,
        worktree_clean=_git("status", "--porcelain") == "",
    )


def _read(name: str) -> dict[str, Any] | None:
    path = OUT / name
    return json.loads(path.read_text()) if path.exists() else None


def _raw_present() -> tuple[str, ...]:
    return tuple(n for n in ("preflight.json", *protocol.RAW_FILE_NAMES) if (OUT / n).exists())


def _gates() -> tuple[Any, ...]:
    return preflight_gates(
        sealed_manifest=_read("manifest.json"),
        sealed_expectations=_read("expectations.json"),
        git=_git_facts(),
        grpc_dns_resolver=os.environ.get(protocol.GRPC_DNS_RESOLVER_ENV),
        raw_present=_raw_present(),
        package_dir=PACKAGE,
    )


def _prepare() -> int:
    if _git("status", "--porcelain"):
        print("REFUSED: working tree not clean")
        return 2
    if OUT.exists() and any(OUT.iterdir()):
        print(f"REFUSED: {OUT} is not empty; a seal is written once")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(
        sealed_json(build_manifest(harness_sha=_git("rev-parse", "HEAD")))
    )
    (OUT / "expectations.json").write_text(sealed_json(expectations_document()))
    print("prepared: commit exactly manifest.json and expectations.json as the seal")
    return 0


def _preflight() -> int:
    gates = _gates()
    for g in gates:
        print(f"  {'PASS' if g.passed else 'FAIL'}  {g.name}: {redact_secrets(g.detail)}")
    return 0 if all(g.passed for g in gates) else 3


def _confirm_model(api_key: str) -> None:
    import xai_sdk

    client = xai_sdk.Client(api_key=api_key)
    model = client.models.get_language_model(protocol.MODEL)
    if getattr(model, "name", None) != protocol.MODEL:
        raise RuntimeError(f"MODEL_UNAVAILABLE: {protocol.MODEL}")


def _live() -> int:
    if _raw_present():
        print("REFUSED: this experiment identity is consumed")
        return 2
    gates = _gates()
    if not all(g.passed for g in gates):
        for g in gates:
            if not g.passed:
                print(f"  FAIL  {g.name}: {redact_secrets(g.detail)}")
        return 3
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        print("REFUSED: XAI_API_KEY not set")
        return 2
    try:
        _confirm_model(api_key)
        inner = XAILocusSemanticReasoner(
            api_key=api_key, model=protocol.MODEL, reasoning_effort=protocol.REASONING_EFFORT
        )
    except Exception as exc:  # noqa: BLE001 - refused before consumption, redacted
        print(f"REFUSED: {redact_secrets(f'{type(exc).__name__}: {exc}')}")
        return 2
    del api_key
    (OUT / "preflight.json").write_text(
        sealed_json(
            {
                "frozen_sha": _git("rev-parse", "HEAD"),
                "gates": [g.model_dump(mode="json") for g in gates],
                "model_confirmed": protocol.MODEL,
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    try:
        run = run_validation(
            inner=inner,
            guard_identity=True,
            clock=lambda: datetime.now(UTC),
            id_factory=lambda prefix: f"{prefix}-{uuid4()}",
        )
    except Exception as exc:  # noqa: BLE001 - recorded, never retried
        print(f"ABORTED: {redact_secrets(f'{type(exc).__name__}: {exc}')}")
        return 4
    text = json.dumps(run.model_dump(mode="json"), indent=1, sort_keys=True, default=str)
    (OUT / "run.json").write_text(redact_secrets(text) + "\n")
    print(f"run {run.status}: {run.frontier_calls} calls, cost {run.provider_cost_usd} USD")
    return 0 if run.status == "COMPLETED" else 4


def _evaluate() -> int:
    run = RunRecord.model_validate(json.loads((OUT / "run.json").read_text()))
    results = evaluate(run)
    (OUT / "structural_verdicts.json").write_text(
        sealed_json({k: v.model_dump(mode="json") for k, v in results.items()})
    )
    (OUT / "adjudication_questions.json").write_text(
        sealed_json({"questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS]})
    )
    for k, v in results.items():
        print(
            f"  {'PASS' if v.passed else 'FAIL'}  {k}" + "".join(f"\n      {f}" for f in v.findings)
        )
    return 0


def _finalize(adjudication: Path) -> int:
    answers = json.loads(adjudication.read_text())
    structural = json.loads((OUT / "structural_verdicts.json").read_text())
    by_id = {a["id"]: a for a in answers["answers"]}
    missing = [q.id for q in SEMANTIC_QUESTIONS if q.id not in by_id]
    semantic_ok = not missing and all(by_id[q.id]["answer"] == "YES" for q in SEMANTIC_QUESTIONS)
    structural_ok = all(v["passed"] for v in structural.values())
    standing = (
        "LOCUS_POLICY_VALIDATED" if structural_ok and semantic_ok else "LOCUS_POLICY_NOT_VALIDATED"
    )
    cases = {
        c.id: structural[c.id]["passed"]
        and all(by_id.get(q, {}).get("answer") == "YES" for q in c.semantic)
        for c in CASES
    }
    (OUT / "verdicts.json").write_text(
        sealed_json(
            {
                "experiment_version": protocol.EXPERIMENT_VERSION,
                "structural_all_passed": structural_ok,
                "semantic_all_yes": semantic_ok,
                "semantic_missing": missing,
                "cases": cases,
                "adjudicator": answers.get("adjudicator"),
                "standing": standing,
            }
        )
    )
    print(standing)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "preflight", "live", "evaluate", "finalize"])
    parser.add_argument("--adjudication", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        return _prepare()
    if args.mode == "preflight":
        return _preflight()
    if args.mode == "live":
        return _live()
    if args.mode == "evaluate":
        return _evaluate()
    if args.adjudication is None:
        parser.error("finalize needs --adjudication")
    return _finalize(args.adjudication)


if __name__ == "__main__":
    sys.exit(main())
