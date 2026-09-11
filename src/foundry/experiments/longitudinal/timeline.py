"""Real Foundry four-commit timeline (spec §15, §20, §25; plan Task 10).

Evidence is read from named commits only — never the working tree — with the Git
blob sha and the content sha256 recorded per version, as in 9O. Two versions of
one path are two immutable :class:`EvidenceItem`s linked by deterministic Git
lineage (``artifact_ref`` / ``supersedes_evidence_id``). Lineage carries no
semantic authority; nothing here originates a semantic conclusion.

Scope is per path (preflight ruling P5): ``FOUNDRY_CONSTITUTION.md`` is
``("constitution",)``; every other path is ``("intent-engine",)``. This is what
lets spec §24's unrelated ``constitution`` scope hold loci that the Track A
supersession must leave untouched.

Arm inputs (spec §20, §26, §27):

* :func:`persistent_delta` — Arm F at step ``t`` receives exactly the items
  whose ``(artifact_ref, content_sha256)`` did not occur at any earlier step.
* :func:`reconstruction_corpus` — Arm R at step ``t`` receives every version
  with step ``<= t``, in timeline order.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Final

from pydantic import Field

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.experiments.intent_v2_dogfood import GitReader

_COMMIT_PATTERN = r"^[0-9a-f]{40}$"

CONSTITUTION_PATH: Final = "FOUNDRY_CONSTITUTION.md"
SPEC_PATH: Final = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER_PATH: Final = "src/foundry/application/semantic_reducer.py"
IDENTITY_PATH: Final = "src/foundry/domain/semantic_identity.py"

CONSTITUTION_SCOPE: Final[tuple[str, ...]] = ("constitution",)
INTENT_ENGINE_SCOPE: Final[tuple[str, ...]] = ("intent-engine",)


class TimelinePath(FrozenModel):
    repo_path: str = Field(min_length=1)
    source_kind: SourceKind
    scope: tuple[str, ...]


class TimelineStep(FrozenModel):
    t: int = Field(ge=1)
    commit: str = Field(pattern=_COMMIT_PATTERN)
    paths: tuple[TimelinePath, ...]


_CONSTITUTION = TimelinePath(
    repo_path=CONSTITUTION_PATH, source_kind=SourceKind.DOCUMENT, scope=CONSTITUTION_SCOPE
)
_SPEC = TimelinePath(
    repo_path=SPEC_PATH, source_kind=SourceKind.DOCUMENT, scope=INTENT_ENGINE_SCOPE
)
_REDUCER = TimelinePath(
    repo_path=REDUCER_PATH, source_kind=SourceKind.CODE, scope=INTENT_ENGINE_SCOPE
)
_IDENTITY = TimelinePath(
    repo_path=IDENTITY_PATH, source_kind=SourceKind.CODE, scope=INTENT_ENGINE_SCOPE
)

TIMELINE: Final[tuple[TimelineStep, ...]] = (
    TimelineStep(
        t=1, commit="097584a39dd76cf86510500acb548778ce00fad9", paths=(_CONSTITUTION, _SPEC)
    ),
    TimelineStep(t=2, commit="2539ff81f79f085c1eba42718947050c1b3ac61c", paths=(_SPEC,)),
    TimelineStep(
        t=3, commit="90246a8b986b0dcbcbae6a4f3484204f916afeb5", paths=(_REDUCER, _IDENTITY)
    ),
    TimelineStep(t=4, commit="779a66ac90eceaea7eb7d4af0692ee4f167292fc", paths=(_REDUCER, _SPEC)),
)


class VersionedEvidence(FrozenModel):
    t: int
    repo_path: str
    artifact_ref: str
    commit: str
    git_blob_sha: str
    content_sha256: str
    source_kind: SourceKind
    scope: tuple[str, ...]
    item: EvidenceItem


def artifact_ref_for(repo_path: str) -> str:
    return f"repo:{repo_path}"


def load_timeline(
    reader: GitReader,
    *,
    project_id: str,
    observed_at_for: Callable[[int], datetime],
) -> tuple[VersionedEvidence, ...]:
    """Read every (step, path) from its named commit; link versions per artifact linearly."""
    versions: list[VersionedEvidence] = []
    latest_by_artifact: dict[str, str] = {}
    for step in TIMELINE:
        observed_at = observed_at_for(step.t)
        for index, path in enumerate(step.paths, start=1):
            raw = reader.blob(step.commit, path.repo_path)
            artifact_ref = artifact_ref_for(path.repo_path)
            evidence_id = f"EV-T{step.t}-{index:02d}"
            item = evidence_item(
                evidence_id=evidence_id,
                project_id=project_id,
                source_kind=path.source_kind,
                source_ref=f"git://{step.commit}/{path.repo_path}",
                content=raw.decode("utf-8"),
                observed_at=observed_at,
                scope=path.scope,
                artifact_ref=artifact_ref,
                supersedes_evidence_id=latest_by_artifact.get(artifact_ref),
            )
            versions.append(
                VersionedEvidence(
                    t=step.t,
                    repo_path=path.repo_path,
                    artifact_ref=artifact_ref,
                    commit=step.commit,
                    git_blob_sha=reader.blob_sha(step.commit, path.repo_path),
                    content_sha256=hashlib.sha256(raw).hexdigest(),
                    source_kind=path.source_kind,
                    scope=path.scope,
                    item=item,
                )
            )
            latest_by_artifact[artifact_ref] = evidence_id
    return tuple(versions)


def persistent_delta(items: tuple[VersionedEvidence, ...], t: int) -> tuple[EvidenceItem, ...]:
    """Arm F input at ``t``: versions whose (artifact_ref, content_sha256) is new at ``t``."""
    seen_before = {(v.artifact_ref, v.content_sha256) for v in items if v.t < t}
    return tuple(
        v.item for v in items if v.t == t and (v.artifact_ref, v.content_sha256) not in seen_before
    )


def reconstruction_corpus(items: tuple[VersionedEvidence, ...], t: int) -> tuple[EvidenceItem, ...]:
    """Arm R input at ``t``: every version with step ``<= t``, in timeline order."""
    return tuple(v.item for v in items if v.t <= t)


def evidence_hashes(items: tuple[VersionedEvidence, ...]) -> tuple[dict[str, str], ...]:
    """Per-version hash record for the sealed manifest."""
    return tuple(
        {
            "t": str(v.t),
            "artifact_ref": v.artifact_ref,
            "commit": v.commit,
            "git_blob_sha": v.git_blob_sha,
            "content_sha256": v.content_sha256,
        }
        for v in items
    )
