# IE2 Address Grain: One Governed Concern (G2)

**Status:** architecture decision by the founder, 2026-09-28. Amends the IE2 v2 design
(`2026-09-10-intent-intelligence-v2-design.md` §7.1, §7.2; new §7.1.1).
**Policy:** `intent-v2-locus-v2` (`XAIGovernedConcernSemanticReasoner`), prompt SHA-256
`77a20f3b1d39787b351aedaf031176c61c295dc8cab526ffa08373da79a801cd`. Output schema, transport,
parser and reference law unchanged (`ffc6946a…`). No live model call has been made under it.

## 1. The defect

Two definitions of a semantic address reached the model at once:

| source | definition |
|---|---|
| IE2 v2 design §7.1 (withdrawn) and the base prompt `intent-v2-9p-v4` | "one subject and one facet (property, aspect, or question) of that subject" |
| locus policy `intent-v2-locus-v1`, appended beneath the base text | "one subject and the one stable question … put the specific aspect in the claim predicate … where they differ, this guidance governs" |

Locus validation v2 (`2ea8ef6`, `LOCUS_POLICY_NOT_VALIDATED`) showed the result: in both of
its failures the model wrote a dimension-shaped facet ("Who may cancel a job", "How
cancellation affects execution attempts"; "How is the sender compensated?"), then read a
later compatible proposition as a different question and created an address ("How a repeated
cancellation is handled"; "When must a late-delivery refund be requested?"). The validation's
own corpus used two grains (C6 grouped a request deadline with its compensation; the large
world separated request window, completion time and payment method), which is the same
missing decision surfacing in the harness.

## 2. The decision

**Locus.** A semantic address is one governed act, entity or record, entitlement, state,
decision or coherent operational concern. `subject` names the concern.

**Facet.** The facet asks about the governed concern as a whole. It never names one of the
concern's dimensions and never paraphrases the first proposition known about it.

**Dimensions are claims.** Who may perform it; when it may occur; eligibility and
preconditions; effects; limits and quantities; deadlines; destinations; what repeating it
does; exceptions. Each is a claim (predicate) at the concern's one address. A different who /
when / how / how long / whether about the same concern never creates an address.

**Separate-address rule.** Create an address only for a different, independently governed
act, entity or record, entitlement, decision, state transition or operational concern: one
with its own rules and lifecycle, whose rules can change without changing the first
concern's. Shared topic words, documents or subject areas never merge concerns.

**Process-stage rule.** A stage of a process has its own address only when it is itself
independently governed as an operation or decision. A deadline for doing something, an
eligibility condition, an amount, a payment destination, an actor, an effect or a repetition
rule belongs to the concern it constrains. Late-delivery compensation is one concern: its
entitlement, the amount refunded, the payment destination and the 14-day request deadline are
claims at one address. (This resolves locus validation v2's C6 inconsistency deliberately.)

## 3. Mechanism: Option A only

The contract is rewritten, not appended to. `intent-v2-locus-v2` is the contrastive
instruction with three base passages **replaced** (the address definition, the CREATE
guidance "distinct subject/facet", the BIND guidance "subject and facet") and the locus-v1
guidance **replaced** by governed-concern guidance. Each replacement anchor must occur
exactly once or the module refuses to import, so drift in the historical text cannot
silently leave a second definition. No model call, challenge step, facet revision or change
to the two-call assimilation law is added. A challenge / second-lens mechanism is considered
only if this contract fails a sealed validation.

## 4. Offline proof (what is decidable without a model)

`src/foundry/experiments/locus_formation/grain.py` and `tests/unit/test_locus_formation_grain.py`:
seven fixture groups (one concern: job cancellation with C09's four propositions,
late-delivery compensation with C6's three, credential revocation with four; separate
concerns: cancellation vs audit-record deletion, late-delivery vs damage compensation,
requesting compensation vs an independently governed bank settlement run, customer refunds
vs supplier overpayment refunds); a deterministic grader (OVER_SPLIT, UNDER_SPLIT, UNPLACED)
that reads no wording; and a facet screen for dimension-shaped facets. The recorded v2 C09
and C6 placements grade as over-splits, v1's recorded revocation locus and v2's recorded
insurance/late-delivery separation as the governed grain. Whether the live model follows the
contract is decided only by a future sealed validation.

## 5. Historical treatment

9P3, locus validation v1 and v2, their artifacts and results are unchanged. v2 remains
`LOCUS_POLICY_NOT_VALIDATED` for `intent-v2-locus-v1`; it is the evidence that exposed the
conflicting definitions. The 9P, 9P2 and locus-v1 prompts, classes and hashes are
byte-identical.
