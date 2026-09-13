"""Mechanical 12-locus root designation for the persistent arms (spec §10.1; T2 brief).

Law: this module may record only structural facts already admitted into
``SemanticState`` -- which live claims a seed evidence id effectively supports, and
which one address those claims sit at. It may never decide, infer, or compare
meaning: no claim statement, predicate, descriptor, or value is ever read, and no
architect chooses among model-created objects. Designation either finds exactly one
supported address or it does not; there is no third outcome and no repair path.

After each persistent arm's T1 admits, ``designate_t1_roots`` designates all twelve
loci from their T1 seed evidence ids (``EV-O-<locus>01``, the spec §7 id law owned
by ``timeline.evidence_id``). An ``UNDESIGNATED`` locus is recorded with its reason
and the run continues; nothing here retries, re-seeds or substitutes an address.

This module imports ``timeline`` only (for ``LOCI``, ``Locus`` and ``evidence_id``),
never ``expectations``, and never constructs or calls a ``SemanticReasoner`` --
every input is already-admitted ledger state.
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.experiments.long_horizon_bounded.timeline import LOCI, Locus, evidence_id

__all__ = ["RootDesignation", "designate_seed_root", "designate_t1_roots"]

_NO_LIVE_SEED_SUPPORTED_CLAIM: Final = "NO_LIVE_SEED_SUPPORTED_CLAIM"
_MULTIPLE_SEED_SUPPORTED_ADDRESSES: Final = "MULTIPLE_SEED_SUPPORTED_ADDRESSES"
_DESIGNATED_REASON: Final = "DESIGNATED"


class RootDesignation(FrozenModel):
    """The mechanical outcome of designating one locus's root from its seed evidence id.

    ``claim_ids`` and ``creating_judgment_ids`` are both sorted and deduplicated.
    On ``UNDESIGNATED``, ``address_id`` is ``None`` and both id tuples are empty:
    there is nothing partial to report, only a named reason.
    """

    locus: Locus
    seed_evidence_id: str
    status: Literal["DESIGNATED", "UNDESIGNATED"]
    address_id: str | None
    claim_ids: tuple[str, ...]
    creating_judgment_ids: tuple[str, ...]
    reason: str


def _undesignated(locus: Locus, seed_evidence_id: str, reason: str) -> RootDesignation:
    return RootDesignation(
        locus=locus,
        seed_evidence_id=seed_evidence_id,
        status="UNDESIGNATED",
        address_id=None,
        claim_ids=(),
        creating_judgment_ids=(),
        reason=reason,
    )


def designate_seed_root(
    state: IntentState, *, locus: Locus, seed_evidence_id: str
) -> RootDesignation:
    """Mechanically designate the root of ``locus`` from one seed evidence id.

    1. derive the current semantic view;
    2. take live claim ids whose ``effective_evidence`` contains ``seed_evidence_id``;
    3. sort those claim ids;
    4. map them to their address ids;
    5. zero seed-supported claims -> ``UNDESIGNATED`` /
       ``NO_LIVE_SEED_SUPPORTED_CLAIM``;
    6. more than one distinct address -> ``UNDESIGNATED`` /
       ``MULTIPLE_SEED_SUPPORTED_ADDRESSES``;
    7. otherwise -> ``DESIGNATED`` with that one address, all seed-supported claim
       ids, and all corresponding creating judgment ids (sorted, deduplicated).

    Nothing about a claim beyond its id and its address is ever read here.
    """
    view = derive_view(state.semantic)
    claim_ids = sorted(
        claim_id
        for claim_id, evidence_ids in view.effective_evidence.items()
        if seed_evidence_id in evidence_ids
    )
    if not claim_ids:
        return _undesignated(locus, seed_evidence_id, _NO_LIVE_SEED_SUPPORTED_CLAIM)

    addresses = {state.semantic.claims[claim_id].address_id for claim_id in claim_ids}
    if len(addresses) > 1:
        return _undesignated(locus, seed_evidence_id, _MULTIPLE_SEED_SUPPORTED_ADDRESSES)

    creating_judgment_ids = tuple(
        sorted({state.semantic.claims[claim_id].created_by_judgment_id for claim_id in claim_ids})
    )
    return RootDesignation(
        locus=locus,
        seed_evidence_id=seed_evidence_id,
        status="DESIGNATED",
        address_id=next(iter(addresses)),
        claim_ids=tuple(claim_ids),
        creating_judgment_ids=creating_judgment_ids,
        reason=_DESIGNATED_REASON,
    )


def designate_t1_roots(state: IntentState) -> dict[Locus, RootDesignation]:
    """Designate every locus in ``LOCI`` order from its T1 seed ``evidence_id(1, locus)``."""
    return {
        locus: designate_seed_root(state, locus=locus, seed_evidence_id=evidence_id(1, locus))
        for locus in LOCI
    }
