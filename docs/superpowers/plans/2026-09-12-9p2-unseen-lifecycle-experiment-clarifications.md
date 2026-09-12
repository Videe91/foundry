# 9P2 Unseen Lifecycle Experiment — Implementation Plan Clarifications

**Status:** Binding implementation-plan self-review corrections. This file changes no scientific hypothesis, evidence, rubric, threshold, arm semantics, policy, or live authorization rule.

**Primary plan:** `docs/superpowers/plans/2026-09-12-9p2-unseen-lifecycle-experiment.md`

**Approved experiment spec:** `docs/superpowers/specs/2026-09-12-9p2-unseen-lifecycle-experiment-design.md`

The approved spec outranks both plan files.

## C1 — Leakage normalization is exact ASCII-whitespace collapse

The primary plan's prose around `split(" ")` is superseded by this exact rule.

Leakage comparison normalization is:

```python
_ASCII_WHITESPACE_RE = re.compile(r"[\t\n\v\f\r ]+")


def normalize_leakage_text(text: str) -> str:
    return _ASCII_WHITESPACE_RE.sub(" ", text.casefold()).strip()
```

Only ASCII whitespace is collapsed. Do not use default `str.split()` semantics, Unicode normalization, punctuation stripping, stemming, fuzzy matching, token similarity, or semantic matching.

Needle SHA256 is computed over the sorted tuple of **unnormalized sealed needle strings** in canonical JSON. Matching uses `normalize_leakage_text` on both needle and haystack, except grading labels which remain word-bounded after case folding.

## C2 — Gate 16 source scanning must be injectable during T4 and complete at final preflight

`answer_key_not_imported_by_request_path` must not silently skip a required request-path module because that module has not been created yet.

Implement the gate core as a pure function over an injected mapping:

```python
request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]
```

It parses every supplied source with `ast` and rejects direct imports of:

```text
foundry.experiments.contrastive_unseen.expectations
.contrastive_unseen.expectations
.expectations
```

or imports of named grading helpers from that module.

During T4 unit tests, pass explicit synthetic/source fixtures for the modules that exist at that task.

The final CLI preflight MUST supply and require all six real request-path files:

```text
src/foundry/experiments/contrastive_unseen/timeline.py
src/foundry/experiments/contrastive_unseen/designation.py
src/foundry/experiments/contrastive_unseen/authority.py
src/foundry/experiments/contrastive_unseen/ablation.py
src/foundry/experiments/contrastive_unseen/records.py
src/foundry/experiments/contrastive_unseen/runner.py
```

If any required file is missing or unreadable at final preflight, gate 16 FAILS. `integrity.py`, `leakage.py`, `artifacts.py`, and the seal-preparation script may import `expectations.py` because they are grading/preflight/artifact code and are not passed through the provider request path.

`runner.py` must not import `artifacts.py`, `integrity.py`, or `leakage.py`; the CLI owns those outer layers.

## C3 — Raw deterministic F-integrity verdicts are exact

The raw run must not let implementation authors invent semantic verdicts. Before architect adjudication, only these deterministic F verdicts are computed:

### F1 — unique T1 root addresses

PASS iff F's A, B, and N roots are all `DESIGNATED` **and their three address ids are pairwise distinct**.

This compares opaque ids only; it does not judge semantic equivalence.

### F2 — stable control

Always `null` / architect-unadjudicated in the raw result. Determining whether N's meaning remained materially unchanged is semantic.

### F3 — allowed operation boundary

PASS iff every completed F T has exactly two requests; Call 1 allowed kinds equal exactly `{BIND_TO_ADDRESS, CREATE_ADDRESS}`; Call 2 allowed kinds equal exactly `{SUPPORTS_CLAIM, ASSERT_CLAIM, SUPERSEDE, CONFLICTS_WITH}`; no F request contains `EQUIVALENT` or `DISTINCT`; and no third F request exists for any T.

### F4 — non-citable historical context

PASS iff, for every F call, every evidence id referenced by every model-originated proposal from that call is present in that exact request's `ReasoningRequest.evidence` ids. Check proposal evidence references structurally for `CREATE_ADDRESS`, `BIND_TO_ADDRESS`, `ASSERT_CLAIM`, and `SUPPORTS_CLAIM`, plus `visible_evidence_ids`. A predecessor id that appears only in `comparison_context` is insufficient.

### F5 — scoped visibility

PASS iff every `known_address` in every F request satisfies `address.scope == () or "kestrel-delivery" in address.scope`; every `known_claim.address_id` is one of that request's known-address ids; and every transition `touched_address_id` is among that request's known-address ids. No semantic wording is inspected.

### F6 — exactly two calls, no retry

PASS iff F completed T1–T4 and has exactly 8 request records, exactly two per T with call numbers `(1, 2)`, with no duplicate request identity and no retry/fallback record.

### F7 — exact replay

PASS iff replaying F's final ledger from an empty state reproduces the serialized final F `IntentState` and derived `CurrentSemanticView` exactly.

### F8 — governance boundary

PASS iff every applied F `SUPERSEDE` that changed semantic state was authored by the frozen human fingerprint `human:human://architect@intent-v2-9p2-unseen-v1`, routed `APPLY` with `HUMAN_AUTHORITY`, and has the same `proposal_signature` as a previously recorded pending model-originated supersede proposal. No model-originated `SUPERSEDE` may itself be the applied state-changing judgment.

These checks are structural/governance checks only. They do not decide whether the superseded interpretation was semantically the correct one to retire; that remains C1/C3 architect adjudication.

## C4 — Prefer typed experiment serialization records

Where the primary plan says `tuple[dict[str, object], ...]` for evidence/manifest-facing records, use experiment-specific frozen Pydantic models instead of free-form dictionaries unless the object is the final JSON serialization boundary.

At minimum define a typed `EvidenceRecord` for `evidence_records()` and typed models for `ExperimentManifest`, leakage results, gate results, request records, root designations, authorization records, and runner results.

`expectations_document()` may serialize a typed `ExpectationsDocument`; its on-disk JSON is still the canonical approved answer-key/rubric data.

## C5 — No raw scientific decision before architect adjudication

For a COMPLETED raw run:

- semantic checkpoint C1/C2/C3 verdicts for F/A/R remain `null`;
- F2 remains `null`;
- material-error totals remain `null`;
- `scientific_decision` remains `null` even when deterministic F1/F3–F8 are known.

The harness MUST NOT call `decision_rule` on invented/default semantic values.

After the raw-run commit is frozen, architect adjudication supplies the missing semantic verdicts/counts in a separate allowed adjudication commit, and only then may `decision_rule` produce PASS / INCONCLUSIVE / FAIL.

## C6 — Final plan precedence

Implementation precedence is:

1. `FOUNDRY_CONSTITUTION.md`
2. approved unseen-lifecycle experiment spec
3. pre-experiment architecture amendment
4. approved 9P2 core design
5. this clarification file
6. primary implementation plan
7. implementation convenience

No live call is authorized by either plan file.