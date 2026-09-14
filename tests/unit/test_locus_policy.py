"""The locus lifecycle policy: an additive successor to the contrastive (F) path.

Root cause it addresses (frozen 9P3 evidence, C09): the historical prompts define a
semantic address as "one subject and one facet (property, aspect, or question)", so a
genuinely new but compatible proposition about a known locus reads as a new facet — the
contrastive path split the locus into a second address, and the historical
non-contrastive path, whose lifecycle vocabulary names only restatement and correction,
supported the old claim and never asserted the new one. The representation itself is
capable: several compatible claims are current at one address elsewhere in the same run.

The successor policy states the missing distinction — an ADDRESS is a stable locus /
question about a subject; a CLAIM is one proposition within it — and classifies every
proposition (never the evidence item) into restatement, correction, compatible extension
or distinct locus. It is a NEW policy version with its own frozen prompt; the historical
``intent-v2-9p-v4`` and ``intent-v2-9p2-v1`` prompts, hashes and classes are untouched.
No network; no reasoner is constructed here.
"""

from __future__ import annotations

import hashlib
import re
import socket

import pytest

import foundry.adapters.semantics.xai_reasoner as mod
from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    XAIContrastiveSemanticReasoner,
    XAILocusSemanticReasoner,
    XAISemanticReasoner,
)

HISTORICAL_9P_PROMPT_SHA256 = "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
HISTORICAL_9P2_PROMPT_SHA256 = "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- identity ------------------------------------------------------------------------


def test_locus_policy_version_is_a_distinct_successor() -> None:
    assert LOCUS_POLICY_VERSION == "intent-v2-locus-v1"
    assert LOCUS_POLICY_VERSION not in {POLICY_VERSION, CONTRASTIVE_POLICY_VERSION}
    assert "LOCUS_POLICY_VERSION" in mod.__all__
    assert "LOCUS_SYSTEM_INSTRUCTION" in mod.__all__
    assert "LOCUS_SYSTEM_INSTRUCTION_SHA256" in mod.__all__
    assert "XAILocusSemanticReasoner" in mod.__all__


def test_locus_instruction_extends_the_contrastive_instruction_byte_for_byte() -> None:
    assert LOCUS_SYSTEM_INSTRUCTION.startswith(CONTRASTIVE_SYSTEM_INSTRUCTION)
    assert LOCUS_SYSTEM_INSTRUCTION != CONTRASTIVE_SYSTEM_INSTRUCTION
    assert (
        "LOCUS LIFECYCLE GUIDANCE"
        in LOCUS_SYSTEM_INSTRUCTION[len(CONTRASTIVE_SYSTEM_INSTRUCTION) :]
    )


def test_locus_instruction_is_frozen_by_a_pasted_hash() -> None:
    assert _sha(LOCUS_SYSTEM_INSTRUCTION) == LOCUS_SYSTEM_INSTRUCTION_SHA256
    assert len(LOCUS_SYSTEM_INSTRUCTION_SHA256) == 64
    assert set(LOCUS_SYSTEM_INSTRUCTION_SHA256) <= set("0123456789abcdef")
    assert LOCUS_SYSTEM_INSTRUCTION_SHA256 not in {
        SYSTEM_INSTRUCTION_SHA256,
        CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    }


def test_historical_policies_are_byte_identical() -> None:
    assert POLICY_VERSION == "intent-v2-9p-v4"
    assert CONTRASTIVE_POLICY_VERSION == "intent-v2-9p2-v1"
    assert SYSTEM_INSTRUCTION_SHA256 == HISTORICAL_9P_PROMPT_SHA256
    assert CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256 == HISTORICAL_9P2_PROMPT_SHA256
    assert _sha(SYSTEM_INSTRUCTION) == HISTORICAL_9P_PROMPT_SHA256
    assert _sha(CONTRASTIVE_SYSTEM_INSTRUCTION) == HISTORICAL_9P2_PROMPT_SHA256
    assert XAISemanticReasoner.policy_version == POLICY_VERSION
    assert XAISemanticReasoner.system_instruction == SYSTEM_INSTRUCTION
    assert XAIContrastiveSemanticReasoner.policy_version == CONTRASTIVE_POLICY_VERSION
    assert XAIContrastiveSemanticReasoner.system_instruction == CONTRASTIVE_SYSTEM_INSTRUCTION


def test_locus_reasoner_is_the_contrastive_path_with_the_successor_policy() -> None:
    assert issubclass(XAILocusSemanticReasoner, XAIContrastiveSemanticReasoner)
    assert XAILocusSemanticReasoner.policy_version == LOCUS_POLICY_VERSION
    assert XAILocusSemanticReasoner.system_instruction == LOCUS_SYSTEM_INSTRUCTION
    assert XAILocusSemanticReasoner.include_comparison_context is True
    # The only overrides are the two policy class variables; parser, schema, reference
    # law and transport are inherited unchanged.
    own = {name for name in vars(XAILocusSemanticReasoner) if not name.startswith("__")}
    assert own == {"policy_version", "system_instruction"}


# --- the law the guidance must state --------------------------------------------------


def _guidance() -> str:
    return LOCUS_SYSTEM_INSTRUCTION[len(CONTRASTIVE_SYSTEM_INSTRUCTION) :]


@pytest.mark.parametrize(
    "sentence",
    [
        # precedence over the historical facet definition it refines
        "This guidance refines the SEMANTIC DEFINITIONS above",
        "this guidance governs",
        # address = stable locus / question; claim = one proposition within it
        "A semantic address is a STABLE LOCUS",
        "the one stable question about",
        "A claim is ONE PROPOSITION within that locus",
        "claims may be current at one address at the same time",
        # new proposition is never, by itself, a reason to split the locus
        "Never create an address merely because evidence introduces a new property",
        "belongs AT that address as an additional claim with its own predicate",
        "CREATE_ADDRESS is appropriate only when a proposition answers a genuinely different",
        # same subject is never, by itself, a reason to merge loci
        "sharing a subject with a known address is not sufficient",
        "adding a proposition is not sufficient to split it",
        # descriptor authoring at locus granularity
        "write the facet as the locus-level question",
        "put the specific aspect in the claim predicate",
        # per-proposition classification and the four outcomes
        "Classify PER PROPOSITION, never per evidence item",
        "restatement:",
        "correction:",
        "compatible extension:",
        "distinct locus:",
        "ASSERT_CLAIM at that SAME address with a new predicate, no SUPERSEDE",
        "the existing compatible claims stay current",
        "never excuses omitting the",
        "ASSERT_CLAIM for a new proposition carried by the same evidence",
    ],
)
def test_locus_guidance_states_each_rule(sentence: str) -> None:
    assert sentence in _guidance(), sentence


def test_locus_guidance_keeps_correction_and_restatement_law() -> None:
    guidance = _guidance()
    assert "SUPPORTS_CLAIM that claim" in guidance
    assert "plus SUPERSEDE of the incompatible claim's created_by_judgment_id" in guidance
    # A correction is still the only path that retires a current claim.
    assert "no SUPERSEDE" in guidance


# --- anti-overfitting: nothing experiment-specific in the request path -----------------


@pytest.mark.parametrize(
    "leak",
    [
        "Orion",
        "orion",
        "cancel",
        "Cancel",
        "C09",
        "locus H",
        "EV-O-",
        "Track A",
        "Track B",
        "Track C",
        "referential status",
        "subsystem gate",
        "provenance identity",
        "credential",
        "retry",
        "jitter",
        "audit",
        "lease",
    ],
)
def test_locus_instruction_contains_no_experiment_or_scenario_wording(leak: str) -> None:
    assert leak not in LOCUS_SYSTEM_INSTRUCTION, leak


@pytest.mark.parametrize(
    "label", ["RESTATEMENT", "CORRECTION", "REVERT", "COMPATIBLE_EXTENSION", "SEMANTIC_NO_OP"]
)
def test_locus_instruction_never_carries_a_canonical_transition_label(label: str) -> None:
    """The hidden transition-class tokens of the sealed experiments are canonical labels;
    the successor prompt speaks of them only as ordinary lower-case English."""
    assert (
        re.search(rf"(?<![A-Za-z0-9_-]){label}(?![A-Za-z0-9_-])", LOCUS_SYSTEM_INSTRUCTION) is None
    )
