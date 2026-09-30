# Interpretation Note: IE2 + IE3 Long-Horizon v1 (Post-Run Audit)

**Status:** interpretation note only, 2026-09-30. It is not a rescoring.

**Concerns:** `intent-ie2-ie3-long-horizon-v1` (`docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1/`).

## What is unchanged

- **The sealed verdict:** `LONG_HORIZON_IE2_IE3_NOT_VALIDATED`.
- **The run's files:** its evidence, expectations, verdicts, adjudication answers and report are frozen and were not edited. No file in the experiment directory was touched by this note.
- **The run is not rerun or rescored.** It does not become a PASS.

## What the post-run audit found

Source: `2026-09-30-ie2-t1-concern-grain-audit.md`. Decision: `2026-09-30-ie2-governed-concern-grain-clarification.md`.

1. **The expectation came from the pre-G2 grain.** The T1 expectation "exactly 12 concerns" (integrity gate I1) was inherited from the 9P3 section grain (2026-09-13), which predates G2 (2026-09-28). 9P3 formed its 12 addresses as subject+facet splits (`worker lease | duration` and `worker lease | renewal`). That same grain produced 9P3 Arm F's C09 over-split at T9.
2. **The model's 9 addresses are lawful under G2.** Under the approved G2 grain as clarified, A+B+C is one governed concern (job execution attempts) and F+G is one (worker lease). The model's 9-address T1 formation is therefore lawful.
3. **The two under-splits are oracle mismatches, not production defects.** The recorded T1 "under-splits" (A+B+C and F+G) are mismatches between the oracle and the grain. They are not known production concern-formation defects.

## What this note does not say

- It does not say the run would have validated. The run's other recorded failures (the T8–T12 accounting refusals, the T13 pending governance, IE3 fidelity misses) are unaffected by this note, and every later-turn check at the merged addresses stays as sealed.
- It does not make the frozen designation law or scorer correct for G2. A future long-horizon run needs a concern-level key (several sections may designate one address), sealed before it runs.
