"""Non-semantic protocol for the 9P3 long-horizon bounded-memory experiment.

Spec §8 (arm identities), §9 (arm order), §14.2 (measurement windows), §17
(budgets and provider defaults) and §18 (authority checkpoint loci). This module
owns only schedule, ceiling, identity and project-id data: which arm runs when,
how many calls may ever be made, which frozen policy/prompt/schema each arm must
present, and at which versions a persistent arm may receive mechanical authority.
It decides nothing semantic and carries no answer key; it imports ``timeline``
only for the ``Locus`` type and must never import ``expectations``. Every value is
a literal locked in the approved spec.
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.experiments.long_horizon_bounded.timeline import Locus

__all__ = [
    "A_POLICY_VERSION",
    "A_PROJECT_ID",
    "A_PROMPT_SHA256",
    "ARM_ORDER_BY_T",
    "ARM_SCHEDULE",
    "AUTHORITY_CHECKPOINTS",
    "EARLY_WINDOW",
    "F_PROJECT_ID",
    "FR_POLICY_VERSION",
    "FR_PROMPT_SHA256",
    "FROZEN_CORE_SHA",
    "GRPC_DNS_RESOLVER_ENV",
    "GRPC_DNS_RESOLVER_FROZEN",
    "LATE_WINDOW",
    "MAX_COST_USD",
    "MAX_FRONTIER_CALLS",
    "MAX_HUMAN_AUTHORIZATIONS",
    "MAX_JUDGE_CALLS",
    "MAX_SAME_CELL_RERUNS",
    "MAX_SEMANTIC_RETRIES",
    "MEASURED_WINDOW",
    "MODEL",
    "OUTPUT_SCHEMA_SHA256",
    "PREDECESSOR_RAW_EVIDENCE_SHA",
    "PROVIDER",
    "REASONING_EFFORT",
    "Arm",
    "r_project_id",
]

Arm = Literal["F", "A", "R"]

# --- §9 arm order: six-step rotation, repeated deterministically -----------------

_ROTATION: Final[tuple[tuple[Arm, Arm, Arm], ...]] = (
    ("F", "A", "R"),
    ("A", "R", "F"),
    ("R", "F", "A"),
    ("F", "R", "A"),
    ("A", "F", "R"),
    ("R", "A", "F"),
)

ARM_ORDER_BY_T: Final[dict[int, tuple[Arm, Arm, Arm]]] = {
    t: _ROTATION[(t - 1) % len(_ROTATION)] for t in range(1, 17)
}

ARM_SCHEDULE: Final[tuple[tuple[int, Arm], ...]] = tuple(
    (t, arm) for t in range(1, 17) for arm in ARM_ORDER_BY_T[t]
)

# --- §18 authority checkpoints: correction and revert transitions only ------------

AUTHORITY_CHECKPOINTS: Final[dict[int, Locus]] = {
    3: "A",
    5: "B",
    7: "F",
    8: "B",
    10: "D",
    12: "G",
    14: "J",
    16: "I",
}

# --- §17 budgets ---------------------------------------------------------------------

MAX_FRONTIER_CALLS: Final[int] = 96
MAX_JUDGE_CALLS: Final[int] = 0
MAX_SEMANTIC_RETRIES: Final[int] = 0
MAX_SAME_CELL_RERUNS: Final[int] = 0
MAX_HUMAN_AUTHORIZATIONS: Final[int] = 48
MAX_COST_USD: Final = 10.0

# --- §8/§17 provider defaults and frozen identities -----------------------------------

PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"

FR_POLICY_VERSION: Final = "intent-v2-9p2-v1"
FR_PROMPT_SHA256: Final = "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410"
A_POLICY_VERSION: Final = "intent-v2-9p-v4"
A_PROMPT_SHA256: Final = "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
OUTPUT_SCHEMA_SHA256: Final = "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
FROZEN_CORE_SHA: Final = "1f89fc86cda463da676bf45603b86a7dcb458452"
PREDECESSOR_RAW_EVIDENCE_SHA: Final = "201198f60c51e16269451e7d582027361d7e8a24"

# --- §7 arm-distinct governor project ids ---------------------------------------------

F_PROJECT_ID: Final = "PROJ-9P3-F"
A_PROJECT_ID: Final = "PROJ-9P3-A"


def r_project_id(t: int) -> str:
    """Arm R uses a fresh store and governor at every ``t`` (spec §8)."""
    return f"PROJ-9P3-R-T{t:02d}"


# --- §14 measurement windows -----------------------------------------------------------

EARLY_WINDOW: Final[tuple[int, ...]] = (2, 3, 4, 5)
LATE_WINDOW: Final[tuple[int, ...]] = (13, 14, 15, 16)
MEASURED_WINDOW: Final[tuple[int, ...]] = tuple(range(2, 17))
