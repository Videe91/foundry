"""Model-visible evidence of the sealed locus-validation corpus.

Spec §5. This module holds only what the model may see: two ledgers, four
documents each, two versions each — sixteen ``EvidenceItem``s — with their ids,
lineage, scope, project, frozen timestamp and byte-exact section texts, plus the
structural facts (content hash, character count) the manifest records about them.
It decides nothing. It never imports the hidden answer key. Every section text is a
literal transcribed from the approved spec; no file, git history, environment
variable or current time influences the evidence, and the spec is never parsed at
runtime.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256

__all__ = [
    "ARTIFACT_REFS",
    "DOCUMENTS",
    "LEDGERS",
    "OBSERVED_AT",
    "PROJECT_IDS",
    "SCOPES",
    "EvidenceRecord",
    "Ledger",
    "Version",
    "corpus_sha256",
    "delta",
    "evidence_id",
    "evidence_records",
    "section_text",
]

Ledger = Literal["alpha", "beta"]
Version = Literal[1, 2]

LEDGERS: Final[tuple[Ledger, ...]] = ("alpha", "beta")
VERSIONS: Final[tuple[Version, ...]] = (1, 2)
PROJECT_IDS: Final[dict[Ledger, str]] = {"alpha": "PROJ-LV-ALPHA", "beta": "PROJ-LV-BETA"}
SCOPES: Final[dict[Ledger, str]] = {"alpha": "keyring", "beta": "relay"}
DOCUMENTS: Final[dict[Ledger, tuple[str, ...]]] = {
    "alpha": ("A1", "A2", "A3", "A4"),
    "beta": ("B1", "B2", "B3", "B4"),
}
ARTIFACT_REFS: Final[dict[str, str]] = {
    "A1": "keyring/spec/credential-revocation.md",
    "A2": "keyring/spec/retry-timing.md",
    "A3": "keyring/spec/worker-lease.md",
    "A4": "keyring/spec/execution-time-limit.md",
    "B1": "relay/runbook/acknowledgement.md",
    "B2": "relay/runbook/delivery-order.md",
    "B3": "relay/runbook/subscription-lease.md",
    "B4": "relay/runbook/delivery-deadline.md",
}
OBSERVED_AT: Final[datetime] = datetime(2026, 9, 15, tzinfo=UTC)

# --- byte-exact section texts (spec §5.1, §5.2) ------------------------------------

_A1_T1: Final = """\
## Credentials — revocation

A client credential can be revoked by its owner or by an operator. Revocation takes
effect immediately and cannot be undone by the client.

Normative rule
1. After a credential has been revoked, no authentication attempt that presents it may
   succeed.

Example
Credential K-17 is revoked at 09:00:00. A login presenting K-17 at 09:00:30 is refused.
"""

_A1_T2: Final = """\
## Credentials — revocation

A client credential can be revoked by its owner or by an operator. Revocation takes
effect immediately and cannot be undone by the client. Because owner tooling retries
its own requests, the same revocation is frequently submitted more than once.

Normative rule
1. After a credential has been revoked, no authentication attempt that presents it may
   succeed.
2. A revocation received for a credential that is already revoked leaves the credential
   revoked and changes nothing else about it.

Example
Credential K-17 is revoked at 09:00:00. A login presenting K-17 at 09:00:30 is refused.
A second revocation of K-17 arrives at 09:05:00; K-17 remains revoked and nothing else
about K-17 changes.
"""

_A2_T1: Final = """\
## Job execution — retry timing

When an execution of a job fails, the scheduler retries the job later rather than at
once, so that a struggling dependency is not hammered.

Normative rule
1. The delay before each retry is double the delay before the previous retry, starting
   from two seconds for the first retry.

Example
Job J-4 fails three times; the scheduler waits 2 s, then 4 s, then 8 s before each
retry.
"""

_A2_T2: Final = """\
## Job execution — retry timing

When an execution of a job fails, the scheduler retries the job later rather than at
once, so that a struggling dependency is not hammered. To keep many failing jobs from
retrying in lockstep, a small random jitter is added to every retry delay.

Normative rule
1. The delay before each retry is double the delay before the previous retry, starting
   from two seconds for the first retry.
2. A random jitter is added to each retry delay; the jitter never exceeds 500
   milliseconds.

Example
Job J-4 fails three times; the scheduler waits 2 s, then 4 s, then 8 s before each
retry, each wait lengthened by at most half a second of jitter.

## Job execution — audit trail

Every execution of a job writes an audit record when it ends.

Normative rule
3. Audit records of job execution are retained for 30 days after they are written and
   are then deleted.

Example
An audit record written on 1 March is deleted on 31 March.
"""

_A3_T1: Final = """\
## Worker lease — duration

A worker holds a lease on the job it is executing so that no other worker picks the
same job up.

Normative rule
1. A lease lasts 90 seconds from the moment it is granted.

Example
A lease granted at 10:00:00 expires at 10:01:30.
"""

_A3_T2: Final = """\
## Worker lease — duration

A worker holds a lease on the job it is executing so that no other worker picks the
same job up.

Normative rule
1. A lease is valid for one and a half minutes, counted from the moment it is granted.

Example
A lease granted at 10:00:00 is no longer valid after 10:01:30.
"""

_A4_T1: Final = """\
## Execution — time limit

A stalled execution must not hold its worker indefinitely.

Normative rule
1. A single execution may run for at most 30 seconds; when the limit is reached the
   execution is stopped and recorded as a failure.

Example
An execution that starts at 11:00:00 and is still running at 11:00:30 is stopped and
recorded as failed.
"""

_A4_T2: Final = """\
## Execution — time limit

A stalled execution must not hold its worker indefinitely.

Normative rule
1. A single execution may run for at most 45 seconds; when the limit is reached the
   execution is stopped and recorded as a failure.

Example
An execution that starts at 11:00:00 and is still running at 11:00:45 is stopped and
recorded as failed.
"""

_B1_T1: Final = """\
# Consumer acknowledgement

Q: What does acknowledging a message do?
A: The message is removed from that consumer's pending set. Relay will not deliver it
to that consumer again.

Q: Is acknowledgement required?
A: Yes. Until a message is acknowledged it stays pending for the consumer that
received it.
"""

_B1_T2: Final = """\
# Consumer acknowledgement

Q: What does acknowledging a message do?
A: The message is removed from that consumer's pending set. Relay will not deliver it
to that consumer again. Acknowledging also releases the storage slot that was reserved
for the message while it was pending, so the slot can be reused by later messages.

Q: Is acknowledgement required?
A: Yes. Until a message is acknowledged it stays pending for the consumer that
received it.
"""

_B2_T1: Final = """\
# Delivery ordering

Behaviour: Messages published by one producer are delivered to a consumer in the order
in which they were published.

Reason: Consumers rebuild state by replaying messages, and an out-of-order replay would
corrupt that state.
"""

_B2_T2: Final = """\
# Delivery ordering

Behaviour: Messages published by one producer are delivered to a consumer in the order
in which they were published.

Behaviour: Ordering survives a redelivery. When a message from a producer is
redelivered, it is delivered before any message that the same producer published after
it.

Reason: Consumers rebuild state by replaying messages, and an out-of-order replay would
corrupt that state.

# Delivery receipts

Behaviour: Relay keeps a receipt for every delivery it makes. Receipts are kept for 14
days and are then discarded.

Reason: Operators investigate delivery disputes within two weeks; older receipts are
never consulted.
"""

_B3_T1: Final = """\
# Subscription lease

Q: How long does a subscription stay alive without a renewal?
A: A subscription expires unless the consumer renews it within 10 minutes of the
previous renewal.
"""

_B3_T2: Final = """\
# Subscription lease

Q: How long does a subscription stay alive without a renewal?
A: A consumer must renew its subscription at least once every 600 seconds, measured
from the previous renewal; otherwise the subscription lapses.
"""

_B4_T1: Final = """\
# Delivery deadline

Behaviour: A message that has not been delivered within 24 hours of being published is
moved to the dead-letter store and is not delivered afterwards.

Reason: A message older than that is stale for every known consumer.
"""

_B4_T2: Final = """\
# Delivery deadline

Behaviour: A message that has not been delivered within 48 hours of being published is
moved to the dead-letter store and is not delivered afterwards.

Reason: A message older than that is stale for every known consumer.
"""

_SECTION_TEXT: Final[dict[tuple[str, Version], str]] = {
    ("A1", 1): _A1_T1,
    ("A1", 2): _A1_T2,
    ("A2", 1): _A2_T1,
    ("A2", 2): _A2_T2,
    ("A3", 1): _A3_T1,
    ("A3", 2): _A3_T2,
    ("A4", 1): _A4_T1,
    ("A4", 2): _A4_T2,
    ("B1", 1): _B1_T1,
    ("B1", 2): _B1_T2,
    ("B2", 1): _B2_T1,
    ("B2", 2): _B2_T2,
    ("B3", 1): _B3_T1,
    ("B3", 2): _B3_T2,
    ("B4", 1): _B4_T1,
    ("B4", 2): _B4_T2,
}


def evidence_id(document: str, t: Version) -> str:
    """Spec §5 id law: ``EV-LV-<document>-T<t>``."""
    return f"EV-LV-{document}-T{t}"


def section_text(document: str, t: Version) -> str:
    """The byte-exact fenced block of spec §5 for ``(document, t)``, trailing newline kept."""
    try:
        return _SECTION_TEXT[(document, t)]
    except KeyError:
        raise ValueError(f"no section text for document {document!r} at T{t}") from None


def _ledger_of(document: str) -> Ledger:
    for ledger in LEDGERS:
        if document in DOCUMENTS[ledger]:
            return ledger
    raise ValueError(f"unknown document {document!r}")


def _item(document: str, t: Version) -> EvidenceItem:
    ledger = _ledger_of(document)
    return evidence_item(
        evidence_id=evidence_id(document, t),
        project_id=PROJECT_IDS[ledger],
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"experiment://locus-validation/{ledger}/T{t}/{document}",
        content=section_text(document, t),
        observed_at=OBSERVED_AT,
        scope=(SCOPES[ledger],),
        artifact_ref=ARTIFACT_REFS[document],
        supersedes_evidence_id=None if t == 1 else evidence_id(document, 1),
    )


def delta(ledger: Ledger, t: Version) -> tuple[EvidenceItem, ...]:
    """The four items of version ``t`` of ``ledger`` in document order.

    T2 items supersede their T1 item and share its ``artifact_ref`` (spec §5).
    """
    return tuple(_item(document, t) for document in DOCUMENTS[ledger])


class EvidenceRecord(FrozenModel):
    """Structural facts only — ids, lineage, hash and length; no meaning (spec §5.3)."""

    evidence_id: str = Field(min_length=1)
    ledger: Ledger
    document: str = Field(min_length=1)
    t: Version
    artifact_ref: str = Field(min_length=1)
    supersedes_evidence_id: str | None
    content_sha256: str = Field(min_length=64, max_length=64)
    chars: int = Field(ge=1)


def evidence_records() -> tuple[EvidenceRecord, ...]:
    """The 16 structural records: alpha then beta, T1 then T2, document order."""
    records: list[EvidenceRecord] = []
    for ledger in LEDGERS:
        for t in VERSIONS:
            for document, item in zip(DOCUMENTS[ledger], delta(ledger, t), strict=True):
                records.append(
                    EvidenceRecord(
                        evidence_id=item.evidence_id,
                        ledger=ledger,
                        document=document,
                        t=t,
                        artifact_ref=ARTIFACT_REFS[document],
                        supersedes_evidence_id=item.supersedes_evidence_id,
                        content_sha256=item.content_sha256,
                        chars=len(item.content),
                    )
                )
    return tuple(records)


def corpus_sha256() -> str:
    """Canonical SHA-256 over the ordered records plus their content — the only corpus hash."""
    return canonical_sha256(
        [
            record.model_dump(mode="json") | {"content": section_text(record.document, record.t)}
            for record in evidence_records()
        ]
    )
