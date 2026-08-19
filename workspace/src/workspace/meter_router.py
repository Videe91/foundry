"""Packet: P-012 — The meter learns addresses: receipts land in project ledgers.

One job: route a meter record to the ledger of the project its tags name, and
append it there.

**The seam is the point.** The Switchboard never learns what a project is — it
keeps writing wherever its meter's `path` points. The Workspace owns the concept
of a project, so it supplies the address. The two packages meet through a path
and a two-member shape (`.path`, `.record`), never through an import: this
module imports nothing from switchboard, and the subprocess guards enforce that.

Version: 0.1.0
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

LEDGER_RELATIVE = Path("ledger") / "meter.jsonl"


def _member(obj: Any, name: str) -> Any:
    """Read `name` off an attribute-object or a mapping. Both are real.

    A caller holding a pydantic MeterRecord has attributes; a caller holding a
    decoded JSON line has a dict. Accepting only one would make the router work
    on live records and silently fail on replayed ones.
    """
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def project_id_of(record: Any) -> str | None:
    """The project_id a record is tagged with, or None if it carries none."""
    tags = _member(record, "tags")
    if tags is None:
        return None
    value = _member(tags, "project_id")
    return None if value is None else str(value)


class JsonlMeter:
    """Append-only JSONL writer with the same two members the Switchboard's
    MeterLedger exposes: `.path` and `.record(record)`.

    Deliberately not an import of MeterLedger. Fifteen lines here keep the
    Workspace dependency-free and keep the seam honest; the format itself is
    pinned on both sides — by P-003's tests there, and by the round-trip test
    here against a captured real receipt (R-019).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, record: Any) -> None:
        """Append exactly one JSON line for this record."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(self._encode(record) + "\n")

    @staticmethod
    def _encode(record: Any) -> str:
        """Serialise by shape, preferring the record's own encoder.

        A pydantic record encodes itself exactly as MeterLedger would — the
        same `model_dump_json()` call — so a routed line is byte-identical to
        an unrouted one rather than merely equivalent.
        """
        dump_json = getattr(record, "model_dump_json", None)
        if callable(dump_json):
            return str(dump_json())
        dump = getattr(record, "model_dump", None)
        payload = dump() if callable(dump) else record
        return json.dumps(payload, separators=(",", ":"), default=str)


class MeterRouter:
    """Sends each record to the meter of the project its tags name.

    Duck-typed into the Switchboard's meter slot: it exposes `.record(record)`,
    which is the whole of what `route_call` asks of a meter. That is why this
    packet changes no Switchboard source at all.
    """

    def __init__(
        self,
        resolve: Callable[[str], Path],
        default_path: str | Path | None = None,
    ) -> None:
        self.resolve = resolve
        self.default_path = None if default_path is None else Path(default_path)
        self._meters: dict[Path, JsonlMeter] = {}

    def record(self, record: Any) -> None:
        """Resolve, then append. Never raises — the meter must not kill a call.

        P-003's law: a receipt that cannot be filed is a warning, never an
        exception. A resolver that throws is a resolution failure like any
        other, contained here rather than propagated into the caller's call.
        """
        project_id = project_id_of(record)
        path: Path | None = None
        if project_id is not None:
            try:
                resolved = self.resolve(project_id)
            except Exception:  # any resolver failure is a routing failure
                resolved = None
            if resolved is not None:
                path = Path(resolved)

        if path is None:
            if self.default_path is None:
                warnings.warn(
                    f"meter record dropped: no ledger for project_id "
                    f"{project_id!r}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                return
            path = self.default_path

        self._meter_for(path).record(record)

    def _meter_for(self, path: Path) -> JsonlMeter:
        if path not in self._meters:
            self._meters[path] = JsonlMeter(path)
        return self._meters[path]


def workspace_resolver(root: str | Path) -> Callable[[str], Path]:
    """Resolve a slug to `<root>/<slug>/ledger/meter.jsonl`.

    Deliberately a cheap existence check rather than a full `open_project`:
    this runs once per metered call, and validating a whole skeleton on the hot
    path would make honest bookkeeping expensive enough to want to skip.
    An unknown slug raises KeyError, which MeterRouter treats as any other
    resolution failure.
    """
    base = Path(root)

    def resolve(project_id: str) -> Path:
        ledger = base / project_id / "ledger"
        if not ledger.is_dir():
            raise KeyError(f"no project ledger for {project_id!r} under {base}")
        return base / project_id / LEDGER_RELATIVE

    return resolve
