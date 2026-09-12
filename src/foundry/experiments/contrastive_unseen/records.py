"""Exact per-call request recording for the 9P2 unseen-lifecycle experiment (spec §17.3).

``RecordingReasoner`` wraps the arm's ``SemanticReasoner`` and, for every ``propose``,
renders the request through the frozen ``render_request`` exactly as the arm's adapter
would (five-key with ``comparison_context`` for F/R, historical four-key for A),
hashes the UTF-8 bytes, records the structural ids the request carried, and only then
delegates. It never changes the request, never touches the returned judgments, and
never retries: within one step (``begin_step(t)``) a third ``propose`` is refused
BEFORE delegation, so the frontier never sees it. A record is appended before the
inner call and kept if that call raises -- the request was rendered, and that is
evidence.

Law of this module: it records structural facts only (ids, hashes, counts, kinds) and
decides nothing about meaning. It is a request-path module: it must never import
``expectations`` (the sealed answer key), and it must never construct a provider
client -- the inner reasoner is supplied by the caller. No API key, header, or secret
is ever recorded; the record holds only what the model itself was shown.

Controller Ruling 4: ``inner``, ``receipts`` and ``draft_payloads`` are exposed so the
runner and artifact layers can reach adapter economics through the wrapper without
knowing whether the inner reasoner (a live adapter or a scripted fake) has them.

Observed identity (whole-branch review Finding 2): the policy version and prompt hash a
record carries are the arm's expected values, so construction REFUSES an inner reasoner
that does not observably match them -- its ``fingerprint.policy_version`` must equal the
arm's policy, and when its class carries ``include_comparison_context`` /
``system_instruction`` (the real adapters do, as class attributes) those must equal the
arm's flag and hash the arm's prompt SHA. A reasoner without those class attributes is
accepted on its fingerprint alone. The check runs once, at wrapping, before any call.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final, Literal

from pydantic import Field

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION_SHA256,
    render_request,
)
from foundry.application.contrastive_context import (
    comparison_context_character_count,
    historical_evidence_ids,
)
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "CALLS_PER_STEP",
    "Arm",
    "RecordingReasoner",
    "RequestRecord",
    "require_reasoner_identity",
]

Arm = Literal["F", "A", "R"]

CALLS_PER_STEP: Final[int] = 2
"""Exactly two frontier calls per (arm, T); the third is refused before delegation."""


class RequestRecord(FrozenModel):
    """Spec §17.3 per-call record: exactly what the model was shown, structurally."""

    arm: Arm
    t: int
    call_number: Literal[1, 2]
    policy_version: str = Field(min_length=1)
    system_prompt_sha256: str = Field(min_length=64, max_length=64)
    rendered_user_request: str
    request_sha256: str = Field(min_length=64, max_length=64)
    citable_evidence_ids: tuple[str, ...]
    historical_comparison_evidence_ids: tuple[str, ...]
    known_address_ids: tuple[str, ...]
    known_claim_ids: tuple[str, ...]
    allowed_judgment_kinds: tuple[str, ...]
    comparison_context_chars: int = Field(ge=0)


def _arm_identity(arm: Arm) -> tuple[str, str, bool]:
    """(policy version, system prompt sha256, include_comparison_context) for ``arm``."""
    if arm == "A":
        return POLICY_VERSION, SYSTEM_INSTRUCTION_SHA256, False
    return CONTRASTIVE_POLICY_VERSION, CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256, True


def require_reasoner_identity(inner: SemanticReasoner, *, arm: Arm) -> None:
    """Raise ``RuntimeError("REASONER_IDENTITY_MISMATCH: ...")`` unless ``inner``
    observably is the arm's policy: fingerprint policy version always; class-level
    ``include_comparison_context`` and ``system_instruction`` when the class has them."""
    policy_version, prompt_sha256, include_context = _arm_identity(arm)
    observed_policy = inner.fingerprint.policy_version
    if observed_policy != policy_version:
        raise RuntimeError(
            f"REASONER_IDENTITY_MISMATCH: arm {arm} inner fingerprint policy_version "
            f"{observed_policy!r} != expected {policy_version!r}"
        )
    cls = type(inner)
    if hasattr(cls, "include_comparison_context"):
        observed_flag = cls.include_comparison_context
        if observed_flag is not include_context:
            raise RuntimeError(
                f"REASONER_IDENTITY_MISMATCH: arm {arm} {cls.__name__}.include_comparison_context "
                f"{observed_flag!r} != expected {include_context!r}"
            )
    if hasattr(cls, "system_instruction"):
        instruction = cls.system_instruction
        observed_sha = (
            hashlib.sha256(instruction.encode("utf-8")).hexdigest()
            if isinstance(instruction, str)
            else f"<{type(instruction).__name__}>"
        )
        if observed_sha != prompt_sha256:
            raise RuntimeError(
                f"REASONER_IDENTITY_MISMATCH: arm {arm} sha256({cls.__name__}.system_instruction) "
                f"{observed_sha!r} != expected {prompt_sha256!r}"
            )


class RecordingReasoner:
    """A ``SemanticReasoner`` that records every request it forwards, unchanged.

    Construction refuses an inner reasoner whose observable identity is not the arm's
    (``require_reasoner_identity``); the recorded policy/prompt identity is therefore
    the identity of the reasoner that was actually called."""

    def __init__(self, inner: SemanticReasoner, *, arm: Arm) -> None:
        require_reasoner_identity(inner, arm=arm)
        self._inner = inner
        self._arm: Arm = arm
        (
            self._policy_version,
            self._system_prompt_sha256,
            self._include_comparison_context,
        ) = _arm_identity(arm)
        self._t: int | None = None
        self._calls_this_step = 0
        self._records: list[RequestRecord] = []

    # --- configuration ------------------------------------------------------------

    @property
    def inner(self) -> SemanticReasoner:
        return self._inner

    @property
    def arm(self) -> Arm:
        return self._arm

    @property
    def policy_version(self) -> str:
        return self._policy_version

    @property
    def system_prompt_sha256(self) -> str:
        return self._system_prompt_sha256

    @property
    def include_comparison_context(self) -> bool:
        return self._include_comparison_context

    # --- SemanticReasoner protocol ------------------------------------------------

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        """Record the exact rendered request, then delegate; refuse a third call first."""
        if self._t is None:
            raise RuntimeError(
                "NO_STEP_BEGUN: RecordingReasoner.propose called before begin_step(t)"
            )
        if self._calls_this_step >= CALLS_PER_STEP:
            raise RuntimeError(
                f"THIRD_CALL_REFUSED: arm {self._arm} T{self._t} already made "
                f"{CALLS_PER_STEP} calls; no retry, fallback, or third call is permitted"
            )
        self._calls_this_step += 1
        call_number: Literal[1, 2] = 1 if self._calls_this_step == 1 else 2
        self._records.append(self._record(request, t=self._t, call_number=call_number))
        return self._inner.propose(request)

    # --- step accounting ----------------------------------------------------------

    def begin_step(self, t: int) -> None:
        """Start step ``t``: resets the per-step call counter."""
        self._t = t
        self._calls_this_step = 0

    @property
    def records(self) -> tuple[RequestRecord, ...]:
        return tuple(self._records)

    # --- adapter economics pass-through (Controller Ruling 4) ----------------------

    @property
    def receipts(self) -> tuple[Any, ...]:
        """``inner.receipts`` when the inner reasoner has them, else ``()``."""
        return tuple(getattr(self._inner, "receipts", ()))

    @property
    def draft_payloads(self) -> tuple[Any, ...]:
        """``inner.draft_payloads`` when the inner reasoner has them, else ``()``."""
        return tuple(getattr(self._inner, "draft_payloads", ()))

    # --- rendering ----------------------------------------------------------------

    def _record(
        self, request: ReasoningRequest, *, t: int, call_number: Literal[1, 2]
    ) -> RequestRecord:
        rendered = render_request(
            request, include_comparison_context=self._include_comparison_context
        )
        context_chars = (
            comparison_context_character_count(request.comparison_context)
            if self._include_comparison_context
            else 0
        )
        return RequestRecord(
            arm=self._arm,
            t=t,
            call_number=call_number,
            policy_version=self._policy_version,
            system_prompt_sha256=self._system_prompt_sha256,
            rendered_user_request=rendered,
            request_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            citable_evidence_ids=tuple(item.evidence_id for item in request.evidence),
            historical_comparison_evidence_ids=historical_evidence_ids(request.comparison_context),
            known_address_ids=tuple(a.address_id for a in request.known_addresses),
            known_claim_ids=tuple(c.claim_id for c in request.known_claims),
            allowed_judgment_kinds=tuple(
                sorted(kind.value for kind in request.allowed_judgment_kinds)
            ),
            comparison_context_chars=context_chars,
        )
