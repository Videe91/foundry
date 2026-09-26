# ruff: noqa: E501
"""IE3 mutant table consumed by ``scripts/run_ie2_mutations.py --table ie3``.

One entry per law in §27 of ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md``,
numbered as there. Each ``Edit`` replaces text that must occur exactly once in the file; when code
moves, re-anchor the entry -- never delete it to make a run green. Anchors are literal source
text, so lines here may exceed the line-length limit.
"""

from __future__ import annotations

from ie2_mutants import Edit, Mutant

_G = "src/foundry/domain/intent_graph.py"
_V = "src/foundry/domain/intent_graph_validation.py"
_C = "src/foundry/domain/intent_graph_compiler.py"
_S = "src/foundry/domain/semantic.py"

SLICE_TESTS: dict[str, tuple[str, ...]] = {
    "ie3s1": (
        "tests/unit/test_ie3_graph_types.py",
        "tests/unit/test_ie3_graph_validation.py",
        "tests/unit/test_ie3_graph_compiler.py",
    ),
}


def _m(name: str, *edits: Edit) -> Mutant:
    return Mutant("ie3s1", name, edits)


MUTANTS: tuple[Mutant, ...] = (
    # 1
    _m(
        "01-duplicate-local-id-accepted",
        Edit(_G, "        if len(set(node_ids)) != len(node_ids):\n", "        if False:\n"),
    ),
    # 2
    _m(
        "02-unresolved-local-ref-accepted",
        Edit(
            _V,
            "            node = self.nodes.get(ref.local_id)\n            if node is None:\n",
            "            node = self.nodes.get(ref.local_id)\n            if node is None and False:\n",
        ),
    ),
    # 3
    _m(
        "03-invisible-existing-ref-accepted",
        Edit(
            _V,
            "            obj = self.visibility.get(ref.object_id)\n            if obj is None:\n",
            "            obj = self.visibility.get(ref.object_id)\n            if obj is None:\n                return SemanticKind.GOAL\n            if obj is None:\n",
        ),
    ),
    # 4
    _m(
        "04-invisible-basis-ref-accepted",
        Edit(
            _V,
            "        if ref.claim_id not in self.visibility.basis_claim_ids:\n",
            "        if False:\n",
        ),
    ),
    # 5
    _m(
        "05-kind-dropped-from-object-digest",
        Edit(
            _G,
            '"ie3.object", self.graph_instance_id, local_id, kind.value',
            '"ie3.object", self.graph_instance_id, local_id',
        ),
    ),
    # 6
    _m(
        "06-run-dropped-from-graph-digest",
        Edit(
            _G,
            'synthesis_digest("ie3.graph", self.project_id, self.synthesis_run_id)',
            'synthesis_digest("ie3.graph", self.project_id)',
        ),
    ),
    # 7
    _m(
        "07-raw-local-id-as-object-id",
        Edit(
            _G,
            'return f"{OBJECT_ID_PREFIX[kind]}-" + synthesis_digest(\n            "ie3.object", self.graph_instance_id, local_id, kind.value\n        )',
            'return f"{OBJECT_ID_PREFIX[kind]}-{local_id}"',
        ),
    ),
    # 8
    _m(
        "08-compiled-order-follows-input",
        Edit(
            _C,
            "    nodes = sorted(result.nodes, key=lambda n: n.local_id.local_id)\n",
            "    nodes = list(result.nodes)\n",
        ),
        Edit(
            _C,
            "        objects=tuple(sorted(objects, key=lambda o: o.id)),\n",
            "        objects=tuple(objects),\n",
        ),
    ),
    # 9
    _m(
        "09-serves-reachability-skipped",
        Edit(
            _V,
            "        if node.kind in RELEVANCE_BEARING_KINDS and not _reaches_intent(graph, local_id):\n",
            "        if False:\n",
        ),
    ),
    # 10
    _m(
        "10-derived-from-counts-as-relevance",
        Edit(
            _V,
            "            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.SERVES))\n",
            "            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.SERVES) + graph.edges(ident, RelationType.DERIVED_FROM))\n",
        ),
    ),
    # 11
    _m(
        "11-serves-counts-as-grounding",
        Edit(
            _V,
            "            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.DERIVED_FROM))\n",
            "            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.DERIVED_FROM) + graph.edges(ident, RelationType.SERVES))\n",
        ),
    ),
    # 12
    _m(
        "12-second-root-allowed",
        Edit(_V, "    if len(new_roots) > 1 or (new_roots and existing):\n", "    if False:\n"),
    ),
    # 13
    _m(
        "13-assumption-affects-not-required",
        Edit(
            _V,
            "        if node.kind is SemanticKind.ASSUMPTION and not graph.edges(local_id, RelationType.AFFECTS):\n",
            "        if False:\n",
        ),
    ),
    # 14
    _m(
        "14-model-goal-direct-permitted",
        Edit(
            _V,
            "        if author_is_human and not evidential_facet:\n",
            "        if (author_is_human or node.kind is SemanticKind.GOAL) and not evidential_facet:\n",
        ),
    ),
    # 15
    _m(
        "15-local-decision-is-a-model-terminal",
        Edit(
            _V,
            '        if namespace == "local":\n            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.DERIVED_FROM))\n',
            '        if namespace == "local":\n            decision = decision or (ident != start and graph.nodes[ident].kind is SemanticKind.DECISION)\n            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.DERIVED_FROM))\n',
        ),
    ),
    # 16
    _m(
        "16-evidence-required-facets-dropped",
        Edit(
            _V,
            "    {ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE}\n",
            "    set()\n",
        ),
    ),
    # 17
    _m(
        "17-cycle-check-skipped",
        Edit(_V, "    _check_acyclic(graph)\n", ""),
    ),
    # 18
    _m(
        "18-hypothetical-ie2-pass-skipped",
        Edit(
            _C,
            "    projected = hypothetical_state(state, compiled)\n    for obj in compiled.objects:\n",
            "    projected = hypothetical_state(state, compiled)\n    for obj in ():\n",
        ),
    ),
    # 19
    _m(
        "19-c11-dropped",
        Edit(
            _C,
            "    if target.authority is Authority.CANONICAL and authority is not Authority.CANONICAL:\n",
            "    if False:\n",
        ),
    ),
    # 20
    _m(
        "20-replacement-scope-coverage-dropped",
        Edit(
            _C,
            "    if not replacement_scope_covers((visibility.run_scope,), tuple(target.scope)):\n",
            "    if False:\n",
        ),
    ),
    # 21
    _m(
        "21-intent-replacement-permitted",
        Edit(
            _G,
            "    mission: str = Field(min_length=1)\n\n    replaceable: ClassVar[bool] = False\n",
            "    mission: str = Field(min_length=1)\n\n    replaceable: ClassVar[bool] = True\n",
        ),
    ),
    # 22
    _m(
        "22-non-blocking-model-gap-accepted",
        Edit(_G, "        if value is not True:\n", "        if False:\n"),
    ),
    # 23
    _m(
        "23-model-gap-kinds-widened",
        Edit(
            _G,
            "        GapKind.UNDERSPECIFIED_SCOPE,\n    }\n)\n",
            "        GapKind.UNDERSPECIFIED_SCOPE,\n        GapKind.MISSING_SUCCESS_METRIC,\n    }\n)\n",
        ),
    ),
    # 24
    _m(
        "24-caps-skipped",
        Edit(_G, "            if size > cap:\n", "            if False:\n"),
    ),
    # 25
    _m(
        "25-retiring-target-reference-allowed",
        Edit(
            _V,
            "        if isinstance(ref, ExistingObjectRef) and ref.object_id in retiring:\n",
            "        if False:\n",
        ),
    ),
    # 26
    _m(
        "26-model-risk-kept-for-non-human-assumption",
        Edit(
            _C,
            "    if author.is_human and node.proposed_risk_level is not None:\n",
            "    if node.proposed_risk_level is not None:\n",
        ),
    ),
    # 27
    _m(
        "27-silent-human-assumption-not-high",
        Edit(
            _C,
            "    return _NON_HUMAN_ASSUMPTION_RISK\n",
            "    return RiskLevel.MEDIUM if author.is_human else _NON_HUMAN_ASSUMPTION_RISK\n",
        ),
    ),
    # 28 -- the compiler holds no claim-address data, so "a scope other than the run scope" is
    # exercised through the one other scope it can reach: the referenced existing objects'.
    _m(
        "28-scope-from-referenced-objects",
        Edit(
            _C,
            '            "scope": (visibility.run_scope,),\n',
            '            "scope": next((tuple(o.scope) for r in result.relations if r.source.local_id == local_id and isinstance(r.target, ExistingObjectRef) for o in [visibility.get(r.target.object_id)] if o is not None), (visibility.run_scope,)),\n',
        ),
    ),
    # 29
    _m(
        "29-absent-confidence-defaulted",
        Edit(
            _C,
            '"confidence": node.confidence}',
            '"confidence": node.confidence if node.confidence is not None else 1.0}',
        ),
    ),
    # 30
    _m(
        "30-semantic-base-confidence-optional",
        Edit(
            _S,
            "    confidence: float = Field(ge=0.0, le=1.0)\n",
            "    confidence: float | None = Field(default=None, ge=0.0, le=1.0)\n",
        ),
    ),
    # 31
    _m(
        "31-path-through-absent-node-accepted",
        Edit(
            _V,
            '            node = self.nodes.get(ref.local_id)\n            if node is None:\n                raise IntentGraphValidationError(\n                    "UNRESOLVED_LOCAL_REF",',
            '            node = self.nodes.get(ref.local_id)\n            if node is None:\n                return SemanticKind.GOAL\n            if node is None:\n                raise IntentGraphValidationError(\n                    "UNRESOLVED_LOCAL_REF",',
        ),
        Edit(
            _V,
            "            node = graph.nodes[ident]\n            if node.kind is SemanticKind.INTENT:\n",
            "            node = graph.nodes.get(ident)\n            if node is None or node.kind is SemanticKind.INTENT:\n",
        ),
    ),
)
