"""Runtime holds: Call-2 work Foundry did not apply, and why (protocol ``ie2-runtime-holds-v1``).

A hold is recorded as a ``SemanticHoldGap``: an ordinary blocking ``Gap`` (one gap plane, read by
closure, resolvable and waivable like any other) that also carries its cause and what it is
about, structurally, so the cause can be closed deterministically and nothing reads prose:

* ``NOT_COMPLETE`` -- the independent verifier judged a proposition not fully preserved;
* ``VERIFIER_OUTPUT_INVALID`` / ``VERIFIER_NOT_INDEPENDENT`` -- its answer could not be used;
* ``VERIFICATION_UNAVAILABLE`` -- no verifier could be reached or selected, so no semantic
  judgement exists at all (never reported as NOT_COMPLETE);
* ``INVALID_CONFLICT_REFERENCE`` -- the response named a conflict with something that is not a
  current claim or a proposition of the response;
* ``CONFLICT`` -- the writer said a proposition conflicts with a current claim or with a
  sibling proposition, or the independent admission verifier (v4) found it conflicts with a
  current claim it was shown: a known contradiction, never left as two current truths. Both
  detecting it is one fact, one gap;
* ``UNCERTAIN`` -- the admission verifier could not tell whether a proposition can hold with
  the current claims: never applied, held as unresolved (an ``AMBIGUITY``) until the same work
  is later verified COMPLETE and NO_CONFLICT.

``basis`` is the stable identity of what was held: every (concern address, source sentence
sha256) pair the held propositions carry. ``resolution_key`` is its digest with the project and
the gap kind; it never depends on invocation, judgment or event ids, so the same requirement
held twice has the same key and a different concern never does.

No new ``GapKind`` exists: kinds are part of sealed model-facing contracts. A conflict is a
``CONTRADICTION``, an uncertain one an ``AMBIGUITY``, an unavailable verifier a
``CONTEXT_FAILURE`` (closed by later processing, the DERIVE route) and every other hold a
``WORKER_DIVERGENCE``; ``cause`` is the precise reason.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Final, Literal

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import Gap, GapKind

__all__ = [
    "HOLD_PROTOCOL",
    "HoldBasis",
    "HoldCause",
    "PropositionConflict",
    "SemanticHoldGap",
    "hold_kind",
    "hold_resolution_key",
    "sentence_sha256",
]

HOLD_PROTOCOL: Final = "ie2-runtime-holds-v1"

HoldCause = Literal[
    "NOT_COMPLETE",
    "VERIFIER_OUTPUT_INVALID",
    "VERIFIER_NOT_INDEPENDENT",
    "VERIFICATION_UNAVAILABLE",
    "INVALID_CONFLICT_REFERENCE",
    "CONFLICT",
    "UNCERTAIN",
]


def hold_kind(cause: HoldCause) -> GapKind:
    if cause == "CONFLICT":
        return GapKind.CONTRADICTION
    if cause == "VERIFICATION_UNAVAILABLE":
        return GapKind.CONTEXT_FAILURE
    if cause == "UNCERTAIN":
        return GapKind.AMBIGUITY
    return GapKind.WORKER_DIVERGENCE


class PropositionConflict(FrozenModel):
    """Call 2's statement that a proposition's claims conflict with a current claim or with
    another proposition of the same response. Not a disposition: the proposition still has
    exactly one."""

    proposition_id: str = Field(min_length=1)
    with_claim_id: str | None = Field(default=None, min_length=1)
    with_proposition_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_one_target(self) -> PropositionConflict:
        if (self.with_claim_id is None) == (self.with_proposition_id is None):
            raise ValueError("a conflict names exactly one claim or one sibling proposition")
        if self.with_proposition_id == self.proposition_id:
            raise ValueError("a proposition cannot conflict with itself")
        return self


class HoldBasis(FrozenModel):
    address_id: str = Field(min_length=1)
    sentence_sha256: str = Field(min_length=64, max_length=64)


class SemanticHoldGap(Gap):
    hold_protocol: Literal["ie2-runtime-holds-v1"]
    cause: HoldCause
    resolution_key: str = Field(min_length=1)
    subject_invocation_id: str = Field(min_length=1)
    basis: tuple[HoldBasis, ...]
    held_proposition_ids: tuple[str, ...]
    held_judgment_ids: tuple[str, ...]
    conflicting_claim_ids: tuple[str, ...] = ()

    @property
    def address_ids(self) -> tuple[str, ...]:
        return tuple(sorted({b.address_id for b in self.basis}))


def sentence_sha256(sentence: str) -> str:
    return hashlib.sha256(sentence.encode("utf-8")).hexdigest()


def hold_resolution_key(project_id: str, kind: GapKind, basis: Iterable[HoldBasis]) -> str:
    pairs = sorted({(b.address_id, b.sentence_sha256) for b in basis})
    canonical = json.dumps([project_id, kind.value, pairs], separators=(",", ":"))
    return "HOLD-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
