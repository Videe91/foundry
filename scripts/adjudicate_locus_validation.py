"""Locus-policy live-validation offline adjudication entry point (spec §11, §14; plan
T8; controller clarification 6).

    uv run python scripts/adjudicate_locus_validation.py \\
        --raw-run-sha <40 hex> \\
        --out docs/superpowers/experiments/2026-09-15-locus-validation-v1 \\
        --answers <json file> --notes "<architect notes>"

``--answers`` is a JSON object ``{"alpha": {"A-S01": true, ...}, "beta": {...}}``: the
architect's binary answers to the spec §7.2 semantic assertions, per ledger, exactly
the ids ``expectations.SEMANTIC_ASSERTION_IDS`` (typed and validated by
``artifacts.Adjudication``; a missing ledger, an unknown id or a non-boolean answer is
a refusal).

Order, and nothing else: parse arguments; refuse -- before anything else -- when
``XAI_API_KEY`` is PRESENT in the injected environment (its value is never read: a
presence-only check, so no provider key can be near an adjudication); read and
validate the answers file into an ``Adjudication``; ``write_adjudication`` over the
committed raw tree (it refuses unless HEAD is the raw-run commit, the worktree is
clean, every one of the 21 raw files equals the committed bytes and the tree is not
yet adjudicated; it rewrites exactly ``verdicts.json`` and ``report.md`` and proves the
other nineteen unchanged); print ``experiment_outcome = <value>`` from the rewritten
``verdicts.json``. Refusals print ``REFUSED: ...`` and exit 2 with nothing written;
success exits 0.

Law of this script: it constructs no reasoner or provider client, makes no network
call, reads no key value, runs only the read-only git commands ``write_adjudication``
asks for, and originates no scientific value -- the outcome is computed by the frozen
``expectations`` rule inside ``write_adjudication`` from the committed structural facts
and the architect's answers; this script only carries the answers in and the recorded
outcome out. Every console line is redacted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from foundry.experiments.locus_validation.artifacts import (
    Adjudication,
    AdjudicationRefused,
    write_adjudication,
)
from foundry.experiments.locus_validation.integrity import GitCliLike
from foundry.experiments.locus_validation.protocol import EXPERIMENT_ARTIFACT_DIR
from foundry.experiments.longitudinal.artifacts import redact_secrets

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_OUT",
    "EXIT_OK",
    "EXIT_REFUSED",
    "GitCli",
    "build_parser",
    "main",
]

API_KEY_ENV: Final = "XAI_API_KEY"
DEFAULT_OUT: Final = EXPERIMENT_ARTIFACT_DIR.rstrip("/")
EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_VERDICTS_NAME: Final = "verdicts.json"
_OUTCOME_KEY: Final = "experiment_outcome"


class _Refused(Exception):
    """A refusal; printed and mapped to ``EXIT_REFUSED``. Nothing has been written."""


# --------------------------------------------------------------------------- subprocess adapter


class GitCli:
    """``GitCliLike`` over read-only git subcommands in ``cwd`` (plain argv, no shell).
    The adjudication writer uses ``head``, ``dirty`` and ``show_bytes``; the rest
    complete the protocol. Never used by tests."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - fixed read-only argv, no shell
            ["git", "-C", str(self._cwd), *args], capture_output=True, check=False
        )

    def _text(self, *args: str) -> str:
        completed = self._run(*args)
        if completed.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed ({completed.returncode}): "
                f"{completed.stderr.decode('utf-8', 'replace').strip()}"
            )
        return completed.stdout.decode("utf-8")

    def head(self) -> str:
        return self._text("rev-parse", "HEAD").strip()

    def dirty(self) -> str:
        return self._text("status", "--porcelain")

    def parents(self, sha: str) -> tuple[str, ...]:
        line = self._text("rev-list", "--parents", "-n", "1", sha).strip()
        return tuple(line.split()[1:])

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self._run("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        output = self._text("diff", "--name-only", f"{base}..{head}")
        return tuple(line for line in output.splitlines() if line)

    def show_bytes(self, sha: str, path: str) -> bytes:
        completed = self._run("show", f"{sha}:{path}")
        if completed.returncode != 0:
            raise RuntimeError(f"git show {sha}:{path} failed ({completed.returncode})")
        return completed.stdout

    def tree_sha(self, sha: str, path: str) -> str:
        return self._text("rev-parse", f"{sha}:{path}").strip()


# --------------------------------------------------------------------------- answers


def _read_answers(path: Path) -> dict[str, Any]:
    """The answers file as a JSON object; anything else is a refusal."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _Refused(f"answers file {path} cannot be read: {type(exc).__name__}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Refused(f"answers file {path} is unparsable: {type(exc).__name__}") from exc
    if not isinstance(parsed, dict):
        raise _Refused(f"answers file {path} is not a JSON object")
    return parsed


def _adjudication(answers: Mapping[str, Any], notes: str) -> Adjudication:
    """External data validated by the model itself: ledgers, ids and strict booleans."""
    try:
        return Adjudication.model_validate({"semantic_answers": dict(answers), "notes": notes})
    except ValidationError as exc:
        raise _Refused(f"answers are not a valid adjudication: {exc}") from exc


def _recorded_outcome(out_dir: Path) -> str:
    """The outcome as ``write_adjudication`` recorded it; read back, never computed."""
    document = json.loads((out_dir / _VERDICTS_NAME).read_text(encoding="utf-8"))
    return str(document.get(_OUTCOME_KEY))


# --------------------------------------------------------------------------- CLI


def _say(line: str) -> None:
    print(redact_secrets(line))


def _commit_sha(value: str) -> str:
    if not _SHA_RE.match(value):
        raise argparse.ArgumentTypeError("--raw-run-sha must be exactly 40 lowercase hex digits")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Locus-policy live-validation: record the architect's offline adjudication over "
            "the committed raw run (no provider, no key)."
        )
    )
    parser.add_argument(
        "--raw-run-sha", required=True, type=_commit_sha, help="the raw-run commit SHA"
    )
    parser.add_argument("--out", default=DEFAULT_OUT, type=Path, help="experiment directory")
    parser.add_argument(
        "--answers",
        required=True,
        type=Path,
        help='JSON file {"alpha": {"A-S01": true, ...}, "beta": {...}}',
    )
    parser.add_argument("--notes", required=True, help="the architect's adjudication notes")
    return parser


def _adjudicate(
    *,
    out_dir: Path,
    raw_run_sha: str,
    answers_path: Path,
    notes: str,
    cwd: Path,
    env: Mapping[str, str],
    git: GitCliLike,
) -> str:
    # Presence-only, before anything else: the value is never read.
    if API_KEY_ENV in env:
        raise _Refused(
            f"{API_KEY_ENV} is present in the environment (presence-only check; its value was "
            "never read); adjudication runs with no provider key"
        )
    adjudication = _adjudication(_read_answers(answers_path), notes)
    try:
        write_adjudication(
            out_dir,
            raw_run_commit_sha=raw_run_sha,
            git=git,
            adjudication=adjudication,
            repo_root=cwd,
            env=env,
        )
    except (AdjudicationRefused, ValueError) as exc:
        raise _Refused(f"{type(exc).__name__}: {exc}") from exc
    return _recorded_outcome(out_dir)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    git: GitCliLike | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exit_:
        code = exit_.code
        return code if isinstance(code, int) else EXIT_REFUSED
    root = (cwd if cwd is not None else Path.cwd()).resolve()
    out_dir: Path = args.out if args.out.is_absolute() else root / args.out
    answers_path: Path = args.answers if args.answers.is_absolute() else root / args.answers
    git_cli: GitCliLike = git if git is not None else GitCli(root)
    environment: Mapping[str, str] = env if env is not None else os.environ
    try:
        outcome = _adjudicate(
            out_dir=out_dir,
            raw_run_sha=args.raw_run_sha,
            answers_path=answers_path,
            notes=args.notes,
            cwd=root,
            env=environment,
            git=git_cli,
        )
    except _Refused as refusal:
        _say(f"REFUSED: {refusal}")
        return EXIT_REFUSED
    _say(f"{_OUTCOME_KEY} = {outcome}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
