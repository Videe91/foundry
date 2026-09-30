"""Seal and preflight of locus validation v6 (design §10).

``build_manifest`` and ``expectations_document`` are the two sealed files, written once by
``prepare`` into an empty directory and committed as the seal. The manifest freezes the design,
the grain decision, the corpus (and the dense density), the source-coverage map, the answer
key, the adjudication questions, the scoring rules (the sources of the evaluator, the
adjudication, the answer key and the scripted authority), the model identity and
configuration, the policy, prompt, output contract and correction law, the admission
configuration (canonical facets and correction sets) and the correction-set authority protocol
with its actor and branches. Preflight recomputes both files from the code and refuses any
difference, then checks the seal shape, a clean tree, every identity, the resolver, single use,
leakage and the regression bytes. Every gate is a pure function of injected facts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    ACCOUNTED_OUTPUT_SCHEMA_SHA256,
    CORRECTION_SET_POLICY_VERSION,
    CORRECTION_SET_SYSTEM_INSTRUCTION,
    CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    accounted_output_schema_sha256,
    semantic_output_schema_sha256,
)
from foundry.application.authority_routing import AUTHORITY_ROUTING_V2
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import CorrectionSetDecidedPayload
from foundry.domain.evidence import sha256_of_content
from foundry.domain.semantic_identity import CANONICAL_FACET_PREFIX
from foundry.domain.structural_refusal import REPROPOSE_MODES, ExecutionMode
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v5 import corpus as v5_corpus
from foundry.experiments.locus_validation_v5 import seal as v5_seal
from foundry.experiments.locus_validation_v6 import corpus, expectations, protocol, world

__all__ = [
    "ANSWER_KEY_VOCABULARY",
    "GATE_NAMES",
    "SCORING_SOURCES",
    "Gate",
    "GitFacts",
    "build_manifest",
    "dense_density",
    "leakage_findings",
    "preflight_gates",
    "sealed_json",
]

SCORING_SOURCES: Final = ("evaluation.py", "adjudication.py", "expectations.py", "authority.py")
"""The scoring rules and the scripted authority, frozen by the digest of their source."""

ANSWER_KEY_VOCABULARY: Final = (
    *v5_seal.ANSWER_KEY_VOCABULARY,
    "correction set",
    "authority",
    "cardinality",
    "n:m",
    "held-out",
    "oracle",
    "suppress",
    "reopen",
)
"""Words that name the answer key or the policy's own terms. None may appear in a
model-visible document or seed address."""

REQUEST_PATH_MODULES: Final = ("corpus", "world", "recording", "runner", "protocol", "authority")

GATE_NAMES: Final = (
    "manifest_matches_code",
    "expectations_match_code",
    "seal_commit_adds_exactly_the_sealed_files",
    "seal_parent_is_the_harness",
    "worktree_clean",
    "policy_identity",
    "experiment_mode_single_attempt",
    "canonical_facet_admission",
    "correction_set_admission",
    "authority_protocol",
    "source_coverage_complete",
    "dense_density",
    "grpc_dns_resolver_native",
    "single_use",
    "leakage",
    "nine_p3_h_bytes",
    "v5_regression_bytes",
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


def dense_density() -> dict[str, int]:
    t1 = corpus.SEED_DOCUMENTS["dense"]
    keys = {d.key for d in t1}
    return {
        "documents": len(t1),
        "characters": sum(len(d.text) for d in t1),
        "propositions": sum(1 for p in expectations.PROPOSITIONS if p.document in keys),
        "concerns": sum(1 for c in expectations.CONCERNS if c.ledger == "dense"),
    }


def _v5_regression_text() -> dict[str, str]:
    return {key: sha256_of_content(corpus.DOCUMENTS[key].text) for key in sorted(corpus.V5_REUSED)}


def build_manifest(*, harness_sha: str, package_dir: Path) -> dict[str, Any]:
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "artifact_format_version": protocol.ARTIFACT_FORMAT_VERSION,
        "design_spec_path": protocol.DESIGN_SPEC_PATH,
        "decision_records_sha256": {
            path: _file_sha(Path(path))
            for path in (protocol.GRAIN_DECISION_PATH, protocol.DESIGN_SPEC_PATH)
        },
        "harness_sha": harness_sha,
        "predecessor": protocol.PREDECESSOR_EXPERIMENT,
        "policy_commit": protocol.POLICY_COMMIT,
        "authority_commit": protocol.AUTHORITY_COMMIT,
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
        "correction_law": protocol.CORRECTION_LAW_FROZEN,
        "execution_mode": protocol.EXECUTION_MODE.value,
        "admission": {
            "canonical_facets": protocol.CANONICAL_FACETS,
            "correction_sets": protocol.CORRECTION_SETS,
        },
        "canonical_facet_prefix": CANONICAL_FACET_PREFIX,
        "authority": {
            "protocol": protocol.AUTHORITY_PROTOCOL,
            "actor": protocol.ARCHITECT,
            "authority_record_id": world.ARCHITECT_AUTHORITY_ID,
            "branched_ledger": protocol.BRANCHED,
            "branches": list(protocol.BRANCHES),
            "rule": "after dense T2 the actor decides every PENDING correction set listed by "
            "list_authority_work, as of the listing's sequence: AGREE in branch AGREE, DECLINE "
            "in branch DECLINE; then each branch assimilates the same T3 delta",
        },
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
        "dense_density": dense_density(),
        "nine_p3_h_evidence": {
            k: {"id": v[0], "sha256": v[1]} for k, v in v5_seal.NINE_P3_H.items()
        },
        "v5_regression_text_sha256": _v5_regression_text(),
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


def _governor_policies() -> dict[str, AdmissionPolicy | None]:
    """What every ledger governor actually runs with (read from fresh governors)."""
    out: dict[str, AdmissionPolicy | None] = {}
    for ledger in protocol.LEDGERS:
        _, governor = world.fresh_governor(
            ledger, clock=lambda: protocol.OBSERVED_AT, id_factory=lambda prefix: f"{prefix}-GATE"
        )
        policy = getattr(governor, "_policy", None)
        out[ledger] = policy if isinstance(policy, AdmissionPolicy) else None
    return out


def _policy_identity_ok() -> tuple[bool, str]:
    computed = hashlib.sha256(CORRECTION_SET_SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    cls = getattr(xai_reasoner, protocol.REASONER_CLASS_FROZEN, None)
    ok = (
        CORRECTION_SET_POLICY_VERSION == protocol.POLICY_VERSION_FROZEN
        and computed == CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256 == protocol.PROMPT_SHA256_FROZEN
        and accounted_output_schema_sha256()
        == ACCOUNTED_OUTPUT_SCHEMA_SHA256
        == protocol.OUTPUT_SCHEMA_SHA256_FROZEN
        and semantic_output_schema_sha256()
        == SEMANTIC_OUTPUT_SCHEMA_SHA256
        == protocol.HISTORICAL_OUTPUT_SCHEMA_SHA256
        and cls is not None
        and getattr(cls, "policy_version", None) == protocol.POLICY_VERSION_FROZEN
        and getattr(cls, "system_instruction", None) == CORRECTION_SET_SYSTEM_INSTRUCTION
        and getattr(getattr(cls, "draft_payload", None), "__name__", None)
        == protocol.OUTPUT_SCHEMA_FROZEN
        and getattr(cls, "correction_law", None) == protocol.CORRECTION_LAW_FROZEN
    )
    law = getattr(cls, "correction_law", None)
    return ok, f"{protocol.POLICY_VERSION_FROZEN} prompt {computed} law {law}"


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
    identity_ok, identity_detail = _policy_identity_ok()
    policies = _governor_policies()
    coverage_gaps = expectations.source_coverage_findings()
    leaks = leakage_findings(package_dir)
    density = dense_density()
    h_ok = all(
        sha256_of_content(corpus.DOCUMENTS[key].text) == sha
        for key, (_, sha) in v5_seal.NINE_P3_H.items()
    )
    v5_ok = all(
        corpus.DOCUMENTS[key].text == v5_corpus.DOCUMENTS[old].text
        for key, old in corpus.V5_REUSED.items()
    )
    decided_literal = CorrectionSetDecidedPayload.model_fields["authority_protocol"].default
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
        Gate(name="policy_identity", passed=identity_ok, detail=identity_detail),
        Gate(
            name="experiment_mode_single_attempt",
            passed=protocol.EXECUTION_MODE is ExecutionMode.EXPERIMENT
            and protocol.EXECUTION_MODE not in REPROPOSE_MODES,
            detail=f"mode {protocol.EXECUTION_MODE.value}",
        ),
        Gate(
            name="canonical_facet_admission",
            passed=protocol.CANONICAL_FACETS is True
            and all(p is not None and p.canonical_facets for p in policies.values()),
            detail="every ledger governor runs canonical_facets=True",
        ),
        Gate(
            name="correction_set_admission",
            passed=protocol.CORRECTION_SETS is True
            and all(p is not None and p.correction_sets for p in policies.values()),
            detail="every ledger governor runs correction_sets=True (this validation only)",
        ),
        Gate(
            name="authority_protocol",
            passed=AUTHORITY_ROUTING_V2 == decided_literal == protocol.AUTHORITY_PROTOCOL,
            detail=f"{AUTHORITY_ROUTING_V2} / {decided_literal}",
        ),
        Gate(
            name="source_coverage_complete",
            passed=not coverage_gaps,
            detail="; ".join(coverage_gaps) or "every sentence of every document accounted for",
        ),
        Gate(
            name="dense_density",
            passed=density["documents"] >= 12
            and density["characters"] >= 8000
            and density["propositions"] >= 30
            and density["concerns"] < density["documents"],
            detail=json.dumps(density, sort_keys=True),
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
            name="v5_regression_bytes",
            passed=v5_ok,
            detail="every carried document == validation v5's sealed text",
        ),
    )
    assert tuple(g.name for g in gates) == GATE_NAMES
    return gates
