"""Seal and preflight of locus validation v4 (design §10).

``build_manifest`` and ``expectations_document`` are the two sealed files, written once by
``prepare`` into an empty directory and committed as the seal. The manifest freezes the
design, corpus, source-coverage map, proposition inventory and expectations, the adjudication
questions, the scoring rules (the sources of the evaluator and of the standing), the model
identity and configuration, the policy identity, the output contract and the canonical-facet
projection. Preflight recomputes both files from the code and
refuses any difference, then checks the git seal shape, a clean tree, the policy identity,
the resolver, single use, leakage and the regression bytes. Every gate is a pure function of
injected facts, so each is testable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    CANONICAL_FACET_POLICY_VERSION,
    CANONICAL_FACET_SYSTEM_INSTRUCTION,
    CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256,
    CONCERN_OUTPUT_SCHEMA_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    concern_output_schema_sha256,
    semantic_output_schema_sha256,
)
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.evidence import sha256_of_content
from foundry.domain.semantic_identity import CANONICAL_FACET_PREFIX
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v4 import corpus, expectations, protocol, world

__all__ = [
    "ANSWER_KEY_VOCABULARY",
    "GATE_NAMES",
    "NINE_P3_H",
    "SCORING_SOURCES",
    "V2_REGRESSION_TEXT",
    "Gate",
    "GitFacts",
    "build_manifest",
    "leakage_findings",
    "preflight_gates",
    "sealed_json",
]

NINE_P3_H: Final[dict[str, tuple[str, str]]] = {
    "H-T1": ("EV-O-H01", "b5bc7209bec7ef060596d0c346416c1dea6cce390c2e69c1cae78edc19f79462"),
    "H-T9": ("EV-O-H09", "422ea6e21a168c65b8fb5a60660358a41b01c29138f3a4448d16d90acf4ed29e"),
}
"""The sealed 9P3 evidence the orion ledger reproduces byte for byte (verified by a test
against the 9P3 manifest's recorded ``content_sha256``)."""

V2_REGRESSION_TEXT: Final[dict[str, str]] = {
    "LATE-T1": "cd10e73c50a82d54dc0d50eae69a114aa4196f2b4d7e30a5ef64e6696d2b1c49",
    "LATE-NOTE-T2": "92b7b49543f9f6ce915b912c2ad8b4dee5e7cd50352370711f77e90e5336ba39",
}
"""sha256 of validation v2's sealed texts for the C6 over-split: the same bytes are the input
here (verified by a test against the v2 sealed manifest)."""

SCORING_SOURCES: Final = ("evaluation.py", "adjudication.py", "expectations.py")
"""The scoring rules, frozen by the digest of their source."""

ANSWER_KEY_VOCABULARY: Final = (
    "restatement",
    "extension",
    "correction",
    "contradiction",
    "distractor",
    "over-split",
    "under-split",
    "supersede",
    "conflicts_with",
    "expected",
    "case ",
    "C0-",
    "C1-",
    "C5-",
    "C7-",
    "C8-",
    "C9",
    "U1-",
    "U4-",
    "locus",
    "governed",
    "concern",
    "dimension",
    "facet",
    "grain",
    "regression",
    "canonical",
    "rules governing",
)
"""Words that name the answer key or the policy's own terms. None may appear in a
model-visible document or seed address."""

REQUEST_PATH_MODULES: Final = ("corpus", "world", "recording", "runner", "protocol")

GATE_NAMES: Final = (
    "manifest_matches_code",
    "expectations_match_code",
    "seal_commit_adds_exactly_the_sealed_files",
    "seal_parent_is_the_harness",
    "worktree_clean",
    "canonical_facet_policy_identity",
    "canonical_facet_admission",
    "source_coverage_complete",
    "grpc_dns_resolver_native",
    "single_use",
    "leakage",
    "nine_p3_h_bytes",
    "v2_regression_bytes",
)


class Gate(FrozenModel):
    name: str
    passed: bool
    detail: str


class GitFacts(FrozenModel):
    head_sha: str
    head_parent_sha: str
    head_added_files: tuple[str, ...]
    head_changed_files: tuple[str, ...]
    worktree_clean: bool


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def build_manifest(*, harness_sha: str, package_dir: Path) -> dict[str, Any]:
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "artifact_format_version": protocol.ARTIFACT_FORMAT_VERSION,
        "design_spec_path": protocol.DESIGN_SPEC_PATH,
        "design_spec_sha256": _file_sha(Path(protocol.DESIGN_SPEC_PATH)),
        "harness_sha": harness_sha,
        "predecessor": {
            "experiment": protocol.PREDECESSOR_EXPERIMENT,
            "adjudication_sha": protocol.PREDECESSOR_ADJUDICATION_SHA,
        },
        "policy_commit": protocol.POLICY_COMMIT,
        "provider": protocol.PROVIDER,
        "model": protocol.MODEL,
        "reasoning_effort": protocol.REASONING_EFFORT,
        "grpc_dns_resolver": protocol.GRPC_DNS_RESOLVER_FROZEN,
        "policy_version": protocol.POLICY_VERSION_FROZEN,
        "reasoner_class": protocol.REASONER_CLASS_FROZEN,
        "prompt_sha256": protocol.PROMPT_SHA256_FROZEN,
        "output_schema": protocol.OUTPUT_SCHEMA_FROZEN,
        "output_schema_sha256": protocol.OUTPUT_SCHEMA_SHA256_FROZEN,
        "historical_output_schema_sha256": protocol.HISTORICAL_OUTPUT_SCHEMA_SHA256,
        "canonical_facets": protocol.CANONICAL_FACETS,
        "canonical_facet_prefix": CANONICAL_FACET_PREFIX,
        "ledgers": {
            ledger: {
                "project_id": protocol.PROJECT_IDS[ledger],
                "scope": protocol.SCOPES[ledger],
                "t1": "MODEL" if ledger in protocol.MODEL_SEEDED else "AUTHOR_SEED",
            }
            for ledger in protocol.LEDGERS
        },
        "budgets": {
            "calls_per_delta": protocol.CALLS_PER_DELTA,
            "max_frontier_calls": protocol.MAX_FRONTIER_CALLS,
            "max_cost_usd": protocol.MAX_COST_USD,
            "retries": 0,
            "judge_calls": 0,
        },
        "nine_p3_h_evidence": {k: {"id": v[0], "sha256": v[1]} for k, v in NINE_P3_H.items()},
        "v2_regression_text_sha256": dict(V2_REGRESSION_TEXT),
        "corpus": corpus.corpus_record(),
        "corpus_sha256": corpus.corpus_sha256(),
        "expectations_sha256": expectations.expectations_sha256(),
        "source_coverage_sha256": expectations.source_coverage_sha256(),
        "source_coverage_findings": list(expectations.source_coverage_findings()),
        "adjudication_questions_sha256": expectations.adjudication_questions_sha256(),
        "scoring_sources_sha256": {name: _file_sha(package_dir / name) for name in SCORING_SOURCES},
    }


def sealed_json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def leakage_findings(package_dir: Path) -> tuple[str, ...]:
    """Answer-key words in model-visible text; request-path modules importing the key."""
    findings: list[str] = []
    for doc in corpus.DOCUMENTS.values():
        text = doc.text.lower()
        for word in ANSWER_KEY_VOCABULARY:
            if word.lower() in text:
                findings.append(f"document {doc.key} contains {word!r}")
    for seeded in corpus.SEED_WORLDS.values():
        for address in seeded:
            # The seeded facet is Foundry's canonical projection of the subject, checked
            # against ``canonical_facet`` elsewhere; the words scanned here are the author's.
            shown = " ".join([address.subject, *(c.text for c in address.claims)])
            shown += " " + " ".join(c.predicate for c in address.claims)
            for word in ANSWER_KEY_VOCABULARY:
                if word.lower() in shown.lower():
                    findings.append(f"seed address {address.key} contains {word!r}")
    for module in REQUEST_PATH_MODULES:
        source = (package_dir / f"{module}.py").read_text()
        for line in source.splitlines():
            if line.startswith(("from ", "import ")) and (
                "expectations" in line or "adjudication" in line or "evaluation" in line
            ):
                findings.append(f"request-path module {module} imports the answer key")
    return tuple(findings)


def _governor_admission_flag() -> bool:
    """What a ledger governor actually runs with (read from a fresh governor, not a literal)."""
    _, governor = world.fresh_governor(
        "core", clock=lambda: protocol.OBSERVED_AT, id_factory=lambda prefix: f"{prefix}-GATE"
    )
    policy = getattr(governor, "_policy", None)
    return isinstance(policy, AdmissionPolicy) and policy.canonical_facets


def preflight_gates(
    *,
    sealed_manifest: Mapping[str, Any] | None,
    sealed_expectations: Mapping[str, Any] | None,
    git: GitFacts,
    grpc_dns_resolver: str | None,
    raw_present: tuple[str, ...],
    package_dir: Path,
) -> tuple[Gate, ...]:
    out_dir = protocol.EXPERIMENT_ARTIFACT_DIR
    sealed = tuple(f"{out_dir}{n}" for n in protocol.SEALED_FILE_NAMES)
    manifest = (
        build_manifest(harness_sha=str(sealed_manifest.get("harness_sha")), package_dir=package_dir)
        if sealed_manifest is not None
        else None
    )
    computed_prompt = hashlib.sha256(CANONICAL_FACET_SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    reasoner_class = getattr(xai_reasoner, protocol.REASONER_CLASS_FROZEN, None)
    admission_flag = _governor_admission_flag()
    coverage_gaps = expectations.source_coverage_findings()
    leaks = leakage_findings(package_dir)
    h_ok = all(
        sha256_of_content(corpus.DOCUMENTS[key].text) == sha for key, (_, sha) in NINE_P3_H.items()
    )
    v2_ok = all(
        sha256_of_content(corpus.DOCUMENTS[key].text) == sha
        for key, sha in V2_REGRESSION_TEXT.items()
    )
    gates = (
        Gate(
            name="manifest_matches_code",
            passed=sealed_manifest is not None and dict(sealed_manifest) == manifest,
            detail="sealed manifest.json == manifest recomputed from the code"
            if sealed_manifest is not None
            else "manifest.json missing",
        ),
        Gate(
            name="expectations_match_code",
            passed=sealed_expectations is not None
            and canonical_sha256(dict(sealed_expectations)) == expectations.expectations_sha256(),
            detail=f"expectations sha256 {expectations.expectations_sha256()}",
        ),
        Gate(
            name="seal_commit_adds_exactly_the_sealed_files",
            passed=sorted(git.head_added_files) == sorted(sealed)
            and sorted(git.head_changed_files) == sorted(sealed),
            detail=f"HEAD {git.head_sha} adds {sorted(git.head_added_files)}",
        ),
        Gate(
            name="seal_parent_is_the_harness",
            passed=sealed_manifest is not None
            and git.head_parent_sha == sealed_manifest.get("harness_sha"),
            detail=f"HEAD parent {git.head_parent_sha}",
        ),
        Gate(name="worktree_clean", passed=git.worktree_clean, detail="git status --porcelain"),
        Gate(
            name="canonical_facet_policy_identity",
            passed=CANONICAL_FACET_POLICY_VERSION == protocol.POLICY_VERSION_FROZEN
            and computed_prompt
            == CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256
            == protocol.PROMPT_SHA256_FROZEN
            and concern_output_schema_sha256()
            == CONCERN_OUTPUT_SCHEMA_SHA256
            == protocol.OUTPUT_SCHEMA_SHA256_FROZEN
            and semantic_output_schema_sha256()
            == SEMANTIC_OUTPUT_SCHEMA_SHA256
            == protocol.HISTORICAL_OUTPUT_SCHEMA_SHA256
            and reasoner_class is not None
            and getattr(reasoner_class, "policy_version", None) == protocol.POLICY_VERSION_FROZEN
            and getattr(reasoner_class, "system_instruction", None)
            == CANONICAL_FACET_SYSTEM_INSTRUCTION
            and getattr(getattr(reasoner_class, "draft_payload", None), "__name__", None)
            == protocol.OUTPUT_SCHEMA_FROZEN,
            detail=f"{CANONICAL_FACET_POLICY_VERSION} {protocol.REASONER_CLASS_FROZEN} "
            f"prompt {computed_prompt} contract {protocol.OUTPUT_SCHEMA_FROZEN}",
        ),
        Gate(
            name="canonical_facet_admission",
            passed=protocol.CANONICAL_FACETS is True and admission_flag is True,
            detail=f"every ledger governor runs AdmissionPolicy(canonical_facets={admission_flag})",
        ),
        Gate(
            name="source_coverage_complete",
            passed=not coverage_gaps,
            detail="; ".join(coverage_gaps) or "every sentence of every document accounted for",
        ),
        Gate(
            name="grpc_dns_resolver_native",
            passed=grpc_dns_resolver == protocol.GRPC_DNS_RESOLVER_FROZEN,
            detail=f"observed {grpc_dns_resolver!r}",
        ),
        Gate(
            name="single_use",
            passed=not raw_present,
            detail=f"raw artifacts present: {list(raw_present)}" if raw_present else "unconsumed",
        ),
        Gate(name="leakage", passed=not leaks, detail="; ".join(leaks) or "clean"),
        Gate(name="nine_p3_h_bytes", passed=h_ok, detail="orion H-T1/H-T9 == sealed 9P3 bytes"),
        Gate(
            name="v2_regression_bytes",
            passed=v2_ok,
            detail="core LATE-T1/LATE-NOTE-T2 == sealed v2 bytes",
        ),
    )
    assert tuple(g.name for g in gates) == GATE_NAMES
    return gates
