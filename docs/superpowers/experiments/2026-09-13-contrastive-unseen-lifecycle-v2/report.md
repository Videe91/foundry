# 9P2 unseen lifecycle -- raw run report

- experiment_version: intent-v2-contrastive-unseen-lifecycle-v2
- artifact_format_version: 1
- operational_status: ABORTED_PROVIDER
- operational_error: XAIProviderError: <_InactiveRpcError of RPC that terminated with: 	status = StatusCode.PERMISSION_DENIED 	details = "Your team dbaababb-9557-4e3d-bbf0-bd56c0a6d2ed has either used all available credits or reached its monthly spending limit. To continue making API requests, please purchase more credits or raise your spending limit." 	debug_error_string = "PERMISSION_DENIED:Your team dbaababb-9557-4e3d-bbf0-bd56c0a6d2ed has either used all available credits or reached its monthly spending limit. To continue making API requests, please purchase more credits or raise your spending limit." >
- frozen_core_sha: 1f89fc86cda463da676bf45603b86a7dcb458452

## Schedule

| position | T | arm | status | project_id | requests | error |
|---|---|---|---|---|---|---|
| 0 | T1 | F | FAILED | PROJ-9P2-F | 1 | XAIProviderError: <_InactiveRpcError of RPC that terminated with: 	status = StatusCode.PERMISSION_DENIED 	details = "Your team dbaababb-9557-4e3d-bbf0-bd56c0a6d2ed has either used all available credits or reached its monthly spending limit. To continue making API requests, please purchase more credits or raise your spending limit." 	debug_error_string = "PERMISSION_DENIED:Your team dbaababb-9557-4e3d-bbf0-bd56c0a6d2ed has either used all available credits or reached its monthly spending limit. To continue making API requests, please purchase more credits or raise your spending limit." > |
| 1 | T1 | A | NOT_RUN | PROJ-9P2-A | 0 | null |
| 2 | T1 | R | NOT_RUN | PROJ-9P2-R-T1 | 0 | null |
| 3 | T2 | A | NOT_RUN | PROJ-9P2-A | 0 | null |
| 4 | T2 | R | NOT_RUN | PROJ-9P2-R-T2 | 0 | null |
| 5 | T2 | F | NOT_RUN | PROJ-9P2-F | 0 | null |
| 6 | T3 | R | NOT_RUN | PROJ-9P2-R-T3 | 0 | null |
| 7 | T3 | F | NOT_RUN | PROJ-9P2-F | 0 | null |
| 8 | T3 | A | NOT_RUN | PROJ-9P2-A | 0 | null |
| 9 | T4 | F | NOT_RUN | PROJ-9P2-F | 0 | null |
| 10 | T4 | A | NOT_RUN | PROJ-9P2-A | 0 | null |
| 11 | T4 | R | NOT_RUN | PROJ-9P2-R-T4 | 0 | null |

## Budget

- frontier_calls: 1
- judge_calls: 0
- human_authorizations: 0
- provider_cost_usd: 0

## Roots

| arm | project_id | key | seed | status | address_id | reason |
|---|---|---|---|---|---|---|
| F | PROJ-9P2-F | - | - | (none) | null | - |
| A | PROJ-9P2-A | - | - | (none) | null | - |

## Authorizations

| arm | T | root | target_judgment_id | outcome | submitted_judgment_id |
|---|---|---|---|---|---|

## Deterministic integrity verdicts (C3)

| id | passed | detail |
|---|---|---|
| F1 | null | not computed: run ABORTED_PROVIDER |
| F2 | null | architect adjudication pending |
| F3 | null | not computed: run ABORTED_PROVIDER |
| F4 | null | not computed: run ABORTED_PROVIDER |
| F5 | null | not computed: run ABORTED_PROVIDER |
| F6 | null | not computed: run ABORTED_PROVIDER |
| F7 | null | not computed: run ABORTED_PROVIDER |
| F8 | null | not computed: run ABORTED_PROVIDER |

## Scientific decision

Semantic checkpoints C1/C2/C3 (F/A/R), F2 and the material-error totals are
`null` in `verdicts.json`; they are architect adjudication after the raw freeze.

scientific_decision = null (architect adjudication pending)
