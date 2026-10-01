# gpt-6-astra — SEMANTIC_COMPLETENESS_VERIFICATION, exam v3: result and ACTOR scorer defect

**Standing (frozen): NOT_CERTIFIED, 74/75.** Evidence:
`tests/certification/evidence/openai/gpt-6-astra/semantic_completeness_verification_exam_v3/certification.json`
(commit `8db3ab8`, SHA-256 `0548fd47…0319`). Never re-scored, never edited, no certificate.
Exam `ie2-semantic-completeness-exam-v3` (`267cfadf…cb65`, seal `a666b24`); verifier policy
`ie2-semantic-completeness-v1` unchanged.

## The run

| | |
|---|---|
| Attempts | 25 cases × 3 = 75, single-shot; 74 PASS, 1 FAIL |
| v2-defect regressions | C02, C04, C24 COMPLETE 3/3; C10, C22 p2 OVERREACH 3/3 |
| Multi-gap | C09, C15, C16, C21 3/3; C05 2/3 |
| Tokens / latency | 70,002 in / 11,884 out; median 4.7 s, max 9.6 s; cost not reported |

## The one failure: a scorer defect

C05 attempt 1 (INCOMPLETE, correct) listed *"The permission to renew a loan is granted to a
member."* and the renewal condition. The sealed `AS_RENEWER` group enumerated role phrases
("may renew", "permitted to renew", …) and did not admit this correct nominal / passive actor
finding: `p1: no finding identifies the sealed ACTOR a member assertion`. Classified as a
harness/scorer defect; evidence preserved, nothing repaired during the run.

## Exam v4: the ACTOR role-binding law

`ie2-semantic-completeness-exam-v4`, `415f142fdea1e1c64fc1b937155f244909abcda6d5f0992ea03856e0781a176f`,
25 cases, 75 future live calls. Harness `tests/certification/_completeness_exam_v4.py`. Every
model-visible request, inventory and non-ACTOR marker group is v3's, carried by reference.

A missing ACTOR is identified only when one finding item binds the semantic role triple
**ACTOR → ROLE → GOVERNED ACTION**, through generic constructions over the assertion's sealed
groups (actor, action verb, action noun, modal, licence, grant; a complement for a restriction):

- `{actor} [modifier] [only] {modal} {action}` — "a member may renew", "only members may reserve"
- `{actor} is/are [only] {licence} to {action}` — "a member is permitted to renew"
- `{action | action noun} …gap… {grant} [det] {actor}` — "the permission to renew a loan is
  granted to a member", "reservation permission is limited to members"
- restriction only: `{complement} cannot / may not / is not {licence} to {action}` —
  "non-members cannot reserve"

No negation and no clause break (if, when, unless, but, …) may sit inside a bound span, so
polarity and attachment are part of the binding. An actor qualified as "other / another /
next / non-" never fills the actor slot (a defensive guard, not the law).

Co-occurrence never counts. The audit's false positives are permanent regressions and fail:
"renewal is only allowed if no other member has reserved the book", "Renewal is permitted only
when the book is not reserved by another member.", "Reservations by a member with fines can be
cancelled." A finding for the other gap therefore never satisfies the actor gap; every sealed
missing assertion must still be found (C05 actor + condition, C16 actor + cancellation).

ACTOR audit: of 8 ACTOR assertions, 6 are REPRESENTED (C02, C04, C09, C14, C22 p2, C24) and
seal no finding; 2 are scored (C05 permission, C16 restriction). All six frozen v3 C05 / C16
findings, including C05 attempt 1, identify their actor under v4.

**History:** v1 PREPARED_NEVER_SAT; v2 LIVE_NOT_CERTIFIED 66/75; v3 LIVE_NOT_CERTIFIED 74/75; v4
the candidate exam.
