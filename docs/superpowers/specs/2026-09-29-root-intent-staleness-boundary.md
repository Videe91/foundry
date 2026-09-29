# Root Intent Staleness Boundary: Decision Record

**Status:** decided by the founder, 2026-09-29 (architecture Option D). Binding amendment: IE3 design §17.2.
**Origin:** the pre-run audit of the 16-turn IE2+IE3 long-horizon experiment (`intent-ie2-ie3-long-horizon-v1`, not started). A model-proposed root must cite a shown claim (`_check_grounding`). The Orion corpus corrects operational claims at T3, T5, T7, T8, T10, T12 and T15, so the root would have gone permanently stale at the first correction, with no lawful reconciliation.

## Pre-change mechanism

`derivation.stale_object_ids` returns every descendant, over recorded `DerivationEdge`s, of three root sets: inactive judgments, the issue versions they minted, and the claims they asserted (R105–R107). IE3 writes one edge per `DERIVED_FROM` relation, with the claim id as parent (R108); Slice-1 uses the judgment id. Traversal is transitive: object → object through `DERIVED_FROM` to an existing Decision, Goal, Requirement or Constraint. `SERVES` is never a derivation edge. The resulting `stale_ids` was read with no exception for kind.

## Decision

A root Intent is a staleness boundary. `DERIVED_FROM` on a root is provenance, not a freshness dependency. See §17.2 for the law, the definition of root (every `INTENT`, exact by relation legality), where it is implemented, and why history is untouched.

## D8 limitation, stated plainly

A real change of purpose still has no lawful path. Root replacement and amendment remain D8, which is not built. This decision only stops ordinary claim corrections from simulating an amendment.

## Certificate impact

Certificates bind prompt, policy, schemas, wire and exam hash, but not the production base commit. The exam hash covers only exam code and worlds, and no v5 world had a root with a derivation edge. So without an exam change, Astra's exam-v5 certificate would still have read CURRENT over a lifecycle it never examined. Exam v6 adds case K and supersedes v5 (`ROOT_INTENT_LIFECYCLE`). Every v5 PASS now reads SUPERSEDED, and every v5 evidence file is pinned byte for byte. A fresh exam-v6 certification is required before any model is called certified under the current lifecycle.

## Case K (exam v6)

- **Setup.** An earlier graph, applied through the production path, left:
  - one PROPOSED root, with a `DERIVED_FROM` edge to the refund-request-window claim;
  - one Requirement on that claim, serving the root.
- **Correction.** The window is corrected (30 → 14 days) and the old judgment superseded.
- **What the model is shown.** The root fresh (and not in `root_intent_ids`, since it is not CANONICAL), the Requirement stale, and only the corrected claim live.
- **Lawful answer.** Exactly one same-kind replacement:
  - grounded on the corrected claim;
  - serving the same root;
  - no Intent node, no witness, no gap. A gap about the root fails the shared gap rule.
- **Afterwards.** The root is unchanged, current, not stale, and the only Intent.
- **Wording.** The mission is never scored.
- **Integrity.** The case refuses to score under the pre-boundary law.
