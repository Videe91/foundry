"""Locus-policy live-validation preregistration: seal ``manifest.json`` and
``expectations.json`` (spec §16; plan T8; controller clarification 5).

    uv run python scripts/prepare_locus_validation.py \\
        [--out docs/superpowers/experiments/2026-09-15-locus-validation-v1]

What it does, in this order, and nothing else -- every git operation before any write:

1.  ``git status --porcelain`` must be empty (clean worktree);
2.  ``git rev-parse HEAD`` is the ``harness_code_sha`` -- the clean HEAD BEFORE any
    preregistration file exists (the seal commit that adds the two files is its child);
3.  ``git merge-base --is-ancestor <BASELINE_SHA> HEAD`` must hold;
4.  ``git merge-base --is-ancestor <DESIGN_BASE_SHA> HEAD`` must hold;
5.  ``git merge-base --is-ancestor <PREDECESSOR_ADJUDICATION_SHA> HEAD`` must hold;
6.  the working-tree bytes of the approved spec must equal ``git show HEAD:<SPEC_PATH>``;
    their SHA256 is sealed as ``spec_sha256``;
7.  for every directory in ``HISTORICAL_ARTIFACT_DIRS``, ``git rev-parse
    <DESIGN_BASE_SHA>:<dir>`` is the tree sha recorded in the manifest and ``git
    rev-parse HEAD:<dir>`` must equal it -- the value is read at the frozen design base,
    never taken from HEAD;
8.  neither ``manifest.json`` nor ``expectations.json`` may exist under ``--out``;
9.  ``build_manifest`` computes the rest from frozen constants; exactly the two files are
    written and their canonical hashes are printed.

Git runs through an injectable command runner (``GitCommandRunnerLike``; the default is
``subprocess`` in ``cwd``) so a test can prove, by refusing any other argv, that the
script uses only the operations above.

Law of this script: it constructs no reasoner, reads no API key, opens no network
connection, runs only the read-only git commands above, commits nothing, and originates
no scientific value -- every sealed field is a frozen literal, a ``corpus`` /
``protocol`` / ``expectations`` / ``leakage`` constant, or a fact of the repository at
HEAD or at the frozen design base. Refusals print ``REFUSED: ...`` and exit 2 with
nothing written; success exits 0.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Protocol

from foundry.experiments.locus_validation.artifacts import (
    SPEC_PATH,
    build_manifest,
    write_preregistration,
)
from foundry.experiments.locus_validation.protocol import (
    BASELINE_SHA,
    DESIGN_BASE_SHA,
    EXPERIMENT_ARTIFACT_DIR,
    HISTORICAL_ARTIFACT_DIRS,
    PREDECESSOR_ADJUDICATION_SHA,
    PREREGISTRATION_FILE_NAMES,
)

__all__ = [
    "DEFAULT_OUT",
    "EXIT_OK",
    "EXIT_REFUSED",
    "GitCommandRunner",
    "GitCommandRunnerLike",
    "build_parser",
    "main",
]

DEFAULT_OUT: Final = EXPERIMENT_ARTIFACT_DIR.rstrip("/")
EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")


class _Refused(Exception):
    """A preregistration refusal; the message is printed and the exit code is 2."""


class GitCommandRunnerLike(Protocol):
    """One read-only git invocation: ``argv`` after ``git`` -> (exit, stdout, stderr)."""

    def run(self, argv: tuple[str, ...]) -> tuple[int, bytes, bytes]: ...


class GitCommandRunner:
    """``GitCommandRunnerLike`` over ``subprocess`` in ``cwd``. Never used by tests."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def run(self, argv: tuple[str, ...]) -> tuple[int, bytes, bytes]:
        completed = subprocess.run(  # noqa: S603 - fixed read-only argv, no shell
            ["git", "-C", str(self._cwd), *argv], capture_output=True, check=False
        )
        return completed.returncode, completed.stdout, completed.stderr


def _git_text(git: GitCommandRunnerLike, *argv: str) -> str:
    code, stdout, stderr = git.run(argv)
    if code != 0:
        raise _Refused(
            f"git {' '.join(argv)} failed ({code}): {stderr.decode('utf-8', 'replace').strip()}"
        )
    return stdout.decode("utf-8")


def _require_ancestor(git: GitCommandRunnerLike, *, label: str, sha: str, head: str) -> None:
    code, _stdout, _stderr = git.run(("merge-base", "--is-ancestor", sha, "HEAD"))
    if code != 0:
        raise _Refused(f"HEAD {head} does not descend from {label} {sha}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seal the locus-validation preregistration files (no calls)."
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="experiment directory receiving manifest.json and expectations.json",
    )
    return parser


def _prepare(out_arg: str, *, cwd: Path, git: GitCommandRunnerLike) -> dict[str, str]:
    dirty = _git_text(git, "status", "--porcelain")
    if dirty.strip():
        raise _Refused(f"worktree is dirty; commit or remove first:\n{dirty.strip()}")
    head = _git_text(git, "rev-parse", "HEAD").strip()
    if not _SHA_RE.match(head):
        raise _Refused(f"git rev-parse HEAD returned {head!r}, not a 40-hex commit sha")
    _require_ancestor(git, label="baseline", sha=BASELINE_SHA, head=head)
    _require_ancestor(git, label="design base", sha=DESIGN_BASE_SHA, head=head)
    _require_ancestor(
        git, label="predecessor adjudication", sha=PREDECESSOR_ADJUDICATION_SHA, head=head
    )

    spec_path = cwd / SPEC_PATH
    if not spec_path.is_file():
        raise _Refused(f"approved spec missing from the working tree: {SPEC_PATH}")
    working_tree_bytes = spec_path.read_bytes()
    code, committed, _stderr = git.run(("show", f"HEAD:{SPEC_PATH}"))
    if code != 0:
        raise _Refused(f"approved spec is not committed at HEAD: {SPEC_PATH}")
    if committed != working_tree_bytes:
        raise _Refused(f"working-tree spec bytes differ from HEAD:{SPEC_PATH}; refusing to seal")

    base = DESIGN_BASE_SHA
    historical_tree_hashes: dict[str, str] = {}
    for directory in HISTORICAL_ARTIFACT_DIRS:
        at_base = _git_text(git, "rev-parse", f"{base}:{directory}").strip()
        at_head = _git_text(git, "rev-parse", f"HEAD:{directory}").strip()
        if at_head != at_base:
            raise _Refused(
                f"historical artifact directory {directory} tree at HEAD {at_head} != tree at "
                f"design base {base} {at_base}; frozen evidence changed -- refusing to seal"
            )
        historical_tree_hashes[directory] = at_base

    out = Path(out_arg)
    if not out.is_absolute():
        out = cwd / out
    existing = [name for name in PREREGISTRATION_FILE_NAMES if (out / name).exists()]
    if existing:
        raise _Refused(f"preregistration file(s) already exist under {out}: {existing}")

    manifest = build_manifest(
        harness_code_sha=head,
        spec_sha256=hashlib.sha256(working_tree_bytes).hexdigest(),
        historical_tree_hashes=historical_tree_hashes,
    )
    return write_preregistration(out, manifest)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    git: GitCommandRunnerLike | None = None,
) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = (cwd if cwd is not None else Path.cwd()).resolve()
    runner: GitCommandRunnerLike = git if git is not None else GitCommandRunner(root)
    try:
        hashes = _prepare(args.out, cwd=root, git=runner)
    except _Refused as refusal:
        print(f"REFUSED: {refusal}")
        return EXIT_REFUSED
    for name in PREREGISTRATION_FILE_NAMES:
        print(f"{name} {hashes[name]}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
