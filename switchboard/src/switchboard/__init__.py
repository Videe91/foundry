"""Packet: P-004 — Family One: Anthropic Adapter.

One job: expose the switchboard's public surface.

Version: 0.4.0
"""

from switchboard.adapters import AnthropicAdapter, adapter_for
from switchboard.meter import MeterLedger, MeterRecord, Usage
from switchboard.registry import UnknownRoleError, load_registry
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.router import ProviderCallError, route_call
from switchboard.tags import CallTags, MissingTagsError

__all__ = [
    "AnthropicAdapter",
    "Attachment",
    "CallTags",
    "Message",
    "MeterLedger",
    "MeterRecord",
    "MissingTagsError",
    "ProviderCallError",
    "SwitchboardRequest",
    "UnknownRoleError",
    "Usage",
    "adapter_for",
    "load_registry",
    "route_call",
]
