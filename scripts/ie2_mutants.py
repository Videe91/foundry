# ruff: noqa: E501
"""IE2 mutant tables consumed by ``scripts/run_ie2_mutations.py``.

One entry per law. Each ``Edit`` replaces text that must occur exactly once in the file; when
code moves, re-anchor the entry -- never delete it to make a run green.

Recovered from the original IE2.1 (42) and IE2.2a (11) harnesses and the IE2.2b-IE2.5 runs,
re-anchored where later slices moved the code. Anchors are deliberately literal source text,
so lines here are allowed to exceed the line-length limit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Edit:
    path: str
    old: str
    new: str


@dataclass(frozen=True)
class Mutant:
    slice: str
    name: str
    edits: tuple[Edit, ...]


_CERT = "tests/certification/"
SLICE_TESTS: dict[str, tuple[str, ...]] = {
    "lv2": ("tests/unit/test_locus_validation_v2_evaluation.py",),
    "ie21": (
        "tests/unit/test_ie21_relation_legality.py",
        "tests/unit/test_ie21_admission.py",
        "tests/unit/test_ie21_graph_semantics.py",
        _CERT,
        "tests/unit/test_package.py",
        "tests/unit/test_closure.py",
    ),
    "ie22a": (
        "tests/unit/test_ie22a_graph_cycles.py",
        "tests/unit/test_ie21_relation_legality.py",
        "tests/unit/test_ie21_admission.py",
        _CERT,
    ),
    "ie22b": (
        "tests/unit/test_ie22b_basis_seam.py",
        "tests/unit/test_ie22b_basis_domain.py",
        "tests/integration/test_intent_synthesis_slice1.py",
        "tests/unit/test_handoff_v2.py",
        "tests/unit/test_ie21_admission.py",
        "tests/unit/test_intent_synthesis_replay.py",
        "tests/unit/test_closure.py",
        "tests/unit/test_ie22c_relevance_seam.py",
        "tests/unit/test_ie22c_relevance_domain.py",
    ),
    "ie22c": (
        "tests/unit/test_ie22c_relevance_seam.py",
        "tests/unit/test_ie22c_relevance_domain.py",
        "tests/unit/test_ie22b_basis_seam.py",
        "tests/unit/test_ie22b_basis_domain.py",
        "tests/integration/test_intent_synthesis_slice1.py",
        "tests/unit/test_handoff_v2.py",
        "tests/unit/test_ie21_admission.py",
        "tests/unit/test_intent_synthesis_replay.py",
        "tests/unit/test_closure.py",
        "tests/unit/test_package.py",
    ),
    "ie23": ("tests/unit/test_ie23_assumption_impact.py",),
    "ie2st": (
        "tests/unit/test_ie2_claim_basis_staleness.py",
        "tests/unit/test_derivation.py",
        "tests/unit/test_semantic_view.py",
        "tests/unit/test_handoff_v2.py",
    ),
    "ie24": ("tests/unit/test_ie24_gap_resolution.py",),
    "ie25": (
        "tests/unit/test_ie25_readiness.py",
        "tests/unit/test_closure.py",
        "tests/unit/test_handoff_v2.py",
    ),
}

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "ie21",
        "01-excludes-legality-dropped",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    RelationType.EXCLUDES: (\n        frozenset({SemanticKind.NON_GOAL}),",
                "    RelationType.EXCLUDES: (\n        frozenset(_NORMATIVE),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "02-derived-from-intent-permitted",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    RelationType.DERIVED_FROM: (frozenset(_NORMATIVE), _BASIS_TARGETS),",
                "    RelationType.DERIVED_FROM: (frozenset(_NORMATIVE), _BASIS_TARGETS | {SemanticKind.INTENT}),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "03-exclusion-blocker-deleted",
        (
            Edit(
                "src/foundry/domain/closure.py",
                "        if isinstance(obj, NonGoal) and obj.authority is Authority.CANONICAL:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "05-exclusion-blocker-fires-on-non-canonical",
        (
            Edit(
                "src/foundry/domain/closure.py",
                "                    and excluded.authority is Authority.CANONICAL",
                "                    and True",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "06-preference-admitted-into-obligations",
        (
            Edit(
                "src/foundry/application/package.py",
                "                if isinstance(obj, Requirement | Constraint | Contract)",
                "                if isinstance(obj, Requirement | Constraint | Contract | Preference)",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "07-exclusion-preference-swapped",
        (
            Edit(
                "src/foundry/application/package.py",
                "        exclusion_ids=_sorted_ids(current, NonGoal),\n        preference_ids=_sorted_ids(current, Preference),",
                "        exclusion_ids=_sorted_ids(current, Preference),\n        preference_ids=_sorted_ids(current, NonGoal),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "08-boundary-ids-drifts-from-the-union",
        (
            Edit(
                "src/foundry/application/package.py",
                "        boundary_ids=_sorted_ids(current, NonGoal, Preference),",
                "        boundary_ids=_sorted_ids(current, NonGoal),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "09-constraint-facet-made-required",
        (
            Edit(
                "src/foundry/domain/semantic.py",
                "    facet: ConstraintFacet | None = None",
                "    facet: ConstraintFacet",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "11-serves-made-non-transitive-root-serving",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "        frozenset(_NORMATIVE - {SemanticKind.INTENT}),",
                "        frozenset(_NORMATIVE),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "12-legality-validated-at-parse-time",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "def validate_relations(state: IntentState, obj: SemanticObject) -> None:",
                "def validate_relations(state: object = None, obj: object = None) -> None:\n    return None\n\n\ndef _unused_validate_relations(state: IntentState, obj: SemanticObject) -> None:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "13-validate-relations-detached-from-the-seam",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        validate_relations(self.state(), obj)",
                "        pass",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "14-derivation-parents-computed-as-empty",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        parents = derivation_parents_of(obj)",
                "        parents = ()",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "15-decision-permitted-as-constrains-source",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    RelationType.CONSTRAINS: (\n        frozenset({SemanticKind.CONSTRAINT}),",
                "    RelationType.CONSTRAINS: (\n        frozenset({SemanticKind.CONSTRAINT, SemanticKind.DECISION}),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "16-decision-removed-as-basis-target",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                '        SemanticKind.DECISION,\n    }\n)\n"""What may ground an object.',
                '    }\n)\n"""What may ground an object.',
            ),
        ),
    ),
    Mutant(
        "ie21",
        "17-external-mandate-collapsed-into-project-waivable",
        (
            Edit(
                "src/foundry/domain/semantic.py",
                '    EXTERNAL_MANDATE = "EXTERNAL_MANDATE"',
                '    EXTERNAL_MANDATE = "PROJECT_BOUNDARY"',
            ),
        ),
    ),
    Mutant(
        "ie21",
        "18-supports-challenges-second-truth",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    RelationType.SUPPORTS: (\n        frozenset({SemanticKind.EVIDENCE}),\n        frozenset({SemanticKind.CLAIM}),\n    ),",
                "    RelationType.SUPPORTS: (\n        frozenset(_NORMATIVE),\n        frozenset({SemanticKind.CLAIM}),\n    ),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "19-supersedes-across-kinds",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "            if target_kind is not source_kind:",
                "            if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "21-non-atomic-object-derive-loop-restored",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        return self._append(\n            EventType.INTENT_OBJECT_ADMITTED,",
                "        for _p in parents:\n            self.derive(obj.id, _p)\n        return self._append(\n            EventType.INTENT_OBJECT_ADMITTED,",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "22-derivation-payload-ignored-by-reducer",
        (
            Edit(
                "src/foundry/application/reducer.py",
                "                        *(\n                            DerivationEdge(\n                                child_id=payload.object.id,\n                                parent_id=parent_id,\n                                recorded_by_event_id=event.event_id,\n                            )\n                            for parent_id in payload.derivation_parent_ids\n                        ),",
                "                        *(),",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "23-reducer-derives-parents-from-relations",
        (
            Edit(
                "src/foundry/application/reducer.py",
                "                            for parent_id in payload.derivation_parent_ids",
                "                            for parent_id in [r.target_id for r in payload.object.relations]",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "24-basis-coherence-weakened-to-a-subset-check",
        (
            Edit(
                "src/foundry/domain/events.py",
                "        if self.derivation_parent_ids != derivation_parents_of(self.object):",
                "        if not set(self.derivation_parent_ids) <= set(derivation_parents_of(self.object)):",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "26-local-copy-of-intent-bearing-kinds",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        if obj.kind not in INTENT_BEARING_SEMANTIC_KINDS:",
                "        if obj.kind not in frozenset({SemanticKind.REQUIREMENT}):",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "27-kind-narrowing-removed",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        if obj.kind not in INTENT_BEARING_SEMANTIC_KINDS:\n            raise ValueError(",
                "        if False:\n            raise ValueError(",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "28-authorship-inferred-from-provenance",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                '        if not author.is_human:\n            raise ValueError(\n                f"{author.provider}/{author.model} may not author a CANONICAL object; "',
                '        if obj.provenance.source_kind.value != "HUMAN":\n            raise ValueError(\n                f"{author.provider}/{author.model} may not author a CANONICAL object; "',
            ),
        ),
    ),
    Mutant(
        "ie21",
        "29-non-human-canonical-accepted",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        if not author.is_human:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "30-covering-authorityrecord-check-removed",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "            covering_authority_record(\n                self.state(), actor_id=author.model, target_scope=obj.scope or None\n            )\n            is None",
                "            False",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "31-human-actor-equality-dropped",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "            if human_actor_id is None or human_actor_id != author.model:",
                "            if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "32-author-dropped-from-payload",
        (
            Edit(
                "src/foundry/domain/events.py",
                "    author: ReasonerFingerprint\n    derivation_parent_ids: tuple[str, ...] = ()",
                "    author: ReasonerFingerprint | None = None\n    derivation_parent_ids: tuple[str, ...] = ()",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "33-target-resolution-narrowed-to-state-objects",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    if target_id in state.semantic.claims:\n        found.append(SemanticKind.CLAIM)",
                "    if False:\n        found.append(SemanticKind.CLAIM)",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "34-ambiguous-id-silently-resolved",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    if len(set(found)) > 1 or len(found) > 1:",
                "    if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "35-unresolved-target-ignored",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                "    if not found:\n        raise UnresolvedTargetError(",
                "    if False:\n        raise UnresolvedTargetError(",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "36-duplicate-id-check-removed",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        if obj.id in self.state().objects:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "37-reducer-overwrites-existing-object",
        (
            Edit(
                "src/foundry/application/reducer.py",
                "            if payload.object.id in state.objects:",
                "            if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "10-canonical-constraint-facet-requirement-removed",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        if obj.facet is None:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "20-external-mandate-accepted-from-project-human-provenance",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "            and obj.provenance.source_kind is SourceKind.HUMAN",
                "            and False",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "25-admission-folded-into-the-shared-object-reducer-case",
        (
            Edit(
                "src/foundry/application/reducer.py",
                "        case EventType.INTENT_OBJECT_ADMITTED:",
                "        case EventType.INTENT_OBJECT_ADMITTED if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "38-undefined-relations-silently-permitted",
        (
            Edit(
                "src/foundry/domain/relation_legality.py",
                '            raise IllegalRelationError(\n                f"{relation.relation_type.value} has no IE2 legality',
                '            continue\n            raise IllegalRelationError(\n                f"{relation.relation_type.value} has no IE2 legality',
            ),
        ),
    ),
    Mutant(
        "ie21",
        "39-admission-event-skips-project-coherence",
        (
            Edit(
                "src/foundry/domain/events.py",
                "    elif isinstance(payload, IntentObjectPayload | IntentObjectAdmissionPayload):",
                "    elif isinstance(payload, IntentObjectPayload):",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "40-admission-event-accepts-any-kind",
        (
            Edit(
                "src/foundry/domain/events.py",
                "        if self.object.kind not in INTENT_BEARING_SEMANTIC_KINDS:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "41-admission-event-skips-basis-coherence",
        (
            Edit(
                "src/foundry/domain/events.py",
                "        if self.derivation_parent_ids != derivation_parents_of(self.object):",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "42-canonical-parent-tuple-unsorted-duplicated",
        (
            Edit(
                "src/foundry/domain/events.py",
                "    return tuple(\n        sorted(\n            {",
                "    return tuple(\n        (\n            [",
            ),
        ),
    ),
    Mutant(
        "ie21",
        "43-exclusion-blocks-a-non-current-target",
        (
            Edit(
                "src/foundry/domain/closure.py",
                "                    and excluded in current",
                "                    and True",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "01-cycle-check-removed-from-the-seam",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        assert_no_cycle_introduced(self.state(), obj)",
                "        pass",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "02-serves-not-checked",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "    {RelationType.SERVES, RelationType.DERIVED_FROM}",
                "    {RelationType.DERIVED_FROM}",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "03-derived-from-not-checked",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "    {RelationType.SERVES, RelationType.DERIVED_FROM}",
                "    {RelationType.SERVES}",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "04-visited-set-removed",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "        if current in visited:\n            continue\n        visited.add(current)",
                "        pass",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "05-traversal-depth-capped-at-1",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "        visited.add(current)",
                "        visited.add(current)\n        if len(visited) > 1:\n            continue",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "06-dangling-candidate-id-ignored",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "        if current == target_id:\n            return True",
                "        if current == target_id and current in state.objects:\n            return True",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "07-any-reachable-cycle-treated-as-the-candidate-s",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "        if current == target_id:\n            return True",
                "        if current in visited:\n            return True\n        if current == target_id:\n            return True",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "08-diamond-reconvergence-treated-as-a-cycle",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "        if current in visited:\n            continue",
                "        if current in visited:\n            return True",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "09-relation-type-ignored-during-the-walk",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "            if relation.relation_type is relation_type:",
                "            if True:",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "10-cycle-checked-relation-set-emptied",
        (
            Edit(
                "src/foundry/domain/graph_cycles.py",
                "    {RelationType.SERVES, RelationType.DERIVED_FROM}",
                "    set()",
            ),
        ),
    ),
    Mutant(
        "ie22a",
        "11-cycle-validation-moved-into-the-reducer",
        (
            Edit(
                "src/foundry/application/reducer.py",
                "        case EventType.INTENT_OBJECT_ADMITTED:",
                "        case EventType.INTENT_OBJECT_ADMITTED if _reject_cycles_at_replay():",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "claim-authority",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if claim.authority is not Authority.CANONICAL:",
                "if claim.authority is Authority.REJECTED:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "claim-judgment-live",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if claim.created_by_judgment_id not in self.active_judgments:",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "claim-evidence-present",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "            if missing:",
                "            if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "evidence-terminal",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "        if obj is None:\n            return _Verdict(\n                UNGROUNDED_CANONICAL_OBJECT,",
                "        if obj is None:\n            return _Verdict(\n                None,",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "assumption",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if kind is SemanticKind.ASSUMPTION:",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "node-current",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if not object_is_current(obj):",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "node-canonical",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if obj.authority is not Authority.CANONICAL:",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "decision-rationale-ignored",
        (
            Edit(
                "src/foundry/domain/basis.py",
                '            if not parents:\n                return _Verdict(\n                    None, node_id, "lawful authoritative terminal"',
                '            if True:\n                return _Verdict(\n                    None, node_id, "lawful authoritative terminal"',
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "intermediate-bare-lawful",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "            if not parents:\n                return _Verdict(\n                    UNGROUNDED_CANONICAL_OBJECT,",
                "            if not parents:\n                return _Verdict(\n                    None,",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "other-kinds-lawful",
        (
            Edit(
                "src/foundry/domain/basis.py",
                'return _Verdict(UNGROUNDED_CANONICAL_OBJECT, node_id, f"{kind.value} is never a basis")',
                'return _Verdict(None, node_id, f"{kind.value} is never a basis")',
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "cycle-check",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if node_id in self.on_path:",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "every-branch",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "if child.code is not None:",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "facet-evidential",
        (
            Edit(
                "src/foundry/domain/basis.py",
                "and not any(v.evidential for v in verdicts)",
                "and False",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "seam-call",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "            assert_lawful_basis(self.state(), obj)",
                "            pass",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "seam-gate",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "        if obj.authority is Authority.CANONICAL:\n            # Non-canonical",
                "        if True:\n            # Non-canonical",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "ready-deliverable",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        and not basis\n",
                "\n",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "ready-canonical-filter",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        and obj.authority is Authority.CANONICAL\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "ready-current-filter",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        if object_is_current(obj)\n        and",
                "        if",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "ready-scope-filter",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        and scope_applies(tuple(obj.scope), scope)\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "codes-exposed",
        (
            Edit(
                "src/foundry/application/handoff_v2.py",
                "    applicable.update({code: code in basis_codes for code in BASIS_BLOCKER_CODES})",
                "    applicable.update({code: False for code in BASIS_BLOCKER_CODES})",
            ),
        ),
    ),
    Mutant(
        "ie22b",
        "current-lifecycle",
        (
            Edit(
                "src/foundry/domain/authority.py",
                "return obj.lifecycle is LifecycleStatus.ACTIVE and obj.authority not in _DEAD_AUTHORITIES",
                "return obj.authority not in _DEAD_AUTHORITIES",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "seam-relevance-call",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "            assert_relevant(self.state(), obj)\n",
                "            pass\n",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "non-canonical-checked",
        (
            Edit(
                "src/foundry/application/semantic_governance.py",
                "            assert_relevant(self.state(), obj)\n",
                "            pass\n        assert_relevant(self.state(), obj)\n",
            ),
            Edit(
                "src/foundry/domain/relevance.py",
                "    if obj.authority is not Authority.CANONICAL:\n        return\n    scopes",
                "    if False:\n        return\n    scopes",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "kind-omitted-decision",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                '        SemanticKind.DECISION,\n    }\n)\n"""§4a',
                '    }\n)\n"""§4a',
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "assumption-included",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                '        SemanticKind.DECISION,\n    }\n)\n"""§4a',
                '        SemanticKind.DECISION,\n        SemanticKind.ASSUMPTION,\n    }\n)\n"""§4a',
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "intermediate-current",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and _live_canonical(obj, scope):\n            for target_id",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and obj.authority is Authority.CANONICAL and _applies(obj, scope):\n            for target_id",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "intermediate-canonical",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and _live_canonical(obj, scope):\n            for target_id",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and object_is_current(obj) and _applies(obj, scope):\n            for target_id",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "intermediate-applicability",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and _live_canonical(obj, scope):\n            for target_id",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and object_is_current(obj) and obj.authority is Authority.CANONICAL:\n            for target_id",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "intermediate-kind",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "        if obj.kind in RELEVANCE_BEARING_KINDS and _live_canonical(obj, scope):\n            for target_id",
                "        if _live_canonical(obj, scope):\n            for target_id",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "root-applicability",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "            if obj.kind is SemanticKind.INTENT and _live_canonical(obj, scope)",
                "            if obj.kind is SemanticKind.INTENT and object_is_current(obj) and obj.authority is Authority.CANONICAL",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "global-as-any",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "    if scope is None:\n        return obj.scope == ()",
                "    if scope is None:\n        return True",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "global-skipped",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "tuple(obj.scope) or (None,)",
                "tuple(obj.scope) or ()",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "serves-as-derived",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "                if relation.relation_type is RelationType.SERVES",
                "                if relation.relation_type is RelationType.DERIVED_FROM",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "any-root",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "    elif len(roots) == 1:",
                "    if len(roots) >= 1:",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "multiple-root-removed",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "        blockers.append(RelevanceBlocker(code=MULTIPLE_CANONICAL_ROOTS, object_ids=roots))",
                "        pass",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "cycle-detection-removed",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "        for cycle in _serves_cycles(state, scope)",
                "        for cycle in ()",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "visited-removed",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "            if source_id not in relevant:",
                "            if True:",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "diamond-as-cycle",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "if len(component) > 1 or node_id in edges[node_id]:",
                "if len(component) >= 1:",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "orphan-suppressed",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "            and obj.id not in relevant\n",
                "            and False\n",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "pd-applicability",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "            if not _applies(decision, scope) or (\n",
                "            if False or (\n",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "pd-serves",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "                relevant is not None and decision_id not in relevant\n",
                "                False\n",
            ),
            Edit(
                "src/foundry/domain/relevance.py",
                "            if decision_id not in relevant:\n                raise",
                "            if False:\n                raise",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "pd-admission-only",
        (
            Edit(
                "src/foundry/domain/relevance.py",
                "            if decision_id not in relevant:\n                raise",
                "            if False:\n                raise",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "pd-readiness-wiring",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "    for object_id, decision_id in irrelevant_decision_terminals(state, scope):",
                "    for object_id, decision_id in ():",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "readiness-ignores-relevance",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        and not relevance\n",
                "\n",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "code-mapping",
        (
            Edit(
                "src/foundry/application/handoff_v2.py",
                "    applicable.update({code: code in relevance_codes for code in RELEVANCE_BLOCKER_CODES})",
                "    applicable.update({code: False for code in RELEVANCE_BLOCKER_CODES})",
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "code-order",
        (
            Edit(
                "src/foundry/application/handoff_v2.py",
                '    "RELEVANCE_CYCLE",\n    "UNGROUNDED',
                '    "UNGROUNDED',
            ),
        ),
    ),
    Mutant(
        "ie22c",
        "scope-helper",
        (
            Edit(
                "src/foundry/domain/scope.py",
                "return scope_descriptor == () or evaluated_scope in scope_descriptor",
                "return evaluated_scope in scope_descriptor",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "seed-removed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    seeds = direct_assumption_impacts(state, assumption_id)\n",
                "    direct_assumption_impacts(state, assumption_id)\n    seeds: tuple[str, ...] = ()\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "first-target-only",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    seeds = direct_assumption_impacts(state, assumption_id)\n",
                "    seeds = direct_assumption_impacts(state, assumption_id)[:1]\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "derived-propagation-removed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        for parent_id in derivation_parents_of(obj):",
                "        for parent_id in ():",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "direction-reversed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "            children.setdefault(parent_id, []).append(obj.id)",
                "            children.setdefault(obj.id, []).append(parent_id)",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "one-hop",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "            if child_id not in reached:\n                reached.add(child_id)\n                frontier.append(child_id)",
                "            if child_id not in reached:\n                reached.add(child_id)",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "visited-removed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "            if child_id not in reached:\n",
                "            if True:\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "dead-intermediate-stops",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "            if child_id not in reached:\n",
                "            if child_id not in reached and object_is_current(state.objects[child_id]):\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "current-filter-removed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        if object_is_current(state.objects[object_id])\n",
                "        if True\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "rejected-included",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        if object_is_current(state.objects[object_id])\n",
                '        if state.objects[object_id].lifecycle.value == "ACTIVE" and state.objects[object_id].authority.value != "SUPERSEDED"\n',
            ),
        ),
    ),
    Mutant(
        "ie23",
        "superseded-included",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        if object_is_current(state.objects[object_id])\n",
                '        if state.objects[object_id].authority.value != "REJECTED"\n',
            ),
        ),
    ),
    Mutant(
        "ie23",
        "unrelated-branch-included",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    frontier = list(seeds)\n",
                "    frontier = list(seeds) + list(children)\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "derivation-edge-substituted",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        for parent_id in derivation_parents_of(obj):\n            children.setdefault(parent_id, []).append(obj.id)",
                "        pass\n    for edge in state.semantic.derivations:\n        children.setdefault(edge.parent_id, []).append(edge.child_id)",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "serves-propagated",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        for parent_id in derivation_parents_of(obj):",
                "        for parent_id in [r.target_id for r in obj.relations if r.relation_type in (RelationType.DERIVED_FROM, RelationType.SERVES)]:",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "diamond-duplicates",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    reached = set(seeds)\n",
                "    emitted = list(seeds)\n    reached = set(seeds)\n",
            ),
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        for child_id in children.get(parent_id, ()):\n",
                "        for child_id in children.get(parent_id, ()):\n            emitted.append(child_id)\n",
            ),
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    reached.discard(assumption_id)\n    return tuple(sorted(reached))",
                "    return tuple(sorted(emitted))",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "order-reversed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    reached.discard(assumption_id)\n    return tuple(sorted(reached))",
                "    reached.discard(assumption_id)\n    return tuple(sorted(reached, reverse=True))",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "order-unsorted",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    reached.discard(assumption_id)\n    return tuple(sorted(reached))",
                "    reached.discard(assumption_id)\n    return tuple(reached)",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "direct-order-unsorted",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    return tuple(\n        sorted(\n            {\n                relation.target_id",
                "    return tuple(\n        list(\n            {\n                relation.target_id",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "direct-order-reversed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    return tuple(\n        sorted(\n            {\n                relation.target_id",
                "    return tuple(\n        sorted(reverse=True, iterable=\n            {\n                relation.target_id",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "same-scope-inferred",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    reached = set(seeds)\n",
                "    reached = set(seeds) | {o.id for o in state.objects.values() for s in seeds if o.id != assumption_id and o.scope == state.objects[s].scope}\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "same-text-inferred",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    reached = set(seeds)\n",
                "    reached = set(seeds) | {o.id for o in state.objects.values() for s in seeds if o.id != assumption_id and getattr(o, 'statement', None) == getattr(state.objects[s], 'statement', 1)}\n",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "dangling-not-ignored",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "                and _local(state, relation.target_id)\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "project-local-removed",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "        if obj.project_id != state.project_id:\n            continue\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "non-assumption-accepted",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                "    if not isinstance(obj, Assumption):",
                "    if False:",
            ),
        ),
    ),
    Mutant(
        "ie23",
        "missing-means-empty",
        (
            Edit(
                "src/foundry/domain/assumption_impact.py",
                '    if obj is None or obj.project_id != state.project_id:\n        raise UnknownAssumptionError(f"no assumption {assumption_id!r} in {state.project_id!r}")',
                "    if obj is None:\n        return Assumption.model_construct(relations=())  # type: ignore[return-value]",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "kind-removed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        GapKind.CONTEXT_FAILURE: frozenset({_D}),\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "missing-authority-gains-research",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        GapKind.MISSING_AUTHORITY: frozenset({_H}),",
                "        GapKind.MISSING_AUTHORITY: frozenset({_H, _R}),",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "stale-evidence-loses-research",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        GapKind.STALE_EVIDENCE: frozenset({_R}),",
                "        GapKind.STALE_EVIDENCE: frozenset({_H}),",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "worker-divergence-not-singleton",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        GapKind.WORKER_DIVERGENCE: frozenset({_C}),",
                "        GapKind.WORKER_DIVERGENCE: frozenset({_C, _H}),",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "unsupported-assumption-loses-wait",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        GapKind.UNSUPPORTED_ASSUMPTION: frozenset({_R, _H, _W}),",
                "        GapKind.UNSUPPORTED_ASSUMPTION: frozenset({_R, _H}),",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "singleton-suppressed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "deterministic_route=candidates[0] if len(candidates) == 1 else None,",
                "deterministic_route=None,",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "multi-route-selects-first",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "deterministic_route=candidates[0] if len(candidates) == 1 else None,",
                "deterministic_route=candidates[0] if candidates else None,",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "resolved-included-bulk",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        if state.gaps[gap_id].status is GapStatus.OPEN\n",
                "        if state.gaps[gap_id].status is not GapStatus.WAIVED\n",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "waived-included-bulk",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        if state.gaps[gap_id].status is GapStatus.OPEN\n",
                "        if state.gaps[gap_id].status is not GapStatus.RESOLVED\n",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "closed-planned-single",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    if gap.status is not GapStatus.OPEN:\n        raise",
                "    if False:\n        raise",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "validator-accepts-illegal",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    return route in LAWFUL_ROUTES[plan.gap_kind]",
                "    return True",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "plan-validator-removed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                '    @model_validator(mode="after")\n',
                "",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "candidate-equality-removed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        if self.candidate_routes != expected:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "deterministic-invariant-removed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        if self.deterministic_route is not decided:",
                "        if False:",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "route-check-trusts-plan",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    return route in LAWFUL_ROUTES[plan.gap_kind]",
                "    return route in plan.candidate_routes",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "planner-wrong-kind",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        gap_kind=gap.kind,",
                "        gap_kind=GapKind.MISSING_INFORMATION,",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "assumption-impact-removed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "            impacted.update(actionable_assumption_blast_radius(state, object_id))",
                "            pass",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "assumption-impact-every-kind",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    if gap.kind is not GapKind.UNSUPPORTED_ASSUMPTION:\n        return ()\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "assumption-first-only",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    for object_id in gap.affected_object_ids:\n        obj",
                "    for object_id in gap.affected_object_ids[:1]:\n        obj",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "historical-radius-used",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "impacted.update(actionable_assumption_blast_radius(state, object_id))",
                "impacted.update(__import__('foundry.domain.assumption_impact', fromlist=['x']).assumption_blast_radius(state, object_id))",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "candidate-order-frozenset",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    return tuple(route for route in ROUTE_ORDER if route in lawful)",
                "    return tuple(lawful)",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "candidate-order-reversed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "    return tuple(route for route in ROUTE_ORDER if route in lawful)",
                "    return tuple(route for route in reversed(ROUTE_ORDER) if route in lawful)",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "bulk-order-insertion",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        for gap_id in sorted(state.gaps)\n",
                "        for gap_id in state.gaps\n",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "bulk-order-reversed",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        for gap_id in sorted(state.gaps)\n",
                "        for gap_id in sorted(state.gaps, reverse=True)\n",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "affected-ids-rewritten",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        affected_object_ids=tuple(gap.affected_object_ids),",
                "        affected_object_ids=tuple(sorted(gap.affected_object_ids)),",
            ),
        ),
    ),
    Mutant(
        "ie24",
        "dangling-dropped",
        (
            Edit(
                "src/foundry/domain/gap_resolution.py",
                "        affected_object_ids=tuple(gap.affected_object_ids),",
                "        affected_object_ids=tuple(i for i in gap.affected_object_ids if i in state.objects),",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "gap-plans-removed",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        gap_resolution_plans=scoped_open_gap_resolution_plans(state, scope),\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "closed-gaps-included",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        if state.gaps[gap_id].status is GapStatus.OPEN\n",
                "        if True\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "out-of-scope-gap-included",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        and gap_applies(state, state.gaps[gap_id], scope)\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "gap-scope-duplicated-naively",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        and gap_applies(state, state.gaps[gap_id], scope)\n",
                "        and (not state.gaps[gap_id].affected_object_ids or any(scope_applies(tuple(state.objects[i].scope), scope) for i in state.gaps[gap_id].affected_object_ids if i in state.objects))\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "gap-scope-synthesis-check-removed",
        (
            Edit(
                "src/foundry/domain/gap_scope.py",
                "    if isinstance(gap, IntentSynthesisGap) and gap.scope != () and scope not in gap.scope:\n        return False\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "gap-scope-unknown-not-applying",
        (
            Edit(
                "src/foundry/domain/gap_scope.py",
                "        if obj is None:\n            return True",
                "        if obj is None:\n            continue",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "assumption-impact-lost",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        gap_resolution_plan(state, gap_id)\n",
                "        gap_resolution_plan(state, gap_id).model_copy(update={'assumption_impact_ids': ()})\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "only-blocking-gaps",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        and gap_applies(state, state.gaps[gap_id], scope)\n",
                "        and gap_applies(state, state.gaps[gap_id], scope)\n        and state.gaps[gap_id].blocking\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "only-non-blocking-gaps",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        and gap_applies(state, state.gaps[gap_id], scope)\n",
                "        and gap_applies(state, state.gaps[gap_id], scope)\n        and not state.gaps[gap_id].blocking\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "inert-detection-removed",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        inert_decision_ids=scoped_inert_decision_ids(state, scope),\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "decision-direction-reversed",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "            and obj.id not in used\n",
                "            and not derivation_parents_of(obj)\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "proposed-consequence-ignored",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        if _live_in(obj, scope):\n            # A self-edge",
                "        if _live_in(obj, scope) and obj.authority is Authority.CANONICAL:\n            # A self-edge",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "dead-consequence-counts",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        if _live_in(obj, scope):\n            # A self-edge",
                "        if scope_applies(tuple(obj.scope), scope):\n            # A self-edge",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "out-of-scope-consequence-counts",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "        if _live_in(obj, scope):\n            # A self-edge",
                "        if object_is_current(obj):\n            # A self-edge",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "non-canonical-decision-reported",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "            and obj.authority is Authority.CANONICAL\n            and _live_in(obj, scope)\n            and obj.id not in used",
                "            and _live_in(obj, scope)\n            and obj.id not in used",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "preferences-removed",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        preference_ids=scoped_preference_ids(state, scope),\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "proposed-preference-omitted",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "            if isinstance(obj, Preference) and _live_in(obj, scope)",
                "            if isinstance(obj, Preference) and _live_in(obj, scope) and obj.authority is Authority.CANONICAL",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "dead-preference-included",
        (
            Edit(
                "src/foundry/domain/completeness.py",
                "            if isinstance(obj, Preference) and _live_in(obj, scope)",
                "            if isinstance(obj, Preference) and scope_applies(tuple(obj.scope), scope)",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "preference-gates-deliverable",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        and not relevance\n",
                "        and not relevance\n        and not scoped_preference_ids(state, scope)\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "inert-decision-gates-deliverable",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "        and not relevance\n",
                "        and not relevance\n        and not scoped_inert_decision_ids(state, scope)\n",
            ),
        ),
    ),
    Mutant(
        "ie25",
        "excludes-duplicated-v2",
        (
            Edit(
                "src/foundry/domain/handoff_v2.py",
                "    relevance = relevance_blockers(state, scope)\n",
                "    relevance = relevance_blockers(state, scope) + tuple(RelevanceBlocker(code='EXCLUSION_BLOCKER_V2', object_ids=(o.id,)) for o in state.objects.values() for r in o.relations if r.relation_type.value == 'EXCLUDES')\n",
            ),
        ),
    ),
    # IE2 repair R105-R107: writer-independent claim-basis staleness.
    Mutant(
        "ie2st",
        "claim-basis-roots-removed",
        (
            Edit(
                "src/foundry/domain/derivation.py",
                "        | descendants(state.derivations, stale_claim_roots)\n",
                "",
            ),
        ),
    ),
    Mutant(
        "ie2st",
        "claim-roots-returned-as-stale",
        (
            Edit(
                "src/foundry/domain/derivation.py",
                "        | stale_versions\n    )\n",
                "        | stale_versions\n        | stale_claim_roots\n    )\n",
            ),
        ),
    ),
    Mutant(
        "ie2st",
        "live-claims-rooted",
        (
            Edit(
                "src/foundry/domain/derivation.py",
                "        if claim.created_by_judgment_id in inactive\n",
                "        if True\n",
            ),
        ),
    ),
    # --- locus validation v2: the structural evaluator's laws ---------------------------
    Mutant("lv2", "lv2-missing-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if target is None or bound.get(target, 0) != 1:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-wrong-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if address_id not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-over-split-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '    if len(creates) > item.creates:\n', '    if False:\n'),)),
    Mutant("lv2", "lv2-merged-creation-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if others:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-new-claim-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if got != n:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-wrong-support-address-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if where not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-missing-support-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if missing:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-address-claim-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '            if address_id is None or got != want:\n', '            if False:\n'),)),
    Mutant("lv2", "lv2-nearby-merge-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if insurance is None or late is None or insurance == late:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-address-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if got != want:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-rejected-admission-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if d.route == "REJECT":\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-fabricated-supersede-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if not expected_keys:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-supersede-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '    if expected_keys and len(supersedes) != len(expected_keys):\n', '    if False:\n'),)),
    Mutant("lv2", "lv2-conflict-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if named_pair not in wanted:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-missing-conflict-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '    if wanted - named:\n', '    if False:\n'),)),
    Mutant("lv2", "lv2-replay-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if lg.replay_matches is not True:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-calls-per-delta-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if dict(per_t) != expected_calls:\n', '        if False:\n'),)),
    Mutant("lv2", "lv2-reference-law-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '                    if problem:\n', '                    if False:\n'),)),
    Mutant("lv2", "lv2-supersede-target-unchecked", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        elif where not in {lg.addresses.get(k) for k in expected_keys}:\n', '        elif False:\n'),)),
    Mutant("lv2", "lv2-unexpected-claims-ignored", (Edit("src/foundry/experiments/locus_validation_v2/evaluation.py", '        if address_id in expected_new:\n', '        if True:\n'),)),
)
