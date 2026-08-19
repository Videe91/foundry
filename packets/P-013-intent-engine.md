# Packet P-013 — Intent, Part One: The Engine (Offline)

**Department:** Coding Floor
**Wave:** 12 (first department packet; Switchboard 350 + Workspace 92, both stamped)
**Language:** Python 3.12
**Authority:** design doc v2.2 Section 4 (Intent), Section 16 (Workspace). Founder rulings this session, record as **R-033**: (a) contradictions are SURFACED — latest statement wins, but the user is told and confirms; (b) impatient users get PROPOSED DEFAULTS requiring explicit confirmation — Foundry never self-signs a constitution; (c) role names `interviewer` and `scribe`.

**Architecture context:** Intent is a conversation loop that fills eight boxes, refuses to pretend they are full when they are not, and ends (in P-015) with a signature. This packet builds the ENGINE, fully offline: the skeleton as data, the Scribe extraction contract, code-owned completeness, the turn loop with injected fake models, and crash-safe persistence into the project's `intent/` directory. Live models are P-014; the endgame (Fire Exits, play-back, signature) is P-015.

**Seam law (the P-012 discipline extended):** the `intent` package MAY import `workspace` (it works on projects — one direction, downward). It must NEVER import `switchboard` or `litellm` — the engine receives its two brains as injected callables by shape. Composition with real models happens at the edge in P-014. Subprocess guards enforce both, same pattern as P-011's.

## One job

`run_turn(state, user_message, interviewer_fn, scribe_fn) -> (state, reply_or_done)`: one interview turn — Scribe updates boxes from the transcript, code checks the skeleton, either the Interviewer's next question comes back or the state says complete. State persists to disk after every turn; a crashed interview resumes exactly where it stopped.

## Dictionary

| Concept | Name |
|---|---|
| The package | `intent` (new top-level: `intent/src/intent/`, own pyproject, same pins: pydantic==2.11.7, pytest==8.4.1, hatchling==1.32.0) |
| The skeleton | `SKELETON` (file `skeleton.py`) — the eight boxes AS DATA: key, title, layman prompt-hint, completeness rule id |
| Box keys | `goal`, `users`, `workflows`, `data`, `boundaries`, `research`, `non_negotiables`, `website` |
| One box's state | `BoxState` (fields: `key`, `content: dict`, `status: str` — one of `empty`, `proposed`, `confirmed`; `proposed_by: str \| None` — `"user"` or `"interviewer"`) |
| Whole interview | `InterviewState` (fields: `slug`, `boxes: dict[str, BoxState]`, `transcript: list[Turn]`, `contradictions: list[Contradiction]`, `turn_count: int`) |
| One turn | `Turn` (fields: `role: str` — `user`/`interviewer`; `content: str`; `at: datetime UTC`) |
| A contradiction | `Contradiction` (fields: `box_key`, `earlier: str`, `later: str`, `surfaced: bool`, `resolved: bool`) |
| Scribe output contract | `ScribeUpdate` (fields: `boxes: dict[str, dict]` — proposed content per box it can now fill/update; `contradictions: list[Contradiction]` — newly detected) |
| Completeness check | `completeness(state) -> dict[str, bool]` (file `rules.py`) — pure code, one rule function per box |
| The turn engine | `run_turn(...)` (file `engine.py`) |
| Turn result | `TurnResult` (fields: `reply: str \| None`, `complete: bool`, `pending_confirmations: list[str]` — box keys awaiting explicit yes) |
| Persistence | `save_state(project, state)` / `load_state(project) -> InterviewState \| None` (file `store.py`) — JSON into `<project>/intent/interview-state.json`, atomic write (temp + rename, the P-011 pattern) |
| Injected brains | `interviewer_fn(transcript, box_status, directives) -> str` and `scribe_fn(transcript, current_boxes) -> ScribeUpdate` — callables by SHAPE, never imports |

## Completeness rules (`rules.py` — code, not model opinion)

- `goal`: content has a non-empty `summary` AND `victory_conditions` list with ≥ 2 entries, each a non-empty string.
- `users`: ≥ 1 user type, each with non-empty `name` and `needs`.
- `workflows`: ≥ 1 workflow, each with non-empty `story` and `mode` in {`automate`, `human_in_loop`}.
- `data`: non-empty `entities` list; `sensitive` present (may be an empty list, but the KEY must exist — "we asked" differs from "nothing sensitive").
- `boundaries`: ≥ 1 non-empty exclusion string.
- `research`: ALWAYS complete — the reserved slot (design doc box 6); its content is `{"status": "reserved"}`.
- `non_negotiables`: keys `security_level`, `scale`, `budget` present with non-empty values.
- `website`: `needed: bool` present; if true, `kind` non-empty.
- **A box counts toward completeness ONLY when `status == "confirmed"`** — proposed content, however good, is not consent (R-033b).

## Behaviour contract

1. **The turn sequence, exactly:** append user Turn → `scribe_fn(transcript, current_boxes)` → merge ScribeUpdate (contract 2) → `completeness()` → if all eight confirmed-complete: `TurnResult(reply=None, complete=True)` → else build directives (contract 4) → `interviewer_fn(...)` → append interviewer Turn → save_state → `TurnResult(reply=..., complete=False, pending_confirmations=...)`.
2. **Merge rules:** Scribe content lands as `proposed` unless it is restating already-`confirmed` content unchanged. A box moves `proposed → confirmed` ONLY via explicit user confirmation, detected by the Scribe reporting the box in a `confirmed_by_user` list on ScribeUpdate (add that field) when the user's message explicitly affirms it. Latest-wins on content conflicts, but a detected conflict with anything previously `confirmed` MUST also emit a Contradiction (R-033a) and demote the box to `proposed` until re-confirmed.
3. **Contradiction lifecycle (R-033a):** new contradictions arrive `surfaced=False`. The directives (contract 4) instruct the Interviewer to surface the oldest unsurfaced one in its next reply ("earlier you said X, now Y — going with Y, correct?"); once passed to the interviewer_fn it is marked `surfaced=True`; the Scribe marks it `resolved=True` when a later user message settles it. Completeness is BLOCKED while any contradiction has `resolved=False` — a signed constitution may not contain a known unresolved conflict.
4. **Directives to the Interviewer** (a small structured dict, the engine's only steering): `incomplete_boxes` (ordered by SKELETON order), `pending_confirmations`, `unsurfaced_contradiction` (at most one), `ask_one_question: True`. The engine NEVER generates question text — charm is the model's job, truth is the code's (the Mediocre-Model Test pointed at ourselves).
5. **Proposed defaults (R-033b):** when the Scribe reports the user deflected ("you decide"), it may fill the box with `proposed_by="interviewer"` content — and that box lands in `pending_confirmations` until the user explicitly affirms. No path exists from `proposed` to `confirmed` without a user turn doing it.
6. **Persistence:** save after EVERY completed turn, atomic. `load_state` on an existing file resumes with full transcript, boxes, and contradictions intact; on absence returns None (fresh interview). Corrupt file → a clear error naming the path, never silent re-init (a broken interview is a finding, P-011 open_project philosophy).
7. **Attachments in the transcript:** a Turn may carry `attachments: list[str]` (paths) — the engine stores them faithfully for P-014 to feed to real models; the fakes ignore them. No attachment processing in this packet.
8. **New registry roles:** add `interviewer` and `scribe` role STUBS to the shipped registry.toml as a HUMAN-authorized config edit (R-012 — the human confirms models; suggest sonnet-5 and haiku respectively as placeholders with a comment that P-014's bake-off decides). Load validation must pass.

## Tests that must pass (ALL offline, fake brains, tmp projects via create_project)

test_rules.py: every completeness rule — the discriminating pair per box (a minimal passing content and the nearest failing mutation: 1 victory condition fails where 2 pass; `sensitive` key absent fails where empty-list passes; `proposed` status fails where `confirmed` passes; etc.). Research is always complete.

test_engine.py:
- scripted three-turn happy path: fakes fill and confirm boxes; completeness flips only when the last box is CONFIRMED, not merely proposed
- deflection: scribe proposes a default → box in pending_confirmations → user affirms next turn → confirmed
- contradiction: user contradicts a confirmed box → Contradiction emitted, box demoted, completeness blocked → directives carry it exactly once (surfaced flips) → user resolves → completeness unblocked
- the engine never fabricates question text (assert reply == the fake interviewer's returned string, verbatim)
- ask-one-question directive always present; unsurfaced_contradiction carries at most one

test_store.py:
- save → load round-trips the full state (boxes, transcript order, contradictions, turn_count)
- atomicity: the file is never half-written (write interrupted via the temp-path assertion pattern from P-011)
- corrupt JSON → error naming the path; absent → None
- state lands under the project's intent_dir (path from the Workspace handle, never computed)

Guards (subprocess, the P-011 pattern): importing `intent` pulls in neither `switchboard` nor `litellm`; `workspace` still imports neither `intent` nor `switchboard` (leaf stays leaf).

Full suite green — Switchboard 350 + Workspace 92 + intent's new.

## Forbidden

- No switchboard/litellm imports in `intent` (guards enforce); no real model calls anywhere.
- No question text generated by the engine; no completeness opinions from models — code owns truth.
- No auto-confirmation path; no silent contradiction resolution; no silent state re-init.
- No Fire Exits, no play-back, no signature, no `advance()` — P-015's job. No CLI — P-014's job.
- No new dependencies. Workspace and Switchboard src untouched except the registry config edit noted in contract 8.
