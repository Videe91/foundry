"""Second strategy for the trailing-newline boundary: force it by length, not by literal.

The enum-forcing probe (``test_openai_pattern_boundary_probe_live``) was inconclusive: OpenAI
strict mode refuses any ``\\n`` inside a string literal, so the disputed value cannot be named in
an ``enum``. Here nothing names it. The field is ``pattern: "^a$"`` with exactly two characters:

* under a ``$`` that also matches before a final newline (Python, PCRE, Perl), the only
  admissible string is ``"a\\n"``, so a constrained decoder must emit it;
* under an end-of-input ``$`` (ECMA-262, JSON Schema's dialect; RE2; Rust), nothing is
  admissible.

The disputed construct is the same one the production ``LOCAL_ID_PATTERN`` ends with: an
unescaped trailing ``$``. Controls make the outcome readable:

* L1 length 1 with the pattern: ``minLength``/``maxLength`` work beside ``pattern`` (expect "a").
* L2 length 3 with the pattern: impossible in every dialect; shows how OpenAI treats a field
  with no admissible string.
* T  length 2 with the pattern: the disputed case.

Reading: T returning ``"a\\n"`` is a soundness counterexample (B). T treated like L2 while L1
returns ``"a"`` is the pattern excluding the value (A). Anything else is inconclusive.

Opt-in twice: ``OPENAI_API_KEY`` and ``RUN_LIVE_OPENAI_SCHEMA_PROBE=1``. Evidence is written to
``tests/certification/evidence/_compatibility/openai/pattern_length_probe.json``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from tests.certification._certification_run import EVIDENCE_ROOT
from tests.integration.test_openai_pattern_boundary_probe_live import MODEL, _call

PROBE_PATH = EVIDENCE_ROOT / "_compatibility" / "openai" / "pattern_length_probe.json"
PATTERN = "^a$"
DISPUTED = "a\n"

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY") and os.environ.get("RUN_LIVE_OPENAI_SCHEMA_PROBE") == "1"
    ),
    reason=(
        "LIVE_OPENAI_SCHEMA_PROBE_NOT_ENABLED: set OPENAI_API_KEY and "
        "RUN_LIVE_OPENAI_SCHEMA_PROBE=1 to probe the pattern boundary"
    ),
)


def probe_schema(length: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "value": {
                "type": "string",
                "pattern": PATTERN,
                "minLength": length,
                "maxLength": length,
            }
        },
        "required": ["value"],
        "additionalProperties": False,
    }


CALLS: dict[str, dict[str, Any]] = {
    "L1_length_1": probe_schema(1),
    "L2_length_3_impossible": probe_schema(3),
    "T_length_2": probe_schema(2),
}
RESULTS: dict[str, Any] = {}


@pytest.mark.parametrize("name", list(CALLS))
def test_probe_call(name: str) -> None:
    RESULTS[name] = {"schema": CALLS[name], **_call(name, CALLS[name])}


def classify(results: dict[str, Any]) -> tuple[str, str]:
    l1, l2, t = (results[n] for n in CALLS)
    if t.get("returned_value") == DISPUTED:
        return "B_PERMITTED", "the provider emitted 'a\\n' as the only string admissible to it"
    if l1.get("returned_value") != "a":
        return "INCONCLUSIVE", "L1 did not return 'a': length keywords beside pattern unproven"
    if t.get("returned_value") is not None:
        return "INCONCLUSIVE", f"T returned {t.get('returned_value')!r}, which no dialect admits"
    same_kind = (t.get("outcome"), t.get("status_code"), t.get("status")) == (
        l2.get("outcome"),
        l2.get("status_code"),
        l2.get("status"),
    )
    if same_kind:
        return "A_EXCLUDED", "T (length 2) was treated exactly like the impossible L2 (length 3)"
    return "INCONCLUSIVE", "T was neither emitted nor treated like the impossible control"


def test_zz_record_and_classify() -> None:
    verdict, reason = classify(RESULTS)
    PROBE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROBE_PATH.write_text(
        json.dumps(
            {
                "kind": "SCHEMA_TRANSPORT_COMPATIBILITY_PROBE (not a model certification)",
                "question": "does an anchored '$' admit a trailing newline on the OpenAI wire?",
                "provider": "openai",
                "model": MODEL,
                "reasoning_effort": "high",
                "reasoning_mode": "standard",
                "pattern": PATTERN,
                "disputed_value_repr": repr(DISPUTED),
                "verdict": verdict,
                "reason": reason,
                "calls": RESULTS,
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"\nPATTERN LENGTH BOUNDARY: {verdict}: {reason}")
