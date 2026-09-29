# IE2 Canonical Facet: the facet is a projection of the governed concern

**Status:** architecture decision by the founder, 2026-09-29, taken after the audit below.
Amends the IE2 v2 design (`2026-09-10-intent-intelligence-v2-design.md` §7.1 table, new
§7.1.2, §7.2).
**Policy:** `intent-v2-locus-v3` (`XAICanonicalFacetSemanticReasoner`), prompt SHA-256
`83a717a9e11d26841b0538bcb781eb766b07bdfc94873213da0965be5ac2d803`, output schema
`ConcernDraftPayload` `08d881db080f87b45abebc3fb79ce53229ccf490b1ba331f75744efb55051b79`.
No live model call has been made under it.

## 1. What validation v3 separated

`intent-v2-locus-validation-v3` (sealed `0feb0dc`, raw run `83bbf3a`, adjudicated `4e277a6`)
remains **LOCUS_POLICY_NOT_VALIDATED** for `intent-v2-locus-v2`. It showed two things:

* **Grouping worked.** Every structural check passed with zero over-splits and zero
  under-splits: C09 formed one cancellation address and the repeated-cancellation
  proposition joined it; C6's 14-day request deadline joined late-delivery compensation; the
  lineage-free extension found the right one of sixteen model-formed payment concerns; the
  four nearby pairs stayed apart.
* **Facet formation failed.** Facets named one dimension ("Sender refund entitlement", on both
  late-delivery and damage compensation: the two semantic NOs of C6 and U2) or no concern
  ("How it is governed" on all sixteen payment concerns, "Governance", "Lifecycle").

## 2. Audit: does the facet carry independent semantics under G2?

| question | finding |
|---|---|
| Does `subject` name the governed concern? | Yes. §7.1.1 makes it so ("`subject` names the concern"); in v3 all 27 model-formed subjects were concern-specific and pairwise distinct while facets repeated. |
| Can two valid G2 addresses share a subject and differ only by facet? | No. Dimensions are claims, so a facet that distinguished two addresses of one subject would be naming a dimension (forbidden) or a concern the subject failed to name (a subject defect). Same-subject addresses in different contexts are distinguished by `scope`, never by facet. |
| Does code depend on facet carrying information beyond subject? | No. `address_id` is minted from project and judgment (`address_id_for`); the identity law forbids descriptor equality; admission, reducer, derivation, contrastive retrieval and view derivation never read facet wording. IE3 synthesis contexts pass it as display text beside the subject (`LocusBasis.facet: str`, min length 1). |
| Identity / hashing / retrieval / equivalence | Not part of any. |
| Provenance / persistence | Recorded inside the CREATE/BIND judgment payload in the event log and on the reduced `SemanticAddress`; replayed as recorded. |
| Certification | IE3 exams render recorded facets in their fixed ledgers; nothing is recomputed. |
| Would a projection preserve the invariants? | Yes: identity, append-only events, replay, reference law and admission ordering are unchanged; the projection is injective, so it cannot merge concerns. |
| What must change? | A new policy identity and output contract (the model no longer writes a facet); a defaulted admission flag. No event, reducer, domain-model or schema-of-state change; no migration. |

Conclusion: under G2 the facet is redundant with the subject. It is made a deterministic
projection. (`ConstraintFacet`, the IE3 constraint enum, is an unrelated concept and is
untouched.)

## 3. The decision

**Invariant.** The facet is a stable canonical descriptor of the governed concern and carries
no independent semantic partitioning decision: `facet == canonical_facet(subject)`.

**Construction.** `canonical_facet(subject) = "Rules governing " + subject`
(`foundry.domain.semantic_identity`). One universal representation, the subject kept byte for
byte: no case folding, trimming or other normalisation, because no existing rule defines
one and each would be a choice. Deterministic, injective, inference-free; it never reads a
case, document or domain.

**Contract (Option A).** The model chooses the governed concern and names it; it writes no
facet. `ConcernDraftPayload` replaces the CREATE_ADDRESS and BIND_TO_ADDRESS drafts with
facet-free ones (every other draft is shared). A reply that still carries a facet violates the
sealed schema and is refused whole, so no model facet is silently overwritten. The adapter
sets `candidate.facet = canonical_facet(draft.subject)`. Option B (keep a model-written facet
and require it to equal the projection) was rejected: it keeps a semantic-looking choice the
model can only get wrong. The historical contract `SemanticDraftPayload` and every historical
policy class are byte-identical; each policy class now declares its contract in a
`draft_payload` class variable.

**Prompt.** `intent-v2-locus-v3` is `intent-v2-locus-v2` with its two facet passages
rewritten (exactly once each, or the module refuses to import): the address definition now
says the model never writes a facet, and the facet rule becomes a subject rule (the subject
names the governed concern itself, specifically enough that it could not name an unrelated
concern; never one dimension, never a generic word, never a paraphrase of the first
proposition).

**Enforcement.** `AdmissionPolicy(canonical_facets=True)` refuses any CREATE_ADDRESS or
BIND_TO_ADDRESS candidate whose facet is not the projection:
`STRUCTURAL: NON_CANONICAL_FACET: …`. The flag defaults to False so historical policies,
seed authors and ledgers route exactly as before; a run of `intent-v2-locus-v3` must set it.

**Limit (stated, not hidden).** The projection preserves every distinction the subject makes
and invents none. If a model gave two different concerns the same subject, their facets would
match too; that is a subject (concern-naming) defect, visible in the subject, and the reason
the prompt's concern-naming rule now sits on the subject.

## 4. The validation-v3 answer-key defect (recorded, not rescored)

Validation v3's C09 semantic NO (Q-T2-H) was an inventory defect, not a production defect.
9P3's H-T9 document says, in prose, "Orion may receive the same cancellation more than once;
a repeated cancellation is simply acknowledged." The sealed inventory listed only the numbered
rule for H-4 ("… must remain cancelled and … must not otherwise change the job's state"). The
live model's claim stated both; the independent adjudicator correctly answered NO against the
sealed key. v3 is not modified or rescored and stays `LOCUS_POLICY_NOT_VALIDATED`. Production
semantics are not changed to fit it.

**Rule for any future validation:** the proposition inventory must account for all
semantically operative source prose, not only numbered rules.
`foundry.experiments.locus_formation.source_coverage` makes that checkable: every sentence of
every source must carry proposition ids or an explicit non-operative reason, and the v3
inventory of H-T9 is caught by a test. No v4 validation is created by this decision.

## 5. Offline proof

`tests/unit/test_canonical_facet_policy.py` and `tests/unit/test_canonical_facet_grain.py`
(the grain tests run the production adapter, `assimilate_delta` and a governor with
`canonical_facets=True`; only the transport is scripted): C09, C6 and credential revocation
keep one address with one unchanged canonical facet as the last dimension joins at T2; the
four nearby pairs get two addresses with different facets; the sixteen v3 subjects get sixteen
distinct concern-specific facets, and every recorded v3 facet is refused; a reply carrying a
facet is refused by the contract. Whether the live model names concerns well is a question for
a future sealed validation.
