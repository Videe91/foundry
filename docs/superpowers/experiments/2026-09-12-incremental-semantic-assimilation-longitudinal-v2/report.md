# Intent Intelligence v2 — Incremental Semantic Assimilation (Longitudinal Dogfood)

- experiment_version: `intent-v2-longitudinal-assimilation-v2`
- frozen_code_sha: `66ef0f1d31784d050b4d862c6c961d5c9051f25b` · run_head_sha: `6567425bce386d73745f7b809fc3133861f3aa52`
- semantic_output_schema_sha256: `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`
- run_status: **COMPLETED**
- failure: none

## Calls per arm per T

| arm | T | status | calls | in tok | out tok | cost USD | error |
|---|---|---|---|---|---|---|---|
| F | T1 | COMPLETED | 2 | 37243 | 7846 | 0.203402 | - |
| F | T2 | COMPLETED | 2 | 44187 | 7362 | 0.274446 | - |
| F | T3 | COMPLETED | 2 | 25125 | 3146 | 0.181656 | - |
| F | T4 | COMPLETED | 2 | 54814 | 5668 | 0.324170 | - |
| R | T1 | COMPLETED | 2 | 37104 | 7878 | 0.201810 | - |
| R | T2 | COMPLETED | 2 | 66536 | 7961 | 0.248602 | - |
| R | T3 | COMPLETED | 2 | 79451 | 5614 | 0.294202 | - |
| R | T4 | COMPLETED | 2 | 120436 | 6923 | 0.389900 | - |

- calls: F=8 R=8 total=16 (ceiling 16)
- input tokens after T1: F=124126 R=266423
- total cost: 2.118188 USD (ceiling 8.00) · within_ceiling=True
- persistent_unchanged_reread_count: 0
- replay: state=True view=True

## Readiness per scope per T (Arm F)

| T | scope | ready | closure_closed | semantic_blockers_clear | stale | pending material | disputed | open |
|---|---|---|---|---|---|---|---|---|
| T1 | constitution | False | False | True | 0 | 0 | 0 | 0 |
| T1 | intent-engine | False | False | True | 0 | 0 | 0 | 0 |
| T2 | constitution | False | False | True | 0 | 0 | 0 | 0 |
| T2 | intent-engine | False | False | False | 0 | 1 | 0 | 0 |
| T3 | constitution | False | False | True | 0 | 0 | 0 | 0 |
| T3 | intent-engine | False | False | False | 0 | 1 | 0 | 0 |
| T4 | constitution | False | False | True | 0 | 0 | 0 | 0 |
| T4 | intent-engine | False | False | False | 0 | 2 | 0 | 0 |

## Authorizations

| T | track | pending judgment | decision | not offered | submitted |
|---|---|---|---|---|---|
| T2 | - | `JDG-a52fa1de-c823-4094-abb1-34959125ee39` | - | UNTRACKED | - |
| T2 | B | `JDG-c6d593b4-a126-406d-98d2-23f165af0c9f` | AGREE | - | `judgment-67c752e2fbfc961f` |
| T3 | - | `JDG-a52fa1de-c823-4094-abb1-34959125ee39` | - | UNTRACKED | - |
| T4 | - | `JDG-a52fa1de-c823-4094-abb1-34959125ee39` | - | UNTRACKED | - |

## Verdicts

Architect-adjudicated expectations are `null` until adjudicated in a separate commit.

| id | adjudicator | verdict | note |
|---|---|---|---|
| E1 | architect | null | - |
| E2 | architect | null | - |
| E3 | architect | null | - |
| E4 | architect | null | - |
| E5 | architect | null | - |
| E6 | deterministic | FAIL | Track A root judgment was never superseded during the run; the unconditional expectation did not hold (no blast radius to check). |
| E7 | deterministic | FAIL | Track A root judgment was never superseded during the run; no stale descendants existed for the affected scope to report. |
| E8 | architect | null | - |
| E9 | architect | null | - |
| E10 | deterministic | PASS | Deterministic half only (request log: no EQUIVALENT/DISTINCT allowed in any call). The duplicate-address count for tracked loci is architect-adjudicated and is not decided here. |
| E11 | deterministic | PASS | state_matches=True; view_matches=True; step_views_reproduced=True; final_revision_matches=True |
| E12 | deterministic | NOT_APPLICABLE | No supersession was declined during the run; precondition never arose. |

_Forensic record only. Semantic quality is not assessed here._
