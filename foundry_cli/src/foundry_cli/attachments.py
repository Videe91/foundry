"""Packet: T-013 — attachable files.

One job: turn a path the founder typed into an Attachment, or say why it cannot
be one.

Split from brains.py under the R-017 precedent. Per R-026 the split inherits its
parent's map entries.

Version: 0.1.0
"""

from __future__ import annotations

from pathlib import Path

from switchboard.request import Attachment


# Extension -> attachment kind, mirroring what the Switchboard's adapters accept.
KINDS: dict[str, str] = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".pdf": "pdf", ".md": "text", ".txt": "text",
}


def attachment_for(path: str | Path) -> Attachment:
    """Build an Attachment, or say why the file cannot be one."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ValueError(f"no such file: {resolved}")
    kind = KINDS.get(resolved.suffix.lower())
    if kind is None:
        raise ValueError(
            f"{resolved.name}: '{resolved.suffix}' is not an attachable kind "
            f"(known: {', '.join(sorted(set(KINDS)))})"
        )
    return Attachment(kind=kind, path=str(resolved))
