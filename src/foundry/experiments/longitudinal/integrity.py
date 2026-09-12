"""Experiment integrity gates for the 9P longitudinal dogfood (spec §28, §31, §32; plan Task 15).

``preflight`` evaluates every gate before a reasoner is constructed and returns one
``GateResult`` per gate in a fixed order. A gate never raises: a gate that cannot be
evaluated is a failed gate whose ``detail`` carries the reason. The entry point (Task 16)
stops before the first live call unless ``all_passed`` holds.

Gates and the failure modes they guard (spec §32):

* ``head_equals_frozen_sha``, ``worktree_clean`` — the live phase starts from the frozen
  commit with a clean tree (Global Constraint 16).
* ``manifest_hash_frozen``, ``prompt_hash_frozen``, ``output_schema_hash_frozen``,
  ``evidence_hashes_frozen`` — the manifest seal, the system-instruction digest, the
  model-facing output-schema digest (``semantic_output_schema_sha256()`` of the exact
  ``SemanticDraftPayload`` contract supplied as ``response_format``) and every evidence
  version's hashes equal what was sealed before the run (§32 #12, #15).
* ``call_ceiling_is_16``, ``cost_ceiling_is_8``, ``human_ceiling_is_3``,
  ``judge_calls_zero`` — the run configuration equals the preregistered ceilings in
  ``expectations.LOCKED_CEILINGS`` (§31). Equality, not ``<=``: a smaller ceiling is a
  different experiment.
* ``xai_retries_disabled`` — the adapter constructs its client with
  ``grpc.enable_retries=0`` (§32 #14). The adapter exposes no constant for this; the
  gate reads the adapter's ``__init__`` source rather than restating the literal.
* ``no_tracked_locus_leakage`` — no tracked-locus description and no expectation id or
  text appears in HARNESS-AUTHORED prompt text (§28, §32 #15; ruling R15-a). The gate
  exists to catch the harness telling the model what is tracked, so it scans the system
  instruction plus every planned request skeleton rendered through the real assembly
  functions with an empty semantic state (the pre-run shape: Call 1 can only
  ``CREATE``, Call 2 sees no known claims) for both arms at every T, carrying the real
  timeline evidence ids, ``source_ref``s, scopes and lineage — but with each item's
  ``content`` replaced by a fixed placeholder. Evidence bytes are immutable history the
  model must see; a tracked phrase inside them is the evidence, not a leak. Because
  evidence is excluded, descriptions and expectation texts are matched
  case-insensitively; expectation ids are matched word-bounded.
* ``persistent_delta_has_no_unchanged_evidence`` — Arm F never re-reads bytes already
  sent at an earlier T (§32 #13).
* ``reconstruction_corpus_is_cumulative`` — Arm R at T receives every version with step
  ``<= T`` in timeline order (§32 #12).

Nothing here originates a semantic conclusion. Git is injected behind ``GitCliLike``;
this module never shells out and never constructs a provider client.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable
from typing import Final, Protocol

from pydantic import Field

from foundry.adapters.semantics.xai_reasoner import (
    SYSTEM_INSTRUCTION,
    ReasoningEffort,
    XAISemanticReasoner,
    render_request,
)
from foundry.application.assimilation_context import (
    assemble_assimilation_request,
    assemble_claim_request,
)
from foundry.domain.common import FrozenModel
from foundry.domain.evidence import EvidenceItem, sha256_of_content
from foundry.domain.state import IntentState
from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    LOCKED_CEILINGS,
    TRACKED_LOCI,
)
from foundry.experiments.longitudinal.timeline import (
    VersionedEvidence,
    evidence_hashes,
    persistent_delta,
    reconstruction_corpus,
)

GATE_NAMES: Final[tuple[str, ...]] = (
    "head_equals_frozen_sha",
    "worktree_clean",
    "manifest_hash_frozen",
    "prompt_hash_frozen",
    "output_schema_hash_frozen",
    "evidence_hashes_frozen",
    "call_ceiling_is_16",
    "cost_ceiling_is_8",
    "human_ceiling_is_3",
    "judge_calls_zero",
    "xai_retries_disabled",
    "no_tracked_locus_leakage",
    "persistent_delta_has_no_unchanged_evidence",
    "reconstruction_corpus_is_cumulative",
)

_SKELETON_PROJECT_ID: Final = "preflight"
"""Never rendered into the prompt (``render_request`` omits ``project_id``)."""

_CONTENT_PLACEHOLDER: Final = "<evidence content excluded from leakage scan>"
"""Stands in for evidence bytes in leakage skeletons (ruling R15-a)."""

_RETRY_OPTION: Final = re.compile(r'"grpc\.enable_retries"\s*,\s*(\d+)')


class GitCliLike(Protocol):
    """What the gates need from Git: HEAD and ``status --short`` (empty when clean)."""

    def head(self) -> str: ...

    def dirty(self) -> str: ...


class GateResult(FrozenModel):
    name: str = Field(min_length=1)
    passed: bool
    detail: str


class RunConfig(FrozenModel):
    """The run's declared ceilings and model settings, compared against the locked values."""

    max_frontier_calls: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0)
    max_human_authorizations: int = Field(ge=0)
    max_judge_calls: int = Field(ge=0)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: ReasoningEffort


_Gate = Callable[[], tuple[bool, str]]


def preflight(
    *,
    git: GitCliLike,
    frozen_sha: str,
    manifest_sha: str,
    expected_manifest_sha: str,
    prompt_sha: str,
    expected_prompt_sha: str,
    schema_sha: str,
    expected_schema_sha: str,
    expected_evidence_hashes: tuple[dict[str, str], ...],
    timeline: tuple[VersionedEvidence, ...],
    config: RunConfig,
) -> tuple[GateResult, ...]:
    """Evaluate every gate in ``GATE_NAMES`` order. Never raises."""
    gates: dict[str, _Gate] = {
        "head_equals_frozen_sha": lambda: _equal("HEAD", git.head(), frozen_sha),
        "worktree_clean": lambda: _worktree_clean(git.dirty()),
        "manifest_hash_frozen": lambda: _equal("manifest sha", manifest_sha, expected_manifest_sha),
        "prompt_hash_frozen": lambda: _equal("prompt sha", prompt_sha, expected_prompt_sha),
        "output_schema_hash_frozen": lambda: _equal(
            "output schema sha", schema_sha, expected_schema_sha
        ),
        "evidence_hashes_frozen": lambda: _evidence_hashes_frozen(
            timeline, expected_evidence_hashes
        ),
        "call_ceiling_is_16": lambda: _ceiling("max_frontier_calls", config.max_frontier_calls),
        "cost_ceiling_is_8": lambda: _ceiling("max_cost_usd", config.max_cost_usd),
        "human_ceiling_is_3": lambda: _ceiling(
            "max_human_authorizations", config.max_human_authorizations
        ),
        "judge_calls_zero": lambda: _ceiling("max_judge_calls", config.max_judge_calls),
        "xai_retries_disabled": _xai_retries_disabled,
        "no_tracked_locus_leakage": lambda: _no_tracked_locus_leakage(timeline),
        "persistent_delta_has_no_unchanged_evidence": lambda: _delta_excludes_unchanged(timeline),
        "reconstruction_corpus_is_cumulative": lambda: _corpus_is_cumulative(timeline),
    }
    return tuple(_evaluate(name, gates[name]) for name in GATE_NAMES)


def all_passed(results: Iterable[GateResult]) -> bool:
    """True iff there is at least one result and every result passed."""
    results = tuple(results)
    return bool(results) and all(r.passed for r in results)


# --------------------------------------------------------------------------- evaluation


def _evaluate(name: str, gate: _Gate) -> GateResult:
    try:
        passed, detail = gate()
    except Exception as exc:  # noqa: BLE001 - a gate that cannot run is a failed gate
        return GateResult(name=name, passed=False, detail=f"could not evaluate: {_safe(exc)}")
    return GateResult(name=name, passed=passed, detail=detail)


def _equal(label: str, actual: str, expected: str) -> tuple[bool, str]:
    if actual == expected:
        return True, f"{label} {actual}"
    return False, f"{label} {actual!r} != expected {expected!r}"


def _worktree_clean(status: str) -> tuple[bool, str]:
    if status.strip() == "":
        return True, "worktree clean"
    return False, f"worktree dirty:\n{status.strip()}"


def _evidence_hashes_frozen(
    timeline: tuple[VersionedEvidence, ...], expected: tuple[dict[str, str], ...]
) -> tuple[bool, str]:
    recomputed = evidence_hashes(timeline)
    if len(recomputed) != len(expected):
        return False, f"{len(recomputed)} versions loaded, {len(expected)} sealed"
    for index, (actual, sealed) in enumerate(zip(recomputed, expected, strict=True)):
        if actual != sealed:
            return False, f"index {index}: loaded {actual} != sealed {sealed}"
    return True, f"{len(recomputed)} evidence versions match the sealed hashes"


def _ceiling(key: str, actual: int | float) -> tuple[bool, str]:
    locked = LOCKED_CEILINGS[key]
    if actual == locked:
        return True, f"config.{key}={actual} == LOCKED_CEILINGS[{key!r}]={locked}"
    return False, f"config.{key}={actual} != LOCKED_CEILINGS[{key!r}]={locked}"


def _adapter_init_source() -> str:
    return inspect.getsource(XAISemanticReasoner.__init__)


def _xai_retries_disabled() -> tuple[bool, str]:
    values = _RETRY_OPTION.findall(_adapter_init_source())
    if not values:
        return False, "XAISemanticReasoner.__init__ sets no grpc.enable_retries channel option"
    if any(value != "0" for value in values):
        return False, f"XAISemanticReasoner.__init__ sets grpc.enable_retries={values}"
    return True, "XAISemanticReasoner.__init__ sets grpc.enable_retries=0"


# --------------------------------------------------------------------------- leakage


def _wordings(text: str) -> tuple[str, ...]:
    """The sealed wording and, when it carries markdown backticks, the same with none (R15-b)."""
    stripped = text.replace("`", "")
    return (text,) if stripped == text else (text, stripped)


def _needles() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Case-insensitive locus descriptions and expectation texts; word-bounded expectation ids.

    Descriptions and texts are compiled both verbatim and with backticks removed so that
    harness text quoting ``Provenance.source_event_ids`` without markdown is still caught.
    """
    needles: list[tuple[str, re.Pattern[str]]] = []
    for locus in TRACKED_LOCI:
        label = f"locus {locus.key} description {locus.description!r}"
        for wording in _wordings(locus.description):
            needles.append((label, re.compile(re.escape(wording), re.IGNORECASE)))
    for expectation in EXPECTATIONS:
        id_pattern = re.compile(rf"\b{re.escape(expectation.id)}\b")
        needles.append((f"expectation id {expectation.id}", id_pattern))
        for wording in _wordings(expectation.text):
            text_pattern = re.compile(re.escape(wording), re.IGNORECASE)
            needles.append((f"expectation {expectation.id} text", text_pattern))
    return tuple(needles)


_NEEDLES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = _needles()


def _without_content(item: EvidenceItem) -> EvidenceItem:
    """The same item with its bytes replaced by the placeholder; structure and lineage kept."""
    return item.model_copy(
        update={
            "content": _CONTENT_PLACEHOLDER,
            "content_sha256": sha256_of_content(_CONTENT_PLACEHOLDER),
        }
    )


def _request_skeletons(
    timeline: tuple[VersionedEvidence, ...],
) -> tuple[tuple[str, str], ...]:
    """Every planned (arm, T, call) request, rendered with evidence bytes excluded."""
    state = IntentState(project_id=_SKELETON_PROJECT_ID)
    rendered: list[tuple[str, str]] = []
    for t in sorted({v.t for v in timeline}):
        arm_inputs = (
            ("F", tuple(_without_content(i) for i in persistent_delta(timeline, t))),
            ("R", tuple(_without_content(i) for i in reconstruction_corpus(timeline, t))),
        )
        for arm, items in arm_inputs:
            for scope in sorted({s for item in items for s in item.scope}):
                call1 = assemble_assimilation_request(
                    project_id=_SKELETON_PROJECT_ID, delta=items, state=state, scope=scope
                )
                rendered.append((f"{arm}/T{t}/call1[{scope}]", render_request(call1)))
            call2 = assemble_claim_request(
                project_id=_SKELETON_PROJECT_ID, delta=items, state=state, neighborhood=()
            )
            rendered.append((f"{arm}/T{t}/call2", render_request(call2)))
    return tuple(rendered)


def _no_tracked_locus_leakage(timeline: tuple[VersionedEvidence, ...]) -> tuple[bool, str]:
    haystacks = (("system_instruction", SYSTEM_INSTRUCTION), *_request_skeletons(timeline))
    offenders = list(
        dict.fromkeys(
            f"{label}: {what}"
            for label, text in haystacks
            for what, pattern in _NEEDLES
            if pattern.search(text)
        )
    )
    scanned = ", ".join(label for label, _ in haystacks)
    if offenders:
        return False, f"scanned {scanned}; offenders: " + "; ".join(offenders)
    return True, f"no tracked description or expectation in {scanned}"


# --------------------------------------------------------------------------- arm inputs


def _delta_excludes_unchanged(timeline: tuple[VersionedEvidence, ...]) -> tuple[bool, str]:
    offenders: list[str] = []
    for t in sorted({v.t for v in timeline}):
        sent_before = {(v.artifact_ref, v.content_sha256) for v in timeline if v.t < t}
        for item in persistent_delta(timeline, t):
            if (item.artifact_ref, item.content_sha256) in sent_before:
                offenders.append(f"T{t}:{item.evidence_id}")
    if offenders:
        return False, "Arm F would re-read unchanged evidence: " + ", ".join(offenders)
    return True, "Arm F delta at every T excludes bytes sent at an earlier T"


def _corpus_is_cumulative(timeline: tuple[VersionedEvidence, ...]) -> tuple[bool, str]:
    for t in sorted({v.t for v in timeline}):
        expected = tuple(v.item for v in timeline if v.t <= t)
        actual = reconstruction_corpus(timeline, t)
        if actual != expected:
            return False, (
                f"T{t}: Arm R corpus {_ids(actual)} != every version <= T{t} in timeline "
                f"order {_ids(expected)}"
            )
    return True, "Arm R corpus at every T is every version <= T in timeline order"


def _ids(items: tuple[EvidenceItem, ...]) -> list[str]:
    return [item.evidence_id for item in items]


def _safe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


__all__ = [
    "GATE_NAMES",
    "GateResult",
    "GitCliLike",
    "RunConfig",
    "all_passed",
    "preflight",
]
