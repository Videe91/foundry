# Foundry Rulings Ledger

Cortex rulings on floor-flagged issues. A ruling recorded here is settled law:
the floor must not re-flag it, and future packets inherit it. Format: packet
the flag came from, the issue, the ruling, and where it takes effect.

## R-001 — Empty-string defaults in CallTags (from P-001, note 1)

**Ruling: RATIFIED.** The gate must be the single voice of rejection, so core
tags default to `""` and the gate treats empty-or-whitespace as missing;
`department` is a validated `str`, not an Enum. Settled pattern for all future
gate-style validation: our error type speaks, never a construction-time error.

## R-002 — Payload placeholder `prompt` (from P-001, note 2)

**Ruling: ACCEPTED for P-001, SUPERSEDED by P-002.** Payload is
`messages: list[Message]`, min length 1. `prompt` is retired. Closed.

## R-003 — Missing [build-system] (from P-001, note 3)

**Ruling: ACCEPTED — packet defect, fixed in P-002.** `hatchling==1.32.0`
pinned as the build backend. Standing rule for packet authors: a build backend
is a dependency and must be pinned like one.

## R-004 — Header + "create exactly this" (from P-002, note 1)

**Ruling: RATIFIED as precedent.** When a packet says "create exactly this"
and Law rule 7 requires a header: header above, packet block verbatim beneath.
Both laws satisfied, neither altered. Applies to all future literal-content
files.

## R-005 — ModelRegistry.resolve (from P-002, note 2)

**Ruling: RATIFIED, Dictionary amended.** Role resolution lives on the
registry as `ModelRegistry.resolve(role)`. Official Dictionary name as of
P-003.

## R-006 — ProviderCallError location (from P-002, note 3)

**Ruling: RATIFIED. SETTLED — do not re-flag.** `ProviderCallError` lives in
`router.py`: it is a routing failure, not a registry failure. Standing rule
for packet authors: every Dictionary name gets an explicit file assignment.

## R-007 — Wheel-packages line + version 0.2.0 (from P-002, note 4)

**Ruling: RATIFIED.** Both were mechanical consequences of stated
instructions (installability; header versions). Mechanical consequences of
explicit instructions are within floor scope.

## R-008 — Module-level litellm import (from P-002 review, floor judgment call)

**Ruling: S1, FIXED in P-003.** Lazy imports inside the None-branches;
module-level litellm import is forbidden and test-enforced. Measured effect:
suite 6.81s → 0.18s. Closed.

## R-009 — test_router.py at 294/300 lines (from P-003)

**Ruling: S1, DEFERRED with a standing authorization.** The floor's
restructure-within-scope was correct and is ratified. The next packet that
touches the Switchboard test suite is pre-authorized to create
`switchboard/tests/conftest.py` and move the shared fakes there. Until such a
packet exists, no action.

## R-010 — pyproject version drift 0.2.0 vs 0.3.0 (from P-003, note 2)

**Ruling: ACCEPTED, DEFERRED.** Scope rules outrank header consistency — the
floor's priority order was correct. The next packet listing pyproject.toml as
modifiable bumps the version to match its wave. Until then, drift is known and
tolerated.

## R-011 — Branch chain (from P-003, note 3)

**Ruling: RATIFIED.** Building P-003 on the P-002 branch was correct — main
lacked P-002, and recreating stamped files is forbidden. Merge order: P-002
PR into main first, then P-003, so each PR shows only its own wave's diff.

## R-012 — registry.toml is configuration, not law (from P-004, registry section)

**Ruling: RATIFIED as a standing rule.** `registry.toml` is **user
configuration**. The human may edit role→model assignments at any time with no
packet, no build, and no stamp — that is the file's entire purpose. Code must
never hardcode a model string; it only reads the registry. Packets after P-004
must not prescribe role→model choices; a future settings layer will manage this
file. Roles may exist in the registry before any code uses them: presence in
config is cheap, and it proves the wiring before the need arrives.

**Corollary the floor is required to flag (see T-001):** if the registry is
configuration, then no stamped test may assert on its *values*. Tests may
assert structure and behaviour only. `test_registry.py` currently violates this
and is stamped, so P-004's registry replacement could not be executed.

## R-013 — Keys exist only at the Switchboard (from P-004, amendment)

**Ruling: RATIFIED as a standing rule.** Keys exist only at the Switchboard —
no other component may ever read provider keys, load `.env`, or accept keys as
parameters; the Switchboard is the single door to all providers.

**Where it takes effect:** `.env` and `.env.example` live at the project root
and `.env` is gitignored. `load_env()` lives in `smoke.py` and is called only
from its main path. Library code under `src/` must never import dotenv or read
the environment — provider credentials reach the provider through LiteLLM's own
env lookup and through nothing Foundry writes. Verification should treat any
`src/` reference to a key name, `os.environ`, or dotenv as a violation of this
ruling regardless of whether the feature works.

## R-014 — Tests on configuration assert structure, never values (from T-001)

**Ruling: RATIFIED.** Tests on configuration files assert STRUCTURE, never
VALUES. Config belongs to the human (R-012); a test that pins config values
contradicts that ownership. `test_registry.py` unstamped for this packet only,
then re-stamped.

**Where it takes effect:** `test_registry.py` now asserts that the shipped
`registry.toml` parses, that every entry has a non-empty `model`, a list of
non-empty string `fallbacks`, and a positive integer `max_tokens`, and that a
`default` role exists. All resolution behaviour is proven against synthetic
TOML written to `tmp_path`, so the real file's values are never load-bearing.
Verified empirically: swapping `architect` to a different model, changing its
ceiling, and adding a cross-family fallback leaves the suite green.

**Standing rule for packet authors:** any future test that reads a
user-editable config file inherits this. Assert the shape; never the contents.

## R-006 corollary — Attachment and PingResult (from P-004, notes 1 and 2)

**Ruling: BOTH RATIFIED, Dictionary amended.**

`Attachment` is assigned to `request.py`. The floor's reasoning is accepted:
`SwitchboardRequest.attachments` needs the type, and placing it in
`adapters.py` would create an import cycle, since `adapters.py` imports
`Message` from `request.py`. The import-cycle constraint decides the
assignment.

`PingResult` is ratified into the Dictionary as the smoke script's per-model
reachability result (fields: `model: str`, `ok: bool`, `seconds: float`,
`error: str | None`), living in `smoke.py`. Standing reminder under R-006: a
packet that introduces a return shape must name it and assign it a file.

## R-015 — Solo flow (from P-004, flag 1)

**Ruling: RATIFIED as the new normal.** Solo flow — pushes to main are
permitted; nothing builds on top of a push until Cortex's cold verification
stamps it. The stamp is the review. Branch/PR flow returns if contributors
multiply.

**Reasoning of record:** the review that actually protects the codebase is
Cortex's cold verification from a fresh clone, which happens after any push,
branch or main, identically. PR ceremony added steps without adding protection
while no second human reviews diffs. The law updates to match reality; the gate
is verification, not branching. Revisitable as a config-of-process.
`2321f0d` is stamped.

## R-016 — Necessary stamped-file modification (from P-004, flag 2)

**Ruling: RATIFIED.** An explicit packet-author instruction that necessarily
touches stamped files is a one-amendment unstamping of exactly those files;
they re-stamp on the next cold-verified green build. `registry.py` and
`test_registry.py` re-stamped as of P-004 completion.

**Standing pattern for the floor:** execute the explicit instruction, then flag
the implicit unstamping upward. That handling is correct and is now the
expected behaviour. Parallel to R-014.

## R-017 — tests/test_effort.py (from P-004, flag 3)

**Ruling: RATIFIED on the R-009 precedent.** `tests/test_effort.py` ratified
into the file map per the R-009 precedent — topic splits beat repeated
compaction.

**Reasoning of record:** R-009's whole point was that `test_router.py` needed
structural relief, and a topic-focused test file is cleaner than a
shared-fixture squeeze.

## R-018 — File map, test_cache.py pre-authorization, include_usage (from P-005)

**Ruling: RATIFIED.** `smoke_debug.py` and `smoke_fixtures.py` ratified into the
file map (R-017 precedent).

**Pre-authorization:** the next packet touching the Switchboard test suite
creates `tests/test_cache.py` and moves cache-extraction tests there.

**Conditional pre-authorization:** if streaming reports zero tokens on a live
run, adding `stream_options` `include_usage` to the streaming path is a
one-line authorized amendment, logged, no new packet.

**Notes of record:** topic splits beat compaction — diagnostics and fixture
bytes are exactly the right things to live apart from the main script. Keeping
`dump_usage` in `smoke.py` per its Dictionary assignment was the correct
precedence read. The `test_cache.py` authorization takes the same
standing-authorization shape as R-009. If a live run reports tokens correctly,
the conditional authorization expires unused.

## R-019 — Fakes model the API, never the implementation (from P-005)

**Ruling: RATIFIED.** Fakes model the API, never the implementation. When a
live run or transformation-code inspection reveals a provider's real shape,
fakes are corrected to that observed shape in the same amendment, citing where
the shape was observed.

**Where it takes effect:** the T-002 diagnosis (LiteLLM's
`AnthropicConfig.transform_request` and a real `litellm.types.utils.Usage`) and
the R-018 amendment (terminal chunk carries usage with EMPTY choices under
`stream_options`). Both shapes are cited in the tests that use them. A fake
that encodes our assumption rather than the provider's behaviour is the defect
class that produced two green-suite-but-broken-live failures in one day.

## R-020 — Smoke wiring guard authorized (from P-005)

**Ruling: RATIFIED.** Smoke wiring guard authorized. `test_smoke.py` unstamped
for this one amendment (R-016) to add offline wiring tests verifying smoke's
prove functions pass system blocks, attachments, effort, meter, and stream
options through to `route_call` correctly; re-stamps on cold-verified green.

**Why:** unit tests of smoke's parts all passed while `smoke.py` would not
start (the `load_env` defect). The guard closes the class "the script does not
start, or a phase silently stops passing something through".

## R-018 extension — test_smoke_wiring.py pre-authorization (from the R-020 guard)

**Extends R-018's pre-authorization list.** `test_smoke.py` at 298/300 — the
next packet touching it creates `tests/test_smoke_wiring.py` and moves the
R-020 guard tests there.

Same standing-authorization shape as the `tests/test_cache.py` entry in R-018
and the R-009 precedent behind both.

## R-021 — Citations and the Files API are deferred (from P-006)

**Ruling: RATIFIED.** Citations and the Files API are deferred until a
consuming department exists — citations pair with the first department needing
sourced answers (likely Intent's research slot or the judges); the Files API
pairs with repeated-document workflows (Intent holding a user's spec across a
conversation). No renovation without a work order.

## R-022 — Verify payload shapes through the provider's transformation (from T-003)

**Ruling: RATIFIED.** Any packet introducing or changing a provider payload
shape must verify that shape through the provider's real transformation code
offline before the suite counts as green. Fixtures assert the
transformation-verified shape and cite it as the observation source (R-019).
Enforcement of: fakes model the API, never the implementation.

**Where it takes effect:** `tests/test_adapters.py` now runs the adapter's real
output through LiteLLM's `AnthropicConfig.transform_request` — asserting that a
text document keeps `source.type: "text"`, that no base64 document source
carries a media type other than `application/pdf` (the exact T-003 defect), and
that the cache mark survives on the system block. The check costs ~1.2s and no
network.

**Why:** three green-suite-but-broken-live failures in one session — `load_env`,
`include_usage`, and T-003 — all shared one cause: the fixture encoded our
assumption, so it could only ever agree with itself. The transformation check
that catches this is the same one that refuted H1 in T-002, and it is free.

## R-023 — P-007 flags all ratified (from P-007)

**Ruling: RATIFIED.** P-007 flags all RATIFIED — `smoke_families.py`,
`smoke_proves.py`, `test_adapters_openai.py` into the file map (R-017;
re-export pattern approved for splits that preserve public surfaces);
`test_streaming.py` as topic-correct streaming home; root `.env.example`
confirmed (P-007's map erred, not the build — packet file maps must reflect
prior amendments); lazy `dump_usage` import per R-008 pattern.

**Standing note:** LiteLLM's cost map keys without provider prefixes; the
stripping lookup is a known seam — verify it on the double-prefixed OpenRouter
family.

**R-022 credited with its first pre-ship catch:** the file-part filename
injection.

## R-014 corollary — config-independence holds in every dimension (from P-007)

**Ruling: RATIFIED.** Config-independence must hold in every dimension, not
just the asserted one — the family-count hardcode passed as config-independent
while one family existed, same disease as the max_tokens proxy one layer up.
Test: would a legitimate R-012 edit in ANY dimension (models, roles, families,
counts) turn this assertion red? If yes, the assertion derives, it doesn't
state.

## R-024 — R-022's ceiling: fidelity is not acceptance (from T-004)

**Ruling: RATIFIED.** R-022's ceiling: transformation checks prove translation
fidelity, not provider acceptance — different properties that coincide only
where the transformation validates. Where it doesn't, provider docs are the
acceptance authority (cite them) and the live smoke run is the final acceptance
gate.

**Layered defense confirmed working:** R-022 caught filename injection offline;
smoke caught MIME rejection live.

**Cross-provider pattern booked as a prediction for Gemini/P-008:** document
and file parts are PDF-only; text travels as text (observed: T-003 Anthropic,
T-004 OpenAI).

## R-025 — Effort ceilings are family knowledge, validated at load (from T-005)

**Ruling: RATIFIED.** Effort ceilings are family knowledge, validated at
registry load, never discovered at call time. Each adapter declares its
family's supported effort levels; `load_registry` rejects a role whose effort
exceeds its primary model's family ceiling, with an error naming the role,
family, and ceiling. R-014 compliant: legality against family rules, never
value choice. Cross-family fallback ceilings remain the human's responsibility
(R-012), surfaced by smoke.

**Also booked:**

- The prediction from R-024 **broke on Gemini** — `text/plain` `inline_data` is
  accepted, so the pattern is provider-specific, not universal. Both text
  candidates get tested by default for future families.
- Gemini's transformation entry point is `sync_transform_request_body`, not
  `transform_request`.
- Contract 4's temperature assertion was unsatisfiable as authored — our half
  is pinned, and LiteLLM's injected `temperature=1.0` is an open R-024
  acceptance question settled only by the live run.

---

## R-026 — P-009 flags ruled

**Ruling: RATIFIED on all four.**

**(1) Conditional pre-authorizations survive their packet.** Executing a prior
packet's conditional pre-authorization when its condition triggers later is
legitimate. P-008 authorized `adapters_gemini.py` conditional on the 300-line
ceiling forcing it; the fourth family forced it, so the condition was met.
`adapters_gemini.py` and `adapters_xai.py` are ratified into the map. The
re-export-identity test — asserting the lazily re-exported symbol is the same
object as the direct import — is approved as the split pattern's standing
guard. Flagging rather than assuming was correct form.

**(2) Packet file maps name RESPONSIBILITIES, not files.** A file split from a
parent inherits the parent's map entries. Touching `smoke_families.py` for a
cache note falls inside a map entry that says "smoke.py — cache behaviour",
because that is where the responsibility migrated. Responsibility-following
edits in split files need no R-016 flag. Root cause acknowledged as an
authoring defect: maps have been naming original files rather than current
homes.

**(3) Shared test fixtures may be imported across test modules; COPYING them is
what is forbidden.** R-009's letter said `conftest.py`; its intent was "shared
fakes live in one place, never duplicated." Importing `SmokeFake` from its
parent module honours the intent exactly — a copied fake would have been the
actual violation, since two fakes drifting apart is the flattering-fixture
disease R-019 exists to prevent. Physical location is layout, not law.

**(4) Standing note — `xai/grok-4.1-fast` is unpriced in litellm 1.97.0.**
Receipts would read `cost=None`. The priced ping column flags it exactly as
designed, so it is acceptable as outage insurance in a fallback position; a
primary position is the human's call under R-012.

---

## R-027 — Provider-facing fixtures answer to the strictest family (from T-006)

**Ruling: RATIFIED.** Provider-facing attachment fixtures must satisfy the
**strictest known family's** content rules, not the loosest, and the rule must
be **asserted by a test**. The IHDR-decoding dimension check is the pattern:
it decodes the fixture and asserts the minimum, and it was proven
discriminating against the retired 1x1 constant rather than assumed to work.

**Known content minimums — maintained here, in one place, so family five and
beyond inherit them:**

- **xAI: images at least 8x8 pixels** (T-006). Below that: `invalid_image`,
  "Image dimensions 1x1 are too small."
- No other family states a content minimum as of 2026-08-18.
- Future discoveries append to this list.

**Offline-only fixtures carry no content obligations.** Byte fidelity is their
whole job, and a single pixel is as good a witness as any image. Leaving the
1x1 constants in the offline adapter tests untouched was the right
discrimination; only *provider-facing* fixtures inherit content rules.

**Taxonomy booked — provider disagreement has three axes:**

1. **Shape acceptance** (T-003, T-004) — which part types a family takes.
2. **Translation fidelity** (R-022) — whether LiteLLM carries our shape intact.
3. **Content acceptance** (T-006) — a family can accept the envelope and reject
   the letter.

**Only the live run judges the third.** No offline instrument can guard it:
perfect byte fidelity of a 1x1 PNG is perfect fidelity of an unacceptable
image. This is R-024's layered defence gaining its third layer explicitly.

**Observation logged, not explained:** xAI reports a constant `cached=128` on
**both** calls of a byte-identical ~3.9k-token pair. That is not prefix-warming
behaviour; a fixed system-side segment is the plausible reading, but plausible
is not proven. Watched across runs. If it stays constant it is xAI's baseline;
if it ever grows with our prefix, that is their prefix cache engaging. Either
way the meter records what arrived.
