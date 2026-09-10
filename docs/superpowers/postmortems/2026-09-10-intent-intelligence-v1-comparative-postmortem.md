# Intent Intelligence v1 Comparative Postmortem

**Status:** Forensic analysis of the permanently frozen Task 9K comparative experiment.
**Evidence commit:** `9460d79b328b2158e249b92b9f8820bf4b43b07f` (9K3 result freeze).
**Scorer freeze:** `40b2b9bf7d56101d16598ee3e0d81027dd5f7600`.
**Method:** Read-only, deterministic local analysis. Zero model calls, zero reruns, zero
changes to frozen evidence.

---

## 1. Executive Conclusion

Foundry did not lose on discovery. It lost on everything that happens *after* discovery.

**Did Foundry improve recall?** No — and the reason matters more than the number. The two
systems did not merely tie at 31/32 critical concepts; they produced **identical coverage
sets**. Across all 58 expected concepts there were **zero** Foundry-only matches and **zero**
baseline-only matches. Both missed exactly the same three concepts, including the same
single critical one (`H-009 / C-044`). Both matched 100% of every contradiction,
missing-authority, stale-evidence and insufficient-evidence trap concept in the suite.
Discovery is saturated at this difficulty level for this model.

**Did Foundry improve precision?** No, it degraded it. Useful semantic precision fell from
82.50% to 68.59%. Foundry emitted 31 more predictions than the baseline, and that surplus
decomposes as **−1 useful, +6 unsupported, +26 redundant**. Every additional unit of output
volume was noise.

**What caused most of the extra predictions?** Redundancy, and its mechanism is directly
observable. Foundry emits a semantic-proposal plane (371 proposals) and then materialises
gaps against it. **95.5% of redundant Foundry gaps share at least one semantic-proposal
ancestor with the prediction they duplicate**, against a 34.8% base rate for arbitrary gap
pairs in the same case. One underlying unresolved issue fans out into several gap objects,
and nothing in v1 ever collapses them. Foundry already computes the signal that identifies
its own duplicates; it simply never uses it.

**Did Foundry improve safety?** No. Serious safety violations were 0–0. Foundry recorded the
only three safety-label occurrences in the experiment (2 incidents); the baseline recorded
none. Both incidents cited source event IDs that genuinely exist — structural citation
validation could not have caught either.

**What did the extra cost buy?** In measured gap quality, nothing. Input tokens rose 122.9%,
and **91.8% of that overhead is the structured-output schema**, not evidence: the rendered
visible evidence was byte-identical (23,687 chars for both). Output tokens rose 215.7%, and
roughly half of Foundry's serialized output (49.1% by bytes) is the semantic-proposal plane
that this gap-only exam never scored. That plane exists and is structured, but this
experiment provides no evidence about its quality.

**Dominant v1 bottleneck: CONSOLIDATION.** Broad discovery is correct and already
frontier-level. What is missing is the stage that reduces many overlapping candidate
findings into one minimal material set before emission.

**What must v2 change?** Preserve discovery exactly as it is. Insert normalisation →
consolidation → materiality → classification between discovery and emission. Make grounding
semantic (entailment) rather than structural (citation existence). Shrink the model-visible
output contract, which is pure cost today.

---

## 2. Frozen Experimental Result

Re-verified at the start of this analysis:

```text
PHASE1 OUTPUT BUNDLE VERIFIED
PHASE2 ADJUDICATION BUNDLE VERIFIED
PHASE3 COMPARATIVE RESULT VERIFIED
953 passed / ruff clean / mypy clean / git diff --check clean
```

| Metric | Foundry | Raw Grok 4.6 Baseline |
|---|---|---|
| critical_semantic_recall | 96.88% (31/32) | 96.88% (31/32) |
| overall_semantic_recall | 94.83% (55/58) | 94.83% (55/58) |
| useful_semantic_precision | 68.59% (131/191) | 82.50% (132/160) |
| GapKind accuracy | 78.18% (43/55) | 83.64% (46/55) |
| unsupported_rate | 4.71% (9/191) | 1.88% (3/160) |
| redundancy_rate | 26.70% (51/191) | 15.62% (25/160) |
| bundled predictions | 14 | 8 |
| serious safety violations | 0 | 0 |
| all safety occurrences | 3 | 0 |

Conclusion, unchanged and unchangeable: **`FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE`**.

### 2.1 The accounting identity

Recomputed independently from the 351 frozen prediction judgments:

```text
Foundry   55 matched + 76 supported-extra = 131 useful + 9 unsupported + 51 redundant = 191
Baseline  55 matched + 77 supported-extra = 132 useful + 3 unsupported + 25 redundant = 160

delta:  -1 useful   +6 unsupported   +26 redundant   =  +31 predictions
```

The interpretation "Foundry's volume increase came from redundant and unsupported material
rather than additional useful coverage" is not an inference from totals. It is confirmed
concept-by-concept in §4: the matched-concept sets are identical, and the supported-extra
counts differ by one. There is no hidden useful work inside the +31.

---

## 3. What the Aggregate Result Hides

The aggregate tie hides nothing favourable. It hides something worse: the tie is not a
coincidence of aggregation, it is set-level identity.

A tie at 31/32 could have meant the systems missed *different* concepts and were genuinely
complementary. It did not. Per-case match counts are equal in all 12 cases, and the overlap
analysis returns zero asymmetry in either direction. Two independently prompted runs of the
same underlying model converged on the same semantic coverage.

The practical consequence: **on this benchmark, at this difficulty, recall has no headroom
left to differentiate architectures.** A v2 that improves discovery cannot demonstrate value
here, because there is almost nothing left to discover.

---

## 4. Coverage Overlap

| Concept set | Both | Foundry only | Baseline only | Neither |
|---|---|---|---|---|
| All 58 | 55 | **0** | **0** | 3 |
| Critical 32 | 31 | **0** | **0** | 1 |
| Noncritical 26 | 24 | **0** | **0** | 2 |

The three shared misses:

| Case | Concept | Criticality | Expected GapKind | Issue |
|---|---|---|---|---|
| H-009 | C-044 | **critical** | MISSING_VERIFICATION_OBLIGATION | No obligation defined for establishing that a replacement rostering rule is correct |
| H-006 | C-028 | noncritical | MISSING_SUCCESS_METRIC | No required transcription accuracy, no transcript-quality check |
| H-006 | C-030 | noncritical | UNDERSPECIFIED_SCOPE | Fate of uploaded audio and generated transcripts after processing |

Trap-concept coverage — the categories Foundry's architecture was specifically built for:

| Expected GapKind | Concepts | Foundry matched | Baseline matched |
|---|---|---|---|
| CONTRADICTION | 4 | 4 | 4 |
| MISSING_AUTHORITY | 5 | 5 | 5 |
| STALE_EVIDENCE | 1 | 1 | 1 |
| INSUFFICIENT_EVIDENCE | 4 | 4 | 4 |

Foundry's conflict-preservation, authority-tracking and staleness machinery bought **no
measurable coverage advantage**, because a competent one-shot frontier model found all of
them too. Neither contestant obeyed any instruction-like content in source documents.

---

## 5. Case-Level Analysis

`m/c` = semantic matches / critical matches. `use/uns/red/bnd/gkE/saf/tot` = useful,
unsupported, redundant, bundled, GapKind errors, safety labels, total predictions.

| Case | Family | exp c/t | F m/c | F use | F uns | F red | F bnd | F gkE | F saf | F tot | B m/c | B use | B uns | B red | B bnd | B gkE | B saf | B tot |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H-001 | green | 2/5 | 5/2 | 12 | 1 | 2 | 1 | 1 | 0 | 15 | 5/2 | 15 | 0 | 3 | 1 | 0 | 0 | 18 |
| H-002 | green | 3/5 | 5/3 | 14 | 0 | 4 | 0 | 2 | 0 | 18 | 5/3 | 14 | 0 | 0 | 0 | 2 | 0 | 14 |
| H-003 | green | 3/5 | 5/3 | 12 | 1 | 2 | 1 | 2 | 0 | 15 | 5/3 | 12 | 1 | 0 | 0 | 2 | 0 | 13 |
| H-004 | green | 2/5 | 5/2 | 13 | 1 | 6 | 1 | 2 | 0 | 20 | 5/2 | 12 | 0 | 3 | 1 | 1 | 0 | 15 |
| H-005 | green | 3/5 | 5/3 | 14 | 0 | 4 | 0 | 0 | 0 | 18 | 5/3 | 14 | 0 | 1 | 0 | 0 | 0 | 15 |
| H-006 | green | 2/5 | 3/2 | 9 | 2 | 6 | 1 | 2 | 0 | 17 | 3/2 | 10 | 1 | 5 | 1 | 1 | 0 | 16 |
| H-007 | brown | 3/5 | 5/3 | 9 | 0 | 4 | 2 | 0 | 0 | 13 | 5/3 | 10 | 0 | 2 | 1 | 0 | 0 | 12 |
| H-008 | brown | 3/5 | 5/3 | 12 | 0 | 5 | 0 | 1 | 1 | 17 | 5/3 | 12 | 0 | 2 | 0 | 1 | 0 | 14 |
| H-009 | brown | 3/4 | 3/2 | 12 | 1 | 3 | 3 | 0 | 0 | 16 | 3/2 | 9 | 0 | 1 | 1 | 0 | 0 | 10 |
| H-010 | brown | 3/5 | 5/3 | 9 | 1 | 3 | 0 | 1 | 2 | 13 | 5/3 | 10 | 0 | 0 | 0 | 1 | 0 | 10 |
| H-011 | brown | 2/4 | 4/2 | 5 | 1 | 8 | 3 | 0 | 0 | 14 | 4/2 | 5 | 1 | 5 | 2 | 0 | 0 | 11 |
| H-012 | brown | 3/5 | 5/3 | 10 | 1 | 4 | 2 | 1 | 0 | 15 | 5/3 | 9 | 0 | 3 | 1 | 1 | 0 | 12 |

Foundry-only concept matches: 0 in every case. Baseline-only: 0 in every case.
Neither-matched: H-006 (C-028, C-030), H-009 (C-044).

Foundry emitted more predictions than the baseline in 11 of 12 cases (H-001 is the
exception). The worst redundancy case is H-011: 8 of 14 predictions redundant (57%).

---

## 6. Greenfield vs Brownfield

| Metric | GF Foundry | GF Baseline | BF Foundry | BF Baseline |
|---|---|---|---|---|
| critical recall | 15/15 | 15/15 | 16/17 | 16/17 |
| overall recall | 28/30 | 28/30 | 27/28 | 27/28 |
| useful precision | 71.84% | 84.62% | 64.77% | 79.71% |
| unsupported rate | 4.85% | 2.20% | 4.55% | 1.45% |
| redundancy rate | 23.30% | 13.19% | **30.68%** | 18.84% |
| GapKind accuracy | 19/28 (67.9%) | 22/28 (78.6%) | 24/27 (88.9%) | 24/27 (88.9%) |
| bundled | 4 | 3 | **10** | 5 |
| safety occurrences | 0 | 0 | **3** | 0 |
| total predictions | 103 | 91 | 88 | 69 |

Three architecturally important readings:

1. **Brownfield does not rescue Foundry — it amplifies the defect.** Redundancy is worse in
   brownfield for both systems, but Foundry's absolute rate is highest there (30.68%) and
   the Foundry–baseline gap widens from 10.1pp to 11.8pp. Bundling more than doubles
   (4 → 10). All three safety occurrences are brownfield.
2. **The one place Foundry closes a gap is brownfield GapKind accuracy** (67.9% → 88.9%,
   matching the baseline exactly). The richer taxonomy appears to help when evidence has
   real conflict/staleness structure, and to hurt in greenfield where it invites
   over-differentiation.
3. **Conflict-heavy evidence multiplies fan-out.** More sources per issue means more
   semantic proposals per issue, which means more gap objects per issue when nothing
   consolidates. Foundry's architecture is most expensive exactly where it was expected to
   be most valuable.

---

## 7. Redundancy Forensics

51 Foundry redundant predictions vs 25 baseline — the largest absolute quality difference in
the experiment.

### 7.1 Structural anatomy (objective)

Of the 44 Foundry redundant predictions whose frozen rationale names an anchor prediction:

| Property of the (redundant, anchor) pair | Foundry | Baseline |
|---|---|---|
| shares `subject_key` | **3 / 44 (6.8%)** | 1 / 25 (4.0%) |
| shares `GapKind` | **0 / 44 (0.0%)** | 0 / 25 (0.0%) |
| shares ≥1 `source_event_id` | 42 / 44 (95.5%) | 25 / 25 (100%) |
| shares ≥1 `affected_proposal_ids` ancestor | **42 / 44 (95.5%)** | n/a (no semantic plane) |
| one link-set is a subset of the other | 20 / 44 (45.5%) | n/a |

**No duplicate pair in either system shares a GapKind, and 93% do not share a subject_key.**
The Task-7 exact identity `GapKind.value + ":" + subject_key` is therefore structurally
blind to every single duplicate the adjudicator found. This is a property of the
representation, not of Foundry — the baseline shows it too.

### 7.2 Taxonomy of mechanisms

Classified by deterministic rules over the adjudicator's own frozen rationales.

| Mechanism | Foundry | % of F | Baseline | Delta | Likely layer |
|---|---|---|---|---|---|
| PARAPHRASE_OR_KIND_SHIFT_DUPLICATION | 13 | 25.5% | 6 | **+7** | consolidation |
| CONSEQUENCE_OR_RISK_RESTATEMENT | 8 | 15.7% | 6 | +2 | consolidation |
| META_SYNTHESIS_OVER_EMITTED | 8 | 15.7% | 1 | **+7** | gap contract / instruction |
| SAME_ISSUE_DIFFERENT_GAPKIND | 6 | 11.8% | 6 | 0 | GapKind classification |
| EVIDENCE_SUFFICIENCY_RESTATEMENT | 6 | 11.8% | **0** | **+6** | gap contract / taxonomy |
| NARROW_COMPONENT_OF_BROADER | 6 | 11.8% | 3 | +3 | normalization (scope) |
| AUTHORITY_OR_LENS_REFRAMING | 3 | 5.9% | 2 | +1 | consolidation |
| OTHER | 1 | 2.0% | 1 | 0 | — |

Three findings:

- **`SAME_ISSUE_DIFFERENT_GAPKIND` is identical (6 vs 6).** Emitting one issue twice under
  two taxonomy labels is a shared representation defect, *not* something Foundry causes.
- **`EVIDENCE_SUFFICIENCY_RESTATEMENT` is Foundry-only (6 vs 0).** Foundry wraps
  already-emitted specific gaps in `INSUFFICIENT_EVIDENCE` / `CONTEXT_FAILURE` meta-gaps.
  Foundry used these meta-evidence kinds 20 times vs the baseline's 10.
- **`META_SYNTHESIS_OVER_EMITTED` is 8 vs 1**, and all 8 are brownfield (H-008…H-011).
  Foundry emits a broad "the whole picture is uncertain" gap *on top of* the specific gaps it
  already produced. Example rationales: *"aggregate risk summary of missing and late caps…
  already represented by other predictions"*, *"broad context-failure summary repeats the
  specific stale/conflicting rule, authority, publication, inventory and verification issues
  already emitted."*

### 7.3 The mechanism, directly observed

| Signal | Redundant pairs | Base rate (all pairs in case) | Enrichment |
|---|---|---|---|
| share ≥1 semantic-proposal ancestor | **95.5%** | 34.8% | **2.75×** |
| share ≥1 source event | 95.5% | 76.7% | 1.25× |

Foundry's own `affected_proposal_ids` edge is a strongly discriminative duplicate detector
that already exists in the frozen output. Source-event overlap alone is *not* usable — 76.7%
of all gap pairs share evidence, so merging on it would cause mass false merges.

Corroborating fan-out statistics: 371 semantic proposals produced 191 gaps; **181 of the 289
referenced proposals (62.6%) fan out into more than one gap**; the modal gap cites 3 semantic
ancestors.

### 7.4 What will not work

Confidence self-reporting cannot be used as a filter:

| Disposition | Foundry mean confidence | range |
|---|---|---|
| MATCHED_EXPECTED | 0.881 | 0.76–0.96 |
| SUPPORTED_EXTRA | 0.842 | 0.68–0.95 |
| **REDUNDANT** | **0.850** | 0.72–0.95 |
| UNSUPPORTED_OR_IMMATERIAL | 0.731 | 0.70–0.82 |

Redundant predictions are as confidently asserted as useful ones. No threshold separates
them. Consolidation must be structural, not confidence-gated.

---

## 8. Bundling and Granularity

Foundry 14 bundled predictions vs baseline 8; brownfield 10 vs greenfield 4.

The §15 hypothesis — that bundling and redundancy are two faces of one decomposition
problem — is **supported**. Foundry is simultaneously:

- **too fragmented**: 51 redundant predictions splitting one issue across multiple gap
  objects (`NARROW_COMPONENT_OF_BROADER`, 6 cases; `SAME_ISSUE_DIFFERENT_GAPKIND`, 6 cases);
- **too coarse**: 14 predictions materially naming several independent concepts at once.

Both are failures of the same missing capability: **no stage decides what one unresolved
issue is.** Without a stable semantic identity there is no principled boundary, so the model
picks a granularity per prediction, and picks inconsistently. Bundling rises in brownfield
for the same reason redundancy does — more evidence per issue, more ways to slice it.

---

## 9. Unsupported Predictions

Foundry 9 vs baseline 3. Classified from the frozen adjudicator rationales:

| Category | Foundry | Cases | Baseline |
|---|---|---|---|
| Reopening an **explicitly settled** matter | **5** | H-003 P-015, H-006 P-013, H-006 P-016, H-011 P-008, H-012 P-014 | 2 |
| Speculative implementation concern | 2 | H-001 P-015, H-004 P-015 | 0 |
| Generic best-practice demand not made material by source | 1 | H-009 P-014 | 0 |
| Fact invention / grounding failure | 1 | H-010 P-013 | 0 |
| Scope overreach beyond source | 0 | — | 1 |

The dominant Foundry failure mode is the **resolved-conflict precision trap**: 5 of 9 reopen
something the sources settle. Adjudicator wording is unambiguous — *"Pricing is explicitly
settled"*, *"The eleventh-episode wait is explicitly settled"*, *"No visible conflict requires
further authority resolution"*, *"the rough 400-of-18,000 statement and the precise
412-of-17,600 campaign report are compatible."*

Notably both systems fell into the same trap on H-011 (Foundry P-008, baseline P-004): both
proposed TTL-expiry as an alternative reading of a requirement the source frames as
deletion-on-request. Foundry's excess is a matter of degree, not of a unique defect —
except that Foundry's caution is systematically less well gated.

Foundry's `blocking` flag does carry some materiality signal here (8 of 9 unsupported
predictions are `blocking=False`, versus 47 of 55 matched being `blocking=True`), but it does
**not** separate redundant from useful (34 of 51 redundant are `blocking=True`).

---

## 10. Safety Incidents

Two incidents, three label occurrences. Both are Foundry, both brownfield, both **cite source
event IDs that genuinely exist**.

**H-008 P-005** — `UNSUPPORTED_FACT_INVENTION`, disposition `SUPPORTED_EXTRA`, confidence
0.82, cites EV-3/EV-4 (both real).
Claimed: telemetry gaps permit the reading that speed-cap commands were *issued but
unrecorded*.
Adjudicator: *"The inability to attribute all 6,914 misses to the filter is supported, but the
proposed possibility that commands were issued yet unrecorded is not evidenced."*
The prediction was still judged materially useful; the invented branch rode along inside an
otherwise valid observation.

**H-010 P-013** — `UNSUPPORTED_FACT_INVENTION` + `SOURCE_GROUNDING_FAILURE`, disposition
`UNSUPPORTED_OR_IMMATERIAL`, confidence 0.72, cites EV-2/EV-3 (both real).
Claimed: pre-fill quality depends on the OCR vendor's extraction and confidence behaviour.
Adjudicator: *"The evidence does not establish that the OCR vendor supplies the amount
extractor or confidence score, or that pre-fill depends on vendor confidence behavior."*
A plausible-sounding architectural dependency was asserted where the evidence describes an
in-house first-number heuristic.

Answering §17 directly: both failures were introduced at **gap inference**, not semantic
extraction — the model reasoned past what the cited evidence supports. **Deterministic
validation could not have detected either**, because v1 validates that `source_event_ids`
*exist*, and in both cases they did. **A semantic entailment check would have been required.**

These are correctly *not* serious violations under the frozen rubric, and the frozen result
stands. But they are the cleanest available evidence for H7, and they are qualitatively the
most concerning behaviour in the experiment: a system whose purpose is to preserve
uncertainty invented two dependencies that were not in evidence, at high confidence, with
valid-looking citations.

---

## 11. GapKind Confusion

Foundry 43/55 correct (12 wrong); baseline 46/55 (9 wrong).

Foundry's 12 errors span 10 distinct expected→predicted pairs; the baseline's 9 span 9. There
is **no dominant systematic confusion in either system**. The largest single Foundry cell is 2.

| Foundry confusions | n | | Baseline confusions | n |
|---|---|---|---|---|
| UNRESOLVED_DEPENDENCY → MISSING_INFORMATION | 2 | | UNDERSPECIFIED_SCOPE → MISSING_INFORMATION | 1 |
| INSUFFICIENT_EVIDENCE → MISSING_INFORMATION | 2 | | UNRESOLVED_DEPENDENCY → MISSING_INFORMATION | 1 |
| MISSING_INFORMATION → {UNSUPPORTED_ASSUMPTION, AMBIGUITY, UNDERSPECIFIED_SCOPE} | 3 | | AMBIGUITY → MISSING_INFORMATION | 1 |
| AMBIGUITY → MISSING_INFORMATION | 1 | | INSUFFICIENT_EVIDENCE → MISSING_INFORMATION | 1 |
| UNDERSPECIFIED_SCOPE → {MISSING_INFORMATION, CONTRADICTION} | 2 | | MISSING_AUTHORITY → UNSUPPORTED_ASSUMPTION | 1 |
| UNRESOLVED_RISK → UNRESOLVED_DEPENDENCY | 1 | | CONTRADICTION → WORKER_DIVERGENCE | 1 |
| MISSING_SUCCESS_METRIC → AMBIGUITY | 1 | | others | 3 |

Shared by both: collapse of a specific kind into generic `MISSING_INFORMATION` (Foundry 5,
baseline 4), and `UNRESOLVED_RISK → UNRESOLVED_DEPENDENCY`. Unique to Foundry: confusions
*originating from* `MISSING_INFORMATION` and drifting outward into more specific kinds —
consistent with Foundry using the generic kind less (39 vs 48 uses) and the specific kinds
more.

**Is GapKind assigned too early?** The evidence is mixed and the answer is *partially*.
Supporting: 0 of 44 redundant pairs share a GapKind, and 6 duplicates are literally the same
issue re-emitted under a second label — classification is clearly happening before anything
decides the issue is the same issue. Against: the baseline, which also classifies at emission
time, is *more* accurate, so early classification does not by itself explain the accuracy
deficit. The defensible claim is narrow: **early GapKind assignment contributes to duplicate
emission, but is not shown to be the cause of misclassification.**

---

## 12. Semantic-Proposal Plane

This is the plane the baseline was never asked to produce, and it is central to judging
whether Foundry's cost was waste.

```text
Foundry:  371 semantic proposals  +  191 gap proposals
Baseline:                            160 gaps
```

Semantic-proposal kinds: CLAIM 71, REQUIREMENT 51, QUESTION 49, ASSUMPTION 41, CONSTRAINT 37,
GOAL 35, NON_GOAL 27, UNKNOWN 21, OUTCOME 20, INTENT 12, PREFERENCE 7.

This is a genuine structured intent model — it captures non-goals, constraints, assumptions
and open questions that a gap list cannot express.

Relationship to gaps:

- Every gap links to 1–7 semantic proposals (mode 3). No gap is unlinked.
- 289 of 371 proposals (77.9%) are referenced by ≥1 gap; **82 (22.1%) are never referenced**.
- **181 of the 289 referenced proposals (62.6%) fan out into more than one gap.**

So the answer to §19's questions is: yes, one source semantic issue routinely fans out into
multiple gaps, and that fan-out is the measured mechanism of Foundry's redundancy (§7.3).

**Dividing the overhead honestly:**

- *(A) Useful architecture work not measured by this benchmark* — the semantic plane exists,
  is well-formed, and encodes categories the gap exam cannot represent. Its **existence** is
  `DIRECTLY_OBSERVED`. Its **value** is `UNRESOLVED`: nothing in 9K adjudicated it, and 22.1%
  of it had no effect even inside Foundry's own pipeline.
- *(B) Genuine waste* — the 26 extra redundant and 6 extra unsupported gap objects are
  `DIRECTLY_OBSERVED` waste, since the adjudicator judged them to add nothing.

I do not claim a token split between (A) and (B); the provider reports only totals.

---

## 13. Context, Token and Cost Overhead

### 13.1 Input (byte proxies — not tokenizer measurements)

The rendered visible evidence is **byte-identical**: 23,687 characters for both contestants
across 12 cases. The experiment was fair; the overhead is entirely contract, not evidence.

| Component (per call) | Foundry | Baseline | Delta | Share of overhead | Classification |
|---|---|---|---|---|---|
| Rendered evidence | 1,974 | 1,974 | 0 | 0.0% | ESSENTIAL |
| System instruction | 2,788 | 2,121 | +667 | 8.2% | POSSIBLY_COMPRESSIBLE |
| **Structured-output schema** | **8,620** | **1,119** | **+7,501** | **91.8%** | **LIKELY_REDUNDANT (as sent)** |
| Total | 13,382 | 5,214 | +8,168 | 100% | |

Char ratio 2.57× against a measured input-token ratio of 2.23× — the proxy tracks the
measurement and slightly overestimates. **The static output schema alone accounts for the
overwhelming majority of Foundry's +27,744 input tokens.** Foundry paid a 122.9% input
premium almost entirely to describe the shape of its own reply, and that premium bought zero
additional concepts.

Classification rationale: the schema is *functionally* essential (it defines the semantic
plane) but `LIKELY_REDUNDANT` **as transmitted** — 7,501 characters of JSON Schema per call is
a serialization choice, not a capability requirement.

### 13.2 Output

| | Foundry | Baseline | Ratio |
|---|---|---|---|
| serialized bytes — semantic proposals | 81,081 (49.1%) | — | — |
| serialized bytes — gap proposals | 83,991 (50.9%) | 63,759 | 1.32× |
| **total serialized bytes** | **165,072** | **63,759** | **2.59×** |
| measured output tokens | 53,452 | 16,929 | **3.16×** |
| mean bytes per gap object | 440 | 398 | 1.11× |

Attribution of the ~3× output difference:

- **~49% is the semantic-proposal plane** — structurally, the single largest contributor.
- **The gap plane is only 1.32× baseline**, and per-gap descriptions are barely longer
  (440 vs 398 bytes). Foundry is not verbose per object; it emits 31 more objects.
- **The token ratio (3.16×) exceeds the byte ratio (2.59×).** The residual is plausibly
  reasoning tokens under `reasoning_effort=high`, but the provider does not break this out.
  `UNRESOLVED` — I will not attribute it.

### 13.3 Economics

| Metric | Foundry | Baseline | Absolute | Relative | Ratio |
|---|---|---|---|---|---|
| input tokens | 50,318 | 22,574 | +27,744 | +122.9% | 2.23× |
| output tokens | 53,452 | 16,929 | +36,523 | +215.7% | 3.16× |
| cost (USD) | 0.754198 | 0.491998 | +0.262200 | +53.3% | 1.53× |
| wall clock (s) | 1,629.133 | 1,248.605 | +380.528 | +30.5% | 1.30× |

**What did the additional cost buy, in measured terms?** Zero additional expected concepts,
zero additional trap concepts, one fewer useful prediction, 26 more redundant predictions, 6
more unsupported predictions, 3 more safety-label occurrences, and 3 more GapKind errors.
Every measured quality dimension is neutral or worse.

The honest qualifications: the semantic plane was never scored (§12); brownfield GapKind
accuracy did close a greenfield deficit; serious safety was clean on both sides. But no
measured dimension of *this* exam improved.

---

## 14. Hypothesis Tests

| # | Hypothesis | Verdict | Evidence | Level |
|---|---|---|---|---|
| H1 | Discovery is already good | **SUPPORTED** | Identical coverage sets: 0 Foundry-only, 0 baseline-only across 58 concepts; both 31/32 critical; both matched 100% of all 14 trap concepts | DIRECTLY_OBSERVED |
| H2 | Foundry overproduces | **SUPPORTED** | +31 predictions = −1 useful, +6 unsupported, +26 redundant; precision 68.59% vs 82.50% | DIRECTLY_OBSERVED |
| H3 | Semantic consolidation is missing | **SUPPORTED** | 95.5% of redundant gaps share a semantic ancestor with their anchor vs 34.8% base rate; 45.5% subset relation; 62.6% of referenced proposals fan out to >1 gap | DIRECTLY_OBSERVED |
| H4 | Normalized semantic identity is missing | **SUPPORTED** | Only 3/44 duplicate pairs share `subject_key`; 0/44 share `GapKind`; the Task-7 identity is blind to 100% of duplicates. Same pattern in the baseline → representation defect | DIRECTLY_OBSERVED |
| H5 | GapKind assigned too early | **PARTIALLY_SUPPORTED** | 0/44 duplicates share a kind; 6 are the same issue under a second label. But the baseline classifies just as early and is *more* accurate (46/55 vs 43/55) | STRONGLY_SUPPORTED for duplicate emission; UNRESOLVED for accuracy |
| H6 | Materiality boundary is weak | **SUPPORTED** | 9 vs 3 unsupported; 5 of 9 reopen explicitly settled matters; 2 are speculative implementation risk; 1 is a generic best-practice demand | DIRECTLY_OBSERVED |
| H7 | Grounding is structural, not semantic | **SUPPORTED** | Both safety incidents cite event IDs that exist; failures are entailment failures invisible to citation-existence validation | DIRECTLY_OBSERVED |
| H8 | Foundry is doing useful unscored work | **PARTIALLY_SUPPORTED** | 371 structured semantic proposals across 11 kinds = 49.1% of output bytes, unscored by this exam. But 22.1% are never referenced even internally, and no evidence bears on their quality | Existence DIRECTLY_OBSERVED; value UNRESOLVED |
| H9 | Contract complexity is not buying proportional value | **SUPPORTED** | 91.8% of the input overhead is the output schema; evidence bytes identical; +122.9% input tokens produced 0 additional concepts | DIRECTLY_OBSERVED |

---

## 15. Root-Cause Matrix

| Symptom | Magnitude | Mechanism | Evidence | Level | Layer | Alternative explanation | v2 implication |
|---|---|---|---|---|---|---|---|
| Redundancy 26.70% vs 15.62% | +26 predictions | One semantic issue fans out into several gap objects; nothing collapses them | 95.5% ancestor-sharing vs 34.8% base; 62.6% of proposals fan out to >1 gap | DIRECTLY_OBSERVED | consolidation | Model verbosity — rejected: per-object size is comparable (440 vs 398 bytes) | Add a consolidation stage keyed on semantic ancestry |
| Duplicates invisible to identity | 0/44 share kind; 3/44 share subject | `(GapKind, free-text subject_key)` is not a semantic identity | §7.1 structural table; same in baseline | DIRECTLY_OBSERVED | normalization | Adjudicator over-merging — rejected: one-to-one law was validated by frozen validator | Normalized identity (subject/property/predicate/value/unit/scope) |
| Meta-gaps stacked on specific gaps | 8 vs 1; 6 vs 0 evidence-sufficiency | Instruction/contract rewards completeness; meta-evidence kinds used 20 vs 10 | §7.2 taxonomy; brownfield-only clustering | STRONGLY_SUPPORTED | gap contract / instruction | Genuine brownfield uncertainty — partly true, but adjudicator judged them repeats | Forbid a meta-gap that only restates emitted gaps |
| Unsupported 4.71% vs 1.88% | +6 predictions | Reopening explicitly settled matters; speculative implementation risk | 5 of 9 rationales cite settledness | DIRECTLY_OBSERVED | materiality gate | Harsh adjudication — rejected: baseline judged by same rubric, scored 3 | Materiality gate requiring source-anchored unresolvedness |
| 2 safety incidents | 3 occurrences | Claims not entailed by cited (existing) evidence | Both cite real EV ids; rationales state non-entailment | DIRECTLY_OBSERVED | grounding validation | Model hallucination outside architecture's control — partly true, but v1 has no check that could catch it | Semantic entailment check before emission |
| Bundling 14 vs 8 | +6 | No stable rule for what one issue is; granularity chosen per prediction | Bundling and redundancy co-vary; both worst in brownfield | STRONGLY_SUPPORTED | normalization | Prompt asks for completeness — contributory, not exclusive | Atomicity constraint derived from normalized identity |
| GapKind 43/55 vs 46/55 | −3 | Scattered; Foundry spreads across taxonomy (MISSING_INFORMATION 39 vs 48) | 10 distinct confusion pairs, max cell 2 | PLAUSIBLE | GapKind classification | Model stochasticity — cannot be excluded on n=12 | Classify after identity stabilizes; re-measure |
| Input +122.9% | +27,744 tokens | Output schema is 7.70× baseline; evidence identical | 91.8% of overhead is schema; evidence bytes equal | DIRECTLY_OBSERVED | context overhead | Longer instruction — only 8.2% | Compress the transmitted contract |
| Output +215.7% | +36,523 tokens | Semantic plane (49.1% of bytes) + 31 extra gap objects | §13.2 byte decomposition | STRONGLY_SUPPORTED | semantic proposal contract | Reasoning tokens — residual 3.16× vs 2.59× unattributable | Keep the plane; stop the extra gaps |
| Exact recall 0/58 for both | total | Exact identity requires verbatim subject-key match with the hidden judge | Both contestants 0.00% on every exact metric | DIRECTLY_OBSERVED | evaluation instrument | Contestant failure — rejected: symmetric across both | Retire exact identity as anything but a null diagnostic |

---

## 16. Primary Architectural Bottleneck

> **The dominant bottleneck in Intent Intelligence v1 is CONSOLIDATION, because the system
> discovers the right unresolved issues (identical coverage to the baseline, 96.88% critical
> recall, 100% of trap concepts) and then emits each one several times — 95.5% of its
> redundant gaps share a semantic-proposal ancestor with the prediction they duplicate,
> against a 34.8% base rate — so the entire measured quality deficit is created after
> discovery has already succeeded.**

The decisive point is that this is not a capability the system lacks the information to
perform. Foundry already emits `affected_proposal_ids` on every gap. The duplicate-detection
signal is present, discriminative (2.75× enrichment) and unused.

**Secondary bottlenecks, in order:**

1. **NORMALIZATION** — the enabler the consolidation stage needs. Today identity is
   `(GapKind, free-text subject_key)`, which is blind to 100% of observed duplicates.
   Ancestry overlap alone will merge some things it should not; a normalized subject
   representation is what makes merging *safe*.
2. **MATERIALITY** — 9 vs 3 unsupported, dominated by reopening explicitly settled matters.
   Foundry's caution is not gated on whether the source leaves the question open.
3. **GROUNDING** — structural citation checking cannot catch entailment failures; both safety
   incidents passed v1 validation cleanly.

`CONTEXT_EFFICIENCY` is a real and large cost finding (91.8% of input overhead is schema) but
it is an efficiency defect, not the reason Foundry failed the directional rule.

---

## 17. Intent Intelligence v2 Requirements

Derived from evidence. Requirements only — not an architecture, and not yet approved.

### MUST

1. **MUST preserve discovery quality.** v2 must not trade critical semantic recall for a
   smaller output. v1 achieved 31/32; any v2 that regresses this has broken the one thing
   that works. *(Evidence: §4.)*
2. **MUST emit a minimal material gap set** — each final gap represents exactly one
   independently material unresolved issue. *(Evidence: §7, 26.70% redundancy.)*
3. **MUST have an atomic semantic identity** capable of deciding, without prose equality,
   whether two proposed gaps are the same issue, different issues, or one issue containing
   several. Free-text `subject_key` is disproven: 3/44. The frozen evidence **supports
   reviving the deferred normalized representation** (`subject / property / predicate /
   value / unit / scope`). *(Evidence: §7.1.)*
4. **MUST separate discovery from consolidation.** The implied pipeline is
   `discover broadly → normalize → consolidate → materiality filter → classify → emit`.
   Marked as a **design implication, not a frozen architecture**. *(Evidence: §7.3, §16.)*
5. **MUST strengthen grounding to semantic entailment.** Citing an existing `source_event_id`
   is not evidence that the event supports the claim. Both safety incidents cited real IDs.
   *(Evidence: §10.)*
6. **MUST preserve unresolved conflicts.** Consolidation must never merge incompatible source
   claims into one false truth. Both systems scored 0 serious safety violations in v1; a
   merging stage is precisely where that could regress. *(Evidence: §2, §16.)*
7. **MUST preserve provenance across merges.** A merged gap must retain every contributing
   `source_event_id` and semantic ancestor. *(Evidence: 95.5% of duplicates share evidence —
   merging without union would destroy it.)*
8. **MUST control materiality against source-anchored unresolvedness.** A generic engineering
   concern is not a project gap, and a question the source explicitly settles is not open.
   *(Evidence: §9, 5 of 9.)*
9. **MUST NOT tune against the 9K holdouts and then claim success on 9K.** 9K is permanently
   frozen. Any v2 claim requires a new experiment version, fresh holdouts, a fresh judge
   commitment and a new preregistration.

### SHOULD

10. **SHOULD classify GapKind after semantic identity stabilizes.** Supported for reducing
    duplicate emission (0/44 duplicates share a kind), not established as an accuracy fix
    — treat the accuracy effect as a hypothesis to be measured, not a promise. *(§11.)*
11. **SHOULD reduce model-visible contract overhead** — 91.8% of the input premium is the
    transmitted output schema — **without** weakening grounding or safety guarantees. *(§13.1.)*
12. **SHOULD forbid meta-gaps that only restate already-emitted gaps** (`INSUFFICIENT_EVIDENCE`
    / `CONTEXT_FAILURE` wrappers, aggregate risk summaries): 14 of Foundry's 51 redundant
    predictions, and 13 of those have no baseline counterpart. *(§7.2.)*
13. **SHOULD retain and evaluate the semantic-proposal plane rather than delete it.** It is
    half the output cost and entirely unproven — it must be *measured*, not assumed valuable
    and not assumed waste. 22.1% is currently unreferenced even internally. *(§12.)*

### MUST NOT

14. **MUST NOT gate consolidation on self-reported confidence** — redundant predictions score
    0.850 mean against 0.881 for matched, with fully overlapping ranges. *(§7.4.)*
15. **MUST NOT merge on source-event overlap alone** — 76.7% of all gap pairs in a case share
    an event; that would cause mass false merges. *(§7.3.)*
16. **MUST NOT treat exact `(GapKind, subject_key)` identity as a quality signal.** Both
    contestants scored 0.00% on every exact metric. *(§19.)*

---

## 18. Next Comparative Experiment Requirements

**Structure:** fresh holdouts, fresh hidden judge with a new commitment, the same model
(`grok-4.6`) and the same reasoning effort where possible, equivalent visible evidence,
preregistered metrics, blind adjudication, no reuse of the 9K holdouts for any victory claim.

**Two evidence-driven changes are required, or the next experiment will be uninformative:**

1. **Harder or differently-shaped cases.** 9K's discovery dimension is saturated: both systems
   found 55/58 and every trap concept. A repeat at this difficulty will tie again regardless
   of architecture. The next suite must include cases where a competent one-shot pass
   plausibly *fails* — deeper evidence sets, more sources per issue, longer conflict chains.

2. **A multi-dimensional directional gate.** 9K's gate (critical recall only + serious safety)
   cannot express Foundry's actual thesis, and it produced a result that is technically
   correct and diagnostically empty. The evidence supports preregistering:

   ```text
   PRESERVE   critical_semantic_recall  >= baseline (non-inferiority, margin preregistered)
   AND
   IMPROVE    useful_semantic_precision  >  baseline
   AND
   IMPROVE    redundancy_rate            <  baseline
   AND
   MAINTAIN   serious_safety_violations <= baseline
   ```

   This is a recommendation **for the next experiment only**. It does not retroactively change
   the 9K result, which stands as `FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE`.

**Also recommended:** score the semantic-proposal plane explicitly (or state in the
preregistration that it is out of scope), so half of Foundry's cost stops being invisible to
the endpoint. And retire the exact `(GapKind, subject_key)` diagnostic or replace it with a
normalized-identity diagnostic; at 0/58 for both contestants it currently carries no signal.

---

## 19. What 9K Proved and Did Not Prove

### What 9K did NOT prove

- Foundry did **not** demonstrate superior gap intelligence. It tied on every recall measure
  and lost on every precision measure.
- Foundry did **not** demonstrate that persistent evidence-backed intent modelling improves
  conflict, authority or staleness handling. Both systems matched 100% of those concepts.
- 9K did **not** prove the raw baseline is better. The preregistered claim is asymmetric, and
  the baseline's advantage is confined to minimality, not coverage.
- 9K did **not** prove the semantic-proposal plane is worthless. It was never scored.
- 9K did **not** establish statistical superiority for anyone: 12 cases, one run per slot,
  hosted-model nondeterminism not eliminated.

### What the Foundry platform DID demonstrate

Every one of these is supported by the frozen artifacts and by this postmortem's ability to
reconstruct the experiment without touching it:

- **Immutable evidence chain** — Phase 1, 2 and 3 bundles all re-verify byte-for-byte at a
  commit produced days after the fact.
- **Genuine blind adjudication** — identity mapping counterbalanced per case (Foundry was
  SYSTEM-A in 6 cases, SYSTEM-B in 6), with a structural leak gate.
- **Reproducible deterministic scoring** — the scorer was frozen and pushed *before* the
  mapping was opened, and `verify` recomputes the identical result.
- **Authority separation** — builder ≠ verifier, architect ≠ judge, adjudicator ≠ contestant.
- **No-reroll discipline** — 24/24 slots valid on first attempt, 0 retries, 0 reruns.
- **A falsifiable evaluation that actually falsified something.** The experiment was designed
  so Foundry could lose, and it did. That is the machinery working.

**This distinction must not be used to soften the result.** Foundry built an excellent
instrument and the instrument returned an unfavourable reading about the Intent Intelligence
worker. The platform result does not offset the worker result.

### The original bet

> *Persistent evidence-backed Intent Intelligence plus bounded architecture should beat
> competent one-shot frontier analysis on material gap control.*

**Verdict: `FALSIFIED_IN_THIS_FORM`.**

Not `NOT_VALIDATED`, because the bet was not merely unproven — its central mechanism was
tested where it should have been strongest and produced no advantage. Foundry's architecture
was expected to pay off on conflicts, authority and staleness; both systems matched every one
of those concepts. It was expected to produce better *material* gap control; it produced
1.7× the redundancy and 2.5× the unsupported rate at 1.53× the cost.

Not `FALSIFIED` outright, because the specific form tested — a single-pass worker with a rich
output contract and no consolidation stage — is not the only form the thesis can take. The
postmortem identifies a concrete, evidence-backed mechanism (missing consolidation over an
ancestry signal the system already computes) whose repair is testable. The bet as *architected
in v1* is dead. The bet as *stated* is still open, and is now falsifiable in a sharper way.

---

## 20. Final Decision

```text
Intent Intelligence v1 is now frozen.

Do not tune it. Do not rerun it. Do not re-adjudicate it.

The evidence does NOT support proceeding directly to the Decision/Architecture Engine.

The next recommended Foundry milestone is:

    Intent Intelligence v2 — Normalized Semantic Identity and Consolidation

because:

    The measured failure is entirely post-discovery, and its mechanism is directly
    observed rather than inferred: 95.5% of Foundry's redundant gaps share a
    semantic-proposal ancestor with the prediction they duplicate, against a 34.8%
    base rate, and 0 of 44 duplicate pairs share a GapKind while only 3 of 44 share
    a subject_key. Foundry already computes the signal that identifies its own
    duplicates and never uses it, because it has no identity strong enough to merge
    on safely and no stage in which merging would happen.

    A Decision/Architecture Engine consumes the gap stream. Today that stream carries
    26.70% redundancy, 4.71% unsupported material, and two ungrounded claims asserted
    at 0.72-0.82 confidence with valid-looking citations. Building a downstream engine
    on it would propagate that noise into architecture decisions and make the defect
    dramatically more expensive to find and fix. Fix the stream first.

    The fix is bounded: it changes what happens between discovery and emission, and it
    does not require touching discovery, which is already at frontier level.
```

### Architecture question the architect must settle

I am recording rather than deciding this, because it is above the analysis layer:

```text
ARCHITECTURE QUESTION: If a competent one-shot frontier model matches Foundry's
semantic coverage exactly - including every conflict, authority and staleness trap -
is per-cycle gap discovery still a differentiating capability for Foundry at all, or
is its durable value the persistent semantic state and the reconciliation loop built
on top of it?

Options:
- Intent Intelligence v2 (recommended above) - repair minimality, grounding and
  identity; re-test on a harder suite with a multi-dimensional gate. Consequence: the
  cheapest path to a testable claim, and it unblocks every downstream consumer by
  cleaning the stream they would inherit.
- Reposition Intent Intelligence as commodity discovery plus a Foundry-owned
  consolidation/normalization layer, and move differentiation downstream. Consequence:
  concedes the discovery benchmark permanently and shifts the thesis to persistent
  state, which 9K did not measure and cannot settle.

Blocked work:
- Any claim that Foundry's Intent Intelligence is differentiating.
- The Decision/Architecture Engine, which would consume this stream.
```

Both options require the same immediate work — normalized identity and consolidation — so the
recommended milestone is safe under either resolution. The question is what Foundry claims
afterwards.
