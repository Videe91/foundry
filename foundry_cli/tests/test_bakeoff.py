"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: test the bake-off — three candidates, blind labels, transcripts landing
in the project's evidence ledger, and nothing of the real interview touched.

The blindness is the protocol, not a nicety: knowing which model is speaking is
exactly what would corrupt a judgement about how each makes a human respond.

Version: 0.1.0
"""

from __future__ import annotations

import random
from pathlib import Path

from conftest import SLUG, FakeRoute, Printer, Reader, fake_registry, scribe_json

from foundry_cli.bakeoff import (
    DEFAULT_CANDIDATES,
    LABELS,
    candidate_registry,
    candidates_for,
    run_bakeoff,
    shuffled,
)
from intent import load_state, new_state, save_state
from intent.store import state_path

SEEDED = random.Random(7)


def _replies(count: int = 60) -> list[str]:
    """Alternating scribe/interviewer replies, enough for any candidate run."""
    out: list[str] = []
    for index in range(count):
        out.append(scribe_json())
        out.append(f"question {index}")
    return out


def _answers(count: int = 40) -> list[str]:
    return ["the idea"] + [f"answer {i}" for i in range(count)]


# --- candidate selection ----------------------------------------------------


def test_the_documented_trio_is_the_default(tmp_path: Path) -> None:
    assert candidates_for(None) == DEFAULT_CANDIDATES
    assert candidates_for(tmp_path / "nothing.toml") == DEFAULT_CANDIDATES


def test_a_bakeoff_table_in_the_registry_overrides_the_default(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry.toml"
    registry.write_text(
        '[bakeoff]\ninterviewer_candidates = ["a/one", "b/two"]\n', encoding="utf-8"
    )
    assert candidates_for(registry) == ("a/one", "b/two")


def test_a_malformed_registry_falls_back_rather_than_exploding(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry.toml"
    registry.write_text("this is not = = toml", encoding="utf-8")
    assert candidates_for(registry) == DEFAULT_CANDIDATES


def test_the_shuffle_reorders_without_losing_anyone() -> None:
    order = shuffled(DEFAULT_CANDIDATES, random.Random(1))
    assert sorted(order) == sorted(DEFAULT_CANDIDATES)


def test_the_shuffle_is_not_a_no_op() -> None:
    """Discriminating: a shuffle that always returned input order would leave
    the labels perfectly informative and the read no longer blind."""
    orders = {tuple(shuffled(DEFAULT_CANDIDATES, random.Random(s)))
              for s in range(25)}
    assert len(orders) > 1


# --- the registry is informed, never edited --------------------------------


def test_a_candidate_registry_is_a_copy_not_an_edit() -> None:
    """R-012: the bake-off produces evidence; the human makes the change."""
    registry = fake_registry()
    original = registry.roles["interviewer"].model
    clone = candidate_registry(registry, "openai/gpt-5.6-luna")

    assert clone.roles["interviewer"].model == "openai/gpt-5.6-luna"
    assert registry.roles["interviewer"].model == original, "the real registry moved"
    assert clone.roles["scribe"].model == registry.roles["scribe"].model


def test_the_scribe_is_held_fixed_across_candidates(tmp_path: Path) -> None:
    """Only the interviewer varies, or the trial measures two things at once."""
    route = FakeRoute(replies=_replies())
    run_bakeoff(SLUG, root=tmp_path, turns=2, route=route, printer=Printer(),
                reader=Reader(_answers()), rng=SEEDED, stamp="2026-08-19")
    scribe_models = {
        c["registry"].roles["scribe"].model for c in route.calls if c["role"] == "scribe"
    }
    assert len(scribe_models) == 1


def test_the_shipped_registry_file_is_never_written(tmp_path: Path) -> None:
    registry_file = tmp_path / SLUG / "registry.toml"
    run_bakeoff(SLUG, root=tmp_path, turns=1, route=FakeRoute(replies=_replies()),
                printer=Printer(), reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19")
    assert not registry_file.exists(), "the bake-off wrote a project registry"


# --- the run ----------------------------------------------------------------


def test_all_three_candidates_run_and_are_labelled_a_b_c(tmp_path: Path) -> None:
    printer = Printer()
    run_bakeoff(SLUG, root=tmp_path, turns=2, route=FakeRoute(replies=_replies()),
                printer=printer, reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19")
    for label in LABELS:
        assert f"=== CANDIDATE {label} ===" in printer.text


def test_the_same_opening_goes_to_every_candidate(tmp_path: Path) -> None:
    route = FakeRoute(replies=_replies())
    reader = Reader(_answers())
    run_bakeoff(SLUG, root=tmp_path, turns=2, route=route, printer=Printer(),
                reader=reader, rng=SEEDED, stamp="2026-08-19")
    # Every call carries the whole transcript, so the opening is message[0]
    # throughout. What matters is that there is exactly ONE opening across all
    # three candidates — the trial is only fair if they answer the same brief.
    openings = {c["messages"][0] for c in route.calls}
    assert openings == {"the idea"}
    first_turns = [c for c in route.calls if len(c["messages"]) == 2]
    assert len(first_turns) == len(LABELS), "each candidate got one opening turn"


def test_the_mapping_is_revealed_only_at_the_end(tmp_path: Path) -> None:
    """The whole point: labels stay uninformative until the reading is done."""
    printer = Printer()
    run_bakeoff(SLUG, root=tmp_path, turns=2, route=FakeRoute(replies=_replies()),
                printer=printer, reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19")
    text = printer.text
    reveal = text.index("=== THE REVEAL ===")
    for model in DEFAULT_CANDIDATES:
        assert model in text[reveal:], f"{model} missing from the reveal"
        assert model not in text[:reveal], f"{model} leaked before the reveal"


def test_the_registry_edit_is_named_as_the_humans(tmp_path: Path) -> None:
    printer = Printer()
    run_bakeoff(SLUG, root=tmp_path, turns=1, route=FakeRoute(replies=_replies()),
                printer=printer, reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19")
    assert "R-012" in printer.text
    assert "evidence, not a decision" in printer.text


# --- evidence ---------------------------------------------------------------


def test_all_three_transcripts_land_in_evidence_under_a_dated_heading(
    tmp_path: Path,
) -> None:
    run_bakeoff(SLUG, root=tmp_path, turns=2, route=FakeRoute(replies=_replies()),
                printer=Printer(), reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19 12:00:00Z")
    evidence = (tmp_path / SLUG / "ledger" / "evidence.md").read_text(encoding="utf-8")

    assert "## Interviewer bake-off — 2026-08-19 12:00:00Z" in evidence
    for label in LABELS:
        assert f"### Candidate {label}" in evidence
    for model in DEFAULT_CANDIDATES:
        assert model in evidence, "the mapping must survive in the record"


def test_evidence_is_appended_not_replaced(tmp_path: Path) -> None:
    for stamp in ("2026-08-19 10:00:00Z", "2026-08-19 11:00:00Z"):
        run_bakeoff(SLUG, root=tmp_path, turns=1,
                    route=FakeRoute(replies=_replies()), printer=Printer(),
                    reader=Reader(_answers()), rng=SEEDED, stamp=stamp)
    evidence = (tmp_path / SLUG / "ledger" / "evidence.md").read_text(encoding="utf-8")
    assert evidence.count("## Interviewer bake-off") == 2


# --- the bake-off pollutes nothing -----------------------------------------


def test_the_real_interview_state_is_never_written(tmp_path: Path) -> None:
    from workspace import open_project

    run_bakeoff(SLUG, root=tmp_path, turns=2, route=FakeRoute(replies=_replies()),
                printer=Printer(), reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19")
    project = open_project(SLUG, root=tmp_path)
    assert load_state(project) is None
    assert not state_path(project).exists()


def test_an_existing_interview_survives_a_bakeoff_untouched(
    tmp_path: Path,
) -> None:
    """Discriminating: absence proves little if there was never anything there."""
    from workspace import create_project

    project = create_project(SLUG, "Demo", root=tmp_path)
    state = new_state(SLUG)
    state.turn_count = 11
    save_state(project, state)
    before = state_path(project).read_text(encoding="utf-8")

    run_bakeoff(SLUG, root=tmp_path, turns=2, route=FakeRoute(replies=_replies()),
                printer=Printer(), reader=Reader(_answers()), rng=SEEDED,
                stamp="2026-08-19")

    assert state_path(project).read_text(encoding="utf-8") == before
    assert load_state(project).turn_count == 11
