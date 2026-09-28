"""The compact Anthropic graph wire cannot weaken Foundry's graph contract.

``foundry.anthropic-graph-wire`` (v2) is a transport form only. These tests prove, offline:

* **Identity**: the prompt, canonical and exam-v4 hashes are unchanged, and tampering with any
  bound field breaks a certificate. (The wire hash and converter-source pins live in
  ``test_anthropic_graph_wire_identity.py``, outside the mutation slice, so a mutant here must
  be caught by behaviour rather than by a digest.)
* **Grammar size** is what the refused v1 was not: no ``$ref``, ``$defs`` or union anywhere.
* **The parser is exactly the wire schema**: over a corpus of lawful and adversarial wire
  instances, ``parse_graph_wire`` accepts precisely what JSON Schema validation accepts.
* **Round trip**: every lawful canonical value survives canonical -> wire -> canonical unchanged.
* **No weakening**: kind-illegal fields, facet/kind mismatches, bad relations, missing semantics,
  unknown fields and unknown enum values are all refused, at the wire or canonically.
* **Mechanical conversion**: it neither invents nor drops a value (multiset proofs).
* **Classification**: wire-valid but canonical-invalid is a protocol failure that never reaches
  the exam scorer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    GRAPH_SYSTEM_INSTRUCTION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.anthropic_graph_wire import (
    DEFERRED_TO_CANONICAL,
    GRAMMAR_ENFORCED,
    GraphWireShapeError,
    anthropic_graph_wire_schema,
    parse_graph_wire,
)
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from foundry.model_runtime.errors import ModelProtocolError
from tests.certification._certification_run import (
    Contestant,
    ProtocolTaskFailure,
    classify_execution_failure,
)
from tests.certification._schema_identity import schema_sha256
from tests.unit._graph_answer_schema import lawful_payloads
from tests.unit.adapters.model_runtime._anthropic_graph_forms import to_wire
from tests.unit.adapters.model_runtime._fake_anthropic import RecordingClientFactory, answer

WIRE: dict[str, Any] = anthropic_graph_wire_schema()
VALIDATOR = Draft202012Validator(WIRE)

OPUS = "claude-opus-5-5"
NEUTRAL_TEXT = ("replaces", "statement", "mission", "decision_rationale")
NEUTRAL_ENUM = ("facet", "proposed_risk_level")


def _node(**overrides: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "kind": "REQUIREMENT",
        "local_id": "req-1",
        "disposition": "NEW",
        "replaces": "",
        "statement": "s",
        "mission": "",
        "decision_rationale": "",
        "facet": None,
        "proposed_risk_level": None,
        "proposal_rationale": "why",
    }
    node.update(overrides)
    return node


def _payload(**parts: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "nodes": [],
        "relations": [],
        "gaps": [],
        "unchanged_object_refs": [],
    }
    payload.update(parts)
    return payload


def _wire_valid(instance: Any) -> bool:
    return VALIDATOR.is_valid(instance)


def _parses(instance: Any) -> bool:
    try:
        parse_graph_wire(json.dumps(instance))
    except GraphWireShapeError:
        return False
    return True


def _canonical(instance: Any) -> IntentGraphDraftPayload:
    return IntentGraphDraftPayload.model_validate_json(
        json.dumps(parse_graph_wire(json.dumps(instance)))
    )


def _canonical_accepts(instance: Any) -> bool:
    try:
        _canonical(instance)
    except ValidationError:
        return False
    return True


def _keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        yield from node
        for value in node.values():
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def _descriptions(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        if isinstance(node.get("description"), str):
            yield node["description"]
        for value in node.values():
            yield from _descriptions(value)
    elif isinstance(node, list):
        for value in node:
            yield from _descriptions(value)


def _scalars(node: Any) -> Counter[Any]:
    found: Counter[Any] = Counter()
    if isinstance(node, dict):
        for value in node.values():
            found += _scalars(value)
    elif isinstance(node, list):
        for value in node:
            found += _scalars(value)
    elif isinstance(node, int | float) and not isinstance(node, bool):
        found[f"number:{float(node)!r}"] += 1  # a JSON number is compared by value: 7 == 7.0
    else:
        found[json.dumps(node)] += 1
    return found


# --------------------------------------------------------------------------- identity (18-20)


def test_19_the_wire_adds_nothing_to_the_prompt_or_the_canonical_contract() -> None:
    """The prompt is the current pinned one and the canonical schema is unchanged."""
    assert hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        GRAPH_SYSTEM_INSTRUCTION_SHA256
    )
    assert schema_sha256(IntentGraphDraftPayload.model_json_schema()) == GRAPH_ANSWER_SCHEMA_SHA256
    assert GRAPH_ANSWER_SCHEMA_SHA256 == (
        "6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494"
    )


def test_20_the_exam_is_the_pinned_one() -> None:
    from tests.certification._intent_graph_exam import EXPECTED_GRAPH_EXAM_SHA256, graph_exam_sha256

    assert graph_exam_sha256() == EXPECTED_GRAPH_EXAM_SHA256


def _record(model: str) -> dict[str, Any]:
    from tests.certification._intent_graph_exam import (
        GRAPH_CERTIFICATION_RECORD_FORMAT,
        _current_graph_identity,
    )

    identity = _current_graph_identity(ModelIdentity(provider="anthropic", model=model))
    return {
        "record_format": GRAPH_CERTIFICATION_RECORD_FORMAT,
        "verdict": "PASS",
        "provider": "anthropic",
        "model": model,
        "task": identity["task"].value,
        **{k: v for k, v in identity.items() if k not in ("identity", "task")},
    }


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("provider", "openai"),
        ("model", "claude-sonnet-5"),
        ("wire_schema_sha256", "ca63b550c1d030be7ca403e1a51aec6ad7878b448266fc3981d3e7158c92222e"),
        ("wire_schema_compiler", "foundry.anthropic-structured-outputs.v1"),
        ("canonical_schema_sha256", "0" * 64),
        ("prompt_sha256", "0" * 64),
        ("exam_sha256", "0" * 64),
    ],
)
def test_18_tampering_with_any_bound_field_breaks_the_certificate(
    field: str, tampered: str
) -> None:
    from tests.certification._intent_graph_exam import (
        _current_graph_identity,
        certificate_binds,
        graph_certificate_standing,
    )

    record = _record(OPUS)
    current = _current_graph_identity(ModelIdentity(provider="anthropic", model=OPUS))
    assert record["wire_schema_sha256"] == schema_sha256(WIRE)
    assert certificate_binds(record, **current)
    assert graph_certificate_standing(record) == "CURRENT"
    record[field] = tampered
    assert not certificate_binds(record, **current)
    if field != "model":  # a record naming another Claude model is judged as that model's
        assert graph_certificate_standing(record) != "CURRENT"


# --------------------------------------------------------------------------- grammar size


def test_the_wire_has_no_reference_definition_or_union() -> None:
    keys = set(_keys(WIRE))
    assert not keys & {"$ref", "$defs", "anyOf", "oneOf", "allOf", "discriminator", "not"}
    type_lists = [n for n in _walk(WIRE) if isinstance(n.get("type"), list)]
    assert type_lists == []


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_the_wire_is_compact_and_every_object_is_closed() -> None:
    assert len(json.dumps(WIRE, sort_keys=True)) < 6000
    objects = [n for n in _walk(WIRE) if n.get("type") == "object"]
    assert objects and all(n["additionalProperties"] is False for n in objects)
    optional = [name for n in objects for name in n["properties"] if name not in n["required"]]
    assert optional == ["confidence", "confidence"]
    nullable_enums = [n for n in _walk(WIRE) if None in n.get("enum", [])]
    assert len(nullable_enums) == 2


def test_the_wire_uses_no_keyword_anthropic_does_not_support() -> None:
    unsupported = {"pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "format"}
    assert not set(_keys(WIRE)) & unsupported


def test_the_enforcement_split_is_recorded() -> None:
    assert len(GRAMMAR_ENFORCED) == 11
    assert len(DEFERRED_TO_CANONICAL) == 9


# --------------------------------------------------------------------------- descriptions


_EXAM_VOCABULARY = re.compile(
    r"refund|purchase|thirty|\bdays?\b|case|exam|scor|fixture|expected|astra|grok|gpt|claude|"
    r"anthropic|openai|xai|req-|stale-|certif|benchmark|pass\b|fail",
    re.IGNORECASE,
)


def test_descriptions_carry_no_exam_or_provider_vocabulary() -> None:
    descriptions = list(_descriptions(WIRE))
    assert descriptions
    leaks = [d for d in descriptions if _EXAM_VOCABULARY.search(d)]
    assert leaks == []


def test_descriptions_use_only_contract_terms_and_no_coaching() -> None:
    """No instruction about *which* kind or relation to choose: that is the prompt's job."""
    text = " ".join(_descriptions(WIRE))
    for coaching in ("prefer", "should", "usually", "typically", "choose", "avoid", "remember"):
        assert coaching not in text.lower(), coaching


# --------------------------------------------------------------------------- A: parser == schema


def _mutations(instance: dict[str, Any]) -> Iterator[Any]:
    """Every single-step structural corruption of a wire instance."""
    yield []
    yield "text"
    yield {**instance, "extra": []}
    for key in instance:
        yield {k: v for k, v in instance.items() if k != key}
        yield {**instance, key: None}
        yield {**instance, key: "x"}
    for key in ("nodes", "relations", "gaps"):
        for index, item in enumerate(instance[key]):
            for field in list(item):
                broken = copy.deepcopy(instance)
                del broken[key][index][field]
                yield broken
                for bad in (None, 7, "ZZZ", [], {}, 0.5, True):
                    broken = copy.deepcopy(instance)
                    broken[key][index][field] = bad
                    yield broken
            broken = copy.deepcopy(instance)
            broken[key][index]["unknown"] = "x"
            yield broken
    for index, _ in enumerate(instance["relations"]):
        for field in ("namespace", "id"):
            for bad in (None, "global", 3):
                broken = copy.deepcopy(instance)
                broken["relations"][index]["target"][field] = bad
                yield broken
        broken = copy.deepcopy(instance)
        broken["relations"][index]["target"]["unknown"] = "x"
        yield broken
    for bad in (None, 3, {"id": "A"}):
        broken = copy.deepcopy(instance)
        broken["unchanged_object_refs"] = [bad]
        yield broken


def _mixed() -> dict[str, Any]:
    return to_wire(lawful_payloads()[-1])


def _wire_corpus() -> list[Any]:
    lawful = [to_wire(value) for value in lawful_payloads()]
    return lawful + list(_mutations(_mixed()))


def test_a_the_parser_accepts_exactly_the_wire_schema_language() -> None:
    corpus = _wire_corpus()
    assert len(corpus) > 500
    disagreements = [x for x in corpus if _parses(x) != _wire_valid(x)]
    assert disagreements == []
    assert any(not _wire_valid(x) for x in corpus)


# --------------------------------------------------------------------------- round trips (1-7)


@pytest.mark.parametrize("value", lawful_payloads(), ids=lambda _: "")
def test_1_every_lawful_value_round_trips_through_the_wire(value: IntentGraphDraftPayload) -> None:
    wire = to_wire(value)
    assert _wire_valid(wire)
    assert _canonical(wire) == value


def test_1_every_node_kind_is_covered() -> None:
    kinds = {node.kind.value for value in lawful_payloads() for node in value.nodes}
    assert kinds == set(WIRE["properties"]["nodes"]["items"]["properties"]["kind"]["enum"])


def test_2_requirement_round_trip() -> None:
    wire = _payload(nodes=[_node(kind="REQUIREMENT", statement="the system must do x")])
    (node,) = _canonical(wire).nodes
    assert node.kind.value == "REQUIREMENT" and node.statement == "the system must do x"
    assert to_wire(_canonical(wire)) == wire


def test_3_constraint_round_trip() -> None:
    wire = _payload(nodes=[_node(kind="CONSTRAINT", facet="EVIDENCE_BOUND", confidence=0.75)])
    (node,) = _canonical(wire).nodes
    assert node.kind.value == "CONSTRAINT" and node.facet.value == "EVIDENCE_BOUND"
    assert node.confidence == 0.75
    assert to_wire(_canonical(wire)) == wire


def test_4_replaces_stale_round_trip() -> None:
    wire = _payload(nodes=[_node(disposition="REPLACES_STALE", replaces="OBJ-7")])
    (node,) = _canonical(wire).nodes
    assert node.disposition.value == "REPLACES_STALE"
    assert node.replaces is not None and node.replaces.object_id == "OBJ-7"
    assert to_wire(_canonical(wire)) == wire


def test_5_gap_round_trip() -> None:
    gap = {
        "local_gap_id": "g1",
        "kind": "AMBIGUITY",
        "description": "d",
        "missing_need": "PROJECT_CHOICE",
        "anchors": [
            {"namespace": "existing", "id": "OBJ-1"},
            {"namespace": "basis", "id": "CLM-1"},
            {"namespace": "local", "id": "n1"},
        ],
    }
    wire = _payload(gaps=[gap])
    (canonical_gap,) = _canonical(wire).gaps
    assert [a.model_dump() for a in canonical_gap.anchors] == [
        {"namespace": "existing", "object_id": "OBJ-1"},
        {"namespace": "basis", "claim_id": "CLM-1"},
        {"namespace": "local", "local_id": "n1"},
    ]
    assert to_wire(_canonical(wire)) == wire


def test_6_witness_round_trip() -> None:
    """R111's witness: ``unchanged_object_refs``, existing objects only."""
    wire = _payload(unchanged_object_refs=["OBJ-1", "OBJ-2"])
    refs = _canonical(wire).unchanged_object_refs
    assert [(r.namespace, r.object_id) for r in refs] == [
        ("existing", "OBJ-1"),
        ("existing", "OBJ-2"),
    ]
    assert to_wire(_canonical(wire)) == wire


def test_7_mixed_graph_round_trip() -> None:
    value = lawful_payloads()[-1]
    assert value.nodes and value.relations and value.gaps and value.unchanged_object_refs
    assert _canonical(to_wire(value)) == value


# --------------------------------------------------------------------------- refusals (8-13)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "REQUIREMENT", "mission": "m"},
        {"kind": "REQUIREMENT", "decision_rationale": "d"},
        {"kind": "INTENT", "mission": "m", "statement": "s"},
        {"kind": "DECISION", "statement": "s", "decision_rationale": ""},
        {"kind": "GOAL", "proposed_risk_level": "LOW"},
        {
            "kind": "INTENT",
            "mission": "m",
            "statement": "",
            "disposition": "REPLACES_STALE",
            "replaces": "OBJ-1",
        },
        {"kind": "ASSUMPTION", "disposition": "REPLACES_STALE", "replaces": "OBJ-1"},
        {"kind": "GOAL", "disposition": "NEW", "replaces": "OBJ-1"},
    ],
)
def test_8_a_kind_illegal_field_combination_is_wire_valid_but_canonically_refused(
    overrides: dict[str, Any],
) -> None:
    wire = _payload(nodes=[_node(**overrides)])
    assert _wire_valid(wire)
    assert not _canonical_accepts(wire)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "REQUIREMENT", "facet": "EXTERNAL_MANDATE"},
        {"kind": "CONSTRAINT", "facet": None},
        {"kind": "INTENT", "mission": "m", "statement": "", "facet": "PROJECT_BOUNDARY"},
    ],
)
def test_9_an_invalid_facet_kind_combination_is_canonically_refused(
    overrides: dict[str, Any],
) -> None:
    wire = _payload(nodes=[_node(**overrides)])
    assert _wire_valid(wire)
    assert not _canonical_accepts(wire)


@pytest.mark.parametrize(
    "relation",
    [
        {
            "source": "Bad Id",
            "relation_type": "SERVES",
            "target": {"namespace": "existing", "id": "O"},
        },
        {"source": "", "relation_type": "SERVES", "target": {"namespace": "existing", "id": "O"}},
        {
            "source": "n1",
            "relation_type": "SERVES",
            "target": {"namespace": "local", "id": "Bad Id"},
        },
        {"source": "n1", "relation_type": "SERVES", "target": {"namespace": "basis", "id": ""}},
    ],
)
def test_10_an_invalid_relation_is_canonically_refused(relation: dict[str, Any]) -> None:
    wire = _payload(relations=[relation])
    assert _wire_valid(wire)
    assert not _canonical_accepts(wire)


def test_10_an_unproposable_relation_type_never_passes_the_wire() -> None:
    relation = {
        "source": "n1",
        "relation_type": "CONFLICTS_WITH",
        "target": {"namespace": "local", "id": "a"},
    }
    assert not _wire_valid(_payload(relations=[relation]))
    assert not _parses(_payload(relations=[relation]))


@pytest.mark.parametrize(
    "overrides",
    [
        {"statement": ""},
        {"proposal_rationale": ""},
        {"kind": "INTENT", "statement": "", "mission": ""},
        {"kind": "DECISION", "decision_rationale": ""},
        {"disposition": "REPLACES_STALE", "replaces": ""},
        {"local_id": ""},
        {"local_id": "Not-Lowercase"},
        {"confidence": 1.5},
        {"confidence": -0.1},
    ],
)
def test_11_missing_or_empty_canonical_semantics_are_refused(overrides: dict[str, Any]) -> None:
    wire = _payload(nodes=[_node(**overrides)])
    assert _wire_valid(wire)
    assert not _canonical_accepts(wire)


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("nodes", 0),
        ("relations", 0),
        ("relations", 0, "target"),
        ("gaps", 0),
        ("gaps", 1, "anchors", 0),
    ],
)
def test_12_an_unknown_field_is_refused_at_the_wire(path: tuple[Any, ...]) -> None:
    wire = _mixed()
    target: Any = wire
    for step in path:
        target = target[step]
    target["note"] = "x"
    assert not _wire_valid(wire)
    assert not _parses(wire)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("nodes", 0, "kind"), "CLAIM"),
        (("nodes", 0, "disposition"), "EXISTING_UNCHANGED"),
        (("nodes", 0, "facet"), "TECHNICAL"),
        (("nodes", 0, "proposed_risk_level"), "EXTREME"),
        (("relations", 0, "relation_type"), "CONFLICTS_WITH"),
        (("relations", 0, "target", "namespace"), "global"),
        (("gaps", 0, "kind"), "UNKNOWN"),
        (("gaps", 0, "missing_need"), "ROUTE"),
        (("gaps", 1, "anchors", 0, "namespace"), "global"),
    ],
)
def test_13_an_unknown_enum_value_is_refused_at_the_wire(path: tuple[Any, ...], value: str) -> None:
    wire = _mixed()
    target: Any = wire
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    assert not _wire_valid(wire)
    assert not _parses(wire)


# --------------------------------------------------------------------------- mechanical (14-15)


def _conversion_corpus() -> list[dict[str, Any]]:
    """Wire-valid instances, lawful and not: the converter must be mechanical on all of them."""
    corpus = [to_wire(value) for value in lawful_payloads()]
    corpus += [x for x in _mutations(_mixed()) if _wire_valid(x)]
    for overrides in (
        {
            "kind": "REQUIREMENT",
            "mission": "m",
            "decision_rationale": "d",
            "facet": "PROJECT_BOUNDARY",
        },
        {"kind": "INTENT", "statement": "s", "mission": "", "proposed_risk_level": "LOW"},
        {"disposition": "NEW", "replaces": "OBJ-9"},
    ):
        corpus.append(_payload(nodes=[_node(**overrides)]))
    return corpus


def _structural(canonical: dict[str, Any]) -> Counter[Any]:
    """Namespace tags the conversion writes for references whose namespace is fixed."""
    fixed = Counter[Any]()
    fixed[json.dumps("local")] += len(canonical["nodes"]) + len(canonical["relations"])
    fixed[json.dumps("existing")] += len(canonical["unchanged_object_refs"]) + sum(
        1 for node in canonical["nodes"] if "replaces" in node
    )
    return fixed


def _neutral(wire: dict[str, Any]) -> Counter[Any]:
    neutral = Counter[Any]()
    for node in wire["nodes"]:
        neutral[json.dumps("")] += sum(1 for f in NEUTRAL_TEXT if node[f] == "")
        neutral[json.dumps(None)] += sum(1 for f in NEUTRAL_ENUM if node[f] is None)
    return neutral


def test_14_conversion_never_invents_a_value() -> None:
    for wire in _conversion_corpus():
        canonical = parse_graph_wire(json.dumps(wire))
        invented = _scalars(canonical) - _scalars(wire) - _structural(canonical)
        assert invented == Counter(), (wire, invented)
        for part in ("nodes", "relations", "gaps", "unchanged_object_refs"):
            assert len(canonical[part]) == len(wire[part])


def test_15_conversion_never_drops_a_model_decision() -> None:
    """Only the declared neutral values ("" and null in kind-specific fields) disappear."""
    for wire in _conversion_corpus():
        canonical = parse_graph_wire(json.dumps(wire))
        dropped = _scalars(wire) - _scalars(canonical)
        assert dropped == _neutral(wire), (wire, dropped)


def test_15_a_kind_illegal_value_is_carried_so_canonical_validation_sees_it() -> None:
    wire = _payload(nodes=[_node(kind="REQUIREMENT", mission="m", facet="PROJECT_BOUNDARY")])
    (node,) = parse_graph_wire(json.dumps(wire))["nodes"]
    assert node["mission"] == "m" and node["facet"] == "PROJECT_BOUNDARY"


def test_explicit_null_confidence_is_not_wire_valid() -> None:
    wire = _payload(nodes=[_node(confidence=None)])
    assert not _wire_valid(wire)
    assert not _parses(wire)


# --------------------------------------------------------------------------- classification (16-17)


def _provider(*outcomes: Any) -> AnthropicModelProvider:
    return AnthropicModelProvider(
        api_key="unused", client_factory=RecordingClientFactory(*outcomes)
    )


@pytest.mark.parametrize(
    ("wire", "stage"),
    [
        (_payload(nodes=[_node(kind="REQUIREMENT", mission="m")]), "canonical form violates"),
        (_payload(nodes=[_node(statement="")]), "canonical form violates"),
        (_payload(nodes=[_node(kind="CLAIM")]), "not an instance of the wire schema"),
        ({"nodes": []}, "not an instance of the wire schema"),
    ],
)
def test_16_an_invalid_answer_is_a_protocol_failure_never_a_pass(wire: Any, stage: str) -> None:
    from tests.unit.adapters.model_runtime.test_anthropic import request

    adapter = _provider(answer(json.dumps(wire), model=OPUS))
    with pytest.raises(ModelProtocolError, match=stage) as error:
        adapter.execute(
            model=ModelIdentity(provider="anthropic", model=OPUS),
            request=request(),
            output_type=IntentGraphDraftPayload,
        )
    assert "could not be parsed as IntentGraphDraftPayload" in str(error.value)
    assert "max_output_tokens" not in str(error.value)
    with pytest.raises(ProtocolTaskFailure):
        classify_execution_failure(error.value)


def _contestant() -> Contestant:
    from tests.certification._intent_graph_exam import GRAPH_EVIDENCE_NAMESPACE

    return Contestant(
        identity=ModelIdentity(provider="anthropic", model=OPUS),
        credential_env="UNUSED",
        provider_factory=lambda _: None,
        task=ModelTask.INTENT_GRAPH_SYNTHESIS,
        evidence_namespace=GRAPH_EVIDENCE_NAMESPACE,
        wire_schema=AnthropicModelProvider.wire_schema,
        wire_schema_compiler=AnthropicModelProvider.WIRE_SCHEMA_COMPILER,
    )


def test_17_the_exam_scorer_never_sees_a_canonical_invalid_answer() -> None:
    """The attempt raises before an observation exists, so there is nothing to score, and the
    substrate is untouched: no graph validation, no ledger write."""
    import tests.certification._intent_graph_exam as exam
    from tests.certification._intent_synthesis_exam import state_of

    substrate = exam.GRAPH_BUILDERS["A"]()
    before = state_of(substrate.store)
    invalid = _payload(nodes=[_node(kind="REQUIREMENT", mission="m")])
    provider = _provider(answer(json.dumps(invalid), model=OPUS))
    with pytest.raises(ProtocolTaskFailure, match="canonical form violates"):
        exam.run_graph_attempt(_contestant(), substrate, "A", 1, provider=provider)
    assert state_of(substrate.store) == before


def test_17_a_canonical_valid_answer_reaches_foundry_governance() -> None:
    import tests.certification._intent_graph_exam as exam

    substrate = exam.GRAPH_BUILDERS["A"]()
    valid = _payload(
        gaps=[
            {
                "local_gap_id": "g1",
                "kind": "AMBIGUITY",
                "description": "d",
                "missing_need": "PROJECT_CHOICE",
                "anchors": [],
            }
        ]
    )
    provider = _provider(answer(json.dumps(valid), model=OPUS))
    observation = exam.run_graph_attempt(_contestant(), substrate, "A", 1, provider=provider)
    assert observation.result is not None
    assert [gap.kind.value for gap in observation.result.gaps] == ["AMBIGUITY"]
