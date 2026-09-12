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

## Verdicts (FINAL — architect adjudication recorded 2026-09-12)

Architect adjudication of E1–E5, E8, E9 and the E10 duplicate-address half is recorded in
`verdicts.json`; the deterministic verdicts E6, E7, E11 and E12 are preserved verbatim from
the run. Zero live calls were made in adjudication.

| id | adjudicator | verdict | note |
|---|---|---|---|
| E1 | architect | **FAIL** | The live Track C designation is ADDR-f2714e74c6dd26c2 / JDG-a777c96a-74b4-4c36-b862-94f18126dee1, and that designated object already existed in T1. Do not post-hoc redefine C. |
| E2 | architect | **FAIL** | At T2 the model did bind the A and B observations to their T1 addresses, but the materially corrected Track A referential-identity interpretation was also created as a new durable address ("Referential identity" / "post-admission determinism") rather than being represented solely as an evolution of the designated A address. Thus the "not created anew" condition does not hold. |
| E3 | architect | **FAIL** | Track B received a new corrected claim at its designated address. Track A did not. The T1 A claim was supported with EV-T2-01, while the corrected interpretation was asserted at the newly-created referential-identity address. |
| E4 | architect | **PASS** | The T1 claims at A and B remain historically present in state after T2. Track B's old judgment is superseded/inactive but not destroyed; Track A's old claim also remains. |
| E5 | architect | **PASS** | No old tracked interpretation was silently retired. Track B's old interpretation becomes inactive only through the exact human-authorized SUPERSEDE. Track A was never superseded. This expectation is the authorization/safe-transition property; E2/E3 capture A's missed correction. |
| E6 | deterministic | **FAIL** | Track A root judgment was never superseded during the run; the unconditional expectation did not hold (no blast radius to check). |
| E7 | deterministic | **FAIL** | Track A root judgment was never superseded during the run; no stale descendants existed for the affected scope to report. |
| E8 | architect | **FAIL** | At T3 Arm F did not establish the preregistered C semantic locus "identity of Provenance.source_event_ids" with a claim describing the actual defective behavior. The T3 outputs contain generic reducer/state/identity/traceability semantics but do not identify that _claim_provenance placed EvidenceItem IDs into Provenance.source_event_ids. |
| E9 | architect | **FAIL** | At T4 Arm F identified the corrected provenance identifier law, but created a new "SemanticClaim \| provenance identifier families" address rather than binding the correction to the designated Track C root. It did not assert the required corrected claim at C plus propose SUPERSEDE of the T3 C claim. |
| E10 | architect | **FAIL** | COMBINED FINAL VERDICT. Deterministic request-log half: PASS (no EQUIVALENT or DISTINCT was requested in any of the 16 calls; F:requests=8, R:requests=8). Architect duplicate-address half: FAIL — Track A's corrected referential-identity meaning was materialized as a separate durable address instead of only reusing/evolving the designated Track A address, so the duplicate-address count for tracked semantic loci is not zero. Combined verdict: FAIL. |
| E11 | deterministic | **PASS** | state_matches=True; view_matches=True; step_views_reproduced=True; final_revision_matches=True |
| E12 | deterministic | **NOT_APPLICABLE** | No supersession was declined during the run; precondition never arose. |

### Decision (frozen `decision_rule`, spec §34)

- **result: `FAIL`**
- failing: `E1, E2, E3, E6, E7, E8, E9, E10`
- Token comparison (F input tokens T2–T4 < R input tokens T2–T4): **124126 < 266423 = PASS**
- Material-error comparison (F ≤ R): **2 <= 2 = PASS**
- declined_any = false → E12 NOT_APPLICABLE, excluded from the conjunction
- No `TOKENS:F>=R`, `ERRORS:F>R` or `UNADJUDICATED:*` item.

Material-error counting (unique material semantic failures at the tracked checkpoints, not
every downstream consequence of one failure):

- F (2): (1) Track A/T2 semantic fork instead of correction at the existing locus;
  (2) Track C/T3 material provenance defect not identified.
- R (2): (1) Track C/T3 material provenance defect not identified; (2) Track C/T4 represents
  the historical defective and corrected interpretations as simultaneously live at one
  locus without semantic reconciliation/supersession.

### Architect notes on the failures

- **E1** — the live Track C designation (`ADDR-f2714e74c6dd26c2` /
  `JDG-a777c96a-74b4-4c36-b862-94f18126dee1`) already existed in T1; C is not redefined
  post hoc.
- **E2** — A and B observations were bound to their T1 addresses at T2, but the corrected
  Track A referential-identity interpretation was also created as a new durable address
  ("Referential identity" / "post-admission determinism"); "not created anew" does not hold.
- **E3** — Track B received a new corrected claim at its designated address; Track A did not
  (the T1 A claim was supported with EV-T2-01 and the corrected interpretation was asserted
  at the newly created address).
- **E6 / E7** — deterministic: the Track A root judgment was never superseded, so the
  preregistered blast-radius transition and scoped stale-descendant reporting never arose.
- **E8** — at T3 Arm F did not establish the preregistered C locus ("identity of
  `Provenance.source_event_ids`") with a claim describing the actual defect (that
  `_claim_provenance` placed EvidenceItem IDs into `Provenance.source_event_ids`).
- **E9** — at T4 Arm F identified the corrected provenance identifier law but created a new
  "SemanticClaim | provenance identifier families" address instead of binding the
  correction to the designated Track C root with a corrected claim plus SUPERSEDE of the T3
  C claim.
- **E10** — deterministic half PASS (no EQUIVALENT/DISTINCT requested); architect half FAIL
  (Track A's corrected meaning materialized as a separate durable address, so the
  duplicate-address count for tracked loci is not zero); combined FAIL.

### Conclusion

Persistent assimilation achieved substantial context reduction (F 124,126 vs R 266,423
input tokens over T2–T4) and replay/governance integrity (E11 PASS; every supersession
human-authorized; no declined proposal), but the preregistered longitudinal correctness
hypothesis **failed**: semantic correction/reuse was not reliable — in particular Track A
correction identity (a fork instead of an evolution of the designated locus) and Track C
defect/correction continuity (defect not identified at T3; correction not bound to C at T4).

_Forensic record. Raw evidence artifacts are unchanged._
