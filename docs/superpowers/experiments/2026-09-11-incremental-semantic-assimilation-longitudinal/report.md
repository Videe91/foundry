# Intent Intelligence v2 — Incremental Semantic Assimilation (Longitudinal Dogfood)

- experiment_version: `intent-v2-longitudinal-assimilation-v1`
- frozen_code_sha: `f017456a36628f3d897cc372439de5f81eabfc1a` · run_head_sha: `b7825d27b89f283942623bb22bb304cf90fe62f3`
- run_status: **FAILED**
- failure: `Arm F T1 failed: SemanticOutputError: model returned an inconsistent claim value: 1 validation error for ClaimValue
  Value error, UNDECIDED must not carry text or quantity [type=value_error, input_value={'kind': <ClaimValueKind....ty': None, 'unit': None}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/value_error`

## Calls per arm per T

| arm | T | status | calls | in tok | out tok | cost USD | error |
|---|---|---|---|---|---|---|---|
| F | T1 | FAILED | 2 | 36340 | 7555 | 0.223784 | `SemanticOutputError: model returned an inconsistent claim value: 1 validation error for ClaimValue
  Value error, UNDECIDED must not carry text or quantity [type=value_error, input_value={'kind': <ClaimValueKind....ty': None, 'unit': None}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/value_error` |
| F | T2 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: T1 failed` |
| F | T3 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: T1 failed` |
| F | T4 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: T1 failed` |
| R | T1 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: Arm F T1 failed` |
| R | T2 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: Arm F T1 failed` |
| R | T3 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: Arm F T1 failed` |
| R | T4 | NOT_RUN | 0 | 0 | 0 | 0.000000 | `stopped: Arm F T1 failed` |

## Readiness per scope per T (Arm F)

| T | scope | ready | closure_closed | semantic_blockers_clear | stale | pending material | disputed | open |
|---|---|---|---|---|---|---|---|---|
| T1 | constitution | False | False | True | 0 | 0 | 0 | 17 |
| T1 | intent-engine | False | False | True | 0 | 0 | 0 | 28 |
| T2 | constitution | False | False | True | 0 | 0 | 0 | 17 |
| T2 | intent-engine | False | False | True | 0 | 0 | 0 | 28 |
| T3 | constitution | False | False | True | 0 | 0 | 0 | 17 |
| T3 | intent-engine | False | False | True | 0 | 0 | 0 | 28 |
| T4 | constitution | False | False | True | 0 | 0 | 0 | 17 |
| T4 | intent-engine | False | False | True | 0 | 0 | 0 | 28 |

## Authorizations

| T | track | pending judgment | decision | not offered | submitted |
|---|---|---|---|---|---|

## Verdicts

Architect-adjudicated expectations are `null` until adjudicated in a separate commit.

| id | adjudicator | verdict | note |
|---|---|---|---|
| E1 | architect | null | - |
| E2 | architect | null | - |
| E3 | architect | null | - |
| E4 | architect | null | - |
| E5 | architect | null | - |
| E6 | deterministic | null | - |
| E7 | deterministic | null | - |
| E8 | architect | null | - |
| E9 | architect | null | - |
| E10 | deterministic | null | - |
| E11 | deterministic | null | - |
| E12 | deterministic | null | - |

_Forensic record only. Semantic quality is not assessed here._
