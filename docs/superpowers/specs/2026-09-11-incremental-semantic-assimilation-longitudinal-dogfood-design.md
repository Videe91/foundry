# Incremental Semantic Assimilation + Longitudinal Dogfood — Design

**Task:** 9P (amended by 9P-A). **Status:** PROPOSED — design only, awaiting architect review.
**Base:** `9afc0175fd42ed4a730fca9857a3fff5b1ada75b` (9O live result).
**9P-A amendment:** the correction protocol is `ASSERT_CLAIM` + `SUPERSEDE` only. A same-response
`CONFLICTS_WITH` against a not-yet-durable claim is impossible under the trust boundary
(the model never invents a durable claim id), and the earlier three-operation pattern would
have needed two human authorizations per correction. See §13, §17, §24.
**Governing law:** `FOUNDRY_CONSTITUTION.md` Laws 3, 4, 5, 7, 8, 9, 10, 11, 13; v2 design spec
`docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md` with its [9N LOCK]s.
No implementation, no plan, no model call, no live run is part of this task.

---

## 1. Problem

9O showed that a frontier model can drive the governed substrate over one static evidence
bundle. It did not show that the substrate lets a frontier model **assimilate change**.
The Foundry thesis is longitudinal:

> Frontier models supply intelligence. Foundry compounds that intelligence across time by
> turning temporary semantic judgments into durable, governed, evolving state.

The question 9P must make testable:

```text
Can new evidence arrive over time
without forcing the frontier brain to reconstruct the entire project's meaning from scratch?
```

## 2. Evidence from 9O

Observed, not assumed (`docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/`):

| Fact | Value |
|---|---|
| calls / cost / tokens | 3 · $0.401626 · 102,350 in / 8,523 out |
| discovery | 38 `CREATE_ADDRESS`, 38 distinct `(subject, facet)`, 34 distinct subjects |
| claims | 38 `ASSERT_CLAIM`, exactly one per address, all `INFERRED`, TEXT=34 ENUM=4 |
| reconciliation | 16 `DISTINCT`, 0 `EQUIVALENT`, 0 `CONFLICTS_WITH` |
| admission | 92/92 `APPLY` — no material kind was ever proposed |
| replay | 189 events, `REPLAY_MATCH` |
| most expensive call | reconciliation ($0.145, 36,985 input tokens) for the least output (1,346 tokens) |

Three lessons drive this design:

1. **Mechanics work.** Draft → runtime wrapping → admission → ledger → replay is sound.
2. **Whole-state reconciliation is the wrong shape.** The costliest call re-read all evidence
   plus all 38 addresses plus all 38 claims to confirm that 16 nearby things differ. The
   lifecycle must not re-run "everything against everything" per cycle.
3. **Nothing longitudinal was exercised.** All five files were visible in one context, so
   the model could consolidate inside a single window. `BIND_TO_ADDRESS`, `SUPERSEDE`,
   claim support, conflict, blast radius and scope response never fired live.

Two of the loci 9O discovered are exactly the ones whose meaning changed in Foundry's real
history: *"Admitted address bindings | referential status"* (Track A) and *"Intent
Intelligence v2 validation | primary versus subsystem gate"* (Track B). That makes them
ideal tracked loci: they were found by the model unprompted, and their interpretation
demonstrably changed between two real commits.

## 3. Foundry lifecycle thesis

```text
T1 initial evidence          → semantic state established
T2 new evidence              → bind to existing meaning where appropriate; create only what is new
T3 understanding changes     → old judgment stays historically visible; new interpretation governed
T4 correction authorized     → old interpretation superseded; current state changes
T5 downstream depended on it → blast radius marks it stale; unrelated scopes stay ready
T6 another brain inherits    → (deferred to 9Q, §33)
```

## 4. Scope

**In:** the semantics of `BIND_TO_ADDRESS`; claim support without mutation; evidence
versioning; semantic supersession and its authority; the smallest candidate-retrieval
strategy; the per-delta call architecture; blast radius and scoped closure under live
change; a two-arm experiment on real Foundry history with a preregistered expectation
manifest; the smallest implementation slice.

**Out:** everything in §36. In particular no embeddings, no general Context Compiler, no
Decision Engine, no second provider, no cross-model continuity (deferred).

## 5. Existing substrate (what already exists, unchanged)

| Primitive | Exists | Live-exposed in 9O adapter |
|---|---|---|
| `CREATE_ADDRESS`, `ASSERT_CLAIM`, `EQUIVALENT`, `DISTINCT`, `CONFLICTS_WITH` | yes | yes |
| `BIND_TO_ADDRESS` | yes — reducer records `bindings[candidate_id] = address_id`; view exposes `active_bindings`; rebinding an actively-bound candidate is refused (D-ADM-4) | **no** |
| `SUPERSEDE` | yes — append-only `SupersessionRecord`, chain-aware `active_judgment_ids`, material kind (second lens or human authority) | **no** |
| admission routing, independence by fingerprint, human authority via `AuthorityRecord` | yes | n/a |
| `DerivationEdge`, `descendants`, `stale_object_ids` → `view.stale_ids` | yes | n/a |
| scoped closure + `IntentDecisionHandoff` readiness (stale in scope blocks) | yes | n/a |
| `EvidenceItem` (id, project, scope, kind, ref, content, sha256, observed_at) | yes | n/a |
| `ReasoningRequest.allowed_judgment_kinds` (explicit task) | yes (9O) | yes |

Three things do not exist and are decided below: a way for new evidence to support an
existing claim without mutating it (§11–12); evidence version identity (§15); and a
derived "satisfied" status for a pending proposal that an authorized lens later applied
(§17).

---

## 6. New-evidence lifecycle (one delta)

```text
EVIDENCE DELTA (immutable new versions only)                     deterministic
        │
        ▼
CALL 1 — ASSIMILATION                                           frontier, bounded
  input : delta evidence + descriptors of candidate addresses
  allowed: BIND_TO_ADDRESS | CREATE_ADDRESS
  output: for each meaningful observation in the delta, EITHER a binding to an existing
          address OR a new address. Zero drafts is legitimate.
        │
        ▼
ADMISSION (both low-risk → APPLY unless structurally invalid)     deterministic
        │
        ▼
NEIGHBORHOOD = addresses touched by admitted bindings/creations   deterministic selection,
                                                                  never a meaning decision
        │
        ▼
CALL 2 — CLAIM ASSIMILATION                                      frontier, bounded
  input : delta evidence + live claims at the neighborhood addresses (+ their judgment ids)
          + evidence-version chronology for cited evidence
  allowed: SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH (known claims only)
  output: NO CHANGE (empty) | support for an existing claim | a new claim |
          a supersession proposal (correction) | a conflict between two ALREADY-KNOWN claims
  law   : every id a draft references must already be in the request. A claim asserted in
          this same response has no durable id yet and can be referenced by NOTHING in it.
        │
        ▼
ADMISSION                                                         deterministic
  SUPPORTS_CLAIM, ASSERT_CLAIM → low-risk → APPLY
  SUPERSEDE, CONFLICTS_WITH    → material → REQUIRE_SECOND_LENS (recorded, pending)
        │
        ▼
AUTHORITY STEP (only if a SUPERSEDE proposal is pending)         human, pre-authorized
  the AuthorityRecord holder AGREES (submits the identical proposal → APPLY under human
  authority; the AI proposal derives SATISFIED_BY) or DECLINES (nothing changes; the
  proposal stays pending and qualifies the affected scope's readiness, §24).
  At most ONE authorization per tracked correction. Pending CONFLICTS_WITH proposals are
  never human-authorized in 9P.
        │
        ▼
DURABLE STATE · blast radius recomputed · scope readiness recomputed
```

Two frontier calls per delta. No reconciliation sweep. No retrieval failure is possible in
9P (§18), so a wrong binding or a missed reuse is attributable to the model, not to
retrieval.

## 7. `BIND_TO_ADDRESS` semantics

`BIND_TO_ADDRESS` is an AI judgment that **a new transient semantic observation refers to
an existing durable semantic address.**

Answers to the ten questions (task §8):

1. **What is bound?** A `SemanticCandidate` — the model's observation of *a subject/facet
   grounded in specific evidence*. It is the same shape that `CREATE_ADDRESS` carries; the
   only difference is that the reasoner asserts it refers to an address that already exists.
2. **Is it a `SemanticCandidate`?** Yes. The candidate is minted by runtime (id, scope from
   cited evidence) exactly as in 9O; the model supplies subject, facet, evidence ids and the
   target `address_id`.
3. **What is durable after the candidate is gone?** Three things, all already in the
   substrate: the immutable `SemanticJudgment` record (which carries the candidate, so its
   descriptors and evidence are readable forever); the `bindings[candidate_id] → address_id`
   entry; and the issue version minted at the address. The candidate object itself has no
   independent lifecycle — it is preserved *inside* the judgment.
4. **How does the binding retain evidence?** Through `candidate.evidence_ids`. The derived
   view's evidence-at-address is the union of every active binding's candidate evidence
   plus every live claim's evidence at that address. This is how new evidence lands on an
   existing locus **without** creating a claim.
5. **How is it superseded?** `SUPERSEDE(target = the BIND judgment)`. The reducer already
   drops inactive bindings from `active_bindings`; the record stays readable. Rebinding the
   same candidate elsewhere requires that supersession first (D-ADM-4, already enforced).
6. **How does it differ from `EQUIVALENT`?** §8.
7. **When should AI prefer BIND over CREATE?** When the observation's *subject and facet*
   denote a locus that an existing address already denotes, regardless of wording. CREATE is
   the correct answer when no known address denotes it (**NO_MATCH is legitimate**, §13 of
   the task). The system instruction states both and forbids forcing a fit.
8. **One evidence item, several candidates?** Yes. A spec section can ground several loci.
9. **Several evidence items, one candidate?** Yes. `candidate.evidence_ids` is a tuple.
10. **Rebind only after supersession?** Yes — already law (D-ADM-4).

**Admission class:** `BIND_TO_ADDRESS` stays **low-risk** (auto-apply). Rationale: a binding
adds an evidence edge and an observation to a locus; it changes no claim, settles nothing,
and is fully reversible by supersession. Contamination risk (failure mode 2) is real but is
handled by measurement and correction, not by making every binding material — making it
material would put a second lens on every evidence arrival, which is exactly the cost
profile 9P is designed to escape.

## 8. `BIND` versus `EQUIVALENT` — validated and locked

The proposed distinction is correct, and it is sharper than a naming convention:

```text
BIND_TO_ADDRESS      transient observation  →  existing durable address
                     prevents durable duplication from being created

EQUIVALENT           existing durable address A  ↔  existing durable address B
                     repairs durable duplication that already exists
```

Consequences that follow from the substrate, not from preference:

- BIND creates **no new identity** and touches **one** address; EQUIVALENT joins **two**
  identities into one locus and re-mints heads for the whole locus.
- BIND is low-risk (reversible, no merge); EQUIVALENT is material (it changes which claims
  share a locus and therefore what can conflict).
- Under bind-first assimilation, EQUIVALENT is a **maintenance** operation, not part of the
  per-delta loop. 9O's 0 EQUIVALENT / 16 DISTINCT result is consistent with this: pairwise
  reconciliation over a healthy state mostly confirms difference at high cost.

**Locked:** the per-delta assimilation loop never asks for `EQUIVALENT` or `DISTINCT`.
Duplicate creation is *measured* (§30) rather than repaired inline. A future maintenance
sweep over a suspected-duplicate neighborhood is out of scope for 9P.

## 9. Candidate lifecycle

```text
model draft (subject, facet, evidence_ids[, address_id])
   → runtime mints candidate_id and scope            (ephemeral object, owned by runtime)
   → wrapped into a CREATE_ADDRESS or BIND_TO_ADDRESS judgment (immutable record)
   → admitted → bindings[candidate_id] = address_id ; issue version minted
   → the candidate persists only as content of its judgment
```

A candidate is **ephemeral as an object and durable as a record**. Nothing else is needed.

## 10. Claim assimilation

Call 2 reasons over the delta and the neighborhood's live claims. Its outcomes, in order of
preference the instruction states:

| Situation | Correct output |
|---|---|
| new evidence restates a live claim | `SUPPORTS_CLAIM` (no new claim) |
| new evidence asserts something not yet claimed at the locus | `ASSERT_CLAIM` |
| new evidence **corrects** a live claim (the old interpretation is no longer current) | `ASSERT_CLAIM` (the new interpretation) **and** `SUPERSEDE(old claim's created_by_judgment_id)` — the correction path (§13) |
| new evidence **contests** a live claim and the reasoner judges neither should retire | `ASSERT_CLAIM` only. A `CONFLICTS_WITH` between the new claim and the old one cannot be proposed in this response (the new claim has no durable id yet); it may be proposed in a later call once both claims are known |
| two claims **already shown** in `known_claims` cannot both be true | `CONFLICTS_WITH(known_a, known_b)` — valid, material, pending; not a 9P expectation |
| new evidence is irrelevant to the neighborhood | nothing (empty drafts) |

"One claim per evidence arrival" is explicitly **not** a rule. Empty output is legitimate.
**Reference law:** a draft may reference only ids present in the request — known
addresses, known claims, known claims' `created_by_judgment_id`, and request evidence.
Runtime mints every new claim id after the response; the model never invents one, and no
draft in the same response may refer to a claim created by that response.

## 11. Existing-claim support — decision

Three candidates were evaluated:

**A. Binding alone.** The BIND candidate's evidence lands on the *address*. This correctly
expresses "this evidence is about this locus" but cannot express "this evidence supports
*claim C1 rather than claim C2* at this locus". Once an address holds two claims — which is
precisely the supersession case — address-level evidence is ambiguous, and Law 11's *"what
evidence supports that decision"* becomes unanswerable at claim granularity. **Insufficient
on its own.**

**B. Explicit `SUPPORTS_CLAIM` judgment.** A semantic judgment (AI decides that evidence E
supports claim C) recorded like any other, reduced into an immutable append-only
`ClaimSupportRecord`. **Recommended** — see §12.

**C. "Add evidence to the claim" via a relationship.** Same as B in effect; the difference is
whether the link is a *judgment* (governed, provenance-bearing, supersedable) or a bare
relationship. It must be a judgment: whether E supports C is a meaning decision, and AI
decides meaning.

**Decision:** B. Binding continues to attach evidence to the address; `SUPPORTS_CLAIM`
attaches evidence to a specific claim. Both are needed, and they are cheap.

## 12. Evidence-to-claim relationship — the one new primitive

```text
JudgmentKind.SUPPORTS_CLAIM                 (new; low-risk; AI-proposed)
  proposal: claim_id, evidence_ids (>=1)

ClaimSupportRecord                          (new; immutable; appended by the reducer)
  claim_id, evidence_ids, judgment_id, recorded_by_event_id

derived in the view:
  effective_evidence(claim) = claim.evidence_ids ∪ evidence of ACTIVE support records
```

Invariants: `SemanticClaim.evidence_ids` is **never rewritten**; a support record is
superseded like any judgment; the claim must be live at admission time (structural rule,
mirrored in the reducer per D-ADM-5). The reducer mints a fresh issue version at the claim's
address so the head reflects the new support. This is the smallest additive primitive that
keeps claim identity and claim support as two distinct facts.

## 13. Changed claims

A claim never changes. A *changed interpretation* is represented as:

```text
old claim C1 (immutable, cites old evidence; asserted by judgment J1 — known to the model)
new claim C2 (immutable, cites new evidence)               ASSERT_CLAIM, low-risk → APPLY
SUPERSEDE(J1)  reason: <why the old interpretation is no longer current>
                                                           material → pending
→ human AGREES (§17)  → J1 inactive; C1 drops out of the current view, stays readable in
                        state; locus CLAIMED with C2 live; blast radius from J1 recomputed
→ human DECLINES      → J1 stays active; C1 AND C2 both live; the SUPERSEDE proposal stays
                        pending; the scope's readiness is qualified by unresolved material
                        governance (§24). Foundry does NOT infer a conflict deterministically.
```

Both drafts are legal in one response because each references only ids the model was
shown: `ASSERT_CLAIM` names a known `address_id`; `SUPERSEDE` names the known
`created_by_judgment_id` of C1. C2's durable `claim_id` is minted by runtime after the
response and is needed by neither operation. A `CONFLICTS_WITH(C1, C2)` cannot appear in
that response — C2 does not exist yet — and is **not** part of the correction path.

Whether a change is a *contest* (keep both live, no supersession) or a *correction*
(supersede the old one) is a semantic-and-authority question. The reasoner proposes;
only authority settles it (§17). "The commit came later" is chronology, never authority
(task §17). The three preregistered 9P tracks are corrections; 9P makes **no claim about
live `CONFLICTS_WITH` handling**, which needs two pre-existing claims and is a later
unresolved-contest experiment.

## 14. Supersession — operation sequence for the real tracks

**Track A (§4.5 referential identity).** T1 evidence: spec @ `097584a` states that after an
admitted binding, address equality "becomes deterministic and authoritative". T2 evidence:
spec @ `2539ff8` states it is a deterministic *referential* fact under the current
interpretation, not new inference and not eternal truth, and may be superseded.

```text
T1  CREATE  ADDR-A (Admitted address bindings | referential status)
    ASSERT  C-A1 "after admission, equality is deterministic and authoritative"     APPLY
T2  BIND    spec@2539ff8 §4.5 → ADDR-A                                              APPLY
    ASSERT  C-A2 "referential fact under current interpretation; not eternal truth" APPLY
    SUPERSEDE(J(C-A1))  reason: architecture correction 9N §4.5                     pending
    human AGREES: submits the identical SUPERSEDE → APPLY; AI proposal SATISFIED_BY it
→   view: ADDR-A CLAIMED with C-A2; C-A1 readable in state; J(C-A1) inactive
    (if the human DECLINES: C-A1 and C-A2 both live; proposal pending; scope qualified)
```

One human authorization for Track A. No `CONFLICTS_WITH` is proposed or expected.

**Track B (validation framing).** Same shape: C-B1 "single-pass cleanliness is the primary
claim" (spec @ `097584a` §23) → C-B2 "single-pass cleanliness is a subsystem gate;
longitudinal persistence is primary" (spec @ `2539ff8` §23.1).

**Track C (provenance identity — a real code defect).** T3 evidence: `semantic_reducer.py`
@ `90246a8` in which `_claim_provenance` copies `evidence_ids` into
`Provenance.source_event_ids`. T4 evidence: the same file @ `779a66a` plus the spec
amendment. Expected: an observation locus (SemanticClaim provenance | identity of
`source_event_ids`) gets an INFERRED implementation claim at T3 ("source_event_ids carries the
claim's evidence ids") and a corrected claim at T4 ("source_event_ids holds EventEnvelope IDs
only; evidence_ids is the evidence edge"), then `SUPERSEDE` of the T3 claim's judgment as
above — one human authorization. This track
tests that the substrate can hold *an observed defect* as a first-class historical belief
and then correct it, which is what brownfield reconciliation will look like.

## 15. Evidence versioning — decision

Two versions of one path are two immutable `EvidenceItem`s. Nothing is overwritten. The
current fields almost suffice; two are added:

```text
EvidenceItem
  artifact_ref            NEW  stable identity of the thing versioned, e.g. "repo:docs/…/design.md"
  supersedes_evidence_id  NEW  the previous immutable version of the same artifact, if any
  source_ref              (as today) "git://<commit>/<path>" — the exact version locator
  content_sha256          (as today)
```

`artifact_ref` is declared by the harness (it knows the path), never parsed out of
`source_ref`. `supersedes_evidence_id` is set deterministically by the harness from the
timeline (the previous version it ingested for that artifact) — this is **evidence
lineage**, knowable from Git, and carries no semantic authority. The view derives
`current_evidence_versions` (latest per `artifact_ref`) and `superseded_evidence_ids`.

**Delta definition (task §20):** at T>1 the persistent arm receives exactly the evidence
items whose `(artifact_ref, content_sha256)` did not exist at T-1: new artifacts and new
versions of known artifacts. Unchanged artifacts are not re-sent. Whole-file versions are
used, not Git diffs — a diff is not self-contained evidence and would push the model to
reason about text edits rather than meaning. Diff-based deltas are DEFERRED (§37).

## 16. Semantic versioning versus evidence versioning — kept apart

```text
evidence version B supersedes evidence version A     deterministic (Git lineage) — recorded as data
semantic claim C2 supersedes semantic claim C1       semantic + authority judgment — governed
```

A claim that cites a superseded evidence version is **not** automatically superseded, not
even flagged stale. The reasoner is *told* (§19) that a cited version has a newer version so
it can re-examine; it must still propose, and authority must still admit. This is the
explicit refusal of "newer artifact wins" (failure mode 8).

## 17. Authority for material change — decision

| Option | Verdict |
|---|---|
| A. second independent frontier model | Not for 9P. It adds a second provider and a cross-model variable to an experiment whose purpose is persistence. It is exactly the 9Q question. |
| **B. human authority (pre-authorized)** | **Selected.** Matches the current authority architecture; keeps semantic and authority layers separate; introduces no new provider. |
| C. narrow deterministic temporal policy | Rejected for semantic supersession. Evidence lineage is recorded deterministically (§15) but never converts into semantic authority. |

**Protocol.** Before the run, one `AuthorityRecord` for a named architect actor, project-wide
scope, is recorded at T0 (it is itself an event). After each Call 2, if a `SUPERSEDE`
proposal is pending, the harness pauses and presents it verbatim. The architect may only
**AGREE** — submit a judgment with the identical `proposal_signature` (same target, same
kind), which routes `APPLY` under existing rule 3 and derives the AI proposal
`SATISFIED_BY` — or **DECLINE**. Nothing about admission is weakened.

The human authority actor may **not**: create a missing claim; identify a missing semantic
address; change a binding; rewrite the proposed claim; edit the supersession target or
reason; author a supersession the AI failed to propose; supply missing semantic reasoning;
or repair model output during the run. Any of those would make the human a contestant
reasoner. Human authorization is a **governance action**, not a reasoning pass, and human
approval is **not evidence that the AI judgment was semantically correct** — correctness is
adjudicated after the run against the sealed expectation manifest (§29), independently of
whether approval was given.

**Declined supersession.** Nothing changes: the old judgment stays active, the old and the
new claim are both live, the proposal stays pending. Foundry must **not** deterministically
infer `CONFLICTS_WITH` from a declined supersession — that would be code originating a
meaning. The unresolved material proposal is unresolved governance and qualifies the
affected scope's readiness (§24). Declining is a legitimate, recorded outcome.

Pending `CONFLICTS_WITH` proposals (possible only between two already-known claims) are
recorded but **never human-authorized in 9P**; the authorization budget is reserved for the
three preregistered corrections.

**Derived status (new, view-level, deterministic):** a pending judgment whose
`proposal_signature` equals that of an applied, active judgment is `SATISFIED_BY` that
judgment. It stops counting as unresolved governance. This is a derivation over structural
signatures, not a meaning decision.

**Preregistered ceiling:** at most **one** human authorization per tracked correction —
Track A ≤1 and Track B ≤1 at T2, Track C ≤1 at T4 — hence ≤3 in the run. With the correction
path being `ASSERT_CLAIM` (auto-applied) + one `SUPERSEDE` (the only material proposal),
the ceiling is exact rather than aspirational. Every authorization is logged with the
pending proposal it satisfied; every decline is logged with the proposal it left pending.

## 18. Candidate retrieval — decision

| Option | Assessment |
|---|---|
| 1. all active in-scope addresses | highest recall; simple; no retrieval failure can confound the first lifecycle experiment |
| 2. lexical/scope top-K | smaller context but paraphrase recall can fail — the experiment would then be measuring retrieval, not persistence |
| 3. hybrid with threshold | the right *future* shape |

**Decision:** Option 3 as the designed mechanism with the threshold set so that **9P runs
entirely in Option-1 mode**. The compiler sends *descriptors only* (address_id, subject,
facet, scope) for every active in-scope address while their count is ≤ 200; at 9O scale
(38 addresses ≈ 40 tokens each) that is ~1.5k tokens, far below the delta evidence itself.
Above the threshold a deterministic lexical top-K ranker would select candidates; that
branch is designed here as a seam and marked **DEFERRED** with the resolving evidence being
a measured retrieval-recall study on a larger corpus. No embeddings.

**Non-authoritative by construction (task §6, failure mode 16):** the compiler decides what
the model *sees*; the model decides what things *mean*; admission decides what *changes*.
The compiler never emits a judgment, never filters the model's output, and its selection is
recorded in the manifest so a miss is auditable.

## 19. Bounded semantic context (the tiny assembly function)

Not the Context Compiler. One function with fixed inputs:

```text
assemble_call1(delta_evidence, active_addresses_in_scope)             → ReasoningRequest
assemble_call2(delta_evidence, neighborhood_addresses, live_claims_at_neighborhood,
               evidence_version_chronology_for_cited_evidence)         → ReasoningRequest
```

`ReasoningRequest` gains no new fields except that `known_claims` rendering must include each
claim's `created_by_judgment_id` (so `SUPERSEDE` can name a target) and each evidence item's
`artifact_ref` / `supersedes_evidence_id` (so the model sees version chronology as data).
Nothing else about the port changes.

**What the model never sees:** the ledger, admissions, the full address set once the
threshold branch exists, previous arms' outputs, expectation manifests, or any tracked-locus
name. **What substitutes for raw history:** address descriptors and live claims. At T2–T4
the persistent arm re-reads **zero** unchanged evidence.

## 20. Assimilation call architectures

| | A. create-then-reconcile | B. bind-first | C. single-call delta plan |
|---|---|---|---|
| calls per delta | 3 (create, assert, reconcile) | **2** | 1 |
| durable duplicates | created first, repaired later | avoided at source | avoided at source |
| context per delta | evidence + all addresses + all claims | delta + descriptors; then delta + neighborhood claims | delta + descriptors + all relevant claims |
| failure isolation | good per stage | good per stage | poor — one schema, one failure surface |
| responsibility per call | narrow | narrow | broad (bind/create/assert/support/conflict/supersede at once) |
| 9O evidence | this *is* 9O; its reconcile step was the weakest | untested | untested; resembles v1's single rich pass that overproduced |
| model sees relationships holistically | no | at call 2 for the neighborhood | yes |

## 21. Architecture alternatives — decision

**A** is rejected: it repeats the shape whose cost profile 9O already measured and it
creates the duplicates the thesis says persistence should avoid.

**C** is attractive on cost but is rejected for 9P on two grounds. First, the claim-level
context depends on which addresses the delta lands on; a single call must therefore be sent
*all* claims or guess the neighborhood before binding — which either re-creates the 9O
reconciliation cost or moves neighborhood selection into the model. Second, one schema
carrying six operation kinds recreates the single-rich-pass responsibility overload that 9L
identified as v1's dominant defect; a single structural refusal would void an entire
cycle's work.

**B is selected.** Bind-first, two bounded calls per delta, neighborhood derived from
*admitted* bindings. It is the smallest shape in which the neighborhood is known before
claims are reasoned about, and each call has one job.

## 22. Recommended architecture

§6 is the recommended flow. Model-facing draft additions (all untrusted, runtime-wrapped
exactly as in 9O):

```text
BindToAddressDraft   address_id, subject, facet, evidence_ids, rationale
SupportsClaimDraft   claim_id, evidence_ids, rationale
SupersedeDraft       target_judgment_id, reason           (target must be a judgment id of a
                                                          claim shown in known_claims)
```

Reference validation extends naturally: `address_id` ∈ known addresses; `claim_id` ∈ known
claims; `target_judgment_id` ∈ {created_by_judgment_id of known claims}; kinds ∈ allowed.
Authority remains runtime-assigned `INFERRED`. Scope remains derived from cited evidence.

**Correction pattern (the only one 9P uses):** `AssertClaimDraft(address_id=<known>)` +
`SupersedeDraft(target_judgment_id=<known claim's judgment>)` in one Call 2 response. Neither
draft needs the new claim's id, so no model-generated durable or local claim id is
introduced and no third frontier call is added. `ConflictsWithDraft` may name only two
`claim_id`s both present in `known_claims`.

## 23. Blast radius

Preregistered **before T2**, off Track A's T1 claim judgment `J(C-A1)`:

```text
J(C-A1)  ──DERIVED_FROM──  D-A1 = "artifact:docs/superpowers/plans/2026-09-11-intent-intelligence-v2-core.md#6.1"
D-A1     ──DERIVED_FROM──  D-A2 = "artifact:src/foundry/domain/admission.py"
D-A2     ──DERIVED_FROM──  D-A3 = "artifact:tests/unit/test_admission.py"
```

These are real Foundry artifacts whose content genuinely depended on the §4.5 reading
(admission's referential-identity handling was written against it). They are recorded as
generic derivation ids; no Decision Engine is implied. Expectation: after the Track A
supersession is authorized at T2, `view.stale_ids ⊇ {D-A1, D-A2, D-A3}` and the T1
issue version of ADDR-A; before it, `stale_ids = ()`. An unrelated preregistered chain off
a Track-neutral locus (e.g. *Foundry | purpose*) must remain clean (failure mode 11).

## 24. Scoped closure

Two scopes are preregistered: `("intent-engine",)` for all tracked loci and
`("constitution",)` for constitution-only loci (Track-neutral). After the Track A
supersession, `handoff("intent-engine").readiness.ready` must become `False` with the three
descendants in `stale_object_ids`; `handoff("constitution")` must be unaffected. The
project is never globally blocked. (Readiness also requires the existing v0 closure
conditions; the harness records both `closure.closed` and the semantic blockers
separately so the semantic effect is visible even if v0 closure is not met.)

**Pending material governance qualifies readiness (new, minimal).** `SemanticReadiness`
gains one field, `pending_material_judgment_ids`: judgments whose latest admission is
`REQUIRE_SECOND_LENS` or `REQUIRE_HUMAN`, that are not `SATISFIED_BY` an active applied
judgment, and that bear on an in-scope address (the existing "bears on" attribution used
for stale objects). `ready` additionally requires this tuple to be empty. So a declined
Track A supersession leaves `intent-engine` not ready — with the reason visible as the
pending proposal id, not as an inferred conflict — while `constitution` is unaffected. No
workflow system, no new event, no new state: a derivation over records that already exist.

## 25. Real Foundry history timeline

Evidence is read from commits, never from the working tree, with blob and content hashes
recorded as in 9O.

| T | Commit | Delta evidence (new immutable versions) | Exercises |
|---|---|---|---|
| T1 | `097584a` | `FOUNDRY_CONSTITUTION.md`; spec `2026-09-10-…-v2-design.md` | state establishment; Tracks A/B *old* beliefs |
| T2 | `2539ff8` | spec (new version) | BIND to A and B; correction (ASSERT + SUPERSEDE); blast radius; scope |
| T3 | `90246a8` | `src/foundry/application/semantic_reducer.py`; `src/foundry/domain/semantic_identity.py` | BIND/CREATE over code; Track C defect as an INFERRED observation |
| T4 | `779a66a` | `semantic_reducer.py` (new version); spec (new version) | Track C correction; supersession; blast radius |

Every delta is a real, checked-in change. T1's evidence set is smaller than 9O's (two files
rather than five) so that T2's delta is a genuinely new spec version rather than a repeat.
The constitution is never re-sent after T1.

## 26. Persistent arm (Arm F)

One governor, one ledger, one project id for the whole run. Per T: ingest delta (with
`supersedes_evidence_id` lineage) → Call 1 → admission → Call 2 → admission → authority step
(agree/decline, ≤1 per tracked correction) if a `SUPERSEDE` proposal is pending → record
stage artifacts. State survives across T. At T1 Call 1
has no known addresses, so only `CREATE_ADDRESS` can occur; that is the ordinary path with an
empty state, not a special case.

## 27. Reconstruction arm (Arm R)

A **fresh** governor, ledger and project id at every T. Input: **every evidence version
available up to T** — old and new — so it can in principle reason about change. Calls: the
same two-call shape with empty known state (Call 1 can only CREATE; Call 2 sees the
addresses Call 1 created and no known claims, so it can only ASSERT). No supersession, no
support and no conflict is possible in R because R has no prior claim or judgment to refer
to; this is not a handicap, it is the thesis. Same model,
same effort, same settings, same system instruction, same draft schema.

## 28. Fairness

- Same model (`grok-4.6`, `high`), same adapter, same prompt, same allowed kinds per call,
  same call count per T (2), same evidence *versions* at each T.
- R receives **more** raw evidence than F at every T>1 (all versions vs the delta). If R
  loses on context it is because it re-reads; if F loses on correctness it is because
  persistence misled it.
- No expectation, tracked-locus name, address id or expected wording appears in any prompt
  (failure mode 15) — the manifest is sealed by content hash before the run.
- No arm gets a reroll; a failed call is a recorded failure for that arm at that T.
- Human authorizations occur only in F (R structurally has nothing to supersede), are
  capped at one per tracked correction and logged. The human may only AGREE or DECLINE the
  exact AI-proposed supersession and may not create a claim, identify an address, change a
  binding, rewrite a claim, edit a target, author an unproposed supersession, supply
  reasoning, or repair output (§17). Human approval is a governance action and is never
  counted as evidence of semantic correctness; correctness is adjudicated post-run against
  the sealed manifest.
- The 9K lesson stands: same hosted model ≠ deterministic pairing. All claims are
  directional internal evidence.

## 29. Expected lifecycle manifest (preregistered; no wording, no ids)

Tracked loci: **A** (referential status of admitted bindings), **B** (validation framing),
**C** (identity of `Provenance.source_event_ids`). For each, adjudicated by the architect
against the ledger after the run:

| # | Expectation | T |
|---|---|---|
| E1 | A and B exist as addresses after T1; C does not yet exist | T1 |
| E2 | at T2 the A- and B-related observations are **bound** to the T1 addresses, not created anew | T2 |
| E3 | at T2 a new claim at A (and at B) expresses the corrected interpretation | T2 |
| E4 | the T1 claims at A and B remain present in state after T2 | T2 |
| E5 | the current view at A (and B) changes **only after** an authorized supersession | T2 |
| E6 | after supersession `stale_ids ⊇ {D-A1, D-A2, D-A3}`; the unrelated chain is clean | T2 |
| E7 | `intent-engine` readiness reports the stale descendants; `constitution` is unaffected | T2 |
| E8 | C exists after T3 with an INFERRED claim describing the observed (defective) behaviour | T3 |
| E9 | at T4 the corrected observation binds to C; a new claim and a `SUPERSEDE` of the T3 claim's judgment are proposed, not silently applied | T4 |
| E12 | if any supersession is declined, the affected scope's readiness reports the pending proposal and no `CONFLICTS_WITH` appears in the ledger without a model proposal | any |
| E10 | no `EQUIVALENT`/`DISTINCT` was requested at any T; duplicate-address count for tracked loci is 0 | all |
| E11 | replay of the F ledger reproduces state and view | end |

## 30. Metrics (no weighted master score)

Per arm, per T, and cumulative:

| Dimension | Measure |
|---|---|
| semantic correctness after change | E1–E9 verdicts (architect) |
| persistent identity reuse | tracked loci reached by BIND at T>1 / tracked loci present |
| duplicate identity creation | new addresses at T>1 judged by the architect to denote an existing locus |
| historical preservation | for each superseded locus: old claim readable? superseding judgment recorded? evidence that changed it linked? (from ledger, deterministic) |
| stale-state detection | E6 (deterministic) |
| scope isolation | E7 (deterministic) |
| context consumed | input tokens per T and cumulative (F vs R) |
| cost | USD per T and cumulative |
| repeated rediscovery | R: addresses re-created at T that denote loci already created at T-1 (architect-adjudicated on tracked loci; counted overall) |
| stability | for tracked loci, does F's current claim set change between T's with no new relevant evidence? |
| unresolved governance | pending second-lens / human / reject counts, and how many were SATISFIED |

Identity continuity is **never** scored by string equality of descriptors (task §29).

## 31. Cost and accounting

Preregistered ceilings: **16 frontier calls** (F: 4 T × 2; R: 4 T × 2), **0 judge calls**,
**≤3 human authorizations (≤1 per tracked correction)**, **$8.00 total** (9O averaged $0.13 per call at ~33k input; R's
inputs grow to ~3× that by T4). Per call the receipt (tokens, cost, wall) is recorded as in
9O. What is sent repeatedly and what is not is made explicit in the artifacts: F's input at
T>1 is delta + descriptors + neighborhood claims; R's is the full corpus. The measured
question is whether F's cumulative input is materially below R's while E1–E9 hold.

## 32. Failure modes — detect · preserve · fail safely

| # | Failure | Detect | Preserve | Fail safely |
|---|---|---|---|---|
| 1 | correct address not retrieved | impossible in Option-1 mode; if threshold branch active, retrieval list recorded | manifest lists what was shown | E2 failure is attributed to the model, not retrieval, only when all addresses were shown |
| 2 | bound to wrong address | architect adjudication of tracked loci; view shows evidence at wrong locus | judgment record; binding reversible by SUPERSEDE | not repaired in-run; recorded |
| 3 | created instead of reused | duplicate-identity metric | both addresses persist | recorded; maintenance EQUIVALENT is out of scope |
| 4 | two meanings bound to one address | architect adjudication | records | recorded |
| 5 | duplicate claim instead of support | duplicate-claim count at neighborhood | claims append-only | recorded |
| 6 | contradiction unnoticed | E3/E9 | evidence present in ledger | recorded |
| 7 | supersession without authority | impossible: material → pending; test `no_material_kind_auto_applied` | proposal recorded | admission refuses |
| 8 | newer version mistaken for authority | no rule reads chronology for admission; human must authorize | lineage recorded as data | structural check: no SUPERSEDE applied without a human or independent lens |
| 9 | material supersession unresolved (declined or unanswered) | pending count; `pending_material_judgment_ids` in readiness | pending judgment recorded; both claims live | legitimate outcome; affected scope not ready; no conflict inferred |
| 9b | a draft references a claim created in the same response | impossible by construction: reference validation admits only ids present in the request | draft recorded with the refusal | whole batch refused as `SemanticOutputError`; recorded, not retried |
| 9c | human acts as reasoner (edits, authors, repairs) | protocol permits only AGREE/DECLINE of the verbatim proposal; harness offers no other input path | log of what was presented and answered | run integrity failure, reported |
| 10 | descendant missing from blast radius | E6 deterministic | edges recorded | recorded mismatch |
| 11 | over-invalidation | unrelated chain check | — | recorded |
| 12 | R under-informed | R evidence set = all versions ≤ T, hashed in manifest | manifest | pre-run check |
| 13 | F rereads full history | F input per T must exclude unchanged artifacts; asserted by the harness | receipts | run aborts before the call |
| 14 | silent rerun | one receipt per (arm, T, call); budget counter; `grpc.enable_retries=0` | receipts | any extra call is an integrity failure, reported |
| 15 | ids/wording leak into prompts | prompt bytes hashed; manifest sealed pre-run; grep of tracked names against prompts | — | run aborts |
| 16 | retrieval as hidden authority | compiler emits only `ReasoningRequest`; never a judgment | selection recorded | design invariant + test |

Live discipline as in 9O: first external call makes the run immutable; any failure → preserve,
write status, commit, stop.

## 33. Cross-model T6 — deferred

**Decision: 9P = T1–T5; 9Q = T6.** Reasons: (a) T6 needs a second provider adapter, which is
new integration surface and a new variable; (b) T6 is only meaningful if T1–T5 hold — a
state that does not assimilate correctly is not worth inheriting; (c) the substrate already
makes T6 possible without change (addresses are Foundry ids, judgments carry reasoner
provenance), so nothing in 9P forecloses it. 9Q's design question is whether a different
brain, given persistent state plus a delta, reuses loci as well as the brain that built them.

## 34. Falsifiable hypothesis

**H-9P (primary).** For the real sequence of Foundry evidence changes T1–T4, persistent
semantic assimilation (Arm F) will correctly reuse and evolve the three tracked loci using
only evidence deltas plus bounded current state — binding new evidence to existing addresses,
preserving prior interpretations, changing current interpretation only under authorized
supersession, and producing the preregistered blast radius and scope response — without
re-reading unchanged evidence at any step.

**Decision rule (preregistered):**

```text
PASS  iff  E1–E9 all hold for all three tracked loci (architect-adjudicated)
      AND  E10, E11 hold (deterministic)
      AND  F's cumulative input tokens over T2–T4 < R's cumulative input tokens over T2–T4
      AND  F introduces no more architect-adjudicated material semantic errors on tracked
           loci than R does at the corresponding T
FAIL  otherwise, with the failing expectation named
```

Correctness is the gate; the token comparison is a necessary condition, never sufficient.
R is a fair comparison, not a straw man: it is given strictly more evidence. Human
authorization counts and outcomes are reported but never enter the rule as evidence of
correctness; a declined supersession is scored on what the AI proposed, not on what the
human did.

**Secondary (descriptive, not gated):** duplicate-identity counts, rediscovery counts,
stability, unresolved-governance counts, per-T cost.

## 35. Smallest implementation slice

1. Expose `BIND_TO_ADDRESS`, `SUPERSEDE` and the new `SUPPORTS_CLAIM` through the xAI draft
   adapter with reference validation extended (§22). Render `created_by_judgment_id` on
   known claims and version lineage on evidence.
2. Add `JudgmentKind.SUPPORTS_CLAIM`, `SupportsClaimProposal`, `ClaimSupportRecord`, reducer
   application (low-risk), admission structural rule (claim must be live), view derivation
   `effective_evidence`. Claims stay immutable.
3. Add `EvidenceItem.artifact_ref` and `supersedes_evidence_id`; view derives current
   versions. No other evidence change.
4. Add view derivation `SATISFIED_BY` for pending judgments whose signature has been applied
   by an active judgment, and `SemanticReadiness.pending_material_judgment_ids` so unresolved
   material governance in scope qualifies readiness (§24).
5. Tiny assimilation orchestrator: delta ingest → Call 1 → admission → neighborhood → Call 2
   → admission → authority pause. Threshold branch present as a seam with the top-K ranker
   **not** implemented (DEFERRED).
6. Tiny context assembly (§19) — explicitly subordinate to the future Context Compiler.
7. Timeline loader for the four commits with blob/content hashes; delta computation by
   `(artifact_ref, content_sha256)`.
8. Arm F and Arm R runners sharing the adapter; per-call receipts; preregistered budgets.
9. Expectation manifest sealed by hash before the run; human-authorization protocol with
   verbatim proposal presentation and agree/decline only.
10. Immutable artifacts (manifest, per-arm results, both ledgers, expectation verdict
    template, report) and replay verification of the F ledger.
11. No Decision Engine, no embeddings, no second provider.

The task's prior (§37) is confirmed with one addition — `SUPPORTS_CLAIM` (item 2) — because
binding alone cannot attach evidence at claim granularity (§11), and one narrowing — no
`EQUIVALENT`/`DISTINCT` in the loop (§8).

## 36. Non-goals

Decision Engine · Architecture Engine · Artifact World · universal ontology · graph database
· embeddings · general Context Compiler · agent router · research engine · UI · production
CLI · multi-agent debate · model marketplace · deployment reconciliation · second provider ·
cross-model continuity (9Q) · inline duplicate repair (`EQUIVALENT` sweeps) · diff-based
evidence deltas · any weakening of material-kind admission.

## 37. Decision summary

| # | Decision |
|---|---|
| 1 | `BIND_TO_ADDRESS` = AI judgment that a new transient observation (a `SemanticCandidate` with subject, facet, evidence) refers to an existing durable address; low-risk; reversible by `SUPERSEDE` |
| 2 | BIND: observation → existing address (prevents duplication). EQUIVALENT: address ↔ address (repairs duplication). EQUIVALENT/DISTINCT are excluded from the per-delta loop |
| 3 | candidate is ephemeral as an object, durable as the content of its judgment record |
| 4 | new evidence attaches to an address via a BIND candidate's evidence, and to a specific claim via `SUPPORTS_CLAIM` |
| 5 | yes — `SUPPORTS_CLAIM` judgment + immutable `ClaimSupportRecord`; `SemanticClaim.evidence_ids` never rewritten; view derives `effective_evidence` |
| 6 | duplicate claims avoided by instructing SUPPORT over ASSERT for restatements and by measuring duplicates; empty Call 2 output is legitimate |
| 7 | a changed interpretation = `ASSERT_CLAIM` (new) + `SUPERSEDE` (old claim's judgment) in one response; the old claim stays readable. No same-response `CONFLICTS_WITH` — the new claim has no durable id yet. `CONFLICTS_WITH` stays in the domain for pairs of already-known claims and is not a 9P expectation |
| 8 | supersession proposed by the model via `SupersedeDraft(target_judgment_id, reason)` where the target is a judgment id shown in `known_claims` |
| 9 | authorized by a pre-authorized human under an `AuthorityRecord`: AGREE or DECLINE the verbatim proposal only, ≤1 per tracked correction (≤3 per run); a decline leaves both claims live and the proposal pending; approval is never evidence of correctness |
| 10 | evidence versions are immutable items linked by `artifact_ref` + `supersedes_evidence_id` (deterministic Git lineage); semantic supersession is a separate governed judgment; no "newer wins" |
| 11 | retrieval: all active in-scope address descriptors while ≤ 200 (9P runs here); lexical top-K seam DEFERRED; no embeddings |
| 12 | two frontier calls per delta: assimilation (BIND/CREATE) then claim assimilation (SUPPORT/ASSERT/CONFLICT/SUPERSEDE); no reconciliation sweep |
| 13 | model sees: delta evidence, address descriptors (Call 1); delta evidence, neighborhood live claims with judgment ids, evidence lineage (Call 2). Never the ledger, admissions or expectations |
| 14 | the compiler selects what is shown, never what it means; selection recorded; it emits no judgment |
| 15 | blast radius triggers on any applied `SUPERSEDE`; preregistered chain D-A1 → D-A2 → D-A3 on real artifacts |
| 16 | after supersession the affected scope reports stale descendants and is not ready; after a declined supersession it reports the pending material proposal and is not ready; unrelated scope unaffected; never global; no conflict is inferred deterministically |
| 17 | Arm F: one ledger across T1–T4, deltas only, bounded state |
| 18 | Arm R: fresh ledger per T, all evidence versions ≤ T, same two-call shape |
| 19 | same model/settings/prompt/kinds/call count; R gets ≥ evidence; no rerolls; prompts sealed against leakage |
| 20 | expectation manifest E1–E11 over loci A, B, C, sealed by hash before the run |
| 21 | metrics per §30; no weighted score; no lexical identity scoring |
| 22 | 16 frontier calls, 0 judge calls, ≤3 human authorizations (≤1 per tracked correction), $8.00 |
| 23 | no reroll; a failed call is a recorded failure for that arm/T |
| 24 | failure modes per §32; first external call makes the run immutable |
| 25 | T6 cross-model deferred to 9Q |
| 26 | smallest slice per §35 |
| 27 | non-goals per §36 |

**DEFERRED (with resolving evidence):** lexical top-K retrieval (a retrieval-recall study on
a corpus above the threshold); diff-based deltas (a comparison against whole-version deltas
on the same timeline); maintenance `EQUIVALENT` sweeps over suspected-duplicate
neighborhoods (the duplicate-identity metric from 9P); cross-model inheritance (9Q).
