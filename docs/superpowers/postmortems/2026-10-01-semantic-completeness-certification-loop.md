# Semantic completeness: the v2-v5 certification loop, and the structured verifier (policy v2)

## Frozen history (never re-scored)

| Exam | Live result (openai/gpt-6-astra) | Evidence | What failed |
|---|---|---|---|
| v1 | PREPARED_NEVER_SAT | — | — |
| v2 | NOT_CERTIFIED 66/75 | `e1833d4` | exam construction: C02, C24, C10 expectations contradicted the verifier law |
| v3 | NOT_CERTIFIED 74/75 | `8db3ab8` | scorer: "The permission to renew a loan is granted to a member." |
| v4 | NOT_CERTIFIED 72/75 | `d02646f` | scorer: "A/The member is the actor permitted to renew the loan."; echo rule on C17 |
| v5 | NOT_CERTIFIED 74/75 | `88eae18` | scorer: "The renewal permission applies to a member." |

From v3 onward the verifier returned **no wrong verdict at all**. Every failure was a correct
answer whose English the deterministic scorer did not recognise. Each exam added a phrase form
or a grammar rule; each live run produced a new correct wording. The loop was stopped.

## Where v1's design caused the loop

`ie2-semantic-completeness-v1` asks the verifier to name each defect in free text
(`missing` / `unsupported` / `contradictory`). Certifying that verifier then required Python to
decide whether an English sentence named the right meaning — marker groups, synonym lists, an
actor grammar, an echo rule. That is semantic interpretation done by deterministic code, which
the architecture assigns to the model, and it does not converge.

## Policy v2: structured findings

**Principle.** The model understands meaning; deterministic code validates references and
structure.

A `StructuredCompletenessReport` (`report_format: ie2-semantic-completeness-report.v2`) gives,
per proposition, a verdict, its `claim_refs` and `findings`. Each `SemanticFinding` is:

| field | MISSING | UNSUPPORTED | CONTRADICTORY |
|---|---|---|---|
| `kind` (14 operative kinds) | required | required | required |
| `proposition_evidence` (verbatim quote) | required | — | required |
| `claim_ref` | — | required | required |
| `claim_evidence` (verbatim quote of that claim) | — | required | required |
| `explanation` | optional free text, never read | | |

Kinds: ACTOR, PERMISSION, OBLIGATION, QUANTITY_LIMIT, TIMING, TIME_ANCHOR, DEADLINE, CONDITION,
ELIGIBILITY, CONSEQUENCE, EXCEPTION, DESTINATION, REPETITION, CHANNEL — the operative assertions
the v1 instruction already names, plus the time anchor and channel that the exams showed are
operative. A duration such as "two weeks" is TIMING.

**Evidence representation.** An exact quote, grounded deterministically: whole words, with case,
whitespace and punctuation folded and nothing else. Proposition evidence must occur in the
proposition's statement or one of its source sentences; claim evidence in the named claim's
subject, predicate or value. Character or token offsets were rejected: models copy text reliably
and count positions badly, so offsets would move brittleness rather than remove it. A quote
cannot cite text that does not exist; a paraphrase is never grounded.

**Deterministic checks (all; nothing else):** every proposition judged exactly once on exactly
its claims; every quote grounded where it says; every `claim_ref` a claim of that proposition;
each direction carries exactly its fields; no duplicate finding; no span given two directions
for one kind; the verdict follows from the findings (CONTRADICTORY > INCOMPLETE > OVERREACH;
COMPLETE has none); the report is in the format of the verifier's recorded policy. An invalid
report is `VERIFIER_OUTPUT_INVALID`: a FAIL, nothing of Call 2 applied.

**What deterministic code no longer does:** decide whether two phrasings mean the same thing;
marker groups, synonyms, actor grammar templates, echo rules.

## Versioning

* **Verifier policy:** new, `ie2-semantic-completeness-v2` (instruction SHA-256
  `07296c5e…9710`). v1 (`56b753a9…`) is unchanged and still served by
  `ModelRuntimeCompletenessVerifier`; v2 by `ModelRuntimeStructuredCompletenessVerifier`. Same
  task (`SEMANTIC_COMPLETENESS_VERIFICATION`), same tier, provider-neutral.
* **Durable record:** same event (`SEMANTIC_COMPLETENESS_RECORDED`); `CompletenessRecord.report`
  is `CompletenessReport | StructuredCompletenessReport`, and must be in the format of the
  recorded `verifier.policy_version`. v1 JSON is unchanged and replays as before; v1 and v2
  records replay side by side. A report in the wrong format is recorded as no report (FAIL).
* **Pipeline:** `ie2-verified-assimilation-v1` unchanged — Call 1 → Call 2 → Call 3 → admission
  only on PASS; the Call-3 contract version travels in each record.
* **Open (not changed here):** model routing certifies by task only (`certified_tasks`), not by
  policy version, so a model registered for the task would be routed for either policy. No
  model is currently certified for this task.

## Certification without phrase matching (design; no exam built)

A non-COMPLETE answer passes only if the verdict is right and, for every sealed expected finding,
some finding has the sealed kind and direction, its proposition evidence covers the sealed source
region (an anchor quote from the statement or a source sentence) and no other expected region,
and its claim ref / claim evidence cover the sealed claim-side region. Offline, the recorded
v3/v4/v5 C05 wordings, v4 C17/1, and the C21, C16, C10, C11 and C23 findings all render to
structured answers that score this way, with no English interpreted
(`tests/certification/_structured_diagnostic.py`, diagnostic only).
