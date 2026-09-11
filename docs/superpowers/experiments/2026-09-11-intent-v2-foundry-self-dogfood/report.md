# Intent Intelligence v2 — First Live Dogfood (Foundry on Foundry)

- experiment_version: `intent-v2-foundry-self-dogfood-v1`
- project_id: `PROJ-9O-FOUNDRY-SELF`
- frozen_code_sha: `376c89cc71ac46552ec9ddc4ef3f4db0d9159bd9`
- model: `grok-4.6` · reasoning_effort: `high`
- policy_version: `intent-v2-9o-v1`
- run_status: **COMPLETED**

## Evidence (frozen by commit)

| id | path | kind | blob | sha256 |
|---|---|---|---|---|
| EV-01 | `FOUNDRY_CONSTITUTION.md` | DOCUMENT | `f94ff1e19344` | `d981eb3aba01` |
| EV-02 | `docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md` | DOCUMENT | `730eae10d38e` | `e6f88ed44f40` |
| EV-03 | `src/foundry/application/semantic_governance.py` | CODE | `c2895657fb60` | `1f6bb91258cc` |
| EV-04 | `src/foundry/domain/semantic_view.py` | CODE | `217cad1a9b62` | `b7a32eaef7ae` |
| EV-05 | `tests/integration/test_semantic_lifecycle.py` | TEST | `6a25a0f5bb10` | `4b1f86349cd2` |

## Calls

| stage | status | allowed | judgments | routes | addresses | claims | in tok | out tok | cost USD | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| discovery | COMPLETED | CREATE_ADDRESS | 38 | APPLY=38 | 38 | 0 | 31928 | 2977 | 0.123064 | 151.695 |
| claims | COMPLETED | ASSERT_CLAIM | 38 | APPLY=38 | 0 | 38 | 33437 | 4200 | 0.133414 | 146.575 |
| reconciliation | COMPLETED | CONFLICTS_WITH, DISTINCT, EQUIVALENT | 16 | APPLY=16 | 0 | 0 | 36985 | 1346 | 0.145148 | 183.333 |

- actual_external_call_count: **3** (budget 3)
- total tokens: 102350 in / 8523 out
- total cost: 0.401626 USD · total wall clock: 481.603 s

## Semantic State

- addresses: 38 · claims: 38
- proposals: EQUIVALENT=0 DISTINCT=16 CONFLICTS_WITH=0
- admission routes: APPLY=92, REJECT=0, REQUIRE_HUMAN=0, REQUIRE_SECOND_LENS=0
- pending second lens: 0 · require human: 0 · rejected: 0 · stale: 0

| locus | addresses | claims | epistemic |
|---|---|---|---|
| `ADDR-0cd4f0d9ce918762` | 1 | 1 | CLAIMED |
| `ADDR-14a08bc566816f41` | 1 | 1 | CLAIMED |
| `ADDR-16a53ea9178d20f8` | 1 | 1 | CLAIMED |
| `ADDR-1d39be6c0d69e659` | 1 | 1 | CLAIMED |
| `ADDR-1d3b7d5d9ae32abf` | 1 | 1 | CLAIMED |
| `ADDR-24272e7cfe83fb91` | 1 | 1 | CLAIMED |
| `ADDR-257f376b72079bb5` | 1 | 1 | CLAIMED |
| `ADDR-31d52f268e0c21e9` | 1 | 1 | CLAIMED |
| `ADDR-33650f46bd5ce4c3` | 1 | 1 | CLAIMED |
| `ADDR-4265ce783734e90e` | 1 | 1 | CLAIMED |
| `ADDR-49de33594660a645` | 1 | 1 | CLAIMED |
| `ADDR-5713659ae21c521d` | 1 | 1 | CLAIMED |
| `ADDR-57604a1dc9b9d754` | 1 | 1 | CLAIMED |
| `ADDR-5a1172434802eec9` | 1 | 1 | CLAIMED |
| `ADDR-5bd8afe0586a9817` | 1 | 1 | CLAIMED |
| `ADDR-5c0a319bc552c17d` | 1 | 1 | CLAIMED |
| `ADDR-612b83fb305e8f8f` | 1 | 1 | CLAIMED |
| `ADDR-6a542211fdc9ee78` | 1 | 1 | CLAIMED |
| `ADDR-6d91e674d892e17f` | 1 | 1 | CLAIMED |
| `ADDR-776f2d4595529c58` | 1 | 1 | CLAIMED |
| `ADDR-790d3c4f0f4dfcd4` | 1 | 1 | CLAIMED |
| `ADDR-79c906f7d78ec17e` | 1 | 1 | CLAIMED |
| `ADDR-7cc6b96dbc453c49` | 1 | 1 | CLAIMED |
| `ADDR-9282e70460b6aac0` | 1 | 1 | CLAIMED |
| `ADDR-9412c7089c784a2c` | 1 | 1 | CLAIMED |
| `ADDR-9c99b68b9f231095` | 1 | 1 | CLAIMED |
| `ADDR-a823950c710bc40a` | 1 | 1 | CLAIMED |
| `ADDR-b3d54e9f292a1565` | 1 | 1 | CLAIMED |
| `ADDR-bb4321b8811ebc5c` | 1 | 1 | CLAIMED |
| `ADDR-c2c00d2bb47d22b8` | 1 | 1 | CLAIMED |
| `ADDR-c50f6a6c6278797b` | 1 | 1 | CLAIMED |
| `ADDR-c8191e76136b56e3` | 1 | 1 | CLAIMED |
| `ADDR-cc032cfffe1c810a` | 1 | 1 | CLAIMED |
| `ADDR-ccd62f4ed0d3f1c9` | 1 | 1 | CLAIMED |
| `ADDR-cdbce4cbbb7a92eb` | 1 | 1 | CLAIMED |
| `ADDR-db347935a1499d86` | 1 | 1 | CLAIMED |
| `ADDR-ed3a874794f7f801` | 1 | 1 | CLAIMED |
| `ADDR-f588c3fd9a4ee613` | 1 | 1 | CLAIMED |

## Replay

- status: **REPLAY_MATCH** · events: 189 · state=True view=True

## Structural Checks

| check | passed | detail |
|---|---|---|
| every_claim_cites_ingested_evidence | PASS | offenders=[] |
| every_relation_references_known_objects | PASS | offenders=[] |
| no_non_human_claim_is_canonical | PASS | offenders=[] |
| no_material_kind_auto_applied | PASS | offenders=[] |
| no_same_model_corroboration | PASS | offenders=[] |
| no_address_or_claim_deleted | PASS | snapshots=4 |
| every_judgment_kind_was_allowed_for_its_stage | PASS | offenders=[] |
| replay_reproduced_state | PASS | state=True view=True |
| external_calls_within_budget | PASS | calls=3 budget=3 |

_Forensic record only. Semantic quality is not assessed here._
