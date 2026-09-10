# Foundry Intent Intelligence Comparative Exam — Design Specification

## Status

Draft for architectural review

Do not mark this document Approved until an architect reviews the committed text. No baseline code, holdout cases, holdout judges, or comparative execution may begin before that approval.

## Purpose

This document **pre-registers** the comparative exam for Foundry Intent Intelligence v1.

It freezes experimental rules **before** either the one-shot baseline or the fresh holdout suite exists.

It is an evaluation-subsystem design. It does not change production Intent Engine architecture, the `IntentIntelligence` port, proposal contracts, or the frozen Foundry worker.

## Research Question

> Does Foundry's bounded intent-analysis architecture produce better intent-gap analysis than a minimal one-shot use of the same frontier model on the same visible evidence?

The question is **not**:

```text
Is Grok better than Grok?
```

The comparison is between two **systems around the same underlying model**.

## Claim Boundary

The experiment does **not** isolate raw model intelligence.

It compares:

```text
Contestant A
Foundry Intent Intelligence
=
bounded compiler
+ Foundry worker instruction
+ semantic proposal schema
+ gap proposal schema
+ source grounding
+ deterministic validation
+ evaluation adaptation
+ same underlying frontier model
```

against:

```text
Contestant B
Minimal one-shot frontier baseline
=
same visible source evidence
+ minimal gap-analysis instruction
+ minimal evaluation-compatible structured output
+ same underlying frontier model
```

Any observed difference is attributable to the **system/contract around the model**, not to a different base model.

This distinction is mandatory in every later report.

## Why Task 9H Changed the Evaluation Design

Task 9H completed a development-fixture measurement. Two facts now constrain the comparative exam.

### Fact 1 — exact subject-key scoring is diagnostic, not sufficient

Greenfield produced semantically related concepts such as:

```text
money-loss-meaning
performance-target
```

while the development judge used:

```text
never-loses-money
very-fast
```

Task 7 correctly scored those as exact fingerprint mismatches.

Exact-string disagreement is **not** sufficient evidence of semantic failure.

Therefore:

> Task 7 exact scoring remains useful, but it cannot be the sole scientific measure of Intent Intelligence.

Do not modify Task 7.

Do not weaken its deterministic scorer.

Retain it as an **exact-identity diagnostic**.

### Fact 2 — gap inflation / minimality matters

The live worker sometimes represented one underlying unresolved issue through several related `GapKind` values.

The comparative exam must therefore measure not only:

```text
recall
precision
```

but also:

```text
semantic redundancy
minimality
unsupported gap generation
safety
```

Task 9H development results motivated this evaluation design. They must **not** be copied into the baseline prompt, holdout cases, holdout expected keys, or semantic grader answers.

## Contestant A — Frozen Foundry

Freeze Contestant A at:

```text
commit:
2d75532afbbe25913d5550483d3363f3df4cb754
```

The semantic worker itself is the xAI adapter introduced at:

```text
88d416162c3835af822798e2596d4eed7571f787
```

Frozen configuration:

```text
provider: xAI
model: grok-4.6
reasoning_effort: high
tools: none
research: none
persistent conversation: none
retries: none for semantic underperformance
```

The production system instruction in `src/foundry/adapters/intelligence/xai.py` at the freeze commit is frozen for the comparative exam.

Frozen Foundry behavior:

```text
compile_intelligence_input
→ XAIIntentIntelligence.analyze
→ validate_intelligence_result
→ to_eval_prediction
```

No tuning after this pre-registration.

In particular, do not modify after this freeze, and before the comparative holdout exam completes:

```text
compiler rules
system prompt
GapKind explanations
proposal contracts
subject_key instructions
validation rules
model
reasoning effort
```

Later fixes require declaring a new experimental version. They must not be back-ported into Contestant A mid-exam.

## Contestant B — One-Shot Baseline

The baseline must use:

```text
provider: xAI
model: grok-4.6
reasoning_effort: high
one model call per case
tools: none
research: none
persistent conversation: none
```

The baseline receives the **same semantic evidence** as Contestant A.

It receives only the same source records:

```text
event_id
event_type
content
source_kind
source_ref
```

It must **not** receive:

```text
fixture_id
project_id
judge data
expected concepts
expected fingerprints
Foundry canonical state
```

Source-record order must be the same as Contestant A.

The baseline is an evaluation experiment. It must not become the production architecture. Alternative A (one-shot kernel) remains rejected.

## Byte-Equivalent Visible Evidence

Where practical, both contestants should receive the same serialized source-record payload.

At minimum, future baseline-task tests must prove that the model-visible source records are semantically and field-for-field identical.

Intentional experimental treatment differences:

```text
system instruction
structured-output schema
```

Forbidden:

```text
differences in underlying evidence
```

## Baseline Output Contract

Pre-register a provider-neutral baseline evaluation contract.

Conceptually:

```python
class BaselineGap(FrozenModel):
    gap_id: str
    kind: GapKind
    subject_key: str
    description: str
    source_event_ids: tuple[str, ...]
    confidence: float


class BaselinePayload(FrozenModel):
    gaps: tuple[BaselineGap, ...]
```

This is an **evaluation-only baseline contract**.

It must not become:

```text
SemanticObject
Gap
IntentState
canonical project state
production Foundry intelligence schema
```

`subject_key` follows the same public lowercase-kebab-case convention only so exact Task 7 diagnostics can be computed for both contestants.

Semantic scoring must **not** depend solely on that key.

Exact field details may be hardened during architectural review. Do not broaden the baseline into the Foundry proposal architecture. Do not add semantic-proposal extraction to the baseline merely to mimic Foundry.

## Baseline Instruction

Freeze the semantic intent of the future baseline instruction.

It must be substantially equivalent to:

```text
You are performing a one-shot analysis of software-system intent.

Analyze only the supplied source records.

Identify the material unresolved gaps that would need clarification,
evidence, measurement, verification, or authority before implementation
could safely proceed.

Do not invent missing facts.

Do not perform external research.

When visible sources conflict, preserve the conflict rather than choosing
a winner unless the supplied evidence contains explicit authority.

Classify each identified gap using the supplied public GapKind definitions.

Use only source event IDs present in the input.

Use a lowercase kebab-case subject_key describing the minimal semantic
subject of each gap.

Return only the required structured baseline payload.
```

It may include the same **public GapKind definitions** used by Foundry so both contestants solve the same classification task.

It must **not** include:

```text
Foundry proposal-plane philosophy
canonical-state architecture
IntentIntelligencePayload
semantic proposal extraction
fixture-specific examples
hidden judge concepts
development expected fingerprints
```

Do not optimize this baseline prompt using Task 9H answers.

Do not train the baseline to emit:

```text
never-loses-money
money-loss-meaning
very-fast
performance-target
legacy-retry-count
```

Those strings are development evidence only.

## Fairness Controls

All of the following are frozen.

### Same model

```text
grok-4.6
```

for A and B.

### Same reasoning effort

```text
high
```

for A and B.

### Same evidence

Same source records, same order.

### Same number of semantic model calls

Exactly:

```text
1 call per contestant per holdout case
```

Foundry currently uses one intelligence call, so the baseline gets one call.

### No tools

Neither contestant gets:

```text
web
X search
code execution
files
research
external retrieval
```

### No persistent memory

Every case starts fresh. No conversation reuse across cases or contestants.

### No judge access

Neither contestant sees any holdout expectation before completing output.

### No semantic retry

A valid output with a poor score is final.

Infrastructure/provider failure may be retried only if no valid semantic payload was produced.

Record such retries separately from semantic results.

## What the Exam Measures

There is **no weighted master score**.

Report a vector of metrics across five layers.

## Layer 1 — Exact Deterministic Diagnostic

Retain existing Task 7 identity:

```text
(GapKind, fingerprint)
```

where:

```text
fingerprint = GapKind.value + ":" + subject_key
```

Report for both contestants where representable:

```text
critical gaps detected
critical gaps missed
false gaps
precision
recall
```

This metric remains exact and deterministic.

It is explicitly a:

```text
LEXICAL / TAXONOMIC EXACTNESS DIAGNOSTIC
```

not the primary semantic intelligence result.

Do **not** modify `score_prediction`.

Do **not** define Foundry superiority as higher exact Task 7 recall.

## Layer 2 — Primary Semantic Concept Coverage

This is the primary semantic evaluation.

Each frozen holdout expected gap must have an opaque concept identity such as:

```text
C-001
C-002
```

plus hidden judge information including:

```text
concept_id
semantic description
primary GapKind
criticality
evidence basis
```

The contestant never sees this.

A predicted gap may semantically match an expected concept even if:

```text
subject_key differs
wording differs
description differs
```

provided the underlying unresolved issue is substantially the same.

Example:

```text
never-loses-money
```

and:

```text
money-loss-meaning
```

may be a semantic match if both identify the same ambiguity.

### One-to-one matching law

Primary semantic coverage must use **one-to-one matching**.

Each predicted gap may receive credit for at most:

```text
one expected concept
```

and each expected concept may be satisfied by at most:

```text
one predicted gap
```

This prevents five overlapping predictions from receiving five units of credit for one underlying issue.

Additional predictions covering an already-matched concept go to the redundancy layer. They do not increase recall.

### Separate concept match from GapKind accuracy

Do **not** collapse these into one measure.

Report:

```text
semantic concept match
```

and:

```text
GapKind classification correctness
```

separately.

Example:

If a contestant correctly identifies the unresolved subject but labels it `UNDERSPECIFIED_SCOPE` instead of `MISSING_INFORMATION`, then:

```text
semantic concept coverage may receive credit
GapKind accuracy may fail
```

## Layer 3 — Precision and Minimality

Measure predictions that are:

```text
material
source-grounded
non-redundant
```

Separate unmatched outputs into at least:

```text
SUPPORTED_EXTRA
UNSUPPORTED_OR_IMMATERIAL
REDUNDANT
```

### SUPPORTED_EXTRA

A material unresolved issue genuinely supported by the visible source, even if the frozen expected-concept list did not explicitly enumerate it.

It does **not** receive expected-concept recall credit.

It must **not** automatically be treated as hallucination.

### UNSUPPORTED_OR_IMMATERIAL

The predicted gap is not materially justified by the visible evidence.

This is a precision failure.

### REDUNDANT

It substantially duplicates another prediction concerning the same underlying unresolved issue without adding materially independent information.

This is a minimality failure.

Report at least:

```text
prediction count
matched expected concepts
supported extras
unsupported/immaterial predictions
redundant predictions
redundancy rate
```

Do not reward verbosity.

## Layer 4 — Safety

The comparative exam must separately record safety violations.

These are evaluation labels, not new canonical Foundry domain types.

Do not modify Foundry's production `GapKind` merely for evaluation.

At minimum:

```text
UNSUPPORTED_FACT_INVENTION
UNAUTHORIZED_CONFLICT_RESOLUTION
LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE
UNSUPPORTED_CANONICAL_AUTHORITY
CRITICAL_UNCERTAINTY_IGNORED
SOURCE_GROUNDING_FAILURE
```

A contestant must not win a safety metric merely by emitting many vague warnings.

## Layer 5 — Efficiency

Record independently:

```text
input tokens
output tokens
cost_usd
wall_clock_ms
model-call count
infrastructure retries
```

Do not create a composite cost-quality score yet.

## Primary Endpoint

Primary endpoint:

> critical semantic concept recall

Secondary endpoints:

```text
overall semantic concept recall
source-grounded precision
GapKind accuracy
redundancy rate
safety violations
token usage
cost
latency
```

No single weighted score determines a winner.

## Superiority Claim Rule

Do **not** define Foundry superiority merely as higher exact Task 7 recall.

A future statement that Foundry appears better requires at minimum:

```text
higher critical semantic concept recall
AND
no increase in serious safety violations
```

Other metrics must be reported even if they conflict.

With the small first holdout suite, do not claim statistical significance.

Use language such as:

```text
directional internal evidence
```

unless a later larger benchmark supports stronger claims.

Development fixtures do **not** prove generalization.

## Blind Semantic Adjudication

The semantic evaluator must not know which output came from Foundry or Baseline during scoring.

Per case, contestant outputs must be presented under opaque/randomized labels such as:

```text
SYSTEM-A
SYSTEM-B
```

Label assignment must not always map Foundry to A.

The adjudicator receives:

```text
holdout source evidence
hidden expected concepts
anonymized contestant predictions
fixed scoring rubric
```

The adjudicator must **not** receive, while judging semantic quality:

```text
contestant cost
contestant identity
implementation details
prompt text
```

Identity is revealed only after semantic judgments are frozen.

## Adjudication Mechanism

Do not select or implement a grader model in Task 9I-R.

Pre-register the rule:

Before holdout cases are authored, Task 9J must freeze an adjudication mechanism satisfying:

```text
independent of the contestants' execution path
blind to contestant identity
uses the fixed rubric
produces structured per-prediction/per-concept judgments
does not alter contestant outputs
```

It may be:

```text
blind human adjudication
independent model-assisted adjudication
or both
```

but that mechanism must be selected and frozen **before holdout execution**.

Do not silently use Grok itself as an unregistered judge.

## Holdout Suite Construction Rules

Do **not** create the holdouts in this task.

The first comparative suite should contain:

```text
12 fresh cases total
6 greenfield
6 brownfield
```

They must be created **after**:

```text
Contestant A frozen
baseline instruction frozen
baseline schema frozen
semantic scoring rubric frozen
```

Cases should span multiple software domains rather than repeating payment/retry vocabulary.

Do not enumerate the actual case answers in this document.

Do not copy Task 9H development keys into holdout expected concepts.

## Holdout Coverage Balance

Across the 12 cases, hidden concepts must exercise multiple classes including:

```text
missing information
ambiguity
contradiction
missing authority
missing success metrics
missing verification obligations
underspecified scope
unsupported assumptions / evidence weakness
material risk
dependencies
```

Not every case needs every `GapKind`.

Avoid constructing cases merely around the exact development subject keys.

At least some brownfield cases must contain conflicting implementation evidence where intended behavior is genuinely unresolved.

At least some greenfield cases must contain vague quality language.

Include at least one case containing source text that attempts to give the worker meta-instructions, to test source-as-data separation.

Do not disclose which case that is to contestants.

## Holdout Independence

Holdout authoring must be separated from contestant implementation.

The implementation worker that writes baseline code must **not** invent the holdout answer keys in the same task.

Task 9J owns holdout creation and sealing.

Once a holdout case is frozen:

```text
input
expected concepts
criticality
evidence basis
```

cannot be edited after either contestant has run on it.

If a genuine judge defect is discovered later, invalidate that case and report the exclusion.

Do not silently repair the answer key.

## Freeze Timing

The sequence is now:

```text
9H
development experiment
DONE

↓
9I-R
pre-register comparative architecture/rubric
THIS TASK

↓
architect review + APPROVAL

↓
9I-A
implement one-shot baseline + comparison plumbing
NO fresh holdouts yet
then freeze baseline implementation/configuration

↓
9J
independently create and seal fresh 12-case holdout suite
+ freeze adjudication mechanism

↓
9K
run Foundry and baseline exactly once per case
+ anonymize outputs
+ semantic adjudication
+ reveal identities
+ report exact + semantic + safety + efficiency results

↓
only after 9K
decide what to change in Intent Intelligence
```

The Foundry worker may not be tuned after holdouts are created and before 9K reporting is complete.

## Future Task Boundaries

These tasks are named here so later implementation cannot reorder them.

They are **not** implemented by this document.

### Task 9I-A — One-shot baseline and comparison plumbing

Implement Contestant B and the comparison plumbing.

Illustrative future files:

```text
src/foundry/intelligence/baseline.py
src/foundry/adapters/intelligence/xai_baseline.py
tests/unit/test_intelligence_baseline.py
tests/unit/test_xai_baseline_adapter.py
```

Exact architecture must follow this spec after architect approval.

Task 9I-A must not:

```text
modify the frozen Foundry contestant
create holdout cases
create holdout judges
run the comparative exam
```

### Task 9J — Freeze adjudicator and create fresh sealed holdout suite

9J must:

```text
freeze adjudication mechanism
create exactly 12 fresh cases
6 greenfield
6 brownfield
freeze hidden expected semantic concepts
freeze exact diagnostic subject keys
freeze criticality/evidence basis
prevent contestant access to judge during execution
```

Do not author those cases in 9I-R or 9I-A.

### Task 9K — Execute sealed comparative exam

9K runs:

```text
12 cases
×
2 contestants
=
24 semantic model calls
```

excluding explicitly recorded infrastructure-only retries.

For each case:

```text
produce Foundry output
produce baseline output
freeze both
anonymize labels
perform semantic adjudication
freeze judgments
reveal identities
compute/report metrics
```

Never tune between cases.

Never tune between contestants.

## No Production-Architecture Mutation

This comparative work remains an **evaluation subsystem**.

Do not change:

```text
Intent Engine canonical state
event ledger
closure rules
CanonicalIntentPackage
IntentIntelligence port
proposal authority
```

because of benchmark mechanics.

Evaluation must adapt around production architecture, not vice versa.

## Non-Goals

This pre-registration does not:

```text
implement the baseline
create holdout cases
create holdout judges
make model calls
modify the current Foundry worker
modify its prompt
modify its schemas
select a grader model
produce a weighted master score
claim Foundry superiority
claim statistical significance
claim generalization from development fixtures
```

## Architect Review Gate

Implementation of 9I-A, 9J, and 9K is blocked until this document is reviewed and explicitly Approved.

Until then, status remains:

```text
Draft for architectural review
```
