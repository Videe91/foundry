# IE2 Governed-Concern Grain: Clarification of G2 (Founder Decision, Option 1)

**Status:** architecture decision by the founder, 2026-09-30.

**Decides:** the question raised by `2026-09-30-ie2-t1-concern-grain-audit.md` §9.

**Clarifies:** `2026-09-28-ie2-governed-concern-grain.md` (G2). G2 is **kept unchanged**. This record removes no rule, adds no rule and changes no model-facing text:
- `intent-v2-locus-v6` is byte-identical;
- no `intent-v2-locus-v7` exists.

## 1. The decision

G2 stands. When several rules govern the same act or entity, they are dimensions of one governed concern, even when each rule has its own quantity, timing, trigger or effect and can be revised independently.

## 2. The governing law, stated explicitly

A semantic address represents one governed:
- act;
- entity or record;
- entitlement;
- state;
- decision;
- or coherent operational concern.

**Dimensions stay claims.** Within that concern, the following remain claims (dimensions) at its one address when they govern that same concern:

| | | |
|---|---|---|
| quantity | limit | timing |
| retry timing | timeout | duration |
| expiry | renewal | preconditions |
| repetition | effects | destination |
| deadlines | exceptions | |

**A distinct address** is required only when the source governs a genuinely distinct act, entity, entitlement, state, decision or operational concern.

**Never an address boundary:**
- section boundaries;
- headings;
- predicates;
- triggers.

A rule's having its own trigger or outcome, or being independently changeable, is not by itself a reason for a new address: the dimensions G2 keeps together (C09, C6) have both properties.

## 3. The Orion cases, decided

| Concern | Sections | Its claims include |
|---|---|---|
| **Job execution attempts** (one concern) | A + B + C | maximum attempt count; retry timing after failure; per-attempt timeout; timeout-as-failure |
| **Worker lease** (one concern) | F + G | lease duration; expiry behaviour; renewal timing; renewal preconditions; renewal effect |

These rules may vary independently as parameters of their concern without requiring separate addresses.

**Explicitly rejected:** a rule of the form "different trigger or outcome ⇒ different concern". It would recreate the over-splitting G2 fixed in C09 (repeated cancellation) and C6 (the request deadline).

## 4. Consequences

- **Oracles derive their concern keys from this law, never from section count.** A sealed answer key may map several sections to one address. One section may never be read as one concern.
- **The frozen long-horizon run `intent-ie2-ie3-long-horizon-v1` is not changed or rescored.** See `2026-09-30-ie2-ie3-long-horizon-v1-interpretation-note.md`.
- **The next fresh IE2 validation (`intent-v2-locus-validation-v6`) seals a G2-derived answer key.** It includes a dense fresh-baseline formation case whose same-concern groups span several sections.
