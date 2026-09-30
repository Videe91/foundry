# IE2 T1 Concern-Grain Audit: Why A+B+C and F+G Merged

**Status:** audit only, 2026-09-30. No production, prompt, policy, scorer or oracle change. No model call.

**Outcome:** STOP.
- The sealed 12-concern T1 oracle conflicts with the approved G2 law (`2026-09-28-ie2-governed-concern-grain.md`).
- The model's 9-address T1 is the G2-consistent grouping.
- Whether G2 should change is a founder decision (§9).

**Sources, read only:**
- frozen run `docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1/run.json` (grok-4.6, `intent-v2-locus-v5`);
- 9P3 corpus `long_horizon_bounded/timeline.py`;
- 9P3 arms F and A (`2026-09-13-long-horizon-bounded-memory-v1/{F,A}/drafts.json`);
- locus validation v5 (`2026-09-29-locus-validation-v5/run.json`);
- the G2 fixtures `experiments/locus_formation/grain.py`.

## 1. T1, reconstructed

**Call 1** made one call over 12 evidence items: 9,855 rendered characters, 9 CREATE drafts and 0 BIND drafts. **Call 2** returned 32 propositions and 32 drafts.

| Locus | Section (normative rules, verbatim substance) | Props | Address (subject; canonical facet `Rules governing <subject>`) | Grouped with |
|---|---|---|---|---|
| A | "at most three times in total"; "the first execution counts as one of the three"; "no further execution" after the third | P01–P05 | `ADDR-3a12…` **Job execution attempts** | B, C |
| B | "Before every retry attempt the worker must wait exactly five seconds, measured from the end of the failed attempt"; "must not be shortened or lengthened based on the attempt number" | P06–P07 | same | A, C |
| C | "Each execution attempt must time out after thirty seconds of execution"; "An attempt that reaches the timeout must be recorded as a failed attempt" | P08–P09 | same | A, B |
| D | further delivery with the same job id "must be ignored" while active; ignoring "must not change the state of the active job" | P10–P11 | `ADDR-d0d9…` Duplicate delivery of an active job | — |
| E | "retain each idempotency key for twenty-four hours after it is first seen"; after that "treated as new" | P12–P14 | `ADDR-aebe…` Job idempotency keys | — |
| F | "A worker lease must last sixty seconds from the moment the job is delivered"; on expiry "without renewal or release, the job must become available to other workers" | P15–P17 | `ADDR-e24e…` **Worker lease on a job** | G |
| G | "A worker may renew its lease every thirty seconds while work on the job is progressing"; "A renewal must extend the lease by the full lease duration from the moment of renewal" | P18–P19 | same | F |
| H | no future attempt after cancellation; a running attempt is not interrupted | P20–P22 | `ADDR-d2e1…` Job cancellation | — |
| I | automatic move to the dead-letter queue after the final failure; no re-execution unless resubmitted | P23–P24 | `ADDR-b828…` Dead-letter handling of exhausted jobs | — |
| J | three dead-letter events per tenant within one hour raise an escalation; the window is measured from the first | P25–P26 | `ADDR-6929…` Operator escalation for tenant dead-letter rate | — |
| K | FIFO only within a partition; no cross-partition guarantee | P27–P29 | `ADDR-c0b5…` Execution order within a queue partition | — |
| L | audit events retained thirty days, deletable after | P30–P32 | `ADDR-b1db…` Job audit events | — |

**The model's Call-1 rationales, verbatim:**
- **A/B/C:** "EV-O-A01, EV-O-B01, and EV-O-C01 govern one act: delivering an admitted job to a worker. Attempt count, retry wait, and per-attempt timeout are limits, timing, and deadline dimensions of that act, not separate loci."
- **F/G:** "EV-O-F01 and EV-O-G01 govern the exclusive lease a worker holds on a delivered job. Duration, expiry, and renewal are dimensions of that lease, not a second concern."

**Every proposition landed correctly within its address.** The claims are faithful; only the grain is contested.

## 2. What A, B, C, F and G govern

| Locus | Governs | Kind |
|---|---|---|
| A | the budget of executions of one job | a *limit* on the execution act; its trigger is an execution ending without success |
| B | when the next execution may start after a failure | a *when* of the same act. A retry attempt is an execution attempt ("before every retry attempt") |
| C | how long one execution may run, and that reaching the limit ends it as failed | a *deadline / how long* plus an *effect* of the same act |
| F | the lease entity: its duration and what its expiry does | the *how long* and *effect* of one entity |
| G | the renewal act on that lease: when it may occur (every 30 s), a precondition (while progressing), its effect (extends by the full duration) | the *when*, *precondition* and *effect* of an act on the same entity |

**Can each change independently?** Yes, and the timeline does change them independently (T3 A, T5/T8 B, T7 F, T12 G). But so can every dimension G2 keeps together: the 14-day request deadline of late-delivery compensation can change without changing the refund amount. Independent changeability therefore does not discriminate here.

**Own trigger, timing, quantity and transition?** Each has one. So do the dimensions of C09 cancellation: "repeated cancellation" has its own trigger and outcome.

## 3. G2 applied mechanically

**The contract G2 gives the model**, identical in v5 and v6 (v6 only appends the CORRECTION SETS block):
- *Dimensions are claims:* "who may perform it; when it may occur; eligibility and preconditions; effects; limits and quantities; deadlines; destinations; what repeating it does; exceptions."
- "A different who, when, how, how long or whether about the same concern is never a reason to create an address."
- *Separate address:* "a different, independently governed act, entity or record, entitlement, decision, state transition or operational concern: one with its own rules and lifecycle, whose rules can change without changing the first concern's."

**A/B/C.** Take the concern to be the execution attempt, which is what each section's own text is about:
- A is its *limit*;
- B is *when it may occur*;
- C is its *deadline / how long* plus an *effect*.

The dimension clause decides this directly. The separate-address clause cannot override it: its independent-change test is satisfied equally by C6's deadline, which G2 rules is a claim ("A deadline for doing something … belongs to the concern it constrains"). **G2 requires one concern.**

**F/G.** Take the concern to be the worker lease:
- duration is *how long*;
- expiry is an *effect*;
- renewal is *when* (every 30 s), a *precondition* (while progressing) and an *effect* (extension).

This is the C09 shape exactly: one governed thing, with facets that 9P3 made separate addresses. **G2 requires one concern.** The contrary reading treats "renewal" as an act distinct from the lease entity. G2's text does not rank act against entity, so that reading is available. It is not the mechanical one, and it splits concerns that G2's C6 and C09 rulings keep whole (§9).

**The oracle.**
- 9P3 (2026-09-13) defines the 12 loci as spec **sections**, with dimension-named labels: "maximum execution attempts", "retry delay", "per-attempt timeout", "worker lease duration", "lease-renewal rule".
- 9P3's persistent arms formed 12 T1 addresses under the pre-G2 subject+facet grain:

  | Locus | 9P3 subject | 9P3 facet |
  |---|---|---|
  | F | worker lease | duration |
  | G | worker lease | renewal |
  | A | job execution attempts | maximum attempt count |
  | C | execution attempt | timeout |

- The same grain made Arm F's C09 over-split at T9: `job cancellation | repeated cancellation handling`. That is the defect G2 was adopted to remove.
- The long-horizon v1 design (2026-09-29) inherited "T1 forms exactly 12 addresses" (I1) without reconciling it with G2.

**Conclusion: the sealed oracle conflicts with G2, decisively for A+C and F+G, and on the text for B.**

**Offline grading** (`grade_grouping`, which reads no wording):

| Placement | Against the 12-section oracle | Against mechanical G2 (9 concerns) |
|---|---|---|
| LH23 T1 (v5) | UNDER_SPLIT (A holds A,B,C), UNDER_SPLIT (F holds F,G) | clean |
| 9P3 T1 (pre-G2) | clean | OVER_SPLIT (A across 3), OVER_SPLIT (F across 2) |

**Admission** (canonical facets on) applies both the 9-address and the 12-address T1 unchanged. No deterministic wall decides grain, correctly: grain is semantic (§8).

## 4. Why v5 did not expose it (what was and was not validated)

| Measure | v5 formation cases | LH23 T1 |
|---|---|---|
| CREATEs in one Call 1 | 7 (core), 16 (C8 large), 2 (jobs), 1 (orion H) | 9 formed, 12 expected |
| Evidence characters | 1,230 / 1,556 / 343 / 587 | ~9,000 (9,855 rendered) |
| Propositions | 14 / 19 / 4 / 3 | 32 |
| Documents about the **same** act or entity that are expected separate | **none** | A/B/C (attempt), F/G (lease) |

**C8.** Its 16 concerns were formed from scratch (not selection), but each concerned a different act or entity with different nouns: refund, payout, chargeback, gift card and so on.

**The G2 fixtures and U1–U4.** Every SEPARATE case separates different acts or entities: cancellation vs audit deletion, late vs damage compensation, compensation vs settlement, customer vs supplier refund. Every ONE_CONCERN case (C09, C6, revocation) groups several rules on one act.

**Validated:** the model separates different acts or entities, and keeps one act's dimensions together, at up to 16 simultaneous concerns.

**Never validated:** whether several independently parameterised rules on the same act or entity must be separate concerns. G2 answers "one concern" (the dimension clause), and the model answered exactly that at T1.

**Density.** The contrast is observational. Every v5 case is 6–30× smaller in evidence than T1, and 9P3 formed 12 at T1's density under a different grain. Density may contribute to the merge, but this audit does not establish it, and nothing establishes it without a live call.

## 5. The Call-1 contract

**The separation test already exists, verbatim.** "Independently governed … whose rules can change without changing the first concern's." It is the candidate "independently changeable" test. Adding it again would change nothing.

**Language that pulls toward grouping:**
- "identify a MINIMAL set of materially meaningful semantic loci" (base text, also in 9P3's prompt);
- "different dimensions, of one governed concern must not become separate addresses";
- "name the governed concern so that a later proposition about any dimension of it belongs there";
- "A different who, when, how, how long or whether … is never a reason to create an address".

This is the post-v3 correction of the over-split failure, and it is what makes A/B/C and F/G one concern. **It is not an overcorrection relative to G2. It is G2.**

## 6. Subject formation is not the cause

The grouping decision came first. The rationale names the concern ("one act: delivering an admitted job"; "the exclusive lease") and classifies the sections as its dimensions, using G2's own categories (limits, timing, deadline; duration, expiry, renewal). The broad subjects "Job execution attempts" and "Worker lease on a job" are that decision named, as G2 instructs ("name the governed concern so that a later proposition about any dimension of it belongs there"). The canonical facet is derived mechanically from the subject and plays no part in grouping. (**Answer: A.**)

## 7. Dense-formation hypothesis

**Result: not supported as the cause.** The deterministic contract accepts both groupings (§3). The model's grouping matches G2 at T1's density. The pre-G2 grain produced 12 at the same density. The hypothesis could only matter if G2 were amended to require separation (§9), and a live validation would then have to test it.

## 8. A deterministic structural fix is not possible

Separating A/B/C or F/G requires knowing that "retry wait" or "renewal" is an independently governed operation rather than a dimension. That is semantic interpretation of natural language.

The only explicit structure that separates them is the section / heading / `artifact_ref`. That is the forbidden rule (different section = different concern). It is also exactly the 9P3 grain that caused C09. **No wall is added.**

## 9. Architecture question (DECIDED 2026-09-30: Option 1)

> Decided by the founder: **Option 1**. G2 is kept; A+B+C and F+G are one governed concern
> each; no "different trigger/outcome ⇒ different concern" rule is adopted. Recorded in
> `2026-09-30-ie2-governed-concern-grain-clarification.md`; the frozen long-horizon run is
> annotated, not rescored, in `2026-09-30-ie2-ie3-long-horizon-v1-interpretation-note.md`; the
> dense-formation validation of §10 is sealed as `intent-v2-locus-validation-v6`, with its
> same-entity class labelled by the decided law.

**ARCHITECTURE QUESTION:** When several rules with their own triggers and parameters govern the *same* act or entity (an execution attempt's budget, retry wait and timeout; a lease's duration and renewal), are they one governed concern (G2 as written) or separate concerns?

**Option 1: G2 stands; the oracle is re-derived at concern grain.**
- A+B+C and F+G are one concern each, so T1 has 9 governed concerns. The frozen T1 was correct.
- The long-horizon oracle becomes a concern-level key: several sections may designate one address, and I1 becomes "12 sections designated onto the 9 governed concerns".
- **Consequence:** no model or policy change, and C09/C6 stay safe. The long-horizon experiment's I1 and the locus checks at A/B/C/F/G were measured against the wrong key, but the frozen run stays frozen and a re-evaluation is a separate, explicit task. Later-turn checks at merged addresses must count claims per locus, not per address.

**Option 2: amend G2 so that an operation with its own trigger and outcome is its own concern, even on a shared act or entity.**
- **Candidate wording:** separate when the rule set is triggered by its own event and produces its own transition (retry scheduling on failure; timeout of a running attempt; renewal of a lease).
- **Consequence:** a new policy (`intent-v2-locus-v7`), and it must carve out the dimensions G2 keeps together. As a trigger-and-outcome test it splits C09 (repeated cancellation has its own trigger and outcome) and threatens C6 (the request deadline has its own trigger), unless "what repeating it does", deadlines, and acts on an entitlement are explicitly excluded.
- Each exclusion is a new judgement call. A candidate that classifies all ten required pairs correctly cannot be derived from G2's text; it would be a new law.

**Option 3: record the class as grain-open.**
- Until the founder decides, validations and oracles accept either grouping for same-act/same-entity rule sets, and score only the unambiguous classes.
- **Consequence:** no false failures, but also no pressure in either direction.

**Blocked:**
- any Call-1 prompt change (v7);
- any new grain regression that encodes A/B/C or F/G as separate;
- any re-scoring of the long-horizon run;
- the labels of the dense-formation validation's same-entity class (§10).

## 10. Future validation design (not built, not run)

**Purpose.** Forming many semantically nearby concerns simultaneously from a fresh baseline, at T1-like density: at least 12 documents, about 8,000 characters and 30 or more propositions. It uses a new domain, not Orion labels.

**Classes, each at least 3 instances, all in one Call 1:**

| Class | Content | Catches |
|---|---|---|
| (a) different acts in one subsystem | e.g. warehouse: receiving, putaway, picking, cycle count, returns inspection | UNDER_SPLIT |
| (b) one act with 3–4 dimensions spread across **separate documents** (who / when / limit / deadline of one act in three sections) | — | OVER_SPLIT; the section-equals-concern failure |
| (c) shared nouns across separate concerns (e.g. "pallet" in receiving and in cycle count) | — | topic-word merging |
| (d) **same act or entity, several rule sets with their own triggers** | the A/B/C and F/G class | its expected labels are **undecided until §9 is answered**; until then the class is scored "either grouping" (Option 3) |

**Scoring.**
- `grade_grouping` reports both OVER_SPLIT and UNDER_SPLIT.
- Answer keys are sealed before the run.
- Correction sets are **enabled** in that validation, per the standing decision (historical off, production off, next fresh IE2 validation on).
