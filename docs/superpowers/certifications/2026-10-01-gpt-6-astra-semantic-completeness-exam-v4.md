# gpt-6-astra — SEMANTIC_COMPLETENESS_VERIFICATION, exam v4: result and two scorer defects

**Standing (frozen): NOT_CERTIFIED, 72/75.** Evidence:
`tests/certification/evidence/openai/gpt-6-astra/semantic_completeness_verification_exam_v4/certification.json`
(commit `d02646f`, SHA-256 `e1285e6d…1e06`). Never re-scored, never edited, no certificate.
Exam `ie2-semantic-completeness-exam-v4` (`415f142f…176f`, seal `92880bd`); verifier policy
`ie2-semantic-completeness-v1` unchanged.

No wrong verdict of any kind, no protocol and no infrastructure failure. Every v3-corrected case
(C02, C04, C24 COMPLETE; C10, C22 p2 OVERREACH) and C16, C21 passed 3/3. Tokens 70,002 in /
12,497 out; latency median 4.9 s, max 14.1 s; cost not reported.

## The three failures: correct answers, rejected by the scorer

| Attempt | Finding | Why the sealed scorer rejected it |
|---|---|---|
| C05/2 | "A member is the actor permitted to renew the loan." | v4's licence construction `{actor} is {licence} to {action}` admitted no appositive role noun ("the actor") after the copula |
| C05/3 | "The member is the actor permitted to renew the loan." | same |
| C17/1 | "The proposition states a loan lasts two weeks (14 days), but CLM-1 states 21 days." | v2's echo rule refused any item containing the whole proposition ("A loan lasts two weeks."), though it names the conflicting 21 days |

## Exam v5: a scorer correction only

`ie2-semantic-completeness-exam-v5`, `88b69c45dd7f508c4068f753b3942febe2d39f4548fc1e30995dfbb8cd9ed99a`,
25 cases, 75 future live calls. Harness `tests/certification/_completeness_exam_v5.py`. Every
model-visible request is v4's byte for byte (sealed by SHA-256 per case); every inventory, role
and marker group is v4's, carried by reference.

- **Appositive role noun.** The ACTOR role triple stands. Its licence construction admits one
  appositive naming the role holder: `{actor} is/are [only] [the] {actor | one | person |
  people | party …} {licence} to {action}`. Polarity, clause-break, bystander and
  complement rules are unchanged; "A member is the actor who cancelled the renewal" fails.
- **Echo law.** Each finding item is split at every occurrence of the proposition text; only
  the remaining segments may identify the sealed region, each on its own (no phrase forms
  across a removed echo). A pure echo, with or without a prefix, leaves nothing.
- **Claim side of a contradiction.** Every CONTRADICTED assertion seals what names the claim's
  side (C11 15; C17 21 days; C23 the issuing branch), anchored in the claims and absent from the
  proposition. Naming only the proposition's own value ("The proposition says 14 days.") never
  identifies a contradiction.

## The pre-seal historical replay gate

Every recorded Astra finding of exams v2, v3 and v4 is replayed (210 attempts, 225
attempt × proposition rows; the five v2 payloads v3 replaced — C02, C04, C10, C22, C24 — have no
v5 counterpart and are named as not replayable). Each must keep the result its own exam's
scorer gave it. Exactly four change, all FAIL → PASS, all sealed as expected:

| Exam | Attempt | Finding |
|---|---|---|
| v3 | C05/1 | "The permission to renew a loan is granted to a member." |
| v4 | C05/2 | "A member is the actor permitted to renew the loan." |
| v4 | C05/3 | "The member is the actor permitted to renew the loan." |
| v4 | C17/1 p2 | "The proposition states a loan lasts two weeks (14 days), but CLM-1 states 21 days." |

The seal writer and the live module's seal check both refuse while the gate reports any other
change. The replay is diagnostic: v2 66/75, v3 74/75 and v4 72/75 stand as recorded.

**History:** v1 PREPARED_NEVER_SAT; v2, v3, v4 LIVE_NOT_CERTIFIED; v5 the candidate exam.
