"""Packet: P-007 — Family Two: OpenAI Adapter.

One job: test the smoke script's ping and prove logic offline, with fakes.

The R-020 wiring guard lives in test_smoke_wiring.py — split out under R-018's
standing pre-authorization when this file reached the 300-line ceiling.

No network, no keys, no dotenv import.

Version: 0.7.0
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from conftest import FREE, FakeCompletion

from smoke_families import (demo_role_for, families_in, family_has_adapter,
                            input_price_of)
from smoke import (
    EXCLUDED_FROM_PROVE,
    SMOKE_DEPARTMENT,
    SMOKE_PROJECT,
    ping_model,
    print_ping_table,
    ping_registry,
    prove_roles,
    unique_models,
)
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute, load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.toml"
SHARED = "anthropic/claude-haiku-4-5-20251001"
SONNET = "anthropic/claude-sonnet-5"

SMOKE_REGISTRY = ModelRegistry(
    roles={
        "architect": RoleRoute(
            model=SONNET, fallbacks=[SHARED], max_tokens=128000, effort="xhigh"
        ),
        "architect_max": RoleRoute(
            model="anthropic/claude-fable-5", fallbacks=[SONNET], max_tokens=128000
        ),
        "judge": RoleRoute(model=SONNET, fallbacks=[SHARED], max_tokens=128000),
        "floor_agent": RoleRoute(model=SHARED, fallbacks=[SONNET], max_tokens=64000),
        "default": RoleRoute(model=SHARED, fallbacks=[], max_tokens=64000),
    }
)


def test_ping_model_reports_ok() -> None:
    result = ping_model(SHARED, FakeCompletion())
    assert result.ok is True
    assert result.model == SHARED
    assert result.error is None


def test_ping_model_reports_failure_without_raising() -> None:
    result = ping_model(SHARED, FakeCompletion(failing=(SHARED,)))
    assert result.ok is False
    assert "unavailable" in result.error


def test_ping_uses_a_minimal_call() -> None:
    fake = FakeCompletion()
    ping_model(SHARED, fake)
    assert fake.calls[0]["max_tokens"] == 8


def test_unique_models_deduplicates_across_roles() -> None:
    models = unique_models(SMOKE_REGISTRY)
    assert sorted(models) == sorted({SHARED, SONNET, "anthropic/claude-fable-5"})


def test_ping_registry_pings_each_model_exactly_once() -> None:
    fake = FakeCompletion()
    results = ping_registry(SMOKE_REGISTRY, fake)
    assert len(fake.calls) == 3
    assert len(results) == 3
    assert all(result.ok for result in results)


def test_prove_roles_skips_default_and_the_escalation_tier(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    responses = prove_roles(SMOKE_REGISTRY, ledger, FakeCompletion(), FREE)
    proven = [response.tags.role for response in responses]
    assert proven == ["architect", "judge", "floor_agent"]
    assert all(role not in proven for role in EXCLUDED_FROM_PROVE)


def test_prove_roles_writes_one_meter_record_per_proven_role(
    tmp_path: Path,
) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    prove_roles(SMOKE_REGISTRY, ledger, FakeCompletion(), FREE)
    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]
    assert [record["tags"]["role"] for record in records] == [
        "architect",
        "judge",
        "floor_agent",
    ]
    assert all(
        record["tags"]["project_id"] == SMOKE_PROJECT
        and record["tags"]["department"] == SMOKE_DEPARTMENT
        for record in records
    )


# --- P-007: family-aware smoke logic --------------------------------------

TWO_FAMILY_REGISTRY = ModelRegistry(
    roles={
        "floor_agent": RoleRoute(model=SHARED, fallbacks=[], max_tokens=64000),
        "architect": RoleRoute(model=SONNET, fallbacks=[], max_tokens=128000),
        "judge": RoleRoute(
            model="openai/gpt-5.6-terra", fallbacks=[], max_tokens=128000
        ),
        "scribe": RoleRoute(model="mistral/large", fallbacks=[], max_tokens=8000),
    }
)


def test_families_are_the_unique_primary_prefixes() -> None:
    assert families_in(TWO_FAMILY_REGISTRY) == ["anthropic", "openai", "mistral"]


def _registry(*roles: tuple[str, str, int]) -> ModelRegistry:
    return ModelRegistry(
        roles={
            name: RoleRoute(model=model, fallbacks=[], max_tokens=ceiling)
            for name, model, ceiling in roles
        }
    )


@pytest.fixture
def stub_cost_map(monkeypatch: pytest.MonkeyPatch):
    """Install a fake cost map — the fast tests never touch the real one."""

    def install(prices: dict[str, float]) -> None:
        module = types.ModuleType("litellm")
        module.model_cost = {
            key: {"input_cost_per_token": price} for key, price in prices.items()
        }
        monkeypatch.setitem(sys.modules, "litellm", module)

    return install


def test_demo_role_is_the_cheapest_priced_model(stub_cost_map) -> None:
    """The retired proxy would pick `pricey` here — it has the lower ceiling."""
    stub_cost_map({"cheap-model": 1e-06, "pricey-model": 2e-06})
    registry = _registry(
        ("pricey", "anthropic/pricey-model", 64000),
        ("cheap", "anthropic/cheap-model", 128000),
    )
    assert demo_role_for(registry, "anthropic") == "cheap"


def test_unpriced_model_sorts_last(stub_cost_map) -> None:
    stub_cost_map({"priced-model": 9e-06})
    registry = _registry(
        ("unpriced", "anthropic/absent-model", 1000),
        ("priced", "anthropic/priced-model", 128000),
    )
    assert demo_role_for(registry, "anthropic") == "priced"


def test_all_unpriced_family_falls_back_to_max_tokens(stub_cost_map) -> None:
    """The demo still runs when nothing in the family is priced."""
    stub_cost_map({})
    registry = _registry(
        ("big", "vendor/model-a", 128000),
        ("small", "vendor/model-b", 8000),
    )
    assert demo_role_for(registry, "vendor") == "small"


def test_equal_price_breaks_by_declaration_order(stub_cost_map) -> None:
    stub_cost_map({"twin-a": 3e-06, "twin-b": 3e-06})
    registry = _registry(
        ("first", "anthropic/twin-a", 128000),
        ("second", "anthropic/twin-b", 8000),
    )
    assert demo_role_for(registry, "anthropic") == "first"


def test_the_real_cost_map_prices_every_shipped_model() -> None:
    """R-022-style: the prefix-stripping lookup works against the real map.

    Structure, not values (R-014) — the human may repoint any role.
    """
    registry = load_registry(REGISTRY_PATH)
    for name, route in registry.roles.items():
        price = input_price_of(route.model)
        assert price is not None and price > 0, f"{name}: {route.model} unpriced"


def test_adapterless_family_is_reported_as_such() -> None:
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "anthropic") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "openai") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "mistral") is False


def test_unpriced_model_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract 7: unpriced is a warning, not a gate."""
    fake = FakeCompletion()
    result = ping_model("vendor/not-a-real-model", fake)
    assert result.ok is True
    assert result.priced is False


def test_priced_model_is_recognised() -> None:
    assert ping_model("anthropic/claude-haiku-4-5-20251001", FakeCompletion()).priced


def test_ping_table_renders_the_pricing_warning(capsys: pytest.CaptureFixture) -> None:
    fake = FakeCompletion()
    print_ping_table(
        [ping_model("vendor/not-a-real-model", fake), ping_model(SHARED, fake)]
    )
    out = capsys.readouterr().out
    assert "UNPRICED — update litellm pin" in out
    assert "(priced)" in out
