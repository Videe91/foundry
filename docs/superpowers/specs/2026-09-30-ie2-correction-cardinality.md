# IE2 Correction Cardinality: Decision Record

**Status:** implemented 2026-09-30 as `intent-v2-locus-v6`, with no live call. It is not yet validated live.
**Origin:** `intent-ie2-ie3-long-horizon-v1` (`a0ee2f7`, `LONG_HORIZON_IE2_IE3_NOT_VALIDATED`). That evidence is frozen and was neither modified nor rescored.

## 1. The frozen T8 shape

Before T8, the address the model had formed for A, B and C (`ADDR-3a12d8a4…`, "Job execution attempts") held 13 live claims. Four of them concern B:

| Claim | Created by | Meaning |
|---|---|---|
| `CLAIM-a05c1b4b` | `JDG-cf225a3b` | wait before the first retry: 2 seconds |
| `CLAIM-b1671aa0` | `JDG-6dc43a9d` | maximum wait before any retry: 30 seconds |
| `CLAIM-efa62a8f` | `JDG-e1da6031` | each later wait doubles |
| `CLAIM-2a1fa269` | `JDG-d2a97d36` | the wait is measured from the end of the failed execution |

At T8 the B section restores a fixed five-second wait that does not vary.

- **Call 1** bound all 12 items: 9 binding judgments, because the merged addresses took several items each.
- **Call 2** proposed the answers below, and non-operative S1 (purpose) and S5 (example):

| Proposition | Sentences | Disposition | SUPERSEDE targets |
|---|---|---|---|
| `P-B-wait` (5 s) | S3 | ASSERT | `JDG-cf225a3b`, `JDG-6dc43a9d` (2:1) |
| `P-B-meas` | S3 | SUPPORTS `CLAIM-2a1fa269` | — |
| `P-B-fixed` | S2, S4 | ASSERT | `JDG-e1da6031` (1:1) |

This is semantically correct. Three old claims become obsolete and two propositions replace them; the compatible measurement-start claim is supported. The answer was refused with `CONFLICTING_DISPOSITION: P-B-wait (ASSERT_CLAIM, SUPERSEDE, SUPERSEDE)`. `VALID_DISPOSITIONS` requires each proposition's sorted kinds to be exactly `(ASSERT_CLAIM, SUPERSEDE)` for a correction, which means one target.

**T9 to T12 were the same defect, not new ones.** Each later Call 2 re-proposed the still-unresolved B revert and was refused for a B proposition carrying two SUPERSEDEs:
- at T10 and T12, the 2-second wait and the cap on one proposition;
- at T9, the cap was attached to the no-variation rule instead.

The D correction (T10) and the G correction (T12) in those same answers were well-formed 1:1 corrections, lost only because the whole response was refused. The frozen T9 answer had also stated the repeated-cancellation meaning (C09) correctly.

## 2. Where "one proposition retires at most one claim" lived

| Layer | Assumption |
|---|---|
| Output schema `AccountedDraftPayload` (`921171df…`) | **none**: any number of SUPERSEDE drafts may name one `proposition_id` |
| Prompt (v4/v5) | wording: "ASSERT_CLAIM plus SUPERSEDE (a correction)" |
| `proposition_accounting.VALID_DISPOSITIONS` | **the law**: (ASSERT, SUPERSEDE) exactly |
| `ReasoningRequest` / port | none |
| Adapter wrapping | none: one `SupersedeProposal` judgment per SUPERSEDE draft |
| Admission | none: per judgment (target applied and active); SUPERSEDE is material, so it is pending |
| Reducer / replay | none: one `SupersessionRecord` per judgment |
| Authority (9P3 protocol) | per target: exactly one pending proposal per eligible target gets an AGREE; more than one is `AMBIGUOUS_PROPOSALS` |
| Historical identities | v4/v5 prompt and schema hashes; validation v5 evidence |

The unit of correction below the accounting law was already the edge, one old claim per SUPERSEDE judgment. The only 1:1 restriction was the accounting law.

## 3. The cardinality law

All four shapes are lawful and occur in real corrections:
- **1 to 1:** the simple case.
- **N to 1:** several fragmented rules consolidated into one (the 2-second wait and the cap into "5 s fixed").
- **1 to N:** a compound rule restated as separate rules.
- **N to M:** a restructuring such as T8.

**Representation chosen: ASSERT plus a target set, per proposition.** A correcting proposition is `ASSERT_CLAIM` plus one `SUPERSEDE` for each current claim it makes obsolete. Any N:M correction is a set of edges (proposition, old claim), so each old claim can be carried by one of the propositions that replace it.

A separate correction group object was rejected. It would add a new durable concept, and authority would still decide per edge, so it would not change what can be expressed.

Under `TARGET_SET`, the laws are:
1. **Exactly one disposition per proposition.** SUPPORTS alone, or ASSERT alone, or ASSERT plus one or more SUPERSEDE (`CONFLICTING_DISPOSITION` otherwise). A SUPERSEDE without an ASSERT, or two ASSERTs, is still refused.
2. **Every SUPERSEDE names a target** (`UNTARGETED_SUPERSEDE`; the output contract also refuses an empty target).
3. **Each old claim is superseded at most once per response** (`DUPLICATE_SUPERSEDE_TARGET`). When several propositions together replace one claim, exactly one carries its SUPERSEDE and the others are ASSERT alone. This keeps authority unambiguous: one pending proposal per target.
4. **Every target was shown to the response** (`UNKNOWN_SUPERSEDE_TARGET`). Only live claims are shown, so an already superseded target is refused here, and admission independently refuses one.
5. **Every target sits at the address of the proposition's ASSERT** (`CROSS_ADDRESS_SUPERSEDE`). This is the approved correction law ("ASSERT_CLAIM at that address plus SUPERSEDE of the incompatible claim"), now enforced mechanically.
6. **No claim is retired without an explicit edge.** Retirement happens only through a SUPERSEDE judgment that names it by id, and nothing is inferred from wording.
7. **A refusal is whole.** It comes before any judgment of Call 2 exists, so the claims, supports, supersessions and pending set are unchanged.

Every accounting finding remains a whole-response refusal. The three new codes are not on the production re-proposal allowlist (production retry is untouched), so a response refused for them is never re-proposed.

## 4. Authority compatibility

The existing authority unit is the edge. Each SUPERSEDE judgment is pending, and the 9P3 protocol gives an AGREE to each eligible target that has exactly one pending proposal.

A target set produces exactly the edges that several 1:1 corrections at one address already produced; T3 in the frozen run had three. So no new approval unit is introduced. The offline T8 regression shows the three targets each AGREEd once, with nothing ambiguous and nothing left pending.

Two properties already existed before this change and were not introduced by it:
- the corrected claim coexists with the old one until authority acts, as the 9P3 rubric says ("does not leave the current view before authority");
- approval is per edge, so a correction set can be half-approved when some of its targets are not eligible.

Whether a multi-edge correction should be approved as one atomic unit belongs to the separate authority-routing task. It is recorded there and does not block this change.

## 5. Identity

- **New policy:** `intent-v2-locus-v6` (`XAICorrectionSetSemanticReasoner`). It is v5's instruction with one "CORRECTION SETS" section appended (prompt `13aa8774…`) and `correction_law = "TARGET_SET"`.
- **Output contract:** `AccountedDraftPayload` `921171df…`, unchanged.
- **Earlier policies:** every policy up to `intent-v2-locus-v5` keeps `ONE_TARGET`, and v5's prompt `cc913e3d…` is byte-identical.
- **Validation status:** v6 is not validated live.

## 6. Still open (not addressed here)

1. **Concern grain at scale.** The T1 merges (A+B+C and F+G) come from G2's governed-concern grain, and that law is unchanged.
2. **Checkpoint-only authority.** A SUPERSEDE proposed outside a correction checkpoint stays pending and blocks its locus from IE3 (frozen T13).
