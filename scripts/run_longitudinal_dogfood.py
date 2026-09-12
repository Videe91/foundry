"""9P entry point: the live incremental semantic assimilation dogfood (plan Task 16/19).

Not a product CLI. Two modes, one script:

    # Task 18 — seal the pre-run artifacts (no reasoner, no key, no call):
    uv run python scripts/run_longitudinal_dogfood.py --seal \\
        --frozen-sha <9P_IMPL_COMMIT> --out docs/superpowers/experiments/<dir>

    # Task 19 — the live run:
    XAI_API_KEY=... uv run python scripts/run_longitudinal_dogfood.py \\
        --frozen-sha <9P_SEAL_COMMIT> --out docs/superpowers/experiments/<dir>

Guarantees enforced here:

* The pre-run ``manifest.json`` and ``expectations.json`` must already exist in
  ``--out`` and no post-run file may; the expectations document is re-parsed and
  re-sealed and every ``integrity.preflight`` gate must pass — the adapter class is
  never bound or constructed before the gates (the name is resolved lazily inside
  ``_xai_reasoner_factory``). Any failed gate prints the gate table and exits 2. The
  runtime system-instruction digest and the runtime model-facing output-schema digest
  (``semantic_output_schema_sha256()``) are each compared with the value sealed in
  ``manifest.json`` (``prompt_hash_frozen``, ``output_schema_hash_frozen``).
* Every console line passes through ``redact_secrets`` (gate details, ``STOP -`` lines,
  failure text, prompts); a ``KeyboardInterrupt`` or ``EOFError`` at a human prompt is
  recorded as ``INTERRUPTED: <type>`` — the run is preserved, never lost (ruling R16-b).
* ``--seal`` refuses if any timeline evidence content carries a secret-shaped token.
* The API key is read from ``XAI_API_KEY`` only, after the gates, and is handed to the
  reasoner factory and nothing else. Empty or missing → ``XAI_API_KEY_NOT_AVAILABLE``,
  exit 2, no reasoner. It is never printed, logged, stored or placed in an artifact.
* Exactly one ``XAISemanticReasoner`` (imported lazily inside ``_xai_reasoner_factory``)
  serves Arm F then Arm R. The first ``FAILED`` frontier step ends every frontier call
  (9P-C-R2): if any Arm F step is ``FAILED`` — a raise, an interrupt, a halted
  authorization — Arm R is never started; every R T is written as a structural
  ``NOT_RUN`` record (``stopped: Arm F T<n> failed``) without touching the reasoner,
  and the run's failure text is ``Arm F T<n> failed: <error>`` (an interrupt at a
  prompt keeps R16-b's ``INTERRUPTED: <kind>`` text). Inside each arm the runner
  applies the same law to its own later T's; an Arm R failure at T<n> is recorded as
  ``Arm R T<n> failed: <error>`` with R T>n ``NOT_RUN`` and no metrics or verdicts.
  No retry, no fresh call after a failure. Root selections and authorizations are
  interactive on stdin:
  the selector is two-step — it shows the active address descriptors with ids and
  accepts only a listed id, then shows every active, applied ``ASSERT_CLAIM`` judgment
  at that address and accepts only a listed judgment id (ruling D: the architect names
  the old interpretation; the code never picks a claim). Nothing else is shown — no
  evidence, nothing from a later T. The authorizer shows the verbatim proposal and
  accepts only ``AGREE`` or ``DECLINE`` — anything else is re-prompted, never
  interpreted.
* The ``expectations.json`` designation slot is filled **live**, inside T1 after the
  A/B/CONTROL designations and before T2's ingest, through ``run_arm_f``'s
  ``on_t1_designations`` hook (ruling R16-a); it holds those three only. Track C's
  designation stays in ``persistent/result.json``.
* Every outcome — including a raise inside the run — is written as the immutable
  post-run artifact set with its status. Exit 0 iff the run status is ``COMPLETED``,
  else 1.

Evidence is read from the timeline commits via ``git show``, never from the working
tree. ``observed_at`` for every version is the harness load time (as in 9O); it is
ledger metadata only and never reaches the prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TextIO

from pydantic import ValidationError

from foundry.adapters.semantics.xai_reasoner import PROVIDER, semantic_output_schema_sha256
from foundry.application.assimilation_context import active_in_scope_addresses
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.semantic_identity import SemanticClaim
from foundry.domain.semantic_judgment import AssertClaimProposal, SemanticJudgment
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState
from foundry.experiments.intent_v2_dogfood import API_KEY_ENV, utc_now
from foundry.experiments.longitudinal.arm_f import ArmFResult, run_arm_f
from foundry.experiments.longitudinal.arm_r import ArmRStep, not_run_steps, run_arm_r
from foundry.experiments.longitudinal.artifacts import (
    ASSIMILATION_SCOPE,
    POST_RUN_FILES,
    PRE_RUN_FILES,
    READINESS_SCOPES,
    TIMELINE_PROJECT_ID,
    assemble_run,
    build_expectation_manifest,
    build_expectations_document,
    build_pre_run_manifest,
    contains_secret_shape,
    default_run_config,
    fill_t1_designation,
    redact_secrets,
    system_instruction_sha256,
    write_post_run_artifacts,
    write_pre_run_artifacts,
)
from foundry.experiments.longitudinal.authority import AuthorizationDecision
from foundry.experiments.longitudinal.derivations import RootSelection
from foundry.experiments.longitudinal.expectations import (
    ExpectationManifest,
    ExpectationVerdict,
    seal,
)
from foundry.experiments.longitudinal.integrity import RunConfig, all_passed, preflight
from foundry.experiments.longitudinal.scoring import (
    ScoringManifest,
    StructuralMetrics,
    deterministic_verdicts,
    structural_metrics,
)
from foundry.experiments.longitudinal.timeline import (
    VersionedEvidence,
    evidence_hashes,
    load_timeline,
)
from foundry.ports.semantic_reasoner import SemanticReasoner

ReasonerFactory = Callable[[str, RunConfig], SemanticReasoner]


class RepositoryGit(Protocol):
    """Blob reads from named commits plus HEAD and ``status --short``."""

    def blob(self, sha: str, path: str) -> bytes: ...

    def blob_sha(self, sha: str, path: str) -> str: ...

    def head(self) -> str: ...

    def dirty(self) -> str: ...


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


class _Stop(Exception):
    """A pre-run refusal; the message is printed and the exit code is 2."""


# --------------------------------------------------------------------------- interaction


class _Interrupted(Exception):
    """The human interrupted (Ctrl-C) or closed stdin at a prompt (ruling R16-b).

    Raised as an ``Exception`` so ``run_arm_f`` records the T it happened in as
    ``FAILED`` and returns its result; ``_Console.interrupted`` remembers it so the
    entry point stops before Arm R and preserves everything recorded so far.
    """


class _Console:
    """Every line printed passes through ``redact_secrets``; every prompt is interrupt-safe."""

    def __init__(self, stdin: TextIO, stdout: TextIO) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self.interrupted: str | None = None

    def say(self, text: str = "") -> None:
        print(redact_secrets(text), file=self._stdout, flush=True)

    def ask(self, prompt: str) -> str:
        self.say(prompt)
        try:
            line = self._stdin.readline()
        except (KeyboardInterrupt, EOFError) as exc:
            raise self._interrupt(type(exc).__name__) from None
        if line == "":
            raise self._interrupt("EOFError")
        return line.rstrip("\r\n")

    def _interrupt(self, kind: str) -> _Interrupted:
        self.interrupted = f"INTERRUPTED: {kind}"
        return _Interrupted(f"{self.interrupted} at a human prompt")


VALUE_RENDER_LIMIT = 200
"""Longest rendering of a claim value the selector prints; longer ones are truncated."""


def _render_value(claim: SemanticClaim) -> str:
    rendered = claim.value.model_dump_json()
    if len(rendered) > VALUE_RENDER_LIMIT:
        return rendered[:VALUE_RENDER_LIMIT] + "..."
    return rendered


def _active_assert_claims_at(state: IntentState, address_id: str) -> dict[str, SemanticClaim]:
    """Every active, applied ``ASSERT_CLAIM`` judgment at ``address_id``, keyed by judgment id.

    Pure lookup in applied (ledger) order — for display only; the order carries no
    preference and the human names the judgment explicitly.
    """
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    claims_by_judgment = {c.created_by_judgment_id: c for c in semantic.claims.values()}
    listed: dict[str, SemanticClaim] = {}
    for judgment_id in semantic.applied_judgment_ids:
        if judgment_id not in active:
            continue
        judgment = semantic.judgments.get(judgment_id)
        claim = claims_by_judgment.get(judgment_id)
        if judgment is None or claim is None:
            continue
        proposal = judgment.proposal
        if isinstance(proposal, AssertClaimProposal) and proposal.address_id == address_id:
            listed[judgment_id] = claim
    return listed


def _interactive_selector(
    console: _Console, label: str, scopes: tuple[str, ...]
) -> Callable[[IntentState], RootSelection]:
    """Two prompts: a listed active address id, then a listed ASSERT_CLAIM judgment id at it.

    Step 1 prints every active address (all readiness scopes) as
    ``id | subject | facet | scope`` and re-prompts on anything not listed. Step 2 prints
    every active, applied ``ASSERT_CLAIM`` judgment at the chosen address as
    ``judgment_id | claim_id | predicate | value | created_by_judgment_id`` (value
    rendering bounded to ``VALUE_RENDER_LIMIT`` characters) and re-prompts on anything
    not listed. Nothing else is shown. Both answers are returned verbatim.
    """

    def select(state: IntentState) -> RootSelection:
        addresses = {
            a.address_id: a for scope in scopes for a in active_in_scope_addresses(state, scope)
        }
        console.say(f"--- designate {label}: active addresses ---")
        for address_id in sorted(addresses):
            a = addresses[address_id]
            console.say(f"{address_id} | {a.subject} | {a.facet} | scope={list(a.scope)}")
        while True:
            address_id = console.ask(f"SELECT {label} address id:")
            if address_id in addresses:
                break
            console.say(f"unknown address id {address_id!r}; choose one of the ids listed above")
        claims = _active_assert_claims_at(state, address_id)
        console.say(f"--- designate {label}: active ASSERT_CLAIM judgments at {address_id} ---")
        for judgment_id, claim in claims.items():
            console.say(
                f"{judgment_id} | {claim.claim_id} | {claim.predicate} | {_render_value(claim)}"
                f" | {claim.created_by_judgment_id}"
            )
        while True:
            judgment_id = console.ask(f"SELECT {label} judgment id:")
            if judgment_id in claims:
                return RootSelection(address_id=address_id, judgment_id=judgment_id)
            console.say(f"unknown judgment id {judgment_id!r}; choose one of the ids listed above")

    return select


def _interactive_authorizer(
    console: _Console,
) -> Callable[[SemanticJudgment], AuthorizationDecision]:
    """Print the verbatim proposal; accept exactly ``AGREE`` or ``DECLINE``."""

    def authorize(pending: SemanticJudgment) -> AuthorizationDecision:
        console.say("--- pending SUPERSEDE proposal (verbatim) ---")
        console.say(pending.model_dump_json(indent=2))
        while True:
            answer = console.ask("AGREE or DECLINE (exactly; anything else is re-asked):")
            if answer == "AGREE":
                return AuthorizationDecision.AGREE
            if answer == "DECLINE":
                return AuthorizationDecision.DECLINE
            console.say("not a decision; answer exactly AGREE or DECLINE")

    return authorize


# --------------------------------------------------------------------------- reasoner


def _xai_reasoner_factory(api_key: str, config: RunConfig) -> SemanticReasoner:
    """Binds the adapter name only here, after every gate has passed; constructs it once."""
    from foundry.adapters.semantics.xai_reasoner import XAISemanticReasoner

    return XAISemanticReasoner(
        api_key=api_key, model=config.model, reasoning_effort=config.reasoning_effort
    )


# --------------------------------------------------------------------------- pre-run


def _load_timeline(git: RepositoryGit) -> tuple[VersionedEvidence, ...]:
    observed_at = utc_now()
    try:
        return load_timeline(
            git, project_id=TIMELINE_PROJECT_ID, observed_at_for=lambda _t: observed_at
        )
    except Exception as exc:  # noqa: BLE001 - reported, never retried
        raise _Stop(f"could not load the timeline: {type(exc).__name__}: {exc}") from exc


def _seal(args: argparse.Namespace, git: RepositoryGit, console: _Console) -> int:
    head = git.head()
    if head != args.frozen_sha:
        console.say(f"STOP - HEAD {head} != frozen sha {args.frozen_sha}")
        return 2
    out = Path(args.out)
    timeline = _load_timeline(git)
    tainted = [v.item.evidence_id for v in timeline if contains_secret_shape(v.item.content)]
    if tainted:
        console.say(f"STOP - timeline evidence carries a secret-shaped token: {tainted}")
        return 2
    config = default_run_config()
    hashes = evidence_hashes(timeline)
    prompt_sha = system_instruction_sha256()
    schema_sha = semantic_output_schema_sha256()
    expectations = build_expectation_manifest(
        frozen_code_sha=args.frozen_sha,
        timeline_hashes=hashes,
        prompt_sha=prompt_sha,
        schema_sha=schema_sha,
        config=config,
    )
    manifest = build_pre_run_manifest(
        frozen_code_sha=args.frozen_sha,
        timeline_hashes=hashes,
        prompt_sha=prompt_sha,
        schema_sha=schema_sha,
        config=config,
        expectations_sha=seal(expectations),
        scope=ASSIMILATION_SCOPE,
        scopes=READINESS_SCOPES,
    )
    write_pre_run_artifacts(out, manifest, build_expectations_document(expectations))
    console.say(f"sealed: {out} expectations_sha256={manifest['expectations_sha256']}")
    return 0


def _read_pre_run(out: Path) -> tuple[dict[str, Any], ExpectationManifest]:
    for name in PRE_RUN_FILES:
        if not (out / name).exists():
            raise _Stop(f"pre-run artifact missing: {out / name}")
    for name in POST_RUN_FILES:
        if (out / name).exists():
            raise _Stop(f"output directory already holds a recorded run artifact: {out / name}")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    try:
        expectations = ExpectationManifest.model_validate(
            json.loads((out / "expectations.json").read_text(encoding="utf-8"))
        )
    except ValidationError as exc:
        raise _Stop(f"expectations.json does not parse as ExpectationManifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise _Stop("manifest.json is not a JSON object")
    if expectations.t1_locus_designation is not None:
        raise _Stop("expectations.json designation slot is already filled; not a sealed pre-run")
    return manifest, expectations


def _run_config(manifest: dict[str, Any]) -> RunConfig:
    try:
        return RunConfig.model_validate(manifest["config"])
    except (KeyError, ValidationError) as exc:
        raise _Stop(f"manifest.json config is not a RunConfig: {exc}") from exc


def _gates(
    *,
    git: RepositoryGit,
    frozen_sha: str,
    manifest: dict[str, Any],
    expectations: ExpectationManifest,
    timeline: tuple[VersionedEvidence, ...],
    config: RunConfig,
    console: _Console,
) -> bool:
    results = preflight(
        git=git,
        frozen_sha=frozen_sha,
        manifest_sha=seal(expectations),
        expected_manifest_sha=str(manifest.get("expectations_sha256", "")),
        prompt_sha=system_instruction_sha256(),
        expected_prompt_sha=str(manifest.get("prompt_sha256", "")),
        schema_sha=semantic_output_schema_sha256(),
        expected_schema_sha=str(manifest.get("semantic_output_schema_sha256", "")),
        expected_evidence_hashes=tuple(
            {str(k): str(v) for k, v in entry.items()}
            for entry in manifest.get("timeline_hashes", ())
        ),
        timeline=timeline,
        config=config,
    )
    for result in results:
        console.say(f"gate {result.name}: {'PASS' if result.passed else 'FAIL'} - {result.detail}")
    return all_passed(results)


# --------------------------------------------------------------------------- the run


type _RunOutcome = tuple[
    ArmFResult | None,
    tuple[ArmRStep, ...],
    StructuralMetrics | None,
    tuple[ExpectationVerdict, ...],
    str | None,
]
"""F result, R steps, metrics, deterministic verdicts, failure text (None if nothing raised)."""


def _run(
    *,
    reasoner: SemanticReasoner,
    timeline: tuple[VersionedEvidence, ...],
    manifest: dict[str, Any],
    console: _Console,
    out: Path,
) -> _RunOutcome:
    scope = str(manifest.get("scope", ASSIMILATION_SCOPE))
    scopes = tuple(str(s) for s in manifest.get("scopes", READINESS_SCOPES))
    f: ArmFResult | None = None
    r: tuple[ArmRStep, ...] = ()
    metrics: StructuralMetrics | None = None
    verdicts: tuple[ExpectationVerdict, ...] = ()
    try:
        f = run_arm_f(
            reasoner=reasoner,
            timeline=timeline,
            policy=AdmissionPolicy(),
            clock=utc_now,
            id_factory=_mint,
            authorizer=_interactive_authorizer(console),
            designate_track_a=_interactive_selector(console, "TRACK A", scopes),
            designate_track_b=_interactive_selector(console, "TRACK B", scopes),
            designate_track_c=_interactive_selector(console, "TRACK C", scopes),
            designate_control=_interactive_selector(console, "CONTROL", scopes),
            scope=scope,
            scopes=scopes,
            on_t1_designations=lambda designations: fill_t1_designation(out, designations),
        )
        for step in f.steps:
            console.say(f"F T{step.t}: {step.status} judgments={len(step.judgment_ids)}")
        failed = next((step for step in f.steps if step.status == "FAILED"), None)
        if failed is not None:
            # 9P-C-R2: the first failed frontier step ends all frontier calls. Arm R is
            # not started; its records are structural NOT_RUN only, and no metrics or
            # verdicts are computed (they require both arms to have run). An interrupt
            # at a prompt (R16-b) is one such failure; it keeps its INTERRUPTED text.
            r = not_run_steps(timeline, f"stopped: Arm F T{failed.t} failed")
            for r_step in r:
                console.say(f"R T{r_step.t}: {r_step.status} ({r_step.error})")
            failure = console.interrupted or f"Arm F T{failed.t} failed: {failed.error}"
            return f, r, metrics, verdicts, failure
        r = run_arm_r(
            reasoner=reasoner,
            timeline=timeline,
            policy=AdmissionPolicy(),
            clock=utc_now,
            id_factory=_mint,
            scope=scope,
        )
        for r_step in r:
            console.say(f"R T{r_step.t}: {r_step.status} judgments={len(r_step.judgment_ids)}")
        r_failed = next((step for step in r if step.status == "FAILED"), None)
        if r_failed is not None:
            # 9P-C-R2 / R2-b: run_arm_r already left every later T NOT_RUN and made no
            # further call; the run is recorded as failed and no metrics or verdicts are
            # computed over a partially run arm.
            return f, r, metrics, verdicts, f"Arm R T{r_failed.t} failed: {r_failed.error}"
        metrics = structural_metrics(f, r, ScoringManifest())
        verdicts = deterministic_verdicts(metrics)
    except KeyboardInterrupt:  # a Ctrl-C outside a prompt (e.g. during a live call): preserve
        return f, r, metrics, verdicts, console.interrupted or "INTERRUPTED: KeyboardInterrupt"
    except Exception as exc:  # noqa: BLE001 - every failure is preserved, never retried
        return f, r, metrics, verdicts, f"{type(exc).__name__}: {exc}"
    return f, r, metrics, verdicts, None


def _mint(prefix: str) -> str:
    return f"{prefix}-{os.urandom(8).hex()}"


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    reasoner_factory: ReasonerFactory | None = None,
    git_factory: Callable[[Path], RepositoryGit] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="run_longitudinal_dogfood")
    parser.add_argument("--frozen-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--seal", action="store_true", help="write the pre-run artifacts only")
    args = parser.parse_args(argv)

    console = _Console(stdin or sys.stdin, stdout or sys.stdout)
    git = (git_factory or GitCli)(Path(args.repo_root))
    out = Path(args.out)

    try:
        if args.seal:
            return _seal(args, git, console)
        manifest, expectations = _read_pre_run(out)
        config = _run_config(manifest)
        timeline = _load_timeline(git)
    except _Stop as stop:
        console.say(f"STOP - {stop}")
        return 2
    except FileExistsError as exc:
        console.say(f"STOP - {exc}")
        return 2

    if not _gates(
        git=git,
        frozen_sha=args.frozen_sha,
        manifest=manifest,
        expectations=expectations,
        timeline=timeline,
        config=config,
        console=console,
    ):
        console.say("STOP - preflight gate failed; no reasoner constructed")
        return 2
    if config.provider != PROVIDER:
        console.say(f"STOP - provider {config.provider!r} is not {PROVIDER!r}; no second provider")
        return 2

    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        console.say("STOP - XAI_API_KEY_NOT_AVAILABLE")
        return 2
    reasoner = (reasoner_factory or _xai_reasoner_factory)(api_key, config)
    del api_key
    console.say(f"live run starting: frozen sha {args.frozen_sha}; ceilings from manifest")

    f, r, metrics, verdicts, failure = _run(
        reasoner=reasoner, timeline=timeline, manifest=manifest, console=console, out=out
    )
    run = assemble_run(
        frozen_code_sha=str(manifest.get("frozen_code_sha", "")),
        run_head_sha=args.frozen_sha,
        semantic_output_schema_sha256=str(manifest.get("semantic_output_schema_sha256", "")),
        f=f,
        r=r,
        metrics=metrics,
        verdicts=verdicts,
        failure=failure,
    )
    write_post_run_artifacts(out, run)
    if failure is not None:
        console.say(f"run raised: {failure}")
    console.say(f"run_status: {run.status}")
    console.say(f"artifacts: {out}")
    return 0 if run.status == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
