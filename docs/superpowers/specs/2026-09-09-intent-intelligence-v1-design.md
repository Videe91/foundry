# Foundry Intent Intelligence v1 — Design Specification

## Status

Draft for architectural review

## Purpose

Intent Intelligence v1 is the first intelligent inspection station inside the Foundry software factory.

It is not an AI software engineer. It does not own factory truth.

Its purpose is:

```text
messy human / artifact input
        ↓
bounded preparation
        ↓
semantic normalization
        ↓
candidate meaning
        ↓
gap detection
        ↓
validated prediction
```

Example input:

```text
"Build a payment platform that never loses money and is very fast."
```

The station should be capable of identifying candidate meaning such as:

```text
Intent: build a payment platform
Candidate obligations: fast operation; money conservation
```

and potential gaps such as:

```text
"very fast" is ambiguous
"never loses money" needs precise semantics
jurisdiction missing
currency scope missing
latency metric missing
money-conservation verification missing
```

The station receives bounded material, analyzes it, and returns structured untrusted proposals. It has no authority to alter canonical Intent State.

## Relationship to Intent Engine v0

Intent Engine v0 is complete. It is the deterministic substrate:

```text
typed EventEnvelope
        ↓
append-only ledger
        ↓
deterministic replay
        ↓
IntentState
        ↓
Sufficient Intent Closure
        ↓
Canonical Intent Package
        ↓
sealed evaluation harness
```

v1 consumes v0 contracts. It does not replace them.

Authoritative v0 artifacts remain:

- semantic objects (`SemanticKind`, `SemanticBase`, concrete types)
- gaps and jobs
- event envelopes, reducers, replay
- closure and Canonical Intent Package
- `EvalInput` / `EvalExpectation` / `EvalPrediction` / `score_prediction`
- sealed `load_input` / `load_judge`

v1 adds a **proposal plane** beside that substrate. It does not add a second semantic kernel.

v0 Python remains a modular monolith. v1 stays inside that monolith behind ports. No microservices, Kubernetes, graph database, persistent super-agent, or provider coupling in the core.

## First Falsifiable Bet

Before model output may enter durable factory state, v1 must answer:

> Can structured Foundry intelligence discover important intent gaps from executor-visible input alone?

The first experiment is **stateless against the sealed evaluation harness**.

```text
EvalInput                  (load_input only)
   ↓
executor-visible events
   ↓
bounded IntelligenceInput
   ↓
IntentIntelligence
   ↓
untrusted IntentIntelligenceResult
   ↓
deterministic validation
   ↓
EvalPrediction
   ↓
hidden EvalExpectation     (load_judge only; never in the intelligence path)
   ↓
deterministic score_prediction
```

The judge never enters the intelligence path.

Only after this bet is empirically useful may a later milestone design authorized transitions from validated proposals into the event ledger. That later work is out of v1 scope.

## Architectural Boundary

This slice installs inspection. It does not install routing, research, context compilation, or canonical mutation.

In scope:

- bounded input compilation from `USER_STATED_INTENT` and `CLAIM_INFERRED`
- untrusted semantic and gap proposal contracts
- deterministic validation of structured worker output
- a provider-neutral executor port
- cheap deterministic detectors where they are trustworthy
- adapter from validated gap proposals to `EvalPrediction`
- evaluation-run evidence capture that is not canonical project state

Out of scope:

- Intelligence Router
- general Context Compiler
- research fabric / Evidence workers
- `PostgresEventStore.append` of model output
- reducer transitions that create canonical objects from proposals
- tool use, shell, filesystem, or database control by the worker
- holdout answer-key authoring
- one-shot baseline implementation (planned, not this design's code)

## Trust Model

The model is **compute**, not memory, not authority, and not canonical state.

```text
MODEL OUTPUT
    ↓
UNTRUSTED PROPOSAL
    ↓
DETERMINISTIC VALIDATION
    ↓
EvalPrediction / evaluation-run evidence
```

An authorized system transition into canonical Intent State is a **later** milestone. v1 must not implement it.

Consequences:

- The worker cannot emit a trusted `EventEnvelope`.
- The worker cannot emit a production `SemanticObject` or `Gap`.
- The worker cannot choose `project_id`.
- The worker cannot mint trusted provenance.
- The worker cannot set `authority`, `lifecycle`, `revision`, or `created_at`.
- The worker cannot append to the event ledger.
- Invalid structured output is a worker failure, not a repair job.

Generation cannot certify itself. Validation lives outside the model.

## Proposal Plane vs Canonical Plane

These planes are different types. Sharing a field name does not make them the same object.

| Plane | Answers | Types | Authority |
|-------|---------|-------|-----------|
| Proposal | What the worker thinks the input means | `SemanticProposal`, `GapProposal` | none |
| Canonical | What Foundry currently considers project state | `SemanticObject`, `Gap`, `IntentState` | event-derived, authorized |

A production `SemanticObject` carries factory metadata:

```text
id, project_id, revision, lifecycle, authority, provenance, created_at
```

A model that generates those fields would fabricate trusted metadata. That is forbidden.

Proposal identifiers (`proposal_id`, gap `fingerprint`) are local to one intelligence result. They are not object IDs, not event IDs, and not project identity. A later canonicalization milestone must define a new authorized mapping; v1 does not smuggle proposal IDs into the ledger.

## Design Alternatives

### A. One giant frontier-model call

Rejected as primary architecture.

One opaque call concentrates too much authority, resists decomposition, resists cost control, blocks future routing, and is harder to falsify. It also tempts the model to emit canonical-looking objects in one shot.

### B. Staged proposal pipeline

Recommended.

```text
input compile
→ deterministic observations where reliable
→ bounded model reasoning for remaining semantic ambiguity
→ untrusted structured proposals
→ deterministic validation
→ scoring now; authorized state transition later
```

This matches Law 4 (cheapest trustworthy executor) and Law 5 (generation cannot certify itself).

### C. Full router / research / swarm immediately

Rejected for now.

That is premature complexity before the first intelligence bet is proven. Routing, research, and general context compilation remain later subsystems.

## Input Compiler

The v1 compiler converts executor-visible typed `EventEnvelope`s into the minimum sufficient request for an intelligence worker.

Supported event types only:

```text
USER_STATED_INTENT
CLAIM_INFERRED
```

If an `EvalInput` contains any other `EventType`, compilation fails visibly. Silent dropping would hide unanalyzed material.

The compiler must never receive:

```text
EvalExpectation
judge.json
hidden fingerprints
EvalScore
```

Suggested types:

```python
class IntelligenceSource(FrozenModel):
    event_id: str
    event_type: Literal[EventType.USER_STATED_INTENT, EventType.CLAIM_INFERRED]
    content: str
    source_kind: SourceKind
    source_ref: str


class IntelligenceInput(FrozenModel):
    fixture_id: str | None
    project_id: str
    source_event_ids: tuple[str, ...]
    inputs: tuple[IntelligenceSource, ...]
```

Content rules:

- `USER_STATED_INTENT` → `content` is payload `text`; `source_kind=HUMAN`; `source_ref` is `actor_id`.
- `CLAIM_INFERRED` → `content` is the claim `statement`; `source_kind` and `source_ref` come from the claim's existing provenance on the executor-visible event.

The compiler **strips** canonical metadata before the worker sees the request:

- no `authority`
- no `lifecycle`
- no `revision`
- no `created_at`
- no full `SemanticObject`
- no `EventEnvelope.payload` union dump

`project_id` and `fixture_id` identify the request. They are not fields the worker may rewrite into proposals.

The worker receives only these compiled sources. No repository walk. No whole-project context. No artifact fetch beyond what the typed events already contain.

## Semantic Proposal Model

Provider-neutral, untrusted, extra-fields-forbidden.

Shared envelope:

```python
class SemanticProposalBase(FrozenModel):
    proposal_id: str
    kind: IntelligenceSemanticKind
    confidence: float   # 0.0 .. 1.0
    source_event_ids: tuple[str, ...]
```

`IntelligenceSemanticKind` is a closed subset of `SemanticKind`:

```text
INTENT
GOAL
OUTCOME
REQUIREMENT
CONSTRAINT
NON_GOAL
PREFERENCE
ASSUMPTION
CLAIM
UNKNOWN
QUESTION
```

Typed payloads (smallest family for the first experiment):

| Kind | Payload fields |
|------|----------------|
| INTENT | `mission: str` |
| GOAL | `statement: str` |
| OUTCOME | `statement: str` |
| REQUIREMENT | `statement: str` |
| CONSTRAINT | `statement: str` |
| NON_GOAL | `statement: str` |
| PREFERENCE | `statement: str` |
| ASSUMPTION | `statement: str`, `risk_level: RiskLevel` |
| CLAIM | `statement: str` |
| UNKNOWN | `question: str`, `blocking: bool` |
| QUESTION | `prompt: str` |

A discriminated union `SemanticProposal` uses `kind`.

Forbidden on every semantic proposal:

```text
authority
lifecycle
project_id
revision
created_at
provenance
event_type
event_id
```

Requirement proposals do **not** invent `Metric` or `VerificationObligation` objects. Missing measurement or proof appears as a **gap proposal**.

Not supported as model-created semantic proposals in v1:

```text
EVIDENCE
DECISION
AUTHORITY_RECORD
AMENDMENT
CONTRACT
METRIC
VERIFICATION_OBLIGATION
RISK
ACTOR
CONFLICT
```

`CONFLICT` is a canonical semantic object in v0. In v1 the worker proposes a `GapProposal` of kind `CONTRADICTION` rather than a canonical `Conflict`. `ACTOR` is omitted from the first experiment; it is not required to falsify the greenfield or brownfield bets.

`risk_level` on an Assumption proposal is an untrusted claim about risk, not canonical `Risk` state.

## Gap Proposal Model

Untrusted. Not a canonical `Gap`.

```python
class GapProposal(FrozenModel):
    fingerprint: str
    kind: GapKind
    description: str
    affected_proposal_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    blocking: bool
    confidence: float
```

Forbidden:

```text
id as a Gap id
project_id
status
resolution_event_id
materiality as canonical Gap.materiality
authority
provenance
```

`fingerprint` plus `kind` is the evaluation identity, identical to Task 7:

```text
(GapKind, fingerprint)
```

Wrong kind with the same fingerprint is not a hit.

The worker must not learn hidden judge fingerprints from the intelligence path. Development fixtures are known in repository history; they are not a scientifically clean final benchmark. See Development Fixtures vs Holdout Fixtures.

## Intelligence Result

```python
class IntelligenceUsage(FrozenModel):
    deterministic_jobs: int
    cheap_model_jobs: int
    standard_model_jobs: int
    strong_model_jobs: int
    frontier_model_jobs: int
    human_escalations: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    wall_clock_ms: int


class IntentIntelligenceResult(FrozenModel):
    semantic_proposals: tuple[SemanticProposal, ...]
    gap_proposals: tuple[GapProposal, ...]
    usage: IntelligenceUsage
```

Usage/cost evidence is separate from semantic meaning.

A free-form essay is not an operational output. Structured result is the worker contract. Extra fields are forbidden.

Empty semantic proposals with gap proposals can be valid (for example, two claims already supplied, only contradiction/authority gaps proposed). Empty gap proposals are valid structured output and will score as total miss against a non-empty judge; that is a quality failure, not a schema failure.

## Deterministic Validation

Validation is outside the model. Structurally invalid output fails visibly. No silent repair, no fingerprint rewriting, no ID synthesis, no dropping of unknown fields.

Required checks:

```text
all proposal_id values unique and non-empty
all gap fingerprints unique and non-empty
all source_event_ids exist in IntelligenceInput.source_event_ids
affected_proposal_ids reference existing proposal_id values
confidence ∈ [0.0, 1.0]
GapKind is a known v0 GapKind
SemanticKind / proposal kind is in the v1 allowed set
no authority field
no CANONICAL promotion
no worker-created trusted provenance
no worker-created event ID
no worker-created project identity
no judge fields (expected_gaps, forbidden_gap_fingerprints, fingerprints copied from judge)
no unexpected extra fields
```

Unknown `source_event_id` or `affected_proposal_id` is a worker failure.

Duplicate proposal IDs or duplicate fingerprints are a worker failure.

Provider/schema mismatch, empty model response, timeout, and budget exhaustion are worker failures, not partial results.

## Executor Port

Provider-neutral. Domain and application must not import vendor SDKs.

```python
class IntentIntelligence(Protocol):
    def analyze(self, request: IntelligenceInput) -> IntentIntelligenceResult: ...
```

The executor is supplied explicitly in v1. The Intelligence Router is not part of this slice.

A later router may choose:

```text
DETERMINISTIC
CHEAP_MODEL
STANDARD_MODEL
STRONG_MODEL
FRONTIER_MODEL
HUMAN
```

v1 keeps the port replaceable so routing can be inserted later without changing proposal contracts.

The first empirical adapter may use whichever capable model is chosen for experimentation. Foundry core depends on `IntentIntelligence`, not on a vendor.

```text
ARCHITECTURE QUESTION: first empirical provider adapter choice
```

Options include Grok, OpenAI, Anthropic, or another provider behind an adapter. Consequences: SDK dependency, payload shapes, and auth live only in `adapters/`; choosing one in the kernel would couple Foundry to a vendor. Do not resolve this in the design as a core dependency.

## Deterministic First-Pass Analysis

Cheapest trustworthy mechanism first.

```text
deterministic preparation
        ↓
deterministic observations/detectors where reliable
        ↓
bounded model reasoning for remaining semantic ambiguity
        ↓
validation
```

Reliable deterministic work includes:

- extracting typed `USER_STATED_INTENT` text and typed `CLAIM_INFERRED` statements
- detecting exact duplicate proposal statements after the worker returns, or exact duplicate source claim statements in the request
- detecting contradictory typed claims whose statements are already structured and incomparable as authorized intent (brownfield retry count 3 vs 5)
- refusing unsupported event types

Unreliable as a primary strategy:

- regex ontologies of English (`very fast`, `never loses money`)
- pretending a phrase list can replace semantic ambiguity analysis

Deterministic detectors may emit `GapProposal` values. Those proposals still pass through the same validator. They are not canonical gaps.

The fake/test executor used in Tasks 9A–9F must not contain the hidden judge fingerprints as hardcoded answers.

## Evaluation Adapter

Deterministic mapping after validation:

```text
IntentIntelligenceResult.gap_proposals
        ↓
EvalPrediction.gaps  as PredictedGap(fingerprint, kind)
```

Scoring identity remains:

```text
(GapKind, fingerprint)
```

Task 7 scorer and sealed loaders are unchanged.

`IntelligenceUsage` maps onto `EvalCost` field-for-field. No new composite score.

The adapter must not call `load_judge`. The evaluation runner that scores a fixture loads judge data only after the intelligence path has produced `EvalPrediction`.

## Greenfield Behavior

Fixture: `evals/fixtures/greenfield/payments_vague`

Intelligence receives only `input.json` via `load_input`.

Visible material is one `USER_STATED_INTENT`:

```text
Build a payment platform that never loses money and is very fast.
```

The hidden judge, which must not enter the intelligence path, currently expects:

```text
AMBIGUITY:never-loses-money
AMBIGUITY:very-fast
MISSING_INFORMATION:jurisdiction
MISSING_INFORMATION:currency-scope
MISSING_SUCCESS_METRIC:latency
MISSING_VERIFICATION_OBLIGATION:money-conservation
```

The worker may propose intents, candidate obligations, unknowns, questions, and gaps. It must not invent canonical metrics or verification obligations as semantic proposals. Those needs appear as gap kinds `MISSING_SUCCESS_METRIC` and `MISSING_VERIFICATION_OBLIGATION`.

This fixture is a **development fixture**. Implementers can see the judge in git history. It cannot by itself prove general intelligence quality.

## Brownfield Behavior

Fixture: `evals/fixtures/brownfield/retry_conflict`

Two executor-visible `CLAIM_INFERRED` events:

```text
Legacy retry count is 3.   (code: client.py)
Legacy retry count is 5.   (code: worker.py)
```

Both are observations, not intended behavior.

Intelligence must preserve both claims as proposals or as compiled sources and must be able to propose:

```text
CONTRADICTION:legacy-retry-count
MISSING_AUTHORITY:legacy-retry-count
```

without selecting 3 or 5 as truth.

This is mandatory. Conflicting implementation evidence does not decide intended behavior.

## Failure Handling

| Failure | Behavior |
|---------|----------|
| invalid structured output / extra fields / schema mismatch | visible worker failure; no repair |
| empty model response | visible worker failure |
| unknown `source_event_id` | visible worker failure |
| unknown `affected_proposal_id` | visible worker failure |
| duplicate `proposal_id` | visible worker failure |
| duplicate gap `fingerprint` | visible worker failure |
| provider failure | visible worker failure |
| timeout | visible worker failure |
| budget exhaustion | visible worker failure |

No retry/router policy in v1. No partial canonicalization of the valid subset of a mixed invalid result.

## Cost and Usage Evidence

`IntelligenceUsage` is evidence of compute spent, not evidence of meaning.

It must be captured with the evaluation run so a score can be reconstructed. It must not be written to `intent_events`.

Mapping to `EvalCost` is mechanical. Zero is valid. Negative values are invalid.

Strong intelligence cost must eventually scale with semantic difficulty, not repository size. v1's bounded compiler is the first enforcement of that law: the worker sees only the compiled sources, not the repo.

## Reproducibility

Do not claim model reasoning is deterministic.

Separate:

```text
deterministic substrate reproducibility   (v0; already proven)
model-output reproducibility              (not claimed)
evaluation-run reconstructability         (required in v1)
```

An evaluation run must persist, outside the canonical event ledger:

```text
IntelligenceInput
validated IntentIntelligenceResult
EvalPrediction
EvalScore
executor identity / adapter name
wall-clock and usage
```

That record reconstructs the score. It is not project memory and not canonical intent.

Exact on-disk layout of run records is an implementation detail for the evaluation-runner task, not a new source of factory truth.

## Provider Boundary

```text
domain/application/intelligence contracts  →  IntentIntelligence
adapters/*                                 →  vendor SDK, auth, wire format
```

Core must not import OpenAI, Anthropic, Grok, Gemini, or any other provider.

The first empirical adapter is chosen later and remains an adapter.

## Security Boundary

Model output is untrusted external input.

The intelligence worker, through this contract, must not control:

```text
database
canonical authority
event sequencing
project identity
judge access
filesystem access
shell execution
```

No tools in this slice.

v0 sealing remains an API boundary, not an OS sandbox. v1 does not add sandboxing. It preserves the existing `load_input` / `load_judge` split and adds a compiler that never accepts judge data.

## Baseline Comparison

Prepare for, do not implement in the design-only task, a controlled comparison:

```text
Structured Foundry pipeline
vs
one-shot model baseline
```

Both receive the **same executor-visible information** (`IntelligenceInput` / equivalent visible event content). Neither receives the judge.

Compare, without a weighted master score:

```text
critical gaps detected
critical gaps missed
false gaps
precision
recall
token usage
cost
wall-clock
strong/frontier calls
```

The one-shot baseline is a later task (9I). It must not become the production architecture (Alternative A remains rejected).

## Development Fixtures vs Holdout Fixtures

Existing fixtures (`payments_vague`, `retry_conflict`) are **development fixtures**.

Because they live in the repository, including judge files, they cannot prove general intelligence quality. They are useful for wiring, validation, and regression of the sealed path.

Before claiming intelligence superiority, a fresh sealed holdout fixture set must be created and frozen independently of the implementation worker.

This design task does **not** create holdout answer keys.

## v1 Non-Goals

v1 will not:

- mutate canonical Intent State
- append model output to PostgreSQL event streams
- emit `REQUIREMENT_CANONICALIZED`, `HUMAN_DECISION_RECORDED`, `SEMANTIC_OBJECT_RECORDED`, or any other production event from the worker
- build the Intelligence Router
- build the general Context Compiler
- run research, web retrieval, or Evidence workers
- select 3 or 5 as the intended retry count
- couple the kernel to a model vendor
- author holdout judges
- generate downstream production application code
- choose full system architecture
- sandbox the OS

## Future Integration into Canonical State

A later milestone may define authorized transitions:

```text
validated proposal
    ↓
human or policy authorization
    ↓
typed EventEnvelope
    ↓
append-only ledger
    ↓
canonical IntentState
```

That mapping is not designed here beyond this constraint: proposal-plane types remain distinct from canonical types, and authorization remains an explicit event, not a side effect of `analyze()`.

## Architecture Invariants

1. Models are compute, not memory.
2. Model output is untrusted.
3. Model output cannot become CANONICAL directly.
4. Model output cannot create trusted provenance.
5. Model output cannot choose project identity.
6. Model output cannot append directly to the event ledger.
7. Judge data never enters executor-visible intelligence input.
8. Whole-project context is forbidden by default.
9. Research remains subordinate and is not part of this slice.
10. Intelligence adapters are provider-neutral at the core boundary.
11. Invalid structured output fails visibly.
12. Structured proposals and canonical semantic objects are different types.
13. Existing v0 semantic/event contracts remain authoritative.
14. Existing development fixtures cannot by themselves prove general intelligence quality.
15. Strong intelligence cost must eventually scale with semantic difficulty, not repository size.
