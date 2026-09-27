"""Identity of a structured-output schema, independent of any provider.

A certification binds the answer contract a model was constrained by, not only the prompt it
read. Two schemas are the same contract exactly when their canonical JSON is byte-identical:
``json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``, UTF-8, the
form Foundry already uses for its output-schema digests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

__all__ = ["schema_sha256"]


def schema_sha256(schema: Mapping[str, Any]) -> str:
    """SHA-256 of the schema's canonical JSON. Key order never changes the digest."""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
