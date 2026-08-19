# Packet P-014 — Intent, Part Two: The Live Interview

**Department:** Coding Floor
**Wave:** 13 (builds on P-013; Switchboard 350 + Workspace 92 + Intent 53, all stamped)
**Language:** Python 3.12

**Architecture context:** P-013's engine is brainless by design — it receives `interviewer_fn` and `scribe_fn` as callables by shape. This packet builds the COMPOSITION EDGE: a CLI that wires those shapes to real models through the Switchboard, streams the Interviewer's voice to the terminal, accepts attachments mid-conversation, routes receipts into the project's own ledger, resumes crashed interviews, and runs the bake-off that decides the Interviewer's brain on evidence. The engine, the Workspace, and the Switchboard remain untouched — this packet is wiring, not organs. The seam law inverts here deliberately: the CLI is ABOVE all three packages and may import all three; it is the first module allowed to, because composition is its entire job.

**The endgame (Fire Exits, play-back, double-write, signature) is P-015.** This packet's interview loops until the engine reports complete, then prints the box summary and says the signature ceremony arrives in the next packet. Honest scaffolding, clearly labeled.

## One job

`python -m foundry intent <slug>` runs a real interview: create-or-resume the project, loop (user types → Scribe extracts via a real cheap model → engine checks → Interviewer's next question streams to the terminal), attachments via an in-conversation command, every call metered into the project's ledger, state saved every turn. Plus `--bake-off` for the three-way Interviewer trial.

## Dictionary

| Concept | Name |
|---|---|
| The package | `foundry_cli` (new top-level: `foundry_cli/src/foundry_cli/`, own pyproject, same pins + NO new deps — argparse and stdlib only) |
| Entry point | `python -m foundry_cli intent <slug>` (module main; a console-script named `foundry` is registered in its pyproject so `foundry intent <slug>` works after `pip install -e .`) |
| The composer | `brains.py` — builds `interviewer_fn` and `scribe_fn` from the Switchboard (`route_call`, registry, adapters) for a given project |
| Interviewer wiring | streaming route_call on role `interviewer`, deltas printed as they arrive (flush), full reply returned to the engine |
| Scribe wiring | blocking route_call on role `scribe`; the reply is parsed into ScribeUpdate (contract 3) |
| The interview loop | `session.py` — create/resume, prompt loop, engine calls, save handled by engine, exit handling |
| In-conversation commands | `/attach <path>` (adds an attachment to the next turn), `/status` (prints box completion table), `/quit` (saves and exits — resume later) |
| The bake-off | `bakeoff.py` — `python -m foundry_cli bakeoff <slug> --turns N` (default 6) |
| Bake-off transcript record | appended to `<project>/ledger/evidence.md` under a dated heading per candidate |
| Meter wiring | P-012's `MeterRouter`/`Project.meter()` — every call tagged `project_id=<slug>`, `department="intent"`, `role=interviewer|scribe` |

## Files to create (each under 300 lines)

```
foundry_cli/
├── pyproject.toml
├── src/foundry_cli/
│   ├── __init__.py
│   ├── __main__.py        — argparse dispatch: intent, bakeoff
│   ├── brains.py          — the composition edge (Switchboard → engine shapes)
│   ├── session.py         — the interview loop + commands
│   └── bakeoff.py         — the three-way trial
└── tests/                 — offline, fakes at the route_call seam
```

Registry, engine, workspace, switchboard: source untouched. (Registry model choices remain the human's; the bake-off exists to inform exactly that edit.)

## Behaviour contract

1. **Session start:** `intent <slug>` → open_project or create_project (reusing P-012's create-if-absent pattern); load_state → resume with a printed one-line recap ("resuming at turn N, 3 of 8 boxes confirmed") or start fresh with the Interviewer's opening question (the engine's first turn runs with an empty user message? NO — the CLI sends a synthetic first user turn containing the user's initial idea: the session PROMPTS "Describe your idea:" before the loop begins on a fresh interview; on resume it goes straight to the prompt loop).
2. **The Scribe's JSON discipline:** the scribe role's system prompt (built in brains.py, cached — it is the stable block) instructs strict JSON matching ScribeUpdate's schema, no prose. Parsing: strip code fences if present, parse, validate via the pydantic model. A malformed reply gets ONE silent retry with a corrective instruction appended; a second failure raises a clear error naming the role and preserving the raw reply in the project's build log — never a silent empty update (a lost extraction is a lost user answer).
3. **Streaming truthfully:** the Interviewer streams via on_chunk printing deltas; the COMPLETE reply the engine stores must be the assembled response content from route_call's return — never a locally re-joined delta buffer (single source of truth; the R-018 lesson).
4. **Attachments:** `/attach <path>` validates the file exists and the extension maps to a known kind (image/pdf/text per the Switchboard's rules), queues it for the NEXT user turn, and reminds the user which families accept what only if the send later fails (don't front-load provider trivia). The attachment rides the route_call to BOTH interviewer and scribe turns for that message (the Scribe needs the document to extract from it).
5. **Receipts:** every call carries tags (project_id=slug, department="intent", role, attempt via the engine's turn_count) and meters into the project's ledger through the P-012 machinery. After `/quit` or completion, print the session's receipt line: N calls, total tokens, total cost (cost may be None-partial — render honestly per the matrix rule: "≥ $X.XX plus unpriced calls" when any receipt lacks cost).
6. **Completion:** when the engine reports complete, print the eight boxes as a plain-words table (key, one-line content summary, confirmed-by) and the line: "Interview complete. The signature ceremony (Fire Exits check, play-back, and signing) arrives in P-015 — this interview is saved and will be picked up there." No advance(), no signature — honest scaffolding.
7. **The bake-off protocol:** `bakeoff <slug> --turns N` runs the SAME interview opening (the user types the idea once; the tool replays it) against each of three candidate models for the interviewer role — read from a `[bakeoff]` table in the project's registry.toml if present, else the documented default trio (anthropic/claude-sonnet-5, openai/gpt-5.6-terra, openai/gpt-5.6-luna) — for N turns each, with the HUMAN typing the answers live for each candidate (three short real conversations, not simulations — the judgment is about how each makes the human respond). Candidate order is SHUFFLED and transcripts are labeled A/B/C with the model mapping revealed only at the end (the blind read, built in). All three transcripts append to evidence.md; the scribe role stays fixed throughout so only the interviewer varies. Each candidate's session is throwaway state (never touches interview-state.json) — bake-off pollutes nothing.
8. **Interrupts:** Ctrl-C mid-stream cancels the current turn cleanly (state is whatever the last completed turn saved) and prints the resume hint. Never a stack trace at the user.

## Tests that must pass (ALL offline — fakes injected at the route_call boundary; no keys, no network)

- brains: interviewer_fn streams (fake deltas reach a capture callback) and returns route_call's assembled content, not a rejoined buffer (discriminating: fake returns content that differs from the deltas' join by one marker character — the engine must store route_call's version)
- scribe: valid JSON parses to ScribeUpdate; fenced JSON parses; malformed → one retry with corrective instruction (assert the second call's messages contain it) → second failure raises naming the role, raw reply logged
- session: fresh start prompts for the idea; resume prints the recap and skips the idea prompt (fake state file); /status renders the table; /quit saves and exits zero
- attachments: /attach with a bad path or unknown extension is rejected at the command with a message; a queued attachment appears on the next turn's calls to BOTH brains (assert on fake route_call kwargs)
- receipts: every fake call carries the full tag set; the session summary counts N calls and renders the honest-partial cost line when one receipt has cost=None
- bakeoff: three candidates run with shuffled A/B/C labels (seeded shuffle in tests), mapping revealed only in the final print, all three transcripts landed in evidence.md under dated headings, interview-state.json untouched (assert absent/unchanged)
- guards: foundry_cli MAY import all three packages (no leaf guard here — composition is the job); the three existing package guards stay green

Full suite green — all four packages.

## Forbidden

- No engine/workspace/switchboard source changes; no registry model edits (the bake-off informs the human's R-012 edit, never makes it).
- No signature, no advance(), no Fire Exits — P-015.
- No new dependencies (argparse + stdlib + the three packages).
- No simulated bake-off answers — the human talks to all three candidates or the evidence is fiction.
- No network in tests; only the human runs live interviews.
