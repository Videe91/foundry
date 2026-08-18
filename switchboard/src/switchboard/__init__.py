"""Packet: P-002 — Switchboard Routing.

One job: expose the switchboard's public surface.

Version: 0.2.0
"""

from switchboard.registry import UnknownRoleError, load_registry
from switchboard.request import Message, SwitchboardRequest
from switchboard.router import ProviderCallError, route_call
from switchboard.tags import CallTags, MissingTagsError

__all__ = [
    "CallTags",
    "Message",
    "MissingTagsError",
    "ProviderCallError",
    "SwitchboardRequest",
    "UnknownRoleError",
    "load_registry",
    "route_call",
]
