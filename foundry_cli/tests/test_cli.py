"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: test the command line surface, and record the seam inversion — this
package MAY import all three others, and the three keep their own guards.

Version: 0.1.0
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from foundry_cli.__main__ import build_parser, main

SRC = Path(__file__).resolve().parents[1] / "src"
REPO = Path(__file__).resolve().parents[2]
PATHS = [SRC, REPO / "intent" / "src", REPO / "workspace" / "src",
         REPO / "switchboard" / "src", REPO / "switchboard"]


def test_intent_takes_a_slug() -> None:
    args = build_parser().parse_args(["intent", "demo-app"])
    assert (args.command, args.slug) == ("intent", "demo-app")


def test_bakeoff_defaults_to_six_turns() -> None:
    assert build_parser().parse_args(["bakeoff", "demo-app"]).turns == 6


def test_bakeoff_turns_is_settable() -> None:
    assert build_parser().parse_args(["bakeoff", "d", "--turns", "3"]).turns == 3


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_an_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["deploy", "demo"])


def test_intent_requires_a_slug_rather_than_guessing() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["intent"])


def test_main_dispatches_to_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_start(slug: str, root=None) -> int:
        seen["slug"] = slug
        return 0

    import foundry_cli.session as session

    monkeypatch.setattr(session, "start", fake_start)
    assert main(["intent", "demo-app"]) == 0
    assert seen["slug"] == "demo-app"


def test_main_dispatches_to_the_bakeoff(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(slug: str, root=None, turns: int = 6) -> int:
        seen.update(slug=slug, turns=turns)
        return 0

    import foundry_cli.bakeoff as bakeoff

    monkeypatch.setattr(bakeoff, "run_bakeoff", fake_run)
    assert main(["bakeoff", "demo-app", "--turns", "2"]) == 0
    assert seen == {"slug": "demo-app", "turns": 2}


# --- the seam inversion -----------------------------------------------------


def test_the_cli_may_import_all_three_packages() -> None:
    """Composition is this package's entire job, so it is exempt BY DESIGN.

    Recorded as a test rather than a comment: the exemption is deliberate, and
    a reader who finds imports here should meet the reason immediately, not
    conclude the seam law was forgotten.
    """
    # `workspace` is imported lazily inside start(), so the check is that all
    # three COEXIST when the CLI actually composes them — not that all three
    # load at import time, which would be a claim about eagerness, not seams.
    probe = (
        "import sys\n"
        "import foundry_cli\n"
        "from foundry_cli.session import start, open_or_create\n"
        "from foundry_cli.bakeoff import run_bakeoff\n"
        "import workspace\n"
        "need = {'intent', 'workspace', 'switchboard'}\n"
        "have = {m.split('.')[0] for m in sys.modules}\n"
        "sys.exit(0 if need <= have else 1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in PATHS)},
        check=False,
    )
    assert result.returncode == 0, (
        f"the CLI should import all three packages.\n{result.stderr}"
    )


def test_the_cli_still_imports_no_litellm_at_module_level() -> None:
    """The exemption covers Foundry packages, not the provider stack: importing
    the CLI must not pay litellm's load time before a call is made (R-008)."""
    probe = (
        "import sys\n"
        "import foundry_cli\n"
        "from foundry_cli.session import start\n"
        "sys.exit(1 if 'litellm' in sys.modules else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in PATHS)},
        check=False,
    )
    assert result.returncode == 0, f"litellm was imported eagerly.\n{result.stderr}"
