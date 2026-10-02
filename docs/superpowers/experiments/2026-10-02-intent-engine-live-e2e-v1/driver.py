"""The driver that ran intent-engine-live-e2e-v1, committed as evidence.

It is ``foundry.experiments.intent_engine_live_v1.live.main`` step for step -- every preflight
gate, the founder's binding, ``live_ports``, one ``run_live``, ``write_raw`` -- plus transparent
recording only: a progress line per model call, the writer's own receipts and parsed payloads,
the IE3 recording provider's records, and the adjudicator's executed identity, usage and raw
structured answer (``call_metadata.json``). Nothing here changes a request, an answer, a budget
or a decision; nothing is retried.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

from foundry.experiments.intent_engine_live_v1 import protocol
from foundry.experiments.intent_engine_live_v1.live import KEY_NAMES, live_ports
from foundry.experiments.intent_engine_live_v1.roles import RoleBinding
from foundry.experiments.intent_engine_live_v1.runner import run_live
from foundry.experiments.intent_engine_live_v1.seal import (
    load_oracle,
    preflight_gates,
    sealed_json,
    write_raw,
)

OUT = Path(protocol.EXPERIMENT_ARTIFACT_DIR)
STARTED = time.perf_counter()


def log(message: str) -> None:
    print(f"[{time.perf_counter() - STARTED:8.1f}s] {message}", flush=True)


class Progress:
    """Transparent: forwards every attribute; logs each call's start, end and duration."""

    def __init__(self, inner: Any, role: str, methods: tuple[str, ...]) -> None:
        self._inner = inner
        self._role = role
        self._methods = methods
        self._n = 0

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name not in self._methods:
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            self._n += 1
            n = self._n
            t = time.perf_counter()
            log(f"{self._role} call {n}: start")
            try:
                answer = target(*args, **kwargs)
            except BaseException as error:
                log(
                    f"{self._role} call {n}: {type(error).__name__} after "
                    f"{time.perf_counter() - t:.1f}s"
                )
                raise
            log(f"{self._role} call {n}: done in {time.perf_counter() - t:.1f}s")
            return answer

        return call


class RecordingProvider:
    """Transparent provider wrapper: records the executed identity, usage and output."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.records: list[dict[str, Any]] = []

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    def execute(self, *, model: Any, request: Any, output_type: Any) -> Any:
        t = time.perf_counter()
        try:
            result = self._inner.execute(model=model, request=request, output_type=output_type)
        except BaseException as error:
            self.records.append(
                {
                    "error": f"{type(error).__name__}: {error}",
                    "wall_clock_s": time.perf_counter() - t,
                }
            )
            raise
        usage = result.usage
        self.records.append(
            {
                "provider": result.identity.provider,
                "model": result.identity.model,
                "task": request.task.value,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": usage.cost_usd,
                "wall_clock_ms": usage.wall_clock_ms,
                "finish_reason": result.finish_reason,
                "output": result.output.model_dump(mode="json"),
            }
        )
        return result


def main() -> int:
    gates = preflight_gates()
    for name, (ok, why) in gates.items():
        log(f"gate {name}: {'PASS' if ok else 'REFUSED'} ({why})")
    if not all(ok for ok, _ in gates.values()):
        log("STOP: a preflight gate refused; no live call made")
        return 2
    binding = RoleBinding.model_validate_json((OUT / protocol.ROLE_BINDING_FILE).read_text())
    keys = {name: os.environ[name] for name in KEY_NAMES}
    writer, verifier, synthesizer, adjudicator = live_ports(binding, keys)
    adjudicator_provider = RecordingProvider(adjudicator._runtime._providers["anthropic"])
    adjudicator._runtime._providers["anthropic"] = adjudicator_provider
    ids = count(1)
    log("live run: start")
    record = run_live(
        writer=Progress(writer, "WRITER", ("propose", "propose_accounted")),
        verifier=Progress(verifier, "VERIFIER", ("verify",)),
        ie3_synthesizer=Progress(synthesizer, "IE3", ("synthesize",)),
        adjudicator=Progress(adjudicator, "ADJUDICATOR", ("adjudicate",)),
        oracle=load_oracle,
        clock=lambda: datetime.now(UTC),
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )
    write_raw(record)
    ie3_provider = synthesizer._runtime._providers["openai"]
    metadata = {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "total_wall_clock_s": time.perf_counter() - STARTED,
        "grpc_dns_resolver": os.environ.get("GRPC_DNS_RESOLVER"),
        "writer_receipts": [r.model_dump(mode="json") for r in writer.receipts],
        "writer_parsed_payloads": [d.model_dump(mode="json") for d in writer._drafts],
        "ie3_provider_records": [r.model_dump(mode="json") for r in ie3_provider.records],
        "adjudicator_provider_records": adjudicator_provider.records,
    }
    (OUT / "call_metadata.json").write_text(sealed_json(metadata))
    log(f"VERDICT {record.report.verdict}")
    log(json.dumps(record.report.counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
