"""Every certification record written before the current record format stays exactly as it was.

The Grok runtime-v1 and runtime-v2 graph records, Astra's schema-refused graph record and both
Slice-1 records were committed at 80ec454 (before schema binding, format v2). Astra's first
semantic graph record (NOT CERTIFIED, 21/24, format v2, exam v1) was committed at 5e88489 (before
exam binding, format v3). Each later binding is prospective: it never rewrites, re-scores or
re-reads an earlier record into a certificate, and it never fabricates an identity into a record
that was written without one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._intent_graph_exam import (
    GRAPH_CERTIFICATION_RECORD_FORMAT,
    HISTORICAL_GRAPH_NAMESPACES,
    SCHEMA_BOUND_RECORD_FORMAT,
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

EVIDENCE_AT_5E88489: Final[dict[str, str]] = {
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_a_ledger.json": (
        "4358799b16ec52c584abd8106c522301b41481fec466c4ae057d883e5612c8fb"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_b_ledger.json": (
        "9f8931f7e7820b8d191b7b1bcc5f6d9c9331d2c6d37e00dd6fbbdc15774ce1ed"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_c_ledger.json": (
        "37ad3a84d5314d6f2b712b3b751e51c77e93da8bdbbe7087a3760f51be5b8007"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_d_ledger.json": (
        "db882c34d632a7a0a2ebaa23ca48be3870d923b9c1d71192ceff3d9c311c9cf3"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_e_ledger.json": (
        "141bae4148408e61c350b0132da210974843bb088ea8d0e179796aae72bd400a"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_f_ledger.json": (
        "1e6cfb2b1014343bec241837c9ed4b2d38efb40fcf4e8634ff474b7fedf4d9a1"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_g_ledger.json": (
        "ab3b9ce183dbd2581405d3f83e69a45e8186e343f75b89a8dd8fcc0be6fe4ca9"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_h_ledger.json": (
        "62b84221c97e671fa581180803c634f0ebb598e6823bd18116183a8b292e8bb7"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/certification.json": (
        "e2f53ae6c49ea1b2184faffb070b2e4cf58fbec9d849eb5eb07aad37de6de697"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/measurements.json": (
        "468d7b50d4d45c256304cc00cdf713ccc3e0147194bef0d167ab81430309b433"
    ),
}
"""SHA-256 of Astra's schema-bound, exam-v1 graph evidence at 5e88489, from the git objects."""

EVIDENCE_AT_5FF8EDF: Final[dict[str, str]] = {
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_a_ledger.json": (
        "85defd235403436cfe1262d18817f2588f8f13270b793cf978e3d3dcf1a84f64"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_b_ledger.json": (
        "c2232e634f669a72e7e4b99fdca62095995d22d2691da4d6a82276e9ca1f1d22"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_c_ledger.json": (
        "977521a946f59a57f22b08512bf0ccaf480f84c62222fb4874a96041f83c61c4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_d_ledger.json": (
        "effbd5ad088581caecf9cc3111f217f756990356f04861c6394466d633ad2050"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_e_ledger.json": (
        "c75bfc80b02b56ba9a5ceb4a32e6f6446eca141a696808a242ae845b1c7cdb2e"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_f_ledger.json": (
        "930f1da738dd6085cb3ed53e7cc61585910cd4a260405657421d91b7a9189b4c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_g_ledger.json": (
        "2a810b704a69703d5af004a8edc9aca6c9a4c17ba82bbfce79d3b8307601e07c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_h_ledger.json": (
        "fca0a74747ef84e1ead37535e5f34c66dfd82cde6687ba3cf63f73114c7a6696"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json": (
        "2d57db6a373a5840a055c97fc4597d251c4a53d122c2c46e55f52f7a9ece3923"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/measurements.json": (
        "0037054493d77deda87c5d5d491835673f5de8fdc23752d878422d5d0784045b"
    ),
}
"""Astra's exam-v2 certificate (PASS 24/24, runtime-v2), committed at 5ff8edf. Superseded."""

GROK_EXAM_V2_DIAGNOSTIC: Final[dict[str, str]] = {
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_a_ledger.json": (
        "5c347c539c2e97927d280d4e6f1aae4018ee39e65a5621df438cf102e2fc4f70"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_b_ledger.json": (
        "df67f918aee9851c2e6fa07eec945c3777344a43bae20ccd1fd659e4cb1d9eef"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_c_ledger.json": (
        "9dd69d20f0609804044e00363fbdfe6ffab97b68bf173877a19592bbaa356803"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_d_ledger.json": (
        "be1c0024ea6162fd09efa7a94844b26617cca5904fba236a85d8b1c72217b28f"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_e_ledger.json": (
        "0736d50cfd1c4eed0552804b262f1d021bc28ca121f00fa084e4055d100d68c9"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_f_ledger.json": (
        "c198710b3b833f759d42d26189902155420619a0ca1f05bde1a8011af54ebb19"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_g_ledger.json": (
        "ad3a62b145694ecefe5835e370a48c62ad439764fa9e4a6b7ac0da07d25d4c1c"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_h_ledger.json": (
        "9ed3f4fe691bb2514d80e98049647b3e5eb2cbab4bd85af88f9a20b20a2e23d1"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/certification.json": (
        "f0750c8f2b84a23300c29a72d49cacf68824885ab2e7e86be3c74d80195d79f3"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/measurements.json": (
        "a9493b79cacc29d39a3b9d566657d9b39378c2642cb0e2569e3104db2a54f1c0"
    ),
}
"""Grok's exam-v2 run (NOT CERTIFIED 21/24), captured byte for byte before it was committed as
diagnostic evidence: its case A failures fall in the dimension exam v2 left unspecified."""

EVIDENCE_AT_2F9F5D6: Final[dict[str, str]] = {
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_a_ledger.json": (
        "111a653c9d0ae6eafb2c9a0483181af166cc807d9490c0d2e979ee9dfef2fffe"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_b_ledger.json": (
        "c4116e44e88d214f1eb036223bafb281e20523b426a897d5441610e3cac407f4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_c_ledger.json": (
        "e75286dd0e10f2cebf42a19df8365633af4225742f42f06368fde24c6f623b9f"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_d_ledger.json": (
        "de73e613f5d2216c07877eec19d0866272bbeae69f1490b2a6655cf4ef16a79f"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_e_ledger.json": (
        "5a50dff148a2a46b2885f4f37d8f7ee6b708e4921a4fc7fc1c63ec573e0daa46"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_f_ledger.json": (
        "d620539a82fa27afc311812c19c6ea202ace97a998c37fda710a5c1a564597f7"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_g_ledger.json": (
        "f2ad202c4c223c6ff4ea12b8209dc601a0da628225bdbba7e9b83eac88fc02e5"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_h_ledger.json": (
        "61c542f07f6e5f7a596b75c5d05b9fe9ced0c1164aea69042c50bcf4a96c797b"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_i_ledger.json": (
        "762b7a4e46a5aa6f543d4f26debdcd411a1aa01330ce7b975eed39d5db2758c4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/certification.json": (
        "6c0480a463a413001f56b21d9fced9fa23950499e9327083c974f082ce698b88"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/measurements.json": (
        "35ceb7d92c52017ab153251eaa1f88c3403bf64103b08f4141b94888186596eb"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_a_ledger.json": (
        "74628d59d1d07f767d09f9de15cd8a1b28e446120af8f73f479b0da2a6a4a983"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_b_ledger.json": (
        "ab00f37f697f8ccd6bfe1b6ec665d6a35ec593d0d0b21b63548bd72b58a82908"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_c_ledger.json": (
        "7095ac57e1514b933704aad33b0161af7d337ae9aea7a727a821af19e91e8ad7"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_d_ledger.json": (
        "b23804ddc2cb8c6b1f2781dba1c4ea3390233bdfd218c590008316c8d63d34b0"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_e_ledger.json": (
        "c15891a3e0d683663a8beb5e30fccef166db047a3f5ada293bbf6e6c25432cf5"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_f_ledger.json": (
        "e934b14ed263ccca7e6c4e5f24af0f5541d91364f89e3cef864674f47e7adf78"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_g_ledger.json": (
        "f9f2d59e4b0fbf7d836edda509cb1558d093d99b1dc7ac5400f8300b2e8b2e2d"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_h_ledger.json": (
        "92ce7e8b164fdbec9746cab3b605d23cf0a775e6f85826f9b6b9aab4f7fd7927"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/certification.json": (
        "1f6e4e41b1ba137e3c8f3f518d55d89bc2ea884e980df92486803e68da13e6d5"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/measurements.json": (
        "7b29e655f041ee7db7ab6f1c298e37811f7d09ef31616ec503edd6c41a926e6a"
    ),
}
"""Exam v3 under runtime-v3, committed at 2f9f5d6: Astra PASS 27/27 (now superseded by exam v4)
and Grok NOT CERTIFIED 20/27."""

PRE_EXAM_BINDING: Final[dict[str, str]] = {**EVIDENCE_AT_80EC454, **EVIDENCE_AT_5E88489}
HISTORICAL_EVIDENCE: Final[dict[str, str]] = {
    **PRE_EXAM_BINDING,
    **EVIDENCE_AT_5FF8EDF,
    **GROK_EXAM_V2_DIAGNOSTIC,
    **EVIDENCE_AT_2F9F5D6,
}

SCHEMA_FIELDS = ("canonical_schema_sha256", "wire_schema_sha256", "wire_schema_compiler")
EXAM_FIELDS = ("exam_id", "exam_version", "exam_sha256")
SCHEMA_BOUND_ASTRA = "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/certification.json"


def test_every_historical_evidence_file_is_byte_identical() -> None:
    assert len(EVIDENCE_AT_5E88489) == len(EVIDENCE_AT_5FF8EDF) == 10
    assert len(GROK_EXAM_V2_DIAGNOSTIC) == 10
    assert len(EVIDENCE_AT_2F9F5D6) == 21  # Astra 11 (with case I), Grok 10 (I-1 had no answer)
    for relative, digest in HISTORICAL_EVIDENCE.items():
        data = (EVIDENCE_ROOT / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, relative


def test_no_file_was_added_to_a_historical_namespace() -> None:
    for namespace in HISTORICAL_GRAPH_NAMESPACES:
        for directory in EVIDENCE_ROOT.glob(f"*/*/{namespace}"):
            for path in directory.iterdir():
                assert str(path.relative_to(EVIDENCE_ROOT)) in HISTORICAL_EVIDENCE, path


def test_no_historical_graph_record_gains_an_identity_it_was_not_written_with() -> None:
    records = [r for r in PRE_EXAM_BINDING if r.endswith("certification.json")]
    assert len(records) == 4
    for relative in records:
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        assert record_format(record) != GRAPH_CERTIFICATION_RECORD_FORMAT
        assert not set(EXAM_FIELDS) & record.keys(), relative
        assert record["verdict"] == "NOT CERTIFIED", relative
        if relative == SCHEMA_BOUND_ASTRA:
            assert record_format(record) == SCHEMA_BOUND_RECORD_FORMAT
            assert set(SCHEMA_FIELDS) <= record.keys()
        else:
            assert record_format(record) == "ie3-graph-certification.v1"
            assert not set(SCHEMA_FIELDS) & record.keys(), relative


def test_the_exam_v2_records_stay_bound_to_exam_v2() -> None:
    """Both were written in the exam-bound format against exam v2 and runtime-v2. Unchanged."""
    expected = {
        "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json": ("PASS", 24),
        "xai/grok-4.7/intent_graph_synthesis_exam_bound/certification.json": ("NOT CERTIFIED", 21),
    }
    for relative, (verdict, passed) in expected.items():
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        assert record_format(record) == GRAPH_CERTIFICATION_RECORD_FORMAT
        assert (record["exam_version"], record["exam_sha256"]) == (
            "2",
            "813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c",
        )
        assert record["policy_version"] == "intent-graph-synthesis-runtime-v2"
        assert (record["verdict"], record["passed_attempts"], record["required_attempts"]) == (
            verdict,
            passed,
            24,
        )


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
    assert verdict(SCHEMA_BOUND_ASTRA) == ("NOT CERTIFIED", 21, 24)


def test_the_exam_v1_record_keeps_its_three_case_c_failures() -> None:
    """Truthful history under the defective exam: nothing re-scored, nothing credited."""
    record = json.loads((EVIDENCE_ROOT / SCHEMA_BOUND_ASTRA).read_text())
    failed = [(a["case"], a["attempt"]) for a in record["attempts"] if a["verdict"] != "PASS"]
    assert failed == [("C", 1), ("C", 2), ("C", 3)]


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
