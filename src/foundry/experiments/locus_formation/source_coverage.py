"""Source coverage for sealed proposition inventories (IE2 v2 design §7.1.2, v3 lesson).

Locus validation v3 sealed an inventory that listed 9P3 H-T9's numbered rules but not its
prose sentence "a repeated cancellation is simply acknowledged"; the live model stated it
and the independent adjudicator correctly failed the claim for saying something the
inventory lacked. The defect was the inventory's, and deterministic code cannot decide which
prose is semantically operative. What it can enforce is that nothing is skipped silently:

* ``source_sentences`` splits a document into its sentences (headings and bare labels such
  as ``Rules`` or ``Example`` carry no sentence and are dropped);
* a future harness gives every sentence a ``SentenceAccount``: the proposition ids it
  carries, or an explicit reason it carries none (for example, an illustrative example
  that restates listed rules);
* ``coverage_findings`` reports every sentence with no account, every account naming no
  sentence of the document, and every account with neither propositions nor a reason.

It never calls a model and is never part of admission.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from foundry.domain.common import FrozenModel

__all__ = ["SentenceAccount", "coverage_findings", "source_sentences"]

_ENUMERATOR: Final = re.compile(r"^(?:\d+[.)]|[-*]|[A-Z]:)\s+")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
"""A sentence ends at ``.``/``!``/``?`` followed by space and a capital, digit, quote or
parenthesis, so an abbreviation inside a sentence ("2 p.m. local time") never splits it."""


class SentenceAccount(FrozenModel):
    sentence: str
    propositions: tuple[str, ...] = ()
    non_operative_reason: str | None = None
    """Why the sentence carries no proposition; required when ``propositions`` is empty."""


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


def coverage_findings(text: str, accounts: Iterable[SentenceAccount]) -> tuple[str, ...]:
    sentences = source_sentences(text)
    accounted = list(accounts)
    findings = [
        f"UNACCOUNTED_SENTENCE: {s!r}"
        for s in sentences
        if not any(a.sentence == s for a in accounted)
    ]
    for account in accounted:
        if account.sentence not in sentences:
            findings.append(f"UNKNOWN_SENTENCE: {account.sentence!r}")
        if not account.propositions and not account.non_operative_reason:
            findings.append(f"UNJUSTIFIED_OMISSION: {account.sentence!r}")
    return tuple(findings)
