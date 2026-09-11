"""Preregistered derivation fixture for the longitudinal dogfood (plan Task 11; spec §23).

This module is **experiment instrumentation, not semantics**. It is executed exactly
once per Arm F run, after T1 completes and before any T2 evidence is ingested, from T1
state only. Nothing it records is ever counted as semantic success: the derivation
edges exist so that a later, model-proposed and human-authorized supersession of the
Track A root exposes a measurable blast radius (``view.stale_ids``) over real Foundry
artifacts, while an unrelated control chain off a constitution-only locus must stay
clean (failure mode 11).

Two acts are separated on purpose:

* ``designate_root`` is the architect's *selection* of which existing T1 address is
  the tracked locus. It reads T1 state, writes nothing, and pins the ledger sequence
  at which the selection was made so Task 17 can verify deterministically that it
  precedes the first T2 ``EVIDENCE_INGESTED`` event. The root judgment is chosen
  mechanically — the earliest applied ``ASSERT_CLAIM`` at that address — so no
  post-output tuning is possible. The architect may not create, bind or edit
  anything through this path. Every tracked locus (A, B, C) and the control are
  designated this way; B and C exist for authorization-budget attribution only
  (ruling R12-d) and never receive a chain.
* ``attach_preregistered_chains`` records the five ``DERIVATION_RECORDED`` events
  through the governor's ordinary ``derive`` path and nothing else. It accepts
  exactly one ``A`` designation and one ``CONTROL`` designation; a ``B`` or ``C``
  designation in either slot is refused.

Ordering guards (enforced, not documented): attachment refuses to proceed once any
post-T1 evidence is present in state. Two independent checks, either of which refuses:

1. **Timeline id guard** — any evidence id of the form ``EV-T<t>-*`` with ``t != 1``
   (``EV-T2-``, ``EV-T3-``, ..., ``EV-T10-``, ...; the Task 10 loader mints evidence
   ids as ``EV-T<n>-<k>`` and only ``EV-T1-*`` is T1).
2. **Artifact lineage guard** — any evidence item whose ``artifact_ref`` is in the
   caller-supplied ``t2_artifact_refs`` AND whose ``evidence_id`` does not start with
   ``EV-T1-`` (a T1 version of a T2 artifact is allowed; a later version is not).

Two further preconditions are enforced:

* **Roots must be active.** Spec §23's premise is ``stale_ids == ()`` before the T2
  supersession, so attachment refuses if either designated root judgment has already
  been superseded (is not in ``active_judgment_ids``).
* **Once only.** If the first id of either chain already appears as a derivation
  child the chains were attached before, and attachment is refused.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal

from pydantic import Field

from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.semantic_judgment import AssertClaimProposal
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState

TRACK_A_CHAIN: Final[tuple[str, str, str]] = (
    "artifact:docs/superpowers/plans/2026-09-11-intent-intelligence-v2-core.md#6.1",
    "artifact:src/foundry/domain/admission.py",
    "artifact:tests/unit/test_admission.py",
)
CONTROL_CHAIN: Final[tuple[str, str]] = ("control:D-N1", "control:D-N2")

T1_EVIDENCE_ID_PREFIX: Final = "EV-T1-"
POST_T1_EVIDENCE_ID_PATTERN: Final = re.compile(r"^EV-T(?!1-)\d+-")
_T2_ALREADY_INGESTED = "T2 evidence already ingested; chains must attach before T2"
_ALREADY_ATTACHED = "preregistered chains already attached; attachment is once-only"

Track = Literal["A", "B", "C", "CONTROL"]
"""Which tracked locus a designation names.

``A`` and ``CONTROL`` roots receive a preregistered derivation chain (spec §23).
``B`` and ``C`` are designated for authorization-budget attribution only (ruling
R12-d: each of the three tracked corrections A, B, C may consume at most one human
authorization); no chain is ever attached for them.
"""


class RootDesignation(FrozenModel):
    """The architect's pre-T2 selection of a tracked T1 locus (the `T1_locus_designation`).

    ``judgment_id`` is the earliest applied ``ASSERT_CLAIM`` judgment whose claim sits
    at ``address_id`` — earliest in applied (ledger) order, chosen mechanically, never
    by hand (ruling R11-d).
    ``ledger_sequence_at_designation`` is the governor's ledger sequence at the moment
    of designation; it must precede the first T2 ``EVIDENCE_INGESTED`` event.
    """

    track: Track
    address_id: str = Field(min_length=1)
    judgment_id: str = Field(min_length=1)
    ledger_sequence_at_designation: int = Field(ge=0)
    designated_at: datetime


def _earliest_applied_assert_claim(state: IntentState, address_id: str) -> str | None:
    semantic = state.semantic
    for judgment_id in semantic.applied_judgment_ids:
        judgment = semantic.judgments.get(judgment_id)
        if judgment is None:
            continue
        proposal = judgment.proposal
        if isinstance(proposal, AssertClaimProposal) and proposal.address_id == address_id:
            return judgment_id
    return None


def designate_root(
    governor: SemanticGovernor,
    *,
    track: Track,
    address_id: str,
    clock: Callable[[], datetime],
) -> RootDesignation:
    """Select an existing T1 address as a tracked locus. Reads state; writes nothing.

    ``track`` may be ``"A"``, ``"B"``, ``"C"`` or ``"CONTROL"``. Tracks B and C are
    designated for authorization-budget attribution only; no derivation chain is ever
    attached for them.

    Raises ``ValueError`` when the address has no applied ``ASSERT_CLAIM`` judgment —
    a locus with no T1 claim cannot be a supersession root.
    """
    state = governor.state()
    judgment_id = _earliest_applied_assert_claim(state, address_id)
    if judgment_id is None:
        raise ValueError(f"address {address_id} has no applied ASSERT_CLAIM judgment")
    return RootDesignation(
        track=track,
        address_id=address_id,
        judgment_id=judgment_id,
        ledger_sequence_at_designation=state.last_sequence,
        designated_at=clock(),
    )


def _post_t1_evidence_present(state: IntentState, t2_artifact_refs: frozenset[str]) -> bool:
    for evidence_id, item in state.semantic.evidence.items():
        if POST_T1_EVIDENCE_ID_PATTERN.match(evidence_id):
            return True
        if item.artifact_ref in t2_artifact_refs and not evidence_id.startswith(
            T1_EVIDENCE_ID_PREFIX
        ):
            return True
    return False


def _already_attached(state: IntentState) -> bool:
    heads = {TRACK_A_CHAIN[0], CONTROL_CHAIN[0]}
    return any(edge.child_id in heads for edge in state.semantic.derivations)


def attach_preregistered_chains(
    governor: SemanticGovernor,
    *,
    track_a: RootDesignation,
    control: RootDesignation,
    t2_artifact_refs: frozenset[str],
) -> tuple[StoredEvent, ...]:
    """Record the preregistered Track A and control derivation chains (spec §23).

    Experiment instrumentation, done after T1 and before T2, from T1 state only; it
    is never counted as semantic success. Records, in order:

    * ``D-A1 <- track_a.judgment_id``, ``D-A2 <- D-A1``, ``D-A3 <- D-A2``
      (``D-A*`` = ``TRACK_A_CHAIN``);
    * ``D-N1 <- control.judgment_id``, ``D-N2 <- D-N1`` (``D-N*`` = ``CONTROL_CHAIN``).

    Guards, each raising ``ValueError`` and appending nothing:

    * ``track_a`` is not an ``"A"`` designation or ``control`` is not a ``"CONTROL"``
      designation (a ``"B"`` / ``"C"`` designation is refused in either slot);
    * any evidence id in state matches ``POST_T1_EVIDENCE_ID_PATTERN``
      (``EV-T<t>-*`` with ``t != 1``, including ``t >= 10``);
    * any evidence item in state has ``artifact_ref`` in ``t2_artifact_refs`` and an
      ``evidence_id`` not starting with ``EV-T1-`` (a post-T1 version of a T2 artifact);
    * either designated root judgment is no longer active (already superseded) —
      spec §23 requires ``stale_ids == ()`` before the T2 supersession;
    * either chain head is already a derivation child (re-attachment).
    """
    if track_a.track != "A" or control.track != "CONTROL":
        raise ValueError("track_a must be the A designation and control the CONTROL designation")
    state = governor.state()
    if _post_t1_evidence_present(state, t2_artifact_refs):
        raise ValueError(_T2_ALREADY_INGESTED)
    active = active_judgment_ids(state.semantic)
    for designation in (track_a, control):
        if designation.judgment_id not in active:
            raise ValueError(
                f"root judgment {designation.judgment_id} (track {designation.track}) is no "
                "longer active; chains must attach while every root is unsuperseded"
            )
    if _already_attached(state):
        raise ValueError(_ALREADY_ATTACHED)

    edges: tuple[tuple[str, str], ...] = (
        (TRACK_A_CHAIN[0], track_a.judgment_id),
        (TRACK_A_CHAIN[1], TRACK_A_CHAIN[0]),
        (TRACK_A_CHAIN[2], TRACK_A_CHAIN[1]),
        (CONTROL_CHAIN[0], control.judgment_id),
        (CONTROL_CHAIN[1], CONTROL_CHAIN[0]),
    )
    return tuple(governor.derive(child_id, parent_id) for child_id, parent_id in edges)
