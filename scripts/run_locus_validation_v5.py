"""Locus validation v5 entry point (design §10).

    uv run python scripts/run_locus_validation_v5.py prepare
    GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation_v5.py preflight
    GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation_v5.py model-check
    GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation_v5.py live
    uv run python scripts/run_locus_validation_v5.py evaluate
    uv run python scripts/run_locus_validation_v5.py finalize --adjudication <file>

``prepare`` writes the two sealed files into an empty experiment directory (clean tree
and a complete source-coverage map required; the manifest records HEAD as
``harness_sha``). The seal is the commit that adds exactly those two files.
``preflight`` evaluates every gate and writes nothing.
``model-check`` confirms ``grok-4.6`` by provider metadata and writes nothing (it does not
consume the experiment). ``live`` re-runs the full preflight, refuses a consumed identity,
reads ``XAI_API_KEY`` only after every gate passed (never printing it), confirms
``grok-4.6``, guards the reasoner's identity, then writes ``preflight.json`` (the consuming
write) and runs the five ledgers once in ``ExecutionMode.EXPERIMENT`` (one attempt per
semantic call; a structurally refused ledger is recorded and the walk continues; no
re-proposal); ``run.json`` is written exactly once. ``evaluate``
computes the structural verdicts from ``run.json`` and writes one adjudication file per
sealed question, holding that question and the frozen packet of its own ledger and
timepoint. ``finalize`` records the adjudicator's answers and the single standing.

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

from foundry.adapters.semantics.xai_reasoner import XAIReproposingSemanticReasoner
from foundry.experiments.locus_validation_v5 import protocol
from foundry.experiments.locus_validation_v5.adjudication import adjudication_bundle, standing
from foundry.experiments.locus_validation_v5.evaluation import CaseResult, evaluate, split_tally
from foundry.experiments.locus_validation_v5.expectations import (
    expectations_document,
    source_coverage_findings,
)
from foundry.experiments.locus_validation_v5.runner import RunRecord, run_validation
from foundry.experiments.locus_validation_v5.seal import (
    GitFacts,
    build_manifest,
    preflight_gates,
    sealed_json,
)
from foundry.experiments.longitudinal.artifacts import redact_secrets

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / protocol.EXPERIMENT_ARTIFACT_DIR
PACKAGE = ROOT / "src/foundry/experiments/locus_validation_v5"
QUESTIONS_DIR = OUT / "adjudication"


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
    gaps = source_coverage_findings()
    if gaps:
        print("REFUSED: source coverage is incomplete:\n  " + "\n  ".join(gaps))
        return 2
    if OUT.exists() and any(OUT.iterdir()):
        print(f"REFUSED: {OUT} is not empty; a seal is written once")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(
        sealed_json(build_manifest(harness_sha=_git("rev-parse", "HEAD"), package_dir=PACKAGE))
    )
    (OUT / "expectations.json").write_text(sealed_json(expectations_document()))
    print("prepared: commit exactly manifest.json and expectations.json as the seal")
    return 0


def _preflight() -> int:
    gates = _gates()
    for g in gates:
        print(f"  {'PASS' if g.passed else 'FAIL'}  {g.name}: {redact_secrets(g.detail)}")
    return 0 if all(g.passed for g in gates) else 3


def _confirm_model(api_key: str) -> str:
    import xai_sdk

    client = xai_sdk.Client(api_key=api_key)
    model = client.models.get_language_model(protocol.MODEL)
    name = getattr(model, "name", None)
    if name != protocol.MODEL:
        raise RuntimeError(f"MODEL_UNAVAILABLE: asked for {protocol.MODEL}, provider said {name!r}")
    return str(name)


def _model_check() -> int:
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        print("REFUSED: XAI_API_KEY not set")
        return 2
    try:
        name = _confirm_model(api_key)
    except Exception as exc:  # noqa: BLE001 - reported, redacted; nothing written
        print(f"MODEL_UNAVAILABLE: {redact_secrets(f'{type(exc).__name__}: {exc}')}")
        return 2
    print(f"model confirmed by provider metadata: {name}")
    return 0


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
        confirmed = _confirm_model(api_key)
        inner = XAIReproposingSemanticReasoner(
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
                "model_confirmed": confirmed,
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
    bundle = adjudication_bundle(run)
    QUESTIONS_DIR.mkdir(exist_ok=True)
    for item in bundle["items"]:
        (QUESTIONS_DIR / f"{item['id']}.json").write_text(sealed_json(item))
    for k, v in results.items():
        print(
            f"  {'PASS' if v.passed else 'FAIL'}  {k}" + "".join(f"\n      {f}" for f in v.findings)
        )
    print(f"split tally: {split_tally(results)}")
    return 0


def _finalize(adjudication: Path) -> int:
    answers = json.loads(adjudication.read_text())
    structural = {
        k: CaseResult.model_validate(v)
        for k, v in json.loads((OUT / "structural_verdicts.json").read_text()).items()
    }
    by_id = {a["id"]: a["answer"] for a in answers["answers"]}
    result = standing(structural, by_id)
    (OUT / "verdicts.json").write_text(
        sealed_json(
            {
                "experiment_version": protocol.EXPERIMENT_VERSION,
                **result.model_dump(mode="json"),
                "split_tally": split_tally(structural),
                "adjudicator": answers.get("adjudicator"),
            }
        )
    )
    print(result.standing)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=["prepare", "preflight", "model-check", "live", "evaluate", "finalize"]
    )
    parser.add_argument("--adjudication", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        return _prepare()
    if args.mode == "preflight":
        return _preflight()
    if args.mode == "model-check":
        return _model_check()
    if args.mode == "live":
        return _live()
    if args.mode == "evaluate":
        return _evaluate()
    if args.adjudication is None:
        parser.error("finalize needs --adjudication")
    return _finalize(args.adjudication)


if __name__ == "__main__":
    sys.exit(main())
