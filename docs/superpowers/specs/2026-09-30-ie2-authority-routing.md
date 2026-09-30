# IE2 Authority Routing: Decision Record

**Status:** implemented 2026-09-30 (`ie2-authority-routing-v1`) with no live call.
**Origin:** the frozen long-horizon run `a0ee2f7`, which was read and not modified.

## 1. The checkpoint-only failure, from the recorded events

At T13, which is not an authority checkpoint, grok-4.6 (`intent-v2-locus-v5`) proposed four SUPERSEDE judgments. All four were routed `REQUIRE_SECOND_LENS` (`MATERIAL_REQUIRES_SECOND_LENS`):

| Judgment | Target | Concern |
|---|---|---|
| `JDG-bf06e7e6` | `JDG-cf225a3b` (2-second first wait) | B |
| `JDG-6e1bc113` | `JDG-e1da6031` (doubling) | B |
| `JDG-767498e4` | `JDG-2a3581f5` (ignore by job id) | D |
| `JDG-d6305087` | `JDG-277ce7e7` (renew every 30 seconds) | G |

**How long they stayed pending.** All four were in `view.pending_judgment_ids` from T13 through T16.

**What they blocked.** Every one of them put a `MISSING_AUTHORITY` blocker on its locus, so IE3's context showed 6 of 9 addresses (A–D, F and G withheld).

**Why they were never eligible.**
- The only thing that ever turned a pending judgment into an AGREE was the experiment's 9P3 module (`long_horizon_bounded.authority`).
- It runs only at the turns in `AUTHORITY_CHECKPOINTS`, and only for targets live at that checkpoint locus's address before the turn.
- At T14 (J) and T16 (I) the four targets were therefore `NOT_ELIGIBLE_NOT_AUTHORIZED`.

**What production offered.** Nothing actionable. The pending state existed only as a projection nothing consulted, and no production API listed it or resolved it by id.

## 2. The authority model before this change (audit)

1. **What awaits authority.** A `SemanticJudgment` whose latest admission route is `REQUIRE_SECOND_LENS` or `REQUIRE_HUMAN`, and that was never applied.
2. **Identity.** Its `judgment_id`. It carries:
   - the project;
   - the proposal (for SUPERSEDE, the target judgment, and so the target claims and address);
   - the rationale (`reason`);
   - the visible evidence;
   - the reasoner fingerprint (model and policy);
   - the invocation and time.

   It does not carry the accounting proposition id, which lives only in the response.
3. **Eligibility.** It is pending when no applied, active judgment `agrees()` with it (same kind, equal `proposal_signature`), per `semantic_view._pending_governance`.
4. **Who resolved it.** In production, nobody; in the experiments, the 9P3 module at checkpoints.
5. **"Human decision required."** It exists as the admission route, but there is no API for it.
6. **A query for unresolved work.** Only `pending_judgment_ids`.
7. **Deterministic and replayable.** Yes, it is a pure projection.
8. **Duplicate decisions.** An AGREE of an already-applied SUPERSEDE is refused structurally ("target already superseded").
9. **Late decisions.** Allowed: admission is timeless.
10. **Replay.** Replay preserves both states.
11. **Same-turn assumption.** Only in the experiment module.
12. **Declining.** There is **no decline decision**: "a declined or unanswered SUPERSEDE stays pending … No workflow record exists" (`semantic_view`, spec §17 and §24).

## 3. The law

Every judgment awaiting an authorized decision is durable authority work. It is:
- discoverable by a stable id;
- resolvable at any time, by any authorized principal;
- replayable and idempotent;
- never lost.

Pending by design is never confused with unrouted.

**Projected, not stored.** `domain.authority_work` is a projection of `IntentState`:
- no new event, and no migration;
- every ledger, old ones included, yields its work on replay;
- the judgments remain the only semantic truth.

**One work item per pending proposal signature.** One AGREE satisfies every pending judgment with that signature, so a repeated proposal never becomes a second obligation. Each item carries:
- the stable id, `AUTH-` plus the sha256 of project, kind and signature;
- the pending judgment ids;
- the routes and reasons;
- `required_resolution`, from the existing admission law:
  - `REQUIRE_HUMAN` needs human authority;
  - `REQUIRE_SECOND_LENS` needs human authority or an independent lens;
- the addresses;
- for a SUPERSEDE, the target and its claims;
- who proposed it, the invocations and the evidence;
- the correction context: the ASSERTs and sibling SUPERSEDEs of the same invocation at the same addresses. This lets an N:M correction be decided with its whole shape in view.

**Unrouted judgments.** A judgment recorded with no admission is reported apart as `unrouted_judgment_ids`. That is the "lost" case.

**The invariant (`authority_routing_findings`).** It checks every boundary of the frozen run:
- every pending judgment is in exactly one item;
- every item names only pending judgments of one signature;
- no item id is duplicated.

**Decision (`application.authority_routing.agree`).** One authenticated `human://` principal agrees one work item, as of the ledger sequence the decision was taken at.
- The AGREE is a new judgment with the identical proposal, under that human's own fingerprint (policy `ie2-authority-routing-v1`).
- Unchanged admission decides whether it applies.
- **Refusals, which write nothing:**
  - a stale decision (the ledger moved);
  - an item that is no longer pending (a duplicate AGREE, or an unknown id);
  - a non-human actor;
  - an empty rationale.
- **Listing** writes nothing.
- **Nothing is approved** in bulk, automatically, or by a model. The proposing fingerprint is never its own lens (admission rule 7).

## 4. The authority unit: the edge, kept

Each SUPERSEDE target is decided separately. Before authority, IE2 already keeps the old claim current beside the new one; the 9P3 rubric says the old meaning "does not leave the current view before authority". A partly approved N:M correction is the same kind of state:
- every old claim still awaiting a decision stays current and visible as pending work;
- the concern stays withheld from IE3 (`MISSING_AUTHORITY`) and from delivery until every judgment bearing on it is resolved.

So no consumer ever treats a partly corrected concern as settled. Take the brief's example: the 5-second rule current, the 2-second rule retired, the 30-second cap still current and pending. That is lawful, and it is visible as unfinished.

Each edge asserts an independent fact ("this claim is obsolete"), so approving one without another is a coherent partial decision. An atomic correction-set unit would add a new durable concept without preventing any state that reaches a consumer, so it was not adopted. The correction context in each item keeps the whole set in front of the decider.

## 5. What later turns see

**IE2.**
- Known claims are the live ones: the old claims awaiting authority and the new asserted ones, with no pending marker. The model contract is unchanged.
- The model may propose again. The same fingerprint repeating itself never approves, and its repeat joins the same work item.
- Unrelated concerns proceed normally.
- A later restatement may SUPPORT either the old or the new claim; both are live until the decision.

**IE3.**
- It sees only settled concerns: a pending judgment bearing on a locus withholds the whole locus from the graph context.
- IE3 is not told that authority work exists. That stays outside its semantic graph context.

No IE2 or IE3 change was needed. `intent-v2-locus-v6` is byte-identical.

## 6. Identity and history

**New identities.** Only the authority protocol, `ie2-authority-routing-v1` (the AGREE fingerprint's policy version). Unchanged:
- no model policy change;
- no event-schema change.

**Historical ledgers.** The frozen 9P3 and long-horizon runs are untouched. Their AGREE events replay exactly: at frozen T3, the three projected items are resolved by the 9P3 AGREEs.

## 7. Architecture question (not decided here)

**ARCHITECTURE QUESTION:** Should an authorized principal be able to *decline* a pending proposal, and if so, how is that recorded?

- **No decline (current law).** A declined proposal stays pending forever and blocks its concern from IE3 and from delivery. That is honest, but a concern can be frozen by a proposal nobody will approve.
- **A durable decline decision.** A new judgment or admission outcome that ends a hold without applying it. That needs a new event or route, a replay rule, and a policy for re-proposal after decline.

**Blocked work.** DISAGREE and REJECT resolution, and racing AGREE against DISAGREE, cannot be built until this is decided.
