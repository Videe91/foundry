"""9P2 unseen-lifecycle preregistration: seal ``manifest.json`` and ``expectations.json``
(spec §17.1; plan T6/T8; v2 revision).

    uv run python scripts/prepare_contrastive_unseen_lifecycle.py \\
        [--out docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2]

The v2 default directory is a fresh experiment identity; the v1 directory
(``2026-09-12-contrastive-unseen-lifecycle-v1``) records the v1 provider abort and is
never written to again.

What it does, in order, and nothing else:

1. ``git status --porcelain`` must be empty (clean worktree);
2. ``git rev-parse HEAD`` is the ``harness_code_sha`` -- the clean HEAD BEFORE any
   preregistration file exists (the seal commit that adds the two files is its child);
3. ``git merge-base --is-ancestor <FROZEN_CORE_SHA> HEAD`` must hold;
4. neither ``manifest.json`` nor ``expectations.json`` may exist under ``--out``;
5. the working-tree bytes of the approved spec must equal ``git show HEAD:<spec path>``;
   their SHA256 is sealed as ``spec_sha256``;
6. ``build_manifest`` computes the rest from frozen constants; exactly the two files are
   written and their canonical hashes are printed.

Law of this script: it constructs no reasoner, reads no API key, opens no network
connection, runs only the four read-only git commands above, commits nothing, and
originates no scientific value -- every sealed field is a frozen literal, a timeline
or expectations constant, or a fact of the repository at HEAD. Refusals exit 2 with the
reason on stdout; success exits 0.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from foundry.experiments.contrastive_unseen.artifacts import (
    PREREGISTRATION_FILE_NAMES,
    SPEC_PATH,
    build_manifest,
    write_preregistration,
)
from foundry.experiments.contrastive_unseen.timeline import FROZEN_CORE_SHA

DEFAULT_OUT = "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2"


class _Refused(Exception):
    """A preregistration refusal; the message is printed and the exit code is 2."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed read-only argv, no shell
        ["git", "-C", str(cwd), *args], capture_output=True, check=False
    )


def _git_text(cwd: Path, *args: str) -> str:
    completed = _git(cwd, *args)
    if completed.returncode != 0:
        raise _Refused(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    return completed.stdout.decode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seal the 9P2 unseen-lifecycle preregistration files (no model call)."
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="experiment directory receiving manifest.json and expectations.json",
    )
    return parser


def _prepare(out_arg: str, *, cwd: Path, frozen_core_sha: str) -> dict[str, str]:
    dirty = _git_text(cwd, "status", "--porcelain")
    if dirty.strip():
        raise _Refused(f"worktree is dirty; commit or remove first:\n{dirty.strip()}")
    head = _git_text(cwd, "rev-parse", "HEAD").strip()
    if _git(cwd, "merge-base", "--is-ancestor", frozen_core_sha, "HEAD").returncode != 0:
        raise _Refused(f"HEAD {head} does not descend from frozen core {frozen_core_sha}")

    out = Path(out_arg)
    if not out.is_absolute():
        out = cwd / out
    existing = [name for name in PREREGISTRATION_FILE_NAMES if (out / name).exists()]
    if existing:
        raise _Refused(f"preregistration file(s) already exist under {out}: {existing}")

    spec_path = cwd / SPEC_PATH
    if not spec_path.is_file():
        raise _Refused(f"approved spec missing from the working tree: {SPEC_PATH}")
    working_tree_bytes = spec_path.read_bytes()
    committed = _git(cwd, "show", f"HEAD:{SPEC_PATH}")
    if committed.returncode != 0:
        raise _Refused(f"approved spec is not committed at HEAD: {SPEC_PATH}")
    if committed.stdout != working_tree_bytes:
        raise _Refused(f"working-tree spec bytes differ from HEAD:{SPEC_PATH}; refusing to seal")

    manifest = build_manifest(
        harness_code_sha=head,
        spec_sha256=hashlib.sha256(working_tree_bytes).hexdigest(),
    )
    return write_preregistration(out, manifest)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    frozen_core_sha: str = FROZEN_CORE_SHA,
) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = (cwd if cwd is not None else Path.cwd()).resolve()
    try:
        hashes = _prepare(args.out, cwd=root, frozen_core_sha=frozen_core_sha)
    except _Refused as refusal:
        print(f"REFUSED: {refusal}")
        return 2
    for name in PREREGISTRATION_FILE_NAMES:
        print(f"{name} {hashes[name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
