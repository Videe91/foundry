"""Every certification record that existed before schema binding stays exactly as it was.

The Grok runtime-v1 and runtime-v2 graph records, Astra's schema-refused graph record and both
Slice-1 records were committed at 80ec454. Schema binding (record format v2) is prospective: it
never rewrites, re-scores or re-reads them into a certificate, and it never fabricates a schema
identity into a record that was written without one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._intent_graph_exam import (
    GRAPH_CERTIFICATION_RECORD_FORMAT,
    HISTORICAL_GRAPH_NAMESPACES,
    record_format,
)

EVIDENCE_AT_80EC454: Final[dict[str, str]] = {
    "openai/gpt-6-astra/case_a_ledger.json": (
        "afcebdb05e95d1de357adb35b63f954621018da1e0cc4a890804ee23d7232e5c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json": (
        "c93642bb82cea5106ed1c275548aca5477f640e689104dae615e2df6d43fbc1e"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_v2/measurements.json": (
        "371e60683a7730b7c63fd728608c34e8d25bace0f08370b354d3828dbab31f8a"
    ),
    "openai/gpt-6-astra/measurements.json": (
        "f159aa3fe77eb8e246299c194b4b6e6cafc3708d88e9e455741cbb8928e78081"
    ),
    "xai/grok-4.7/case_a_ledger.json": (
        "db4b0e495398e4faf8d92b2113b30094dacd7a69e3a66546060cf0d9b47f93b0"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_a_ledger.json": (
        "0626caf1881c6448681d7f10ba555ccfa1dffd1088fec5cf90f8eba0cf3a2369"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_b_ledger.json": (
        "43c8e2cfee90fbb7e1a2e68702ad5ecf7ab4af1ce52a1a1b89f96748533356a9"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_c_ledger.json": (
        "434ae05e50f605073b4d2220df2220d4382a3708af4e53d8dc6bfc1f39cf15ba"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_d_ledger.json": (
        "139e078eb3aa6cb4e5d6869bbdb6b6723ab77548e264e050d845ecc10b9a33c0"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_e_ledger.json": (
        "f48a9a3dc0029a02fd5314decac747781c056b980b9f5fb8283bddeb42920526"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_f_ledger.json": (
        "fa7dee528abb3398a2402c5fd9389acdd5286aee7a046ac9060eac6061e4a59d"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_g_ledger.json": (
        "6f019ca48b44fb56c0f4bea4f8a635fdd2b1657bf349eec85775b423ac6b21a7"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_h_ledger.json": (
        "6bfa14a02a40d5ff2068d6fc2b28f341b0ce3e4b3e1e87d8376b77935e2655de"
    ),
    "xai/grok-4.7/intent_graph_synthesis/certification.json": (
        "d1bc0c55b4c15e62c6b54ebe590e0c87c3d79ab31b10de5b2515d3e8fcd40070"
    ),
    "xai/grok-4.7/intent_graph_synthesis/measurements.json": (
        "cf59649ae589c2e1513f911354f447d43517d15dbedf40dd995d248fc2138801"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_b_ledger.json": (
        "cbff91c484a2e0f9582f2e88b1be909444e373388191bd5b0d8c9d71eb3caba8"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_c_ledger.json": (
        "72fc6a861b4c66296354e1caeebc755aef396c7b8951652eb481d53e21105d69"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_d_ledger.json": (
        "fd36ba73eb942c5e9dc4fa4d556d2f3bd79da47d5bc890de30ece9b8c5c2b513"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_e_ledger.json": (
        "3e3eb8784362361ec21cb6557d41882a29ea9827f3eb57549f20d0cd38084664"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/certification.json": (
        "9885131d8cac4e95ee6945dd1142abf4a71e015f15b1c52a11689bff35b92d3e"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/measurements.json": (
        "f6c77e382d2cd8717a61bd59c29015bced649204b2307c5048dc4a833a016097"
    ),
    "xai/grok-4.7/measurements.json": (
        "3f1e1080dafa080c6a0e4453fa8ac9a4c9a799b7072950fcef1e5920b6896305"
    ),
}
"""SHA-256 of every committed evidence file at 80ec454, read from the git objects."""

SCHEMA_FIELDS = ("canonical_schema_sha256", "wire_schema_sha256", "wire_schema_compiler")


def test_every_pre_schema_evidence_file_is_byte_identical() -> None:
    for relative, digest in EVIDENCE_AT_80EC454.items():
        data = (EVIDENCE_ROOT / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, relative


def test_no_file_was_added_to_a_historical_namespace() -> None:
    for namespace in HISTORICAL_GRAPH_NAMESPACES:
        for directory in EVIDENCE_ROOT.glob(f"*/*/{namespace}"):
            for path in directory.iterdir():
                assert str(path.relative_to(EVIDENCE_ROOT)) in EVIDENCE_AT_80EC454, path


def test_no_historical_graph_record_gains_a_schema_identity() -> None:
    records = [r for r in EVIDENCE_AT_80EC454 if r.endswith("certification.json")]
    assert len(records) == 3
    for relative in records:
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        assert record_format(record) != GRAPH_CERTIFICATION_RECORD_FORMAT
        assert not set(SCHEMA_FIELDS) & record.keys(), relative
        assert record["verdict"] == "NOT CERTIFIED", relative


def test_the_historical_verdicts_are_unchanged() -> None:
    def verdict(relative: str) -> tuple[str, int, int]:
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        return record["verdict"], record["passed_attempts"], record["required_attempts"]

    assert verdict("xai/grok-4.7/intent_graph_synthesis/certification.json") == (
        "NOT CERTIFIED",
        4,
        24,
    )
    assert verdict("xai/grok-4.7/intent_graph_synthesis_v2/certification.json") == (
        "NOT CERTIFIED",
        7,
        24,
    )
    assert verdict("openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json") == (
        "NOT CERTIFIED",
        0,
        24,
    )


def test_the_astra_graph_record_still_means_no_model_examination_occurred() -> None:
    """0/24 is not a semantic score: every attempt was refused before inference."""
    record = json.loads(
        (
            EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json"
        ).read_text()
    )
    attempts = record["attempts"]
    assert len(attempts) == 24
    for attempt in attempts:
        assert attempt["verdict"] == "INCOMPLETE"
        assert attempt["outcome"] == "NO_ANSWER"
        assert attempt["failure"].startswith("TransportFailure:")
        assert attempt["output_tokens"] is None
    assert not list(
        (EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_v2").glob("case_*_ledger.json")
    ), "no answer existed, so no model-authored ledger may exist"
