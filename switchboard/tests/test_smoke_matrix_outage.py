"""Packet: R-028 — an outage is not a capability failure.

One job: test that the matrix tells a provider-capacity condition apart from a
real capability failure — UNAVAILABLE rather than FAIL, after one bounded retry,
and never at the cost of stopping the sweep.

Split from test_smoke_matrix.py under the R-017 precedent when these tests
pushed it past the 300-line ceiling. Per R-026 the split inherits its parent's
map entries.

Version: 0.10.1
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from smoke_matrix import KINDS, OK, UNAVAILABLE, is_unavailable, render_matrix
from test_smoke_matrix import ALL_MODELS, SHARED, MatrixFake, _sweep

# --- R-028: an outage is not a capability failure -------------------------


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry delay is 20s in production; tests must not actually wait."""
    import smoke_matrix

    monkeypatch.setattr(smoke_matrix, "RETRY_DELAY_SECONDS", 0.0)


@pytest.mark.parametrize(
    "message",
    [
        "litellm.InternalServerError: AnthropicError - Overloaded",
        '{"type":"overloaded_error","message":"Overloaded"}',
        "litellm.MidStreamFallbackError: ... Overloaded",
        "ServiceUnavailable: 503",
        "provider returned 529",
    ],
)
def test_capacity_errors_are_recognised_however_litellm_wraps_them(
    message: str,
) -> None:
    """The same Opus-5 condition arrived as MidStreamFallbackError when
    streaming and InternalServerError when blocking, so the class name cannot
    be the test — the provider's words are."""
    assert is_unavailable(RuntimeError(message))


@pytest.mark.parametrize(
    "message",
    [
        "Invalid file data: unsupported MIME type 'text/plain'",
        "Image has 256 total pixels (16x16), which is below the minimum",
        "Model not found: grok-4.1-fast",
    ],
)
def test_real_capability_failures_are_not_mistaken_for_outages(
    message: str,
) -> None:
    """Discriminating: every one of these is a genuine defect we have actually
    hit (T-004, T-006, the bad fallback ID). None may render as UNAVAILABLE."""
    assert not is_unavailable(RuntimeError(message))


class FlakyFake(MatrixFake):
    """Fails with a capacity error N times, then succeeds."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.remaining = failures

    def __call__(self, **kwargs: Any) -> Any:
        if self.remaining > 0:
            self.remaining -= 1
            raise RuntimeError("litellm.InternalServerError - Overloaded")
        return super().__call__(**kwargs)


def test_one_bounded_retry_rescues_a_transient_blip(tmp_path: Path) -> None:
    fake = FlakyFake(failures=1)
    rows = _sweep(tmp_path, fake, [SHARED])
    assert rows[0].cells["image"] == OK


def test_a_sustained_outage_records_unavailable_not_fail(tmp_path: Path) -> None:
    """The Opus-5 case: five FAIL cells read as 'cannot do attachments'."""
    rows = _sweep(tmp_path, FlakyFake(failures=99), [SHARED])
    cells = rows[0].cells
    for column in (*KINDS, "cache c1", "cache c2"):
        assert cells[column] == UNAVAILABLE, column
    assert not any(c.startswith("FAIL(") for c in cells.values())


def test_unavailable_renders_plainly_with_no_footnote(tmp_path: Path) -> None:
    """UNAVAILABLE is short and self-explanatory; only FAIL needs a footnote."""
    grid = render_matrix(_sweep(tmp_path, FlakyFake(failures=99), [SHARED]))
    assert UNAVAILABLE in grid
    assert "failures" not in grid
    assert "FAIL[" not in grid


def test_an_outage_never_stops_the_sweep(tmp_path: Path) -> None:
    rows = _sweep(tmp_path, FlakyFake(failures=99))
    assert [row.model for row in rows] == ALL_MODELS
