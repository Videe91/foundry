# 9P2 unseen lifecycle -- raw run report

- experiment_version: intent-v2-contrastive-unseen-lifecycle-v3
- artifact_format_version: 1
- operational_status: COMPLETED
- operational_error: null
- frozen_core_sha: 1f89fc86cda463da676bf45603b86a7dcb458452

## Schedule

| position | T | arm | status | project_id | requests | error |
|---|---|---|---|---|---|---|
| 0 | T1 | F | COMPLETED | PROJ-9P2-F | 2 | null |
| 1 | T1 | A | COMPLETED | PROJ-9P2-A | 2 | null |
| 2 | T1 | R | COMPLETED | PROJ-9P2-R-T1 | 2 | null |
| 3 | T2 | A | COMPLETED | PROJ-9P2-A | 2 | null |
| 4 | T2 | R | COMPLETED | PROJ-9P2-R-T2 | 2 | null |
| 5 | T2 | F | COMPLETED | PROJ-9P2-F | 2 | null |
| 6 | T3 | R | COMPLETED | PROJ-9P2-R-T3 | 2 | null |
| 7 | T3 | F | COMPLETED | PROJ-9P2-F | 2 | null |
| 8 | T3 | A | COMPLETED | PROJ-9P2-A | 2 | null |
| 9 | T4 | F | COMPLETED | PROJ-9P2-F | 2 | null |
| 10 | T4 | A | COMPLETED | PROJ-9P2-A | 2 | null |
| 11 | T4 | R | COMPLETED | PROJ-9P2-R-T4 | 2 | null |

## Budget

- frontier_calls: 24
- judge_calls: 0
- human_authorizations: 4
- provider_cost_usd: 0.490336000000000016

## Roots

| arm | project_id | key | seed | status | address_id | reason |
|---|---|---|---|---|---|---|
| F | PROJ-9P2-F | A | EV-K-A1 | DESIGNATED | ADDR-41301eebc689f79c | DESIGNATED |
| F | PROJ-9P2-F | B | EV-K-B1 | DESIGNATED | ADDR-f91a4e3e986396e4 | DESIGNATED |
| F | PROJ-9P2-F | N | EV-K-N1 | DESIGNATED | ADDR-8f0b1b961ed551fa | DESIGNATED |
| A | PROJ-9P2-A | A | EV-K-A1 | DESIGNATED | ADDR-744793b4596c8be1 | DESIGNATED |
| A | PROJ-9P2-A | B | EV-K-B1 | DESIGNATED | ADDR-d4b6fce926bcfe94 | DESIGNATED |
| A | PROJ-9P2-A | N | EV-K-N1 | DESIGNATED | ADDR-b33579bb2afa002d | DESIGNATED |

## Authorizations

| arm | T | root | target_judgment_id | outcome | submitted_judgment_id |
|---|---|---|---|---|---|
| F | T2 | A | JDG-b1884cb0-70cd-4922-802d-c838886c2c71 | AGREED | judgment-a3b8e52a-bf7e-4cfe-b78b-1da9e33421f0 |
| F | T4 | B | JDG-d9a63f5f-42af-4f6e-a99d-53bc4f939047 | AGREED | judgment-516dce1d-cb39-4f97-9808-6b2b54ec41aa |
| A | T2 | A | JDG-3cb3ebb3-fa88-4af1-a4fa-162c201023ba | AGREED | judgment-18e298da-3d17-4af6-8042-2197233e098b |
| A | T4 | B | JDG-de624337-99d2-4d3b-8c9d-946c6776eeda | AGREED | judgment-cf7916b2-3090-4b91-90ac-f624f3c1bc63 |

## Deterministic integrity verdicts (C3)

| id | passed | detail |
|---|---|---|
| F1 | true | A/B/N DESIGNATED at pairwise-distinct address ids ['ADDR-41301eebc689f79c', 'ADDR-f91a4e3e986396e4', 'ADDR-8f0b1b961ed551fa'] |
| F2 | null | architect adjudication pending |
| F3 | true | every F request offered exactly the locked call-1/call-2 kind sets; no third request |
| F4 | true | 14 model-originated proposals cite only that call's evidence ids |
| F5 | true | every known address in 8 F requests is scope-eligible; known claims and touched addresses stay within each request's known addresses |
| F6 | true | F completed T1-T4 with exactly 8 requests, two per T (1, 2), no duplicate identity |
| F7 | true | replay of 39 F events reproduces final state and view |
| F8 | true | 2 applied SUPERSEDE judgment(s), each a human AGREE (APPLY/HUMAN_AUTHORITY) of an earlier pending model proposal; no model SUPERSEDE applied |

## Scientific decision

Semantic checkpoints C1/C2/C3 (F/A/R), F2 and the material-error totals are
`null` in `verdicts.json`; they are architect adjudication after the raw freeze.

scientific_decision = null (architect adjudication pending)
