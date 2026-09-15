"""Non-semantic protocol of the locus-policy live-validation experiment.

Spec §8 (identity gates), §12 (ceilings), §13 (artifact layout), §17 (historical
preservation) and §18 (exact call budget). This module owns only literals: the
experiment version, the git identities the seal must descend from and preserve, the
frozen provider / model / policy / prompt / schema identity the guarded reasoner
must present, the ceilings, the per-ledger call schedule, and the ledger, scope and
project ids re-exported from the corpus. It decides nothing semantic, carries no
answer key, never reads a file, the environment, git or the clock, and must never
import ``expectations`` or any grading module. Every value is a literal locked in
the approved plan; none is derived at runtime.
"""

from __future__ import annotations

from typing import Final

from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.experiments.locus_validation.corpus import LEDGERS, PROJECT_IDS, SCOPES, Ledger

__all__ = [
    "ARTIFACT_FORMAT_VERSION",
    "BASELINE_SHA",
    "CALLS_PER_DELTA",
    "CALLS_PER_LEDGER",
    "CEILING_KEYS",
    "DELTAS",
    "DESIGN_BASE_SHA",
    "EXPERIMENT_ARTIFACT_DIR",
    "EXPERIMENT_VERSION",
    "GRPC_DNS_RESOLVER_ENV",
    "GRPC_DNS_RESOLVER_FROZEN",
    "HISTORICAL_ARTIFACT_DIRS",
    "HISTORICAL_PROMPT_SHA256S",
    "LEDGERS",
    "MAX_COST_USD",
    "MAX_FRONTIER_CALLS",
    "MAX_HUMAN_AUTHORIZATIONS",
    "MAX_JUDGE_CALLS",
    "MAX_SAME_CELL_RERUNS",
    "MAX_SEMANTIC_RETRIES",
    "MODEL",
    "OUTPUT_SCHEMA_SHA256_FROZEN",
    "POLICY_VERSION_FROZEN",
    "PREDECESSOR_ADJUDICATION_SHA",
    "PREDECESSOR_ARTIFACT_DIR",
    "PREDECESSOR_RAW_RUN_SHA",
    "PREREGISTRATION_FILE_NAMES",
    "PROJECT_IDS",
    "PROMPT_SHA256_FROZEN",
    "PROVIDER",
    "REASONING_EFFORT",
    "SCOPES",
    "Ledger",
]

# --- experiment identity -------------------------------------------------------------

EXPERIMENT_VERSION: Final = "intent-v2-locus-validation-v1"
ARTIFACT_FORMAT_VERSION: Final = 1
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-15-locus-validation-v1/"
PREREGISTRATION_FILE_NAMES: Final = ("manifest.json", "expectations.json")

# --- §8 gate 3 / §17 git identities (pasted literals, never derived) -------------------

BASELINE_SHA: Final = "b34b987454c942965fa09a556725693896ecc426"
# The commit that added the approved plan: the historical-preservation base at which
# every directory in ``HISTORICAL_ARTIFACT_DIRS`` exists (spec §8 gate 16).
DESIGN_BASE_SHA: Final = "1441e2e0f56a34ebfc8ccdf9a60cfdf95c1d0696"
HISTORICAL_ARTIFACT_DIRS: Final[tuple[str, ...]] = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
    "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
    "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/",
)
PREDECESSOR_RAW_RUN_SHA: Final = "f045612e9ec9917b73649175cf08f91f087f2828"
PREDECESSOR_ADJUDICATION_SHA: Final = "3c30c16193dae6a9a03fe630f2ca33bf2a2e8c13"
PREDECESSOR_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
)

# --- §8 gates 4–8, 15: provider, policy, prompt and schema identity --------------------

PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"
GRPC_DNS_RESOLVER_FROZEN: Final = "native"

POLICY_VERSION_FROZEN: Final = "intent-v2-locus-v1"
PROMPT_SHA256_FROZEN: Final = "e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)
HISTORICAL_PROMPT_SHA256S: Final[dict[str, str]] = {
    "intent-v2-9p-v4": "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1",
    "intent-v2-9p2-v1": "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410",
}

# --- §12 ceilings ------------------------------------------------------------------------

MAX_FRONTIER_CALLS: Final = 8
MAX_JUDGE_CALLS: Final = 0
MAX_SEMANTIC_RETRIES: Final = 0
MAX_SAME_CELL_RERUNS: Final = 0
MAX_HUMAN_AUTHORIZATIONS: Final = 0
MAX_COST_USD: Final = 2.0
CEILING_KEYS: Final = (
    "max_frontier_calls",
    "max_judge_calls",
    "max_semantic_retries",
    "max_same_cell_reruns",
    "max_human_authorizations",
    "max_provider_cost_usd",
)

# --- §18 call schedule ----------------------------------------------------------------------

DELTAS: Final = (1, 2)
"""T1 seed delta, then T2 revision delta, over a fresh governor per ledger."""

CALLS_PER_LEDGER: Final = 4
"""``len(DELTAS) * CALLS_PER_DELTA``; two ledgers give the 8-call ceiling."""
