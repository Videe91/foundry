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

- **xAI images — TWO independent minimums, both required** (T-006):
  1. **each side at least 8 pixels** — `invalid_image`, "Image dimensions 1x1
     are too small. Both width and height must be at least 8 pixels."
  2. **at least 512 pixels in total** — `invalid_image`, "Image has 256 total
     pixels (16x16), which is below the minimum of 512 pixels."
  Appended 2026-08-18: clause 2 was discovered only after clause 1 was fixed.
  A 16x16 fixture satisfied the error message we had and was still rejected.
  **The provider reported its rule one clause at a time**, so a guard written
  from an error message is a guard written from half a rule. Fixture is now
  32x32 (1024 pixels), clearing both with margin.
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

---

## R-028 — The per-model sweep ruled (from `model-evidence.md`, T-007)

**Ruling: RATIFIED.**

**`ledger/model-evidence.md` is a permanent, append-only instrument.** It records
what each model has been *observed* to do, as distinct from what its family is
assumed to do. **Human-authorised targeted probes with scratch-path meters are
the approved method** — the probe never writes to `ledger/meter.jsonl`, so the
real ledger stays a record of real smoke runs.

### R-027 corrected, by measurement

- **xAI caches in 128-token blocks, committed asynchronously.** Not "a ~128-token
  floor". Seven of seven observed values are exact multiples of 128, and one
  byte-identical pair went **backwards** — 2,560 then 128 — which a synchronous
  cache cannot do. Asynchronous by proof, not by inference. xAI cache figures are
  therefore not reproducible within a run and must never be asserted.
- **Gemini implicit caching engages between 5,682 and 6,109 tokens**, commits
  **whole ~4,096-token blocks only**, and is **position-independent** (identical
  behaviour for `systemInstruction` and a user message). The documented 4,096
  minimum is **necessary, not sufficient**: a 4,584-token prefix cleared the
  documented bar and cached nothing.

### Standing knowledge: `max_tokens` must budget reasoning plus visible output

A cap that fits only the answer yields a **successful, correctly-metered, EMPTY
call**. Confirmed on Gemini (29 reasoning tokens, zero text, `finish_reason=
"length"`) and on Anthropic. **Ping's 8-token cap is legitimate** — it tests
liveness, not content. **Any content-asserting probe budgets reasoning.**

### Opus-5

Matrix columns are **UNKNOWN due to provider outage**, confirmed by status page
and differential evidence: it failed identically streamed and blocking, with and
without attachments, on a minimal call, while three sibling Anthropic models
answered in the same minute. **Re-probe on recovery.**

### T-007 ruled: the shared cache block is retired

**Cache demo blocks become PER-FAMILY**, each sized to that family's *measured*
effective minimum plus margin, **declared beside that family's cache note** with
the sizing evidence cited:

| family | paragraphs | tokens | measured minimum |
|---|---|---|---|
| anthropic | 60 | ~3,721 | 2,048 (T-002) |
| openai | 60 | ~3,721 | 1,024 |
| xai | 60 | ~3,721 | 128 (one block) |
| **gemini** | **105** | **~6,511** | **6,109 measured; 4,096 documented** |

A family with no declared block **falls back to the largest, never the
smallest** — oversized costs slightly more and still demonstrates caching, while
undersized demonstrates nothing at all, silently. That silence was the defect.

### Matrix amendment

- A distinct **`UNAVAILABLE`** cell for 5xx / overload / capacity errors, after
  **one bounded retry (~20s)**. Matched on the provider's own words rather than
  the exception class, because LiteLLM wrapped the identical Opus-5 condition as
  `MidStreamFallbackError` when streaming and `InternalServerError` when
  blocking.
- **Prove and matrix output print a visible note whenever `model_used` differs
  from the role's primary.** The fallback chain is meant to absorb an outage; it
  is not meant to conceal which model did the work.

---

> **Numbering note:** R-029 is intentionally unused. R-030 was assigned directly
> by Cortex; the gap is deliberate, not a removed ruling.

---

## R-030 — A ruling that corrects a class comes with a sweep for its siblings

**Ruling: RATIFIED.**

When a ruling corrects a **CLASS** of defect, the same amendment **sweeps the
codebase for other instances of that class before closing** — a class rarely has
one member.

**Precedent:** R-028's config-vs-capacity taxonomy was fixed in the matrix while
the **ping gate held the earlier, and more damaging, copy of the same bug for
another hour** (T-008). The matrix would have rendered the outage as
`UNAVAILABLE` exactly as ruled; it never got the chance, because the gate
returned 1 first and stopped a nine-model sweep with advice — "fix
registry.toml" — that was wrong. One instrument was corrected, its sibling was
not, and the untouched copy sat one layer *upstream* of the fixed one, where it
did more harm.

This is a **ruling-application** rule, not a code rule. The failure was not in
the taxonomy, which was right, nor in the matrix change, which was correct and
complete for what it named. It was in treating "the ruling is applied" as
finished once the instrument that prompted the ruling was fixed.

**In practice:** before closing an amendment that corrects a class, name the
class out loud, then grep for it. If a second instance exists, it is in scope —
whether or not the packet or ticket mentioned it. If a second instance exists and
is deliberately left, say so and why, so the omission is a recorded decision
rather than an oversight.

**Also ratified, without ceremony:**

- The R-017 split creating `tests/test_smoke_ping_gate.py` — both parents had
  crossed the ceiling and one dedicated home beats two partial ones.
- The ~6-second cold-cache cost in
  `test_adapters.py::test_transformation_keeps_text_documents_on_a_text_source`,
  **noted and not fixed** — correct restraint, outside T-008's scope. Recorded
  here as the known lever should suite runtime ever need attention.

---

## R-031 — An aggregator family declares no effort vocabulary (from P-010)

**Ruling: RATIFIED as the packet defines it.**

An **aggregator family has NO family-wide effort vocabulary.** The vocabulary
belongs to the **routed model**, not to the front door: DeepSeek V4 Pro documents
high and xhigh; Kimi's is unpublished; hundreds of other routable models vary and
change without notice.

Therefore the `openrouter` family **declares no ceiling**, and load-time
validation **skips it** — exactly as it skips a family with no adapter at all.
Effort compatibility on an openrouter role is the **human's per-model
responsibility** under R-012, surfaced by ping and prove. The adapter still
passes `reasoning_effort` through when set (OpenAI-compatible passthrough,
transformation-verified).

**Why a ceiling would be worse than none.** R-025 exists because an effort level
a family cannot serve should fail at load rather than at call time. That
reasoning depends on the family *having* a vocabulary to check. Invented for an
aggregator, a ceiling does one of two harms and cannot avoid both: set narrow it
rejects a lawful config that the routed model accepts, set wide it licenses a
config the routed model will reject at call time. The honest answer is to
declare nothing, which is a statement about knowledge rather than a permission.

**The mechanism is an absence, not a special case.** `OpenRouterAdapter` declares
no `EFFORT_LEVELS`, so `effort_levels_for` returns None and the existing R-025
guard has nothing to check. **Nothing in `load_registry` names openrouter**, and
a test asserts that by inspecting the module source — a special case would have
been a second thing to keep in step with the first.

**Guarded by a discriminating pair.** An openrouter role loads at *all five*
effort values; gemini still rejects `xhigh` and xai still rejects `max`, each
naming role, family and ceiling. Were the skip accidentally widened, the second
half would pass vacuously and R-025 would be dead without a failing test.

### Also recorded from P-010

- **The R-023 seam was broken, and found before any adapter code existed.**
  Contract 1 mandated the seam test first; it failed. The priced lookup stripped
  exactly one prefix, so `openrouter/anthropic/claude-opus-5` — an ordinary thing
  for a human to configure — reached `anthropic/claude-opus-5`, missed, and would
  have reported UNPRICED with `cost=None` on every receipt. **568 cost-map
  entries were unreachable that way.** Fixed with progressive stripping: full
  string first, then each stripped form, first hit wins.
- **R-030 sweep performed, one member found.** Three prefix-splitting sites
  exist; `family_of` and `load_registry`'s error text both take segment `[0]`,
  which is correctly `openrouter` for a double-prefixed string. Only the cost
  lookup assumed a single prefix. The absence of siblings is recorded so it is a
  decision rather than an oversight.
- **Redirect slugs are forbidden repository-wide**, enforced by a scanning test
  that proves its own reach and its own matcher before trusting its silence.

---

## R-023 CONFIRMED — the seam prediction, resolved by P-010

R-023's standing note read: *"LiteLLM's cost map keys without provider prefixes;
the stripping lookup is a known seam — **verify it on the double-prefixed
OpenRouter family**."*

**Verified. The prediction was correct, and the seam was broken.**

Single-prefix stripping left **568 real cost-map entries unreachable**. A
double-prefixed string reached only its once-stripped form:
`openrouter/anthropic/claude-opus-5` → `anthropic/claude-opus-5` → miss, while
the map prices it bare as `claude-opus-5`. Every such model would have reported
UNPRICED with `cost=None` on every receipt — a silent costing failure, not a
loud one.

**Fixed with progressive stripping**, pinned against the **observed** keying,
which is inconsistent by measurement rather than by assumption:

- **97 keys carry the full double prefix** (`openrouter/anthropic/claude-opus-4.6`)
- **many others carry none at all** (`claude-opus-5`)

So no single stripping depth is correct. The lookup tries the full string, then
each progressively-stripped form, first hit wins. The guard **failed before it
passed**, which is the only way to know it discriminates, and a companion test
holds the four certified families to their existing resolution so the fix could
not have been a widening that broke nothing visibly.

R-023's standing note is hereby **closed**. The seam it predicted was real.

**R-031 recorded as implemented-by-absence.** The aggregator effort skip is not a
branch: `OpenRouterAdapter` declares no `EFFORT_LEVELS`, so `effort_levels_for`
returns None and the R-025 guard has nothing to check. **Nothing in
`load_registry` names openrouter**, and this is asserted by **source
inspection** rather than by behaviour alone — a special case would have been a
second thing to keep in step with the first, and the test would not have noticed
it drifting.

**Standing note — P-010's four target models are UNPRICED by design.**
`moonshotai/kimi-k3`, `moonshotai/kimi-k2.7-code`, `deepseek/deepseek-v4-pro-0813`
and `deepseek/deepseek-v4-flash-0731` are **absent from litellm 1.97.0's cost map
under every form** — full double-prefixed, once-stripped, and bare. This is not
the seam and is not fixed by progressive stripping; the entries simply do not
exist. They render **UNPRICED in ping**, which is the warning working exactly as
designed, and their **receipts carry tokens with `cost=None`** until a pin
revision prices them. Metering is unaffected: token counts are the provider's,
only the dollar estimate is absent.

---

## R-032 — P-011's two ambiguity resolutions RATIFIED; tests must pass on a fresh clone

**Ruling: both resolutions RATIFIED as built.**

**1. `signatures` is an APPEND-ARRAY, not a table keyed by status.** The
Dictionary said "table"; contract 4 said "appends". The long-haul loop revisits
states — `live → amended → building → … → live` — so a status-keyed table would
overwrite the previous signing of `building` and lose precisely the history a
signature chain exists to keep. Appending is the only reading that survives the
documented lifecycle, and a test signs `building` twice to hold it.

**2. `registry.toml` is ABSENT-BY-CONTRACT at birth.** The test list said "every
Dictionary path property exists after create"; contract 1 said "does NOT create
a project registry.toml (absence = inherit global, by design)". They conflict on
exactly one entry, and the reasoned contract wins: every other skeleton file is
stamped, registry.toml is not. An empty registry would not be a harmless
placeholder — it would **override the global brains with nothing**, which is the
opposite of what its absence means (16.2 rule 2, R-012). Pinned by name in
`NEVER_CREATED`.

### Booked as a class: tests must pass on a fresh clone

**A probe that depends on untracked local state is the flattering-fixture
disease pointed at the filesystem.**

Found by cold verification. P-011's git-law test probed `git check-ignore
projects` — the bare name. The rule is `projects/`, directory-only and correct,
and git can only match a bare `projects` when that directory happens to exist on
disk. The workspace root is untracked, so the probe passed on the machine that
wrote it and failed on a fresh clone: the test's result depended on local state
rather than on the rule it claimed to verify.

**Fixed** by probing paths INSIDE the root — `projects/anything-at-all` and
below — which match the directory rule regardless of what exists locally.
Demonstrated both ways with the directory removed: the old probe fails, the new
one passes. The discriminating companion stands, asserting the rule is not an
over-broad ignore that would hide the factory's own source.

**The standing rule:** a test may not depend on state that a fresh clone does
not carry. Untracked directories, developer-local files, and anything a
`.gitignore` removes from a checkout are all outside what a test may assume.

---

## R-033 — Intent's three founder rulings (from P-013)

**Ruling: RATIFIED as the packet defines it.**

**(a) Contradictions are SURFACED — latest wins, but the founder is told and
confirms.** When a later statement conflicts with something already confirmed,
the new content stands *as content*, but the box is **demoted to `proposed`**
and a `Contradiction` is recorded. The Interviewer is instructed to raise the
oldest unsurfaced one ("earlier you said X, now Y — going with Y, correct?"),
and it is marked surfaced only once it has actually been handed over.
**Completeness is blocked while any contradiction is unresolved**: a signed
constitution may not contain a conflict someone already noticed.

**(b) Impatient founders get PROPOSED DEFAULTS requiring explicit confirmation
— Foundry never self-signs a constitution.** A deflection ("you decide") lets
the Interviewer fill a box, recorded with `proposed_by="interviewer"` so its
authorship is never lost. That box lands in `pending_confirmations` and
**counts for nothing** until a user turn affirms it. **A box counts toward
completeness ONLY when `status == "confirmed"`** — proposed content, however
good, is not consent. There is no path from `proposed` to `confirmed` that does
not run through a user's own words.

**(c) The role names are `interviewer` and `scribe`.** Stubs added to the
shipped registry as a human-authorised config edit under R-012 — sonnet-5 and
haiku respectively, **placeholders that P-014's bake-off decides on evidence.**

### The line this draws, recorded because it governs every later department

**Charm is the model's job; truth is the code's.** The engine never generates a
word of the interview — it hands the Interviewer a structured directive and
returns whatever comes back, verbatim. Completeness is pure code, one rule per
box, because a model asked "is this good enough?" will say yes to be agreeable,
and a constitution signed on an agreeable answer is worth nothing. This is the
Mediocre-Model Test pointed at ourselves: the engine must be correct with a
mediocre model on the other end.

### Seam law extended (the P-012 discipline)

`intent` MAY import `workspace` — one direction, downward, because it works on
projects. It must **never** import `switchboard` or `litellm`: the two brains
arrive as **injected callables matched by shape**, and composition with real
models happens at the edge in P-014. Enforced by subprocess guards in both
directions — `intent` pulls in neither forbidden package, and **`workspace`
stays a leaf**, importing neither `intent` nor `switchboard`.

---

## R-034 — A test may not depend on a sys.path only the test runner builds

**Ruling: RATIFIED.**

**R-032's sibling**, and the pair states the whole rule between them:

- **R-032:** a test may not depend on **state a fresh clone lacks**.
- **R-034:** a test may not depend on **an import environment only pytest
  constructs**.

### The pattern: the installed-invocation subprocess test

Run **the user's exact command**, `cwd` at the repo root, `PYTHONPATH`
**stripped**, in a subprocess — and **skip** when the packages are not
installed, because a bare clone has not run `pip install -e` and R-032 forbids
failing on state a checkout does not carry.

### Guards must state their own reach

**An honestly-limited guard beats a silently-overclaiming one.** A test whose
docstring admits what it cannot see is worth more than one that reads as total
coverage and is not, because the second teaches a future reader to stop looking.

The namespace-shadow check is the example: under pytest the injected `src/`
paths make it pass regardless of what is installed, so its docstring says so and
points at the subprocess test as the thing that actually covers CLI startup.

### Precedent

The `intent` namespace shadow — **564 green tests and a CLI that could not
start.** `foundry_cli/pyproject.toml` injected `../intent/src` into pytest's
`pythonpath`, so the real package always won under test. A plain run from the
repo root had no such help, and Python treated the repo-root `intent/`
**directory** as an empty PEP 420 namespace package: `import intent` succeeded
and `intent.state` did not exist. The error text was the tell — `No module named
'intent.state'`, not `'intent'`.

**The sixth costume of guard-passes-for-the-wrong-reason.** The others: the
Gemini cache label (T-002 shape, prefix below threshold), the flattering fixture
(T-003/T-004), the image rule read from one clause of an error message (T-006),
the cache block sized to the wrong family's minimum (T-007), and the git-law
probe reading local filesystem state (R-032). Each time the assertion was true
and measured something other than what it claimed. The class does not seem to be
running out of costumes, which is itself the argument for cold verification
staying in the loop permanently.
