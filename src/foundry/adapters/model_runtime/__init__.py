"""Provider-specific adapters for the shared Model Runtime.

Everything vendor-shaped lives here. ``foundry/model_runtime`` stays provider-neutral and
imports no SDK; this package is where a real provider's protocol is spoken and then
translated back into the neutral contract.
"""

from foundry.adapters.model_runtime.xai import XAI_PROVIDER_ID, XAIModelProvider

__all__ = ["XAI_PROVIDER_ID", "XAIModelProvider"]
