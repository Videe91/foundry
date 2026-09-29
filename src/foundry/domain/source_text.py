"""Deterministic sentence segmentation of evidence text (IE2 v2 design §7.1.3).

Structural, not semantic: it decides where sentences begin and end, never what they mean or
whether they matter. Sealed validations use it to build their source-coverage maps; the
proposition-accounting policy uses it to give every sentence of accountable evidence a stable
id that a claim-writing response must account for.

Rules: headings (``#``) and blank lines carry no sentence; list enumerators (``1.``, ``2)``,
``-``, ``*``, ``Q:``) are removed; a line with no ``.``/``!``/``?`` is a bare label
("Rules", "Example") and carries none; a sentence ends at ``.``/``!``/``?`` followed by space
and a capital, digit, quote or parenthesis, so an abbreviation inside a sentence
("2 p.m. local time") never splits it.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["numbered_sentences", "sentence_id", "source_sentences"]

_ENUMERATOR: Final = re.compile(r"^(?:\d+[.)]|[-*]|[A-Z]:)\s+")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def source_sentences(text: str) -> tuple[str, ...]:
    """Every sentence of ``text``, in order, with list enumerators removed."""
    sentences: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _ENUMERATOR.sub("", line)
        if not re.search(r"[.!?]", line):
            continue  # a bare label ("Rules", "Normative rule", "Example")
        sentences.extend(part.strip() for part in _SENTENCE_END.split(line) if part.strip())
    return tuple(sentences)


def sentence_id(evidence_id: str, position: int) -> str:
    """The stable id of the ``position``-th (1-based) sentence of an evidence item."""
    return f"{evidence_id}#S{position}"


def numbered_sentences(evidence_id: str, text: str) -> tuple[tuple[str, str], ...]:
    """``(sentence_id, sentence)`` for every sentence of one evidence item, in order."""
    return tuple(
        (sentence_id(evidence_id, n), sentence)
        for n, sentence in enumerate(source_sentences(text), start=1)
    )
