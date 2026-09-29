"""IE2 + IE3 long-horizon experiment entry point (design §6, §18).

    uv run python scripts/run_long_horizon_ie2_ie3.py prepare
    GRPC_DNS_RESOLVER=native uv run python scripts/run_long_horizon_ie2_ie3.py preflight
    GRPC_DNS_RESOLVER=native uv run python scripts/run_long_horizon_ie2_ie3.py model-check
    GRPC_DNS_RESOLVER=native uv run python scripts/run_long_horizon_ie2_ie3.py live
    uv run python scripts/run_long_horizon_ie2_ie3.py evaluate
    uv run python scripts/run_long_horizon_ie2_ie3.py finalize --adjudication <file>

``prepare`` writes the two sealed files into an empty experiment directory (clean tree and a
complete source-coverage map required; the manifest records HEAD as ``harness_sha``); the seal
is the commit adding exactly those two files. ``preflight`` evaluates every gate and writes
nothing. ``model-check`` confirms ``grok-4.6`` and ``gpt-6-astra`` by provider metadata and
writes nothing. ``live`` re-runs the full preflight, refuses a consumed identity, reads both
keys only after every gate passed (never printing them), confirms both models, guards both
identities, writes ``preflight.json`` (the consuming write), runs T1..T16 once and writes
``run.json`` once. ``evaluate`` computes the mechanical verdicts and writes one packet per
sealed question. ``finalize`` records the adjudicator's answers and the single standing.

Exit codes: 0 ok; 2 refused (nothing written, not consumed); 3 a gate failed; 4 aborted after
consumption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from foundry.adapters.semantics.xai_reasoner import XAIReproposingSemanticReasoner  # noqa: E402
from foundry.experiments.long_horizon_ie2_ie3 import protocol  # noqa: E402
from foundry.experiments.long_horizon_ie2_ie3.adjudication import (  # noqa: E402
    adjudication_bundle,
    standing,
)
from foundry.experiments.long_horizon_ie2_ie3.evaluation import (  # noqa: E402
    CheckResult,
    evaluate,
)
from foundry.experiments.long_horizon_ie2_ie3.expectations import (  # noqa: E402
    expectations_document,
    source_coverage_findings,
)
from foundry.experiments.long_horizon_ie2_ie3.ie3_runtime import (  # noqa: E402
    build_synthesizer,
    live_provider,
    registry_from_certificate,
)
from foundry.experiments.long_horizon_ie2_ie3.recording import (  # noqa: E402
    RunBudget,
    require_ie3_identity,
)
from foundry.experiments.long_horizon_ie2_ie3.runner import (  # noqa: E402
    RunRecord,
    run_experiment,
)
from foundry.experiments.long_horizon_ie2_ie3.seal import (  # noqa: E402
    GitFacts,
    build_manifest,
    preflight_gates,
    sealed_json,
)
from foundry.experiments.longitudinal.artifacts import redact_secrets  # noqa: E402

OUT = ROOT / protocol.EXPERIMENT_ARTIFACT_DIR
PACKAGE = ROOT / "src/foundry/experiments/long_horizon_ie2_ie3"
QUESTIONS_DIR = OUT / "adjudication"
CERTIFICATE = ROOT / protocol.IE3_CERTIFICATE_PATH
HISTORICAL_MANIFEST = ROOT / protocol.HISTORICAL_ARTIFACT_DIR / "manifest.json"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_facts() -> GitFacts:
    added = tuple(
        p for p in _git("diff", "--name-only", "--diff-filter=A", "HEAD^", "HEAD").splitlines() if p
    )
    changed = tuple(p for p in _git("diff", "--name-only", "HEAD^", "HEAD").splitlines() if p)
    ancestor = (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", protocol.ROOT_STALENESS_BOUNDARY_COMMIT, "HEAD"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )
    return GitFacts(
        head_sha=_git("rev-parse", "HEAD"),
        head_parent_sha=_git("rev-parse", "HEAD^"),
        head_added_files=added,
        head_changed_files=changed,
        worktree_clean=_git("status", "--porcelain") == "",
        boundary_commit_is_ancestor=ancestor,
    )


def _certificate_facts() -> tuple[str, str]:
    from tests.certification._intent_graph_exam import graph_certificate_standing

    data = CERTIFICATE.read_bytes()
    return hashlib.sha256(data).hexdigest(), graph_certificate_standing(json.loads(data))


def _read(name: str) -> dict[str, Any] | None:
    path = OUT / name
    return json.loads(path.read_text()) if path.exists() else None


def _raw_present() -> tuple[str, ...]:
    return tuple(n for n in ("preflight.json", *protocol.RAW_FILE_NAMES) if (OUT / n).exists())


def _gates() -> tuple[Any, ...]:
    cert_sha, cert_standing = _certificate_facts()
    return preflight_gates(
        sealed_manifest=_read("manifest.json"),
        sealed_expectations=_read("expectations.json"),
        git=_git_facts(),
        historical_manifest=json.loads(HISTORICAL_MANIFEST.read_text()),
        certificate_sha256=cert_sha,
        certificate_standing=cert_standing,
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


def _confirm_models(xai_key: str, openai_key: str) -> dict[str, str]:
    import openai
    import xai_sdk

    grok = xai_sdk.Client(api_key=xai_key).models.get_language_model(protocol.IE2_MODEL)
    grok_name = getattr(grok, "name", None)
    if grok_name != protocol.IE2_MODEL:
        raise RuntimeError(f"MODEL_UNAVAILABLE: {protocol.IE2_MODEL} -> {grok_name!r}")
    astra = openai.OpenAI(api_key=openai_key, max_retries=0).models.retrieve(protocol.IE3_MODEL)
    if astra.id != protocol.IE3_MODEL:
        raise RuntimeError(f"MODEL_UNAVAILABLE: {protocol.IE3_MODEL} -> {astra.id!r}")
    return {"ie2": str(grok_name), "ie3": str(astra.id), "ie3_owned_by": str(astra.owned_by)}


def _keys() -> tuple[str, str] | None:
    xai_key, openai_key = os.environ.get("XAI_API_KEY", ""), os.environ.get("OPENAI_API_KEY", "")
    if not xai_key or not openai_key:
        print("REFUSED: XAI_API_KEY and OPENAI_API_KEY must both be set")
        return None
    return xai_key, openai_key


def _model_check() -> int:
    keys = _keys()
    if keys is None:
        return 2
    try:
        confirmed = _confirm_models(*keys)
    except Exception as exc:  # noqa: BLE001 - reported, redacted; nothing written
        print(f"MODEL_UNAVAILABLE: {redact_secrets(f'{type(exc).__name__}: {exc}')}")
        return 2
    print(f"models confirmed by provider metadata: {confirmed}")
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
    keys = _keys()
    if keys is None:
        return 2
    xai_key, openai_key = keys
    budget = RunBudget()
    try:
        confirmed = _confirm_models(xai_key, openai_key)
        ie2 = XAIReproposingSemanticReasoner(
            api_key=xai_key,
            model=protocol.IE2_MODEL,
            reasoning_effort=protocol.IE2_REASONING_EFFORT,
        )
        require_ie3_identity()
        registry = registry_from_certificate(json.loads(CERTIFICATE.read_text()))
        synthesizer, recording = build_synthesizer(live_provider(openai_key), budget, registry)
    except Exception as exc:  # noqa: BLE001 - refused before consumption, redacted
        print(f"REFUSED: {redact_secrets(f'{type(exc).__name__}: {exc}')}")
        return 2
    del xai_key, openai_key, keys
    started = datetime.now(UTC)
    (OUT / "preflight.json").write_text(
        sealed_json(
            {
                "frozen_sha": _git("rev-parse", "HEAD"),
                "gates": [g.model_dump(mode="json") for g in gates],
                "models_confirmed": confirmed,
                "started_at": started.isoformat(),
            }
        )
    )
    try:
        run = run_experiment(
            ie2=ie2,
            ie3_synthesizer=synthesizer,
            ie3_calls=lambda: tuple(recording.records),
            budget=budget,
            guard_identity=True,
            clock=lambda: datetime.now(UTC),
            id_factory=lambda prefix: f"{prefix}-{uuid4()}",
        )
    except Exception as exc:  # noqa: BLE001 - recorded, never retried
        print(f"ABORTED: {redact_secrets(f'{type(exc).__name__}: {exc}')}")
        return 4
    finished = datetime.now(UTC)
    document = {
        **run.model_dump(mode="json"),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }
    text = json.dumps(document, indent=1, sort_keys=True, default=str)
    (OUT / "run.json").write_text(redact_secrets(text) + "\n")
    print(
        f"run {run.status}: IE2 {run.ie2_calls} calls ({run.ie2_cost_usd} USD), IE3 "
        f"{run.ie3_calls} calls, {run.human_authorizations} AGREEs, "
        f"{(finished - started).total_seconds():.0f} s; error {run.error}"
    )
    return 0 if run.status == "COMPLETED" else 4


def _load_run() -> RunRecord:
    raw = json.loads((OUT / "run.json").read_text())
    raw.pop("started_at", None)
    raw.pop("finished_at", None)
    return RunRecord.model_validate(raw)


def _evaluate() -> int:
    run = _load_run()
    result = evaluate(run)
    (OUT / "structural_verdicts.json").write_text(sealed_json(result.model_dump(mode="json")))
    bundle = adjudication_bundle(run)
    QUESTIONS_DIR.mkdir(exist_ok=True)
    for item in bundle["items"]:
        (QUESTIONS_DIR / f"{item['id']}.json").write_text(sealed_json(item))
    for name, check in result.checks.items():
        print(f"  {'PASS' if check.passed else 'FAIL'}  {name}"
              + "".join(f"\n      {f}" for f in check.findings[:12]))  # fmt: skip
    print(f"first divergence: {result.first_divergence}")
    return 0


def _finalize(adjudication: Path) -> int:
    answers = json.loads(adjudication.read_text())
    verdicts = json.loads((OUT / "structural_verdicts.json").read_text())
    checks = {k: CheckResult.model_validate(v) for k, v in verdicts["checks"].items()}
    by_id = {a["id"]: a["answer"] for a in answers["answers"]}
    result = standing(checks, by_id)
    (OUT / "verdicts.json").write_text(
        sealed_json(
            {
                "experiment_version": protocol.EXPERIMENT_VERSION,
                **result.model_dump(mode="json"),
                "first_divergence": verdicts.get("first_divergence"),
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
