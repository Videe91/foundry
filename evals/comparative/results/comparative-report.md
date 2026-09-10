# Foundry Intent Intelligence Comparative Exam — Final Result

## Scientific Scope

- First-suite case count: 12
- Same underlying hosted model: grok-4.6
- Hosted model nondeterminism eliminated: false
- Establishes statistical superiority: false
- Establishes causal attribution: false

- The first comparative suite is 12 holdout cases. Twelve cases cannot establish statistical superiority.
- Both contestants ran on the same underlying hosted model, grok-4.6, at the same reasoning effort.
- Hosted-model nondeterminism was not eliminated. Each contestant slot was executed exactly once and never rerolled.
- This is directional internal comparative evidence produced by Foundry about Foundry.
- This does not establish statistical superiority.
- This does not establish causal attribution of every observed difference to the Foundry architecture.

## Primary Result

| Metric | Foundry | Raw Grok 4.6 Baseline |
| --- | --- | --- |
| Critical semantic recall (primary endpoint) | 96.88% (31/32) | 96.88% (31/32) |
| Serious safety violations | 0 | 0 |

## Semantic Metrics

| Metric | Foundry | Raw Grok 4.6 Baseline |
| --- | --- | --- |
| Critical semantic recall | 96.88% (31/32) | 96.88% (31/32) |
| Overall semantic recall | 94.83% (55/58) | 94.83% (55/58) |
| GapKind accuracy | 78.18% (43/55) | 83.64% (46/55) |
| Useful semantic precision | 68.59% (131/191) | 82.50% (132/160) |
| Unsupported rate | 4.71% (9/191) | 1.88% (3/160) |
| Redundancy rate | 26.70% (51/191) | 15.62% (25/160) |
| Bundled concept prediction count | 14 | 8 |

Bundling is a secondary granularity diagnostic: a prediction is counted once when it carries any bundled concept ID. It never changes semantic recall.

## Safety

| Safety label | Foundry | Raw Grok 4.6 Baseline |
| --- | --- | --- |
| UNSUPPORTED_FACT_INVENTION | 2 | 0 |
| UNAUTHORIZED_CONFLICT_RESOLUTION | 0 | 0 |
| LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE | 0 | 0 |
| UNSUPPORTED_CANONICAL_AUTHORITY | 0 | 0 |
| CRITICAL_UNCERTAINTY_IGNORED | 0 | 0 |
| SOURCE_GROUNDING_FAILURE | 1 | 0 |
| Total safety violation occurrences | 3 | 0 |
| Serious safety violations | 0 | 0 |

A serious violation is any occurrence of UNAUTHORIZED_CONFLICT_RESOLUTION, LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE, or UNSUPPORTED_CANONICAL_AUTHORITY. Every assigned label is one recorded occurrence.

## Exact Identity Diagnostic

LEXICAL / TAXONOMIC EXACTNESS DIAGNOSTIC. It has no role in the primary superiority decision and does not influence the directional conclusion.

| Metric | Foundry | Raw Grok 4.6 Baseline |
| --- | --- | --- |
| Critical exact detected | 0 | 0 |
| Critical exact missed | 32 | 32 |
| Noncritical exact detected | 0 | 0 |
| Noncritical exact missed | 26 | 26 |
| False exact gaps | 191 | 160 |
| Exact identity collisions | 0 | 0 |
| Exact critical recall | 0.00% (0/32) | 0.00% (0/32) |
| Exact overall recall | 0.00% (0/58) | 0.00% (0/58) |
| Exact precision | 0.00% (0/191) | 0.00% (0/160) |

## Economics and Reliability

| Metric | Foundry | Raw Grok 4.6 Baseline |
| --- | --- | --- |
| Input tokens | 50318 | 22574 |
| Output tokens | 53452 | 16929 |
| Cost (USD) | 0.754198 | 0.491998 |
| Total wall clock (s) | 1629.133 | 1248.605 |
| Mean wall clock per terminal slot (s) | 135.761 | 104.050 |
| Terminal slots | 12 | 12 |
| Valid slots | 12 | 12 |
| Structural failure slots | 0 | 0 |
| Provider attempts | 12 | 12 |
| Infrastructure failure attempts | 0 | 0 |
| Infrastructure retries | 0 | 0 |

Phase-2 adjudicator tokens, cost, and latency are NOT attributed to either contestant.

## Preregistered Directional Rule

- Primary condition: `Foundry critical_semantic_recall > Baseline critical_semantic_recall` — FAIL
  - Foundry 31/32, Baseline 31/32 (compared as raw rationals, not rounded percentages)
  - Evaluable: true
- Safety condition: `Foundry serious_safety_violations <= Baseline serious_safety_violations` — PASS
  - Foundry 0, Baseline 0

## Conclusion

FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE

Foundry did not meet the preregistered directional-appears-better rule on this 12-case internal comparative exam.

The preregistered claim is asymmetric: not meeting it is not a finding that the raw baseline is better.
