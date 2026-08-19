"""Packet: T-010 / R-035 — acceptance layer one: the middleware's gate.

One job: answer what LiteLLM will forward for a given model's family.

`litellm.completion` checks every request against this set BEFORE the family's
transformation runs, so a parameter missing here never reaches the code our
R-022 checks exercise. That is the layer T-010 fell through — the transformation
carried `reasoning_effort` for openrouter perfectly well, and the call still
could not be made.

Layer one is NECESSARY but not SUFFICIENT: `stream_options` fails this gate for
anthropic and gemini and has worked live on every streamed call since P-010.
See tests/test_param_gate.py, which demands live evidence for such pairs rather
than treating this module as the final word.

Version: 0.15.1
"""

from __future__ import annotations


def supported_params_for(model: str) -> frozenset[str]:
    """What LiteLLM will forward for this model's family.

    `litellm.completion` checks a request against this set BEFORE the family's
    transformation runs, so a parameter missing here never reaches the code our
    R-022 checks exercise (T-010).

    Permissive on any uncertainty — an unknown model, a provider LiteLLM cannot
    place, an empty answer — because this gate exists to catch a known refusal,
    not to invent new ones. Returning "everything is allowed" degrades to the
    behaviour we had before the gate existed.
    """
    family, _, bare = model.partition("/")
    if not bare:
        return _EVERYTHING
    try:
        from litellm import get_supported_openai_params

        params = get_supported_openai_params(model=bare, custom_llm_provider=family)
    except Exception:
        return _EVERYTHING
    return frozenset(params) if params else _EVERYTHING


class _Everything(frozenset):
    """A set that contains anything asked of it."""

    def __contains__(self, _item: object) -> bool:
        return True


_EVERYTHING = _Everything()


def accepts_effort_param(model: str) -> bool:
    """Whether LiteLLM will forward `reasoning_effort` for this family at all.

    Distinct from `effort_levels_for`, which answers WHICH levels a family
    accepts. R-035 narrows R-031 on exactly this line: an aggregator declares no
    level vocabulary, but whether the parameter can be SENT is family-level
    knowledge, discoverable offline, and validated at load.
    """
    return "reasoning_effort" in supported_params_for(model)
