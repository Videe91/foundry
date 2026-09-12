"""9P2 T2: deterministic bounded old-to-new evidence diff.

Spec §10, plan §4. ``render_unified_diff`` is a *transport* representation of an
evidence transition, not a semantic judgment: standard-library ``difflib.unified_diff``
over ``content.splitlines()``, exactly three unchanged context lines per hunk,
evidence-id labels, deterministic output, and a hard support bound of exactly
65,536 rendered Unicode characters. Nothing here normalizes, ranks hunks, truncates,
summarizes, classifies, or calls a model. The tests below lock that shape.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from foundry.application import context_errors, contrastive_diff
from foundry.application.context_errors import ContextUnsupported
from foundry.application.contrastive_diff import (
    DIFF_CONTEXT_LINES,
    MAX_TRANSITION_DIFF_CHARS,
    render_unified_diff,
)
from foundry.domain.common import SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item

PROJECT = "proj-9p2"
T0 = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)

SEMANTIC_LABEL_TOKENS = ("CORRECTION", "SUPPORT", "CONFLICT", "NEW")


def _ev(evidence_id: str, content: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"repo://{evidence_id}",
        content=content,
        observed_at=T0,
    )


OLD_LINES = [f"line {i} unchanged" for i in range(1, 10)]
NEW_LINES = list(OLD_LINES)
NEW_LINES[4] = "line 5 changed"
OLD_TEXT = "\n".join(OLD_LINES)
NEW_TEXT = "\n".join(NEW_LINES)


# --- constants and error type ------------------------------------------------------


def test_constants_are_locked() -> None:
    assert DIFF_CONTEXT_LINES == 3
    assert MAX_TRANSITION_DIFF_CHARS == 65_536


def test_context_unsupported_is_runtime_error_and_module_exposes_only_it() -> None:
    assert issubclass(ContextUnsupported, RuntimeError)
    public = [name for name in dir(context_errors) if not name.startswith("_")]
    assert public == ["ContextUnsupported"]
    assert ContextUnsupported.__doc__ == (
        "The exact structurally selected context exceeds a locked support bound."
    )


# --- headers, context, determinism, identity ----------------------------------------


def test_headers_are_evidence_id_labels() -> None:
    rendered = render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))
    lines = rendered.split("\n")
    assert lines[0] == "--- evidence:EV-old"
    assert lines[1] == "+++ evidence:EV-new"


def test_three_unchanged_context_lines_per_hunk_when_available() -> None:
    rendered = render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))
    lines = rendered.split("\n")
    assert lines[2] == "@@ -2,7 +2,7 @@"
    hunk = lines[3:]
    assert len(hunk) == 8
    assert hunk[0:3] == [" line 2 unchanged", " line 3 unchanged", " line 4 unchanged"]
    assert hunk[3] == "-line 5 unchanged"
    assert hunk[4] == "+line 5 changed"
    assert hunk[5:8] == [" line 6 unchanged", " line 7 unchanged", " line 8 unchanged"]
    # lines 1 and 9 fall outside the three-line window and are not shown
    assert " line 1 unchanged" not in lines
    assert " line 9 unchanged" not in lines


def test_output_is_exactly_stdlib_unified_diff_shape() -> None:
    old, new = _ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT)
    expected = "\n".join(
        difflib.unified_diff(
            OLD_TEXT.splitlines(),
            NEW_TEXT.splitlines(),
            fromfile="evidence:EV-old",
            tofile="evidence:EV-new",
            n=3,
            lineterm="",
        )
    )
    assert render_unified_diff(old, new) == expected
    assert not render_unified_diff(old, new).endswith("\n")


def test_deterministic_repeat_output() -> None:
    old, new = _ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT)
    first = render_unified_diff(old, new)
    second = render_unified_diff(old, new)
    assert first == second
    assert first == render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))


def test_identical_content_renders_empty_string() -> None:
    assert render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", OLD_TEXT)) == ""


# --- support bound: exactly 65,536 allowed, 65,537 refused ---------------------------


def _install_fixed_size_diff(
    monkeypatch: pytest.MonkeyPatch, first_len: int, second_len: int
) -> list[dict[str, Any]]:
    """Replace ``difflib.unified_diff`` as seen by the module with a fake yielding two lines.

    The rendered string is ``first_len + 1 + second_len`` characters, so the boundary is
    exact, including the single ``"\\n"`` join separator.
    """
    calls: list[dict[str, Any]] = []

    def fake_unified_diff(a: Any, b: Any, **kwargs: Any) -> Iterator[str]:
        calls.append({"a": a, "b": b, **kwargs})
        yield "x" * first_len
        yield "y" * second_len

    monkeypatch.setattr(contrastive_diff.difflib, "unified_diff", fake_unified_diff)
    return calls


def test_exactly_max_chars_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fixed_size_diff(monkeypatch, 32_768, 32_767)
    rendered = render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))
    assert len(rendered) == 65_536
    assert rendered == "x" * 32_768 + "\n" + "y" * 32_767
    assert calls == [
        {
            "a": OLD_TEXT.splitlines(),
            "b": NEW_TEXT.splitlines(),
            "fromfile": "evidence:EV-old",
            "tofile": "evidence:EV-new",
            "n": 3,
            "lineterm": "",
        }
    ]


def test_one_over_max_chars_is_refused_before_any_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fixed_size_diff(monkeypatch, 32_768, 32_768)
    with pytest.raises(ContextUnsupported) as excinfo:
        render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))
    message = str(excinfo.value)
    assert message.startswith("UNSUPPORTED_TRANSITION_DIFF: ")
    assert message == (
        "UNSUPPORTED_TRANSITION_DIFF: rendered diff has 65537 characters; maximum is 65536"
    )


def test_bound_counts_unicode_characters_not_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_unified_diff(a: Any, b: Any, **kwargs: Any) -> Iterator[str]:
        yield "é" * 65_536  # 65,536 characters, 131,072 UTF-8 bytes

    monkeypatch.setattr(contrastive_diff.difflib, "unified_diff", fake_unified_diff)
    rendered = render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))
    assert len(rendered) == 65_536


# --- no semantic labels, no mutation -------------------------------------------------


def test_no_semantic_labels_added_and_only_unified_diff_lines() -> None:
    rendered = render_unified_diff(_ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT))
    for token in SEMANTIC_LABEL_TOKENS:
        assert token not in rendered
    allowed_prefixes = ("--- ", "+++ ", "@@ ", " ", "-", "+")
    for line in rendered.split("\n"):
        assert line.startswith(allowed_prefixes), line


def test_evidence_objects_are_not_mutated() -> None:
    old, new = _ev("EV-old", OLD_TEXT), _ev("EV-new", NEW_TEXT)
    old_before, new_before = old.model_dump(), new.model_dump()
    render_unified_diff(old, new)
    assert old.model_dump() == old_before
    assert new.model_dump() == new_before
    assert old.content == OLD_TEXT
    assert new.content == NEW_TEXT
