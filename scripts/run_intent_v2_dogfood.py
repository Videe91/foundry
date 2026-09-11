"""Task 9O-B entry point: the first live Intent Intelligence v2 dogfood.

Not a product CLI. Usage:

    XAI_API_KEY=... uv run python scripts/run_intent_v2_dogfood.py \\
        --frozen-sha <9O_ADAPTER_COMMIT> --out docs/superpowers/experiments/<dir>

Guarantees enforced here:
* HEAD must equal --frozen-sha and the working tree must be clean; evidence is read
  from that commit via `git show`, never from the working tree.
* The API key is read from XAI_API_KEY only and is never printed, logged, stored or
  placed in an exception or artifact.
* Exactly one XAISemanticReasoner drives at most MAX_EXTERNAL_MODEL_CALLS calls.
  Every outcome - including failure - is written as an immutable artifact set.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from foundry.adapters.semantics.xai_reasoner import XAISemanticReasoner
from foundry.domain.admission import AdmissionPolicy
from foundry.experiments.intent_v2_dogfood import (
    API_KEY_ENV,
    load_frozen_evidence,
    run_dogfood,
    utc_now,
    write_artifacts,
)


class GitCli:
    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root

    def _run(self, *args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(self._root), *args], capture_output=True, check=True, text=False
        ).stdout.decode("utf-8")

    def blob(self, sha: str, path: str) -> bytes:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(self._root), "show", f"{sha}:{path}"],
            capture_output=True,
            check=True,
        ).stdout

    def blob_sha(self, sha: str, path: str) -> str:
        return self._run("rev-parse", f"{sha}:{path}").strip()

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

    def branch(self) -> str:
        return self._run("branch", "--show-current").strip()

    def dirty(self) -> str:
        return self._run("status", "--short").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_intent_v2_dogfood")
    parser.add_argument("--frozen-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)

    git = GitCli(Path(args.repo_root))
    head = git.head()
    if head != args.frozen_sha:
        print(f"STOP - HEAD {head} != frozen sha {args.frozen_sha}")
        return 2
    if git.dirty():
        print("STOP - working tree is not clean")
        return 2
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        print("STOP - XAI_API_KEY_NOT_AVAILABLE")
        return 3
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"STOP - output directory already holds a recorded run: {out}")
        return 2

    evidence = load_frozen_evidence(git, args.frozen_sha, observed_at=utc_now())
    reasoner = XAISemanticReasoner(api_key=api_key)
    del api_key
    print(f"frozen sha: {args.frozen_sha}")
    print(f"evidence items: {len(evidence)}")
    print("live run starting: max 3 external calls, no retries")

    run = run_dogfood(
        reasoner=reasoner,
        evidence=evidence,
        policy=AdmissionPolicy(),
        clock=utc_now,
        id_factory=lambda prefix: f"{prefix}-{os.urandom(8).hex()}",
        frozen_sha=args.frozen_sha,
        branch=git.branch(),
    )
    write_artifacts(out, run)
    r = run.result
    print(f"run_status: {r.run_status}")
    for stage in r.stages:
        print(
            f"  {stage.stage}: {stage.status} judgments={len(stage.judgment_ids)} "
            f"addresses+={len(stage.addresses_created)} claims+={len(stage.claims_created)} "
            f"tokens={stage.input_tokens}/{stage.output_tokens} cost={stage.cost_usd:.6f}"
        )
    print(f"external calls: {r.actual_external_call_count}")
    print(f"total cost: {r.total_cost_usd:.6f} USD")
    print(f"replay: {r.replay.status}")
    print(f"artifacts: {out}")
    return 0 if r.run_status == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
