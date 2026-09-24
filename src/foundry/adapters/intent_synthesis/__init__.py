"""Intent-specific adapters.

This is where the Intent Synthesis prompt and model-facing schema live — not in
``foundry/model_runtime`` (shared plumbing that must stay provider-neutral) and not in
``foundry/adapters/model_runtime`` (provider transport that must stay Intent-unaware).
"""

from foundry.adapters.intent_synthesis.model_runtime import (
    INTENT_SYNTHESIS_POLICY_ID,
    INTENT_SYNTHESIS_POLICY_VERSION,
    ModelRuntimeIntentSynthesizer,
)

__all__ = [
    "INTENT_SYNTHESIS_POLICY_ID",
    "INTENT_SYNTHESIS_POLICY_VERSION",
    "ModelRuntimeIntentSynthesizer",
]
