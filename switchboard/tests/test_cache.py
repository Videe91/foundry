"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: test cache-token extraction from each family's usage shape.

Created under R-018's standing pre-authorization when test_router.py reached
the 300-line ceiling; the cache tests moved here from that file.

Shapes are transformation- or docs-verified per R-019/R-022 and cited.

Version: 0.9.0
"""

from __future__ import annotations

from types import SimpleNamespace

from conftest import FREE, REGISTRY, FakeCompletion, fixed_cost, make_request

from switchboard.router import route_call

def _litellm_shaped(prompt: int, cached: int, creation: int) -> object:
    """Usage shape LiteLLM builds for Anthropic (T-002): BOTH a nested
    prompt_tokens_details AND top-level cache_* fields. cached from the
    wrapper, creation from the top level."""
    usage = SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=20, total_tokens=prompt + 20,
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=cached, cache_creation_tokens=creation
        ),
        cache_creation_input_tokens=creation, cache_read_input_tokens=cached,
    )
    choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    return SimpleNamespace(choices=[choice], usage=usage)


def test_cache_write_is_read_from_the_real_litellm_shape() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _litellm_shaped(3721, 0, 3721), FREE
    )
    assert response.usage.cache_creation_tokens == 3721
    assert response.usage.cached_tokens == 0


def test_cache_read_is_read_from_the_real_litellm_shape() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _litellm_shaped(3721, 3721, 0), FREE
    )
    assert response.usage.cached_tokens == 3721
    assert response.usage.cache_creation_tokens == 0


def test_cache_token_fields_default_to_zero_when_absent() -> None:
    response = route_call(make_request(), REGISTRY, FakeCompletion(), FREE)
    assert response.usage.cached_tokens == 0
    assert response.usage.cache_creation_tokens == 0


# --- OpenAI usage shape ---------------------------------------------------


def _openai_shaped(prompt: int, cached: int) -> object:
    """The usage shape OpenAI reports.

    Cached reads arrive under prompt_tokens_details.cached_tokens — the same
    path the extractor already reads for Anthropic — and OpenAI reports no
    cache-creation counter, so that field stays absent.
    """
    usage = SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=20,
        total_tokens=prompt + 20,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage
    )


def test_openai_cached_tokens_are_extracted() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _openai_shaped(2048, 1024), FREE
    )
    assert response.usage.cached_tokens == 1024
    assert response.usage.prompt_tokens == 2048


def test_openai_absent_cache_creation_reads_as_zero() -> None:
    """OpenAI reports no creation counter; the extractor must not invent one."""
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _openai_shaped(2048, 0), FREE
    )
    assert response.usage.cache_creation_tokens == 0
    assert response.usage.cached_tokens == 0


# --- Gemini usage shape (P-008 contract 5) --------------------------------


def _gemini_shaped(prompt: int, cached: int) -> object:
    """The usage shape LiteLLM builds for Gemini.

    Gemini reports cached prefix tokens as `cachedContentTokenCount`, which
    LiteLLM normalises into `prompt_tokens_details.cached_tokens` — the same
    path Anthropic and OpenAI already use, so the extractor needs no change.
    """
    usage = SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=20,
        total_tokens=prompt + 20,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage
    )


def test_gemini_cached_tokens_are_extracted() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _gemini_shaped(4096, 2048), FREE
    )
    assert response.usage.cached_tokens == 2048
    assert response.usage.prompt_tokens == 4096


def test_gemini_reports_no_cache_creation_counter() -> None:
    """Implicit caching only — there is no creation counter to invent."""
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _gemini_shaped(4096, 0), FREE
    )
    assert response.usage.cache_creation_tokens == 0


# --- xAI usage shape (P-009 contracts 6 and 7) ----------------------------


def _xai_shaped(prompt: int, cached: int, ticks: int | None = None) -> object:
    """The usage shape LiteLLM builds for xai models.

    xAI's API is OpenAI-compatible, so cached input arrives at the same
    `prompt_tokens_details.cached_tokens` path the extractor already reads —
    no router change. `ticks` is the optional extra described in contract 6.
    """
    details = SimpleNamespace(cached_tokens=cached)
    usage = SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=20,
        total_tokens=prompt + 20,
        prompt_tokens_details=details,
    )
    if ticks is not None:
        usage.cost_in_usd_ticks = ticks
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage
    )


def test_xai_cached_tokens_are_extracted() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _xai_shaped(4096, 1024), FREE
    )
    assert response.usage.cached_tokens == 1024
    assert response.usage.prompt_tokens == 4096


def test_an_unknown_ticks_field_is_ignored_rather_than_guessed_at() -> None:
    """Contract 6: `cost_in_usd_ticks` is absent from litellm 1.97.0.

    A grep of the installed package finds the field nowhere, so there is no
    observed shape to parse and no speculative parsing was built (R-024 note).
    This pins the safe half: if a future litellm starts surfacing it, the
    extractor carries on and cost still comes from the cost function — it does
    not crash, and it does not silently mistake ticks for dollars.
    """
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _xai_shaped(4096, 0, ticks=1234),
        fixed_cost(0.5),
    )
    assert response.usage.total_tokens == 4116
    assert response.usage.cost_usd == 0.5
