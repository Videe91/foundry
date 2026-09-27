"""Typed Intent Graph proposals and graph identity (IE3 Slice 1).

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§5, §8-§10, §14,
§19; R99, R100; Q1, Q3, Q5, Q6).

A graph synthesizer proposes MEANING as a typed graph and nothing else. Every node variant is its
own class, discriminated on ``kind``: there is no generic node carrying a free field dictionary,
because each domain kind has required fields of its own and a generic shape could only satisfy
them by inventing values.

Trust boundary
--------------
``FrozenModel``'s ``extra="forbid"`` is the enforcement. No proposal can express a durable id,
authority, scope, provenance, creation time, lifecycle, revision, materiality, event id or
durable relation. Runtime owns every one of them (§8).

References live in three typed namespaces (R100). ``LocalNodeRef`` names a node of the same
result, ``ExistingObjectRef`` an object runtime showed, and ``BasisClaimRef`` a claim runtime
showed. Each is a model rather than a string, so a URI such as ``"local://goal-1"`` is never
parsed into one and the namespaces cannot collapse into a plain id. Whether a reference actually
resolves is decided against the visibility surface in ``intent_graph_validation``.

Identity (§14)
--------------
``IntentGraphIdentity`` is new rather than a stretched ``SynthesisIdentity``, whose semantics are
per proposal. Every durable id is a full-width ``synthesis_digest`` over runtime-owned inputs,
under ``ie3.*`` domain tags that never coincide with Slice-1's tags. A model-local id is an input
to a digest and never an id itself.

Pure domain: no I/O, no clock, no randomness, no provider import.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Final, Literal

from pydantic import (
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from foundry.domain.common import FrozenModel, RelationType, RiskLevel
from foundry.domain.gaps import GapKind
from foundry.domain.intent_synthesis import synthesis_digest
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import ConstraintFacet, SemanticKind

__all__ = [
    "GRAPH_CONTRACT_VERSION",
    "IE3_GRAPH_NODE_KINDS",
    "IE3_MODEL_GAP_KINDS",
    "IE3_PROPOSABLE_RELATIONS",
    "LOCAL_ID_PATTERN",
    "MAX_GRAPH_GAPS",
    "MAX_GRAPH_NODES",
    "MAX_GRAPH_RELATIONS",
    "OBJECT_ID_PREFIX",
    "AssumptionNodeProposal",
    "BasisClaimRef",
    "ConstraintNodeProposal",
    "DecisionNodeProposal",
    "ExistingObjectRef",
    "GoalNodeProposal",
    "GraphGapProposal",
    "GraphNodeDisposition",
    "GraphNodeProposal",
    "GraphRef",
    "GraphRelationProposal",
    "IntentGraphGap",
    "IntentGraphIdentity",
    "IntentGraphSynthesisResult",
    "IntentNodeProposal",
    "LocalNodeRef",
    "MissingNeed",
    "NonGoalNodeProposal",
    "OutcomeNodeProposal",
    "PreferenceNodeProposal",
    "RequirementNodeProposal",
]

GRAPH_CONTRACT_VERSION: Final = "ie3.graph-v1"

IE3_GRAPH_NODE_KINDS: Final[frozenset[SemanticKind]] = frozenset(
    {
        SemanticKind.INTENT,
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.CONSTRAINT,
        SemanticKind.NON_GOAL,
        SemanticKind.PREFERENCE,
        SemanticKind.DECISION,
        SemanticKind.ASSUMPTION,
    }
)
"""R99, written out. Never derived from ``INTENT_BEARING_SEMANTIC_KINDS``, a frozen Slice-1
compatibility set that also carries ``CONTRACT``."""

IE3_MODEL_GAP_KINDS: Final[frozenset[GapKind]] = frozenset(
    {
        GapKind.AMBIGUITY,
        GapKind.MISSING_INFORMATION,
        GapKind.CONTRADICTION,
        GapKind.UNSUPPORTED_ASSUMPTION,
        GapKind.UNDERSPECIFIED_SCOPE,
    }
)
"""§19. Every other kind is a deterministic runtime fact, a quality-slice concern or authority."""

IE3_PROPOSABLE_RELATIONS: Final[frozenset[RelationType]] = frozenset(
    {
        RelationType.DERIVED_FROM,
        RelationType.SERVES,
        RelationType.EXCLUDES,
        RelationType.AFFECTS,
    }
)
"""§10: the four axes an IE2 law consumes. Everything else is undecided semantics and refused."""

MAX_GRAPH_NODES: Final = 32
MAX_GRAPH_RELATIONS: Final = 128
MAX_GRAPH_GAPS: Final = 16
"""Q6. Exceeding a cap refuses the whole result; nothing is ever truncated."""

LOCAL_ID_PATTERN: Final = r"^[a-z][a-z0-9_-]{0,63}$"

OBJECT_ID_PREFIX: Final[Mapping[SemanticKind, str]] = MappingProxyType(
    {
        SemanticKind.INTENT: "INT",
        SemanticKind.GOAL: "GOAL",
        SemanticKind.OUTCOME: "OUT",
        SemanticKind.REQUIREMENT: "REQ",
        SemanticKind.CONSTRAINT: "CON",
        SemanticKind.NON_GOAL: "NG",
        SemanticKind.PREFERENCE: "PREF",
        SemanticKind.DECISION: "DEC",
        SemanticKind.ASSUMPTION: "ASM",
    }
)
"""Readability convention only. ``resolve_target_kind`` never inspects id text."""


class MissingNeed(StrEnum):
    """Q3: what an unresolved region is missing, as the model sees it. Untrusted diagnosis.

    Deliberately NOT a ``GapResolutionRoute`` and never mapped to one: ``LAWFUL_ROUTES`` stays the
    authority on how a gap may close, and any route selected later must still pass
    ``assert_route_allowed``.
    """

    PROJECT_CHOICE = "PROJECT_CHOICE"
    EXTERNAL_FACT = "EXTERNAL_FACT"
    UNDETERMINED = "UNDETERMINED"


class GraphNodeDisposition(StrEnum):
    """What a node does to existing intent.

    ``EXISTING_UNCHANGED`` is not a node: already-represented intent is referenced through an
    ``ExistingObjectRef`` in ``IntentGraphSynthesisResult.unchanged_object_refs`` and nothing is
    minted for it (§8, R111).
    """

    NEW = "NEW"
    REPLACES_STALE = "REPLACES_STALE"


# --------------------------------------------------------------------------- answer schema
#
# The generated JSON Schema is a faithful, provider-neutral description of what Pydantic
# accepts; Pydantic stays the source of truth and the final authority. Three laws that Pydantic
# enforces were absent from the generated schema, so the schema accepted values Pydantic
# refuses. Each is expressed below as JSON Schema only: no validator, default, constructor or
# accepted value changes. ``test_ie3_graph_answer_schema`` pins the inventory and proves
# agreement.


class _UnionTagRequired:
    """At a discriminated-union boundary, every branch requires its tag.

    Pydantic's union dispatch refuses a member without its tag even though the tag has a Python
    default, but generation left the tag out of ``required``. The requirement is placed at the
    boundary (``{"$ref": ..., "required": [tag]}``), so a standalone use of the same model keeps
    its lawful default there.
    """

    def __init__(self, tag: str) -> None:
        self._tag = tag

    def __get_pydantic_json_schema__(
        self, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        union = handler.resolve_ref_schema(json_schema)
        union["oneOf"] = [{**branch, "required": [self._tag]} for branch in union["oneOf"]]
        return json_schema


def _node_state(
    schema: dict[str, Any],
    disposition: GraphNodeDisposition,
    replaces: dict[str, Any],
    required: tuple[str, ...],
) -> dict[str, Any]:
    """One lawful (disposition, replaces) state of a node family, with ``kind`` required."""
    variant = copy.deepcopy(schema)
    state: dict[str, Any] = {"const": disposition.value, "type": "string"}
    if disposition is GraphNodeDisposition.NEW:
        state["default"] = GraphNodeDisposition.NEW.value
    variant["properties"]["disposition"] = state
    variant["properties"]["replaces"] = replaces
    needed = set(schema.get("required", ())) | {"kind", *required}
    variant["required"] = [name for name in variant["properties"] if name in needed]
    return variant


def _node_answer_schema(schema: dict[str, Any], cls: type[Any]) -> None:
    """Express ``validate_disposition`` in the schema.

    An irreplaceable family (INTENT, ASSUMPTION) has one state: ``NEW`` with no target, either
    of which may be omitted because Pydantic defaults them to exactly that. A replaceable family
    has two states, told apart by ``disposition``: ``NEW`` (omittable, target null or omitted)
    and ``REPLACES_STALE`` (both required, target an ``ExistingObjectRef``).
    """
    target = next(
        branch for branch in schema["properties"]["replaces"]["anyOf"] if branch != {"type": "null"}
    )
    new = _node_state(
        schema, GraphNodeDisposition.NEW, {"type": "null", "default": None}, required=()
    )
    if not cls.replaceable:
        schema.clear()
        schema.update(new)
        return
    stale = _node_state(
        schema,
        GraphNodeDisposition.REPLACES_STALE,
        target,
        required=("disposition", "replaces"),
    )
    header = {key: schema[key] for key in ("title", "description") if key in schema}
    schema.clear()
    schema.update(header)
    schema["oneOf"] = [new, stale]


_PROPOSABLE_RELATION_SCHEMA: Final[dict[str, Any]] = {
    "description": "The relations graph synthesis may propose (IE3_PROPOSABLE_RELATIONS).",
    "enum": [relation.value for relation in RelationType if relation in IE3_PROPOSABLE_RELATIONS],
    "title": "Relation Type",
    "type": "string",
}
"""Expresses ``GraphRelationProposal.only_proposable_relations``. The domain ``RelationType``
enum itself is not narrowed; only what this field accepts is described."""


# --------------------------------------------------------------------------- references


class LocalNodeRef(FrozenModel):
    """A node of the same result. Resolvable only within that result."""

    namespace: Literal["local"] = "local"
    local_id: str = Field(pattern=LOCAL_ID_PATTERN)


class ExistingObjectRef(FrozenModel):
    """An existing object runtime showed. Never a durable id for anything new."""

    namespace: Literal["existing"] = "existing"
    object_id: str = Field(min_length=1)


class BasisClaimRef(FrozenModel):
    """A v2 ``SemanticClaim`` runtime showed as basis."""

    namespace: Literal["basis"] = "basis"
    claim_id: str = Field(min_length=1)


type GraphRef = Annotated[
    LocalNodeRef | ExistingObjectRef | BasisClaimRef,
    Field(discriminator="namespace"),
    _UnionTagRequired("namespace"),
]


# --------------------------------------------------------------------------- nodes


class _NodeProposal(FrozenModel):
    """Fields every node shares. Meaning, a local handle and a disposition; never authority."""

    model_config = ConfigDict(json_schema_extra=_node_answer_schema)

    local_id: LocalNodeRef
    disposition: GraphNodeDisposition = GraphNodeDisposition.NEW
    replaces: ExistingObjectRef | None = None
    proposal_rationale: str = Field(min_length=1)
    """Why the proposer proposes this node. Kept with the decision, never on the object."""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Q1: ``None`` means no number was asserted. It is carried exactly, never defaulted."""

    replaceable: ClassVar[bool] = True

    @model_validator(mode="after")
    def validate_disposition(self) -> _NodeProposal:
        if self.disposition is GraphNodeDisposition.NEW:
            if self.replaces is not None:
                raise ValueError("disposition NEW must not name a replacement target")
            return self
        if not self.replaceable:
            raise ValueError(
                f"{type(self).__name__} cannot be replaced through synthesis (§17): replacing "
                "a root or a premise is not a stale-basis reconciliation"
            )
        if self.replaces is None:
            raise ValueError("disposition REPLACES_STALE requires a replacement target")
        return self


class IntentNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.INTENT] = SemanticKind.INTENT
    mission: str = Field(min_length=1)

    replaceable: ClassVar[bool] = False


class GoalNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.GOAL] = SemanticKind.GOAL
    statement: str = Field(min_length=1)


class OutcomeNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.OUTCOME] = SemanticKind.OUTCOME
    statement: str = Field(min_length=1)


class RequirementNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.REQUIREMENT] = SemanticKind.REQUIREMENT
    statement: str = Field(min_length=1)


class ConstraintNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.CONSTRAINT] = SemanticKind.CONSTRAINT
    statement: str = Field(min_length=1)
    facet: ConstraintFacet


class NonGoalNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.NON_GOAL] = SemanticKind.NON_GOAL
    statement: str = Field(min_length=1)


class PreferenceNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.PREFERENCE] = SemanticKind.PREFERENCE
    statement: str = Field(min_length=1)


class DecisionNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.DECISION] = SemanticKind.DECISION
    statement: str = Field(min_length=1)
    decision_rationale: str = Field(min_length=1)
    """The project's reason for the choice; becomes ``ProjectDecision.rationale``."""


class AssumptionNodeProposal(_NodeProposal):
    kind: Literal[SemanticKind.ASSUMPTION] = SemanticKind.ASSUMPTION
    statement: str = Field(min_length=1)
    proposed_risk_level: RiskLevel | None = None
    """Q5: authoritative only when an authenticated human states it. For any other author it is
    recorded input, and the compiled Assumption is ``HIGH`` whatever it says."""

    replaceable: ClassVar[bool] = False


type GraphNodeProposal = Annotated[
    IntentNodeProposal
    | GoalNodeProposal
    | OutcomeNodeProposal
    | RequirementNodeProposal
    | ConstraintNodeProposal
    | NonGoalNodeProposal
    | PreferenceNodeProposal
    | DecisionNodeProposal
    | AssumptionNodeProposal,
    Field(discriminator="kind"),
]
"""``kind`` is required inside every node state (``_node_answer_schema``): node proposals occur
only in this union, so the tag is required where it is defined rather than at the boundary."""


# --------------------------------------------------------------------------- relations and gaps


class GraphRelationProposal(FrozenModel):
    """One proposed edge. The source is always a new local node (G6): relations are
    object-local, and admission never revises an existing object."""

    source: LocalNodeRef
    relation_type: Annotated[RelationType, WithJsonSchema(_PROPOSABLE_RELATION_SCHEMA)]
    target: GraphRef

    @field_validator("relation_type", mode="after")
    @classmethod
    def only_proposable_relations(cls, value: RelationType) -> RelationType:
        if value not in IE3_PROPOSABLE_RELATIONS:
            raise ValueError(
                f"{value.value} is not proposable in {GRAPH_CONTRACT_VERSION}; only "
                "DERIVED_FROM, SERVES, EXCLUDES and AFFECTS carry a decided meaning"
            )
        return value


class GraphGapProposal(FrozenModel):
    """An explicitly unresolved region (R104). Never a stand-in for a missing node."""

    local_gap_id: str = Field(pattern=LOCAL_ID_PATTERN)
    kind: GapKind
    description: str = Field(min_length=1)
    missing_need: MissingNeed
    blocking: bool
    anchors: tuple[GraphRef, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("kind", mode="after")
    @classmethod
    def only_model_gap_kinds(cls, value: GapKind) -> GapKind:
        if value not in IE3_MODEL_GAP_KINDS:
            raise ValueError(f"{value.value} is not an IE3 model gap kind")
        return value

    @field_validator("blocking", mode="after")
    @classmethod
    def model_gaps_block(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError(
                "a model gap must be blocking in graph-v1; the proposer does not get to declare "
                "its own uncertainty harmless"
            )
        return value


class IntentGraphSynthesisResult(FrozenModel):
    """One graph synthesizer answer: a safe partial graph plus explicit gaps (R104)."""

    graph_contract_version: Literal["ie3.graph-v1"] = GRAPH_CONTRACT_VERSION
    nodes: tuple[GraphNodeProposal, ...] = ()
    relations: tuple[GraphRelationProposal, ...] = ()
    gaps: tuple[GraphGapProposal, ...] = ()
    unchanged_object_refs: tuple[ExistingObjectRef, ...] = ()
    """R111: shown, current, non-stale objects that already mean what was intended. Mint
    nothing for them. A witness only: not a relation, replacement, basis, authority or effect.
    Deterministic Foundry checks eligibility, never semantic sameness."""

    @model_validator(mode="after")
    def validate_shape(self) -> IntentGraphSynthesisResult:
        # Relations alone never count: every relation's source must be a new node.
        if not self.nodes and not self.gaps and not self.unchanged_object_refs:
            raise ValueError("an empty result is refused; synthesis must not decline silently")
        unchanged_ids = [ref.object_id for ref in self.unchanged_object_refs]
        if len(set(unchanged_ids)) != len(unchanged_ids):
            raise ValueError("duplicate unchanged_object_refs in one result")
        for name, size, cap in (
            ("MAX_GRAPH_NODES", len(self.nodes), MAX_GRAPH_NODES),
            ("MAX_GRAPH_RELATIONS", len(self.relations), MAX_GRAPH_RELATIONS),
            ("MAX_GRAPH_GAPS", len(self.gaps), MAX_GRAPH_GAPS),
        ):
            if size > cap:
                raise ValueError(
                    f"{size} exceeds {name}={cap}; the result is refused, not truncated"
                )
        node_ids = [n.local_id.local_id for n in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("duplicate node local_id in one result")
        gap_ids = [g.local_gap_id for g in self.gaps]
        if len(set(gap_ids)) != len(gap_ids):
            raise ValueError("duplicate gap id in one result")
        clash = set(node_ids) & set(gap_ids)
        if clash:
            raise ValueError(f"node and gap local ids collide: {sorted(clash)}")
        return self


class IntentGraphGap(IntentSynthesisGap):
    """A compiled IE3 model gap: the synthesis gap plus its untrusted Q3 diagnostic."""

    missing_need: MissingNeed


# --------------------------------------------------------------------------- identity


class IntentGraphIdentity(FrozenModel):
    """Runtime-owned identity of one graph synthesis run (§14). One graph per run."""

    project_id: str = Field(min_length=1)
    synthesis_run_id: str = Field(min_length=1)

    @property
    def graph_instance_id(self) -> str:
        return "GSY-" + synthesis_digest("ie3.graph", self.project_id, self.synthesis_run_id)

    def node_instance_id(self, local_id: str) -> str:
        return "GSN-" + synthesis_digest("ie3.node", self.graph_instance_id, local_id)

    def object_id(self, kind: SemanticKind, local_id: str) -> str:
        return f"{OBJECT_ID_PREFIX[kind]}-" + synthesis_digest(
            "ie3.object", self.graph_instance_id, local_id, kind.value
        )

    def gap_id(self, local_gap_id: str) -> str:
        return "GAP-" + synthesis_digest("ie3.gap", self.graph_instance_id, local_gap_id)

    def event_id(self, step: str) -> str:
        return "EVT-" + synthesis_digest("ie3.event", self.graph_instance_id, step)
