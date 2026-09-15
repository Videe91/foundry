"""Locus-validation protocol literals (T2): version, identities, ceilings, schedule.

Every literal is pinned verbatim against the plan (spec §8 gates 4–8 and 11, §12
ceilings, §17 historical preservation, §18 call budget) and, where an in-process
source of truth exists, against the frozen adapter constants -- never a live call.
``protocol.py`` is a request-path module: it must not import the hidden answer key
or any grading module (checked by parsing its source with ``ast``).
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from foundry.adapters.semantics import xai_reasoner as adapter
from foundry.application.incremental_assimilation import CALLS_PER_DELTA as APPLICATION_CALLS
from foundry.experiments.locus_validation import corpus as corpus_module
from foundry.experiments.locus_validation import protocol as protocol_module
from foundry.experiments.locus_validation.protocol import (
    ARTIFACT_FORMAT_VERSION,
    BASELINE_SHA,
    CALLS_PER_DELTA,
    CALLS_PER_LEDGER,
    CEILING_KEYS,
    DELTAS,
    DESIGN_BASE_SHA,
    EXPERIMENT_ARTIFACT_DIR,
    EXPERIMENT_VERSION,
    GRPC_DNS_RESOLVER_ENV,
    GRPC_DNS_RESOLVER_FROZEN,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PROMPT_SHA256S,
    LEDGERS,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    MAX_SAME_CELL_RERUNS,
    MAX_SEMANTIC_RETRIES,
    MODEL,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    POLICY_VERSION_FROZEN,
    PREDECESSOR_ADJUDICATION_SHA,
    PREDECESSOR_ARTIFACT_DIR,
    PREDECESSOR_RAW_RUN_SHA,
    PREREGISTRATION_FILE_NAMES,
    PROJECT_IDS,
    PROMPT_SHA256_FROZEN,
    PROVIDER,
    REASONING_EFFORT,
    SCOPES,
)
from foundry.experiments.long_horizon_bounded import integrity as predecessor_integrity

REPO_ROOT = Path(__file__).resolve().parents[2]
FORTY_HEX = re.compile(r"^[0-9a-f]{40}$")
SIXTY_FOUR_HEX = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_provider_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    yield
    assert "XAI_API_KEY" not in os.environ


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- experiment identity ------------------------------------------------------------


def test_experiment_version_and_artifact_format_are_the_plan_literals() -> None:
    assert EXPERIMENT_VERSION == "intent-v2-locus-validation-v1"
    assert ARTIFACT_FORMAT_VERSION == 1
    assert EXPERIMENT_ARTIFACT_DIR == "docs/superpowers/experiments/2026-09-15-locus-validation-v1/"
    assert PREREGISTRATION_FILE_NAMES == ("manifest.json", "expectations.json")


def test_git_identities_are_forty_hex_literals() -> None:
    assert BASELINE_SHA == "b34b987454c942965fa09a556725693896ecc426"
    assert DESIGN_BASE_SHA == "1441e2e0f56a34ebfc8ccdf9a60cfdf95c1d0696"
    assert PREDECESSOR_RAW_RUN_SHA == "f045612e9ec9917b73649175cf08f91f087f2828"
    assert PREDECESSOR_ADJUDICATION_SHA == "3c30c16193dae6a9a03fe630f2ca33bf2a2e8c13"
    for sha in (
        BASELINE_SHA,
        DESIGN_BASE_SHA,
        PREDECESSOR_RAW_RUN_SHA,
        PREDECESSOR_ADJUDICATION_SHA,
    ):
        assert FORTY_HEX.fullmatch(sha), sha


def test_historical_artifact_dirs_are_the_seven_frozen_directories() -> None:
    assert len(HISTORICAL_ARTIFACT_DIRS) == 7
    assert HISTORICAL_ARTIFACT_DIRS[:6] == predecessor_integrity.HISTORICAL_ARTIFACT_DIRS
    assert HISTORICAL_ARTIFACT_DIRS == (
        "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
        "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
        "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
        "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
        "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
        "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
        "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/",
    )
    assert len(set(HISTORICAL_ARTIFACT_DIRS)) == 7
    for directory in HISTORICAL_ARTIFACT_DIRS:
        assert directory.endswith("/"), directory
        assert (REPO_ROOT / directory).is_dir(), directory
    assert HISTORICAL_ARTIFACT_DIRS[6] == PREDECESSOR_ARTIFACT_DIR


# --- provider / policy identities -------------------------------------------------


def test_provider_model_effort_and_resolver_are_frozen() -> None:
    assert (PROVIDER, MODEL, REASONING_EFFORT) == ("xai", "grok-4.6", "high")
    assert PROVIDER == adapter.PROVIDER
    assert MODEL == adapter.DEFAULT_MODEL
    assert (GRPC_DNS_RESOLVER_ENV, GRPC_DNS_RESOLVER_FROZEN) == ("GRPC_DNS_RESOLVER", "native")


def test_locus_policy_version_equals_the_in_process_adapter_constant() -> None:
    assert POLICY_VERSION_FROZEN == "intent-v2-locus-v1"
    assert POLICY_VERSION_FROZEN == adapter.LOCUS_POLICY_VERSION


def test_locus_prompt_hash_equals_the_pasted_literal_and_the_live_instruction() -> None:
    assert PROMPT_SHA256_FROZEN == (
        "e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1"
    )
    assert PROMPT_SHA256_FROZEN == adapter.LOCUS_SYSTEM_INSTRUCTION_SHA256
    assert _sha256(adapter.LOCUS_SYSTEM_INSTRUCTION) == PROMPT_SHA256_FROZEN


def test_output_schema_hash_equals_the_in_process_schema() -> None:
    assert OUTPUT_SCHEMA_SHA256_FROZEN == (
        "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
    )
    assert OUTPUT_SCHEMA_SHA256_FROZEN == adapter.SEMANTIC_OUTPUT_SCHEMA_SHA256
    assert adapter.semantic_output_schema_sha256() == OUTPUT_SCHEMA_SHA256_FROZEN


def test_historical_prompts_are_unchanged() -> None:
    assert HISTORICAL_PROMPT_SHA256S == {
        "intent-v2-9p-v4": "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1",
        "intent-v2-9p2-v1": "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410",
    }
    assert HISTORICAL_PROMPT_SHA256S[adapter.POLICY_VERSION] == adapter.SYSTEM_INSTRUCTION_SHA256
    assert HISTORICAL_PROMPT_SHA256S[adapter.POLICY_VERSION] == _sha256(adapter.SYSTEM_INSTRUCTION)
    assert (
        HISTORICAL_PROMPT_SHA256S[adapter.CONTRASTIVE_POLICY_VERSION]
        == adapter.CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    )
    assert HISTORICAL_PROMPT_SHA256S[adapter.CONTRASTIVE_POLICY_VERSION] == _sha256(
        adapter.CONTRASTIVE_SYSTEM_INSTRUCTION
    )
    for sha in HISTORICAL_PROMPT_SHA256S.values():
        assert SIXTY_FOUR_HEX.fullmatch(sha)


# --- ceilings and call budget ------------------------------------------------------


def test_ceilings_are_eight_zero_zero_zero_zero_two() -> None:
    assert (
        MAX_FRONTIER_CALLS,
        MAX_JUDGE_CALLS,
        MAX_SEMANTIC_RETRIES,
        MAX_SAME_CELL_RERUNS,
        MAX_HUMAN_AUTHORIZATIONS,
    ) == (8, 0, 0, 0, 0)
    assert MAX_COST_USD == 2.0
    assert isinstance(MAX_COST_USD, float)


def test_ceiling_keys_are_the_manifest_order() -> None:
    assert CEILING_KEYS == (
        "max_frontier_calls",
        "max_judge_calls",
        "max_semantic_retries",
        "max_same_cell_reruns",
        "max_human_authorizations",
        "max_provider_cost_usd",
    )


def test_call_budget_is_two_ledgers_times_two_deltas_times_two_calls() -> None:
    assert CALLS_PER_DELTA == 2
    assert CALLS_PER_DELTA is APPLICATION_CALLS
    assert DELTAS == (1, 2)
    assert CALLS_PER_LEDGER == 4
    assert len(DELTAS) * CALLS_PER_DELTA == CALLS_PER_LEDGER
    assert len(LEDGERS) * CALLS_PER_LEDGER == MAX_FRONTIER_CALLS


# --- ledger identities re-exported from the corpus ------------------------------


def test_ledger_scope_and_project_ids_are_the_corpus_values() -> None:
    assert LEDGERS == ("alpha", "beta")
    assert LEDGERS is corpus_module.LEDGERS
    assert PROJECT_IDS is corpus_module.PROJECT_IDS
    assert SCOPES is corpus_module.SCOPES
    assert protocol_module.Ledger is corpus_module.Ledger
    assert PROJECT_IDS == {"alpha": "PROJ-LV-ALPHA", "beta": "PROJ-LV-BETA"}
    assert SCOPES == {"alpha": "keyring", "beta": "relay"}


# --- request-path hygiene --------------------------------------------------------


def test_protocol_never_imports_the_answer_key_or_a_grading_module() -> None:
    tree = ast.parse(Path(protocol_module.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    package = "foundry.experiments.locus_validation."
    for name in ("expectations", "evaluation", "leakage", "integrity", "artifacts"):
        assert package + name not in mods, name
    allowed_foundry = {
        "foundry.application.incremental_assimilation",
        "foundry.experiments.locus_validation.corpus",
    }
    assert {m for m in mods if m.startswith("foundry")} <= allowed_foundry


def test_public_names_are_declared() -> None:
    exported = set(protocol_module.__all__)
    for name in (
        "EXPERIMENT_VERSION",
        "DESIGN_BASE_SHA",
        "HISTORICAL_ARTIFACT_DIRS",
        "CALLS_PER_DELTA",
        "CEILING_KEYS",
        "Ledger",
        "LEDGERS",
    ):
        assert name in exported, name
    assert exported <= set(vars(protocol_module))
