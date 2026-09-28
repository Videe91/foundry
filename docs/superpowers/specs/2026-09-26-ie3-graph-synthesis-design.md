# IE3 — Multi-Type Intent Graph Synthesis (architecture checkpoint)

**Status:** APPROVED architecture checkpoint (2026-09-26), with rulings **R99–R104** and
resolutions of **Q1–Q6** (§0). No production code exists for IE3 yet.
**Base:** `feat/intent-intelligence-v2` @ `b176364ee1dfb12b84cee00a34f84ddf25595c43`.
**Precedence:** `FOUNDRY_CONSTITUTION.md` > this document > implementation.
IE2 (IE2.1–IE2.5) is frozen; its checked-in mutation suite (171 mutants) is part of the
regression contract.

The design rules are numbered **G1…G17**. They are approved as part of this checkpoint, and §0
maps them to the rulings. Where a ruling or a Q resolution differs from the original
recommendation, the ruling governs, and the sections below have been updated to match it.

Findings marked *(code reading)* were established by reading source, not by executing a test.
Each one is converted into a RED test in the slice that depends on it.

---

## 0. Approved rulings and resolutions

| Ruling | Content | Design rules |
|---|---|---|
| **R99** | IE3 synthesizes exactly INTENT, GOAL, OUTCOME, REQUIREMENT, CONSTRAINT, NON_GOAL, PREFERENCE, DECISION, ASSUMPTION. Metric and VerificationObligation are deferred to a quality slice. | G1, G2 (§5–§7) |
| **R100** | The typed proposal variants and the `LocalNodeRef` / `ExistingObjectRef` / `BasisClaimRef` namespace design are approved. New nodes never carry model-selected durable ids. | G3, G5, G6, G12 (§8–§10, §14) |
| **R101** | `DERIVED_FROM`, `SERVES`, `AFFECTS` and `EXCLUDES` remain separate semantic axes. Relevance is never implicit. A same-batch, model-created Decision may not bootstrap authority or basis for another new node. | G7–G10 (§10–§12) |
| **R102** | Model intelligence never grants canonical authority. AI_INFERRED project choices remain non-canonical unless a separate lawful human authority act establishes otherwise. | G4, G11 (§8, §13) |
| **R103** | Atomicity option C: one new durable graph transition decides and applies the validated graph atomically. There is no separate incomplete decision/application window. | G13 (§15–§16) |
| **R104** | A safe partial graph plus explicit gaps is allowed, in the same atomic transition. Every persisted node must be independently structurally valid, and no dangling or local dependency may point through an unresolved region. | G16 (§19) |
| **R105–R107** | Writer-independent claim-basis staleness: claims asserted by inactive judgments are traversal roots of `stale_object_ids`, never returned themselves, and both historical edge conventions propagate identically (§30). | §30 |
| **R108** | IE3 records every `DerivationEdge.parent_id` as the actual durable target of the object's `DERIVED_FROM` relation: `BasisClaimRef` → claim id, `ExistingObjectRef` → object id, `LocalNodeRef` → resolved new object id. A claim id is never translated to its judgment id. Slice-1's judgment-id convention stays frozen legacy behaviour. | §16 |
| **R109** | For a non-human node, origin is ``RESEARCH_DERIVED`` only when it cites at least one claim directly and every directly cited claim's effective evidence is entirely ``RESEARCH``; otherwise ``AI_INFERRED``. An empty direct-claim set is ``AI_INFERRED`` (Slice-1's vacuous ``all([])`` is not inherited). Basis authority, existing-object basis and same-batch basis never make a node research-derived. As built in `domain/intent_graph_routing.py::derive_graph_origins`. | §13 |
| **R110** | Graph synthesis is its own Model Runtime task: `ModelTask.INTENT_GRAPH_SYNTHESIS`, pinned to `ModelTier.REASONER` and distinct from `INTENT_SYNTHESIS`. A model certified only for `INTENT_SYNTHESIS` is ineligible for graph synthesis, and no existing `ModelDescriptor.certified_tasks` is widened. As built in `adapters/intent_graph_synthesis/model_runtime.py`: policy `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v1`, a new pinned-hash system instruction, and a model-facing draft schema (runtime owns gap `blocking` and `graph_contract_version`). No production descriptor is graph-certified; certification is a later, separate step. | §22 |
| **R111** | `IntentGraphSynthesisResult` (and the model-facing draft) carries `unchanged_object_refs: tuple[ExistingObjectRef, ...]`. Each is a model-proposed witness that a shown, current, non-stale object already represents the intended meaning: mint nothing for it. It is not a relation, replacement, basis, authority claim or effect, and receives no assignment or origin. The result's non-empty law is nodes OR gaps OR unchanged refs. A pure-witness result routes `NO_CHANGE` / `EXISTING_UNCHANGED`. The reducer requires `NO_CHANGE` to carry witnesses only (no nodes, relations, gaps or compiled graph), and checks every witness on every route for existence, currency and non-staleness where the event lands, never re-judging sameness. The prompt's same-thing rule names `unchanged_object_refs` explicitly; the policy id and version are unchanged, because no graph model was certified under the earlier prompt. | §8, §13 |
| **Prompt runtime-v2** (contract clarification, no new semantics) | The first live graph certification (`xai/grok-4.7`, commit `65c6b4e8`, NOT CERTIFIED 4/24, prompt `265a7fbd…`, `runtime-v1`) exposed three prompt-expression defects over semantics the domain already had. (1) `unchanged_object_refs` is scoped to "an existing object that itself already represents a meaning the supplied claims assert"; a parent Intent, a served Goal, an unaffected or conflicting NonGoal, or context is never a witness. (2) PARAPHRASE, CORRECTION (use the existing `REPLACES_STALE`, never a parallel node), NEW and UNRESOLVED are distinguished explicitly. (3) The existing `RETIRING_TARGET_REFERENCED` law is stated to the model. No validator, domain law or schema changed. Following the adapters' written rule that a prompt change is a deliberate version bump, the policy version becomes `intent-graph-synthesis-runtime-v2`, and the orchestrator fence follows. Slice 4.1's no-bump exception no longer applies, because `runtime-v1` is now durable authorship on committed exam ledgers. The policy id stays `intent-synthesis.graph-v1` (graph contract unchanged). New prompt `e8e1763db2c7f7df1496406082d0e0014b4de0f0ecea80f6e1e535951a97e605`. The v1 evidence is immutable, and no certification crosses the change. | §22 |
| **Answer-schema contract** (Option A: schema correctness, provider wire adaptation, schema binding) | Astra's first graph run produced no answer: OpenAI refused the graph-answer schema before inference (`400 invalid_json_schema`, "'oneOf' is not permitted"), so no model was examined. Inspection then showed the generated schema did not describe what Pydantic accepts. **Hierarchy:** (1) Pydantic domain semantics are the source of truth; (2) the canonical graph-answer schema (`IntentGraphDraftPayload.model_json_schema()`, pinned `GRAPH_ANSWER_SCHEMA_SHA256`) is a faithful provider-neutral description of them; (3) a provider wire schema is a deterministic representation of the canonical one, stricter where the provider requires and sound (wire-valid ⇒ Pydantic-valid); (4) every returned answer is validated by Pydantic again. **Canonical corrections (JSON Schema only; validators, defaults, construction and accepted values unchanged, pinned by a Pydantic accept/reject fingerprint over 16,438 instances):** `namespace` is required at every `GraphRef` union branch (`{"$ref": …, "required": ["namespace"]}`; standalone refs keep their default); `kind` is required in every node state; `relation_type` admits only the 4 proposable relations; INTENT and ASSUMPTION admit only `disposition` NEW (omittable) with `replaces` null (omittable); each of the 7 replaceable kinds is two states, NEW (target null/omitted) and REPLACES_STALE (`disposition` and `replaces` required, target an `ExistingObjectRef`), 16 leaf states in all. Canonical hash `83215cee…` → `6b64d274…`. **Wire:** xAI transmits the canonical schema unchanged (`xai-sdk.chat-parse.model-json-schema.v1`). OpenAI transmits `compile_openai_wire_schema` output (`foundry.openai-structured-outputs.v1`, hash `7b825730…`): `oneOf`→`anyOf` only where exclusivity is proven structurally, the SDK's own strict form reproduced byte-exactly, and a fail-closed audit; `discriminator` metadata is carried unchanged pending the compatibility probe. A schema with no `oneOf` (Slice-1) is sent byte-identically to before. The adapter sends `text.format` and validates the answer itself with the SDK's own rule (`model_validate_json` on the first final-answer text); nothing is repaired. **Binding:** graph certification record format `ie3-graph-certification.v2` binds canonical schema hash, provider wire schema hash and wire compiler as well as provider, model, task, policy and prompt; a record without `record_format` is historical v1, gains no fabricated schema identity and can never bind a schema-bound identity. New evidence goes to `intent_graph_synthesis_schema_bound`; both earlier namespaces are immutable. **Versioning:** policy id and version stay `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v2`. The written bump rule concerns the prompt, which is unchanged (`e8e1763d…`); the schema change adds no semantics, and the schema contract is versioned by its own hashes and compiler identity, which no earlier certificate can match. | §22 |
| **Node-kind ontology** (runtime-v3; exam v3) | Auditing Grok's exam-v2 case A (2026-09-28) found a system semantic gap. IE2 §2 separates `REQUIREMENT` ("required obligation") from `CONSTRAINT` ("hard boundary on the solution space"), with different closure consequences (§15: a PROPOSED Constraint blocks, a PROPOSED Requirement does not). Yet the runtime-v2 prompt named both kinds and defined neither, the facet meanings never reached the schema, case A's claim carried only a bare value (the port forbids evidence content, so the normative sentence never reached the model), and the exam scored the distinction while never requiring a CONSTRAINT. **Invariant (recorded in IE2 §2):** the kind follows what a meaning governs (delivered behaviour → REQUIREMENT; the space of admissible solutions → CONSTRAINT), never modal wording. **Model-facing change:** the prompt defines every legal kind, states the REQUIREMENT-or-CONSTRAINT rule and gives every facet's relaxation meaning, with no exam content. Schema, wire and compiler are unchanged. Under the written rule that a prompt change is a deliberate bump, the policy version becomes `intent-graph-synthesis-runtime-v3`, and the orchestrator fence follows. The policy id stays `intent-synthesis.graph-v1`; the new prompt is `504b6080…`. **Representation:** no production change. The request's claim (subject, facet, predicate, value) is the semantic unit and can carry a whole proposition; the exam's case A claim did not, and exam v3 states it. **Exam v3** (`72ca1102…`): case A's claim is a proposition, and a new case I pairs a delivered-behaviour obligation (REQUIREMENT) with a data-hosting boundary (CONSTRAINT) in the same modality ("must … within"), so neither keyword matching nor always-REQUIREMENT can pass. Exam v2 is frozen (`exam_manifests/ie3-graph-exam-v2.json`, `813f04d4…`) and recorded in `SUPERSEDED_GRAPH_EXAMS`. **Standing:** `graph_certificate_standing` reads a record against the current contract. Astra's exam-v2 PASS is SUPERSEDED (true history, no current authority). Grok's exam-v2 run is diagnostic NOT CERTIFIED and, per the supersession entry, not a precedent on REQUIREMENT versus CONSTRAINT. | §15, §22 |
| **Exam v4** (case F; runtime-v3 unchanged) | A read-only audit (2026-09-28) found that exam v3's case F had the same class of defect earlier fixed in A and C. The restated claim was the bare value "thirty days after purchase" under the default facet "How long may a refund take?", beside a request-window `REQ-stale` whose basis link is not visible. A refund-duration reading (NEW, with the stale object left alone) was therefore lawful under runtime-v3 but scored FAIL, as Grok's v3 F-2 was. The scorer also accepted any gap at all. **Exam v4** (`2c676e55…`): case F's address (subject "Refund request window", facet "Within how many days of purchase are refund requests accepted?", predicate `refund_request_window`) and both claim values state the refund-request window, so REQ-stale and the claim visibly mean the same thing. The scorer now requires exactly one same-kind REPLACES_STALE of REQ-stale, grounded on the restatement and durably retiring it, with no gap (none remains to be raised) and no parallel node. As with corrected case C, an unambiguous change is not a gap. Prompt, policy (`runtime-v3`, `504b6080…`), schemas and compilers are unchanged, and only case F's world and code moved (a test proves this). Exam v3 is frozen (`exam_manifests/ie3-graph-exam-v3.json`, `72ca1102…`) and recorded in `SUPERSEDED_GRAPH_EXAMS` (`not_a_precedent_for = STALE_OBJECT_UNDER_AN_AMBIGUOUS_CLAIM`). Astra's v3 PASS is now SUPERSEDED; Grok's v3 record stays NOT_CERTIFIED (F-1 a genuine failure; F-2 a lawful reading of v3). | §22 |

The remaining rules (G14 replacement by kind, G15 the NonGoal/conflict boundary, G17 the context
DTO) are approved with the checkpoint.

| Q | Resolution | Where applied |
|---|---|---|
| **Q1 confidence** | Optional confidence, but **only for the nine IE3 kinds**, following Requirement's narrow D12 precedent. `SemanticBase.confidence` stays required globally. `None` means no numeric confidence was asserted; runtime never invents 0, 0.5 or 1 for a human choice. This needs a narrow `semantic.py` change in Slice 1. | §8, §23, §24, §26, §28 |
| **Q2 scope** | Runtime-derived from the graph synthesis run scope. The model never chooses node scope. | §8, §14 |
| **Q3 missing-need diagnostic** | An untrusted diagnostic enum `PROJECT_CHOICE` / `EXTERNAL_FACT` / `UNDETERMINED`. It is not a `GapResolutionRoute` and never executes work. IE2.4 `LAWFUL_ROUTES` stays authoritative, and any future route selection must still pass `assert_route_allowed()`. | §19, §20 |
| **Q4 EXTERNAL_MANDATE** | The IE2.1 provenance rule stays unchanged. An external mandate is **not** declared permanently non-canonical: external provenance, a lawful evidential basis and authenticated human authority may eventually establish one. graph-v1 cannot represent that path cleanly, so it is deferred rather than IE2 being weakened. | §13 |
| **Q5 assumption risk** | AI_INFERRED and RESEARCH_DERIVED Assumptions receive `HIGH` at runtime, and the model cannot lower the authoritative risk level. An authenticated, explicit human risk level is preserved; otherwise `HIGH`. | §6, §8 |
| **Q6 graph caps** | graph-v1: 32 nodes, 128 relations, 16 gaps. Exceeding a cap is refusal, never truncation. | §16, §21, §26 |

A prerequisite IE2 correctness repair must land before IE3 applies any durable graph (§30).

---

## 1. Repository facts discovered

| # | Fact | Evidence |
|---|---|---|
| F1 | `EventStore.append(event, expected_sequence)` is single-event. There is no batch append in the port or either adapter; Postgres wraps one event per transaction. | `ports/event_store.py`; `adapters/postgres/event_store.py`; bridge spec §10.6 |
| F2 | `INTENT_OBJECT_SYNTHESIZED` is **Requirement-only in the reducer**, whatever the envelope admits. `_validate_object` requires `obj.id == identity.object_id("REQ")` and `isinstance(obj, Requirement)`, and requires relations to be **exactly** one `DERIVED_FROM` per basis claim. `IntentObjectPayload.basis_claim_ids` has `min_length=1`. So the event cannot carry a Goal, a basis-free object, or any `SERVES`. | `application/reducer.py::_validate_object`; `domain/events.py::IntentObjectPayload` |
| F3 | The decision surface is typed to one Requirement proposal: `IntentSynthesisDecidedPayload.proposal`, `IntentSynthesisDecisionRecord.proposal: RequirementSynthesisProposal`, and `IntentSynthesisState.decisions` keyed by `proposal_instance_id`. | `domain/intent_synthesis.py`; `domain/intent_synthesis_state.py` |
| F4 | `SynthesisIdentity(project_id, synthesis_run_id, model_proposal_id)` is **per proposal**. `object_id(prefix)` and `event_id(step)` hang off one `proposal_instance_id`. There is no graph-level identity. | `domain/intent_synthesis.py` |
| F5 | `synthesis_digest(*parts)` is canonical-JSON full SHA-256 (no boundary forgery, no truncation). It is general-purpose. | same |
| F6 | Slice-1 lifecycle: `DECIDED` is appended at `expected_sequence = N` (C12). The effect `SYNTHESIZED` follows as a separate append, so there is one legal *incomplete* window. Recovery (T9) reads the durable record and never calls a provider. The `DuplicateEventError` backstop and a bounded 3-attempt concurrency retry apply, and `_refresh_for_retry` revalidates against a fresh request. | `application/intent_synthesis.py` |
| F7 | Retirement rides inside the effect event (C7). `RetirementRecord`s live in `intent_synthesis.retirements` and are the only input to `handoff_v2.validly_reconciled`. | `reducer.py`; `domain/handoff_v2.py` |
| F8 | v2 readiness reads the Slice-1 incomplete set through `scoped_incomplete_synthesis_proposal_ids`, rebuilding scope from `record.proposal.basis_claim_ids`. Any new lifecycle with an incomplete window would need its own readiness integration. | `domain/handoff_v2.py` |
| F9 | `SemanticGovernor.record_intent_object` admits **one** object per event. It checks relation legality, cycles, basis and relevance **against current state only**. A relation to a not-yet-admitted same-batch object raises `UnresolvedTargetError`. Its event ids come from a `uuid4` factory. | `application/semantic_governance.py`; `domain/relation_legality.py` |
| F10 | Basis law: an object with no `DERIVED_FROM` yields **no** basis defect, except canonical `EVIDENCE_BOUND`/`EXTERNAL_MANDATE` Constraints. Direct authoritative choice is therefore already lawful (R37). Lawful evidential terminals are `CANONICAL` `SemanticClaim`s only (R42). Slice-1's `INFERRED` basis claims cannot ground canonical intent. | `domain/basis.py`; IE2.2 spec §4–§5a |
| F11 | Relevance: an explicit object-local `SERVES` path to exactly one current canonical Intent applicable to the scope. At the seam it is checked for `CANONICAL` candidates only; readiness evaluates the same law. | `domain/relevance.py` |
| F12 | Legality matrix: `DERIVED_FROM` goes normative → {Claim, Evidence, Constraint, Goal, Outcome, Requirement, Decision}. `SERVES` goes normative−Intent → {Goal, Outcome, Intent}. `EXCLUDES` goes NonGoal → {Goal, Outcome, Requirement, Constraint}. `AFFECTS` goes {Preference, Assumption} → normative. Assumption may be the source of `AFFECTS` only. Relations undefined in the matrix fail closed. | `domain/relation_legality.py` |
| F13 | Relations are **object-local on the source**, and admission creates but never revises. An existing NonGoal therefore can never gain an `EXCLUDES` to a new object. Closure's `EXCLUDED_BY_NON_GOAL` reads only the NonGoal's own relations. | `domain/closure.py`; `record_intent_object` |
| F14 | *(code reading)* Staleness roots are inactive judgment ids plus `issue_versions`. `SemanticClaim`s are a separate plane. Slice-1 writes claim-basis `DerivationEdge`s with parent = `claim.created_by_judgment_id`, which propagates staleness. `INTENT_OBJECT_ADMITTED` writes parent = the relation target (the claim id), which **does not** propagate claim supersession. | `domain/derivation.py::stale_object_ids`; `reducer.py` **Repaired by R105–R107 (§30): both conventions now propagate supersession.** |
| F15 | `SemanticBase.confidence` is a required `float`. Only `Requirement` is widened to `float \| None` (D12). The only reader of object confidence is the Slice-1 reducer's equality binding. | `domain/semantic.py`; grep |
| F16 | Requirement `materiality`, `requires_metric` and `requires_verification` are runtime-owned. Slice-1 pins them to `LOW` / `False` / `False` (D3/D4 open). | `application/intent_synthesis.py::_build_requirement` |
| F17 | Closure blocks on **any** current non-canonical `Constraint` (`NON_CANONICAL_OBLIGATION`). It also blocks on any current `Assumption` with `risk_level ∈ {HIGH, CRITICAL}` unless a resolved or waived gap names it (`UNCONTROLLED_HIGH_RISK_ASSUMPTION`). Both apply at every authority. | `domain/closure.py` |
| F18 | Slice-1 result rule C24 is proposals XOR gaps. Model gaps must be `AMBIGUITY` and blocking. `IntentSynthesisGap` carries explicit `scope`, and nullable `materiality`/`risk`/`confidence`. | `application/intent_synthesis.py`; `domain/intent_synthesis_gap.py` |
| F19 | `KnownIntentObject` exposes statement text, basis claim ids and loci only. It has no relations, facet, risk level, roots or open gaps. It spans `INTENT_BEARING_SEMANTIC_KINDS` (including `CONTRACT`). It is bounded by `KNOWN_INTENT_OBJECT_THRESHOLD` (200) and `MAX_KNOWN_INTENT_CONTEXT_CHARS` (131 072). `IntentSynthesisRequest.basis` has `min_length=1`. | `ports/intent_synthesizer.py`; `application/intent_synthesis_context.py` |
| F20 | Pinned runtime identity: `intent-synthesis.slice1` / `intent-synthesis-runtime-v1`. The fingerprint's `policy_version` is durable authorship. | `adapters/intent_synthesis/model_runtime.py` |
| F21 | `intelligence/proposals.py` variants belong to the v1 experiment vocabulary. They make confidence required and carry model-supplied `source_event_ids` and `affected_proposal_ids`. | `intelligence/proposals.py` |
| F22 | `gap_applies`: an `IntentSynthesisGap` with explicit scope is filtered by it, and an unknown `affected_object_ids` entry applies conservatively. `LAWFUL_ROUTES[MISSING_INFORMATION] = {DERIVE, RESEARCH, ASK_HUMAN, PRESERVE_WAIT}`. No route is stored on a gap (R70/R71). | `domain/gap_scope.py`; `domain/gap_resolution.py` |
| F23 | IE2.1 refuses a canonical `EXTERNAL_MANDATE` whose provenance is `SourceKind.HUMAN`. Slice-1 `HUMAN_STATED` objects carry `SourceKind.HUMAN` provenance. | `semantic_governance.py::_require_facet`; `_build_requirement` |
| F24 | `DETERMINISTIC_NORMALIZATION` origin raises; it is unsupported. | `_reject_malformed_authorship` |
| F25 | `assert_no_cycle_introduced(state, obj)` walks `SERVES` and `DERIVED_FROM`, one object at a time, against state. | `domain/graph_cycles.py` |

## 2. Frozen/certified compatibility boundary

The following are **frozen**. IE3 adds beside them and never widens them:

- **Types:** `IntentSynthesisProposal`, `RequirementSynthesisProposal`, `IntentSynthesisResult`, `IntentSynthesisPolicy`, `IntentSynthesisDecision`, `IntentSynthesisDecisionRecord`, `SynthesisIdentity` (semantics and digest tags), `IntentDisposition`, `route_intent_synthesis`, `INTENT_BEARING_SEMANTIC_KINDS`.
- **Events:** `INTENT_SYNTHESIS_DECIDED`, `INTENT_OBJECT_SYNTHESIZED` and `INTENT_SYNTHESIS_INVALIDATED`, with their payloads, envelope validation and reducer arms.
- **State and readiness:** `IntentSynthesisState` (type and validators), `incomplete_proposal_ids`, and the `handoff_v2` Slice-1 incomplete gate.
- **Application:** `ports/intent_synthesizer.py` (the request, `KnownIntentObject`, `LocusBasis`, `BasisClaim`, the protocol) and `application/intent_synthesis_context.py`.
- **Orchestration and runtime:** `application/intent_synthesis.py` (T8/T9), `adapters/intent_synthesis/model_runtime.py`, `SYSTEM_INSTRUCTION` and its SHA, and the policy id/version.
- **Certification:** `tests/certification/**` including recorded evidence.

**An additive path is possible, so no mutation of the frozen path is proposed.** IE3 needs:

- new domain modules;
- one new event type with its own payload;
- one new `IntentState` plane, defaulting to empty so old streams replay byte-identically;
- one new reducer arm;
- one write into the **existing** retirement tuple, which keeps a single reconciliation law (§17);
- a narrow widening of `confidence` to `float | None` on the eight IE3 kinds that do not already
  have it (Q1). This is additive for parsing: every historical event carries a number, and a
  number still validates.

None of these changes the parse, reduction or meaning of any existing event.

## 3. Reusable primitives

| Class | Primitive |
|---|---|
| **A** unchanged | `synthesis_digest`; `replacement_scope_covers`; `validate_synthesis_actor`; `SynthesisOrigin`; `IntentSynthesisRoute` (APPLY/NO_CHANGE/REQUIRE_HUMAN/REJECT); `IntentSynthesisGap`; `LEGAL_RELATION_TARGETS`, `resolve_target_kind`, `validate_relations`; `assert_no_cycle_introduced`; `basis_defects`/`assert_lawful_basis`/`basis_decision_terminals`; `canonical_roots`/`relevant_ids`/`assert_relevant`; `assumption_impact`; `gap_resolution_plan`/`LAWFUL_ROUTES`; `completeness`; `gap_applies`; `scope_applies`; `object_is_current`; `covering_authority_record`; `derive_view().stale_ids`; `RetirementRecord`; `LocusBasis`/`BasisClaim` (embedded unchanged in the new request); `ReasonerFingerprint`; `EventStore` port; `ConstraintFacet`; the non-IE3 `SemanticObject` classes; the per-claim origin rule of `_derive_origin`, re-expressed per node |
| **B** additive extension | the eight IE3 kind classes other than Requirement (optional `confidence`, Q1); `IntentState` (+ graph-decision plane); `EventType`/`EVENT_PAYLOAD_TYPES`/`EventEnvelope` validation/`_reject_project_mismatch` (+ one type); `reduce_event` (+ one arm); `intent_synthesis.retirements` (IE3 appends to it, §17); the mutation runner (+ `--table`, §24); `ModelRuntime` (reused by a new adapter) |

## 4. Requirement-specific or unsafe primitives

| Class | Primitive | Why |
|---|---|---|
| **C** Requirement-specific | `SynthesisIdentity.object_id("REQ")`, `_build_requirement`, `_validate_object`, `IntentObjectPayload`, `_SLICE_1_MATERIALITY`, `_runtime_scope` (basis-only), `KnownIntentObject.materiality`, the `relates_to_object_id` disposition matrix | F2, F4, F16, F19 |
| **D** frozen | all of §2 | certification |
| **E** unsafe for IE3 | `INTENT_BEARING_SEMANTIC_KINDS` as ontology | Contains `CONTRACT`; it is a compatibility set (IE2.2 §4a). |
| **E** | `intelligence/proposals.SemanticProposal` / `GapProposal` | Model-owned event ids and proposal cross-refs (F21) |
| **E** | a `record_intent_object` loop over a graph | Not atomic; same-batch refs cannot resolve; uuid ids (F9) |
| ~~**E**~~ **A** (since R105–R107) | the `INTENT_OBJECT_ADMITTED` claim-parent edge convention | Was unsafe before the §30 repair (F14): claim supersession never reached such edges. After R105–R107 it propagates exactly as the judgment-parent convention does, and IE3 adopts it (R108, §16). |
| **E** | `REQUIREMENT_SUPERSEDED` | Requirement-only; writes no `RetirementRecord`, so v2 cannot treat it as reconciliation |
| **E** | C24 XOR | Forbids an honest partial graph (§19) |
| **E** | `SemanticGovernor._append` | Random ids; non-deterministic recovery |

## 5. Exact IE3 target-kind set

`IE3_GRAPH_NODE_KINDS` has **9 kinds**. It is written out and never derived from another set.

| Kind | Ruling | Reason |
|---|---|---|
| INTENT | **in** | The root. Without it a scope with no root can never become relevance-complete. |
| GOAL | **in** | The relevance spine. |
| OUTCOME | **in** | A legal `SERVES` target and a relevance-bearing kind. |
| REQUIREMENT | **in** | The Slice-1 capability, generalised. |
| CONSTRAINT | **in** | Requires `facet`. Note F17: every non-canonical one blocks closure. |
| NON_GOAL | **in** | The only `EXCLUDES` source. It is relevance-bearing. |
| PREFERENCE | **in** | Relevance-bearing. Never an obligation (IE2.5). |
| DECISION | **in** | An authoritative terminal. Consequences derive from it. |
| ASSUMPTION | **in** (§6) | A premise node. It carries `AFFECTS` only. |
| METRIC, VERIFICATION_OBLIGATION | out (§7) | Quality slice. |
| CONTRACT | out | Legacy. IE2.2 gives it no semantics. |
| ACTOR | out | Context, not intended state (Slice-1 D1). |
| CLAIM, EVIDENCE | out | These belong to the v2 semantic plane via judgments. Synthesis minting them would be basis laundering. |
| UNKNOWN, QUESTION | out | Expressed as gaps: one gap plane, routed by IE2.4. |
| CONFLICT | out | Expressed as a `CONTRADICTION` gap. A model-minted `Conflict` would be a closure blocker created from prose with no route. |
| RISK | out | Epistemic; no IE2 law consumes it. The closure-relevant risk signal lives on Assumption. |
| AUTHORITY_RECORD, AMENDMENT | out | Human governance acts. A model must never produce them. |

## 6. Assumption inclusion ruling

**Ruling (G1): option A. Assumption is part of the same IE3 graph, as a premise node.**

- An Assumption's only lawful dependency edge is `AFFECTS` → intended-state object (F12). When the dependent object is new, that edge needs a same-batch local reference. A separate extraction step could only run after the graph is durable.
- That leaves a window in which a Requirement exists without its declared premise. IE2.3 blast radius then under-reports, and a material premise silently disappears. That is exactly the failure the constitution forbids.
- Graph synthesis is also where premises are recognised ("this requirement assumes X"). Splitting that from meaning synthesis would ask a second pass to rediscover what the first one saw.

Constraints that keep "Assumption is not basis" structural:

- it has no `DERIVED_FROM` and no `SERVES`; legality already forbids both;
- it must carry **at least one `AFFECTS`**, because a premise that affects nothing is noise;
- it is never a `DERIVED_FROM` target (IE2.2b refuses it anywhere in a chain);
- questionable support is expressed by an `UNSUPPORTED_ASSUMPTION` gap anchored to the local Assumption. IE2.4 then plans RESEARCH/ASK_HUMAN/PRESERVE_WAIT with the IE2.3 radius, all unchanged.

`risk_level` is a closure lever (F17). Under **Q5** the model cannot hold that lever:

- a non-human (AI_INFERRED or RESEARCH_DERIVED) Assumption is compiled with `risk_level = HIGH`,
  whatever the model proposed;
- a human-authored Assumption keeps the risk level the authenticated human explicitly stated. If
  the human stated none, it is `HIGH`.

So every AI-recognised premise blocks closure (`UNCONTROLLED_HIGH_RISK_ASSUMPTION`) until a gap
naming it is resolved or waived. That is the intended cost.

## 7. Metric/VerificationObligation ruling

**Ruling (G2): both are out of IE3. They belong in a later quality slice.**

- `requires_metric` and `requires_verification` are pinned `False` (F16). Deciding when they turn on is open decision D4.
- `MEASURED_BY`/`VERIFIED_BY` targets are measurement design, which sits partly at the architecture layer.
- No IE2 law consumes them.
- IE3 v1 may also not emit `MISSING_SUCCESS_METRIC`/`MISSING_VERIFICATION_OBLIGATION` gaps. This keeps the quality slice whole rather than half-started.

## 8. Typed proposal variants and field ownership

There is no generic proposal (G3). There is one discriminated union on `kind`. Every node proposal shares:

```
local_id:     LocalNodeRef                      model-local handle, unique per result
disposition:  GraphNodeDisposition              NEW | REPLACES_STALE   (new enum; EXISTING_UNCHANGED is
                                                 not a node — it is an ExistingObjectRef in
                                                 IntentGraphSynthesisResult.unchanged_object_refs,
                                                 R111)
replaces:     ExistingObjectRef | None          set iff REPLACES_STALE
proposal_rationale: str (min 1)                 why the model proposes it; kept in the decision
                                                 record, never on the object
confidence:   float | None                      Q1: None = no number was asserted; carried to the
                                                 object exactly, never replaced by a default
```

| Variant | Kind-specific fields (all MODEL-PROPOSED) |
|---|---|
| `IntentNodeProposal` | `mission` |
| `GoalNodeProposal` / `OutcomeNodeProposal` / `NonGoalNodeProposal` / `PreferenceNodeProposal` | `statement` |
| `RequirementNodeProposal` | `statement` |
| `ConstraintNodeProposal` | `statement`, `facet: ConstraintFacet` (required) |
| `DecisionNodeProposal` | `statement`, `decision_rationale` (the project's reason for the choice) |
| `AssumptionNodeProposal` | `statement`, `proposed_risk_level: RiskLevel \| None` (Q5: authoritative only for an authenticated human author; otherwise recorded in the decision and the object gets `HIGH`) |

**Field ownership** (`extra="forbid"` enforces the absence of every non-model field):

| Owner | Fields |
|---|---|
| **MODEL-PROPOSED** | text fields; `facet`; `decision_rationale`; local ids; typed relation proposals; disposition and replacement ref; gap proposals and their untrusted `missing_need` diagnostic (Q3); `confidence`, optional (Q1); `proposed_risk_level`, which is non-authoritative for non-human authors (Q5) |
| **RUNTIME-DERIVED** | `id`, `project_id`, `kind` (by variant), `revision=1`, `lifecycle=ACTIVE`, `created_at = decided_at`, `scope = (run scope,)` (Q2), `provenance`, compiled `relations`, Requirement `materiality=LOW`/`requires_metric=False`/`requires_verification=False` (inherits the Slice-1 pin; D3/D4 stay open), per-node `origin`, the authoritative Assumption `risk_level` for non-human authors (`HIGH`, Q5), identities, derivation edges, retirement records, event ids |
| **HUMAN/GOVERNANCE-OWNED** | `authority` (routing from origin + live `AuthorityRecord`); authenticated authorship (`human_actor_id`); an explicitly stated human Assumption risk level (Q5); `AuthorityRecord`s; policy material sets; resolution or waiver of gaps; any later approval of a `REQUIRE_HUMAN` graph |

The model owns none of the following: authority, lifecycle, durable object ids, event ids, instance ids, `created_at`, provenance, authorship or revision.

Authority is computed from **origin only**. It never reads model name, tier, provider, certification or confidence. A stronger model therefore cannot acquire stronger authority (G4).

## 9. Local/existing/basis reference model

Typed namespaces form a discriminated union. URI strings are never parsed:

```
LocalNodeRef      {namespace: "local",    local_id:  ^[a-z][a-z0-9_-]{0,63}$}
ExistingObjectRef {namespace: "existing", object_id: str}   ∈ request.known_objects ids
BasisClaimRef     {namespace: "basis",    claim_id:  str}   ∈ request basis live claim ids
GraphRef = LocalNodeRef | ExistingObjectRef | BasisClaimRef
```

Rules (G5):

- **R-ref-1:** node `local_id`s are unique. Gap ids use a separate `LocalGapId` namespace, and the two may not collide.
- **R-ref-2:** every `LocalNodeRef` resolves to a node in the same result.
- **R-ref-3:** an `ExistingObjectRef` resolves only to an object **shown** in the request, so the model cannot cite invisible state.
- **R-ref-4:** a `BasisClaimRef` resolves only to a claim shown in the request basis.
- **R-ref-5:** node proposals have no id field, so the model cannot supply a durable id for a new node.
- **R-ref-6:** ambiguity is impossible by construction, because the namespace is explicit. The compiled state still re-runs `resolve_target_kind`, whose ambiguity check is kept as defence in depth.

## 10. Relation proposal contract

Relations are graph-level typed edges, `GraphRelationProposal(source: LocalNodeRef, relation_type, target: GraphRef)`.

**The source is always a `LocalNodeRef` (G6).** No proposal may add a relation to an existing object, because relations are object-local and admission never revises (F13).

| Relation | Legal source kinds (local) | Legal target |
|---|---|---|
| `DERIVED_FROM` | all 8 normative kinds | `BasisClaimRef`; or local/existing of kind Constraint, Goal, Outcome, Requirement, Decision |
| `SERVES` | Goal, Outcome, Requirement, Constraint, NonGoal, Preference, Decision | local/existing Goal, Outcome, Intent |
| `EXCLUDES` | NonGoal | local/existing Goal, Outcome, Requirement, Constraint |
| `AFFECTS` | Assumption | local/existing of the 8 normative kinds |

The following are **not proposable** in IE3. No IE2 law consumes them, and new undecided semantics are refused: `CONSTRAINS`, `CONFLICTS_WITH`, `MEASURED_BY`, `VERIFIED_BY`, `SUPPORTS`, `CHALLENGES`, `REQUIRES`, `RELATES_TO`, and `SUPERSEDES` (replacement is the disposition, not a relation). `Preference AFFECTS` is legal in IE2 but no law reads it, so it is also excluded.

Further rules:

- no duplicate `(source, type, target)`;
- no self-edge;
- no `SERVES`/`DERIVED_FROM` cycle across graph ∪ current state;
- a `REPLACES_STALE` node's `replaces` target may not also be a relation target in the same graph. It is retiring and would be a dead edge.

Legality is checked twice:

1. structurally, against the kinds of local nodes plus request-visible existing kinds;
2. after compilation, by the **unchanged** `validate_relations` over the hypothetical post-graph state (§25).

## 11. Basis construction law

`DERIVED_FROM` means "why justified", and only that. `GroundingPolicy` is a pure table keyed by **(origin class, kind, facet)** (G7):

| Kind | HUMAN_STATED | Non-human (AI_INFERRED, RESEARCH_DERIVED) |
|---|---|---|
| Intent | direct (basis optional) | **evidence-required** |
| Goal, Outcome, NonGoal, Preference, Decision | direct (optional) | **evidence-required** |
| Requirement | direct **or** derived (R37) | **evidence-required** |
| Constraint `PROJECT_BOUNDARY` | direct (optional) | **evidence-required** |
| Constraint `EVIDENCE_BOUND` / `EXTERNAL_MANDATE` | **evidence-required** | **evidence-required** |
| Assumption | basis forbidden | basis forbidden |

**Evidence-required, structurally:** at least one `DERIVED_FROM` path, through local nodes and visible existing objects' `DERIVED_FROM`, must reach a **terminal**. A terminal is a `BasisClaimRef` or an `ExistingObjectRef` to a Decision. A local Decision is **not** a terminal for a non-human node. Otherwise the model would ground its own proposal on its own invented choice (**R101**). The same ruling means a model-created Decision can never lend authority to another new node; authority is assigned per node from origin alone (§13).

**Direct choice** means no basis is forced. We do not fabricate claims to satisfy graph shape (§8 of the brief). Declared basis must still be lawful (R37).

A non-human author may **not** originate a project choice without evidence. A missing choice becomes a gap, which feeds IE4 `ASK_HUMAN` (G8). This is how "direct authoritative normative choice" stays distinct from "evidence-derived intended state".

For nodes assigned `CANONICAL`, the unchanged `assert_lawful_basis` runs over the hypothetical state. For example, an `INFERRED` basis claim is refused per R42, and a human who wants canonical intent must state it directly or cite a canonical claim.

Laws preserved:

- basis never lends authority (R49);
- human-authored evidence never makes model text `HUMAN_STATED` (origin follows the author, per C9/I22);
- certification never grants authority.

## 12. Relevance construction law

`SERVES` means "why relevant", and only that. It is authority-blind and structural (G9):

- every relevance-bearing node (the IE2.2 §4a set) carries at least one `SERVES`;
- the `SERVES` closure over local nodes ∪ visible current existing objects must reach an Intent, either a local Intent node or a visible current existing Intent;
- Intent nodes number **at most one** per graph. A local Intent is refused when the request shows a current Intent applicable to the run scope, because that would mint a second root (`MULTIPLE_CANONICAL_ROOTS`);
- an Assumption carries no `SERVES`, and at least one `AFFECTS` (§6).

Relevance is **never** inferred from shared batch, scope, claim, text or subject. For example, a Requirement and an Intent in one batch with no `SERVES` is refused.

For `CANONICAL` nodes, the unchanged `assert_relevant` runs over the hypothetical state. It proves a canonical path, so a canonical node serving a `PROPOSED` Goal is refused, which is correct. `DERIVED_FROM` never satisfies relevance, and `SERVES` never satisfies grounding (G10).

## 13. Authority law by origin and kind

The same law applies to every IE3 kind. Authority comes from origin; basis and model are never consulted (G11).

| Origin | Maximum authority | Condition |
|---|---|---|
| HUMAN_STATED | CANONICAL | A live `AuthorityRecord` covers the node's scope. Otherwise the whole graph routes `REQUIRE_HUMAN` / `AUTHORITY_UNRESOLVED`. `EXTERNAL_MANDATE` is the exception described below (Q4). |
| DETERMINISTIC_NORMALIZATION | — | Unsupported; fails closed (F24). |
| AI_INFERRED | PROPOSED | always |
| RESEARCH_DERIVED | PROPOSED | always. Research supplies evidence, never authority. |

Can each of the following AI_INFERRED kinds become CANONICAL automatically? **No**, in every case:

- Intent
- Goal
- NonGoal
- Preference
- ProjectDecision
- Constraint

Under **R102**, none of them becomes canonical except through a separate lawful human authority act.

**External mandates (Q4).** The IE2.1 provenance rule is unchanged: a canonical `EXTERNAL_MANDATE`
may not carry `SourceKind.HUMAN` provenance. An external mandate is **not** declared permanently
non-canonical. External provenance, a lawful evidential basis and authenticated human authority may
eventually establish one. graph-v1 cannot represent that combination cleanly, because a
HUMAN_STATED node's provenance is the human and deriving provenance from basis evidence is the
laundering C9/I22 forbids. The path is therefore **deferred**, not simulated:

- in graph-v1, a HUMAN_STATED `EXTERNAL_MANDATE` node routes the whole graph to `REQUIRE_HUMAN`;
- a non-human `EXTERNAL_MANDATE` node is PROPOSED, as for every non-human node;
- IE2 is not weakened to make either case pass.

Anti-invention stays the first governance rule. A non-human node with an assigned `CANONICAL` routes the **whole graph** to `REJECT` / `AUTHORITY_INVENTION`. As in Slice-1, this stage is callable on its own as a negative control.

- **Origin per node:** for a human author, every node is `HUMAN_STATED`. For a non-human author, a node is `RESEARCH_DERIVED` iff every `BasisClaimRef` it cites directly is all-`RESEARCH`, and otherwise `AI_INFERRED`. This is Slice-1's rule, applied per node.
- **Graph route:** the graph is the unit of decision. Precedence is `REJECT` > `REQUIRE_HUMAN` > `APPLY`. A result with no nodes and no gaps but at least one `unchanged_object_refs` witness is `NO_CHANGE` / `EXISTING_UNCHANGED` (R111), resolved before `APPLY`. Beside new nodes or gaps, witnesses are audit-only and do not change the route. An entirely empty result is refused, and relations alone never make a result meaningful.
- **Consequences:** under F17, every PROPOSED Constraint blocks closure until a human canonicalises or rejects it. Every PROPOSED Requirement stays non-blocking under the LOW pin.

## 14. Identity derivation

`IntentGraphIdentity(project_id, synthesis_run_id)` is new. It is **not** a stretched `SynthesisIdentity`, whose semantics are per-proposal (F4). All values are `synthesis_digest`, with domain tags distinct from Slice-1 (G12):

```
graph_instance_id   = "GSY-" + d("ie3.graph", project_id, synthesis_run_id)
node_instance_id(ℓ) = "GSN-" + d("ie3.node",  graph_instance_id, ℓ)
object_id(k, ℓ)     = PREFIX[k] + "-" + d("ie3.object", graph_instance_id, ℓ, k)
gap_id(g)           = "GAP-" + d("ie3.gap",   graph_instance_id, g)
event_id(step)      = "EVT-" + d("ie3.event", graph_instance_id, step)      step ∈ {"DECIDED"}
PREFIX = {INTENT:INT, GOAL:GOAL, OUTCOME:OUT, REQUIREMENT:REQ, CONSTRAINT:CON,
          NON_GOAL:NG, PREFERENCE:PREF, DECISION:DEC, ASSUMPTION:ASM}   # convention, never identity
```

- **The run** is runtime-created, with one provider call per run. A fresh provider answer always gets a new run id.
- **Retries:** a `ConcurrencyError` retry before anything is durable reuses the same run id and ids.
- **Mapping:** local → durable is a pure function of `(identity, ℓ, kind)`. It is reconstructable from the durable record, and is also persisted in the compiled delta and checked by the reducer.
- **Replay** mints nothing. The provider cannot choose any id.
- **Retries** cannot duplicate: the same graph maps to the same event id, and `DuplicateEventError` then means "adopt the durable decision".
- **Scope (Q2):** every node's scope is `(request.scope,)`, the graph synthesis run scope, derived at runtime. The model never chooses node scope. Basis claim address scopes do **not** set node scope; they already bound what the request may show. This deliberately differs from Slice-1 I6, which stays unchanged for Slice-1. A project-wide node therefore needs a project-wide run mode, which graph-v1 does not define.

## 15. Atomicity alternatives

| Criterion | **A** graph decision + per-object events | **B** graph decision + one application event | **C** one decide-and-apply event |
|---|---|---|---|
| crash consistency | ✗ objects 1..k are visible truth after a crash at k | ✓ one incomplete window | ✓ nothing-or-everything |
| partial graph visibility | ✗ every reader (closure, relevance, basis, package) would need masking | ✓ none | ✓ none |
| same-batch refs | ✗ each event must reduce alone. Topological order fixes dangling edges but **not** visibility. | ✓ | ✓ |
| append-only replay | ✓ | ✓ | ✓ |
| concurrent writers | per-event retries on a half-applied graph | decision at N; the effect revalidated later | decision **and** effect computed at N and appended at `expected_sequence = N`. A `ConcurrencyError` means nothing durable, so it refreshes and recomputes. |
| deterministic identity | ✓ | ✓ | ✓ |
| retry idempotency | complex, per object | ✓ | ✓ `DuplicateEventError` means adopt |
| replacement/retirement | a window between replacement and retirement unless folded | ✓ folded | ✓ folded |
| duplicate application | per-object guards | applied marker | the decision *is* the application; its id is unique |
| provider-free recovery | needed, per object | needed (a T9 analogue) | **nothing to recover** |
| legal exit from every durable decision | needs invalidation per object | needs graph invalidation + readiness integration (F8) | trivially terminal at its own event |
| payload | small events | decision record + compiled delta across two events | one event, bounded by the graph caps (Q6) |

**A is rejected**: it creates visible partial truth.

**B works**, but it re-creates Slice-1's incomplete window, invalidation event and recovery path, and it needs new readiness wiring. It pays that cost for no benefit, because the effect is fully decidable at the same N as the decision.

## 16. Recommended atomicity/recovery design

**Approved (R103, G13): C, a single `INTENT_GRAPH_SYNTHESIS_DECIDED` event.** It decides and applies the validated graph in one durable transition. There is no separate incomplete decision/application window. It must not land before the §30 repair.

- **Payload** `IntentGraphSynthesisDecidedPayload`:
  - `graph_contract_version: Literal["ie3.graph-v1"]`;
  - `identity`;
  - `author`;
  - `result` (the whole typed graph result, so the proposal is always readable whatever the route);
  - `node_origins`;
  - `node_authorities`;
  - `decision` (route + bounded reasons);
  - `compiled: CompiledIntentGraph | None`, where `compiled` is set **iff** `route == APPLY`.
  `CompiledIntentGraph` holds `objects` (sorted by id), `local_to_object_id`, `retirements` (target, replacement, node instance), `gaps` (`IntentSynthesisGap`s) and `derivation_parents` per object.
- **Reducer** (new arm):
  - it requires the deterministic event id, and that the graph id has no durable decision yet;
  - it records the decision into a new `intent_graph_synthesis` plane;
  - if `APPLY`, it independently checks binding invariants as a **second body**, never the producer's compiler:
    - ids are re-derived from identity + local id + kind;
    - kinds, text, facet and risk equal the result nodes;
    - authority equals `node_authorities`;
    - `created_at` equals `occurred_at`;
    - revision 1 and `ACTIVE`;
    - relations equal the resolved proposal relations;
    - no object id already exists;
    - replacement preconditions hold (same as Slice-1's `_validate_replacement`);
  - it then applies objects, `DerivationEdge`s (R108: parent = the actual `DERIVED_FROM` target id: a claim id, an existing object id, or a resolved new object id), the retirements (→ the existing `intent_synthesis.retirements`), and the gaps into `state.gaps`, **in one transition**;
  - it never recompiles and never re-runs IE2 laws. Those are forward-only (IE2.1 law).
- **Runtime flow**, all at state N:
  1. compile the request;
  2. make one provider call;
  3. validate the whole result against the request;
  4. assign origin and authority, and route;
  5. if `APPLY`, compile and run the IE2 laws on the hypothetical state;
  6. append at `expected_sequence = N`.

  On `ConcurrencyError`, it replays, recompiles the request and revalidates the *same* result, as `_refresh_for_retry` does. If that fails, it raises `SnapshotChanged` and requires a new run. It makes at most 3 attempts. On `DuplicateEventError`, it adopts the durable decision.
- **Caps (Q6):** graph-v1 allows at most 32 nodes, 128 relations and 16 gaps. Exceeding any cap refuses the whole result; nothing is ever truncated. The reducer re-checks the caps as part of its second body.
- **Derivation parents (R108):** IE3 uses the actual `DERIVED_FROM` target ids as derivation
  parents: a claim id, an existing object id or a resolved new object id. Claim-id edges are safe
  under R105–R107, so no translation to `claim.created_by_judgment_id` happens. Slice-1's
  judgment-id edge remains frozen legacy behaviour. `CompiledIntentGraph.derivation_parents`
  carries, per object, exactly the sorted unique `DERIVED_FROM` targets, and the reducer re-checks
  that equality before writing one edge per parent.
- **As built (Slice 2):**
  - The payload carries `node_assignments` (one `GraphNodeAssignment(local_id, origin,
    authority)` per node) in place of separate origin and authority maps.
  - It also carries `run_scope`: every node's scope is `(run_scope,)` (Q2), and the reducer cannot
    bind scope without it.
  - The shape law (`APPLY` iff compiled, compiled identity, one assignment per node) is one shared
    function, `validate_graph_decision_shape`. The payload, the record and the reducer all call it.
  - The reducer checks every binding before it builds the record, so a union field's re-validation
    is never the first refusal.
- **Versioning:** unknown `graph_contract_version` values are refused at parse. A future `ie3.graph-v2` adds a Literal arm, and v1 events replay forever.
- **Precedent:** IE2.1 `IntentObjectAdmissionPayload` ("everything the admission durably means travels in this one event") and Slice-1 C1/C7, carried to their conclusion. Slice-1 itself remains untouched.

## 17. Replacement semantics by kind

The general rule (G14) reuses Slice-1 and the reducer rules. `REPLACES_STALE` requires a target that is:

- visible and current;
- of the **same kind**;
- in `stale_ids`;
- not already retired;
- replaced with scope coverage (C21);
- `CANONICAL` only if the replacement is also `CANONICAL` (C11).

Otherwise the node is refused, or, for C11, the graph routes `REQUIRE_HUMAN`. Retirement writes a `RetirementRecord` into the **existing** `intent_synthesis.retirements`, with `proposal_instance_id = node_instance_id`. That keeps `validly_reconciled` as the one reconciliation law, and two nodes may not replace one target.

| Kind | Fit | Rule |
|---|---|---|
| Requirement, Constraint | fits | allowed |
| Goal, Outcome | fits, but retiring breaks every inbound `SERVES` | allowed. Children become visible `ORPHANED_CANONICAL_OBJECT` blockers until they are replaced or re-served in the same or a later graph. That is honest and never silent. |
| Decision | fits, but inbound consequences go `DEAD_BASIS` | allowed; same honesty argument |
| NonGoal, Preference | stale only when evidence-derived | allowed when stale |
| **Intent** | **does not fit.** Every `SERVES` in scope would orphan, and a root swap is a mission change. | **refused.** It needs a later amendment workflow (D8). |
| **Assumption** | **does not fit.** It has no basis, so it is never stale, and IE2.3 has no "false" state (R68). | **refused** |

Direct-choice objects with no basis are never stale, so they cannot be replaced through synthesis. Non-synthesis retirement remains D8.

## 18. NonGoal/conflict handling

**Boundary (G15):** recognising a semantic contradiction from prose happens **only** in the synthesizer. It is recorded as a **model-authored `CONTRADICTION` gap**, blocking, anchored to the existing NonGoal (`affected_object_ids`) and to any claims involved. The conflicting candidate is **not** proposed.

The reasons:

- the existing NonGoal cannot gain `EXCLUDES` (F13);
- a PROPOSED conflicting Requirement would sit silently, because closure only blocks canonical × canonical;
- the gap is routed to {RESEARCH, ASK_HUMAN, RECONCILE}.

The rest of the graph may still be proposed (§19). A new NonGoal in the same graph may carry `EXCLUDES` to local or existing targets, and closure's existing canonical × canonical rule then applies.

The deterministic IE2 layer continues to claim only **explicit `EXCLUDES`**. Nothing downstream may present the gap as a deterministic finding. Its authorship stays in the decision record, and the certification exam (a later slice) must include NonGoal-conflict cases, because the deterministic layer cannot catch a model that misses one.

## 19. Partial-graph + gap ruling

**Approved (R104, G16): a safe partial graph plus explicit anchored gaps, in one atomic transition.** Whole-result XOR is not retained.

**R104 invariant.** Every persisted node must be structurally valid on its own, using only:

- other nodes persisted in the **same** transition;
- visible existing objects;
- visible basis claims.

No reference, required basis path or required relevance path may point at, or pass through, a
region the result leaves unresolved. That includes a node the model omitted, a node refused by
validation, or anything expressed only as a gap. A gap may **anchor to** a persisted node (for
example `UNSUPPORTED_ASSUMPTION` on a persisted Assumption), but a gap is never a stand-in for a
missing node.

Validation is whole-result: one invalid node refuses the result. It is never silently dropped to
make the rest fit.

- **Shape:** a result may carry nodes, gaps, or both. An empty result is refused.
- **Gap kinds:** `IE3_MODEL_GAP_KINDS` = {AMBIGUITY, MISSING_INFORMATION, CONTRADICTION, UNSUPPORTED_ASSUMPTION, UNDERSPECIFIED_SCOPE}. All others are refused. Some are deterministic runtime facts, some belong to the quality slice, and one is authority.
- **Model gaps are always blocking in v1.** The model does not get to declare its own uncertainty harmless. Waiver is human, and `PRESERVE_WAIT` keeps blocking (R81).
- **Anchors** are typed `GraphRef`s:
  - local nodes resolve to durable ids in `affected_object_ids`;
  - existing refs go in as-is;
  - claims go to `affected_claim_ids`;
  - `scope = (request.scope,)`.

  Gap ids are deterministic (§14). `source_event_ids` and `affected_proposal_ids` do not exist.
- **Missing-need diagnostic (Q3):** each gap proposal carries
  `missing_need: MissingNeed ∈ {PROJECT_CHOICE, EXTERNAL_FACT, UNDETERMINED}`, persisted on an
  `IntentSynthesisGap` subtype. It is **untrusted model diagnosis**:
  - it is not a `GapResolutionRoute`;
  - it never executes work;
  - it never changes `LAWFUL_ROUTES` or `gap_resolution_plan`;
  - any future route selection must still pass `assert_route_allowed()`.
- **Structure stays whole:** every included node must satisfy §10–§12. A node whose basis or relevance cannot be established must be **left out**, with a gap stating why. For example, "no known Goal this requirement serves" is `MISSING_INFORMATION`.
- **No masquerade:** nodes and gaps land in one event (§16). A crash can therefore never leave a complete-looking graph without its gaps, and closure blocks the scope via `OPEN_BLOCKING_GAP` until each gap is resolved or waived.

## 20. IE4/IE5 compatibility

IE3 produces graph + honest unresolved work, and nothing else. IE2.4 plans every IE3 gap unchanged. IE3 anchors (object ids, claim ids, scope) are what the IE4/IE5 context compilers will need.

| Unresolved condition | IE3 gap kind | Lawful routes (unchanged) |
|---|---|---|
| missing project choice | MISSING_INFORMATION / AMBIGUITY / UNDERSPECIFIED_SCOPE | includes ASK_HUMAN; UNDERSPECIFIED_SCOPE is ASK_HUMAN only |
| missing externally knowable fact | MISSING_INFORMATION | includes RESEARCH |
| presently unknowable | MISSING_INFORMATION | includes PRESERVE_WAIT |
| contradictory existing state | CONTRADICTION | includes RECONCILE |
| premise needs support | UNSUPPORTED_ASSUMPTION | RESEARCH / ASK_HUMAN / PRESERVE_WAIT, with the IE2.3 radius |

The kind alone cannot tell "project choice" from "external fact" for MISSING_INFORMATION. Under **Q3**, IE3 records the model's untrusted `missing_need` (`PROJECT_CHOICE` / `EXTERNAL_FACT` / `UNDETERMINED`) at the point it is known. IE4/IE5 may read it as a hint. `LAWFUL_ROUTES` remains authoritative, and `assert_route_allowed()` remains the only gate on a selected route.

## 21. New IE3 context DTO

The new, versioned, request-only DTO lives in `ports/intent_graph_synthesizer.py`. The frozen Slice-1 request is untouched (G17).

```
IntentGraphSynthesisRequest
  project_id, scope
  basis: tuple[LocusBasis, ...]                 # reused unchanged; may be empty
  known_objects: tuple[KnownGraphObject, ...]   # IE3 kinds only; current (stale flagged)
  root_intent_ids: tuple[str, ...]              # canonical_roots(state, scope)
  open_gaps: tuple[KnownOpenGap, ...]           # OPEN and gap_applies; avoids duplicate gaps
  allowed_node_kinds: frozenset[SemanticKind]   # = IE3_GRAPH_NODE_KINDS (runtime-pinned)
  allowed_gap_kinds: frozenset[GapKind]         # = IE3_MODEL_GAP_KINDS
  limits: GraphLimits                           # 32 nodes / 128 relations / 16 gaps (Q6)
  (validator: basis or known_objects is non-empty)

KnownGraphObject
  object_id, kind, authority, is_stale, scope, text
  facet: ConstraintFacet | None                 # Constraint only
  risk_level: RiskLevel | None                  # Assumption only
  relations: tuple[KnownRelation, ...]          # DERIVED_FROM/SERVES/EXCLUDES/AFFECTS only,
                                                # targets filtered to shown ids or basis claims
  basis_claim_ids, basis_locus_ids
KnownOpenGap
  gap_id, kind, description, blocking, affected_object_ids
```

- It is bounded by the Slice-1 thresholds (`KNOWN_INTENT_OBJECT_THRESHOLD`, `MAX_KNOWN_INTENT_CONTEXT_CHARS`). Exceeding them is a deterministic blocker gap with no provider call.
- It is deterministic, with everything sorted by id.
- It is scope-aware, via `scope_applies` and `gap_applies`.
- It is provider-neutral.
- Decision rationale stays hidden, as in Slice-1.
- It is compiled fresh per call and never persisted.

## 22. Policy/prompt/certification versioning

| Surface | Slice-1 (frozen) | IE3 |
|---|---|---|
| policy id | `intent-synthesis.slice1` | `intent-synthesis.graph-v1` |
| policy version | `intent-synthesis-runtime-v1` | `intent-graph-synthesis-runtime-v1` |
| prompt | `SYSTEM_INSTRUCTION` + SHA | new instruction + its own SHA-256 |
| adapter | `adapters/intent_synthesis/model_runtime.py` | `adapters/intent_graph_synthesis/model_runtime.py` |
| certification | `tests/certification/*intent_synthesis*` + evidence | a new exam and evidence tree |
| event contract | Slice-1 events | `graph_contract_version = "ie3.graph-v1"` |

The name `…runtime-v2` is deliberately avoided: it would read as a successor to Slice-1's runtime rather than a separate capability.

The graph orchestrator refuses a synthesizer whose fingerprint `policy_version` is not the graph policy. Grok/OpenAI Slice-1 certifications stay valid for Requirement synthesis only. There is no live provider work before the certification slice.

## 23. Exact new files proposed

**Slice 1** (domain only):

- `src/foundry/domain/intent_graph.py`: constants (`IE3_GRAPH_NODE_KINDS`, `IE3_MODEL_GAP_KINDS`, `PREFIX`, caps 32/128/16), refs, 9 node variants, `GraphRelationProposal`, `GraphGapProposal` (with `missing_need`), `MissingNeed`, `IntentGraphSynthesisResult`, `GraphNodeDisposition`, `IntentGraphIdentity`
- `src/foundry/domain/intent_graph_validation.py`: `GraphVisibility` (visible existing id→kind/current/stale/scope, basis claim ids, root ids, run scope), `validate_intent_graph(result, visibility, *, author_is_human)`, `GroundingPolicy`
- `src/foundry/domain/intent_graph_compiler.py`: `compile_intent_graph(...) -> CompiledIntentGraph`, `hypothetical_state(state, compiled)`, `assert_compiled_graph_lawful(state, compiled)` (the unchanged IE2 laws)
- `tests/unit/_ie3_fixtures.py`, `tests/unit/test_ie3_graph_types.py`, `tests/unit/test_ie3_graph_validation.py`, `tests/unit/test_ie3_graph_compiler.py`
- `scripts/ie3_mutants.py`

**Later slices** (listed, not approved for Slice 1):

- `ports/intent_graph_synthesizer.py`
- `application/intent_graph_synthesis_context.py`
- `domain/intent_graph_routing.py`
- `domain/intent_graph_state.py`
- `application/intent_graph_synthesis.py`
- `adapters/intent_graph_synthesis/model_runtime.py`
- the graph certification exam and evidence

## 24. Exact existing files requiring modification

- **Slice 1:**
  - `src/foundry/domain/semantic.py` (Q1): `confidence: float | None = None` on `Intent`, `Goal`, `Outcome`, `Constraint`, `NonGoal`, `ProjectDecision`, `Preference` and `Assumption`, following the D12 pattern on `Requirement` (already optional). Each gets its own documented Liskov exception. `SemanticBase.confidence` and every non-IE3 kind stay required. This is a **shared** module, so the IE2 mutation gate is mandatory (§28).
  - `scripts/run_ie2_mutations.py`: an additive `--table {ie2,ie3}` flag, default `ie2`, so the IE2 run stays byte-identical in behaviour.

  No other existing `src/` file changes in Slice 1.
- **Prerequisite, before any durable graph application:** the §30 IE2 staleness repair. Its files are decided by its own RED-first task, not here.
- **Later slices:**
  - `domain/events.py`: the type, payload, envelope check and project-mismatch arm;
  - `domain/state.py`: the new plane, defaulting to empty;
  - `application/reducer.py`: the new arm.

  `handoff_v2.py` needs **no** change under R103, because there is no incomplete state. Retirements reuse the existing plane.

## 25. First implementation slice

**IE3 Slice 1 is typed graph + validation + deterministic compilation, plus the narrow Q1 `semantic.py` widening that lets all nine kinds compile to real `SemanticObject`s. It has no ledger, events, reducer, port, adapter or prompt.**

It proves that:

- a typed multi-kind graph exists;
- local refs compile to deterministic durable ids that are independent of node order;
- invalid graphs fail closed;
- the model cannot supply durable ids;
- basis and relevance stay separate;
- the **unchanged** IE2 laws (`validate_relations`, `assert_no_cycle_introduced`, and, for canonical nodes, `assert_lawful_basis` and `assert_relevant`) accept the compiled result on a hypothetical post-graph `IntentState`, and refuse it where IE2 would.

Compiler inputs are all runtime-owned and passed explicitly:

- `identity`;
- `decided_at`;
- `decision_event_id`;
- per-node origin and authority;
- the run scope;
- the author.

## 26. RED tests for first slice

- **Semantic model (Q1):**
  - each of the eight widened kinds accepts `confidence=None`, and it round-trips as `None`, distinct from `0.0`;
  - `SemanticBase` and every non-IE3 kind (Claim, Evidence, Unknown, Question, Conflict, Risk, Metric, Contract, VerificationObligation, AuthorityRecord, Amendment, Actor) still refuse a missing confidence;
  - historical events with numeric confidence replay byte-identically.
- **Types:**
  - each of the 9 variants constructs;
  - a missing `facet`, `risk_level` or `decision_rationale` fails;
  - the forbidden fields (`id`, `object_id`, `authority`, `scope`, `provenance`, `created_at`, `lifecycle`, `revision`, `relations`, `materiality`, `source_event_ids`) are each refused on every variant;
  - a `kind` outside the 9 (METRIC, CONTRACT, ACTOR, CLAIM, …) is refused;
  - a ref given as a URI string is refused;
  - an invalid `local_id` pattern is refused;
  - NEW with `replaces` is refused, and REPLACES_STALE without it is refused;
  - duplicate node, gap and cross-namespace local ids are refused;
  - an empty result is refused;
  - the caps are enforced at exactly 32/128/16 (33 nodes, 129 relations and 17 gaps are each refused, never truncated);
  - `missing_need` accepts only `PROJECT_CHOICE` / `EXTERNAL_FACT` / `UNDETERMINED`, and is not a `GapResolutionRoute` value.
- **Validation:**
  - unresolved local refs are refused;
  - invisible existing refs and basis refs are refused;
  - a legality matrix (parametrised legal and illegal pairs, including Intent as `SERVES` source, `DERIVED_FROM` → Intent, Assumption `DERIVED_FROM`/`SERVES`, Requirement `EXCLUDES`, and non-proposable relation types);
  - duplicate edges and self-edges are refused;
  - `SERVES`/`DERIVED_FROM` cycles are refused, both in-graph and via existing objects;
  - relevance reach: none (refused), via local Goal→local Intent (accepted), via existing Goal→existing Intent (accepted), same-batch-no-`SERVES` (refused);
  - a second root is refused;
  - Assumption without `AFFECTS` is refused;
  - human grounding: Goal direct (accepted), `EVIDENCE_BOUND`/`EXTERNAL_MANDATE` with no basis (refused), `PROJECT_BOUNDARY` direct (accepted);
  - non-human grounding: Goal direct (refused), Requirement→local Decision only (refused), →existing Decision (accepted), →claim (accepted), →local Goal→claim (accepted);
  - separation: `DERIVED_FROM` to a Goal does not count as relevance, and `SERVES` does not count as grounding;
  - gap-kind fence, gap `blocking=False` refused, and gap anchors resolved;
  - R104: a relation, basis path or relevance path through a node absent from the result is refused, and a gap cannot substitute for the missing node.
- **Compiler:**
  - determinism, including under node permutation;
  - an id formula golden test;
  - ids change with run, project, local id and kind;
  - raw local id text never appears as an id;
  - refs are resolved to durable ids, and claim and existing ids are preserved;
  - runtime-owned fields (`created_at`, revision, lifecycle, provenance by origin, `source_event_ids`, Requirement LOW/False/False, authority = assigned);
  - confidence carried exactly, with `None` staying `None` and no default number invented (Q1);
  - every node's scope equals `(run scope,)`, including nodes citing claims with other address scopes (Q2);
  - a non-human Assumption compiles to `HIGH` whatever the model proposed, a human Assumption keeps an explicitly stated risk level, and a human Assumption with none compiles to `HIGH` (Q5);
  - the compiled graph passes the unchanged IE2 legality and cycle checks on the hypothetical state;
  - a canonical human graph passes basis and relevance when lawful, and fails with IE2 errors for an `INFERRED` basis claim and for serving a `PROPOSED` Goal;
  - the retirement plan and each violated precondition;
  - Intent and Assumption replacement refused, and double replacement refused;
  - a missing or extra authority assignment refused;
  - `CANONICAL` for a non-human origin refused as defence in depth;
  - the input state is unchanged.

## 27. Mutation controls for first slice

`scripts/ie3_mutants.py` has slice `ie3s1`. Each mutant must be killed:

1. drop the duplicate-local-id check
2. accept an unresolved local ref
3. accept an invisible existing ref
4. accept an invisible basis ref
5. drop `kind` from the object-id digest
6. drop `run_id` from the graph digest
7. use the raw local id as the object id
8. make the compiled order follow input order
9. skip the `SERVES` reachability check
10. count `DERIVED_FROM` toward relevance
11. count `SERVES` toward grounding
12. allow a second Intent root
13. drop the Assumption `AFFECTS ≥ 1` rule
14. treat a non-human Goal as direct-permitted
15. accept a local Decision as a non-human terminal
16. drop the evidence-required facets
17. skip the cycle check
18. skip the hypothetical-state IE2 law pass
19. drop the C11 check in the retirement plan
20. drop scope coverage in the retirement plan
21. permit Intent replacement
22. accept a non-blocking model gap
23. widen `IE3_MODEL_GAP_KINDS`
24. skip the caps, or truncate instead of refusing
25. allow the relation-target-is-retiring rule to pass
26. compile a non-human Assumption with the model's risk level instead of `HIGH`
27. default a human Assumption with no stated risk to anything but `HIGH`
28. derive node scope from basis claim addresses instead of the run scope
29. replace `confidence=None` with a number during compilation
30. make `SemanticBase.confidence` optional globally (a non-IE3 kind must still refuse `None`)
31. let a path through a node absent from the result satisfy basis or relevance (R104)

## 28. IE2 regression/mutation gates

Every IE3 slice runs the full suite (`uv run pytest -v`, `uv run ruff check .`, `uv run mypy src`), all 171 IE2 mutants killed (`uv run python scripts/run_ie2_mutations.py`), and all IE3 mutants killed.

Slice 1 modifies the shared `domain/semantic.py` (Q1), so the IE2 gate is **mandatory** for it: 171/171 killed, with no IE2 mutant re-anchored or removed.

Slices touching events, the reducer or state must additionally keep all of the following unchanged:

- Slice-1 certification (offline replay: `tests/certification/test_live_ledger_replay.py`, harness-neutrality);
- the `test_intent_synthesis_*` suite;
- event replay of historical streams;
- P4 (closure/package unaffected by IE2/IE3 readiness diagnostics);
- v1/v2 handoff semantics.

An IE2 law change requires explicit approval before any mutant is re-anchored or removed.

## 29. Architecture questions — resolved

All six questions raised at the checkpoint are resolved (§0); none remains open for Slice 1.

| Q | Original recommendation | Resolution | Difference from the recommendation |
|---|---|---|---|
| Q1 confidence | Option B, widen 8 kinds | Optional only for the nine IE3 kinds; `SemanticBase` stays required | As recommended. Confirmed narrow; a global widening is ruled out. |
| Q2 scope | Option A, claim scope if cited, else run scope | Run scope for **every** node; the model never chooses | Stricter: claim address scopes no longer set node scope. |
| Q3 missing need | Option B, 4-value diagnostic | `PROJECT_CHOICE` / `EXTERNAL_FACT` / `UNDETERMINED`; untrusted; never a route | Three values, not four. `EXISTING_CONTRADICTION` is already expressed by the `CONTRADICTION` gap kind. |
| Q4 external mandate | Option A, preserve the rule | Rule preserved; the canonical path is **deferred**, not declared impossible | The document no longer says IE3 can never canonicalise one. |
| Q5 assumption risk | Option B, pin non-human to HIGH | As recommended; human explicit risk preserved, otherwise HIGH | Adds the human-silent default of `HIGH`. |
| Q6 caps | Option A, 32/128/16 | As recommended; refusal, never truncation | — |

Open decisions carried forward unchanged and **not** reopened by IE3: D3 (materiality policy), D4
(materiality widening and `requires_metric`/`requires_verification`), D8 (non-synthesis retirement),
and a project-wide run mode (§14).

## 30. Prerequisite IE2 correctness repair: writer-dependent staleness

**Must land, RED-first, before IE3 begins durable graph application.** It is not fixed in this
design commit, and IE3 Slice 1, which writes nothing durable, does not depend on it.

**The defect** *(code reading, F14)*:

- `stale_object_ids` roots claim supersession at **inactive judgment ids** and **issue-version ids**.
  `SemanticClaim`s live in a separate plane and are not roots.
- The frozen Slice-1 writer (`INTENT_OBJECT_SYNTHESIZED`) records a claim basis as
  `DerivationEdge(parent_id = claim.created_by_judgment_id)`, so superseding that judgment makes
  the object stale. That is correct.
- The IE2.1 generic admission writer (`INTENT_OBJECT_ADMITTED`) records
  `DerivationEdge(parent_id = claim_id)`, taken from the object's `DERIVED_FROM` targets. A claim id
  is not a staleness root, so the same basis supersession leaves an admitted object **not** stale.

Staleness therefore depends on which writer recorded the object. That breaks "one law, every
writer" (R45–R51), and it would silently exempt IE2.1-admitted intent from the v2 stale-delivery
gate and from `REPLACES_STALE` reconciliation.

**Why it gates IE3:** under R103, IE3's reducer writes derivation edges. IE3 must be built on a
staleness law that does not depend on the writer, not on whichever convention it happens to copy.
§16 already specifies the propagating convention for IE3's own edges. The repair makes that choice
a law rather than an accident, and it covers the existing IE2.1 writer.

**Bounds for the repair task** (its design belongs to that task and is not decided here):

- RED first: a test showing an `INTENT_OBJECT_ADMITTED` object with a claim basis is not in
  `stale_ids` after its asserting judgment is superseded, while the equivalent Slice-1 object is.
- Historical events must replay unchanged. The event log is never rewritten; any fix is in how
  current state is projected, or in future writes, as that task rules.
- Slice-1 certification, `test_intent_synthesis_*`, P4 and v1/v2 handoff semantics are unchanged.
- The full suite and all 171 IE2 mutants are killed. If it adds a law, it adds a mutant for it.
- If the repair needs a choice between those options, it stops and raises an architecture question.

**As built (rulings R105–R107).** The repair is a current-view projection change in
`src/foundry/domain/derivation.py::stale_object_ids`, and nothing else:

```
inactive          = applied_judgment_ids − active_judgment_ids
stale_versions    = { v | issue_versions[v].created_by_judgment_id ∈ inactive }
stale_claim_roots = { c | claims[c].created_by_judgment_id ∈ inactive }        (R105)

stale_object_ids  = descendants(edges, inactive ∪ stale_versions)
                  ∪ descendants(edges, stale_claim_roots)
                  ∪ stale_versions
```

- Claim ids are traversal causes, never returned for being superseded (R106).
- They are walked as a separate root set, so the repair only ever adds descendants. It cannot
  drop an id the judgment/version walk already returned. A claim root itself is never returned.
- Both edge conventions, `parent = claim_id` and `parent = claim.created_by_judgment_id`, now
  propagate identically (R107). No event, payload, reducer arm or recorded edge changed, and
  history replays byte-identically.
- The RED tests run on the real `INTENT_OBJECT_ADMITTED` path in
  `tests/unit/test_ie2_claim_basis_staleness.py`.
- Three mutants in IE2 slice `ie2st` guard the law: claim roots removed, claim roots returned,
  and live claims rooted.

IE3's durable graph slice may therefore use either convention for claim-basis edges. It chose the
actual-target convention (R108, §16).
