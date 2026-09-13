"""Non-semantic 9P3 protocol: schedule, ceilings, identities, project ids, windows (T1).

Locks the six-step arm rotation over 16 versions (48 cells), the authority
checkpoint loci, the frozen ceilings, the provider/policy/prompt/schema identities
(checked against the frozen adapter constants, never a live call), the per-arm
project ids and the early/late measurement windows. ``protocol.py`` must not import
``expectations`` (checked by parsing its source with ``ast``).
"""

from __future__ import annotations

import ast
import hashlib
import socket
from pathlib import Path

import pytest

from foundry.experiments.long_horizon_bounded import protocol as protocol_module
from foundry.experiments.long_horizon_bounded.protocol import (
    A_POLICY_VERSION,
    A_PROJECT_ID,
    A_PROMPT_SHA256,
    ARM_ORDER_BY_T,
    ARM_SCHEDULE,
    AUTHORITY_CHECKPOINTS,
    EARLY_WINDOW,
    F_PROJECT_ID,
    FR_POLICY_VERSION,
    FR_PROMPT_SHA256,
    GRPC_DNS_RESOLVER_FROZEN,
    LATE_WINDOW,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    MAX_SAME_CELL_RERUNS,
    MAX_SEMANTIC_RETRIES,
    MEASURED_WINDOW,
    MODEL,
    OUTPUT_SCHEMA_SHA256,
    PROVIDER,
    REASONING_EFFORT,
    r_project_id,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def test_arm_schedule_is_the_frozen_rotation() -> None:
    pattern = [
        ("F", "A", "R"),
        ("A", "R", "F"),
        ("R", "F", "A"),
        ("F", "R", "A"),
        ("A", "F", "R"),
        ("R", "A", "F"),
    ]
    for t in range(1, 17):
        assert ARM_ORDER_BY_T[t] == pattern[(t - 1) % 6]
    assert len(ARM_SCHEDULE) == 48
    assert ARM_SCHEDULE[:3] == ((1, "F"), (1, "A"), (1, "R"))
    assert ARM_SCHEDULE[-3:] == ((16, "F"), (16, "R"), (16, "A"))
    assert [t for t, _ in ARM_SCHEDULE] == sorted(t for t, _ in ARM_SCHEDULE)


def test_authority_checkpoints_and_budgets_are_exact() -> None:
    assert AUTHORITY_CHECKPOINTS == {
        3: "A",
        5: "B",
        7: "F",
        8: "B",
        10: "D",
        12: "G",
        14: "J",
        16: "I",
    }
    assert (
        MAX_FRONTIER_CALLS,
        MAX_JUDGE_CALLS,
        MAX_SEMANTIC_RETRIES,
        MAX_SAME_CELL_RERUNS,
        MAX_HUMAN_AUTHORIZATIONS,
        MAX_COST_USD,
    ) == (96, 0, 0, 0, 48, 10.0)
    assert MAX_FRONTIER_CALLS == 16 * 3 * 2


def test_identities_match_the_frozen_adapter() -> None:
    from foundry.adapters.semantics import xai_reasoner as x

    assert FR_POLICY_VERSION == x.CONTRASTIVE_POLICY_VERSION == "intent-v2-9p2-v1"
    assert A_POLICY_VERSION == x.POLICY_VERSION == "intent-v2-9p-v4"
    assert hashlib.sha256(x.CONTRASTIVE_SYSTEM_INSTRUCTION.encode()).hexdigest() == FR_PROMPT_SHA256
    assert hashlib.sha256(x.SYSTEM_INSTRUCTION.encode()).hexdigest() == A_PROMPT_SHA256
    assert x.semantic_output_schema_sha256() == OUTPUT_SCHEMA_SHA256
    assert (PROVIDER, MODEL, REASONING_EFFORT, GRPC_DNS_RESOLVER_FROZEN) == (
        "xai",
        "grok-4.6",
        "high",
        "native",
    )


def test_project_ids_and_windows() -> None:
    assert (F_PROJECT_ID, A_PROJECT_ID, r_project_id(7)) == (
        "PROJ-9P3-F",
        "PROJ-9P3-A",
        "PROJ-9P3-R-T07",
    )
    assert EARLY_WINDOW == (2, 3, 4, 5)
    assert LATE_WINDOW == (13, 14, 15, 16)
    assert tuple(range(2, 17)) == MEASURED_WINDOW


def test_protocol_does_not_import_expectations() -> None:
    tree = ast.parse(Path(protocol_module.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not any("expectations" in m for m in mods)
