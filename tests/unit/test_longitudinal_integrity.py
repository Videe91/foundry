"""Experiment integrity gates for the 9P longitudinal dogfood (spec §28, §31, §32 13–16).

Every gate is proven in both directions: a frozen, clean, correctly configured run
passes it; the specific defect it exists to catch fails it. Gates never raise — a gate
that cannot be evaluated is a failed gate with the reason in ``detail``.

No network, no repository access, no xAI client: git is a fake, the timeline is loaded
from fake blobs, and the socket guard refuses any connection attempt.
"""

from __future__ import annotations

import hashlib
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics.xai_reasoner import (
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    semantic_output_schema_sha256,
)
from foundry.experiments.longitudinal import integrity
from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    LOCKED_CEILINGS,
    TRACKED_LOCI,
)
from foundry.experiments.longitudinal.integrity import (
    GATE_NAMES,
    GateResult,
    RunConfig,
    all_passed,
    preflight,
)
from foundry.experiments.longitudinal.timeline import (
    VersionedEvidence,
    evidence_hashes,
    load_timeline,
)

T0 = datetime(2026, 9, 11, tzinfo=UTC)
PROJECT = "PROJ-9P"
FROZEN_SHA = "f" * 40
MANIFEST_SHA = "a" * 64

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --------------------------------------------------------------------------- fakes


class FakeGit:
    """Serves bytes for exact ``(commit, path)`` pairs; anything else does not exist."""

    def __init__(self, blobs: dict[tuple[str, str], bytes]) -> None:
        self._blobs = blobs

    def blob(self, sha: str, path: str) -> bytes:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return self._blobs[(sha, path)]

    def blob_sha(self, sha: str, path: str) -> str:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return hashlib.sha1(b"blob " + self._blobs[(sha, path)]).hexdigest()


class FakeGitCli:
    """The minimal CLI surface the gates need: HEAD sha and ``status --short`` output."""

    def __init__(
        self,
        *,
        head: str = FROZEN_SHA,
        dirty: str = "",
        head_error: Exception | None = None,
        dirty_error: Exception | None = None,
    ) -> None:
        self._head = head
        self._dirty = dirty
        self._head_error = head_error
        self._dirty_error = dirty_error

    def head(self) -> str:
        if self._head_error is not None:
            raise self._head_error
        return self._head

    def dirty(self) -> str:
        if self._dirty_error is not None:
            raise self._dirty_error
        return self._dirty


def _blobs(**overrides: bytes) -> dict[tuple[str, str], bytes]:
    base = {
        (T1, CONSTITUTION): b"constitution v1\n",
        (T1, SPEC): b"spec v1\n",
        (T2, SPEC): b"spec v2\n",
        (T3, REDUCER): b"reducer v1\n",
        (T3, IDENTITY): b"identity v1\n",
        (T4, REDUCER): b"reducer v2\n",
        (T4, SPEC): b"spec v3\n",
    }
    keyed = {
        "t1_constitution": (T1, CONSTITUTION),
        "t1_spec": (T1, SPEC),
        "t2_spec": (T2, SPEC),
        "t3_reducer": (T3, REDUCER),
        "t3_identity": (T3, IDENTITY),
        "t4_reducer": (T4, REDUCER),
        "t4_spec": (T4, SPEC),
    }
    for name, content in overrides.items():
        base[keyed[name]] = content
    return base


def _observed_at(t: int) -> datetime:
    return T0 + timedelta(days=t)


def _load(blobs: dict[tuple[str, str], bytes]) -> tuple[VersionedEvidence, ...]:
    return load_timeline(FakeGit(blobs), project_id=PROJECT, observed_at_for=_observed_at)


def _config(**overrides: Any) -> RunConfig:
    base: dict[str, Any] = {
        "max_frontier_calls": 16,
        "max_cost_usd": 8.0,
        "max_human_authorizations": 3,
        "max_judge_calls": 0,
        "provider": "xai",
        "model": "grok-4.6",
        "reasoning_effort": "high",
    }
    return RunConfig(**{**base, **overrides})


@pytest.fixture
def timeline() -> tuple[VersionedEvidence, ...]:
    return _load(_blobs())


@pytest.fixture
def ok(timeline: tuple[VersionedEvidence, ...]) -> dict[str, Any]:
    """Keyword arguments for a run that passes every gate."""
    return {
        "git": FakeGitCli(),
        "frozen_sha": FROZEN_SHA,
        "manifest_sha": MANIFEST_SHA,
        "expected_manifest_sha": MANIFEST_SHA,
        "prompt_sha": hashlib.sha256(SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest(),
        "expected_prompt_sha": SYSTEM_INSTRUCTION_SHA256,
        "schema_sha": semantic_output_schema_sha256(),
        "expected_schema_sha": SEMANTIC_OUTPUT_SCHEMA_SHA256,
        "expected_evidence_hashes": evidence_hashes(timeline),
        "timeline": timeline,
        "config": _config(),
    }


def _gate(results: tuple[GateResult, ...], name: str) -> GateResult:
    matches = [r for r in results if r.name == name]
    assert len(matches) == 1, f"expected exactly one {name!r} gate, got {len(matches)}"
    return matches[0]


def _only_failed(results: tuple[GateResult, ...], *names: str) -> None:
    assert {r.name for r in results if not r.passed} == set(names)


# --------------------------------------------------------------------------- shape


def test_all_gates_pass_on_a_frozen_clean_correctly_configured_run(ok: dict[str, Any]) -> None:
    results = preflight(**ok)
    assert all(r.passed for r in results), [r for r in results if not r.passed]
    assert all_passed(results)


def test_gates_are_the_fourteen_planned_gates_in_deterministic_order(ok: dict[str, Any]) -> None:
    assert GATE_NAMES == (
        "head_equals_frozen_sha",
        "worktree_clean",
        "manifest_hash_frozen",
        "prompt_hash_frozen",
        "output_schema_hash_frozen",
        "evidence_hashes_frozen",
        "call_ceiling_is_16",
        "cost_ceiling_is_8",
        "human_ceiling_is_3",
        "judge_calls_zero",
        "xai_retries_disabled",
        "no_tracked_locus_leakage",
        "persistent_delta_has_no_unchanged_evidence",
        "reconstruction_corpus_is_cumulative",
    )
    first = preflight(**ok)
    second = preflight(**ok)
    assert tuple(r.name for r in first) == GATE_NAMES
    assert first == second


def test_gate_result_is_frozen(ok: dict[str, Any]) -> None:
    result = preflight(**ok)[0]
    with pytest.raises(ValidationError):
        result.passed = False  # type: ignore[misc]


def test_run_config_is_frozen_and_rejects_unknown_fields() -> None:
    config = _config()
    with pytest.raises(ValidationError):
        config.max_frontier_calls = 17  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RunConfig(**{**config.model_dump(), "rerolls": 1})


def test_preflight_never_raises_when_a_gate_cannot_be_evaluated(ok: dict[str, Any]) -> None:
    ok["git"] = FakeGitCli(
        head_error=RuntimeError("git rev-parse exploded"),
        dirty_error=OSError("git status exploded"),
    )
    results = preflight(**ok)
    assert tuple(r.name for r in results) == GATE_NAMES
    _only_failed(results, "head_equals_frozen_sha", "worktree_clean")
    assert "git rev-parse exploded" in _gate(results, "head_equals_frozen_sha").detail
    assert "git status exploded" in _gate(results, "worktree_clean").detail


# --------------------------------------------------------------------------- git


def test_head_equals_frozen_sha(ok: dict[str, Any]) -> None:
    assert _gate(preflight(**ok), "head_equals_frozen_sha").passed

    ok["git"] = FakeGitCli(head="0" * 40)
    results = preflight(**ok)
    _only_failed(results, "head_equals_frozen_sha")
    gate = _gate(results, "head_equals_frozen_sha")
    assert "0" * 40 in gate.detail
    assert FROZEN_SHA in gate.detail


def test_worktree_clean(ok: dict[str, Any]) -> None:
    assert _gate(preflight(**ok), "worktree_clean").passed

    ok["git"] = FakeGitCli(dirty=" M src/foundry/experiments/longitudinal/integrity.py")
    results = preflight(**ok)
    _only_failed(results, "worktree_clean")
    assert "integrity.py" in _gate(results, "worktree_clean").detail


# --------------------------------------------------------------------------- hashes


def test_manifest_hash_frozen(ok: dict[str, Any]) -> None:
    assert _gate(preflight(**ok), "manifest_hash_frozen").passed

    ok["manifest_sha"] = "b" * 64
    results = preflight(**ok)
    _only_failed(results, "manifest_hash_frozen")
    assert "b" * 64 in _gate(results, "manifest_hash_frozen").detail


def test_prompt_hash_frozen(ok: dict[str, Any]) -> None:
    assert _gate(preflight(**ok), "prompt_hash_frozen").passed

    ok["prompt_sha"] = hashlib.sha256(b"an edited system instruction").hexdigest()
    results = preflight(**ok)
    _only_failed(results, "prompt_hash_frozen")
    assert SYSTEM_INSTRUCTION_SHA256 in _gate(results, "prompt_hash_frozen").detail


def test_output_schema_hash_frozen(ok: dict[str, Any]) -> None:
    gate = _gate(preflight(**ok), "output_schema_hash_frozen")
    assert gate.passed
    assert SEMANTIC_OUTPUT_SCHEMA_SHA256 in gate.detail

    # The runtime contract drifted from what was sealed (a variant, a field, a bound).
    ok["schema_sha"] = hashlib.sha256(b"an edited SemanticDraftPayload schema").hexdigest()
    results = preflight(**ok)
    _only_failed(results, "output_schema_hash_frozen")
    assert SEMANTIC_OUTPUT_SCHEMA_SHA256 in _gate(results, "output_schema_hash_frozen").detail

    # The sealed value was tampered with (or is absent) in manifest.json.
    ok["schema_sha"] = semantic_output_schema_sha256()
    ok["expected_schema_sha"] = ""
    results = preflight(**ok)
    _only_failed(results, "output_schema_hash_frozen")
    assert "''" in _gate(results, "output_schema_hash_frozen").detail


def test_evidence_hashes_frozen(ok: dict[str, Any]) -> None:
    assert _gate(preflight(**ok), "evidence_hashes_frozen").passed

    tampered = list(ok["expected_evidence_hashes"])
    tampered[2] = {**tampered[2], "content_sha256": "e" * 64}
    ok["expected_evidence_hashes"] = tuple(tampered)
    results = preflight(**ok)
    _only_failed(results, "evidence_hashes_frozen")
    assert "index 2" in _gate(results, "evidence_hashes_frozen").detail


def test_evidence_hashes_frozen_fails_when_the_timeline_bytes_changed(ok: dict[str, Any]) -> None:
    ok["timeline"] = _load(_blobs(t3_identity=b"identity v1 with a stray edit\n"))
    results = preflight(**ok)
    _only_failed(results, "evidence_hashes_frozen")


def test_evidence_hashes_frozen_fails_on_a_different_version_count(ok: dict[str, Any]) -> None:
    ok["expected_evidence_hashes"] = ok["expected_evidence_hashes"][:-1]
    results = preflight(**ok)
    _only_failed(results, "evidence_hashes_frozen")
    assert "7" in _gate(results, "evidence_hashes_frozen").detail
    assert "6" in _gate(results, "evidence_hashes_frozen").detail


# --------------------------------------------------------------------------- ceilings


def test_ceilings_are_the_locked_constants() -> None:
    assert LOCKED_CEILINGS["max_frontier_calls"] == 16
    assert LOCKED_CEILINGS["max_cost_usd"] == 8.0
    assert LOCKED_CEILINGS["max_human_authorizations"] == 3
    assert LOCKED_CEILINGS["max_judge_calls"] == 0


@pytest.mark.parametrize("value", [17, 15, 0])
def test_call_ceiling_is_16(ok: dict[str, Any], value: int) -> None:
    assert _gate(preflight(**ok), "call_ceiling_is_16").passed

    ok["config"] = _config(max_frontier_calls=value)
    results = preflight(**ok)
    _only_failed(results, "call_ceiling_is_16")
    assert str(value) in _gate(results, "call_ceiling_is_16").detail


@pytest.mark.parametrize("value", [8.01, 7.99, 16.0])
def test_cost_ceiling_is_8(ok: dict[str, Any], value: float) -> None:
    assert _gate(preflight(**ok), "cost_ceiling_is_8").passed

    ok["config"] = _config(max_cost_usd=value)
    results = preflight(**ok)
    _only_failed(results, "cost_ceiling_is_8")
    assert str(value) in _gate(results, "cost_ceiling_is_8").detail


@pytest.mark.parametrize("value", [4, 2])
def test_human_ceiling_is_3(ok: dict[str, Any], value: int) -> None:
    assert _gate(preflight(**ok), "human_ceiling_is_3").passed

    ok["config"] = _config(max_human_authorizations=value)
    results = preflight(**ok)
    _only_failed(results, "human_ceiling_is_3")
    assert str(value) in _gate(results, "human_ceiling_is_3").detail


def test_judge_calls_zero(ok: dict[str, Any]) -> None:
    assert _gate(preflight(**ok), "judge_calls_zero").passed

    ok["config"] = _config(max_judge_calls=1)
    results = preflight(**ok)
    _only_failed(results, "judge_calls_zero")
    assert "1" in _gate(results, "judge_calls_zero").detail


# --------------------------------------------------------------------------- adapter


def test_xai_retries_disabled_reads_the_adapter(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _gate(preflight(**ok), "xai_retries_disabled")
    assert gate.passed
    assert "grpc.enable_retries" in gate.detail

    monkeypatch.setattr(
        integrity,
        "_adapter_init_source",
        lambda: 'Client(api_key=api_key, channel_options=[("grpc.enable_retries", 3)])',
    )
    results = preflight(**ok)
    _only_failed(results, "xai_retries_disabled")

    monkeypatch.setattr(integrity, "_adapter_init_source", lambda: "Client(api_key=api_key)")
    results = preflight(**ok)
    _only_failed(results, "xai_retries_disabled")


def test_xai_retries_disabled_fails_when_the_adapter_source_is_unreadable(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unreadable() -> str:
        raise OSError("could not get source code")

    monkeypatch.setattr(integrity, "_adapter_init_source", _unreadable)
    results = preflight(**ok)
    _only_failed(results, "xai_retries_disabled")
    assert "could not get source code" in _gate(results, "xai_retries_disabled").detail


# --------------------------------------------------------------------------- leakage


def _with_item_update(
    timeline: tuple[VersionedEvidence, ...], evidence_id: str, **update: Any
) -> tuple[VersionedEvidence, ...]:
    """Replace one version's harness-authored item fields (ids, refs, scope); bytes untouched."""
    return tuple(
        v.model_copy(update={"item": v.item.model_copy(update=update)})
        if v.item.evidence_id == evidence_id
        else v
        for v in timeline
    )


def test_no_tracked_locus_leakage_passes_when_prompts_are_clean(ok: dict[str, Any]) -> None:
    gate = _gate(preflight(**ok), "no_tracked_locus_leakage")
    assert gate.passed
    # Every planned request skeleton was rendered: two arms × four T × two calls.
    assert "F/T1" in gate.detail
    assert "R/T4" in gate.detail


def test_leakage_gate_ignores_a_tracked_description_inside_evidence_content(
    ok: dict[str, Any],
) -> None:
    """Evidence bytes are immutable history the model must see (ruling R15-a)."""
    leaked = TRACKED_LOCI[1].description  # Track B
    ok["timeline"] = _load(
        _blobs(
            t2_spec=f"| 26 | **[9N LOCK]** {leaked.title()} | row |\n{leaked}\n".encode(),
            t1_constitution=f"{EXPECTATIONS[0].text}\n{EXPECTATIONS[0].id}\n".encode(),
        )
    )
    ok["expected_evidence_hashes"] = evidence_hashes(ok["timeline"])
    results = preflight(**ok)
    assert _gate(results, "no_tracked_locus_leakage").passed
    assert all_passed(results)


def test_leakage_gate_catches_a_tracked_description_in_a_request(ok: dict[str, Any]) -> None:
    leaked = TRACKED_LOCI[1].description  # Track B
    ok["timeline"] = _with_item_update(ok["timeline"], "EV-T2-01", source_ref=f"notes/{leaked}.md")

    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    gate = _gate(results, "no_tracked_locus_leakage")
    assert leaked in gate.detail
    assert "F/T2" in gate.detail
    assert "R/T2" in gate.detail
    assert "R/T3" in gate.detail  # the corpus carries the leak forward
    assert "T1" not in gate.detail.split("offenders")[-1]


def test_leakage_gate_catches_a_case_variant_of_a_description_in_harness_text(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    leaked = TRACKED_LOCI[1].description  # "validation framing"
    variant = leaked.title()  # "Validation Framing"
    assert variant != leaked
    monkeypatch.setattr(integrity, "SYSTEM_INSTRUCTION", SYSTEM_INSTRUCTION + f"\n{variant}")
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    gate = _gate(results, "no_tracked_locus_leakage")
    assert "system_instruction" in gate.detail
    assert leaked in gate.detail

    monkeypatch.setattr(integrity, "SYSTEM_INSTRUCTION", SYSTEM_INSTRUCTION)
    ok["timeline"] = _with_item_update(ok["timeline"], "EV-T3-02", scope=(leaked.upper(),))
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    assert "F/T3" in _gate(results, "no_tracked_locus_leakage").detail


def test_leakage_gate_catches_an_expectation_id_and_text(ok: dict[str, Any]) -> None:
    expectation = EXPECTATIONS[3]  # E4
    ok["timeline"] = _with_item_update(
        ok["timeline"], "EV-T4-01", artifact_ref=f"repo:see-{expectation.id}-for-the-rule"
    )
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    gate = _gate(results, "no_tracked_locus_leakage")
    assert expectation.id in gate.detail
    assert "F/T4" in gate.detail

    ok["timeline"] = _with_item_update(
        ok["timeline"], "EV-T1-01", source_ref=expectation.text.upper()
    )
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    detail = _gate(results, "no_tracked_locus_leakage").detail
    assert f"expectation {expectation.id} text" in detail


def test_leakage_gate_catches_a_backtick_free_description_and_text(ok: dict[str, Any]) -> None:
    """Ruling R15-b: markdown backticks in the sealed wording must not hide a leak."""
    track_c = TRACKED_LOCI[2].description
    assert "`" in track_c
    stripped = track_c.replace("`", "")
    ok["timeline"] = _with_item_update(ok["timeline"], "EV-T3-02", source_ref=f"notes/{stripped}")
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    gate = _gate(results, "no_tracked_locus_leakage")
    assert "locus C" in gate.detail
    assert "F/T3" in gate.detail

    e7 = next(e for e in EXPECTATIONS if e.id == "E7")
    assert "`" in e7.text
    ok["timeline"] = _with_item_update(
        ok["timeline"], "EV-T3-02", source_ref=e7.text.replace("`", "").upper()
    )
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    assert "expectation E7 text" in _gate(results, "no_tracked_locus_leakage").detail

    # The verbatim (backticked) wording matches both needles but is reported once.
    ok["timeline"] = _with_item_update(ok["timeline"], "EV-T3-02", source_ref=track_c)
    detail = _gate(preflight(**ok), "no_tracked_locus_leakage").detail
    assert detail.count("F/T3/call2: locus C") == 1


def test_leakage_gate_does_not_match_an_expectation_id_inside_a_longer_token(
    ok: dict[str, Any],
) -> None:
    ok["timeline"] = _with_item_update(
        ok["timeline"], "EV-T3-02", source_ref="PHASE1/E12x/CASE1/SE1"
    )
    assert _gate(preflight(**ok), "no_tracked_locus_leakage").passed


def test_leakage_gate_scans_the_system_instruction(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    leaked = TRACKED_LOCI[0].description  # Track A
    monkeypatch.setattr(
        integrity, "SYSTEM_INSTRUCTION", SYSTEM_INSTRUCTION + f"\nHint: look for {leaked}."
    )
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    gate = _gate(results, "no_tracked_locus_leakage")
    assert "system_instruction" in gate.detail
    assert leaked in gate.detail


def test_leakage_skeletons_exclude_evidence_bytes_but_keep_structure(ok: dict[str, Any]) -> None:
    skeletons = integrity._request_skeletons(ok["timeline"])
    labels = [label for label, _ in skeletons]
    assert labels[0] == "F/T1/call1[constitution]"
    assert "R/T4/call2" in labels
    for _, rendered in skeletons:
        assert "constitution v1" not in rendered
        assert "spec v2" not in rendered
    rendered_t2_f = dict(skeletons)["F/T2/call2"]
    assert "EV-T2-01" in rendered_t2_f
    assert f"repo:{SPEC}" in rendered_t2_f
    assert '"supersedes_evidence_id":"EV-T1-02"' in rendered_t2_f
    kinds = (
        '"allowed_judgment_kinds":["ASSERT_CLAIM","CONFLICTS_WITH","SUPERSEDE","SUPPORTS_CLAIM"]'
    )
    assert kinds in rendered_t2_f


def test_leakage_gate_fails_closed_when_a_request_cannot_be_rendered(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _broken(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("render exploded")

    monkeypatch.setattr(integrity, "render_request", _broken)
    results = preflight(**ok)
    _only_failed(results, "no_tracked_locus_leakage")
    assert "render exploded" in _gate(results, "no_tracked_locus_leakage").detail


# --------------------------------------------------------------------------- arm inputs


def test_persistent_delta_has_no_unchanged_evidence(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _gate(preflight(**ok), "persistent_delta_has_no_unchanged_evidence").passed

    # A timeline whose T2 spec bytes equal T1's still passes: the delta drops it.
    ok["timeline"] = _load(_blobs(t2_spec=b"spec v1\n"))
    ok["expected_evidence_hashes"] = evidence_hashes(ok["timeline"])
    assert _gate(preflight(**ok), "persistent_delta_has_no_unchanged_evidence").passed

    # A regressed Arm F input that re-sends every version at T re-reads unchanged bytes.
    monkeypatch.setattr(
        integrity,
        "persistent_delta",
        lambda items, t: tuple(v.item for v in items if v.t == t),
    )
    results = preflight(**ok)
    _only_failed(results, "persistent_delta_has_no_unchanged_evidence")
    gate = _gate(results, "persistent_delta_has_no_unchanged_evidence")
    assert "EV-T2-01" in gate.detail
    assert "T2" in gate.detail


def test_persistent_delta_gate_fails_if_arm_f_would_reread_the_whole_history(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        integrity,
        "persistent_delta",
        lambda items, t: tuple(v.item for v in items if v.t <= t),
    )
    results = preflight(**ok)
    _only_failed(results, "persistent_delta_has_no_unchanged_evidence")
    gate = _gate(results, "persistent_delta_has_no_unchanged_evidence")
    assert "EV-T1-01" in gate.detail  # the constitution must never be re-sent after T1


def test_reconstruction_corpus_is_cumulative(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _gate(preflight(**ok), "reconstruction_corpus_is_cumulative").passed

    # A regressed Arm R input that sends only the delta at T is under-informed (§32 #12).
    monkeypatch.setattr(
        integrity,
        "reconstruction_corpus",
        lambda items, t: tuple(v.item for v in items if v.t == t),
    )
    results = preflight(**ok)
    _only_failed(results, "reconstruction_corpus_is_cumulative")
    gate = _gate(results, "reconstruction_corpus_is_cumulative")
    assert "T2" in gate.detail
    assert "EV-T1-01" in gate.detail


def test_reconstruction_corpus_gate_fails_on_a_reordered_corpus(
    ok: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        integrity,
        "reconstruction_corpus",
        lambda items, t: tuple(reversed([v.item for v in items if v.t <= t])),
    )
    results = preflight(**ok)
    _only_failed(results, "reconstruction_corpus_is_cumulative")


# --------------------------------------------------------------------------- all_passed


def test_all_passed(ok: dict[str, Any]) -> None:
    results = preflight(**ok)
    assert all_passed(results)

    ok["config"] = _config(max_judge_calls=1)
    assert not all_passed(preflight(**ok))

    assert not all_passed(())
    assert not all_passed(
        (
            GateResult(name="a", passed=True, detail=""),
            GateResult(name="b", passed=False, detail="x"),
        )
    )
