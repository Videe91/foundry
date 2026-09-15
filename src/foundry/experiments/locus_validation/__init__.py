"""Locus-policy live-validation experiment harness.

Experiment version ``intent-v2-locus-validation-v1``.

Experiment-only code. The law of this package: the AI decides meaning; the harness
governs structure; nothing here selects an outcome. ``corpus`` is model-visible,
non-semantic request-path data; ``expectations`` is the hidden scientific contract
and is never imported by a request-path module. Nothing in this package alters
production semantics or makes a provider call on import.
"""
