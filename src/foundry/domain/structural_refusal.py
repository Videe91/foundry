"""Structural refusal and the production-only bounded re-proposal (design 2026-09-29).

A semantic call's answer can be refused by a deterministic structural law before any of it
reaches state: IE2's proposition accounting (``foundry.domain.proposition_accounting``) and
IE3's graph validation (``PARALLEL_NODE``). This module holds what is shared by both engines:

* ``ExecutionMode``: only ``PRODUCTION`` may re-propose. ``CERTIFICATION`` and ``EXPERIMENT``
  measure the model's first answer and stop there. A caller that names no mode gets no
  re-proposal (fail closed);
* the per-engine **allowlists**: re-proposal is permitted only when every refusal code is one
  Foundry can state deterministically as a breach of the answer contract. Anything else (an
  undesirable meaning, a scorer or reviewer disagreeing, low confidence, a provider fault, an
  admission REJECT of one judgment) never re-proposes;
* ``ReproposalNotice``: what the second attempt is told. A fixed text and the refusal findings
  (codes and ids) only, never what to do. The second answer is a complete new proposal;
* ``StructuralRefusal``: the durable audit record of one refused attempt, appended as
  ``STRUCTURAL_REFUSAL_RECORDED`` (it changes no state);
* ``MAX_REPROPOSALS`` = 1: attempt 2 is final. No attempt 3, no loop the model controls.

``REPROPOSAL_CONTRACT_SHA256`` pins the notice text, both allowlists and the maximum, so none
of them changes without a deliberate new identity.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint

__all__ = [
    "IE2_REPROPOSABLE_CODES",
    "IE3_REPROPOSABLE_CODES",
    "MAX_REPROPOSALS",
    "REPROPOSAL_CONTRACT_SHA256",
    "REPROPOSAL_NOTICE_TEMPLATE",
    "REPROPOSE_MODES",
    "ExecutionMode",
    "RefusalEngine",
    "ReproposalNotice",
    "StructuralRefusal",
    "refusal_codes",
    "reproposal_contract_sha256",
    "reproposable",
]


class ExecutionMode(StrEnum):
    PRODUCTION = "PRODUCTION"
    CERTIFICATION = "CERTIFICATION"
    EXPERIMENT = "EXPERIMENT"


class RefusalEngine(StrEnum):
    IE2_CLAIM_ASSIMILATION = "IE2_CLAIM_ASSIMILATION"
    IE3_GRAPH_SYNTHESIS = "IE3_GRAPH_SYNTHESIS"


REPROPOSE_MODES: Final[frozenset[ExecutionMode]] = frozenset({ExecutionMode.PRODUCTION})
MAX_REPROPOSALS: Final = 1

IE2_REPROPOSABLE_CODES: Final[frozenset[str]] = frozenset(
    {
        "UNACCOUNTED_SENTENCE",
        "UNKNOWN_SENTENCE",
        "DOUBLE_ACCOUNTED_SENTENCE",
        "UNACCOUNTED_PROPOSITION",
        "UNKNOWN_PROPOSITION",
        "DUPLICATE_PROPOSITION",
        "CONFLICTING_DISPOSITION",
        "PROPOSITION_EVIDENCE_MISMATCH",
    }
)
"""Proposition accounting (§7.1.3): whole-response refusals raised before any judgment exists.
``NON_CANONICAL_FACET`` is deliberately absent: it is an admission REJECT of one judgment after
the batch is submitted (other judgments of the batch may already be applied), and the
canonical-facet adapter cannot produce it, since it projects every facet itself."""

IE3_REPROPOSABLE_CODES: Final[frozenset[str]] = frozenset({"PARALLEL_NODE"})
"""Graph validation codes Foundry re-proposes on. Only the parallel-duplicate wall is admitted
for now; the other graph codes stay single-shot until they are reviewed one by one."""

_ALLOWLISTS: Final[dict[RefusalEngine, frozenset[str]]] = {
    RefusalEngine.IE2_CLAIM_ASSIMILATION: IE2_REPROPOSABLE_CODES,
    RefusalEngine.IE3_GRAPH_SYNTHESIS: IE3_REPROPOSABLE_CODES,
}

REPROPOSAL_NOTICE_TEMPLATE: Final = (
    "Your previous proposal for this same request was refused because it broke the structural "
    "answer contract. Refusal: {findings}. Nothing from that proposal was kept. Answer the whole "
    "request again with a complete new proposal."
)


def refusal_codes(findings: tuple[str, ...]) -> tuple[str, ...]:
    """The code of each finding (``CODE: detail``), in order."""
    return tuple(finding.split(":", 1)[0].strip() for finding in findings)


def reproposable(engine: RefusalEngine, findings: tuple[str, ...]) -> bool:
    """True iff there is a finding and every finding's code is on the engine's allowlist."""
    codes = refusal_codes(findings)
    return bool(codes) and all(code in _ALLOWLISTS[engine] for code in codes)


class ReproposalNotice(FrozenModel):
    """What attempt 2 is shown about attempt 1: the fixed notice and the findings, nothing else."""

    refused_attempt: Literal[1] = 1
    findings: tuple[str, ...] = Field(min_length=1)

    def text(self) -> str:
        return REPROPOSAL_NOTICE_TEMPLATE.format(findings="; ".join(self.findings))


class StructuralRefusal(FrozenModel):
    """One refused attempt, as recorded. Audit only: nothing of the proposal reaches state."""

    engine: RefusalEngine
    mode: ExecutionMode
    attempt: Literal[1, 2]
    request_sha256: str = Field(min_length=64, max_length=64)
    """The exact semantic request both attempts answer (the notice is not part of it)."""
    reasoner: ReasonerFingerprint
    findings: tuple[str, ...] = Field(min_length=1)
    codes: tuple[str, ...] = Field(min_length=1)
    reproposable: bool
    invocation_id: str | None = None
    """Links the provider receipt (tokens, cost, latency) the adapter recorded, when it has one."""
    proposal_json: str = Field(min_length=1)
    """The refused proposal as the sealed contract parsed it, canonical JSON."""
    reproposal_of: str | None = None
    """For attempt 2: the event id of attempt 1's refusal record."""
    notice: ReproposalNotice | None = None
    """For attempt 2: exactly what the model was shown about attempt 1."""


def reproposal_contract_sha256() -> str:
    """SHA256 of the notice text, the sorted allowlists and the maximum."""
    canonical = json.dumps(
        {
            "notice_template": REPROPOSAL_NOTICE_TEMPLATE,
            "allowlists": {engine.value: sorted(codes) for engine, codes in _ALLOWLISTS.items()},
            "max_reproposals": MAX_REPROPOSALS,
            "modes": sorted(mode.value for mode in REPROPOSE_MODES),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


REPROPOSAL_CONTRACT_SHA256: Final[str] = (
    "613ac28687a1ce020c4a2adc87d8efd3fc27e10301ce5a535f8ebac4a8bb9a84"
)
"""A PASTED LITERAL, checked by ``tests/unit/test_structural_reproposal.py``."""
