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
    "lf": ("tests/unit/test_locus_formation_grain.py",),
    "cf": (
        "tests/unit/test_canonical_facet_policy.py",
        "tests/unit/test_canonical_facet_grain.py",
        "tests/unit/test_admission.py",
        "tests/unit/test_xai_semantic_reasoner.py",
    ),
    "lv2": ("tests/unit/test_locus_validation_v2_evaluation.py",),
    "rp": (
        "tests/unit/test_ie3_parallel_node.py",
        "tests/unit/test_structural_reproposal.py",
    ),
    "pa": (
        "tests/unit/test_proposition_accounting.py",
        "tests/unit/test_proposition_accounting_policy.py",
    ),
    "lh23": ("tests/unit/test_long_horizon_ie2_ie3.py",),
    "ar": ("tests/unit/test_authority_routing.py",),
    "scv": (
        "tests/unit/test_semantic_completeness_domain.py",
        "tests/unit/test_semantic_completeness_pipeline.py",
        "tests/unit/test_semantic_completeness_adapters.py",
        "tests/unit/test_completeness_verifier_exam.py",
        "tests/unit/test_structural_reproposal.py",
    ),
    "scv2": (
        "tests/certification/test_semantic_completeness_exam_v2.py",
        "tests/certification/test_semantic_completeness_exam_v2_harness.py",
        "tests/certification/test_semantic_completeness_exam_v2_certificate.py",
    ),
    "scv3": (
        "tests/certification/test_semantic_completeness_exam_v3_coherence.py",
        "tests/certification/test_semantic_completeness_exam_v3.py",
        "tests/certification/test_semantic_completeness_exam_v3_harness.py",
        "tests/certification/test_semantic_completeness_exam_v3_certificate.py",
    ),
    "scv4": (
        "tests/certification/test_semantic_completeness_exam_v4_actor.py",
        "tests/certification/test_semantic_completeness_exam_v4.py",
        "tests/certification/test_semantic_completeness_exam_v4_harness.py",
        "tests/certification/test_semantic_completeness_exam_v4_certificate.py",
    ),
    "scv5": (
        "tests/certification/test_semantic_completeness_exam_v5.py",
        "tests/certification/test_semantic_completeness_exam_v5_replay.py",
        "tests/certification/test_semantic_completeness_exam_v5_harness.py",
        "tests/certification/test_semantic_completeness_exam_v5_certificate.py",
    ),
    "scs": (
        "tests/unit/test_semantic_completeness_v2_domain.py",
        "tests/unit/test_semantic_completeness_v2_adapter.py",
        "tests/unit/test_semantic_completeness_v2_pipeline.py",
        "tests/certification/test_structured_completeness_diagnostic.py",
    ),
    "scx": (
        "tests/unit/test_model_runtime_contract_routing.py",
        "tests/unit/test_semantic_completeness_v2_domain.py",
        "tests/certification/test_structured_completeness_exam.py",
        "tests/certification/test_structured_completeness_exam_harness.py",
        "tests/certification/test_structured_completeness_exam_certificate.py",
    ),
    "rts": (
        "tests/unit/test_semantic_completeness_v3.py",
        "tests/unit/test_semantic_completeness_v3_pipeline.py",
    ),
    "rth": (
        "tests/unit/test_runtime_holds.py",
        "tests/unit/test_conflict_policy.py",
        "tests/unit/test_semantic_completeness_v3_pipeline.py",
        "tests/unit/test_intent_engine_e2e_harness.py",
    ),
    "rta": (
        "tests/unit/test_semantic_admission_v4.py",
        "tests/unit/test_runtime_holds.py",
        "tests/unit/test_intent_engine_e2e_harness.py",
    ),
    "rv5": (
        "tests/unit/test_semantic_admission_v5.py",
        "tests/unit/test_runtime_holds.py",
        "tests/unit/test_intent_engine_live_v2_routing.py",
    ),
    "e2e": (
        "tests/unit/test_intent_engine_e2e_outcome.py",
        "tests/unit/test_intent_engine_e2e_harness.py",
    ),
    "lv6": (
        "tests/unit/test_locus_validation_v6_corpus.py",
        "tests/unit/test_locus_validation_v6_answer_key.py",
        "tests/unit/test_locus_validation_v6_seal.py",
        "tests/unit/test_locus_validation_v6_evaluation.py",
        "tests/unit/test_locus_validation_v6_authority.py",
        "tests/unit/test_locus_validation_v6_adjudication.py",
    ),
    "cs": (
        "tests/unit/test_correction_set_authority.py",
        "tests/unit/test_authority_routing.py",
    ),
    "cc": (
        "tests/unit/test_correction_cardinality.py",
        "tests/unit/test_correction_set_policy.py",
    ),
    "lv5": (
        "tests/unit/test_locus_validation_v5_evaluation.py",
        "tests/unit/test_locus_validation_v5_adjudication.py",
        "tests/unit/test_locus_validation_v5_seal.py",
    ),
    "lv4": (
        "tests/unit/test_locus_validation_v4_evaluation.py",
        "tests/unit/test_locus_validation_v4_adjudication.py",
        "tests/unit/test_locus_validation_v4_seal.py",
    ),
    "lv3": (
        "tests/unit/test_locus_validation_v3_evaluation.py",
        "tests/unit/test_locus_validation_v3_adjudication.py",
    ),
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
                "        | descendants(edges, stale_claim_roots)\n",
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
                "        | stale_versions\n    ) - staleness_boundary_ids\n",
                "        | stale_versions\n        | stale_claim_roots\n    ) - staleness_boundary_ids\n",
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
    # --- locus validation v3: structural laws, timepoint-exact packets and the standing ---
    Mutant("lv3", "lv3-missing-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if target is None or bound.get(target, 0) != 1:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-wrong-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if address_id not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-over-split-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '    if len(creates) > item.creates:\n', '    if False:\n'),)),
    Mutant("lv3", "lv3-merged-creation-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if others:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-new-claim-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if got != n:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-wrong-support-address-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if where not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-missing-support-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if missing:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-address-claim-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '            if address_id is None or got != want:\n', '            if False:\n'),)),
    Mutant("lv3", "lv3-separate-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if a is None or b is None or a == b:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-address-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if got != want:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-rejected-admission-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if d.route == "REJECT":\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-fabricated-supersede-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if not expected_keys:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-supersede-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '    if expected_keys and len(supersedes) != len(expected_keys):\n', '    if False:\n'),)),
    Mutant("lv3", "lv3-conflict-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if named_pair not in wanted:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-missing-conflict-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '    if wanted - named:\n', '    if False:\n'),)),
    Mutant("lv3", "lv3-replay-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if lg.replay_matches is not True:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-calls-per-delta-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if dict(per_t) != expected_calls:\n', '        if False:\n'),)),
    Mutant("lv3", "lv3-reference-law-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '                    if problem:\n', '                    if False:\n'),)),
    Mutant("lv3", "lv3-supersede-target-unchecked", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        elif where not in {lg.addresses.get(k) for k in expected_keys}:\n', '        elif False:\n'),)),
    Mutant("lv3", "lv3-unexpected-claims-ignored", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '        if address_id in expected_new:\n', '        if True:\n'),)),
    Mutant("lv3", "lv3-split-tally-blind", (Edit("src/foundry/experiments/locus_validation_v3/evaluation.py", '            if tag in tally:\n', '            if False:\n'),)),
    Mutant("lv3", "lv3-packet-uses-final-state", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '    state = run.deltas[after - 1].state_after.semantic\n', '    state = run.deltas[-1].state_after.semantic\n'),)),
    Mutant("lv3", "lv3-packet-shows-later-documents", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '(REVISION[run.ledger] if after == 2 else ())', 'REVISION[run.ledger]'),)),
    Mutant("lv3", "lv3-packet-drops-relations", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '        relations.append(entry)\n', '        pass\n'),)),
    Mutant("lv3", "lv3-bundle-ignores-timepoint", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '        frozen = packet(lg, q.after) if lg is not None else None\n', '        frozen = packet(lg, 2) if lg is not None else None\n'),)),
    Mutant("lv3", "lv3-standing-ignores-no", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '    semantic_ok = not missing and not said_no\n', '    semantic_ok = not missing\n'),)),
    Mutant("lv3", "lv3-standing-ignores-missing", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '    semantic_ok = not missing and not said_no\n', '    semantic_ok = not said_no\n'),)),
    Mutant("lv3", "lv3-standing-ignores-structural", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '    validated = structural_ok and semantic_ok and critical and all(cases.values())\n', '    validated = semantic_ok and critical and all(cases.values())\n'),)),
    Mutant("lv3", "lv3-standing-ignores-critical", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '    critical = cases.get(CRITICAL_CASE, False)\n', '    critical = True\n'),)),
    Mutant("lv3", "lv3-case-ignores-semantic", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", '        and all(answers.get(q) == "YES" for q in c.semantic)\n', '\n'),)),
    Mutant("lv3", "lv3-lowercase-yes-accepted", (Edit("src/foundry/experiments/locus_validation_v3/adjudication.py", 'answers.get(q.id, "YES") != "YES"', 'answers.get(q.id, "YES").upper() != "YES"'),)),
    # --- canonical facet: projection, admission invariant, contract, source coverage -------
    Mutant("cf", "cf-projection-folds-case", (Edit('src/foundry/domain/semantic_identity.py', '    return CANONICAL_FACET_PREFIX + subject\n', '    return CANONICAL_FACET_PREFIX + subject.lower()\n'),)),
    Mutant("cf", "cf-projection-is-generic", (Edit('src/foundry/domain/semantic_identity.py', '    return CANONICAL_FACET_PREFIX + subject\n', '    return "How it is governed"\n'),)),
    Mutant("cf", "cf-invariant-never-applied", (Edit('src/foundry/domain/admission.py', '    if policy.canonical_facets:\n', '    if False:\n'),)),
    Mutant("cf", "cf-invariant-accepts-any-facet", (Edit('src/foundry/domain/admission.py', '    if candidate.facet == canonical_facet(candidate.subject):\n', '    if True:\n'),)),
    Mutant("cf", "cf-invariant-skips-bind", (Edit('src/foundry/domain/admission.py', 'def _facet_problems(p: JudgmentProposal) -> list[str]:\n    if not isinstance(p, CreateAddressProposal | BindToAddressProposal):\n', 'def _facet_problems(p: JudgmentProposal) -> list[str]:\n    if not isinstance(p, CreateAddressProposal):\n'),)),
    Mutant("cf", "cf-flag-on-by-default", (Edit('src/foundry/domain/admission.py', '    canonical_facets: bool = False\n', '    canonical_facets: bool = True\n'),)),
    Mutant("cf", "cf-adapter-copies-subject", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', 'else canonical_facet(draft.subject),', 'else draft.subject,'),)),
    Mutant("cf", "cf-policy-sends-historical-contract", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '    draft_payload: ClassVar[type[DraftPayload]] = ConcernDraftPayload\n', '    draft_payload: ClassVar[type[DraftPayload]] = SemanticDraftPayload\n'),)),
    Mutant("cf", "cf-transport-ignores-contract", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', 'response_format=self.draft_payload,', 'response_format=SemanticDraftPayload,'),)),
    Mutant("cf", "cf-parser-ignores-contract", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '_parse_payload(response, self.draft_payload)', '_parse_payload(response)'),)),
    Mutant("cf", "cf-prompt-drops-generic-rule", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', 'never one dimension of the concern, never a generic word such as', 'never one dimension of the concern, never a word such as'),)),
    Mutant("cf", "cf-coverage-ignores-unaccounted", (Edit('src/foundry/experiments/locus_formation/source_coverage.py', '        if not any(a.sentence == s for a in accounted)\n', '        if False\n'),)),
    Mutant("cf", "cf-coverage-accepts-unknown", (Edit('src/foundry/experiments/locus_formation/source_coverage.py', '        if account.sentence not in sentences:\n', '        if False:\n'),)),
    Mutant("cf", "cf-coverage-accepts-bare-omission", (Edit('src/foundry/experiments/locus_formation/source_coverage.py', '        if not account.propositions and not account.non_operative_reason:\n', '        if False:\n'),)),
    Mutant("cf", "cf-coverage-keeps-enumerators", (Edit('src/foundry/domain/source_text.py', '        line = _ENUMERATOR.sub("", line)\n', '        pass\n'),)),
    # --- locus validation v4: v3's laws, claim ranges, canonical facets, source coverage ---
    Mutant("lv4", "lv4-missing-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if target is None or bound.get(target, 0) != 1:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-wrong-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if address_id not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-over-split-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '    if len(creates) > item.creates:\n', '    if False:\n'),)),
    Mutant("lv4", "lv4-merged-creation-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if others:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-wrong-support-address-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if where not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-missing-support-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if missing:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-separate-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if a is None or b is None or a == b:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-address-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if got != count:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-rejected-admission-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if d.route == "REJECT":\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-fabricated-supersede-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if not expected_keys:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-supersede-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '    if expected_keys and len(supersedes) != len(expected_keys):\n', '    if False:\n'),)),
    Mutant("lv4", "lv4-conflict-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if named_pair not in wanted:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-missing-conflict-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '    if wanted - named:\n', '    if False:\n'),)),
    Mutant("lv4", "lv4-replay-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if lg.replay_matches is not True:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-calls-per-delta-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if dict(per_t) != expected_calls:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-reference-law-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '                    if problem:\n', '                    if False:\n'),)),
    Mutant("lv4", "lv4-supersede-target-unchecked", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        elif where not in {lg.addresses.get(k) for k in expected_keys}:\n', '        elif False:\n'),)),
    Mutant("lv4", "lv4-unexpected-claims-ignored", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '        if address_id in expected_new:\n', '        if True:\n'),)),
    Mutant("lv4", "lv4-split-tally-blind", (Edit("src/foundry/experiments/locus_validation_v4/evaluation.py", '            if tag in tally:\n', '            if False:\n'),)),
    Mutant("lv4", "lv4-packet-uses-final-state", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '    state = run.deltas[after - 1].state_after.semantic\n', '    state = run.deltas[-1].state_after.semantic\n'),)),
    Mutant("lv4", "lv4-packet-shows-later-documents", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '(REVISION[run.ledger] if after == 2 else ())', 'REVISION[run.ledger]'),)),
    Mutant("lv4", "lv4-packet-drops-relations", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '        relations.append(entry)\n', '        pass\n'),)),
    Mutant("lv4", "lv4-bundle-ignores-timepoint", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '        frozen = packet(lg, q.after) if lg is not None else None\n', '        frozen = packet(lg, 2) if lg is not None else None\n'),)),
    Mutant("lv4", "lv4-standing-ignores-no", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '    semantic_ok = not missing and not said_no\n', '    semantic_ok = not missing\n'),)),
    Mutant("lv4", "lv4-standing-ignores-missing", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '    semantic_ok = not missing and not said_no\n', '    semantic_ok = not said_no\n'),)),
    Mutant("lv4", "lv4-standing-ignores-structural", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '    validated = structural_ok and semantic_ok and critical and all(cases.values())\n', '    validated = semantic_ok and critical and all(cases.values())\n'),)),
    Mutant("lv4", "lv4-standing-ignores-critical", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '    critical = cases.get(CRITICAL_CASE, False)\n', '    critical = True\n'),)),
    Mutant("lv4", "lv4-case-ignores-semantic", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", '        and all(answers.get(q) == "YES" for q in c.semantic)\n', '\n'),)),
    Mutant("lv4", "lv4-lowercase-yes-accepted", (Edit("src/foundry/experiments/locus_validation_v4/adjudication.py", 'answers.get(q.id, "YES") != "YES"', 'answers.get(q.id, "YES").upper() != "YES"'),)),
    Mutant("lv4", "lv4-new-claim-range-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '        if not low <= got <= high:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-new-claim-range-floor-ignored", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '        if not low <= got <= high:\n', '        if not got <= high:\n'),)),
    Mutant("lv4", "lv4-address-range-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '            if address_id is None or not want[0] <= got <= want[1]:\n', '            if address_id is None:\n'),)),
    Mutant("lv4", "lv4-facet-projection-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '            if a.facet != canonical_facet(a.subject):\n', '            if False:\n'),)),
    Mutant("lv4", "lv4-banned-facet-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '            if a.facet in BANNED_FACETS:\n', '            if False:\n'),)),
    Mutant("lv4", "lv4-facet-collision-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '            if a.facet in seen:\n', '            if False:\n'),)),
    Mutant("lv4", "lv4-candidate-facet-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '        ) and p.candidate.facet != canonical_facet(p.candidate.subject):\n', '        ) and False:\n'),)),
    Mutant("lv4", "lv4-model-facet-unchecked", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '        if n:\n', '        if False:\n'),)),
    Mutant("lv4", "lv4-coverage-not-scored", (Edit('src/foundry/experiments/locus_validation_v4/evaluation.py', '        out.add("SOURCE-COVERAGE", "SOURCE_COVERAGE", finding)\n', '        pass\n'),)),
    Mutant("lv4", "lv4-coverage-ignores-unsourced", (Edit('src/foundry/experiments/locus_validation_v4/expectations.py', '            if document == key and pid not in carried:\n', '            if False:\n'),)),
    Mutant("lv4", "lv4-coverage-ignores-unknown", (Edit('src/foundry/experiments/locus_validation_v4/expectations.py', '            if placed.get(pid) != key:\n', '            if False:\n'),)),
    Mutant("lv4", "lv4-coverage-ignores-unmapped", (Edit('src/foundry/experiments/locus_validation_v4/expectations.py', '        if accounts is None:\n            findings.append(', '        if accounts is None:\n            continue\n            findings.append('),)),
    Mutant("lv4", "lv4-identity-ignores-contract", (Edit('src/foundry/experiments/locus_validation_v4/recording.py', '    "output_schema": OUTPUT_SCHEMA_FROZEN,\n    "output_schema_sha256": OUTPUT_SCHEMA_SHA256_FROZEN,\n}', '}'),)),
    Mutant("lv4", "lv4-admission-gate-reads-literal", (Edit('src/foundry/experiments/locus_validation_v4/seal.py', '            passed=protocol.CANONICAL_FACETS is True and admission_flag is True,\n', '            passed=protocol.CANONICAL_FACETS is True,\n'),)),
    Mutant("lv4", "lv4-coverage-gate-blind", (Edit('src/foundry/experiments/locus_validation_v4/seal.py', '            passed=not coverage_gaps,\n', '            passed=True,\n'),)),
    Mutant("cf", "cf-coverage-splits-abbreviations", (Edit('src/foundry/domain/source_text.py', '(?=[A-Z0-9', '(?=['),)),
    # --- proposition accounting: the law, the adapter boundary, the pipeline wiring -------
    Mutant("pa", "pa-unknown-sentence-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        if sid not in sentence_evidence:\n', '        if False:\n'),)),
    Mutant("pa", "pa-unaccounted-sentence-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        if not carried[sid] and not declared[sid]:\n', '        if False:\n'),)),
    Mutant("pa", "pa-double-accounted-sentence-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        elif (carried[sid] and declared[sid]) or declared[sid] > 1:\n', '        elif False:\n'),)),
    Mutant("pa", "pa-double-declared-sentence-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        elif (carried[sid] and declared[sid]) or declared[sid] > 1:\n', '        elif carried[sid] and declared[sid]:\n'),)),
    Mutant("pa", "pa-duplicate-proposition-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        if n > 1:\n', '        if False:\n'),)),
    Mutant("pa", "pa-unknown-proposition-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '            findings.append(f"UNKNOWN_PROPOSITION: {d.proposition_id}")\n', '            pass\n'),)),
    Mutant("pa", "pa-evidence-mismatch-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        if d.kind is not JudgmentKind.SUPERSEDE and not required <= set(d.evidence_ids):\n', '        if False:\n'),)),
    Mutant("pa", "pa-unaccounted-proposition-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        if not got:\n', '        if False:\n'),)),
    Mutant("pa", "pa-conflicting-disposition-ignored", (Edit('src/foundry/domain/proposition_accounting.py', '        elif not _is_valid(got, correction_law):\n', '        elif False:\n'),)),
    Mutant("pa", "pa-supersede-alone-is-a-disposition", (Edit('src/foundry/domain/proposition_accounting.py', '        (JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE),\n', '        (JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE),\n        (JudgmentKind.SUPERSEDE,),\n'),)),
    Mutant("pa", "pa-conflict-is-a-disposition", (Edit('src/foundry/domain/proposition_accounting.py', '        (JudgmentKind.SUPPORTS_CLAIM,),\n', '        (JudgmentKind.SUPPORTS_CLAIM,),\n        (JudgmentKind.CONFLICTS_WITH,),\n'),)),
    Mutant("pa", "pa-adapter-never-accounts", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '        if isinstance(payload, AccountedDraftPayload):\n', '        if False:\n'),)),
    Mutant("pa", "pa-adapter-renders-no-sentences", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '    if include_sentence_index:\n', '    if False:\n'),)),
    Mutant("pa", "pa-policy-hides-sentence-index", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '                        include_sentence_index=self.include_sentence_index,\n', '                        include_sentence_index=False,\n'),)),
    Mutant("pa", "pa-nothing-is-accountable", (Edit('src/foundry/application/assimilation_context.py', '            cited.update(proposal.candidate.evidence_ids)\n', '            pass\n'),)),
    Mutant("pa", "pa-stray-accountable-evidence-accepted", (Edit('src/foundry/ports/semantic_reasoner.py', '        if stray:\n', '        if False:\n'),)),
    Mutant("pa", "pa-sentence-ids-zero-based", (Edit('src/foundry/domain/source_text.py', '    return f"{evidence_id}#S{position}"\n', '    return f"{evidence_id}#S{position - 1}"\n'),)),
    # --- structural walls: IE3 PARALLEL_NODE and the production-only bounded re-proposal ---
    Mutant("rp", "rp-parallel-node-unchecked", (Edit('src/foundry/domain/intent_graph_validation.py', '    _check_parallel_nodes(graph)\n', '    pass\n'),)),
    Mutant("rp", "rp-parallel-node-ignores-kind", (Edit('src/foundry/domain/intent_graph_validation.py', '            if node.disposition is not GraphNodeDisposition.NEW or node.kind is not kind:\n', '            if node.disposition is not GraphNodeDisposition.NEW:\n'),)),
    Mutant("rp", "rp-parallel-node-ignores-claims", (Edit('src/foundry/domain/intent_graph_validation.py', '            if shared:\n', '            if True:\n'),)),
    Mutant("rp", "rp-parallel-node-ignores-disposition", (Edit('src/foundry/domain/intent_graph_validation.py', '            if node.disposition is not GraphNodeDisposition.NEW or node.kind is not kind:\n', '            if node.kind is not kind:\n'),)),
    Mutant("rp", "rp-any-code-reproposable", (Edit('src/foundry/domain/structural_refusal.py', '    return bool(codes) and all(code in _ALLOWLISTS[engine] for code in codes)\n', '    return bool(codes)\n'),)),
    Mutant("rp", "rp-no-finding-reproposable", (Edit('src/foundry/domain/structural_refusal.py', '    return bool(codes) and all(code in _ALLOWLISTS[engine] for code in codes)\n', '    return all(code in _ALLOWLISTS[engine] for code in codes)\n'),)),
    Mutant("rp", "rp-two-reproposals", (Edit('src/foundry/domain/structural_refusal.py', 'MAX_REPROPOSALS: Final = 1\n', 'MAX_REPROPOSALS: Final = 2\n'),)),
    Mutant("rp", "rp-certification-may-repropose", (Edit('src/foundry/domain/structural_refusal.py', 'REPROPOSE_MODES: Final[frozenset[ExecutionMode]] = frozenset({ExecutionMode.PRODUCTION})\n', 'REPROPOSE_MODES: Final[frozenset[ExecutionMode]] = frozenset(ExecutionMode)\n'),)),
    Mutant("rp", "rp-ie2-mode-ungated", (Edit('src/foundry/application/claim_reproposal.py', '        if mode not in REPROPOSE_MODES:\n            raise\n        assert mode is not None\n        first = _refusal(', '        if False:\n            raise\n        assert mode is not None\n        first = _refusal('),)),
    Mutant("rp", "rp-ie2-any-reasoner-reproposes", (Edit('src/foundry/application/claim_reproposal.py', '        if not first.reproposable or not getattr(type(reasoner), "accepts_reproposal", False):\n', '        if not first.reproposable:\n'),)),
    Mutant("rp", "rp-ie2-notice-dropped", (Edit('src/foundry/application/claim_reproposal.py', '    retry = request.model_copy(update={"reproposal": ReproposalNotice(findings=first.findings)})\n', '    retry = request\n'),)),
    Mutant("rp", "rp-ie2-second-refusal-unrecorded", (Edit('src/foundry/application/claim_reproposal.py', '        governor.record_structural_refusal(\n            _refusal(\n                again,', '        (lambda _: None)(\n            _refusal(\n                again,'),)),
    Mutant("rp", "rp-ie2-first-refusal-unrecorded", (Edit('src/foundry/application/claim_reproposal.py', '        recorded = governor.record_structural_refusal(first)\n', '        recorded = None\n'),)),
    Mutant("rp", "rp-ie3-mode-ungated", (Edit('src/foundry/application/intent_graph_synthesis.py', '        if mode not in REPROPOSE_MODES:\n            raise\n        assert mode is not None\n        first = _graph_refusal(', '        if False:\n            raise\n        assert mode is not None\n        first = _graph_refusal('),)),
    Mutant("rp", "rp-ie3-uncertified-reproposes", (Edit('src/foundry/application/intent_graph_synthesis.py', '            or retry_author.policy_version not in CERTIFIED_GRAPH_REPROPOSAL_POLICY_VERSIONS\n', '            or False\n'),)),
    Mutant("rp", "rp-ie3-off-allowlist-reproposes", (Edit('src/foundry/application/intent_graph_synthesis.py', '            not first.reproposable\n            or retry_author is None\n', '            retry_author is None\n'),)),
    Mutant("rp", "rp-ie3-reproposal-authored-as-v4", (Edit('src/foundry/application/intent_graph_synthesis.py', '        author = retry_author\n', '        author = author\n'),)),
    Mutant("rp", "rp-adapter-accepts-any-notice", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '        if request.reproposal is not None and not self.accepts_reproposal:\n', '        if False:\n'),)),
    Mutant("rp", "rp-adapter-renders-no-notice", (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '    if include_reproposal_notice and request.reproposal is not None:\n', '    if False:\n'),)),
    # --- locus validation v5: v4's laws, proposition accounting, EXPERIMENT single attempt ---
    Mutant("lv5", "lv5-missing-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if target is None or bound.get(target, 0) != 1:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-wrong-bind-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if address_id not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-over-split-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '    if len(creates) > item.creates:\n', '    if False:\n'),)),
    Mutant("lv5", "lv5-merged-creation-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if others:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-wrong-support-address-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if where not in expected_bind_ids:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-missing-support-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if missing:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-separate-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if a is None or b is None or a == b:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-address-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if got != count:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-rejected-admission-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if d.route == "REJECT":\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-fabricated-supersede-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if not expected_keys:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-supersede-count-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '    if expected_keys and len(supersedes) != len(expected_keys):\n', '    if False:\n'),)),
    Mutant("lv5", "lv5-conflict-pair-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if named_pair not in wanted:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-missing-conflict-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '    if wanted - named:\n', '    if False:\n'),)),
    Mutant("lv5", "lv5-replay-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if lg.replay_matches is not True:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-calls-per-delta-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '        elif dict(per_t) != expected_calls:\n', '        elif False:\n'),)),
    Mutant("lv5", "lv5-reference-law-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '                    if problem:\n', '                    if False:\n'),)),
    Mutant("lv5", "lv5-supersede-target-unchecked", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        elif where not in {lg.addresses.get(k) for k in expected_keys}:\n', '        elif False:\n'),)),
    Mutant("lv5", "lv5-unexpected-claims-ignored", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '        if address_id in expected_new:\n', '        if True:\n'),)),
    Mutant("lv5", "lv5-split-tally-blind", (Edit("src/foundry/experiments/locus_validation_v5/evaluation.py", '            if tag in tally:\n', '            if False:\n'),)),
    Mutant("lv5", "lv5-packet-uses-final-state", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '    state = run.deltas[after - 1].state_after.semantic\n', '    state = run.deltas[-1].state_after.semantic\n'),)),
    Mutant("lv5", "lv5-packet-shows-later-documents", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '(REVISION[run.ledger] if after == 2 else ())', 'REVISION[run.ledger]'),)),
    Mutant("lv5", "lv5-packet-drops-relations", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '        relations.append(entry)\n', '        pass\n'),)),
    Mutant("lv5", "lv5-bundle-ignores-timepoint", (Edit('src/foundry/experiments/locus_validation_v5/adjudication.py', '        frozen = packet(lg, q.after) if lg is not None and len(lg.deltas) >= q.after else None\n', '        frozen = packet(lg, 2) if lg is not None and len(lg.deltas) >= q.after else None\n'),)),
    Mutant("lv5", "lv5-standing-ignores-no", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '    semantic_ok = not missing and not said_no\n', '    semantic_ok = not missing\n'),)),
    Mutant("lv5", "lv5-standing-ignores-missing", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '    semantic_ok = not missing and not said_no\n', '    semantic_ok = not said_no\n'),)),
    Mutant("lv5", "lv5-standing-ignores-structural", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '    validated = structural_ok and semantic_ok and critical and all(cases.values())\n', '    validated = semantic_ok and critical and all(cases.values())\n'),)),
    Mutant("lv5", "lv5-standing-ignores-critical", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '    critical = cases.get(CRITICAL_CASE, False)\n', '    critical = True\n'),)),
    Mutant("lv5", "lv5-case-ignores-semantic", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", '        and all(answers.get(q) == "YES" for q in c.semantic)\n', '\n'),)),
    Mutant("lv5", "lv5-lowercase-yes-accepted", (Edit("src/foundry/experiments/locus_validation_v5/adjudication.py", 'answers.get(q.id, "YES") != "YES"', 'answers.get(q.id, "YES").upper() != "YES"'),)),
    Mutant("lv5", "lv5-new-claim-range-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '        if not low <= got <= high:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-new-claim-range-floor-ignored", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '        if not low <= got <= high:\n', '        if not got <= high:\n'),)),
    Mutant("lv5", "lv5-address-range-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '            if address_id is None or not want[0] <= got <= want[1]:\n', '            if address_id is None:\n'),)),
    Mutant("lv5", "lv5-facet-projection-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '            if a.facet != canonical_facet(a.subject):\n', '            if False:\n'),)),
    Mutant("lv5", "lv5-banned-facet-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '            if a.facet in BANNED_FACETS:\n', '            if False:\n'),)),
    Mutant("lv5", "lv5-facet-collision-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '            if a.facet in seen:\n', '            if False:\n'),)),
    Mutant("lv5", "lv5-candidate-facet-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '        ) and p.candidate.facet != canonical_facet(p.candidate.subject):\n', '        ) and False:\n'),)),
    Mutant("lv5", "lv5-model-facet-unchecked", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '        if n:\n', '        if False:\n'),)),
    Mutant("lv5", "lv5-coverage-not-scored", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '        out.add("SOURCE-COVERAGE", "SOURCE_COVERAGE", finding)\n', '        pass\n'),)),
    Mutant("lv5", "lv5-coverage-ignores-unsourced", (Edit('src/foundry/experiments/locus_validation_v5/expectations.py', '            if document == key and pid not in carried:\n', '            if False:\n'),)),
    Mutant("lv5", "lv5-coverage-ignores-unknown", (Edit('src/foundry/experiments/locus_validation_v5/expectations.py', '            if placed.get(pid) != key:\n', '            if False:\n'),)),
    Mutant("lv5", "lv5-coverage-ignores-unmapped", (Edit('src/foundry/experiments/locus_validation_v5/expectations.py', '        if accounts is None:\n            findings.append(', '        if accounts is None:\n            continue\n            findings.append('),)),
    Mutant("lv5", "lv5-identity-ignores-contract", (Edit('src/foundry/experiments/locus_validation_v5/recording.py', '    "output_schema": OUTPUT_SCHEMA_FROZEN,\n    "output_schema_sha256": OUTPUT_SCHEMA_SHA256_FROZEN,\n}', '}'),)),
    Mutant("lv5", "lv5-admission-gate-reads-literal", (Edit('src/foundry/experiments/locus_validation_v5/seal.py', '            passed=protocol.CANONICAL_FACETS is True and admission_flag is True,\n', '            passed=protocol.CANONICAL_FACETS is True,\n'),)),
    Mutant("lv5", "lv5-coverage-gate-blind", (Edit('src/foundry/experiments/locus_validation_v5/seal.py', '            passed=not coverage_gaps,\n', '            passed=True,\n'),)),
    Mutant("lv5", "lv5-accounting-not-recomputed", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '            for finding in recompute_accounting(c):\n', '            for finding in ():\n'),)),
    Mutant("lv5", "lv5-refusal-not-scored", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '            if c.refusal_findings:\n                for finding in c.refusal_findings:\n', '            if False:\n                for finding in c.refusal_findings:\n'),)),
    Mutant("lv5", "lv5-refusal-tagged-as-abort", (Edit('src/foundry/experiments/locus_validation_v5/evaluation.py', '                if refused\n', '                if False\n'),)),
    Mutant("lv5", "lv5-refusal-aborts-the-walk", (Edit('src/foundry/experiments/locus_validation_v5/runner.py', '        status, error = "REFUSED", redact_secrets("; ".join(refused.findings))\n', '        status, error = "FAILED", redact_secrets("; ".join(refused.findings))\n'),)),
    Mutant("lv5", "lv5-refused-call-unrecorded", (Edit('src/foundry/experiments/locus_validation_v5/recording.py', '            refusal = refused\n', '            raise\n'),)),
    Mutant("lv5", "lv5-rendered-without-sentences", (Edit('src/foundry/experiments/locus_validation_v5/recording.py', '            include_sentence_index=getattr(inner_type, "include_sentence_index", False),\n', '            include_sentence_index=False,\n'),)),
    Mutant("lv5", "lv5-packet-without-accounting", (Edit('src/foundry/experiments/locus_validation_v5/adjudication.py', '        "model_accounting": _model_accounting(run, after),\n', '        "model_accounting": None,\n'),)),
    Mutant("lv5", "lv5-production-mode", (Edit('src/foundry/experiments/locus_validation_v5/protocol.py', 'EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT\n', 'EXECUTION_MODE: Final = ExecutionMode.PRODUCTION\n'),)),
    Mutant("lv5", "lv5-restatement-disposed-as-assert", (Edit('src/foundry/experiments/locus_validation_v5/expectations.py', '        "RESTATES": "SUPPORTS_CLAIM",\n', '        "RESTATES": "ASSERT_CLAIM",\n'),)),
    # --- governed-concern grain: grader, facet screen and the contract's deciding rules ------
    Mutant("lf", "lf-over-split-unchecked", (Edit("src/foundry/experiments/locus_formation/grain.py", "        if len(addresses) > 1:\n", "        if False:\n"),)),
    Mutant("lf", "lf-under-split-unchecked", (Edit("src/foundry/experiments/locus_formation/grain.py", "        if len(concerns) > 1:\n", "        if False:\n"),)),
    Mutant("lf", "lf-unplaced-unreported", (Edit("src/foundry/experiments/locus_formation/grain.py", '            findings.append(f"UNPLACED: {proposition.id}")\n', "            pass\n"),)),
    Mutant("lf", "lf-screen-misses-who", (Edit("src/foundry/experiments/locus_formation/grain.py", 'r"^\\s*(who|whom|whose|when|', 'r"^\\s*(whom|whose|when|'),)),
    Mutant("lf", "lf-screen-misses-how", (Edit("src/foundry/experiments/locus_formation/grain.py", 'where|whether|which|how(', 'where|whether|which|hows('),)),
    Mutant("lf", "lf-contract-drops-dimensions-rule", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", '            "dimensions of a concern are claims at its one address, never separate addresses:",\n', '            "dimensions of a concern are claims:",\n'),)),
    Mutant("lf", "lf-contract-drops-stage-rule", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", 'in its own right. A deadline for",\n', 'in its own right. A limit for",\n'),)),
    Mutant("lf", "lf-contract-drops-separate-rule", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", '            "independently governed act, entity or record, entitlement, decision, state",\n', '            "act, entity or record, entitlement, decision, state",\n'),)),
    Mutant("lf", "lf-contract-drops-topic-rule", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", '            "Sharing a topic word, a document or a subject area with a known address is never a",\n', '            "Sharing a subject area with a known address is never a",\n'),)),
    # --- IE2 + IE3 long-horizon harness (lh23) ---------------------------------------
    Mutant("lh23", "lh23-missing-supersede-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '        if not agreed:\n', '        if False:\n'),)),
    Mutant("lh23", "lh23-claim-range-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '        if not lo <= n <= hi:\n', '        if False:\n'),)),
    Mutant("lh23", "lh23-new-address-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '            out.add(name, "OVER_SPLIT", f"new address {new_id} at T{turn.t}")\n', '            pass\n'),)),
    Mutant("lh23", "lh23-wrong-bind-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '                if r.designated.get(locus) != held:\n', '                if False:\n'),)),
    Mutant("lh23", "lh23-accounting-not-recomputed", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '                for finding in recompute_accounting(c):\n', '                for finding in ():\n'),)),
    Mutant("lh23", "lh23-root-count-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '    if len(intents) != 1:\n', '    if False:\n'),)),
    Mutant("lh23", "lh23-root-judged-on-raw-plane", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '    view = derive_intent_view(after)\n', '    view = derive_view(after.semantic)\n'),)),
    Mutant("lh23", "lh23-stale-retention-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '        if oid in stale:\n', '        if False:\n'),)),
    Mutant("lh23", "lh23-coverage-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '        if not any(cid in _derived_from(o) for o in nodes.values()):\n', '        if False:\n'),)),
    Mutant("lh23", "lh23-duplicates-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '        if len(oids) > 1:\n', '        if False:\n'),)),
    Mutant("lh23", "lh23-false-new-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '            if not set(_derived_from(o)) & claims_new:\n', '            if False:\n'),)),
    Mutant("lh23", "lh23-gaps-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '    for gid in sorted(set(after.gaps) - set(before.gaps)):\n', '    for gid in ():\n'),)),
    Mutant("lh23", "lh23-ie3-refusal-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '    if ie3.status != "APPLIED":\n', '    if False:\n'),)),
    Mutant("lh23", "lh23-missing-turn-passes", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/evaluation.py", '        if t not in recorded:\n', '        if False:\n'),)),
    Mutant("lh23", "lh23-standing-ignores-ie3-answers", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/adjudication.py", '    ok = not failed and not unanswered and not ie2_no and not ie3_no\n', '    ok = not failed and not unanswered and not ie2_no\n'),)),
    Mutant("lh23", "lh23-corpus-items-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/corpus.py", '                if r.get(key) != value:\n', '                if False:\n'),)),
    Mutant("lh23", "lh23-certificate-standing-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/seal.py", '            and certificate_standing == "CURRENT",\n', '            and True,\n'),)),
    Mutant("lh23", "lh23-boundary-commit-unchecked", (Edit("src/foundry/experiments/long_horizon_ie2_ie3/seal.py", '            passed=git.boundary_commit_is_ancestor,\n', '            passed=True,\n'),)),
    # --- IE2 correction cardinality (intent-v2-locus-v6) ----------------------------------
    Mutant("cc", "cc-one-target-only-restored", (Edit("src/foundry/domain/proposition_accounting.py", '    return counts[JudgmentKind.ASSERT_CLAIM] == 1 and set(counts) <= {\n', '    return kinds in VALID_DISPOSITIONS and set(counts) <= {\n'),)),
    Mutant("cc", "cc-second-target-silently-dropped", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", '            self._wrap(request, draft, invocation_id, proposed_at) for draft in payload.drafts\n', '            self._wrap(request, draft, invocation_id, proposed_at) for i, draft in enumerate(payload.drafts) if not (isinstance(draft, AccountedSupersedeDraft) and any(isinstance(e, AccountedSupersedeDraft) and e.proposition_id == draft.proposition_id for e in payload.drafts[:i]))\n'),)),
    Mutant("cc", "cc-unknown-target-accepted", (Edit("src/foundry/domain/proposition_accounting.py", '        if e.target_address_id is None:\n', '        if e.target_address_id is None and False:\n'),)),
    Mutant("cc", "cc-cross-address-accepted", (Edit("src/foundry/domain/proposition_accounting.py", '        elif e.target_address_id not in e.proposition_address_ids:\n', '        elif e.target_address_id is None:\n'),)),
    Mutant("cc", "cc-omitted-proposition-accepted", (Edit("src/foundry/domain/proposition_accounting.py", '        if not got:\n', '        if False:\n'),)),
    Mutant("cc", "cc-retirement-without-assert-carrier", (Edit("src/foundry/domain/proposition_accounting.py", '    return counts[JudgmentKind.ASSERT_CLAIM] == 1 and set(counts) <= {\n', '    return counts[JudgmentKind.ASSERT_CLAIM] <= 1 and set(counts) <= {\n'),)),
    Mutant("cc", "cc-refused-correction-accepted", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", '    if correction_law == \"TARGET_SET\":\n        findings = (*findings, *_correction_edges_findings(request, payload))\n    if findings:\n', '    if correction_law == \"TARGET_SET\":\n        findings = (*findings, *_correction_edges_findings(request, payload))\n    if findings and not all(f.startswith((\"DUPLICATE_SUPERSEDE_TARGET\", \"CROSS_ADDRESS_SUPERSEDE\", \"UNKNOWN_SUPERSEDE_TARGET\")) for f in findings):\n'),)),
    Mutant("cc", "cc-many-to-many-collapsed-to-one-to-one", (Edit("src/foundry/domain/proposition_accounting.py", '            by_target[d.target_judgment_id].append(d.proposition_id)\n', '            by_target[d.proposition_id].append(d.target_judgment_id)\n'),)),
    Mutant("cc", "cc-historical-default-flipped", (Edit("src/foundry/adapters/semantics/xai_reasoner.py", '    correction_law: ClassVar[CorrectionLaw] = "ONE_TARGET"\n', '    correction_law: ClassVar[CorrectionLaw] = "TARGET_SET"\n'),)),
    # --- IE2 authority routing (ie2-authority-routing-v1) --------------------------------
    Mutant("ar", "ar-work-not-projected", (Edit("src/foundry/domain/authority_work.py", '    for judgment_id in view.pending_judgment_ids:\n', '    for judgment_id in ():\n'),)),
    Mutant("ar", "ar-duplicate-work-per-judgment", (Edit("src/foundry/domain/authority_work.py", '        grouped[work_id(state.project_id, judgment)].append(judgment)\n', '        grouped[work_id(state.project_id, judgment) + judgment.judgment_id].append(judgment)\n'),)),
    Mutant("ar", "ar-older-pending-work-lost", (Edit("src/foundry/domain/authority_work.py", '    for judgment_id in view.pending_judgment_ids:\n', '    for judgment_id in view.pending_judgment_ids[-1:]:\n'),)),
    Mutant("ar", "ar-orphan-work-from-satisfied", (Edit("src/foundry/domain/authority_work.py", '    for judgment_id in view.pending_judgment_ids:\n', '    for judgment_id in (*view.pending_judgment_ids, *view.satisfied_by):\n'),)),
    Mutant("ar", "ar-nm-edges-collapsed-by-invocation", (Edit("src/foundry/domain/authority_work.py", '        grouped[work_id(state.project_id, judgment)].append(judgment)\n', '        grouped[judgment.invocation_id].append(judgment)\n'),)),
    Mutant("ar", "ar-model-may-decide", (Edit("src/foundry/application/authority_routing.py", 'AGREE on ``work_id`` as of ``expected_sequence``."""\n    if not human_actor_id.startswith(_HUMAN_PREFIX):\n', 'AGREE on ``work_id`` as of ``expected_sequence``."""\n    if not human_actor_id:\n'),)),
    Mutant("ar", "ar-duplicate-resolution-accepted", (Edit("src/foundry/application/authority_routing.py", '    if item is None:\n', '    if False:\n'),)),
    Mutant("ar", "ar-stale-decision-accepted", (Edit("src/foundry/application/authority_routing.py", '    if state.last_sequence != expected_sequence:\n        raise StaleAuthorityDecision(\n            f"decided at sequence {expected_sequence}, the ledger is at {state.last_sequence}"\n        )\n    if work_id in state.semantic.correction_sets:\n', '    if False:\n        raise StaleAuthorityDecision(\n            f"decided at sequence {expected_sequence}, the ledger is at {state.last_sequence}"\n        )\n    if work_id in state.semantic.correction_sets:\n'),)),
    Mutant("ar", "ar-marked-resolved-prematurely", (Edit("src/foundry/application/authority_routing.py", '        resolved=all(i.work_id != work_id for i in after.items),\n', '        resolved=True,\n'),)),
    Mutant("ar", "ar-invisible-pending-undetected", (Edit("src/foundry/domain/authority_work.py", '        if seen[judgment_id] == 0:\n', '        if False:\n'),)),
    Mutant("ar", "ar-orphan-undetected", (Edit("src/foundry/domain/authority_work.py", '            if judgment_id not in pending:\n                findings.append(f"ORPHAN_WORK: {item.work_id} names', '            if False:\n                findings.append(f"ORPHAN_WORK: {item.work_id} names'),)),
    Mutant("ar", "ar-unapproved-correction-shown-to-ie3", (Edit("src/foundry/application/intent_synthesis_context.py", '        found[GapKind.MISSING_AUTHORITY] = ()\n', '        pass\n'),)),
    Mutant("scv", 'scv-verifier-bypassed', (Edit('src/foundry/application/claim_reproposal.py', '        if verifier is None:\n            return governor.propose_and_submit(reasoner, attempt)\n', '        if True:\n            return governor.propose_and_submit(reasoner, attempt)\n'),)),
    Mutant("scv", 'scv-verifier-always-pass', (Edit('src/foundry/domain/semantic_completeness.py', '    if not independent(verifier.as_fingerprint(), writer):\n        return "FAIL", ("VERIFIER_NOT_INDEPENDENT",)\n', '    return "PASS", ()\n    if not independent(verifier.as_fingerprint(), writer):\n        return "FAIL", ("VERIFIER_NOT_INDEPENDENT",)\n'),)),
    Mutant("scv", 'scv-missing-consequence-complete', (Edit('src/foundry/domain/semantic_completeness.py', '    if any(v.verdict != "COMPLETE" for v in report.verdicts):\n', '    if any(v.verdict not in ("COMPLETE", "INCOMPLETE") for v in report.verdicts):\n'),)),
    Mutant("scv", 'scv-decomposition-incomplete', (Edit('src/foundry/domain/semantic_completeness.py', '        if set(v.claim_refs) != refs:\n', '        if set(v.claim_refs) != refs or len(refs) > 1:\n'),)),
    Mutant("scv", 'scv-overreach-ignored', (Edit('src/foundry/domain/semantic_completeness.py', '    if any(v.verdict != "COMPLETE" for v in report.verdicts):\n', '    if any(v.verdict not in ("COMPLETE", "OVERREACH") for v in report.verdicts):\n'),)),
    Mutant("scv", 'scv-fail-still-applies', (Edit('src/foundry/application/semantic_completeness.py', '    if outcome == "FAIL":\n        raise SemanticCompletenessRefused(record, failures)\n', '    if False:\n        raise SemanticCompletenessRefused(record, failures)\n'),)),
    Mutant("scv", 'scv-fail-still-creates-correction-work', (Edit('src/foundry/application/semantic_completeness.py', '    if outcome == "FAIL":\n        raise SemanticCompletenessRefused(record, failures)\n', '    if outcome == "FAIL":\n        governor.submit_proposed(writer, proposal.judgments)\n        raise SemanticCompletenessRefused(record, failures)\n'),)),
    Mutant("scv", 'scv-wrong-proposition-claim-mapping', (Edit('src/foundry/application/semantic_completeness.py', '            if proposal.disposed_by.get(j.judgment_id) == prop.proposition_id\n', '            if True\n'),)),
    Mutant("scv", 'scv-verifier-identity-unbound', (Edit('src/foundry/domain/semantic_completeness.py', '    if not independent(verifier.as_fingerprint(), writer):\n', '    if False:\n'),)),
    Mutant("scv", 'scv-replay-recomputes', (Edit('src/foundry/application/semantic_completeness.py', '            return record.outcome\n', '            return "PASS" if record.report is not None and all(v.verdict == "COMPLETE" for v in record.report.verdicts) else "FAIL"\n'),)),
    Mutant("scv", 'scv-production-unverified', (Edit('src/foundry/application/incremental_assimilation.py', '    if mode is ExecutionMode.PRODUCTION and verifier is None:\n', '    if False:\n'),)),
    Mutant("scv", 'scv-semantic-failure-reproposed', (Edit('src/foundry/application/claim_reproposal.py', '        decisions, calls = verified_propose_and_submit(governor, reasoner, verifier, attempt)\n', '        try:\n            decisions, calls = verified_propose_and_submit(governor, reasoner, verifier, attempt)\n        except RuntimeError:\n            decisions, calls = verified_propose_and_submit(governor, reasoner, verifier, attempt)\n'),)),
    Mutant("scv2", 'scv2-scorer-ignores-findings', (Edit('tests/certification/_completeness_exam.py', '        if not identifies(_region(verdict), expected.groups, statements[expected.proposition_id]):\n', '        if False:\n'), Edit('tests/certification/_completeness_exam.py', '        for phrase in expected.forbidden:\n', '        for phrase in ():\n'),)),
    Mutant("scv2", 'scv2-verdict-only', (Edit('tests/certification/_completeness_exam.py', '        if expected.verdict == "COMPLETE":\n            continue\n', '        if True:\n            continue\n'),)),
    Mutant("scv2", 'scv2-one-mandatory-group-ignored', (Edit('tests/certification/_completeness_exam.py', '        all(_satisfies(item, g) for g in groups)\n', '        all(_satisfies(item, g) for g in groups[:1])\n'),)),
    Mutant("scv2", 'scv2-naive-substring', (Edit('tests/certification/_completeness_exam.py', '    return f" {normalise(phrase)} " in f" {normalise(text)} "\n', '    return normalise(phrase) in normalise(text)\n'),)),
    Mutant("scv2", 'scv2-regression-refusal-group-ignored', (Edit('tests/certification/_completeness_exam.py', '(LATENESS_48, REFUSAL), DEADLINE_MISREAD', '(LATENESS_48,), DEADLINE_MISREAD'),)),
    Mutant("scv2", 'scv2-regression-lateness-group-ignored', (Edit('tests/certification/_completeness_exam.py', '(LATENESS_48, REFUSAL), DEADLINE_MISREAD', '(REFUSAL,), DEADLINE_MISREAD'),)),
    Mutant("scv2", 'scv2-overreach-detail-ignored', (Edit('tests/certification/_completeness_exam.py', '        if expected.verdict == "COMPLETE":\n            continue\n', '        if expected.verdict in ("COMPLETE", "OVERREACH"):\n            continue\n'),)),
    Mutant("scv2", 'scv2-contradictory-detail-ignored', (Edit('tests/certification/_completeness_exam.py', '        if expected.verdict == "COMPLETE":\n            continue\n', '        if expected.verdict in ("COMPLETE", "CONTRADICTORY"):\n            continue\n'),)),
    Mutant("scv2", 'scv2-verdict-leaked-into-request', (Edit('tests/certification/_completeness_exam.py', '            subject_invocation_id=f"INV-{number:04d}",\n', '            subject_invocation_id=f"INV-{number:04d}-{items[0][1].verdict}",\n'),)),
    Mutant("scv2", 'scv2-case-label-leaked-into-request', (Edit('tests/certification/_completeness_exam.py', '            project_id=PROJECT,\n', '            project_id=category,\n'),)),
    Mutant("scv2", 'scv2-repetition-three-to-one', (Edit('tests/certification/_completeness_exam.py', 'COMPLETENESS_RUNS_PER_CASE: Final = 3\n', 'COMPLETENESS_RUNS_PER_CASE: Final = 1\n'),)),
    Mutant("scv2", 'scv2-certificate-omits-exam-identity', (Edit('tests/certification/_completeness_exam.py', '        "record_format": COMPLETENESS_CERTIFICATION_RECORD_FORMAT,\n        "exam_id": COMPLETENESS_EXAM_ID,\n        "exam_version": COMPLETENESS_EXAM_VERSION,\n        "exam_sha256": completeness_exam_sha256(),\n        "candidate": contestant.label,\n', '        "record_format": COMPLETENESS_CERTIFICATION_RECORD_FORMAT,\n        "candidate": contestant.label,\n'),)),
    Mutant("scv2", 'scv2-certificate-omits-verifier-policy-identity', (Edit('tests/certification/_completeness_exam.py', '        "tier": ModelTier.REASONER.value,\n        "verifier_policy_id": COMPLETENESS_POLICY_ID,\n        "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,\n', '        "tier": ModelTier.REASONER.value,\n'),)),
    Mutant("scv2", 'scv2-forbidden-interpretation-ignored', (Edit('tests/certification/_completeness_exam.py', '        for phrase in expected.forbidden:\n', '        for phrase in ():\n'),)),
    Mutant("scv2", 'scv2-keyword-stuffing-accepted', (Edit('tests/certification/_completeness_exam.py', '        and not _is_stuffed(item, groups)\n', ''),)),
    Mutant("scv2", 'scv2-proposition-echo-accepted', (Edit('tests/certification/_completeness_exam.py', '        and not _restates(item, statement)\n', ''),)),
    Mutant("scv2", 'scv2-any-region-field-accepted', (Edit('tests/certification/_completeness_exam.py', '        if not identifies(_region(verdict), expected.groups, statements[expected.proposition_id]):\n', '        if not identifies((*verdict.missing, *verdict.unsupported, *verdict.contradictory), expected.groups, statements[expected.proposition_id]):\n'),)),
    Mutant("scv2", 'scv2-majority-vote', (Edit('tests/certification/_completeness_exam.py', '    return "PASS" if all(a["verdict"] == "PASS" for a in attempts) else "NOT CERTIFIED"\n', '    return "PASS" if sum(a["verdict"] == "PASS" for a in attempts) * 2 > len(attempts) else "NOT CERTIFIED"\n'),)),
    Mutant("scv2", 'scv2-binding-not-fail-closed', (Edit('tests/certification/_completeness_exam.py', '    return all(key in record and record[key] == expected[key] for key in BINDING_FIELDS)\n', '    return all(record.get(key) == expected[key] for key in BINDING_FIELDS)\n'),)),
    Mutant("scv2", 'scv2-integrity-trusts-recorded-report', (Edit('tests/certification/_completeness_exam.py', '        if score_completeness_report(case, report):\n', '        if False:\n'),)),
    Mutant("scv2", 'scv2-global-gates-skipped', (Edit('tests/certification/_completeness_exam.py', '        *score_completeness_global_gates(observation, case, candidate=candidate),\n', ''),)),
    Mutant("lv6", 'lv6-section-count-grain', (Edit('src/foundry/experiments/locus_validation_v6/expectations.py', '    _dense_concern(_RES, "BOOKING-T1", "HOLD-T1", "PROLONG-T1"),\n', '    _dense_concern(_RES, "BOOKING-T1"),\n    _dense_concern("HOLD", "HOLD-T1"),\n    _dense_concern("PROLONG", "PROLONG-T1"),\n'),)),
    Mutant("lv6", 'lv6-distinct-dense-concerns-merged', (Edit('src/foundry/experiments/locus_validation_v6/expectations.py', '    _dense_concern(_LATE, "LATE-T1", "LATE-WAIVER-T1"),\n    _dense_concern(_CLEAN, "CLEANING-T1"),\n', '    _dense_concern(_LATE, "LATE-T1", "LATE-WAIVER-T1", "CLEANING-T1"),\n'),)),
    Mutant("lv6", 'lv6-same-concern-timing-split', (Edit('src/foundry/experiments/locus_validation_v6/expectations.py', '    _dense_concern(_UNL, "UNLOCK-T1", "UNLOCK-WAIT-T1", "UNLOCK-TIMEOUT-T1"),\n', '    _dense_concern(_UNL, "UNLOCK-T1", "UNLOCK-WAIT-T1"),\n    _dense_concern("UNLOCK-TIMEOUT", "UNLOCK-TIMEOUT-T1"),\n'),)),
    Mutant("lv6", 'lv6-proposition-dropped', (Edit('src/foundry/experiments/locus_validation_v6/expectations.py', '_ids("RES-5"), _ids("RES-6"), _E, _E, _E),\n', '_ids("RES-5"), _E, _E, _E, _E),\n'),)),
    Mutant("lv6", 'lv6-one-target-only-policy', (Edit('src/foundry/adapters/semantics/xai_reasoner.py', '    correction_law: ClassVar[CorrectionLaw] = "TARGET_SET"\n', '    correction_law: ClassVar[CorrectionLaw] = "ONE_TARGET"\n'),)),
    Mutant("lv6", 'lv6-one-target-only-recompute', (Edit('src/foundry/experiments/locus_validation_v6/evaluation.py', '        correction_law=CORRECTION_LAW_FROZEN,\n', '        correction_law="ONE_TARGET",\n'),)),
    Mutant("lv6", 'lv6-correcting-assert-leaks', (Edit('src/foundry/domain/correction_set.py', '        if isinstance(j.proposal, AssertClaimProposal) and j.proposal.address_id in corrected:\n', '        if isinstance(j.proposal, AssertClaimProposal) and j.proposal.address_id in corrected and False:\n'),)),
    Mutant("lv6", 'lv6-partial-correction-set', (Edit('src/foundry/application/semantic_reducer.py', '    for member in record.member_judgment_ids:\n        applied, member_touched = _transition(', '    for member in record.supersede_judgment_ids:\n        applied, member_touched = _transition('),)),
    Mutant("lv6", 'lv6-decline-applies', (Edit('src/foundry/application/semantic_reducer.py', '    if payload.outcome == "DECLINE":\n        return transitioned\n', '    if False:\n        return transitioned\n'),)),
    Mutant("lv6", 'lv6-declined-correction-reopens', (Edit('src/foundry/domain/correction_set.py', '        if existing.status == "DECLINED":\n', '        if False:\n'),)),
    Mutant("lv6", 'lv6-canonical-facet-bypassed', (Edit('src/foundry/experiments/locus_validation_v6/world.py', '    return AdmissionPolicy(canonical_facets=CANONICAL_FACETS, correction_sets=CORRECTION_SETS)\n', '    return AdmissionPolicy(canonical_facets=False, correction_sets=CORRECTION_SETS)\n'),)),
    Mutant("lv6", 'lv6-checkpoint-only-authority', (Edit('src/foundry/experiments/locus_validation_v6/authority.py', '    for item in listed.correction_sets:\n', '    for item in (listed.correction_sets if False else ()):\n'),)),
    Mutant("lv6", 'lv6-separation-unchecked', (Edit('src/foundry/experiments/locus_validation_v6/evaluation.py', '        if a is None or b is None or a == b:\n', '        if False:\n'),)),
    Mutant("lv6", 'lv6-over-split-unchecked', (Edit('src/foundry/experiments/locus_validation_v6/evaluation.py', '            if len(creates) > 1:\n                out.add(case, "OVER_SPLIT"', '            if False:\n                out.add(case, "OVER_SPLIT"'),)),
    Mutant("lv6", 'lv6-repeat-unchecked', (Edit('src/foundry/experiments/locus_validation_v6/evaluation.py', '        if new:\n            out.add(case, "REOPENED"', '        if False:\n            out.add(case, "REOPENED"'),)),
    Mutant("lv6", 'lv6-correction-sets-disabled', (Edit('src/foundry/experiments/locus_validation_v6/world.py', '    return AdmissionPolicy(canonical_facets=CANONICAL_FACETS, correction_sets=CORRECTION_SETS)\n', '    return AdmissionPolicy(canonical_facets=CANONICAL_FACETS, correction_sets=False)\n'),)),
    Mutant("cs", 'cs-corrections-admitted-edge-by-edge', (Edit('src/foundry/application/semantic_governance.py', '        if not self._policy.correction_sets:\n', '        if True:\n'),)),
    Mutant("cs", 'cs-correcting-assert-not-held', (Edit('src/foundry/domain/correction_set.py', '        if isinstance(j.proposal, AssertClaimProposal) and j.proposal.address_id in corrected:\n', '        if isinstance(j.proposal, AssertClaimProposal) and j.proposal.address_id in corrected and False:\n'),)),
    Mutant("cs", 'cs-members-applied-on-admission', (Edit('src/foundry/domain/correction_set.py', '    return all_members(AdmissionRoute.REQUIRE_HUMAN, CORRECTION_SET_MEMBER, set_id), record\n', '    return all_members(AdmissionRoute.APPLY, CORRECTION_SET_MEMBER, set_id), record\n'),)),
    Mutant("cs", 'cs-invalid-member-ignored', (Edit('src/foundry/domain/correction_set.py', '    if refusals:\n', '    if False:\n'),)),
    Mutant("cs", 'cs-agree-applies-only-retirements', (Edit('src/foundry/application/semantic_reducer.py', '    for member in record.member_judgment_ids:\n        applied, member_touched = _transition(', '    for member in record.supersede_judgment_ids:\n        applied, member_touched = _transition('),)),
    Mutant("cs", 'cs-agree-applies-only-assertions', (Edit('src/foundry/application/semantic_reducer.py', '    for member in record.member_judgment_ids:\n        applied, member_touched = _transition(', '    for member in record.assertion_judgment_ids:\n        applied, member_touched = _transition('),)),
    Mutant("cs", 'cs-decline-applies', (Edit('src/foundry/application/semantic_reducer.py', '    if payload.outcome == "DECLINE":\n        return transitioned\n', '    if False:\n        return transitioned\n'),)),
    Mutant("cs", 'cs-second-terminal-decision-accepted', (Edit('src/foundry/application/semantic_reducer.py', '    if record.status != "PENDING":\n        raise ValueError(f"correction set {record.correction_set_id} is already {record.status}")\n', '    if False:\n        raise ValueError(f"correction set {record.correction_set_id} is already {record.status}")\n'),)),
    Mutant("cs", 'cs-agreed-version-not-derived-from-members', (Edit('src/foundry/application/semantic_reducer.py', '        for member in record.member_judgment_ids[:-1]\n', '        for member in ()\n'),)),
    Mutant("cs", 'cs-declined-set-still-blocks', (Edit('src/foundry/domain/semantic_view.py', '        if judgment_id in in_declined_set:\n            continue\n', '        if False:\n            continue\n'),)),
    Mutant("cs", 'cs-pending-set-not-pending', (Edit('src/foundry/domain/semantic_view.py', '        if judgment_id in in_pending_set:\n            pending.append(judgment_id)\n            continue\n', '        if judgment_id in in_pending_set:\n            continue\n'),)),
    Mutant("cs", 'cs-repeat-after-decline-reopens', (Edit('src/foundry/domain/correction_set.py', '        if existing.status == "DECLINED":\n', '        if False:\n'),)),
    Mutant("cs", 'cs-pending-repeat-is-second-obligation', (Edit('src/foundry/domain/correction_set.py', '        if existing.status == "PENDING":\n', '        if False:\n'),)),
    Mutant("cs", 'cs-equivalence-by-evidence-id', (Edit('src/foundry/domain/correction_set.py', '                sha256_of_content(semantic.evidence[e].content)\n', '                e\n'),)),
    Mutant("cs", 'cs-equivalence-ignores-targets', (Edit('src/foundry/domain/correction_set.py', '    return "CEQ-" + _digest(project_id, address_id, sorted(targets), sorted(hashes))\n', '    return "CEQ-" + _digest(project_id, address_id, sorted(hashes))\n'),)),
    Mutant("cs", 'cs-member-is-a-lens', (Edit('src/foundry/domain/admission.py', '    if any(judgment_id in r.member_judgment_ids for r in semantic.correction_sets.values()):\n        return False\n', '    if False:\n        return False\n'),)),
    Mutant("cs", 'cs-set-split-into-edge-items', (Edit('src/foundry/domain/authority_work.py', '        if judgment_id in in_set:\n            continue\n', '        if False:\n            continue\n'),)),
    Mutant("cs", 'cs-pending-set-not-listed', (Edit('src/foundry/domain/authority_work.py', '        correction_sets=tuple(\n            _correction_set_item(state, r) for r in records if r.status == "PENDING"\n        ),\n', '        correction_sets=(),\n'),)),
    Mutant("cs", 'cs-model-may-decide', (Edit('src/foundry/application/authority_routing.py', 'on correction set ``work_id``."""\n    if not human_actor_id.startswith(_HUMAN_PREFIX):\n', 'on correction set ``work_id``."""\n    if not human_actor_id:\n'),)),
    Mutant("cs", 'cs-stale-decision-accepted', (Edit('src/foundry/application/authority_routing.py', '    if state.last_sequence != expected_sequence:\n        raise StaleAuthorityDecision(\n            f"decided at sequence {expected_sequence}, the ledger is at {state.last_sequence}"\n        )\n    record = state.semantic.correction_sets.get(work_id)\n', '    if False:\n        raise StaleAuthorityDecision(\n            f"decided at sequence {expected_sequence}, the ledger is at {state.last_sequence}"\n        )\n    record = state.semantic.correction_sets.get(work_id)\n'),)),
    Mutant("cs", 'cs-ledger-accepts-borrowed-authority', (Edit('src/foundry/application/reducer.py', '        and record.authorized_by == payload.decided_by\n', '        and True\n'),)),
    Mutant("cs", 'cs-legacy-edge-declinable', (Edit('src/foundry/application/authority_routing.py', '        if any(i.work_id == work_id for i in queue.items):\n', '        if False:\n'),)),
    Mutant("cs", 'cs-agree-not-revalidated', (Edit('src/foundry/application/semantic_governance.py', '            if refusals:\n', '            if False:\n'),)),
    Mutant("scv3", 'scv3-actor-omitted-complete-allowed', (Edit('tests/certification/_completeness_exam_v3.py', '             (claim("JDG-1", RESERVATIONS, "maximum_active_reservations_per_member", "4"),)),\n        _inventory(\n            held("ACTOR", "a member", "per member", "JDG-1"),\n', '             (claim("JDG-1", RESERVATIONS, "maximum_active_reservations", "4"),)),\n        _inventory(\n'),)),
    Mutant("scv3", 'scv3-time-anchor-omitted-overreach-expected', (Edit('tests/certification/_completeness_exam_v3.py', '                    "refused if made more than 7 days after return, and the member is "\n', '                    "refused if made more than 7 days, and the member is "\n'), Edit('tests/certification/_completeness_exam_v3.py', '            held("TIME_ANCHOR", "after return", "after return", "JDG-1"),\n', ''),)),
    Mutant("scv3", 'scv3-precedence-reversed', (Edit('tests/certification/_completeness_exam_v3.py', '    if "MISSING" in statuses:\n        return "INCOMPLETE"\n    if "UNSUPPORTED" in statuses:\n        return "OVERREACH"\n', '    if "UNSUPPORTED" in statuses:\n        return "OVERREACH"\n    if "MISSING" in statuses:\n        return "INCOMPLETE"\n'),)),
    Mutant("scv3", 'scv3-inventory-ignored', (Edit('tests/certification/_completeness_exam_v3.py', '        if a.status == region\n', '        if False\n'),)),
    Mutant("scv3", 'scv3-complete-allowed-with-missing', (Edit('tests/certification/_completeness_exam_v3.py', '    if "MISSING" in statuses:\n        return "INCOMPLETE"\n', ''),)),
    Mutant("scv3", 'scv3-overreach-allowed-with-missing', (Edit('tests/certification/_completeness_exam_v3.py', '    if "MISSING" in statuses:\n', '    if "MISSING" in statuses and "UNSUPPORTED" not in statuses:\n'),)),
    Mutant("scv3", 'scv3-contradiction-ignored', (Edit('tests/certification/_completeness_exam_v3.py', '    if "CONTRADICTED" in statuses:\n', '    if False:\n'),)),
    Mutant("scv3", 'scv3-inventory-leaked-to-model', (Edit('tests/certification/_completeness_exam_v3.py', '            subject_invocation_id=f"INV-{number:04d}",\n', '            subject_invocation_id=f"INV-{number:04d}-{items[0][1].assertions[0].kind}",\n'),)),
    Mutant("scv3", 'scv3-v2-evidence-mutated', (Edit('tests/certification/evidence/openai/gpt-6-astra/semantic_completeness_verification_exam_v2/certification.json', '"passed_attempts": 66,', '"passed_attempts": 67,'),)),
    Mutant("scv3", 'scv3-k-credit-payload-changed', (Edit('tests/certification/_completeness_exam.py', '"claim_deadline_after_reservation_start", "48 hours"),', '"claim_deadline_after_reservation_start", "48 hours, a later claim is refused"),'),)),
    Mutant("scv3", 'scv3-k-credit-refusal-unsealed', (Edit('tests/certification/_completeness_exam_v3.py', '        lost("CONSEQUENCE", "a later claim is refused", *_v2_groups("C21")),\n', ''),)),
    Mutant("scv3", 'scv3-only-designed-gap-required', (Edit('tests/certification/_completeness_exam_v3.py', '        for finding in expected.findings:\n', '        for finding in expected.findings[-1:]:\n'),)),
    Mutant("scv3", 'scv3-unclassified-claim-allowed', (Edit('tests/certification/_completeness_exam_v3.py', '            problems.append(f"{where}: claim {ref} is unclassified")\n', '            pass\n'),)),
    Mutant("scv3", 'scv3-missing-stated-by-a-claim-allowed', (Edit('tests/certification/_completeness_exam_v3.py', '                    problems.append(f"{label}: {phrase!r} is stated by a claim")\n', '                    pass\n'),)),
    Mutant("scv3", 'scv3-represented-anchor-unchecked', (Edit('tests/certification/_completeness_exam_v3.py', '            if not mentions(_claim_text(review, a.by), phrase):\n', '            if False:\n'),)),
    Mutant("scv3", 'scv3-forbidden-interpretation-ignored', (Edit('tests/certification/_completeness_exam_v3.py', '        for phrase in expected.forbidden:\n', '        for phrase in ():\n'),)),
    Mutant("scv3", 'scv3-budget-not-case-count-times-three', (Edit('tests/certification/_completeness_exam_v3.py', 'COMPLETENESS_CALL_BUDGET: Final = 75\n', 'COMPLETENESS_CALL_BUDGET: Final = 25\n'),)),
    Mutant("scv3", 'scv3-global-gates-skipped', (Edit('tests/certification/_completeness_exam_v3.py', '        *score_completeness_global_gates(observation, executable(case), candidate=candidate),\n', ''),)),
    Mutant("scv3", 'scv3-integrity-trusts-recorded-report', (Edit('tests/certification/_completeness_exam_v3.py', '        if score_completeness_report(case, report):\n', '        if False:\n'),)),
    Mutant("scv4", 'scv4-actor-marker-ignored', (Edit('tests/certification/_completeness_exam_v4.py', '        for e in _actor_ends(tokens, i, role.actor):\n', '        for e in [i]:\n'), Edit('tests/certification/_completeness_exam_v4.py', '                    if _actor_ends(tokens, _skip(tokens, t, DETERMINERS), role.actor):\n', '                    if True:\n'),)),
    Mutant("scv4", 'scv4-action-marker-ignored', (Edit('tests/certification/_completeness_exam_v4.py', '                if any(_g(tokens, m, role.action) for m in _g(tokens, j, role.modal)):\n', '                if _g(tokens, j, role.modal):\n'),)),
    Mutant("scv4", 'scv4-role-relation-ignored', (Edit('tests/certification/_completeness_exam_v4.py', '                if any(_g(tokens, m, role.action) for m in _g(tokens, j, role.modal)):\n', '                if any(_g(tokens, m, role.action) for m in (j, *_g(tokens, j, role.modal))):\n'),)),
    Mutant("scv4", 'scv4-actor-and-action-co-occurrence-accepted', (Edit('tests/certification/_completeness_exam_v4.py', '        tokens = normalise(item).split()\n', '        tokens = normalise(item).split()\n        if any(_g(tokens, i, role.actor) for i in range(len(tokens))) and any(_g(tokens, i, role.action) or _g(tokens, i, role.action_noun) for i in range(len(tokens))):\n            return True\n'),)),
    Mutant("scv4", 'scv4-nominal-phrasing-rejected', (Edit('tests/certification/_completeness_exam_v4.py', '            or _role_then_actor(tokens, role)\n', '            or False\n'),)),
    Mutant("scv4", 'scv4-passive-phrasing-rejected', (Edit('tests/certification/_completeness_exam_v4.py', '                if copula and _licensed_to_act(tokens, _skip(tokens, j + 1, ("only",)), role):\n', '                if False:\n'),)),
    Mutant("scv4", 'scv4-exact-v3-c05-finding-rejected', (Edit('tests/certification/_completeness_exam_v4.py', '    ("granted to", "limited to", "restricted to", "reserved for"),\n', '    ("limited to", "restricted to", "reserved for"),\n'),)),
    Mutant("scv4", 'scv4-negated-permission-accepted', (Edit('tests/certification/_completeness_exam_v4.py', '    "not", "no", "never", "nor", "neither", "without", "cannot",\n', '    "nor", "neither",\n'),)),
    Mutant("scv4", 'scv4-clause-break-ignored', (Edit('tests/certification/_completeness_exam_v4.py', '    "if", "when", "unless", "because", "but", "while", "where", "whereas", "although",\n    "though", "provided", "except", "and", "or", "whether", "until",\n', ''),)),
    Mutant("scv4", 'scv4-complement-affirmed-accepted', (Edit('tests/certification/_completeness_exam_v4.py', '                if any(_g(tokens, d, role.action) for d in _ends(tokens, j, DENIED_MODALS)):\n', '                if any(_g(tokens, d, role.action) for d in _ends(tokens, j, (*DENIED_MODALS, "may", "can"))):\n'),)),
    Mutant("scv4", 'scv4-bystander-guard-removed', (Edit('tests/certification/_completeness_exam_v4.py', 'BYSTANDER_QUALIFIERS: Final = ("other", "another", "else", "next", "non")\n', 'BYSTANDER_QUALIFIERS: Final = ()\n'),)),
    Mutant("scv4", 'scv4-markers-across-separate-items', (Edit('tests/certification/_completeness_exam_v4.py', '        tokens = normalise(item).split()\n', '        tokens = normalise(" ".join(items)).split()\n'),)),
    Mutant("scv4", 'scv4-c16-not-structural', (Edit('tests/certification/_completeness_exam_v4.py', '    if role is not None:\n', '    if role is not None and role is not RESERVER_ROLE:\n'),)),
    Mutant("scv4", 'scv4-only-one-gap-required', (Edit('tests/certification/_completeness_exam_v4.py', '        for finding in expected.findings:\n', '        for finding in expected.findings[-1:]:\n'),)),
    Mutant("scv4", 'scv4-v3-evidence-mutated', (Edit('tests/certification/evidence/openai/gpt-6-astra/semantic_completeness_verification_exam_v3/certification.json', '"passed_attempts": 74,', '"passed_attempts": 75,'),)),
    Mutant("scv4", 'scv4-history-replaces-v3', (Edit('tests/certification/_completeness_exam_v4.py', '    *V3_PRIOR_EXAMS,\n', ''),)),
    Mutant("scv4", 'scv4-global-gates-skipped', (Edit('tests/certification/_completeness_exam_v4.py', '        *score_completeness_global_gates(observation, executable(case), candidate=candidate),\n', ''),)),
    Mutant("scv4", 'scv4-integrity-trusts-recorded-report', (Edit('tests/certification/_completeness_exam_v4.py', '        if score_completeness_report(case, report):\n', '        if False:\n'),)),
    Mutant("scv5", 'scv5-appositive-actor-rejected', (Edit('tests/certification/_completeness_exam_v5.py', '        return [k, d + 1]\n', '        return [k]\n'),)),
    Mutant("scv5", 'scv5-actor-binding-loosened-to-co-occurrence', (Edit('tests/certification/_completeness_exam_v5.py', '        tokens = segment.split()\n', '        tokens = segment.split()\n        if any(_g(tokens, i, role.actor) for i in range(len(tokens))) and any(_g(tokens, i, role.action) or _g(tokens, i, role.action_noun) for i in range(len(tokens))):\n            return True\n'),)),
    Mutant("scv5", 'scv5-bystander-guard-removed', (Edit('tests/certification/_completeness_exam_v4.py', 'BYSTANDER_QUALIFIERS: Final = ("other", "another", "else", "next", "non")\n', 'BYSTANDER_QUALIFIERS: Final = ()\n'),)),
    Mutant("scv5", 'scv5-polarity-ignored', (Edit('tests/certification/_completeness_exam_v4.py', '    "not", "no", "never", "nor", "neither", "without", "cannot",\n', '    "nor", "neither",\n'),)),
    Mutant("scv5", 'scv5-clause-break-ignored', (Edit('tests/certification/_completeness_exam_v4.py', '    "if", "when", "unless", "because", "but", "while", "where", "whereas", "although",\n', '    "because", "while", "where", "whereas", "although",\n'),)),
    Mutant("scv5", 'scv5-pure-echo-accepted', (Edit('tests/certification/_completeness_exam_v5.py', '            segments.append([])\n', '            segments.append(tokens[i : i + len(echo)])\n            segments.append([])\n'), Edit('tests/certification/_completeness_exam_v5.py', '    return identifies(_segments(items, statement), groups, statement)\n', '    return identifies(_segments(items, statement), groups, "\\x00")\n'),)),
    Mutant("scv5", 'scv5-all-echoed-findings-rejected', (Edit('tests/certification/_completeness_exam_v5.py', '            segments.append([])\n', '            return ()\n'),)),
    Mutant("scv5", 'scv5-contradiction-remainder-ignored', (Edit('tests/certification/_completeness_exam_v5.py', '    groups = (*finding.groups, side) if side is not None else finding.groups\n', '    groups = finding.groups\n'),)),
    Mutant("scv5", 'scv5-echo-removal-deletes-too-much', (Edit('tests/certification/_completeness_exam_v5.py', '            i += len(echo)\n', '            i = len(tokens)\n'),)),
    Mutant("scv5", 'scv5-echo-removal-joins-the-text', (Edit('tests/certification/_completeness_exam_v5.py', '            segments.append([])\n', '            pass\n'),)),
    Mutant("scv5", 'scv5-all-gaps-weakened', (Edit('tests/certification/_completeness_exam_v5.py', '        for finding in expected.findings:\n', '        for finding in expected.findings[-1:]:\n'),)),
    Mutant("scv5", 'scv5-replay-gate-skipped', (Edit('tests/certification/_completeness_exam_v5.py', '    problems = replay_problems(historical_replay())\n    if problems:\n', '    problems = replay_problems(historical_replay())\n    if False:\n'),)),
    Mutant("scv5", 'scv5-unexpected-historical-change-ignored', (Edit('tests/certification/_completeness_exam_v5.py', '        elif r.historical != r.v5:\n', '        elif False:\n'),)),
    Mutant("scv5", 'scv5-v4-history-mutated', (Edit('tests/certification/evidence/openai/gpt-6-astra/semantic_completeness_verification_exam_v4/certification.json', '"passed_attempts": 72,', '"passed_attempts": 73,'),)),
    Mutant("scv5", 'scv5-history-replaces-v4', (Edit('tests/certification/_completeness_exam_v5.py', '    *V4_PRIOR_EXAMS,\n', ''),)),
    Mutant("scv5", 'scv5-requests-differ-from-v4', (Edit('tests/certification/_completeness_exam_v5.py', '            subject_invocation_id=f"INV-{number:04d}",\n', '            subject_invocation_id=f"INV-{number:04d}-5",\n'),)),
    Mutant("scv5", 'scv5-global-gates-skipped', (Edit('tests/certification/_completeness_exam_v5.py', '        *score_completeness_global_gates(observation, executable(case), candidate=candidate),\n', ''),)),
    Mutant("scv5", 'scv5-integrity-trusts-recorded-report', (Edit('tests/certification/_completeness_exam_v5.py', '        if score_completeness_report(case, report):\n', '        if False:\n'),)),
    Mutant("scs", 'scs-span-existence-not-checked', (Edit('src/foundry/domain/semantic_completeness.py', '        if f.proposition_evidence is not None and not any(', '        if False and not any('),)),
    Mutant("scs", 'scs-claim-ref-existence-not-checked', (Edit('src/foundry/domain/semantic_completeness.py', '        if f.claim_ref is not None and f.claim_ref not in claims:', '        if False:'), Edit('src/foundry/domain/semantic_completeness.py', '            and not grounded(f.claim_evidence, claims[f.claim_ref])', '            and not grounded(f.claim_evidence, claims.get(f.claim_ref, f.claim_evidence))'),)),
    Mutant("scs", 'scs-claim-evidence-not-checked', (Edit('src/foundry/domain/semantic_completeness.py', '            and not grounded(f.claim_evidence, claims[f.claim_ref])', '            and False'),)),
    Mutant("scs", 'scs-partial-word-grounding', (Edit('src/foundry/domain/semantic_completeness.py', '    return bool(q) and f" {q} " in f" {_folded(text)} "', '    return bool(q) and q in _folded(text)'),)),
    Mutant("scs", 'scs-duplicates-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '    if len(set(keys)) != len(keys):', '    if False:'),)),
    Mutant("scs", 'scs-wrong-finding-kind-accepted', (Edit('tests/certification/_structured_diagnostic.py', '    if (f.kind, f.direction) != (region.kind, region.direction):', '    if f.direction != region.direction:'),)),
    Mutant("scs", 'scs-wrong-direction-accepted', (Edit('tests/certification/_structured_diagnostic.py', '    if (f.kind, f.direction) != (region.kind, region.direction):', '    if f.kind != region.kind:'),)),
    Mutant("scs", 'scs-one-quote-for-two-regions', (Edit('tests/certification/_structured_diagnostic.py', '        if any(_covers(f.proposition_evidence, o.anchors) for o in others if o.anchors):', '        if False:'),)),
    Mutant("scs", 'scs-incomplete-without-evidence-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '        if self.verdict != follows:', '        if self.verdict != follows and self.findings:'),)),
    Mutant("scs", 'scs-contradiction-without-claim-evidence', (Edit('src/foundry/domain/semantic_completeness.py', '            "CONTRADICTORY": (True, True, True),', '            "CONTRADICTORY": (True, True, False),'),)),
    Mutant("scs", 'scs-overreach-without-claim-ref', (Edit('src/foundry/domain/semantic_completeness.py', '            "UNSUPPORTED": (False, True, True),', '            "UNSUPPORTED": (False, False, True),'),)),
    Mutant("scs", 'scs-report-format-mismatch-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '    if report is None or expected is None or not isinstance(report, expected):', '    if report is None:'),)),
    Mutant("scs", 'scs-verifier-failure-still-admitted', (Edit('src/foundry/application/semantic_completeness.py', '    if outcome == "FAIL":\n        raise SemanticCompletenessRefused(record, failures)\n', '    if False:\n        raise SemanticCompletenessRefused(record, failures)\n'),)),
    Mutant("scs", 'scs-correction-set-after-verifier-failure', (Edit('src/foundry/application/semantic_completeness.py', '    if outcome == "FAIL":\n        raise SemanticCompletenessRefused(record, failures)\n', '    if outcome == "FAIL":\n        governor.submit_proposed(writer, proposal.judgments)\n        raise SemanticCompletenessRefused(record, failures)\n'),)),
    Mutant("scs", 'scs-replay-recomputes', (Edit('src/foundry/application/semantic_completeness.py', '            return record.outcome\n', '            return "PASS" if record.report is not None and all(v.verdict == "COMPLETE" for v in record.report.verdicts) else "FAIL"\n'),)),
    Mutant("scs", 'scs-v1-history-not-replayable', (Edit('src/foundry/domain/semantic_completeness.py', '    report: (\n        CompletenessReport\n        | StructuredCompletenessReport\n        | VerdictCompletenessReport\n        | AdmissionReport\n        | AdmissionReportV5\n        | None\n    )\n    """``None`` when the verifier', '    report: (\n        StructuredCompletenessReport\n        | VerdictCompletenessReport\n        | AdmissionReport\n        | AdmissionReportV5\n        | None\n    )\n    """``None`` when the verifier'),)),
    Mutant("scx", 'scx-task-only-match-accepted', (Edit('src/foundry/model_runtime/registry.py', '            and (request.contract is None or certified_contract(descriptor, request) is not None)\n', ''),)),
    Mutant("scx", 'scx-policy-version-ignored', (Edit('src/foundry/model_runtime/registry.py', '            if c.task is request.task and c.contract == request.contract\n', "            if c.task is request.task and c.contract.model_copy(update={'policy_version': getattr(request.contract, 'policy_version', None)}) == request.contract\n"),)),
    Mutant("scx", 'scx-instruction-hash-ignored', (Edit('src/foundry/model_runtime/registry.py', '            if c.task is request.task and c.contract == request.contract\n', "            if c.task is request.task and c.contract.model_copy(update={'instruction_sha256': getattr(request.contract, 'instruction_sha256', None)}) == request.contract\n"),)),
    Mutant("scx", 'scx-canonical-schema-ignored', (Edit('src/foundry/model_runtime/registry.py', '            if c.task is request.task and c.contract == request.contract\n', "            if c.task is request.task and c.contract.model_copy(update={'output_schema_sha256': getattr(request.contract, 'output_schema_sha256', None)}) == request.contract\n"), Edit('src/foundry/model_runtime/runtime.py', '        if request.contract is not None and (\n            request.contract.output_schema_sha256 != output_schema_sha256(output_type)\n        ):', '        if False and (\n            request.contract.output_schema_sha256 != output_schema_sha256(output_type)\n        ):'),)),
    Mutant("scx", 'scx-wire-schema-ignored', (Edit('src/foundry/model_runtime/runtime.py', '        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != certified.wire_schema_sha256:', '        if False:'),)),
    Mutant("scx", 'scx-missing-contract-accepted', (Edit('src/foundry/model_runtime/domain.py', '        if self.task in CONTRACT_BOUND_TASKS and self.contract is None:', '        if False:'),)),
    Mutant("scx", 'scx-certificate-binding-not-fail-closed', (Edit('tests/certification/_structured_completeness_exam.py', '        key in record and key in expected and record[key] == expected[key]', '        record.get(key) == expected.get(key)'),)),
    Mutant("scx", 'scx-gates-ignore-the-contract', (Edit('tests/certification/_structured_completeness_exam.py', '    if sent.contract != COMPLETENESS_V2_CONTRACT:', '    if False:'),)),
    Mutant("scx", 'scx-explanation-affects-score', (Edit('tests/certification/_structured_completeness_exam.py', '    if finding.direction != region.direction or finding.kind not in region.kinds:', '    if finding.direction != region.direction or finding.kind not in region.kinds or "member" in finding.explanation:'),)),
    Mutant("scx", 'scx-quotes-not-grounded', (Edit('tests/certification/_structured_completeness_exam.py', '    problems = report_findings(case.request, report)', '    problems = ()'),)),
    Mutant("scx", 'scx-claim-quote-not-checked', (Edit('tests/certification/_structured_completeness_exam.py', '        if not _covers(finding.claim_evidence, (str(region.claim_anchor),)):', '        if False:'),)),
    Mutant("scx", 'scx-claim-ref-not-checked', (Edit('tests/certification/_structured_completeness_exam.py', '        if finding.claim_ref != region.claim_ref:\n            return False\n', ''),)),
    Mutant("scx", 'scx-wrong-kind-accepted', (Edit('tests/certification/_structured_completeness_exam.py', '    if finding.direction != region.direction or finding.kind not in region.kinds:', '    if finding.direction != region.direction:'),)),
    Mutant("scx", 'scx-wrong-direction-accepted', (Edit('tests/certification/_structured_completeness_exam.py', '    if finding.direction != region.direction or finding.kind not in region.kinds:', '    if finding.kind not in region.kinds:'),)),
    Mutant("scx", 'scx-one-finding-for-several-regions', (Edit('tests/certification/_structured_completeness_exam.py', '        if any(_covers(finding.proposition_evidence, o.anchors) for o in others):', '        if False:'),)),
    Mutant("scx", 'scx-k-credit-one-gap-accepted', (Edit('tests/certification/_structured_completeness_exam.py', '        for region in sealed.regions:\n', '        for region in sealed.regions[:1]:\n'),)),
    Mutant("scx", 'scx-unsealed-finding-accepted', (Edit('tests/certification/_structured_completeness_exam.py', '        for f in verdict.findings:\n', '        for f in ():\n'),)),
    Mutant("scx", 'scx-complete-with-findings-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '        if self.verdict != follows:', '        if self.verdict != follows and self.verdict != "COMPLETE":'),)),
    Mutant("scx", 'scx-non-complete-without-findings-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '        if self.verdict != follows:', '        if self.verdict != follows and self.findings:'),)),
    Mutant("rts", 'rts-not-complete-applies', (Edit('src/foundry/application/semantic_completeness.py', '        held += [(u, "NOT_COMPLETE", ()) for u in units if failing & set(u.proposition_ids)]', '        held += []'),)),
    Mutant("rts", 'rts-gap-not-created', (Edit('src/foundry/application/semantic_completeness.py', '    for gap in gaps:', '    for gap in ():'),)),
    Mutant("rts", 'rts-closure-ignores-open-gap', (Edit('src/foundry/domain/closure.py', 'if gap_applies(state, gap, scope) and gap.status is GapStatus.OPEN and gap.blocking is True:', 'if False:'),)),
    Mutant("rts", 'rts-correction-set-partially-applies', (Edit('src/foundry/domain/completeness_units.py', '    for _, correction in sets:', '    for _, correction in ():'),)),
    Mutant("rts", 'rts-authority-work-for-incomplete-correction', (Edit('src/foundry/application/semantic_completeness.py', '    held_judgments = {j for u, _, _ in held for j in u.judgment_ids}', '    held_judgments = {j for j, p in proposal.disposed_by.items() if any(p in u.proposition_ids[:1] for u, _, _ in held)}'),)),
    Mutant("rts", 'rts-malformed-answer-treated-as-complete', (Edit('src/foundry/application/semantic_completeness.py', '    elif outcome == "FAIL":', '    elif False:'),)),
    Mutant("rts", 'rts-replay-recomputes-the-outcome', (Edit('src/foundry/application/semantic_completeness.py', '            return record.outcome\n', '            return "PASS" if record.report is not None and all(v.verdict == "COMPLETE" for v in record.report.verdicts) else "FAIL"\n'),)),
    Mutant("rts", 'rts-note-wording-affects-result', (Edit('src/foundry/domain/semantic_completeness.py', '    return tuple(v.proposition_id for v in report.verdicts if v.verdict == "NOT_COMPLETE")', '    return tuple(v.proposition_id for v in report.verdicts if v.verdict == "NOT_COMPLETE" or "refusal" in (v.note or ""))'),)),
    Mutant("rts", 'rts-wrong-verifier-contract-accepted', (Edit('src/foundry/model_runtime/registry.py', '            and (request.contract is None or certified_contract(descriptor, request) is not None)\n', ''),)),
    Mutant("e2e", 'e2e-implicit-contradiction-accepted', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '        if frozenset((a, b)) not in explicit:', '        if False:'),)),
    Mutant("e2e", 'e2e-declined-set-applied-ignored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '        if s.status == "DECLINED" and landed:', '        if False:'),)),
    Mutant("e2e", 'e2e-supersede-without-agreement-ignored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '        if not human and judgment_id not in agreed:', '        if False:'),)),
    Mutant("e2e", 'e2e-refused-step-not-a-silent-gap', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '    for step_id in outcome.refused_steps:', '    for step_id in ():'),)),
    Mutant("e2e", 'e2e-ie3-uncovered-claim-ignored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '            if truth_id in current_truths and truth_id not in stated:', '            if False:'),)),
    Mutant("e2e", 'e2e-closure-not-scored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '        sorted(g.kind for g in open_holds) != sorted(expected.open_blocking_gap_kinds)\n        or unblocked\n        or outcome.closure_closed != expected.closure_closed\n', '        False\n'),)),
    Mutant("e2e", 'e2e-wrong-target-reported-as-missing', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '            if truth_id in retired_truths:', '            if False:'),)),
    Mutant("e2e", 'e2e-clean-without-ie3-passes', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '    elif expected.ie3_required and not outcome.ie3_evaluated:', '    elif False:'),)),
    Mutant("e2e", 'e2e-harness-retries-refused-step', (Edit('src/foundry/experiments/intent_engine_e2e/harness.py', '            continue\n', '            assimilate_delta(governor=governor, reasoner=reasoner, delta=(item,), scope=scenario.scope, mode=EXECUTION_MODE, verifier=verifier)\n            continue\n'),)),
    Mutant("e2e", 'e2e-harness-decides-without-a-single-pending-set', (Edit('src/foundry/experiments/intent_engine_e2e/harness.py', '    if len(pending) != 1:', '    if not pending:'),)),
    Mutant("rth", 'rth-conflicting-new-claim-applies', (Edit('src/foundry/application/semantic_completeness.py', '            if conflicted & set(u.proposition_ids):', '            if False:'),)),
    Mutant("rth", 'rth-sibling-contradictions-both-apply', (Edit('src/foundry/domain/completeness_units.py', '    for a, b in linked:  # two sibling propositions said to conflict: one conflict group', '    for a, b in ():  # two sibling propositions said to conflict: one conflict group'),)),
    Mutant("rth", 'rth-conflict-gap-omitted', (Edit('src/foundry/application/semantic_completeness.py', '    for gap in gaps:\n        governor.record_gap(gap)\n', '    for gap in gaps:\n        if gap.cause != "CONFLICT":\n            governor.record_gap(gap)\n'),)),
    Mutant("rth", 'rth-unrelated-safe-work-held', (Edit('src/foundry/application/semantic_completeness.py', '    held_judgments = {j for u, _, _ in held for j in u.judgment_ids}', '    held_judgments = {j.judgment_id for j in judgments} if held else set()'),)),
    Mutant("rth", 'rth-gap-resolved-by-unrelated-evidence', (Edit('src/foundry/domain/hold_resolution.py', 'and g.basis and set(g.basis) <= have', 'and bool(have)'),)),
    Mutant("rth", 'rth-corrected-redelivery-does-not-resolve', (Edit('src/foundry/application/semantic_holds.py', '        *closed_by_delivery(state, delivered, exclude),\n', ''),)),
    Mutant("rth", 'rth-unavailable-verifier-records-no-gap', (Edit('src/foundry/application/semantic_completeness.py', '        _hold_unverified(governor, proposal, check, str(unavailable))\n', ''),)),
    Mutant("rth", 'rth-unavailable-verifier-applies-work', (Edit('src/foundry/application/semantic_completeness.py', '        return (), 1\n', '        return governor.submit_proposed(writer, proposal.judgments), 1\n'),)),
    Mutant("rth", 'rth-local-gap-project-wide', (Edit('src/foundry/application/semantic_holds.py', '        affected_object_ids=(*addresses, *sorted(conflicting_claim_ids)),', '        affected_object_ids=(),'),)),
    Mutant("rth", 'rth-closure-ignores-hold-gaps', (Edit('src/foundry/domain/closure.py', 'if gap_applies(state, gap, scope) and gap.status is GapStatus.OPEN and gap.blocking is True:', 'if gap_applies(state, gap, scope) and gap.status is GapStatus.OPEN and gap.blocking is True and not hasattr(gap, "cause"):'),)),
    Mutant("rth", 'rth-resolution-not-durable', (Edit('src/foundry/application/semantic_governance.py', '        return self._append(EventType.GAP_RESOLVED, GapResolvedPayload(gap_id=gap_id), "gap")', '        return None  # type: ignore[return-value]'),)),
    Mutant("rth", 'rth-replay-ignores-recorded-resolution', (Edit('src/foundry/application/reducer.py', '                    "status": GapStatus.RESOLVED,', '                    "status": current_gap.status,'),)),
    Mutant("rth", 'rth-conflict-closed-while-claim-current', (Edit('src/foundry/domain/hold_resolution.py', '        and not set(g.conflicting_claim_ids) & current\n', ''),)),
    Mutant("rth", 'rth-agree-never-closes-conflict', (Edit('src/foundry/application/authority_routing.py', '        close_resolved_holds(governor, applied_addresses=(decided.address_id,))\n', '        pass\n'),)),
    Mutant("rta", 'rta-verifier-conflict-ignored', (Edit('src/foundry/application/semantic_completeness.py', '        conflicted = {c.proposition_id for c in proposal.conflicts} | set(verifier_conflicts)', '        conflicted = {c.proposition_id for c in proposal.conflicts}'),)),
    Mutant("rta", 'rta-uncertain-treated-as-safe', (Edit('src/foundry/application/semantic_completeness.py', '        held += [(u, "UNCERTAIN", ()) for u in units if uncertain & set(u.proposition_ids)]\n', ''),)),
    Mutant("rta", 'rta-conflicting-claim-id-not-validated', (Edit('src/foundry/domain/semantic_completeness.py', '                if cid not in shown', '                if False'),)),
    Mutant("rta", 'rta-duplicate-conflict-gap', (Edit('src/foundry/application/semantic_completeness.py', '                held.append((u, "CONFLICT", claims))', '                held.append((u, "CONFLICT", claims))\n                held.append((u, "CONFLICT", claims))'),)),
    Mutant("rta", 'rta-writer-miss-bypasses-verifier', (Edit('src/foundry/application/semantic_completeness.py', '        consistency=bool(getattr(verifier, "checks_consistency", False)),', '        consistency=False,'),)),
    Mutant("rta", 'rta-correction-set-partially-applies', (Edit('src/foundry/domain/completeness_units.py', '    for _, correction in sets:', '    for _, correction in ():'),)),
    Mutant("rta", 'rta-unavailable-treated-as-no-conflict', (Edit('src/foundry/application/semantic_completeness.py', '        return (), 1\n', '        return governor.submit_proposed(writer, proposal.judgments), 1\n'),)),
    Mutant("rta", 'rta-verifier-called-again', (Edit('src/foundry/application/semantic_completeness.py', '        answer = verifier.verify(check)\n', '        answer = verifier.verify(check)\n        answer = verifier.verify(check)\n'),)),
    Mutant("rta", 'rta-v4-report-accepted-on-plain-request', (Edit('src/foundry/domain/semantic_completeness.py', '    if type(request) is not _REQUEST_FOR.get(type(report), CompletenessRequest):', '    if not isinstance(request, CompletenessRequest):'),)),
    Mutant("rta", 'rta-uncertain-reported-as-incomplete', (Edit('src/foundry/application/semantic_completeness.py', '        held += [(u, "UNCERTAIN", ()) for u in units if uncertain & set(u.proposition_ids)]', '        held += [(u, "NOT_COMPLETE", ()) for u in units if uncertain & set(u.proposition_ids)]'),)),
    Mutant("e2e", 'e2e-incorrect-gap-resolution-ignored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '            if still:\n                add(DefectCategory.INCORRECT_GAP_RESOLUTION, g.gap_id, *still)', '            if False:\n                add(DefectCategory.INCORRECT_GAP_RESOLUTION, g.gap_id, *still)'),)),
    Mutant("e2e", 'e2e-expected-open-contradiction-not-required', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '        if any(g.status == "OPEN" for g in holds):\n            continue', '        if True:\n            continue'),)),
    Mutant("e2e", 'e2e-held-truth-current-ignored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '        elif final[r.truth_id] == "HELD":', '        elif False:'),)),
    Mutant("e2e", 'e2e-ie3-misstatement-ignored', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '            if not gr.truth_ids or wrong or not gr.faithful:', '            if not gr.truth_ids or wrong:'),)),
    Mutant("e2e", 'e2e-uncertain-reading-passes', (Edit('src/foundry/experiments/intent_engine_e2e/outcome.py', '    elif uncertain:\n        verdict = "NOT_VALIDATED"', '    elif False:\n        verdict = "NOT_VALIDATED"'),)),
    Mutant("rv5", 'rv5-routing-falls-back-to-any-pending-work', (Edit('src/foundry/experiments/intent_engine_live_v2/harness.py', '    if len(pending) == 1:', '    if not pending:\n        pending = [i for i, r in semantic.correction_sets.items() if r.status == "PENDING"][:1]\n    if len(pending) == 1:'),)),
    Mutant("rv5", 'rv5-decision-window-spans-other-steps', (Edit('src/foundry/experiments/intent_engine_live_v2/harness.py', '        window = tuple(store.load(governor.project_id, after_sequence=start))', '        window = tuple(store.load(governor.project_id, after_sequence=0))'),)),
    Mutant("rv5", 'rv5-ambiguous-work-guessed', (Edit('src/foundry/experiments/intent_engine_live_v2/harness.py', '    if len(pending) > 1:', '    if False:'),)),
    Mutant("rv5", 'rv5-foreign-provenance-accepted', (Edit('src/foundry/experiments/intent_engine_live_v2/harness.py', '        if sources != {(evidence_id(step),)}:', '        if False:'),)),
    Mutant("rv5", 'rv5-conflicting-evidence-treated-as-supported', (Edit('src/foundry/application/semantic_completeness.py', '            named |= {r.claim_id for r in replacements if r.judgement == "CONFLICTING_EVIDENCE"}', '            named |= set()'),)),
    Mutant("rv5", 'rv5-uncertain-replacement-treated-as-supported', (Edit('src/foundry/application/semantic_completeness.py', '                r.judgement == "UNCERTAIN" for r in replacements', '                False for r in replacements'),)),
    Mutant("rv5", 'rv5-replacement-targets-not-supplied', (Edit('src/foundry/application/semantic_completeness.py', '            replacement_targets=replacement_targets(state, proposal),', '            replacement_targets=(),'),)),
    Mutant("rv5", 'rv5-invalid-replacement-target-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '            if sorted(r.claim_id for r in v.replacements) != sorted(targets):', '            if False:'),)),
    Mutant("rv5", 'rv5-conflicting-correction-opens-authority-work', (Edit('src/foundry/application/semantic_completeness.py', '        conflicted = {c.proposition_id for c in proposal.conflicts} | set(verifier_conflicts)', '        conflicted = {c.proposition_id for c in proposal.conflicts}'),)),
    Mutant("rv5", 'rv5-duplicate-contradiction-gap', (Edit('src/foundry/application/semantic_completeness.py', '                held.append((u, "CONFLICT", claims))', '                held.append((u, "CONFLICT", claims))\n                held.append((u, "CONFLICT", claims))'),)),
    Mutant("rv5", 'rv5-replay-reruns-verifier', (Edit('src/foundry/application/semantic_completeness.py', '        answer = verifier.verify(check)\n', '        answer = verifier.verify(check)\n        answer = verifier.verify(check)\n'),)),
    Mutant("rv5", 'rv5-report-on-wrong-request-type-accepted', (Edit('src/foundry/domain/semantic_completeness.py', '    if type(request) is not _REQUEST_FOR.get(type(report), CompletenessRequest):', '    if not isinstance(request, CompletenessRequest):'),)),
)
