"""IE2 mutation controls: prove each Intent Graph law is asserted by at least one test.

    uv run python scripts/run_ie2_mutations.py                 # every slice
    uv run python scripts/run_ie2_mutations.py --slice ie22c   # one slice
    uv run python scripts/run_ie2_mutations.py --slice ie24 --only kind-removed
    uv run python scripts/run_ie2_mutations.py --list
    uv run python scripts/run_ie2_mutations.py --check-anchors   # fast, runs no tests

Each mutant (``scripts/ie2_mutants.py``) is one deliberate violation of a law: a small textual
edit to production code. The runner applies it, runs the slice's tests with ``-x``, and
restores the file. A mutant is **killed** when the tests fail (a timeout also counts: a
removed visited-set loops forever), and **survives** when they stay green -- a survivor is a
law no test asserts. An **anchor** failure means the text to mutate no longer occurs exactly
once; the code moved and the mutant must be re-anchored, never skipped.

Exit status is 0 only when every selected mutant is killed.

Safety, because this edits ``src/`` in place:

* originals are held in memory **and** journalled under ``.git/ie2-mutation-journal/`` before
  any edit; a run interrupted mid-mutant is restored from that journal on the next start;
* every restore is verified byte-for-byte against the original, and the journal is cleared
  only once everything is verified;
* ``__pycache__`` under ``src/`` is cleared around every mutant so no stale bytecode survives.

No model, network or provider is involved; this runs the ordinary offline test suite.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ie2_mutants import MUTANTS, SLICE_TESTS, Mutant

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / ".git" / "ie2-mutation-journal"


def _journal_dir() -> Path:
    git = ROOT / ".git"
    if git.is_file():  # a worktree: .git is a pointer file to the real git dir
        pointer = git.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip()
        return (ROOT / pointer).resolve() / "ie2-mutation-journal"
    return JOURNAL


def _clear_bytecode() -> None:
    for cache in (ROOT / "src").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _recover(journal: Path) -> None:
    """Restore any file an interrupted run left mutated, then clear the journal."""
    if not journal.exists():
        return
    restored = 0
    for saved in sorted(journal.rglob("*")):
        if saved.is_file():
            target = ROOT / saved.relative_to(journal)
            target.write_bytes(saved.read_bytes())
            restored += 1
    shutil.rmtree(journal)
    _clear_bytecode()
    print(f"recovered {restored} file(s) from an interrupted run", flush=True)


def _run_tests(tests: tuple[str, ...], timeout: int) -> tuple[bool, str]:
    """(killed, summary) for one test run."""
    command = [sys.executable, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
    try:
        result = subprocess.run(
            [*command, *tests], cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return True, f"timeout after {timeout}s"
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return result.returncode != 0, lines[-1] if lines else f"exit {result.returncode}"


def _apply(mutant: Mutant, originals: dict[Path, bytes]) -> str | None:
    """Write the mutated files. Returns an anchor problem instead of writing, if any."""
    texts = {path: originals[path].decode("utf-8") for path in originals}
    for edit in mutant.edits:
        path = ROOT / edit.path
        count = texts[path].count(edit.old)
        if count != 1:
            return f"anchor occurs {count}x in {edit.path}: {edit.old[:60]!r}"
        texts[path] = texts[path].replace(edit.old, edit.new, 1)
    for path, text in texts.items():
        path.write_text(text, encoding="utf-8")
    return None


def _restore(originals: dict[Path, bytes]) -> None:
    for path, data in originals.items():
        path.write_bytes(data)
    for path, data in originals.items():
        if path.read_bytes() != data:
            raise RuntimeError(f"restore of {path} did not verify; see the journal")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--slice", choices=sorted(SLICE_TESTS), action="append")
    parser.add_argument("--only", nargs="+", default=[], help="mutant names within the slice")
    parser.add_argument("--timeout", type=int, default=300, help="seconds per mutant")
    parser.add_argument("--list", action="store_true", help="list mutants and exit")
    parser.add_argument(
        "--check-anchors", action="store_true", help="verify every anchor; run no tests"
    )
    args = parser.parse_args()

    selected = [
        m
        for m in MUTANTS
        if (not args.slice or m.slice in args.slice) and (not args.only or m.name in args.only)
    ]
    unknown = set(args.only) - {m.name for m in selected}
    if unknown:
        parser.error(f"unknown mutant(s) for the selected slice(s): {sorted(unknown)}")
    if args.list:
        for m in selected:
            print(f"{m.slice:6} {m.name}")
        return 0
    if args.check_anchors:
        stale = [
            f"{m.slice}/{m.name}: {e.path}: {e.old[:60]!r} occurs {n}x"
            for m in selected
            for e in m.edits
            if (n := (ROOT / e.path).read_text(encoding="utf-8").count(e.old)) != 1
        ]
        for line in stale:
            print(f"  stale anchor: {line}")
        print(f"{len(selected) - len({s.split(':')[0] for s in stale})}/{len(selected)} anchored")
        return 1 if stale else 0

    journal = _journal_dir()
    _recover(journal)

    paths = sorted({ROOT / edit.path for m in selected for edit in m.edits})
    originals = {path: path.read_bytes() for path in paths}
    for path, data in originals.items():
        saved = journal / path.relative_to(ROOT)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(data)

    killed: list[str] = []
    survived: list[str] = []
    anchors: list[str] = []
    started = time.monotonic()
    try:
        for m in selected:
            label = f"{m.slice}/{m.name}"
            mutated = {ROOT / e.path: originals[ROOT / e.path] for e in m.edits}
            problem = _apply(m, mutated)
            if problem is not None:
                anchors.append(f"{label}: {problem}")
                print(f"  ANCHOR   {label}: {problem}", flush=True)
                continue
            _clear_bytecode()
            try:
                was_killed, summary = _run_tests(SLICE_TESTS[m.slice], args.timeout)
            finally:
                _restore(mutated)
                _clear_bytecode()
            if was_killed:
                killed.append(label)
                print(f"  killed   {label}  ({summary})", flush=True)
            else:
                survived.append(label)
                print(f"  SURVIVED {label}  <-- law not asserted ({summary})", flush=True)
    finally:
        _restore(originals)
        _clear_bytecode()
        shutil.rmtree(journal, ignore_errors=True)

    minutes = (time.monotonic() - started) / 60
    print(f"\nkilled {len(killed)}/{len(selected)} in {minutes:.1f} min")
    for label in survived:
        print(f"  survivor: {label}")
    for problem in anchors:
        print(f"  stale anchor: {problem}")
    return 0 if not survived and not anchors else 1


if __name__ == "__main__":
    sys.exit(main())
