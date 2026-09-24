"""Model Runtime error taxonomy.

These are deliberately not collapsed into one exception. "No model is certified for this
task", "the certified model's adapter is not installed", "the transport failed", "the
provider substituted a different model" and "the output did not satisfy the contract" are
five different operational situations with five different fixes — a registry change, a
deployment change, a retry or incident, a provider bug, and a schema or prompt problem
respectively. A single generic error would erase that distinction at exactly the moment
an operator needs it.
"""

from __future__ import annotations

__all__ = [
    "ModelProtocolError",
    "ModelProviderError",
    "ModelProviderUnavailableError",
    "ModelRequestError",
    "ModelRuntimeError",
    "ModelUnavailableError",
]


class ModelRuntimeError(RuntimeError):
    """Base for every Model Runtime failure."""


class ModelRequestError(ModelRuntimeError):
    """The caller's request or the runtime's configuration is structurally invalid.

    A caller bug or a misconfiguration, detectable without contacting any provider.
    """


class ModelUnavailableError(ModelRuntimeError):
    """No registered model is certified for this exact task, tier and capability set.

    Not a transport problem: Foundry has simply not certified anything that may do this
    work. The fix is a certification decision, never a silent relaxation of the request.
    """


class ModelProviderUnavailableError(ModelRuntimeError):
    """A certified model was selected, but its provider adapter is not installed.

    Deliberately distinct from ``ModelUnavailableError``: the model is authorised, the
    deployment simply cannot reach it. Falling through to another model would mean
    executing on something Foundry did not certify for this work.
    """


class ModelProviderError(ModelRuntimeError):
    """The provider adapter failed while executing the call.

    The original exception is preserved as ``__cause__`` so transport detail stays
    diagnosable without leaking a vendor object into a public contract.
    """


class ModelProtocolError(ModelRuntimeError):
    """The provider's response broke the contract it was called under.

    Wrong provider or model identity, or output that does not satisfy the caller's type.
    Never repaired, coerced or partially accepted — a response that had to be edited to
    be acceptable is not evidence of what the model actually returned.
    """
