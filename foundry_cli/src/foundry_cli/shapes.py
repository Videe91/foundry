"""Packet: T-012 — the Scribe's box-content shape.

One job: get a model's reply into a shape the completeness rules can READ, or
say precisely why it cannot be.

Split from brains.py under the R-017 precedent when the shape checks pushed it
past the 300-line ceiling. Per R-026 the split inherits its parent's map
entries.

Version: 0.1.0
"""

from __future__ import annotations

import json
from typing import Any

from intent.state import ScribeUpdate


# The wrapper the live Scribe produced (T-012): it mirrored the BoxState shape
# it is SHOWN in "Current boxes" instead of returning the box's own schema.
_WRAPPER_MARKERS = frozenset({"status", "proposed_by"})


def unwrap_box_content(key: str, content: Any) -> tuple[dict[str, Any] | None, str]:
    """Return (content, problem). Exactly one is meaningful.

    Recoverable: a wrapper whose inner `content` is itself an object — unwrap it
    and carry on, because the extraction is there and only the envelope is
    wrong.

    Not recoverable: a wrapper around a bare string, which is what the live
    Scribe produced. Completeness cannot read it, so it is REJECTED rather than
    stored — a box that can never satisfy its rule is worse than an empty one,
    since it looks answered.
    """
    if not isinstance(content, dict):
        return None, f"box '{key}': content must be an object, got {type(content).__name__}"
    if _WRAPPER_MARKERS & set(content) and "content" in content:
        inner = content["content"]
        if isinstance(inner, dict):
            return inner, ""
        return None, (
            f"box '{key}': content was wrapped in the BoxState shape "
            f"({{\"content\": ..., \"status\": ...}}) around a "
            f"{type(inner).__name__}, not the box's own schema"
        )
    return content, ""


def normalise_boxes(update: Any) -> str:
    """Unwrap what can be unwrapped; report the first thing that cannot.

    Mutates the update in place. An empty string means every box is readable by
    the completeness rules.
    """
    for key, content in list(update.boxes.items()):
        fixed, problem = unwrap_box_content(key, content)
        if problem:
            return problem
        update.boxes[key] = fixed
    return ""


def strip_fences(text: str) -> str:
    """Remove a ```json fence if the model wrapped its JSON in one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


def parse_update(raw: str) -> tuple[ScribeUpdate | None, str]:
    """Parse, then check every box is a shape completeness can READ.

    Never silently accepts a shape the rules cannot evaluate: a box stored
    in the wrong shape can never satisfy its rule, so the interview could
    not complete and nothing would say why (T-012).
    """
    try:
        update = ScribeUpdate.model_validate(json.loads(strip_fences(raw)))
    except Exception as exc:
        return None, f"reply was not valid JSON for the update shape ({exc})"
    problem = normalise_boxes(update)
    return (None, problem) if problem else (update, "")

def parse_as(raw: str, model: Any) -> Any:
    try:
        return model.model_validate(json.loads(strip_fences(raw)))
    except Exception:
        return None
