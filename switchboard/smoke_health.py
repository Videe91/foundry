"""Packet: T-008 / R-028 — provider health, told apart from configuration.

One job: decide whether a provider error is a CAPACITY condition (nothing is
misconfigured; retry later) or a real failure (something must be fixed).

A leaf module on purpose: both the ping gate and the matrix need this taxonomy
and must agree on it. The matrix got it under R-028 while the ping gate kept
treating an outage as a config error — blocking a whole nine-model run with the
advice "fix registry.toml" when there was nothing to fix (T-008).

Version: 0.10.2
"""

from __future__ import annotations

# Matched on the provider's own words, not the exception class: LiteLLM wrapped
# the identical Opus-5 overload as MidStreamFallbackError when streaming and
# InternalServerError when blocking.
_UNAVAILABLE_MARKERS = (
    "overloaded",
    "service unavailable",
    "internalservererror",
    "serviceunavailable",
    "capacity",
    "502",
    "503",
    "529",
)


def is_unavailable(error: BaseException | str) -> bool:
    """True when the provider could not serve us, whatever the model can do.

    Deliberately narrow. A matcher that called every error transient would hide
    exactly the defects these instruments exist to find — T-004's MIME
    rejection, T-006's pixel floor, and a model ID that does not exist all
    reach us as provider errors too, and every one of them needed a fix.
    """
    return any(marker in str(error).lower() for marker in _UNAVAILABLE_MARKERS)
