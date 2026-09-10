from __future__ import annotations

import json

from foundry.intelligence.input import IntelligenceInput, IntelligenceSource


def render_source_records(request: IntelligenceInput) -> str:
    payload = {"sources": [_source_record(source) for source in request.inputs]}
    return json.dumps(payload, separators=(",", ":"))


def _source_record(source: IntelligenceSource) -> dict[str, str]:
    return {
        "event_id": source.event_id,
        "event_type": str(source.event_type),
        "content": source.content,
        "source_kind": str(source.source_kind),
        "source_ref": source.source_ref,
    }
