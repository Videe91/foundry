"""Seal and preflight of the IE2 + IE3 long-horizon experiment (design §6, §18).

``build_manifest`` and ``expectations_document`` are the two sealed files, written once by
``prepare`` into an empty directory and committed as the seal (a commit adding exactly those
two files, whose parent is the harness). The manifest freezes the design, the corpus (with
its proof of identity to 9P3), the answer key and its digests, the adjudication questions,
the scoring sources, both layers' model and configuration identities, the IE3 certificate
identity and the budgets. Preflight recomputes both files from the code and refuses any
difference, then checks the git seal shape, a clean tree, both layers' identities, that the
IE3 certificate reads CURRENT, single-attempt modes, canonical facets, source coverage, the
historical corpus, the resolver, single use and leakage. Every gate is a pure function of
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
    ACCOUNTED_OUTPUT_SCHEMA_SHA256,
    REPROPOSAL_POLICY_VERSION,
    REPROPOSAL_SYSTEM_INSTRUCTION,
    REPROPOSAL_SYSTEM_INSTRUCTION_SHA256,
    accounted_output_schema_sha256,
)
from foundry.application.intent_graph_synthesis import CERTIFIED_GRAPH_REPROPOSAL_POLICY_VERSIONS
from foundry.domain.common import FrozenModel
from foundry.domain.structural_refusal import REPROPOSE_MODES, ExecutionMode
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v5.recording import (
    EXPECTED_IDENTITY as V5_EXPECTED_IDENTITY,
)
from foundry.experiments.long_horizon_ie2_ie3 import corpus, expectations, protocol
from foundry.experiments.long_horizon_ie2_ie3.recording import (
    EXPECTED_IE2_IDENTITY,
    IdentityDrift,
    require_ie3_identity,
)

__all__ = [
    "GATE_NAMES",
    "SCORING_SOURCES",
    "Gate",
    "GitFacts",
    "build_manifest",
    "leakage_findings",
    "preflight_gates",
    "sealed_json",
]

SCORING_SOURCES: Final = ("evaluation.py", "adjudication.py", "expectations.py")
REQUEST_PATH_MODULES: Final = ("corpus", "recording", "runner", "ie3_runtime", "protocol")

GATE_NAMES: Final = (
    "manifest_matches_code",
    "expectations_match_code",
    "seal_commit_adds_exactly_the_sealed_files",
    "seal_parent_is_the_harness",
    "worktree_clean",
    "root_staleness_boundary_present",
    "ie2_policy_identity",
    "ie3_runtime_identity",
    "ie3_certificate_current",
    "single_attempt_modes",
    "canonical_facet_admission",
    "source_coverage_complete",
    "historical_corpus_identical",
    "grpc_dns_resolver_native",
    "single_use",
    "leakage",
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
    boundary_commit_is_ancestor: bool


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def build_manifest(*, harness_sha: str, package_dir: Path) -> dict[str, Any]:
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "artifact_format_version": protocol.ARTIFACT_FORMAT_VERSION,
        "design_spec_path": protocol.DESIGN_SPEC_PATH,
        "design_spec_sha256": _file_sha(Path(protocol.DESIGN_SPEC_PATH)),
        "harness_sha": harness_sha,
        "historical_experiment": protocol.HISTORICAL_EXPERIMENT,
        "historical_artifact_dir": protocol.HISTORICAL_ARTIFACT_DIR,
        "project_id": protocol.PROJECT_ID,
        "scope": corpus.SCOPE,
        "execution_mode": protocol.EXECUTION_MODE.value,
        "ie2": {
            "provider": protocol.IE2_PROVIDER,
            "model": protocol.IE2_MODEL,
            "reasoning_effort": protocol.IE2_REASONING_EFFORT,
            "grpc_dns_resolver": protocol.GRPC_DNS_RESOLVER_FROZEN,
            "policy_version": protocol.IE2_POLICY_VERSION,
            "reasoner_class": protocol.IE2_REASONER_CLASS,
            "prompt_sha256": protocol.IE2_PROMPT_SHA256,
            "output_schema": protocol.IE2_OUTPUT_SCHEMA,
            "output_schema_sha256": protocol.IE2_OUTPUT_SCHEMA_SHA256,
            "canonical_facets": protocol.CANONICAL_FACETS,
            "validation": protocol.IE2_VALIDATION,
        },
        "ie3": {
            "provider": protocol.IE3_PROVIDER,
            "model": protocol.IE3_MODEL,
            "reasoning_effort": protocol.IE3_REASONING_EFFORT,
            "reasoning_mode": protocol.IE3_REASONING_MODE,
            "output_guard": protocol.IE3_OUTPUT_GUARD,
            "timeout_seconds": protocol.IE3_TIMEOUT_SECONDS,
            "task": protocol.IE3_TASK,
            "policy_id": protocol.IE3_POLICY_ID,
            "policy_version": protocol.IE3_POLICY_VERSION,
            "prompt_sha256": protocol.IE3_PROMPT_SHA256,
            "canonical_schema_sha256": protocol.IE3_CANONICAL_SCHEMA_SHA256,
            "wire_schema_sha256": protocol.IE3_WIRE_SCHEMA_SHA256,
            "wire_schema_compiler": protocol.IE3_WIRE_SCHEMA_COMPILER,
            "exam_version": protocol.IE3_EXAM_VERSION,
            "exam_sha256": protocol.IE3_EXAM_SHA256,
            "certificate_path": protocol.IE3_CERTIFICATE_PATH,
            "certificate_sha256": protocol.IE3_CERTIFICATE_SHA256,
            "root_staleness_boundary_commit": protocol.ROOT_STALENESS_BOUNDARY_COMMIT,
        },
        "budgets": {
            "ie2_calls_per_turn": protocol.IE2_CALLS_PER_TURN,
            "ie3_calls_per_turn": protocol.IE3_CALLS_PER_TURN,
            "max_ie2_calls": protocol.MAX_IE2_CALLS,
            "max_ie3_calls": protocol.MAX_IE3_CALLS,
            "max_ie2_cost_usd": protocol.MAX_IE2_COST_USD,
            "retries": 0,
            "reproposals": 0,
            "judge_calls": 0,
        },
        "corpus": corpus.corpus_record(),
        "expectations_sha256": expectations.expectations_sha256(),
        "adjudication_questions_sha256": expectations.adjudication_questions_sha256(),
        "adjudication_question_count": len(expectations.ADJUDICATION_QUESTIONS),
        "scoring_sources_sha256": {name: _file_sha(package_dir / name) for name in SCORING_SOURCES},
        "historical_comparison": {
            "F": "14/15, failed C09",
            "A": "14/15, failed C09",
            "R": "1/15, failed from C03 onward",
            "rule": "reported beside this run, never rescored; the architecture, contracts and "
            "components have changed, so it is not a model benchmark",
        },
    }


def sealed_json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def leakage_findings(package_dir: Path) -> tuple[str, ...]:
    findings: list[str] = []
    for module in REQUEST_PATH_MODULES:
        source = (package_dir / f"{module}.py").read_text()
        for line in source.splitlines():
            if line.startswith(("from ", "import ")) and any(
                word in line
                for word in (
                    "expectations",
                    "adjudication",
                    "evaluation",
                    "long_horizon_bounded.expectations",
                )
            ):
                findings.append(f"request-path module {module} imports the answer key: {line}")
    return tuple(findings)


def _governor_admission_flag() -> bool:
    from foundry.adapters.memory.event_store import InMemoryEventStore
    from foundry.application.semantic_governance import SemanticGovernor
    from foundry.domain.admission import AdmissionPolicy

    governor = SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=protocol.PROJECT_ID,
        policy=AdmissionPolicy(canonical_facets=protocol.CANONICAL_FACETS),
        clock=lambda: protocol.OBSERVED_AT,
        id_factory=lambda prefix: f"{prefix}-GATE",
    )
    policy = getattr(governor, "_policy", None)
    return isinstance(policy, AdmissionPolicy) and policy.canonical_facets


def preflight_gates(
    *,
    sealed_manifest: Mapping[str, Any] | None,
    sealed_expectations: Mapping[str, Any] | None,
    git: GitFacts,
    historical_manifest: Mapping[str, Any],
    certificate_sha256: str,
    certificate_standing: str,
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
    computed_prompt = hashlib.sha256(REPROPOSAL_SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    reasoner_class = getattr(xai_reasoner, protocol.IE2_REASONER_CLASS, None)
    try:
        require_ie3_identity()
        ie3_detail, ie3_ok = "runtime-v4 policy, prompt, schemas and wire == certificate", True
    except IdentityDrift as drift:
        ie3_detail, ie3_ok = str(drift), False
    coverage_gaps = expectations.source_coverage_findings()
    corpus_findings = corpus.historical_corpus_findings(historical_manifest)
    leaks = leakage_findings(package_dir)
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
            name="root_staleness_boundary_present",
            passed=git.boundary_commit_is_ancestor,
            detail=f"{protocol.ROOT_STALENESS_BOUNDARY_COMMIT} is an ancestor of HEAD",
        ),
        Gate(
            name="ie2_policy_identity",
            passed=REPROPOSAL_POLICY_VERSION == protocol.IE2_POLICY_VERSION
            and computed_prompt
            == REPROPOSAL_SYSTEM_INSTRUCTION_SHA256
            == protocol.IE2_PROMPT_SHA256
            and accounted_output_schema_sha256()
            == ACCOUNTED_OUTPUT_SCHEMA_SHA256
            == protocol.IE2_OUTPUT_SCHEMA_SHA256
            and reasoner_class is not None
            and getattr(reasoner_class, "policy_version", None) == protocol.IE2_POLICY_VERSION
            and V5_EXPECTED_IDENTITY == EXPECTED_IE2_IDENTITY,
            detail=f"{REPROPOSAL_POLICY_VERSION} prompt {computed_prompt}",
        ),
        Gate(name="ie3_runtime_identity", passed=ie3_ok, detail=ie3_detail),
        Gate(
            name="ie3_certificate_current",
            passed=certificate_sha256 == protocol.IE3_CERTIFICATE_SHA256
            and certificate_standing == "CURRENT",
            detail=f"certificate {certificate_sha256[:12]} standing {certificate_standing}",
        ),
        Gate(
            name="single_attempt_modes",
            passed=protocol.EXECUTION_MODE is ExecutionMode.EXPERIMENT
            and protocol.EXECUTION_MODE not in REPROPOSE_MODES
            and not CERTIFIED_GRAPH_REPROPOSAL_POLICY_VERSIONS,
            detail=f"mode {protocol.EXECUTION_MODE.value}; IE3 re-proposal policies "
            f"{sorted(CERTIFIED_GRAPH_REPROPOSAL_POLICY_VERSIONS)}",
        ),
        Gate(
            name="canonical_facet_admission",
            passed=protocol.CANONICAL_FACETS is True and _governor_admission_flag(),
            detail="the governor runs AdmissionPolicy(canonical_facets=True)",
        ),
        Gate(
            name="source_coverage_complete",
            passed=not coverage_gaps,
            detail="; ".join(coverage_gaps) or "every sentence of every section accounted for",
        ),
        Gate(
            name="historical_corpus_identical",
            passed=not corpus_findings,
            detail="; ".join(corpus_findings[:5]) or "192 items == sealed 9P3 corpus",
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
    )
    assert tuple(g.name for g in gates) == GATE_NAMES
    return gates
