"""Sealed expectation manifest for the 9P longitudinal dogfood (spec §29, §34).

Expectation texts are copied verbatim from the spec §29 table. The manifest is
preregistered: it names loci and expectations only in prose and never carries a
runtime id (address, claim, judgment, invariant). Nothing in this module is ever
sent to a model.

Adjudication split (spec §29, §34):

* architect  — E1, E2, E3, E4, E5, E8, E9 (read against the ledger after the run)
* deterministic — E6, E7, E10, E11, E12 (computed from the ledger / view / replay)

E10 is a single expectation with two halves. The "no ``EQUIVALENT``/``DISTINCT``
was requested at any T" half is deterministic (read from the request log). The
"duplicate-address count for tracked loci is 0" half is architect-adjudicated,
because deciding that two addresses denote the same locus is a semantic judgement
(Global Constraint 1). The expectation keeps one id and the verbatim spec text; the
split is recorded in ``adjudication_note`` so the sealed manifest carries it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import Field, field_validator, model_validator

from foundry.domain.common import FrozenModel

# Reused so the seal is byte-identical canonical JSON with the frozen artifact pipeline;
# the transitive xAI import constructs no client and makes no network call.
from foundry.evaluation.experiment_manifest import canonical_json_bytes, sha256_bytes

Adjudicator = Literal["architect", "deterministic"]

EXPERIMENT_VERSION: Final = "intent-v2-longitudinal-assimilation-v2"

LOCKED_CEILINGS: Final[dict[str, int | float]] = {
    "max_frontier_calls": 16,
    "max_judge_calls": 0,
    "max_human_authorizations": 3,
    "per_track_authorizations": 1,
    "max_cost_usd": 8.0,
}

_REQUIRED_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {*LOCKED_CEILINGS, "model", "reasoning_effort", "policy_version"}
)

_TIMELINE_HASH_KEYS: Final[frozenset[str]] = frozenset(
    {"t", "artifact_ref", "commit", "git_blob_sha", "content_sha256"}
)

_SEAL_EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset({"t1_locus_designation"})


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Expectation(FrozenModel):
    id: str = Field(pattern=r"^E[1-9][0-9]*$")
    text: str = Field(min_length=1)
    t: str = Field(min_length=1)
    adjudicator: Adjudicator
    conditional: bool = False
    adjudication_note: str = ""


EXPECTATIONS: Final[tuple[Expectation, ...]] = (
    Expectation(
        id="E1",
        text="A and B exist as addresses after T1; C does not yet exist",
        t="T1",
        adjudicator="architect",
    ),
    Expectation(
        id="E2",
        text=(
            "at T2 the A- and B-related observations are **bound** to the T1 addresses, "
            "not created anew"
        ),
        t="T2",
        adjudicator="architect",
    ),
    Expectation(
        id="E3",
        text="at T2 a new claim at A (and at B) expresses the corrected interpretation",
        t="T2",
        adjudicator="architect",
    ),
    Expectation(
        id="E4",
        text="the T1 claims at A and B remain present in state after T2",
        t="T2",
        adjudicator="architect",
    ),
    Expectation(
        id="E5",
        text="the current view at A (and B) changes **only after** an authorized supersession",
        t="T2",
        adjudicator="architect",
    ),
    Expectation(
        id="E6",
        text="after supersession `stale_ids ⊇ {D-A1, D-A2, D-A3}`; the unrelated chain is clean",
        t="T2",
        adjudicator="deterministic",
    ),
    Expectation(
        id="E7",
        text=(
            "`intent-engine` readiness reports the stale descendants; `constitution` is unaffected"
        ),
        t="T2",
        adjudicator="deterministic",
    ),
    Expectation(
        id="E8",
        text=(
            "C exists after T3 with an INFERRED claim describing the observed (defective) behaviour"
        ),
        t="T3",
        adjudicator="architect",
    ),
    Expectation(
        id="E9",
        text=(
            "at T4 the corrected observation binds to C; a new claim and a `SUPERSEDE` of the "
            "T3 claim's judgment are proposed, not silently applied"
        ),
        t="T4",
        adjudicator="architect",
    ),
    Expectation(
        id="E10",
        text=(
            "no `EQUIVALENT`/`DISTINCT` was requested at any T; duplicate-address count for "
            "tracked loci is 0"
        ),
        t="all",
        adjudicator="deterministic",
        adjudication_note=(
            "The `EQUIVALENT`/`DISTINCT` half is deterministic (request log). The "
            "duplicate-address count half is architect-adjudicated: whether two addresses "
            "denote one tracked locus is a semantic judgement. One id, one verdict."
        ),
    ),
    Expectation(
        id="E11",
        text="replay of the F ledger reproduces state and view",
        t="end",
        adjudicator="deterministic",
    ),
    Expectation(
        id="E12",
        text=(
            "**applies only if at least one supersession is declined during the run.** Then: "
            "the affected scope's readiness reports the pending proposal, and no "
            "`CONFLICTS_WITH` appears in the ledger without a semantic-reasoner proposal"
        ),
        t="any",
        adjudicator="deterministic",
        conditional=True,
    ),
)

_EXPECTATIONS_BY_ID: Final[dict[str, Expectation]] = {e.id: e for e in EXPECTATIONS}

UNCONDITIONAL_EXPECTATION_IDS: Final[tuple[str, ...]] = tuple(
    e.id for e in EXPECTATIONS if not e.conditional
)
CONDITIONAL_EXPECTATION_IDS: Final[tuple[str, ...]] = tuple(
    e.id for e in EXPECTATIONS if e.conditional
)


class ExpectationVerdict(FrozenModel):
    id: str
    verdict: Verdict
    adjudicator: Adjudicator
    evidence_refs: tuple[str, ...]
    note: str = ""

    @field_validator("id")
    @classmethod
    def _known_expectation(cls, value: str) -> str:
        if value not in _EXPECTATIONS_BY_ID:
            msg = f"unknown expectation id {value!r}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _not_applicable_only_when_conditional(self) -> ExpectationVerdict:
        expectation = _EXPECTATIONS_BY_ID[self.id]
        if self.verdict is Verdict.NOT_APPLICABLE and not expectation.conditional:
            msg = f"{self.id} is unconditional and may only be PASS or FAIL"
            raise ValueError(msg)
        return self


class TrackedLocus(FrozenModel):
    key: Literal["A", "B", "C"]
    description: str = Field(min_length=1)
    t_introduced: int = Field(ge=1)


TRACKED_LOCI: Final[tuple[TrackedLocus, ...]] = (
    # Descriptions are exactly the spec §29 parentheticals: no before/after readings
    # ("no wording, no ids").
    TrackedLocus(
        key="A",
        description="referential status of admitted bindings",
        t_introduced=1,
    ),
    TrackedLocus(
        key="B",
        description="validation framing",
        t_introduced=1,
    ),
    TrackedLocus(
        key="C",
        description="identity of `Provenance.source_event_ids`",
        t_introduced=3,
    ),
)


class ExpectationManifest(FrozenModel):
    experiment_version: Literal["intent-v2-longitudinal-assimilation-v2"]
    frozen_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    timeline_hashes: tuple[dict[str, str], ...]
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    """Digest of the model-facing output contract (``semantic_output_schema_sha256()``)."""
    config: dict[str, Any]
    expectations: tuple[Expectation, ...]
    tracked_loci: tuple[TrackedLocus, ...]
    t1_locus_designation: dict[str, Any] | None = None

    @field_validator("timeline_hashes")
    @classmethod
    def _timeline_hashes_complete(
        cls, value: tuple[dict[str, str], ...]
    ) -> tuple[dict[str, str], ...]:
        for entry in value:
            missing = _TIMELINE_HASH_KEYS - entry.keys()
            if missing:
                msg = f"timeline hash entry missing keys {sorted(missing)}"
                raise ValueError(msg)
        return value

    @field_validator("config")
    @classmethod
    def _config_honours_locked_ceilings(cls, value: dict[str, Any]) -> dict[str, Any]:
        missing = _REQUIRED_CONFIG_KEYS - value.keys()
        if missing:
            msg = f"config missing keys {sorted(missing)}"
            raise ValueError(msg)
        for key, locked in LOCKED_CEILINGS.items():
            if value[key] != locked:
                msg = f"config[{key!r}] must equal locked ceiling {locked!r}, got {value[key]!r}"
                raise ValueError(msg)
        return value


def seal(manifest: ExpectationManifest) -> str:
    """Return the sha256 of the manifest's canonical JSON.

    ``t1_locus_designation`` is excluded from the sealed bytes. It is filled after
    T1 of the live run (the address ids that were minted for the A-root and the
    control root, the ledger sequence, and the designation time) so that later
    expectations can be adjudicated against concrete ids. Everything that can be
    fixed before the first live call is fixed before the first live call; the
    designation is the one field that cannot be, so the seal must be stable across
    it being filled. Otherwise the pre-run and post-run seals would differ and the
    manifest could not prove it was not edited between them.
    """
    payload = manifest.model_dump(mode="json", exclude=set(_SEAL_EXCLUDED_FIELDS))
    return sha256_bytes(canonical_json_bytes(payload))


class DecisionInputs(FrozenModel):
    verdicts: tuple[ExpectationVerdict, ...]
    f_input_tokens_t2_t4: int = Field(ge=0)
    r_input_tokens_t2_t4: int = Field(ge=0)
    f_material_errors: int = Field(ge=0)
    r_material_errors: int = Field(ge=0)
    declined_any: bool

    @field_validator("verdicts")
    @classmethod
    def _one_verdict_per_expectation(
        cls, value: tuple[ExpectationVerdict, ...]
    ) -> tuple[ExpectationVerdict, ...]:
        ids = [v.id for v in value]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            msg = f"duplicate verdicts for {duplicates}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _conditional_verdicts_match_precondition(self) -> DecisionInputs:
        """Spec §29/§34: a conditional verdict is NOT_APPLICABLE iff its precondition never arose.

        E12's precondition is a declined supersession, read from ``declined_any``. A
        NOT_APPLICABLE verdict alongside a decline, or a PASS/FAIL verdict without one,
        is not a truthful record and is rejected here so ``decision_rule`` only ever
        sees inputs that satisfy §34 literally.
        """
        for verdict in self.verdicts:
            if not _EXPECTATIONS_BY_ID[verdict.id].conditional:
                continue
            is_na = verdict.verdict is Verdict.NOT_APPLICABLE
            if is_na and self.declined_any:
                msg = (
                    f"{verdict.id} is NOT_APPLICABLE but a supersession was declined "
                    "(declined_any=True); its precondition arose so it must be PASS or FAIL"
                )
                raise ValueError(msg)
            if not is_na and not self.declined_any:
                msg = (
                    f"{verdict.id} is {verdict.verdict.value} but no supersession was declined "
                    "(declined_any=False); its precondition never arose so it must be "
                    "NOT_APPLICABLE"
                )
                raise ValueError(msg)
        return self


class DecisionOutcome(FrozenModel):
    result: Literal["PASS", "FAIL"]
    failing: tuple[str, ...]


def decision_rule(inputs: DecisionInputs) -> DecisionOutcome:
    """Spec §34 decision rule, preregistered.

    PASS iff E1–E9 hold ∧ E10, E11 hold ∧ (declined_any → E12 holds)
    ∧ F input tokens over T2–T4 < R input tokens over T2–T4
    ∧ F material errors ≤ R material errors.
    FAIL otherwise, naming every failing condition.

    A required expectation without a verdict is a failure named
    ``UNADJUDICATED:<id>``. E12 is required iff a supersession was declined;
    ``DecisionInputs`` guarantees its recorded verdict is consistent with that,
    so a ``NOT_APPLICABLE`` E12 here is always excluded from the conjunction.
    """
    by_id = {v.id: v for v in inputs.verdicts}
    failing: list[str] = []

    for expectation in EXPECTATIONS:
        required = not expectation.conditional or inputs.declined_any
        verdict = by_id.get(expectation.id)
        if verdict is None:
            if required:
                failing.append(f"UNADJUDICATED:{expectation.id}")
            continue
        if verdict.verdict is Verdict.NOT_APPLICABLE:
            continue
        if verdict.verdict is not Verdict.PASS:
            failing.append(expectation.id)

    if not inputs.f_input_tokens_t2_t4 < inputs.r_input_tokens_t2_t4:
        failing.append("TOKENS:F>=R")
    if inputs.f_material_errors > inputs.r_material_errors:
        failing.append("ERRORS:F>R")

    return DecisionOutcome(result="PASS" if not failing else "FAIL", failing=tuple(failing))
