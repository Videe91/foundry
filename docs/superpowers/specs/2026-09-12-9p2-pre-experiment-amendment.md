# 9P2 Pre-Experiment Architecture Amendment

**Status:** Architect-locked after independent review of implementation commit `be9001bb008609f8d3729645485900da09041ccc`.

**Applies to:** `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`

**Purpose:** Resolve the two open architecture questions raised by the T0-T7 implementation before the 9P2 implementation may be frozen for a live preregistered experiment.

---

## Ruling A — Contrastive widening is scope-closed

The requested assimilation scope is a hard semantic-visibility boundary.

For a `ReasoningRequest` assembled for scope `S`, a structurally touched live claim may appear in `ComparisonContext`, and its address may widen Call 2, **only if that address is already eligible for scope `S` under the existing address-scope rule**:

```text
address.scope == ()
OR
S in address.scope
```

Therefore:

1. Call 1 still begins from all active in-scope addresses, including project-wide addresses.
2. `profile_address_ids` is the eligibility boundary for claim/address transition touches in that request, not merely a rendering hint.
3. A predecessor evidence version may structurally support live claims in several scopes; only claims whose addresses are in the request's eligible address set may be included as `EFFECTIVE_EVIDENCE_OF` / `CLAIM_AT_ADDRESS` transition targets.
4. Out-of-scope claim ids and address ids must not appear in the request's comparison context.
5. `contrastive_address_ids(request_1.comparison_context)` must therefore be a subset of Call 1's active in-scope address ids.
6. Call 2's `claim_neighborhood` remains the union of the Call-1 decision neighborhood and in-scope contrastive addresses only. It may not widen into another semantic scope merely because the same predecessor evidence structurally touches a claim there.
7. Project-wide addresses remain eligible by the existing `scope == ()` rule.
8. No lexical, embedding, descriptor, or semantic rule is introduced by this boundary. It is deterministic authorization of what state a scoped request is permitted to see, not a meaning decision.

### Required repair

`compile_comparison_context` must restrict transition-touched claims to claims whose `address_id` is present in the supplied `profile_address_ids` set.

The function may continue to emit an evidence-lineage transition with zero touched claims when the current evidence explicitly supersedes a predecessor; the old-to-new diff is still structural history. But no out-of-scope claim/address edge may be carried with that transition.

### Required tests

At minimum prove:

- one predecessor effectively supports one live claim at scope A and one live claim at scope B;
- compiling with only scope-A/profile-A addresses includes only the scope-A claim/address edges;
- `contrastive_address_ids` contains only A;
- Call 2 does not receive the B address or B claim;
- a project-wide address remains eligible for either scope;
- no third call, retry, fallback, or semantic classification is introduced.

This ruling resolves implementation concern **AQ2**.

---

## Ruling B — 9P2 needs its own leakage gate over the actual contrastive prompt

The historical 9P gate `no_tracked_locus_leakage` remains historical evidence for the 9P experiment. It must not be treated as sufficient for 9P2 because historical `render_request(...)` deliberately omits `comparison_context`.

Before the first live 9P2 provider call, the preregistered 9P2 experiment must define and seal a distinct leakage gate that scans the exact harness-authored text the 9P2 model can receive.

The 9P2 leakage haystack must include, at minimum:

1. `CONTRASTIVE_SYSTEM_INSTRUCTION` for policy `intent-v2-9p2-v1`;
2. every planned Call-1 and Call-2 request skeleton rendered through the real 9P2 assembly path;
3. rendering with `include_comparison_context=True` (or through `XAIContrastiveSemanticReasoner`'s exact request-rendering policy);
4. the actual five-key request shape, including `comparison_context`;
5. structurally generated comparison edges/diffs using content placeholders so immutable evidence bytes themselves are not falsely classified as harness leakage;
6. every preregistered tracked-locus description, expectation id, and expectation text as leakage needles, under the same evidence-vs-harness distinction used by 9P.

The gate must fail closed before reasoner construction/live calls if a tracked expectation or locus is exposed by harness-authored prompt/context.

The old 9P gate may remain unchanged for historical compatibility. The new 9P2 gate belongs to the separate preregistered experiment plan and is required before live authorization.

This ruling resolves implementation concern **AQ1**.

---

## Ruling C — Transition identity fields are required in 9P2 v0

The conceptual `ComparisonContext` sketch in the original spec showed:

```text
predecessor_evidence_id | null
artifact_ref | null
```

For 9P2 v0, a transition capsule exists only when current evidence has an explicit `supersedes_evidence_id`, and valid supersession already requires a matching artifact lineage. Therefore the implemented non-null contract is the authoritative v0 contract:

```text
predecessor_evidence_id: required non-empty id
artifact_ref: required non-empty id
```

Evidence without a predecessor creates no transition capsule.

This records and ratifies implementation ruling **R1**; it does not add new behavior.

---

## Freeze gate after this amendment

The 9P2 implementation may be frozen for scientific preregistration only after:

1. Ruling A is implemented with RED -> GREEN evidence;
2. full local verification remains green;
3. independent review finds no Critical/Important issue in the repair;
4. historical 9P artifacts/policy/schema remain unchanged;
5. no live provider/model/judge call has occurred.

Ruling B is then implemented as part of the separate 9P2 experiment preregistration before live authorization.

9Q remains unauthorized.
