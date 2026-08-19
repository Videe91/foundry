"""Packet: P-016 — Research Both Ways.

One job: test the web-search capability — spec validation, the rendered tool
block, the family gate (including down the fallback chain), usage extraction,
and that an ordinary call is untouched.

R-024 honesty: the R-022 checks below prove the block survives LiteLLM's real
Anthropic transformation. They do NOT prove Anthropic accepts it — the live
smoke run (PROVE 5) is the acceptance gate.

Version: 0.16.0
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import FREE, REGISTRY, FakeCompletion, make_request, provider

from switchboard.adapters_search import (
    WEB_SEARCH_TOOL_NAME,
    WEB_SEARCH_TOOL_TYPE,
    search_tool_for,
    supports_search,
)
from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.request import WebSearchSpec
from switchboard.router import ProviderCallError, route_call

ANTHROPIC = "anthropic/claude-sonnet-5"
OPENAI = "openai/gpt-5.6-terra"


def _registry(model: str, fallbacks: list[str] | None = None) -> ModelRegistry:
    return ModelRegistry(roles={"builder": RoleRoute(
        model=model, fallbacks=fallbacks or [], max_tokens=4096)})


def _searched(**kwargs):
    return make_request(web_search=WebSearchSpec(**kwargs))


# --- contract 1: spec validation at the model ------------------------------


def test_both_domain_lists_together_are_refused_naming_both() -> None:
    """Anthropic's docs: an allow list OR a block list, never both."""
    with pytest.raises(Exception) as excinfo:
        WebSearchSpec(allowed_domains=["a.com"], blocked_domains=["b.com"])
    message = str(excinfo.value)
    assert "allowed_domains" in message and "blocked_domains" in message


@pytest.mark.parametrize("value", [0, -1, 21, 100])
def test_max_uses_bounds_are_enforced(value: int) -> None:
    with pytest.raises(Exception):
        WebSearchSpec(max_uses=value)


@pytest.mark.parametrize("value", [1, 5, 20])
def test_max_uses_accepts_the_documented_range(value: int) -> None:
    assert WebSearchSpec(max_uses=value).max_uses == value


def test_either_list_alone_is_fine() -> None:
    assert WebSearchSpec(allowed_domains=["a.com"]).allowed_domains == ["a.com"]
    assert WebSearchSpec(blocked_domains=["b.com"]).blocked_domains == ["b.com"]


def test_the_default_is_a_ceiling_not_a_target() -> None:
    """Documented on the spec because every use is billed."""
    assert WebSearchSpec().max_uses == 5
    assert "billed" in WebSearchSpec.__doc__


# --- contract 2: rendering (R-022) -----------------------------------------


def test_a_minimal_spec_renders_exactly_the_documented_block() -> None:
    block = search_tool_for(ANTHROPIC, WebSearchSpec(max_uses=3))
    assert block == {
        "type": WEB_SEARCH_TOOL_TYPE, "name": WEB_SEARCH_TOOL_NAME, "max_uses": 3
    }


def test_empty_optionals_are_omitted_entirely_never_sent_empty() -> None:
    """`"allowed_domains": []` reads to a provider as "allow nothing", which is
    the opposite of "no restriction"."""
    block = search_tool_for(ANTHROPIC, WebSearchSpec())
    assert "allowed_domains" not in block
    assert "blocked_domains" not in block
    assert "user_location" not in block


def test_a_full_spec_carries_every_field() -> None:
    spec = WebSearchSpec(max_uses=2, blocked_domains=["spam.example"],
                         user_location={"type": "approximate", "country": "GB"})
    block = search_tool_for(ANTHROPIC, spec)
    assert block["blocked_domains"] == ["spam.example"]
    assert block["user_location"] == {"type": "approximate", "country": "GB"}


def test_the_tool_block_survives_anthropics_real_transformation() -> None:
    """R-022, cited: LiteLLM's AnthropicConfig.transform_request in
    litellm/llms/anthropic/chat/transformation.py carries the block verbatim.

    R-024: this proves fidelity, not acceptance. PROVE 5 is the gate.
    """
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    block = search_tool_for(ANTHROPIC, WebSearchSpec(max_uses=2))
    body = AnthropicConfig().transform_request(
        model="claude-sonnet-5",
        messages=[{"role": "user", "content": "what is the base rate?"}],
        optional_params={"tools": [block]},
        litellm_params={}, headers={},
    )
    assert body["tools"] == [block]
    assert body["tools"][0]["type"] == WEB_SEARCH_TOOL_TYPE


# --- contract 3: the family gate -------------------------------------------


def test_only_the_anthropic_family_can_search_today() -> None:
    assert supports_search(ANTHROPIC) is True
    for model in (OPENAI, "gemini/gemini-3.7-flash", "xai/grok-4.6",
                  "openrouter/moonshotai/kimi-k3", "mistral/large"):
        assert supports_search(model) is False, model


def test_the_gate_is_capability_driven_not_a_family_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A future family opens the gate by DEFINING search_tool.

    Proven behaviourally rather than by grepping for family names: a stand-in
    adapter that can search opens the gate under a model string that is not
    Anthropic's, which a hardcoded list could not do.
    """
    import switchboard.adapters_search as module

    class Searching:
        def search_tool(self, spec: object) -> dict:
            return {"type": "future", "max_uses": spec.max_uses}

    monkeypatch.setattr(module, "adapter_for", lambda _model: Searching())
    assert module.supports_search("future/model-1") is True
    assert module.search_tool_for("future/model-1", WebSearchSpec(max_uses=2)) == {
        "type": "future", "max_uses": 2
    }


def test_a_searched_request_to_a_family_without_search_is_refused() -> None:
    fake = FakeCompletion()
    with pytest.raises(ProviderCallError) as excinfo:
        route_call(_searched(), _registry(OPENAI), fake, FREE)
    message = str(excinfo.value)
    assert "openai" in message and "web search" in message
    assert fake.calls == [], "the provider was called anyway"


def test_a_searched_request_to_anthropic_carries_the_tools_kwarg() -> None:
    fake = FakeCompletion()
    route_call(_searched(max_uses=4), _registry(ANTHROPIC), fake, FREE)
    tools = fake.calls[0]["tools"]
    assert tools == [{"type": WEB_SEARCH_TOOL_TYPE,
                      "name": WEB_SEARCH_TOOL_NAME, "max_uses": 4}]


def test_a_fallback_that_cannot_search_fails_the_gate_too() -> None:
    """The never-silently-drop law applied to capability: a searched request
    must not become an unsearched one by falling back."""
    fake = FakeCompletion(failing=(ANTHROPIC,))
    with pytest.raises(ProviderCallError) as excinfo:
        route_call(_searched(), _registry(ANTHROPIC, [OPENAI]), fake, FREE)
    message = str(excinfo.value)
    assert ANTHROPIC in message and OPENAI in message
    assert [c["model"] for c in fake.calls] == [ANTHROPIC], "openai was called"


def test_an_unsearched_request_still_falls_back_normally() -> None:
    """Discriminating: the gate must not break ordinary fallback."""
    fake = FakeCompletion(failing=(ANTHROPIC,))
    response = route_call(make_request(), _registry(ANTHROPIC, [OPENAI]), fake, FREE)
    assert response.model_used == OPENAI


# --- contract 7: an ordinary call is untouched -----------------------------


def test_a_request_without_search_sends_no_tools_kwarg_at_all() -> None:
    """Absence, not emptiness — the R-018 pattern."""
    fake = FakeCompletion()
    route_call(make_request(), REGISTRY, fake, FREE)
    assert "tools" not in fake.calls[0]


def test_an_unsearched_call_reports_zero_searches() -> None:
    response = route_call(make_request(), REGISTRY, FakeCompletion(), FREE)
    assert response.usage.web_search_requests == 0


# --- contract 4: usage extraction (R-019, discovered not guessed) ----------


def _usage_with_searches(count: int | None) -> object:
    """The shape litellm 1.97.0 really builds.

    Discovered offline: litellm.types.utils.Usage carries `server_tool_use`,
    and litellm.types.utils.ServerToolUse declares `web_search_requests`.
    """
    usage = SimpleNamespace(
        prompt_tokens=1000, completion_tokens=50, total_tokens=1050,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    if count is not None:
        usage.server_tool_use = SimpleNamespace(web_search_requests=count)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage
    )


def test_the_search_count_is_read_from_the_real_path() -> None:
    response = route_call(
        make_request(), REGISTRY, provider(_usage_with_searches(3)), FREE
    )
    assert response.usage.web_search_requests == 3


def test_an_absent_server_tool_section_reads_as_zero_never_crashes() -> None:
    response = route_call(
        make_request(), REGISTRY, provider(_usage_with_searches(None)), FREE
    )
    assert response.usage.web_search_requests == 0


def test_the_streamed_terminal_chunk_carries_the_count_too() -> None:
    """Contract 6: search must work on both paths. The interviewer streams."""
    usage = SimpleNamespace(
        prompt_tokens=1000, completion_tokens=50, total_tokens=1050,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        server_tool_use=SimpleNamespace(web_search_requests=2),
    )

    def stream_fake(**_kwargs: object) -> object:
        def emit() -> object:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="answer"))]
            )
            yield SimpleNamespace(choices=[], usage=usage)
        return emit()

    received: list[str] = []
    response = route_call(make_request(), REGISTRY, stream_fake, FREE, None,
                          received.append)
    assert received == ["answer"]
    assert response.content == "answer"
    assert response.usage.web_search_requests == 2


# --- contract 5: the meter carries it --------------------------------------


def test_a_receipt_with_searches_round_trips_through_the_ledger(tmp_path) -> None:
    from switchboard.meter import MeterLedger, MeterRecord

    ledger = MeterLedger(tmp_path / "meter.jsonl")
    route_call(make_request(), REGISTRY, provider(_usage_with_searches(4)),
               FREE, ledger)
    restored = MeterRecord.model_validate_json(
        ledger.path.read_text(encoding="utf-8").strip()
    )
    assert restored.usage.web_search_requests == 4


def test_the_receipt_field_defaults_to_zero_for_every_old_record() -> None:
    """Every meter line written before P-015 lacks the field entirely."""
    from switchboard.meter import MeterRecord

    old = (
        '{"tags":{"project_id":"p","department":"intent","role":"scribe",'
        '"packet_id":null,"ticket_id":null,"attempt_number":null},'
        '"model_used":"anthropic/claude-sonnet-5",'
        '"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12,'
        '"cost_usd":0.1,"cached_tokens":0,"cache_creation_tokens":0},'
        '"recorded_at":"2026-08-18T18:29:50.971682Z"}'
    )
    assert MeterRecord.model_validate_json(old).usage.web_search_requests == 0
