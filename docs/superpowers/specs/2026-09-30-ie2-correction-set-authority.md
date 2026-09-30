# IE2 Atomic Correction-Set Authority: Decision Record

**Status:** implemented 2026-09-30 (`ie2-authority-routing-v2`). No live call was made. The
long-horizon experiment was not rerun.

**Decided by:** the architect, choosing Option B after the contradiction stop report.

**Amends:** `2026-09-30-ie2-authority-routing.md` §4, whose claim that edge-level partial approval is lawful is withdrawn for corrections, and §7, whose decline question is now decided.

## 1. Why: the admission-order audit

**v1 `propose_and_submit`.** Judgments are submitted one by one in response order. Each is recorded, then routed by `route_judgment` over a freshly replayed state. The partial outcome comes from kind, not order:

| Judgment | Rule | Route |
|---|---|---|
| `ASSERT_CLAIM` (INFERRED) | not a material kind (rule 6) | `LOW_RISK`, **APPLY** immediately |
| `SUPERSEDE` | material (rule 7) | `REQUIRE_SECOND_LENS`, unless an independent lens or a covering human `AuthorityRecord` (rule 4) |

**Effect.** A correction "new claim X replaces old claim Y" therefore made X current at once, while the retirement of Y waited for authority.

**Frozen T13, concern D (run `a0ee2f7`).**
- `CLAIM-5a75c5d7` ("any delivery with the same job id is ignored") stayed current.
- Its correction, the id-plus-key rule (two claims), was applied beside it.
- The locus was CLAIMED, not DISPUTED. It was withheld from IE3 only because the SUPERSEDE was pending.

A decline, or any end of the hold, would have delivered both rules as settled.

**Other paths.**
- 9P3 checkpoints agreed individual SUPERSEDEs, so edge by edge.
- No other path applies part of a correction.

## 2. The correction set

**Grouping** (`domain.correction_set.form_correction_sets`). This is deterministic and reads judgment fields only. Within one non-human response, a correction set forms for every address that at least one SUPERSEDE retires a claim at. Its members are:
- every `ASSERT_CLAIM` at that address;
- every `SUPERSEDE` of a claim there (the target's single address, by `judgment_address_ids`).

**Whole-address hold.** Judgments carry no proposition id, so a correcting ASSERT and a compatible ASSERT at the same address cannot be told apart without guessing. The whole address is held. The cost is that a compatible new claim at a corrected address waits with the correction.

**Left to ordinary law:**
- `SUPPORTS_CLAIM`. A support of a still-current claim is lawful whatever the decision.
- ASSERTs at addresses no SUPERSEDE of the response touches.
- A SUPERSEDE with an unknown target (refused structurally).
- A SUPERSEDE whose target bears on several addresses (a relation judgment, not a claim). It stays a v1 per-signature item.

**Identities.**

| Identity | Formula |
|---|---|
| Instance | `CSET-` + sha256(project, invocation, address)[:24]. One per address per response. |
| Equivalence (decline and repeat) | `CEQ-` + sha256(project, address, sorted target judgment ids, sorted sha256 of the **content** of the evidence the ASSERT members cite)[:24] |

The equivalence key uses content, not evidence ids, because the same section text redelivered under a new evidence id is the same basis. Changed text, or a different target set, is a new basis. The model's wording and fingerprint never enter either key: a different proposer does not escape a decline.

**Routing** (`route_correction_set`). Every member is first routed by the unchanged admission rules.

| Condition | Outcome for every member | Set recorded? |
|---|---|---|
| One structural refusal | `REJECT` (`CORRECTION_SET_INVALID`) | no |
| Equivalent to a DECLINED set | `REJECT` (`CORRECTION_DECLINED`, set id) | no |
| Equivalent to a PENDING set | `REJECT` (`CORRECTION_SET_REPEAT`, set id) | no, so a repeat never becomes a second obligation |
| Otherwise | `REQUIRE_HUMAN` (`CORRECTION_SET_MEMBER`, set id) | `CORRECTION_SET_PROPOSED` is appended |

## 3. States and events

**PENDING** (`CORRECTION_SET_PROPOSED`).
- Nothing of the set is current, and the pre-correction state is.
- Every member is pending, whatever else agrees with it.
- The address is withheld from IE3 (`MISSING_AUTHORITY`, unchanged).
- The set is one authority-work item (`CorrectionSetWorkItem`, `work_id` = set id, `HUMAN_AUTHORITY`).
- No member appears in a per-signature item.
- No member is a lens (`admission._is_lens`), so no independent proposal can corroborate one edge apart.

**AGREED** (`CORRECTION_SET_DECIDED`, `AGREE`).
- Every member is applied inside this one event: assertions first, then supersessions.
- Before appending, the governor re-routes every member over current state. One refusal (for example a target retired meanwhile) refuses the whole decision, and nothing is written.
- The reducer applies all members or refuses the event.
- One issue version is minted per touched address over the **final** state, so history holds no snapshot of a half-applied set.
- That version names the last member (a SUPERSEDE, as any supersession does). It is recorded DERIVED_FROM every other member, so the existing staleness law marks it stale if any member's effect later ends. This is the one mechanical consequence of atomic application; it uses the existing derivation primitive and adds no field.

**DECLINED** (`CORRECTION_SET_DECIDED`, `DECLINE`).
- Nothing applies.
- The decision is durable: decider, authority record, rationale and event id are all recorded.
- Members are no longer pending, so the concern is released with its pre-correction state.
- Any later equivalent proposal is refused `CORRECTION_DECLINED`. A changed basis or target set reopens the question as a new PENDING set.

**No partial outcome.** A set has at most one terminal decision. The reducer refuses a second one ("already AGREED/DECLINED"), so a mixed outcome cannot be recorded.

## 4. Authority and concurrency

**Who may decide.** Only an authenticated `human://` principal with a live, project-wide `AuthorityRecord` of their own. This is the coverage a human AGREE of a supersession already needs (rule 4). It is checked twice:
- by `application.authority_routing.decide_correction_set`, before anything is written;
- by the reducer, so a forged or borrowed decision is unreplayable and never appended.

**Refusals, all before anything is written:**
- a stale `expected_sequence`;
- an unknown set;
- a resolved set;
- a non-human actor;
- an unauthorized human;
- an empty rationale.

Of two racing terminal decisions, the first wins whole.

**API.**
- `decline` is the DECLINE of a set. For a v1 per-signature item it raises `DeclineRefused`: only a correction set has a decline decision.
- Legacy `agree` is unchanged for per-signature items (fingerprint policy `ie2-authority-routing-v1`). Given a set id, it refuses and points to `decide_correction_set`.

## 5. Verified on the frozen run (offline, the model's own replies)

**T8** (5 judgments at the retry address):
- It forms one set: 2 ASSERTs (5-second wait, fixed wait) and 3 SUPERSEDEs (`JDG-cf225a3b`, `JDG-6dc43a9d`, `JDG-e1da6031`).
- The SUPPORT is ordinary.
- Nothing retires while it is PENDING.
- AGREE retires exactly the three and makes the two new claims current.
- DECLINE changes nothing.

**T8→T9.**
- **Under AGREE:** T9 assimilates in two calls, using the corrected T9 answer the cardinality fixture uses.
- **Under DECLINE:** the model's unchanged T9 reply re-proposes the same correction on byte-identical basis content. It is refused `CORRECTION_DECLINED`, and T9 proceeds.
- **Both cases:** the H claim (repeated cancellation) becomes current, and no authority work remains.

**T13** (from the frozen pre-T13 ledger):
- It forms three sets (retry, D, lease). The H claim applies ordinarily.
- **D while PENDING:** the old rule is current, its correction is not, and D is withheld from IE3. The v1 contradiction is gone.
- **D after AGREE:** only the id-plus-key rule is current, and IE3 sees it.
- **D after DECLINE:** only the old rule is current, and IE3 sees it.
- **Every case:** never both rules at once.

## 6. Identity and history

**New identity.** `ie2-authority-routing-v2`, the protocol literal on `CorrectionSetDecidedPayload`.

**New events.** `CORRECTION_SET_PROPOSED` and `CORRECTION_SET_DECIDED`.

**New state.** `SemanticState.correction_sets`, empty for every existing ledger.

**The policy switch.** `AdmissionPolicy.correction_sets` defaults to `False`. Every historical ledger and frozen experiment therefore admits exactly as recorded, with no migration: the frozen long-horizon run replays with no correction set at any boundary.

**Model contract.** Unchanged. `intent-v2-locus-v6` (prompt `13aa8774…`, schema `921171df…`) is byte-identical.

**IE3.** No semantic change. It still sees only settled concerns, and set members use the same pending withholding.

## 7. Not decided here

- Whether and when production and future experiments turn `correction_sets` on. It is opt-in per `AdmissionPolicy`, and this change turns it on nowhere outside tests.
- Whether a future model contract should carry proposition ids on judgments, so that a compatible ASSERT at a corrected address need not wait with the correction (§2). That would be a model-contract change, a new policy version.
