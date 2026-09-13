"""Frozen Orion evidence corpus for the 9P3 long-horizon bounded-memory experiment.

Spec §3 (loci and artifact refs), §4 (T1 baseline texts), §5 (T2–T16 replacement
texts and document order) and §7 (evidence corpus law). This module owns only
model-visible evidence: 16 versions x 12 loci = 192 ``EvidenceItem``s, their ids,
lineage, timestamps, scope and byte-exact section texts, plus structural facts
about them (content hashes, byte lengths, raw character counts). It must never
decide or encode semantic meaning, and it must never import ``expectations`` or
``protocol`` — the hidden answer key lives in ``expectations`` exclusively, so a
request-path module built from this file alone cannot see it. No file, git
history, environment variable or current time may influence the evidence: every
section text below is a literal transcribed from the approved spec; the spec is
never parsed at runtime.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item

__all__ = [
    "ARTIFACT_REFS",
    "DOCUMENT_ORDER",
    "EXPERIMENT_VERSION",
    "LOCI",
    "PROJECT_ID",
    "SCOPE",
    "SCOPE_TUPLE",
    "SECTION_TEXT",
    "TIMELINE",
    "VERSION_COUNT",
    "EvidenceRecord",
    "LifecycleEvidence",
    "Locus",
    "corpus_sha256",
    "evidence_id",
    "evidence_records",
    "observed_at",
    "persistent_delta",
    "raw_evidence_character_count",
    "reconstruction_corpus",
]

Locus = Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]

LOCI: Final[tuple[Locus, ...]] = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L")
EXPERIMENT_VERSION: Final = "intent-v2-long-horizon-bounded-memory-v1"
PROJECT_ID: Final = "PROJ-9P3-ORION"
SCOPE: Final = "orion-jobs"
SCOPE_TUPLE: Final[tuple[str, ...]] = (SCOPE,)
VERSION_COUNT: Final[int] = 16

ARTIFACT_REFS: Final[dict[Locus, str]] = {
    "A": "orion/spec/A-execution-attempts.md",
    "B": "orion/spec/B-retry-delay.md",
    "C": "orion/spec/C-attempt-timeout.md",
    "D": "orion/spec/D-duplicate-delivery.md",
    "E": "orion/spec/E-idempotency-keys.md",
    "F": "orion/spec/F-worker-lease.md",
    "G": "orion/spec/G-lease-renewal.md",
    "H": "orion/spec/H-cancellation.md",
    "I": "orion/spec/I-final-failure.md",
    "J": "orion/spec/J-operator-escalation.md",
    "K": "orion/spec/K-ordering.md",
    "L": "orion/spec/L-audit-retention.md",
}

_ORDER_T1_T3: Final[tuple[Locus, ...]] = (
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
)
_ORDER_T4_T12: Final[tuple[Locus, ...]] = (
    "A",
    "C",
    "B",
    "F",
    "G",
    "H",
    "D",
    "E",
    "K",
    "I",
    "J",
    "L",
)
_ORDER_T13_T16: Final[tuple[Locus, ...]] = (
    "A",
    "C",
    "B",
    "F",
    "G",
    "H",
    "D",
    "E",
    "I",
    "J",
    "K",
    "L",
)

DOCUMENT_ORDER: Final[dict[int, tuple[Locus, ...]]] = {
    1: _ORDER_T1_T3,
    2: _ORDER_T1_T3,
    3: _ORDER_T1_T3,
    4: _ORDER_T4_T12,
    5: _ORDER_T4_T12,
    6: _ORDER_T4_T12,
    7: _ORDER_T4_T12,
    8: _ORDER_T4_T12,
    9: _ORDER_T4_T12,
    10: _ORDER_T4_T12,
    11: _ORDER_T4_T12,
    12: _ORDER_T4_T12,
    13: _ORDER_T13_T16,
    14: _ORDER_T13_T16,
    15: _ORDER_T13_T16,
    16: _ORDER_T13_T16,
}

# --- byte-exact section texts (spec §4.1–§4.12, §5) --------------------------------

_T1: Final[dict[Locus, str]] = {
    "A": (
        "## 1. Execution attempts\n"
        "\n"
        "Every job admitted to Orion is executed by a worker. An execution attempt is one delivery "
        "of the job to a worker that either succeeds, fails, or times out. Orion bounds the number "
        "of attempts so that a job that cannot succeed does not consume worker capacity forever.\n"
        "\n"
        "Normative rule\n"
        "1. A job must be executed at most three times in total.\n"
        "2. The first execution counts as one of the three.\n"
        "3. When the third execution has ended without success, no further execution of that job "
        "may be started.\n"
        "\n"
        "Example\n"
        "A job whose first two executions fail is executed a third time. If that execution also "
        "fails, the job has exhausted its attempts.\n"
    ),
    "B": (
        "## 2. Retry delay\n"
        "\n"
        "After an execution attempt fails, Orion waits before delivering the job again. The wait "
        "gives transient downstream faults time to clear without hammering the dependency that "
        "just failed.\n"
        "\n"
        "Normative rule\n"
        "1. Before every retry attempt the worker must wait exactly five seconds, measured from "
        "the end of the failed attempt.\n"
        "2. The wait must not be shortened or lengthened based on the attempt number.\n"
        "\n"
        "Example\n"
        "An attempt fails at 10:00:00. The next attempt may start no earlier than 10:00:05. If "
        "that attempt also fails at 10:00:20, the following attempt may start no earlier than "
        "10:00:25.\n"
    ),
    "C": (
        "## 3. Attempt timeout\n"
        "\n"
        "A worker that hangs must not hold a job indefinitely. Each attempt is bounded by a "
        "timeout after which the attempt is treated as failed and the retry policy applies.\n"
        "\n"
        "Normative rule\n"
        "1. Each execution attempt must time out after thirty seconds of execution.\n"
        "2. An attempt that reaches the timeout must be recorded as a failed attempt.\n"
        "\n"
        "Example\n"
        "An attempt starts at 12:00:00 and has not completed by 12:00:30. Orion records the "
        "attempt as failed at 12:00:30.\n"
    ),
    "D": (
        "## 4. Duplicate delivery\n"
        "\n"
        "Producers may deliver the same job more than once, for example after a network timeout on "
        "the producer side. Orion must not execute a job twice because of such redelivery.\n"
        "\n"
        "Normative rule\n"
        "1. While a job with a given job id is active, any further delivery carrying the same job "
        "id must be ignored.\n"
        "2. Ignoring a duplicate delivery must not change the state of the active job.\n"
        "\n"
        "Example\n"
        "Job J-17 is delivered at 09:00 and is executing. A second delivery of J-17 arrives at "
        "09:01 and is ignored; J-17 continues unaffected.\n"
    ),
    "E": (
        "## 5. Idempotency keys\n"
        "\n"
        "Each delivery may carry an idempotency key chosen by the producer. Orion remembers keys "
        "for a bounded period so that repeated deliveries with the same key can be recognised.\n"
        "\n"
        "Normative rule\n"
        "1. Orion must retain each idempotency key for twenty-four hours after it is first seen.\n"
        "2. After the retention period the key may be forgotten and a later delivery with the same "
        "key is treated as new.\n"
        "\n"
        "Example\n"
        "Key K-9 is first seen on Monday at 08:00. A delivery with K-9 on Monday at 20:00 is "
        "recognised as a repeat. A delivery with K-9 on Tuesday at 09:00 is treated as new.\n"
    ),
    "F": (
        "## 6. Worker lease\n"
        "\n"
        "A worker that receives a job holds a lease on it. The lease is how Orion knows that the "
        "job is being worked on and prevents a second worker from taking it.\n"
        "\n"
        "Normative rule\n"
        "1. A worker lease must last sixty seconds from the moment the job is delivered to the "
        "worker.\n"
        "2. When the lease expires without renewal or release, the job must become available to "
        "other workers.\n"
        "\n"
        "Example\n"
        "A worker receives job J-4 at 14:00:00 and neither renews nor releases it. At 14:01:00 the "
        "lease expires and J-4 may be delivered to another worker.\n"
    ),
    "G": (
        "## 7. Lease renewal\n"
        "\n"
        "Long-running work must be able to keep its lease. A worker renews the lease to signal "
        "that it is still progressing.\n"
        "\n"
        "Normative rule\n"
        "1. A worker may renew its lease every thirty seconds while work on the job is "
        "progressing.\n"
        "2. A renewal must extend the lease by the full lease duration from the moment of "
        "renewal.\n"
        "\n"
        "Example\n"
        "A worker holding a sixty-second lease that started at 14:00:00 renews at 14:00:30; the "
        "lease now runs until 14:01:30.\n"
    ),
    "H": (
        "## 8. Cancellation\n"
        "\n"
        "A producer or operator may cancel a job. Cancellation stops Orion from investing further "
        "effort in the job, but Orion does not forcibly abort work that a worker is already "
        "performing.\n"
        "\n"
        "Normative rule\n"
        "1. After a job is cancelled, no future execution attempt of that job may be started.\n"
        "2. Cancellation must not interrupt an execution attempt that is already running; that "
        "attempt runs to its own completion, failure or timeout.\n"
        "\n"
        "Example\n"
        "Job J-8 is cancelled while its second attempt is running. The second attempt continues; "
        "when it ends, no third attempt is started.\n"
    ),
    "I": (
        "## 9. Final failure handling\n"
        "\n"
        "When a job has used all of its attempts without success, Orion must decide what happens "
        "to it. Orion parks such jobs where they can be inspected without blocking the queue.\n"
        "\n"
        "Normative rule\n"
        "1. After the final unsuccessful execution attempt, Orion must automatically move the job "
        "to the dead-letter queue.\n"
        "2. A job in the dead-letter queue must not be executed again unless explicitly "
        "resubmitted.\n"
        "\n"
        "Example\n"
        "Job J-2 fails its last permitted attempt at 16:05. Orion moves J-2 to the dead-letter "
        "queue at 16:05 without operator involvement.\n"
    ),
    "J": (
        "## 10. Operator escalation\n"
        "\n"
        "Repeated dead-letter events for one tenant usually indicate a systemic fault rather than "
        "isolated bad jobs. Orion escalates to an operator when the rate of such events crosses a "
        "threshold.\n"
        "\n"
        "Normative rule\n"
        "1. When three dead-letter events occur for the same tenant within one hour, Orion must "
        "raise an operator escalation.\n"
        "2. The one-hour window must be measured from the first of the three events.\n"
        "\n"
        "Example\n"
        "Tenant T-1 accumulates dead-letter events at 10:05, 10:40 and 10:55. The third event is "
        "within one hour of the first, so an escalation is raised.\n"
    ),
    "K": (
        "## 11. Queue ordering\n"
        "\n"
        "Producers sometimes depend on jobs being executed in the order they were enqueued. Orion "
        "guarantees ordering only where it can do so without serialising the whole service.\n"
        "\n"
        "Normative rule\n"
        "1. First-in-first-out execution order must be guaranteed only among jobs in the same "
        "queue partition.\n"
        "2. No ordering guarantee is made between jobs in different partitions.\n"
        "\n"
        "Example\n"
        "Jobs J-10 and J-11 are enqueued in that order into partition P-3; J-10 begins execution "
        "before J-11. Job J-12 in partition P-4 may begin before or after either.\n"
    ),
    "L": (
        "## 12. Audit retention\n"
        "\n"
        "Every state transition of a job is recorded as an audit event. Audit events support "
        "incident investigation and tenant reporting, and are retained for a bounded period.\n"
        "\n"
        "Normative rule\n"
        "1. Audit events must be retained for thirty days after they are recorded.\n"
        "2. After thirty days an audit event may be deleted.\n"
        "\n"
        "Example\n"
        "An audit event recorded on 1 March may be deleted on or after 31 March.\n"
    ),
}

_T4: Final[dict[Locus, str]] = {
    "A": (
        "## Execution — attempt budget\n"
        "\n"
        "Orion delivers each job to a worker for execution. One delivery that ends in success, "
        "failure or timeout is an execution. Because some jobs can never succeed, the number of "
        "executions per job is capped.\n"
        "\n"
        "Normative rule\n"
        "1. Each job begins with one initial execution.\n"
        "2. If the initial execution does not succeed, the worker may perform up to three retry "
        "executions of that job.\n"
        "3. When the third retry has ended without success, no further execution of that job may "
        "be started.\n"
        "\n"
        "Example\n"
        "Job Q-31 fails on its initial execution and on three retries. Q-31 is not executed a "
        "fifth time.\n"
    ),
    "C": (
        "## Execution — time limit per execution\n"
        "\n"
        "Workers can stall. To keep a stalled worker from holding a job forever, every execution "
        "is subject to a time limit, after which the execution is treated as a failure and the "
        "retry rules take over.\n"
        "\n"
        "Normative rule\n"
        "1. An individual execution may run for no longer than half a minute; when that limit is "
        "reached the execution must be stopped.\n"
        "2. An execution stopped at the limit must be recorded as a failed attempt.\n"
        "\n"
        "Example\n"
        "Job Q-31's retry starts at 08:15:00 and is still running at 08:15:30; Orion stops it and "
        "records a failure.\n"
    ),
    "B": (
        "## Execution — delay before a retry\n"
        "\n"
        "Once an execution has failed, Orion pauses before delivering the job again so that a "
        "transient fault downstream has a chance to clear.\n"
        "\n"
        "Normative rule\n"
        "1. Before every retry attempt the worker must wait exactly five seconds, measured from "
        "the end of the failed attempt.\n"
        "2. The wait must not be shortened or lengthened based on the attempt number.\n"
        "\n"
        "Example\n"
        "Q-31's initial execution fails at 08:14:10; the first retry starts no earlier than "
        "08:14:15. Each later retry likewise starts no earlier than five seconds after the "
        "preceding failure.\n"
    ),
    "F": (
        "## Ownership — lease on a delivered job\n"
        "\n"
        "Delivering a job to a worker grants that worker a lease. The lease tells Orion the job is "
        "in hand and keeps other workers away from it.\n"
        "\n"
        "Normative rule\n"
        "1. A worker lease must last sixty seconds from the moment the job is delivered to the "
        "worker.\n"
        "2. When the lease expires without renewal or release, the job must become available to "
        "other workers.\n"
        "\n"
        "Example\n"
        "Worker W-2 receives Q-40 at 09:30:00 and goes silent. At 09:31:00 the lease lapses and "
        "Q-40 can be handed to W-5.\n"
    ),
    "G": (
        "## Ownership — keeping the lease alive\n"
        "\n"
        "A worker that is still making progress renews its lease so that the job is not reassigned "
        "underneath it.\n"
        "\n"
        "Normative rule\n"
        "1. A worker may renew its lease every thirty seconds while work on the job is "
        "progressing.\n"
        "2. A renewal must extend the lease by the full lease duration from the moment of "
        "renewal.\n"
        "\n"
        "Example\n"
        "W-2 renews Q-40's sixty-second lease at 09:30:30; the lease now ends at 09:31:30.\n"
    ),
    "H": (
        "## Ownership — cancelling a job\n"
        "\n"
        "Producers and operators can cancel jobs. Cancellation tells Orion to stop investing in "
        "the job; it does not reach into a worker and abort work already under way.\n"
        "\n"
        "Normative rule\n"
        "1. After a job is cancelled, no future execution attempt of that job may be started.\n"
        "2. Cancellation must not interrupt an execution attempt that is already running; that "
        "attempt runs to its own completion, failure or timeout.\n"
        "\n"
        "Example\n"
        "Q-40 is cancelled while its second execution is running. That execution finishes on its "
        "own terms and no further execution follows.\n"
    ),
    "D": (
        "## Input handling — repeated deliveries\n"
        "\n"
        "A producer that times out may send the same job again. Orion recognises the repeat by job "
        "id and does not run the job twice.\n"
        "\n"
        "Normative rule\n"
        "1. While a job with a given job id is active, any further delivery carrying the same job "
        "id must be ignored.\n"
        "2. Ignoring a duplicate delivery must not change the state of the active job.\n"
        "\n"
        "Example\n"
        "Q-52 is delivered at 11:00 and again at 11:02 while still active; the second delivery is "
        "dropped and Q-52 is unaffected.\n"
    ),
    "E": (
        "## Input handling — idempotency-key memory\n"
        "\n"
        "Deliveries may carry a producer-chosen idempotency key. Orion keeps recent keys so "
        "repeats can be recognised.\n"
        "\n"
        "Normative rule\n"
        "1. Orion must retain each idempotency key for twenty-four hours after it is first seen.\n"
        "2. After the retention period the key may be forgotten and a later delivery with the same "
        "key is treated as new.\n"
        "\n"
        "Example\n"
        "Key IK-77 first appears on Thursday at 13:00; it is recognised at Thursday 23:00 and "
        "forgotten by Friday 14:00.\n"
    ),
    "K": (
        "## Delivery guarantees — ordering\n"
        "\n"
        "Some producers rely on enqueue order. Orion promises order only where doing so does not "
        "serialise the whole service.\n"
        "\n"
        "Normative rule\n"
        "1. First-in-first-out execution order must be guaranteed only among jobs in the same "
        "queue partition.\n"
        "2. No ordering guarantee is made between jobs in different partitions.\n"
        "\n"
        "Example\n"
        "Q-60 then Q-61 are enqueued into partition P-1; Q-60 starts first. Q-62 in P-2 has no "
        "ordering relation to either.\n"
    ),
    "I": (
        "## Failure handling — after the last attempt\n"
        "\n"
        "A job that has spent its attempt budget without succeeding is parked for inspection "
        "rather than left blocking the queue.\n"
        "\n"
        "Normative rule\n"
        "1. After the final unsuccessful execution attempt, Orion must automatically move the job "
        "to the dead-letter queue.\n"
        "2. A job in the dead-letter queue must not be executed again unless explicitly "
        "resubmitted.\n"
        "\n"
        "Example\n"
        "Q-31 exhausts its attempts at 08:20; Orion places it in the dead-letter queue at 08:20 "
        "with no operator action.\n"
    ),
    "J": (
        "## Failure handling — alerting an operator\n"
        "\n"
        "Many dead-letter events for one tenant in a short time usually mean something systemic. "
        "Orion raises an escalation when that pattern appears.\n"
        "\n"
        "Normative rule\n"
        "1. When three dead-letter events occur for the same tenant within one hour, Orion must "
        "raise an operator escalation.\n"
        "2. The one-hour window must be measured from the first of the three events.\n"
        "\n"
        "Example\n"
        "Tenant T-7 produces dead-letter events at 08:20, 08:45 and 09:10; the third falls within "
        "an hour of the first, so an escalation is raised.\n"
    ),
    "L": (
        "## Audit — how long records are kept\n"
        "\n"
        "Each job state change produces an audit event used for investigations and tenant reports. "
        "Audit events are kept for a bounded period.\n"
        "\n"
        "Normative rule\n"
        "1. Audit events must be retained for thirty days after they are recorded.\n"
        "2. After thirty days an audit event may be deleted.\n"
        "\n"
        "Example\n"
        "An audit event written on 2 June may be removed on or after 2 July.\n"
    ),
}

_REPLACEMENTS: Final[dict[int, dict[Locus, str]]] = {
    2: {
        "C": (
            "## 3. Attempt timeout\n"
            "\n"
            "A worker that hangs must not hold a job indefinitely. Each attempt is bounded by a "
            "timeout after which the attempt is treated as failed and the retry policy applies.\n"
            "\n"
            "Normative rule\n"
            "1. An individual execution may run for no longer than half a minute; when that limit "
            "is reached the execution must be stopped.\n"
            "2. An execution stopped at the limit must be recorded as a failed attempt.\n"
            "\n"
            "Example\n"
            "An execution starts at 12:00:00 and is still running at 12:00:30. Orion stops it and "
            "records a failed attempt at 12:00:30.\n"
        ),
    },
    3: {
        "A": (
            "## 1. Execution attempts\n"
            "\n"
            "Every job admitted to Orion is executed by a worker. An execution attempt is one "
            "delivery of the job to a worker that either succeeds, fails, or times out. Orion "
            "bounds the number of attempts so that a job that cannot succeed does not consume "
            "worker capacity forever.\n"
            "\n"
            "Normative rule\n"
            "1. Each job begins with one initial execution.\n"
            "2. If the initial execution does not succeed, the worker may perform up to three "
            "retry executions of that job.\n"
            "3. When the third retry has ended without success, no further execution of that job "
            "may be started.\n"
            "\n"
            "Example\n"
            "A job's initial execution fails, and so do its first and second retries. A third "
            "retry is performed. If that retry also fails, the job has exhausted its attempts.\n"
        ),
    },
    5: {
        "B": (
            "## Execution — delay before a retry\n"
            "\n"
            "Once an execution has failed, Orion pauses before delivering the job again so that a "
            "transient fault downstream has a chance to clear. The pause grows with each failure "
            "so that a dependency under sustained pressure is not retried at a fixed cadence.\n"
            "\n"
            "Normative rule\n"
            "1. Before the first retry of a job the worker must wait two seconds, measured from "
            "the end of the failed execution.\n"
            "2. Before each later retry the worker must wait twice as long as it waited before the "
            "previous retry.\n"
            "3. The wait before any retry must never exceed thirty seconds.\n"
            "\n"
            "Example\n"
            "Q-31 fails at 08:14:10. Its first retry starts no earlier than 08:14:12; if that "
            "fails at 08:14:20 the second retry starts no earlier than 08:14:24; a subsequent wait "
            "would be eight seconds, then sixteen, then thirty (the cap).\n"
        ),
    },
    6: {
        "A": (
            "## Execution — attempt budget\n"
            "\n"
            "Orion delivers each job to a worker for execution. One delivery that ends in success, "
            "failure or timeout is an execution. Because some jobs can never succeed, the number "
            "of executions per job is capped.\n"
            "\n"
            "Normative rule\n"
            "1. One original execution of a job may be followed by no more than three retry "
            "executions.\n"
            "2. Once three retry executions have ended without success, the job must not be "
            "executed again.\n"
            "\n"
            "Example\n"
            "Q-31 is executed once and then retried three times without success. Q-31 is not "
            "executed again.\n"
        ),
    },
    7: {
        "F": (
            "## Ownership — lease on a delivered job\n"
            "\n"
            "Delivering a job to a worker grants that worker a lease. The lease tells Orion the "
            "job is in hand and keeps other workers away from it. Field experience shows that "
            "sixty seconds was too short for workers that perform a cold start before their first "
            "renewal.\n"
            "\n"
            "Normative rule\n"
            "1. A worker lease must last ninety seconds from the moment the job is delivered to "
            "the worker.\n"
            "2. When the lease expires without renewal or release, the job must become available "
            "to other workers.\n"
            "\n"
            "Example\n"
            "Worker W-2 receives Q-40 at 09:30:00 and goes silent. At 09:31:30 the lease lapses "
            "and Q-40 can be handed to W-5.\n"
        ),
    },
    8: {
        "B": (
            "## Execution — delay before a retry\n"
            "\n"
            "Once an execution has failed, Orion pauses before delivering the job again so that a "
            "transient fault downstream has a chance to clear. Operational review found that a "
            "growing pause made recovery times unpredictable for tenants; the delay is therefore a "
            "single fixed pause again.\n"
            "\n"
            "Normative rule\n"
            "1. Before every retry attempt the worker must wait exactly five seconds, measured "
            "from the end of the failed attempt.\n"
            "2. The wait must not be shortened or lengthened based on the attempt number.\n"
            "\n"
            "Example\n"
            "Q-31 fails at 08:14:10; its first retry starts no earlier than 08:14:15, and every "
            "later retry likewise starts no earlier than five seconds after the preceding "
            "failure.\n"
        ),
    },
    9: {
        "H": (
            "## Ownership — cancelling a job\n"
            "\n"
            "Producers and operators can cancel jobs. Cancellation tells Orion to stop investing "
            "in the job; it does not reach into a worker and abort work already under way. Because "
            "producers retry their own requests, Orion may receive the same cancellation more than "
            "once; a repeated cancellation is simply acknowledged.\n"
            "\n"
            "Normative rule\n"
            "1. After a job is cancelled, no future execution attempt of that job may be started.\n"
            "2. Cancellation must not interrupt an execution attempt that is already running; that "
            "attempt runs to its own completion, failure or timeout.\n"
            "3. If Orion receives a cancellation for a job that is already cancelled, the job must "
            "remain cancelled and the repeated cancellation must not otherwise change the job's "
            "state.\n"
            "\n"
            "Example\n"
            "Q-40 is cancelled while its second execution is running; that execution finishes on "
            "its own terms and no further execution follows. A second cancellation for Q-40 "
            "arrives a minute later; Q-40 stays cancelled and nothing else about Q-40 changes.\n"
        ),
    },
    10: {
        "D": (
            "## Input handling — repeated deliveries\n"
            "\n"
            "A producer that times out may send the same job again, but two deliveries that share "
            "a job id are not necessarily the same request: a producer may reuse a job id for "
            "different payloads. Orion therefore uses the idempotency key to decide whether a "
            "repeat is genuinely the same request.\n"
            "\n"
            "Normative rule\n"
            "1. While a job with a given job id is active, a further delivery must be ignored only "
            "when it carries both the same job id and the same idempotency key as the active job.\n"
            "2. A further delivery that carries the same job id but a different idempotency key "
            "must be rejected as conflicting input and must not change the state of the active "
            "job.\n"
            "\n"
            "Example\n"
            "Q-52 (key IK-1) is delivered at 11:00 and is active. A delivery of Q-52 with key IK-1 "
            "at 11:02 is ignored. A delivery of Q-52 with key IK-2 at 11:03 is rejected as "
            "conflicting.\n"
        ),
    },
    11: {
        "L": (
            "## Audit — how long records are kept\n"
            "\n"
            "Each job state change produces an audit event used for investigations and tenant "
            "reports. Audit history is kept for a bounded period so that investigations have a "
            "predictable window.\n"
            "\n"
            "Normative rule\n"
            "1. Audit history must remain queryable for one month, defined here as thirty calendar "
            "days from the moment each event is recorded.\n"
            "2. Once an event is older than that window it may be deleted.\n"
            "\n"
            "Example\n"
            "An audit event written on 2 June must remain queryable through 2 July and may be "
            "removed afterwards.\n"
        ),
    },
    12: {
        "G": (
            "## Ownership — keeping the lease alive\n"
            "\n"
            "A worker that is still making progress renews its lease so that the job is not "
            "reassigned underneath it. Renewal is driven by remaining lease life rather than a "
            "fixed cadence, and is rate-limited so that many workers cannot flood the lease "
            "service.\n"
            "\n"
            "Normative rule\n"
            "1. A worker must renew its lease when twenty seconds of lease life remain, provided "
            "work on the job is progressing.\n"
            "2. A worker must never renew the same lease more often than once every fifteen "
            "seconds.\n"
            "3. A renewal must extend the lease by the full lease duration from the moment of "
            "renewal.\n"
            "\n"
            "Example\n"
            "W-2 holds a ninety-second lease on Q-40 from 09:30:00. It renews at 09:31:10 (twenty "
            "seconds remaining); the lease now ends at 09:32:40, and W-2 may not renew again "
            "before 09:31:25.\n"
        ),
    },
    13: {
        "K": (
            "## Consistency — what order jobs run in\n"
            "\n"
            "Orion offers a narrow consistency promise about execution order. Producers that need "
            "strict sequencing place related jobs in one partition; producers that do not need it "
            "gain throughput by spreading work across partitions. The promise is deliberately "
            "limited so that a slow job in one partition never stalls the others.\n"
            "\n"
            "Normative rule\n"
            "1. First-in-first-out execution order must be guaranteed only among jobs in the same "
            "queue partition.\n"
            "2. No ordering guarantee is made between jobs in different partitions.\n"
            "\n"
            "Example\n"
            "Q-70 then Q-71 are enqueued into partition P-9; Q-70 starts first. Q-72 in P-10 may "
            "start before, between or after them.\n"
        ),
    },
    14: {
        "J": (
            "## Failure handling — alerting an operator\n"
            "\n"
            "Many dead-letter events for one tenant in a short time usually mean something "
            "systemic. The threshold is tuned so that a brief burst does not page an operator "
            "while a sustained fault does.\n"
            "\n"
            "Normative rule\n"
            "1. When five dead-letter events occur for the same tenant within any rolling "
            "thirty-minute window, Orion must raise an operator escalation.\n"
            "2. The window is rolling: at each new dead-letter event Orion must count the events "
            "for that tenant in the preceding thirty minutes, including the new event.\n"
            "\n"
            "Example\n"
            "Tenant T-7 produces dead-letter events at 08:20, 08:25, 08:31, 08:40 and 08:49. At "
            "08:49 five events fall within the preceding thirty minutes, so an escalation is "
            "raised.\n"
        ),
    },
    15: {
        "F": (
            "## Ownership — lease on a delivered job\n"
            "\n"
            "Delivering a job to a worker grants that worker a lease. The lease tells Orion the "
            "job is in hand and keeps other workers away from it.\n"
            "\n"
            "Normative rule\n"
            "1. A worker owns a delivered job for one and a half minutes unless the lease is "
            "renewed or released earlier.\n"
            "2. When that ownership period ends without renewal or release, the job must become "
            "available to other workers.\n"
            "\n"
            "Example\n"
            "Worker W-2 receives Q-40 at 09:30:00, never renews and never releases. At 09:31:30 "
            "ownership ends and Q-40 can be handed to W-5.\n"
        ),
    },
    16: {
        "I": (
            "## Failure handling — after the last attempt\n"
            "\n"
            "A job that has spent its attempt budget without succeeding needs a human decision. "
            "Automatic dead-lettering hid genuine faults from tenants; Orion now keeps the job "
            "visible in a failed state until an operator has looked at it.\n"
            "\n"
            "Normative rule\n"
            "1. After the final unsuccessful execution attempt, Orion must leave the job in the "
            "failed state.\n"
            "2. A job in the failed state must require operator review before any further action "
            "is taken on it.\n"
            "3. Orion must not automatically move a job to the dead-letter queue.\n"
            "\n"
            "Example\n"
            "Q-31 exhausts its attempts at 08:20. Q-31 remains in the failed state and appears in "
            "the operator review list; nothing moves it to the dead-letter queue automatically.\n"
        ),
    },
}


def _materialize() -> dict[tuple[int, Locus], str]:
    """Carry every locus forward version by version (spec §5: byte-identical unless replaced)."""
    texts: dict[tuple[int, Locus], str] = {}
    current = dict(_T1)
    for t in range(1, VERSION_COUNT + 1):
        if t == 4:
            current = dict(_T4)
        for locus, text in _REPLACEMENTS.get(t, {}).items():
            current[locus] = text
        for locus in LOCI:
            texts[(t, locus)] = current[locus]
    return texts


SECTION_TEXT: Final[dict[tuple[int, Locus], str]] = _materialize()


def _check_version(t: int) -> None:
    if not 1 <= t <= VERSION_COUNT:
        raise ValueError(f"version out of range 1..{VERSION_COUNT}: {t}")


def evidence_id(t: int, locus: Locus) -> str:
    """Spec §7 id law: ``EV-O-<locus><TT>``."""
    return f"EV-O-{locus}{t:02d}"


def observed_at(t: int, locus: Locus) -> datetime:
    """Spec §7: ``2026-10-<TT>T00:<pp>:00Z`` with ``pp`` the document position at ``t``."""
    return datetime(2026, 10, t, 0, DOCUMENT_ORDER[t].index(locus), tzinfo=UTC)


class LifecycleEvidence(FrozenModel):
    t: int = Field(ge=1, le=VERSION_COUNT)
    locus: Locus
    item: EvidenceItem


class EvidenceRecord(FrozenModel):
    """Structural facts only — no hidden answer-key semantics (spec §7)."""

    t: int = Field(ge=1, le=VERSION_COUNT)
    locus: Locus
    evidence_id: str = Field(min_length=1)
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    artifact_ref: str | None
    supersedes_evidence_id: str | None
    observed_at: str
    scope: tuple[str, ...]
    content_sha256: str
    content_bytes: int = Field(ge=0)


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _build_timeline() -> tuple[LifecycleEvidence, ...]:
    entries: list[LifecycleEvidence] = []
    for t in range(1, VERSION_COUNT + 1):
        for locus in DOCUMENT_ORDER[t]:
            item = evidence_item(
                evidence_id=evidence_id(t, locus),
                project_id=PROJECT_ID,
                source_kind=SourceKind.DOCUMENT,
                source_ref=f"experiment://orion/T{t:02d}/{locus}",
                content=SECTION_TEXT[(t, locus)],
                observed_at=observed_at(t, locus),
                scope=SCOPE_TUPLE,
                artifact_ref=ARTIFACT_REFS[locus],
                supersedes_evidence_id=None if t == 1 else evidence_id(t - 1, locus),
            )
            entries.append(LifecycleEvidence(t=t, locus=locus, item=item))
    return tuple(entries)


TIMELINE: Final[tuple[LifecycleEvidence, ...]] = _build_timeline()


def persistent_delta(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]:
    """Arm F/A input at ``t``: the twelve items of version ``t`` in document order.

    Only ``project_id`` is replaced; every other field is byte-identical to the
    frozen timeline item.
    """
    _check_version(t)
    return tuple(
        le.item.model_copy(update={"project_id": project_id}) for le in TIMELINE if le.t == t
    )


def reconstruction_corpus(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]:
    """Arm R input at ``t``: every item of versions ``1..t``, version order then document order."""
    _check_version(t)
    return tuple(
        le.item.model_copy(update={"project_id": project_id}) for le in TIMELINE if le.t <= t
    )


def evidence_records() -> tuple[EvidenceRecord, ...]:
    """Structural evidence facts for the manifest/artifact layer.

    Records version/locus/id/kind/ref/lineage/timestamp/scope/hash/byte-length only.
    It does not duplicate hidden answer-key semantics.
    """
    return tuple(
        EvidenceRecord(
            t=le.t,
            locus=le.locus,
            evidence_id=le.item.evidence_id,
            source_kind=le.item.source_kind,
            source_ref=le.item.source_ref,
            artifact_ref=le.item.artifact_ref,
            supersedes_evidence_id=le.item.supersedes_evidence_id,
            observed_at=_iso_z(le.item.observed_at),
            scope=le.item.scope,
            content_sha256=le.item.content_sha256,
            content_bytes=len(le.item.content.encode("utf-8")),
        )
        for le in TIMELINE
    )


def raw_evidence_character_count(t: int) -> int:
    """Spec §13: ``sum(len(content))`` over R's cumulative batch at ``t``."""
    return sum(len(item.content) for item in reconstruction_corpus(t, project_id=PROJECT_ID))


def corpus_sha256() -> str:
    """Canonical SHA256 over the structural evidence records (freeze identity, spec §19)."""
    payload = json.dumps(
        [record.model_dump(mode="json") for record in evidence_records()],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
