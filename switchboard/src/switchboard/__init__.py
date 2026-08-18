"""Packet: P-001 — Switchboard Scaffold.

One job: expose the switchboard's public surface.

Version: 0.1.0
"""

from switchboard.request import SwitchboardRequest
from switchboard.router import route_call
from switchboard.tags import CallTags

__all__ = ["CallTags", "SwitchboardRequest", "route_call"]
