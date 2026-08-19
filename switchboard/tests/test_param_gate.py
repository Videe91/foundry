"""Packet: T-010 / R-035 — acceptance has three layers.

One job: the R-030 sweep. For every family we ship, every parameter our
adapters and router actually send must either pass LiteLLM's supported-params
gate, or be listed below with a citation for why we send it anyway.

The point is that the NEXT parameter meets this wall offline, in a test, rather
than in a live run at PROVE 1 (which is how T-010 was found).

Version: 0.15.1
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smoke import unique_models
from smoke_families import families_in, family_of
from switchboard.param_gate import supported_params_for
from switchboard.registry import load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.toml"

# Every parameter route_call can put on the wire, and when.
SENT_PARAMS: dict[str, str] = {
    "max_tokens": "every call, from the role's ceiling",
    "stream": "every call — streaming is the default since P-010",
    "stream_options": "every streamed call, so usage rides the terminal chunk",
    "reasoning_effort": "when the role sets an effort",
    "tools": "when the request carries a web_search spec (P-015)",
}

# (family, param) pairs the gate refuses that we send ANYWAY, each with the
# live evidence that justifies it. A pair may only live here with a citation —
# "it seems to work" is not an entry.
LIVE_PROVEN: dict[tuple[str, str], str] = {
    ("anthropic", "stream_options"): (
        "Live since P-010: every streamed Anthropic call carries it and the "
        "terminal chunk returns usage. Proven again on the four-family "
        "certificate (2026-08-18) and every cache demo since — without it the "
        "run reported tokens=0/0, which is what R-018 exists to remember."
    ),
    ("gemini", "stream_options"): (
        "Live on the four-family certificate (2026-08-18): the streamed Gemini "
        "call returned a terminal usage chunk. Same mechanism as Anthropic — "
        "LiteLLM handles stream_options above the per-provider param list."
    ),
}

# Parameters we never send to a family, so the gate's opinion is moot. Enforced
# by code, not by convention — each entry names what enforces it.
NEVER_SENT: dict[tuple[str, str], str] = {
    ("openrouter", "reasoning_effort"): (
        "T-010: load_registry rejects any openrouter role that sets an effort, "
        "so this parameter cannot reach the wire for this family."
    ),
}


def _shipped_families() -> list[str]:
    return families_in(load_registry(REGISTRY_PATH))


def _one_model_per_family() -> dict[str, str]:
    models: dict[str, str] = {}
    for model in unique_models(load_registry(REGISTRY_PATH)):
        models.setdefault(family_of(model), model)
    return models


PAIRS = [
    (family, model, param)
    for family, model in _one_model_per_family().items()
    for param in SENT_PARAMS
]


@pytest.mark.parametrize(
    ("family", "model", "param"), PAIRS,
    ids=[f"{f}-{p}" for f, _m, p in PAIRS],
)
def test_every_parameter_we_send_clears_the_gate_or_is_accounted_for(
    family: str, model: str, param: str
) -> None:
    """The wall. A parameter that fails the gate and has no entry below is a
    call this family cannot make — found here, not at PROVE 1."""
    if param in supported_params_for(model):
        return
    key = (family, param)
    justification = LIVE_PROVEN.get(key) or NEVER_SENT.get(key)
    assert justification, (
        f"LiteLLM's supported-params gate refuses '{param}' for the '{family}' "
        f"family, and nothing accounts for it. Either we must not send it "
        f"(add to NEVER_SENT with what enforces that), or there is live proof "
        f"it works anyway (add to LIVE_PROVEN with the citation). This is the "
        f"T-010 wall — see R-035."
    )


def test_the_sweep_actually_reaches_every_shipped_family() -> None:
    """A sweep that swept nothing would pass in silence."""
    covered = {family for family, _model, _param in PAIRS}
    assert covered == set(_shipped_families())
    assert len(covered) >= 5, "five families ship today"


def test_the_sweep_would_catch_a_new_refusal() -> None:
    """Discriminating: prove the wall is load-bearing rather than decorative.

    A parameter LiteLLM refuses for every family, with no entry in either
    table, must fail the check — otherwise the sweep is a formality.
    """
    invented = "definitely_not_a_real_openai_param"
    model = _one_model_per_family()["anthropic"]
    assert invented not in supported_params_for(model)
    assert (("anthropic", invented) not in LIVE_PROVEN
            and ("anthropic", invented) not in NEVER_SENT)


def test_every_accounted_pair_is_still_actually_refused() -> None:
    """The tables must not outlive their reason.

    If LiteLLM starts supporting one of these, the entry becomes a lie sitting
    in a test file — so the entry itself expires when the refusal does.
    """
    models = _one_model_per_family()
    for family, param in {**LIVE_PROVEN, **NEVER_SENT}:
        model = models.get(family)
        if model is None:
            continue
        assert param not in supported_params_for(model), (
            f"'{param}' is now supported for '{family}' — remove the entry, "
            f"the exception it documents no longer exists"
        )


def test_every_justification_carries_a_citation() -> None:
    """'It seems to work' is not an entry."""
    for key, text in LIVE_PROVEN.items():
        assert any(mark in text for mark in ("P-0", "R-0", "20")), key
    for key, text in NEVER_SENT.items():
        assert any(mark in text for mark in ("T-0", "R-0")), key
