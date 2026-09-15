# Locus-policy live validation -- raw run report

- experiment_version: intent-v2-locus-validation-v1
- artifact_format_version: 1
- policy_version: intent-v2-locus-v1
- prompt_sha256: e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1
- status: COMPLETED
- error: null

## Ledgers

| ledger | project_id | scope | status | deltas | requests | receipts | error |
|---|---|---|---|---|---|---|---|
| alpha | PROJ-LV-ALPHA | keyring | COMPLETED | 2 | 4 | 4 | null |
| beta | PROJ-LV-BETA | relay | COMPLETED | 2 | 4 | 4 | null |

## Budget

- frontier_calls: 8
- judge_calls: 0
- human_authorizations: 0
- provider_cost_usd: 0.301194000000000006

## Deterministic integrity verdicts (L1-L9)

| id | passed | applies_to | failed_ledgers | detail |
|---|---|---|---|---|
| L1 | true | alpha,beta | - | alpha: 2 completed delta(s) each made exactly calls (1, 2); beta: 2 completed delta(s) each made exactly calls (1, 2) |
| L2 | true | alpha,beta | - | alpha: 4 distinct request(s), at most two per delta; beta: 4 distinct request(s), at most two per delta; 8 request records == 8 frontier calls; no judge call |
| L3 | true | alpha,beta | - | alpha: every reference resolves against its exact request; no same-response id used (4 calls checked); beta: every reference resolves against its exact request; no same-response id used (4 calls checked) |
| L4 | true | alpha,beta | - | alpha: 1 completed ledger(s) replay exactly; beta: 1 completed ledger(s) replay exactly |
| L5 | true | alpha,beta | - | alpha: 4 request(s): snapshots, receipts and ledger events reconcile one-to-one; beta: 4 request(s): snapshots, receipts and ledger events reconcile one-to-one |
| L6 | true | alpha,beta | - | 2 SUPERSEDE proposal(s), none applied; 0 human authorizations |
| L7 | true | alpha,beta | - | identity guard never tripped |
| L8 | true | alpha,beta | - | provider cost 0.301194000000000006 USD <= 2.0 USD; 8 frontier calls <= 8 |
| L9 | false | alpha,beta | alpha,beta | alpha S01 FAILED ['EXTRA_DRAFT']; alpha V03 FAILED ['EXTRA_DRAFT']; beta S01 FAILED ['EXTRA_DRAFT'] |

## Case assertions (spec 7.1, deterministic)

| ledger | case_id | structural_passed | tags | detail |
|---|---|---|---|---|
| alpha | S01 | false | EXTRA_DRAFT | EXTRA_DRAFT: live claims at ADDR-ae0de307833fe2f5 = 4 (CLAIM-4595a59fd8389ce6, CLAIM-6e40a646df3777e1, CLAIM-a7a6fa6d5d7a5ba3, CLAIM-ded86e6bf830ecb3), expected 1 |
| alpha | V01 | true | - | all assertions hold |
| alpha | V02 | true | - | all assertions hold |
| alpha | V03 | false | EXTRA_DRAFT | EXTRA_DRAFT: live claims at ADDR-39dc382e48c93564 = 2 (CLAIM-3d2e4e5e5c85eb6c, CLAIM-51a89384b48e756a), expected exactly 1 citing EV-LV-A2-T2 |
| alpha | V04 | true | - | all assertions hold |
| alpha | V05 | true | - | all assertions hold |
| beta | S01 | false | EXTRA_DRAFT | EXTRA_DRAFT: live claims at ADDR-53ff2ec77ba59cb1 = 2 (CLAIM-2201c29c64ec55c0, CLAIM-66b6d8722274bac3), expected 1 |
| beta | V01 | true | - | all assertions hold |
| beta | V02 | true | - | all assertions hold |
| beta | V03 | true | - | all assertions hold |
| beta | V04 | true | - | all assertions hold |
| beta | V05 | true | - | all assertions hold |

## Outcome

The semantic assertions, notes, case outcomes and the outcome of the experiment
are `null` in `verdicts.json`; they are architect adjudication after the raw-run
commit (spec 11, 14).

experiment_outcome = LOCUS_POLICY_NOT_VALIDATED (architect adjudication over raw-run commit 17cc9f650a11e4f1dc0486a137b77cc4c6051ccc)

## Adjudication

- raw_run_commit_sha: 17cc9f650a11e4f1dc0486a137b77cc4c6051ccc
- rule_zero: false
- decision: LOCUS_POLICY_NOT_VALIDATED

### Semantic assertions (spec 7.2)

| assertion | alpha | beta |
|---|---|---|
| A-S01 | true | true |
| A-V01 | true | true |
| A-V02 | true | true |
| A-V03 | true | true |
| A-V05 | true | true |

### Case outcomes (spec 14)

| ledger | case_id | structural_passed | semantic_answer | passed | tags |
|---|---|---|---|---|---|
| alpha | S01 | false | true | false | EXTRA_DRAFT |
| alpha | V01 | true | true | true | - |
| alpha | V02 | true | true | true | - |
| alpha | V03 | false | true | false | EXTRA_DRAFT |
| alpha | V04 | true | null | true | - |
| alpha | V05 | true | true | true | - |
| beta | S01 | false | true | false | EXTRA_DRAFT |
| beta | V01 | true | true | true | - |
| beta | V02 | true | true | true | - |
| beta | V03 | true | true | true | - |
| beta | V04 | true | null | true | - |
| beta | V05 | true | true | true | - |

### Failing cases

- alpha S01: tags ['EXTRA_DRAFT']; A-S01 answered true
- alpha V03: tags ['EXTRA_DRAFT']; A-V03 answered true
- beta S01: tags ['EXTRA_DRAFT']; A-S01 answered true

### Notes

Independent offline review of the frozen raw evidence. All semantic assertions pass. Structural failures remain alpha S01, alpha V03, and beta S01; therefore the preregistered all-or-nothing validation criterion is not met.
