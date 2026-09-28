"""Seal and preflight of locus validation v2 (design §10).

``build_manifest`` and ``expectations_document`` are the two sealed files, written once by
``prepare`` into an empty directory and committed as the seal. Preflight recomputes both
from the code and refuses any difference, then checks the git seal shape, a clean tree,
the policy identity, the resolver, single use (no raw artifact), leakage and the 9P3
locus-H bytes. Every gate is a pure function of injected facts, so each is testable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from foundry.adapters.semantics.xai_reasoner import (
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
)
from foundry.domain.common import FrozenModel
from foundry.domain.evidence import sha256_of_content
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v2 import corpus, expectations, protocol

__all__ = [
    "GATE_NAMES",
    "NINE_P3_H",
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
    "C9",
    "locus",
)
"""Words that name the answer key. None may appear in a model-visible document."""

REQUEST_PATH_MODULES: Final = ("corpus", "world", "recording", "runner", "protocol")

GATE_NAMES: Final = (
    "manifest_matches_code",
    "expectations_match_code",
    "seal_commit_adds_exactly_the_sealed_files",
    "seal_parent_is_the_harness",
    "worktree_clean",
    "locus_policy_identity",
    "grpc_dns_resolver_native",
    "single_use",
    "leakage",
    "nine_p3_h_bytes",
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


def build_manifest(*, harness_sha: str) -> dict[str, Any]:
    spec = Path(protocol.DESIGN_SPEC_PATH)
    spec_sha = hashlib.sha256(spec.read_bytes()).hexdigest() if spec.exists() else "MISSING"
    return {
        "experiment_version": protocol.EXPERIMENT_VERSION,
        "artifact_format_version": protocol.ARTIFACT_FORMAT_VERSION,
        "design_spec_path": protocol.DESIGN_SPEC_PATH,
        "design_spec_sha256": spec_sha,
        "harness_sha": harness_sha,
        "predecessor": {
            "experiment": protocol.PREDECESSOR_EXPERIMENT,
            "adjudication_sha": protocol.PREDECESSOR_ADJUDICATION_SHA,
        },
        "provider": protocol.PROVIDER,
        "model": protocol.MODEL,
        "reasoning_effort": protocol.REASONING_EFFORT,
        "grpc_dns_resolver": protocol.GRPC_DNS_RESOLVER_FROZEN,
        "policy_version": protocol.POLICY_VERSION_FROZEN,
        "prompt_sha256": protocol.PROMPT_SHA256_FROZEN,
        "output_schema_sha256": protocol.OUTPUT_SCHEMA_SHA256_FROZEN,
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
        "corpus": corpus.corpus_record(),
        "corpus_sha256": corpus.corpus_sha256(),
        "expectations_sha256": expectations.expectations_sha256(),
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
    for world in corpus.SEED_WORLDS.values():
        for address in world:
            shown = " ".join([address.subject, address.facet, *(c.text for c in address.claims)])
            for word in ANSWER_KEY_VOCABULARY:
                if word.lower() in shown.lower():
                    findings.append(f"seed address {address.key} contains {word!r}")
    for module in REQUEST_PATH_MODULES:
        source = (package_dir / f"{module}.py").read_text()
        if "expectations" in source.replace("# ", "") and "import" in source:
            for line in source.splitlines():
                if line.startswith(("from ", "import ")) and "expectations" in line:
                    findings.append(f"request-path module {module} imports the answer key")
    return tuple(findings)


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
        build_manifest(harness_sha=str(sealed_manifest.get("harness_sha")))
        if sealed_manifest is not None
        else None
    )
    computed_prompt = hashlib.sha256(LOCUS_SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    leaks = leakage_findings(package_dir)
    h_ok = all(
        sha256_of_content(corpus.DOCUMENTS[key].text) == sha for key, (_, sha) in NINE_P3_H.items()
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
            name="locus_policy_identity",
            passed=LOCUS_POLICY_VERSION == protocol.POLICY_VERSION_FROZEN
            and computed_prompt == LOCUS_SYSTEM_INSTRUCTION_SHA256 == protocol.PROMPT_SHA256_FROZEN
            and SEMANTIC_OUTPUT_SCHEMA_SHA256 == protocol.OUTPUT_SCHEMA_SHA256_FROZEN,
            detail=f"{LOCUS_POLICY_VERSION} prompt {computed_prompt}",
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
    )
    assert tuple(g.name for g in gates) == GATE_NAMES
    return gates
