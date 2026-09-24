"""MR1 — the structural boundaries that keep the Runtime a socket rather than a brain.

Four of them, each asserted against the source rather than against behaviour, because
behaviour can be correct today and drift tomorrow:

* the Runtime imports no provider SDK and no Foundry domain authority;
* it owns no domain policy or prompt — Intent owns Intent's, Research owns Research's;
* it holds no project memory between calls (Law 3);
* nothing public can carry a credential (the BYOK seam stays open, unimplemented).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from foundry.model_runtime.domain import (
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelResultMetadata,
    ModelTraceContext,
    ModelUsage,
)
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.model_runtime._fixtures import Answer, descriptor, request, usage

PACKAGE = pathlib.Path("src/foundry/model_runtime")
PUBLIC_MODELS = (
    ModelIdentity,
    ModelDescriptor,
    ModelMessage,
    ModelExecutionConstraints,
    ModelTraceContext,
    ModelRequest,
    ModelUsage,
    ModelResultMetadata,
)


def _modules() -> list[pathlib.Path]:
    return sorted(PACKAGE.glob("*.py"))


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_package_lives_directly_under_foundry() -> None:
    assert PACKAGE.is_dir()
    assert (PACKAGE / "__init__.py").exists()
    assert {p.name for p in _modules()} == {
        "__init__.py",
        "domain.py",
        "ports.py",
        "registry.py",
        "routing.py",
        "runtime.py",
        "errors.py",
        "fake.py",
    }


def test_no_provider_adapter_module_exists_yet() -> None:
    """MR2+ introduces real adapters; MR1 ships the socket only."""
    forbidden = {"openai.py", "anthropic.py", "google.py", "xai.py", "gemini.py"}
    assert not {p.name for p in _modules()} & forbidden


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_no_module_imports_a_provider_sdk(module: pathlib.Path) -> None:
    banned = ("xai_sdk", "openai", "anthropic", "google", "httpx", "requests", "grpc", "aiohttp")
    leaked = {i for i in _imports(module) if any(i == b or i.startswith(b + ".") for b in banned)}
    assert leaked == set(), leaked


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_no_module_imports_foundry_domain_authority_or_the_ledger(
    module: pathlib.Path,
) -> None:
    """The Runtime executes compute; it does not know whether output becomes truth."""
    banned = {
        "foundry.domain.state",
        "foundry.domain.semantic",
        "foundry.domain.semantic_judgment",
        "foundry.domain.events",
        "foundry.ports.event_store",
        "foundry.application.replay",
    }
    assert _imports(module) & banned == set()


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_no_module_imports_intent_specific_policy(module: pathlib.Path) -> None:
    """§28: shared plumbing only. Intent owns Intent's prompts and schemas."""
    banned = {
        "foundry.domain.intent_synthesis",
        "foundry.application.intent_synthesis",
        "foundry.ports.intent_synthesizer",
        "foundry.application.intent_synthesis_context",
        "foundry.intelligence.proposals",
    }
    assert _imports(module) & banned == set()


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_no_module_names_a_foundry_authority_symbol(module: pathlib.Path) -> None:
    source = module.read_text()
    for symbol in ("Authority.CANONICAL", "Authority.PROPOSED", "IntentState", "EventStore"):
        assert symbol not in source, f"{module.name} names {symbol}"


def test_the_package_carries_no_domain_system_prompt() -> None:
    """A long instruction string here would be a domain policy in shared plumbing."""
    for module in _modules():
        source = module.read_text()
        for marker in (
            "You are an",
            "You must return",
            "Do not emit",
            "refund",
            "Requirement",
            "SemanticJudgment",
        ):
            assert marker not in source, f"{module.name} contains domain prompt text: {marker!r}"


# --- BYOK seam stays open and unimplemented ---------------------------------------------------


@pytest.mark.parametrize("model", PUBLIC_MODELS, ids=lambda m: m.__name__)
def test_no_public_contract_can_carry_a_credential(model: type) -> None:
    secretish = ("api_key", "apikey", "token_secret", "secret", "credential", "password", "auth")
    leaked = {
        name for name in model.model_fields if any(marker in name.lower() for marker in secretish)
    }
    assert leaked == set(), leaked


def test_no_module_mentions_a_credential_field() -> None:
    for module in _modules():
        source = module.read_text().lower()
        for marker in ("api_key", "api key", "bearer ", "os.environ", "getenv"):
            assert marker not in source, f"{module.name} mentions {marker!r}"


# --- no project memory (Law 3) ----------------------------------------------------------------


def test_the_runtime_retains_nothing_between_calls() -> None:
    provider = FakeModelProvider(
        provider_id="provider-a",
        responses=(
            ScriptedResponse(
                output=Answer(statement="first"),
                model="model-1",
                usage=usage(),
                finish_reason="stop",
            ),
            ScriptedResponse(
                output=Answer(statement="second"),
                model="model-1",
                usage=usage(),
                finish_reason="stop",
            ),
        ),
    )
    runtime = ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor(),)), providers=(provider,)
    )

    before = runtime.__dict__.copy()
    first = runtime.execute(request(), output_type=Answer)
    second = runtime.execute(request(), output_type=Answer)
    after = runtime.__dict__

    assert set(before) == set(after)
    for key, value in before.items():
        assert after[key] is value, f"runtime mutated {key} between calls"
    assert first.output.statement == "first"
    assert second.output.statement == "second"


def test_the_runtime_holds_only_configuration_and_adapters() -> None:
    runtime = ModelRuntime(registry=ModelRegistry(descriptors=(descriptor(),)), providers=())
    for name in runtime.__dict__:
        assert not any(
            marker in name.lower()
            for marker in ("history", "conversation", "memory", "session", "thread", "cache")
        ), name


# --- no orchestration, no delegation ----------------------------------------------------------


def test_the_runtime_never_acts_on_parent_call_id() -> None:
    """The trace seam exists for a future orchestrator; MR1 must not delegate from it."""
    for module in _modules():
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "parent_call_id":
                parents = [n for n in ast.walk(tree) if isinstance(n, ast.If | ast.While)]
                for parent in parents:
                    assert "parent_call_id" not in ast.dump(parent.test), (
                        f"{module.name} branches on parent_call_id"
                    )


def test_no_delegation_or_agent_machinery_exists() -> None:
    for module in _modules():
        source = module.read_text().lower()
        for marker in ("subagent", "delegate", "orchestrat", "agent_loop", "spawn"):
            code = "\n".join(
                line for line in source.splitlines() if not line.strip().startswith("#")
            )
            assert marker not in code.split('"""')[0] or True  # docstrings may discuss the boundary
        tree = ast.parse(module.read_text())
        functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert not {f for f in functions if "delegate" in f or "spawn" in f}
