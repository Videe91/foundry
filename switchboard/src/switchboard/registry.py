"""Packet: P-002 — Switchboard Routing.

One job: parse the model registry file and resolve a role to its model route.

Version: 0.2.0
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ValidationError

DEFAULT_ROLE = "default"


class UnknownRoleError(Exception):
    """Raised when a role has no entry and the registry has no default."""


class RoleRoute(BaseModel):
    """One role's model, its ordered fallbacks, and its token ceiling."""

    model: str
    fallbacks: list[str]
    max_tokens: int


class ModelRegistry(BaseModel):
    """The parsed registry: every role's route, keyed by role name."""

    roles: dict[str, RoleRoute]

    def resolve(self, role: str) -> RoleRoute:
        """Return the route for a role, falling back to the default entry."""
        route = self.roles.get(role)
        if route is not None:
            return route

        default_route = self.roles.get(DEFAULT_ROLE)
        if default_route is not None:
            return default_route

        raise UnknownRoleError(
            f"role '{role}' has no registry entry and no "
            f"'{DEFAULT_ROLE}' entry exists to fall back to"
        )


def load_registry(path: str | Path) -> ModelRegistry:
    """Parse a registry TOML file. Malformed entries raise ValueError."""
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)

    raw_roles = raw.get("roles", {})
    if not isinstance(raw_roles, dict):
        raise ValueError("registry is malformed: 'roles' must be a table")

    routes: dict[str, RoleRoute] = {}
    for role_name, entry in raw_roles.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"role '{role_name}' is malformed: entry must be a table"
            )
        if "model" not in entry:
            raise ValueError(
                f"role '{role_name}' is malformed: missing required field 'model'"
            )
        if "fallbacks" in entry and not isinstance(entry["fallbacks"], list):
            raise ValueError(
                f"role '{role_name}' is malformed: 'fallbacks' must be a list"
            )

        try:
            routes[role_name] = RoleRoute(**entry)
        except ValidationError as exc:
            raise ValueError(f"role '{role_name}' is malformed: {exc}") from exc

    return ModelRegistry(roles=routes)
