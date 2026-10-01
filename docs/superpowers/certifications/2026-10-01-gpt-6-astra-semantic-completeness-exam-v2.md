# gpt-6-astra — SEMANTIC_COMPLETENESS_VERIFICATION, exam v2: result and exam-construction defect

**Standing (frozen): NOT_CERTIFIED, 66/75.** Evidence:
`tests/certification/evidence/openai/gpt-6-astra/semantic_completeness_verification_exam_v2/certification.json`
(commit `e1833d4`, SHA-256 `ec509dfc…aa86`). Never re-scored, never edited, no certificate.

**Architecture decision (2026-10-01):** the three failures are an **exam-construction defect**.
The verifier policy `ie2-semantic-completeness-v1` — its instruction (`56b753a9…`), actor
completeness, verdict precedence, `CompletenessReport` (`3686a0fc…`), wire schema (`cc39ac45…`)
and runtime — is sufficient and **unchanged**. No `semantic-completeness-v2`, no new runtime
identity, no schema change. Only the certification exam changes: exam v3.

## The run

| | |
|---|---|
| Model | `openai/gpt-6-astra` (`models.retrieve`: id `gpt-6-astra`, owned_by `system`) |
| Exam | `ie2-semantic-completeness-exam-v2`, `c6f9ca5b…338d`, seal `49e91e4` |
| Attempts | 25 cases × 3 = 75, single-shot, `max_retries=0`, high / standard / 180 s / no guard |
| Result | 66 PASS, 9 FAIL: C02 ×3, C10 ×3, C24 ×3. No protocol or infrastructure failure |
| Tokens | 69,951 in / 13,781 out; cost not reported; latency median 5.5 s, max 12.3 s |

## Why v2 was defective

The verifier law lists **an actor** among operative assertions ("an actor, an obligation or
permission, a quantity or limit, a timing, a deadline, …") and resolves several defects as
**CONTRADICTORY > INCOMPLETE > OVERREACH**. v2's expected verdicts were hand-authored without
accounting for every operative region of each proposition.

**C02 (sealed COMPLETE).** "A member may hold at most four reservations at once." Claim:
`Library reservations | maximum_active_reservations | 4`. The proposition names the member as
actor; no claim states it (read literally the claim is a library-wide cap). Under
`ie2-semantic-completeness-v1` the exact v2 payload is legitimately **INCOMPLETE**. Astra: 3/3
INCOMPLETE, "the limit … applies per member".

**C24 (sealed COMPLETE).** "Members may print up to 20 pages a day free of charge; further pages
cost 0.10 EUR each." Claims: `Printing | free_print_quota | …`, `Printing |
additional_page_price | …`. Same defect: the member actor is in the proposition and in no claim.
Legitimately **INCOMPLETE**. Astra: 3/3 INCOMPLETE, members as the actors.

**C10 (sealed OVERREACH).** "A damage report made more than 7 days after return is refused."
Claim value: "refused after 7 days, and the member is suspended". The claim adds an unsupported
suspension (OVERREACH) **and** drops the "after return" anchor (INCOMPLETE). Precedence makes
the exact v2 payload **INCOMPLETE**; OVERREACH was wrong. Astra: 3/3 INCOMPLETE, listing both
the anchor (missing) and the suspension (unsupported).

Astra's v2 answers are **not** reinterpreted as passes. Exam v2 remains frozen and NOT_CERTIFIED.

## The coherence audit of all 25 cases (before v3)

| Case | Finding | Decision |
|---|---|---|
| C22 p2 (sealed OVERREACH) | "A member may borrow up to ten items at once" vs `Library loans \| maximum_loans \| 10 items, only with a valid photo ID`: the C02 actor defect, so missing + unsupported → INCOMPLETE. Astra answered OVERREACH 3/3 (passed) | Fix like C10: actor explicit, photo ID the only defect, OVERREACH |
| C04 (sealed COMPLETE) | Actor only presupposed by "no **other** member has reserved" | Option B: make the renewing member explicit |
| C05, C09, C15, C16, C21 | Secondary missing assertions beside the designed gap (actor; under-16 eligibility; "of return" anchor; "only members"; "in the app"). Verdict still INCOMPLETE | Payloads carried unchanged; every sealed missing assertion must now be found |
| all others | coherent with the law and precedence | carried unchanged |

## Exam v3

`ie2-semantic-completeness-exam-v3`, `267cfadf1303c43252439b34ed14366cb94467080e5c3256ac8db729d3becb65`,
25 cases, 75 future live calls (3 independent runs per case, every one passing). Harness:
`tests/certification/_completeness_exam_v3.py`.

- **Semantic inventory (scorer-side only, never sent).** Each proposition's operative assertions
  — kinds ACTOR, OBLIGATION, PERMISSION, QUANTITY, TIMING, TIME_ANCHOR, DEADLINE, CONDITION,
  ELIGIBILITY, CONSEQUENCE, EXCEPTION, DESTINATION, REPETITION, CHANNEL — each REPRESENTED (by
  named claims), MISSING, UNSUPPORTED or CONTRADICTED, anchored to the proposition's and claims'
  text. Construction fails on an unanchored, unclassified or misclassified assertion and on any
  unclassified claim.
- **Derived verdict.** CONTRADICTED → CONTRADICTORY; else MISSING → INCOMPLETE; else UNSUPPORTED
  → OVERREACH; else COMPLETE. No verdict is authored.
- **Findings.** Every assertion in the derived verdict's region is a required finding with its
  own marker groups (v2's groups carried by reference). Several finding items may jointly cover
  them. v2's whole-word matcher, stuffing, echo and forbidden-interpretation rules are unchanged.
- **Corrections.** C02 `maximum_active_reservations_per_member`; C04 `maximum_renewals_per_member`;
  C24 `free_print_quota_per_member` / `additional_page_price_per_member`; C10 "refused if made
  more than 7 days after return, and the member is suspended"; C22 p2
  `maximum_loans_per_member` = "10 items at once, only with a valid photo ID". Every other
  model-visible payload is v2's, byte for byte; K-CREDIT (C21) is the frozen v6 request.
- **History.** v1 PREPARED_NEVER_SAT; v2 LIVE_NOT_CERTIFIED 66/75; v3 the candidate exam.
