"""Does OpenAI Structured Outputs admit ``"a\\n"`` under the production ``local_id`` pattern?

SCHEMA TRANSPORT COMPATIBILITY, not model certification. The earlier probe only showed that a
model asked for ``"a\\n"`` returned ``"a"``, which cannot tell a constrained decoder from a
compliant model. Here the value is *forced*: a one-field strict schema whose ``enum`` holds only
the disputed string, intersected with the exact production ``LOCAL_ID_PATTERN``. The model has no
choice to make, so what comes back is the provider's own verdict on the pattern.

Four calls, raw SDK (no Foundry parsing, so nothing downstream can mask the provider's
behaviour), same endpoint and configuration as the certification contestant:

* C1 enum ``["a\\n"]``, no pattern: the newline value can be forced at all.
* C2 enum ``["a"]`` + pattern: ``enum`` and ``pattern`` together are accepted and honoured.
* C3 enum ``["A"]`` + pattern: how a plainly violating enum/pattern intersection is treated.
* T  enum ``["a\\n"]`` + pattern: the disputed boundary.

Reading: T returning ``"a\\n"`` is a soundness counterexample (B). T behaving like C3 while C1
and C2 behave as controls should is the pattern excluding the value (A). Anything else is
inconclusive, and is recorded as such.

Opt-in twice: ``OPENAI_API_KEY`` and ``RUN_LIVE_OPENAI_SCHEMA_PROBE=1``. Evidence is written to
``tests/certification/evidence/_compatibility/openai/pattern_boundary_probe.json``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import openai
import pytest

from foundry.domain.intent_graph import LOCAL_ID_PATTERN
from tests.certification._certification_run import EVIDENCE_ROOT

MODEL = "gpt-6-astra"
PROBE_PATH = EVIDENCE_ROOT / "_compatibility" / "openai" / "pattern_boundary_probe.json"
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


def probe_schema(enum: list[str], pattern: str | None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "string", "enum": enum}
    if pattern is not None:
        value["pattern"] = pattern
    return {
        "type": "object",
        "properties": {"value": value},
        "required": ["value"],
        "additionalProperties": False,
    }


CALLS: dict[str, dict[str, Any]] = {
    "C1_enum_newline_no_pattern": probe_schema([DISPUTED], None),
    "C2_enum_a_with_pattern": probe_schema(["a"], LOCAL_ID_PATTERN),
    "C3_enum_uppercase_with_pattern": probe_schema(["A"], LOCAL_ID_PATTERN),
    "T_enum_newline_with_pattern": probe_schema([DISPUTED], LOCAL_ID_PATTERN),
}
RESULTS: dict[str, Any] = {}


def _call(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)
    try:
        response = client.responses.create(
            model=MODEL,
            input=[
                {
                    "role": "user",
                    "content": "Return the JSON object required by the schema.",
                }
            ],
            text={
                "format": {"type": "json_schema", "name": "Probe", "strict": True, "schema": schema}
            },
            reasoning={"effort": "high", "mode": "standard", "context": "current_turn"},
            store=False,
            tools=[],
            max_output_tokens=4000,
            timeout=180.0,
        )
    except openai.APIStatusError as exc:
        return {
            "outcome": "API_REJECTED",
            "status_code": exc.status_code,
            "error": str(exc),
        }
    except openai.APIError as exc:
        return {"outcome": "TRANSPORT_FAILURE", "error": f"{type(exc).__name__}: {exc}"}
    texts = [
        content.text
        for item in response.output or []
        if item.type == "message"
        for content in item.content or []
        if content.type == "output_text"
    ]
    returned: Any = None
    if texts:
        try:
            returned = json.loads(texts[0]).get("value")
        except (json.JSONDecodeError, AttributeError):
            returned = None
    return {
        "outcome": "RESPONDED",
        "status": response.status,
        "incomplete_reason": getattr(response.incomplete_details, "reason", None),
        "executed_model": response.model,
        "raw_output_texts": texts,
        "returned_value": returned,
        "returned_value_repr": repr(returned),
    }


@pytest.mark.parametrize("name", list(CALLS))
def test_probe_call(name: str) -> None:
    RESULTS[name] = {"schema": CALLS[name], **_call(name, CALLS[name])}


def classify(results: dict[str, Any]) -> tuple[str, str]:
    c1, c2, c3, t = (results[n] for n in CALLS)
    if t.get("returned_value") == DISPUTED:
        return "B_PERMITTED", "the provider returned the disputed value under the pattern"
    if c1.get("returned_value") != DISPUTED:
        return "INCONCLUSIVE", "C1 did not return the newline value, so it cannot be forced"
    if c2.get("returned_value") != "a":
        return "INCONCLUSIVE", "C2 did not honour enum and pattern together"
    if c3.get("returned_value") == "A":
        return "INCONCLUSIVE", "C3 returned an enum value that violates the pattern: enum wins"
    same_kind = t.get("outcome") == c3.get("outcome") and t.get("status_code") == c3.get(
        "status_code"
    )
    if same_kind:
        return "A_EXCLUDED", "T was treated exactly like the plainly violating C3"
    return "INCONCLUSIVE", "T was neither returned nor treated like C3"


def test_zz_record_and_classify() -> None:
    verdict, reason = classify(RESULTS)
    PROBE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROBE_PATH.write_text(
        json.dumps(
            {
                "kind": "SCHEMA_TRANSPORT_COMPATIBILITY_PROBE (not a model certification)",
                "question": "does the production local_id pattern admit 'a\\n' on the OpenAI wire?",
                "provider": "openai",
                "model": MODEL,
                "reasoning_effort": "high",
                "reasoning_mode": "standard",
                "pattern": LOCAL_ID_PATTERN,
                "disputed_value_repr": repr(DISPUTED),
                "verdict": verdict,
                "reason": reason,
                "calls": RESULTS,
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"\nPATTERN BOUNDARY: {verdict}: {reason}")
