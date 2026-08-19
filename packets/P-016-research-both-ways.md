# Packet P-016 — Research Both Ways: The Searching Interviewer + The Sweep

**Department:** Coding Floor
**Wave:** 15 (builds on P-015; all four packages stamped, search live-proven)
**Language:** Python 3.12
**Authority:** design doc §15.1 (research rulebook: gather → attach sources → synthesize → CHALLENGE THE INTENT, findings dated and expiring), §4 box 6. Founder ruling this session, record as **R-036**: mid-interview search INFORMS QUESTIONS, NEVER FILLS BOXES — only the user and the sweep write the constitution; and the sweep runs before signature, its challenges acknowledged at the P-017 play-back.

**Architecture context:** two consumers of one capability. (1) The interviewer's brain gains the search tool at the composition edge — when the user says "like TrustedForm," the next question is informed by a lookup, not a guess. The ENGINE does not change: search happens inside the model's turn, invisible to run_turn. (2) The sweep is a distinct stage with a distinct role: on a completed interview, it finds the real market, fills box 6 with dated findings, and produces CHALLENGES — the things the market says that the intent doesn't. Challenges are recorded here; P-017 makes the user acknowledge them before signing.

## One job

Registry roles can be configured to search; the interviewer uses it mid-conversation without the engine knowing; `foundry research <slug>` runs the sweep on a completed interview, writing `intent/research.md` + structured findings, filling box 6, and recording challenges for the signature ceremony.

## Dictionary

| Concept | Name |
|---|---|
| Role search config | `RoleRoute.web_search: bool = False` and `RoleRoute.web_search_max_uses: int = 3` (registry fields — R-014: structure validated, values are the human's) |
| Auto-attach | route_call: when the resolved role has `web_search=True` AND the request carries no explicit spec AND the family supports search → attach `WebSearchSpec(max_uses=<role's>)`; an explicit request spec always wins; a role with web_search=True on a non-searching family FAILS AT LOAD (R-035's gate, extended: capability checked where it is knowable) |
| The researcher | registry role `researcher` (stub added, human-authorized: suggest anthropic/claude-sonnet-5, web_search=true, web_search_max_uses=8, effort high — comment: the sweep's brain, human's to change) |
| Sweep entry | `run_research(project, researcher_fn) -> ResearchFindings` (file `intent/src/intent/research.py` — engine-side, brains injected by shape, imports neither switchboard nor litellm; guards extend) |
| Findings model | `ResearchFindings` (file `research.py`; fields: `players: list[Player]` (name, url, what_they_do, relevance), `table_stakes: list[str]`, `edge: list[str]`, `challenges: list[Challenge]`, `sources: list[str]`, `generated_at: datetime UTC`, `expires_at: datetime UTC = generated_at + 30 days`) |
| A challenge | `Challenge` (fields: `claim: str` — what the market/facts say; `against: str` — which part of the intent it presses on; `sources: list[str]`; `acknowledged: bool = False` — P-017 flips it) |
| Researcher output contract | strict JSON matching ResearchFindings' buildable fields (the P-014 scribe discipline: one corrective retry, then loud failure preserving the raw reply) |
| Persistence | findings JSON at `<project>/intent/research.json` (atomic); human-readable `<project>/intent/research.md` rendered from it (players table, stakes vs edge, challenges, sources, dates) |
| Box 6 fill | the research box content becomes `{"status": "completed", "generated_at": ..., "expires_at": ..., "challenges_open": N}` — still internal, never conversational |
| CLI | `python -m foundry_cli research <slug>` (and `foundry research <slug>`) |
| Expiry law | P-017 must refuse to sign on findings past `expires_at` (recorded here as the contract P-017 inherits; not built here) |

## Files to create or modify (each under 300 lines)

```
switchboard/
├── src/switchboard/registry.py — MODIFY (R-016 flag): the two role fields + load-time capability check
├── src/switchboard/router.py   — MODIFY (R-016 flag): auto-attach
└── tests/ (topic-correct homes)

intent/
├── src/intent/research.py      — NEW: models + run_research + renderers
└── tests/test_research.py      — NEW

foundry_cli/
├── src/foundry_cli/brains.py   — MODIFY: researcher_fn (search-enabled role call, JSON discipline); interviewer needs NO wiring change (auto-attach does it when the human flips the registry)
├── src/foundry_cli/research_cmd.py — NEW: the command
├── src/foundry_cli/__main__.py — MODIFY: dispatch
└── tests/

registry.toml — human-authorized config edit: researcher stub; interviewer gains web_search=true, web_search_max_uses=2 (the founder's standing intent from this session)
```

## Behaviour contract

1. **Auto-attach precedence, tested discriminatingly:** explicit request spec > role config > nothing. A role with web_search=False and a request with no spec → no tools kwarg at all (byte-identical law, assert absence).
2. **Load-time capability check (R-035 extended):** `web_search=true` on a role whose primary model's family lacks `search_tool` → load error naming role, family, and the missing capability. Fallback families that cannot search: the P-015 runtime gate already refuses per-attempt — registry comments carry the human warning (the max_tokens-ceiling precedent).
3. **The engine stays deaf to search (R-036):** no engine change; a test asserts the interviewer's searched-or-not is invisible to run_turn (fake interviewer_fn output identical either way → identical state). The Scribe role must NOT search: scribe web_search stays false; a test in the CLI asserts the scribe call carries no tools even when the interviewer's does.
4. **run_research sequence:** load_state → completeness must be TRUE (a sweep on an unfinished interview is refused, naming what is incomplete) → build the research brief from CONVERSATIONAL boxes only (goal, users, workflows, data, boundaries, non_negotiables, website — internal boxes excluded by the T-009 rule) → researcher_fn → validate/retry per the scribe discipline → persist JSON + render md → update box 6 content via the store (state saved atomically) → return findings.
5. **The challenge discipline (the rulebook's step 4):** the researcher prompt REQUIRES at least one challenge or an explicit `"challenges": []` with a stated reason string in a `no_challenges_because` field — silence is not allowed; "the market agrees with everything" must be said out loud to be doubted. Challenges reference which intent element they press on (`against`), so P-017 can show them next to what the user is signing.
6. **Expiry:** `expires_at = generated_at + 30 days` (the rulebook's dated-findings law; the value is a named constant with the rationale, not magic). research.md prints both dates prominently.
7. **Re-running research:** allowed; overwrites findings (append the old research.md to `intent/research-archive.md` first — findings are replaced, never silently lost) and resets box 6 counts.
8. **CLI output:** streams nothing (the researcher may take a while — print a working line), then prints: players found, N challenges (each on one line: claim → against), the file paths, the receipt line (tokens, searches, cost — the P-015 receipt shape), and "Challenges are acknowledged at signing (P-017)."
9. **Receipts:** researcher calls tagged project_id=slug, department="intent", role="researcher"; metered into the project ledger.

## Tests that must pass (ALL offline — fakes at the boundaries)

switchboard (topic-correct homes):
- auto-attach precedence trio (explicit wins; role config attaches with the role's max_uses; false+none → no tools kwarg)
- load: web_search=true on an openrouter-primary role → error naming role/family/capability; on anthropic → loads; structure-only (R-014) — no value assertions on the shipped file beyond validity

intent/test_research.py:
- refuses an incomplete interview naming the incomplete boxes
- brief built from conversational boxes only (internal excluded — assert "research" absent from the brief)
- happy path: fake researcher returns valid findings → JSON + md written atomically, box 6 updated (status completed, challenges_open=N), state saved
- challenge discipline: findings with empty challenges AND no reason → validation error; with reason → accepted
- expiry: expires_at = generated_at + 30d; md contains both dates
- re-run archives the previous md before overwrite
- malformed researcher JSON → one corrective retry → loud failure preserving raw reply
- guards: intent still imports neither switchboard nor litellm

foundry_cli:
- research command: completed fake project → prints challenges, paths, receipt; incomplete → the refusal, exit non-zero
- scribe never searches even when interviewer does (assert on fake route_call kwargs per role)
- receipt line carries searches per P-015's shape

Full suite green — all four packages.

## Forbidden

- No engine changes (R-036: search is invisible to run_turn). No signature, no acknowledgment flow, no advance() — P-017.
- No search for the scribe. No box-filling from mid-interview search — only run_research writes box 6.
- No web_fetch, no citation rendering beyond source URLs in findings.
- No new dependencies, no keys, no network in tests; only the human runs the sweep.
