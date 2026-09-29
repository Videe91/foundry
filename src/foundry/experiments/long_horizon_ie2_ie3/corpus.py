"""The historical Orion corpus, reused byte for byte (design §2).

Every turn's input is ``long_horizon_bounded.timeline.persistent_delta(t)``: the twelve
sections of version ``t`` in the historical document order, the frozen items with only
``project_id`` replaced, exactly as the 9P3 persistent arms received them. Nothing is
reworded, reordered or added. ``historical_corpus_findings`` proves identity against the
sealed 9P3 manifest: the structural corpus digest and, item by item, id, locus, version,
lineage, timestamp, scope, kind, reference, byte length and content sha256.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from foundry.domain.evidence import EvidenceItem, sha256_of_content
from foundry.experiments.long_horizon_bounded import timeline
from foundry.experiments.long_horizon_ie2_ie3.protocol import HISTORICAL_CORPUS_SHA256, PROJECT_ID

__all__ = ["corpus_record", "delta", "historical_corpus_findings", "section_text"]

SCOPE = timeline.SCOPE
LOCI = timeline.LOCI


def delta(t: int) -> tuple[EvidenceItem, ...]:
    """The twelve items of version ``t``, historical order, this experiment's project id."""
    return timeline.persistent_delta(t, project_id=PROJECT_ID)


def section_text(t: int, locus: timeline.Locus) -> str:
    return timeline.SECTION_TEXT[(t, locus)]


def corpus_record() -> dict[str, Any]:
    return {
        "source": "foundry.experiments.long_horizon_bounded.timeline.persistent_delta",
        "historical_corpus_sha256": timeline.corpus_sha256(),
        "items": [r.model_dump(mode="json") for r in timeline.evidence_records()],
        "project_id": PROJECT_ID,
        "representation_differences": [
            "project_id is PROJ-LH23-ORION (9P3 persistent arms: PROJ-9P3-F / PROJ-9P3-A); "
            "every other field of every item is the frozen timeline item"
        ],
    }


def historical_corpus_findings(historical_manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Every difference between this corpus and the sealed 9P3 manifest's evidence list."""
    findings: list[str] = []
    if timeline.corpus_sha256() != HISTORICAL_CORPUS_SHA256:
        findings.append(f"corpus sha256 {timeline.corpus_sha256()} != {HISTORICAL_CORPUS_SHA256}")
    if historical_manifest.get("corpus_sha256") != HISTORICAL_CORPUS_SHA256:
        findings.append("9P3 manifest corpus_sha256 is not the pinned historical digest")
    recorded: Sequence[Mapping[str, Any]] = historical_manifest.get("evidence", ())
    by_id = {r["evidence_id"]: r for r in recorded}
    ours = [le for le in timeline.TIMELINE]
    if len(ours) != len(recorded) or len(ours) != 192:
        findings.append(f"item count {len(ours)} vs historical {len(recorded)}")
    for t in range(1, 17):
        for item in delta(t):
            r = by_id.get(item.evidence_id)
            if r is None:
                findings.append(f"{item.evidence_id} missing from the 9P3 manifest")
                continue
            content = item.content
            observed = {
                "content_sha256": sha256_of_content(content),
                "content_bytes": len(content.encode("utf-8")),
                "t": t,
                "artifact_ref": item.artifact_ref,
                "supersedes_evidence_id": item.supersedes_evidence_id,
                "source_ref": item.source_ref,
                "source_kind": item.source_kind.value,
                "scope": list(item.scope),
                "observed_at": item.observed_at.isoformat().replace("+00:00", "Z"),
            }
            for key, value in observed.items():
                if r.get(key) != value:
                    findings.append(f"{item.evidence_id} {key}: {value!r} != {r.get(key)!r}")
    return tuple(findings)
