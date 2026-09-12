"""9P2 unseen-lifecycle experiment harness (frozen Kestrel timeline, ablation, runner).

This package holds experiment-only code for the 9P2 unseen-lifecycle comparative
run. It decides nothing about production behaviour and is never imported by
``src/foundry/domain``, ``application``, ``ports``, or ``adapters``.
"""

from __future__ import annotations
