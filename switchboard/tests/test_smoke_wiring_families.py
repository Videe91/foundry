"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: the per-family half of the R-020 wiring guard — that prove_families
demos every family present, each with its own effort, cache pair, attachment
kinds, and meter records, and that an adapterless family is skipped aloud.

Split from test_smoke_wiring.py under the R-017 precedent when the fourth
family pushed that file past the 300-line ceiling. SmokeFake is imported from
its parent rather than copied — one fake, one definition (R-009's intent).

No network, no keys. Shapes mirror the real API per R-019.

Version: 0.11.0
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FREE
from test_smoke_wiring import SHARED, SmokeFake, _messages

from smoke import prove_attachments, prove_families
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute

OPENAI = "openai/gpt-5.6-terra"
GEMINI = "gemini/gemini-3.7-flash"
XAI = "xai/grok-4.6"
OPENROUTER = "openrouter/moonshotai/kimi-k3"
TWO_FAMILY_REGISTRY = ModelRegistry(roles={
    "floor_agent": RoleRoute(model=SHARED, fallbacks=[], max_tokens=64000, effort="medium"),
    "judge": RoleRoute(model=OPENAI, fallbacks=[], max_tokens=128000, effort="high"),
    "judge_third": RoleRoute(model=GEMINI, fallbacks=[], max_tokens=64000, effort="low"),
    "judge_fourth": RoleRoute(model=XAI, fallbacks=[], max_tokens=64000, effort="high"),
    # No effort ceiling exists for an aggregator (R-031), so "max" is lawful
    # here even though it would be rejected on gemini or xai.
    "judge_fifth": RoleRoute(model=OPENROUTER, fallbacks=[], max_tokens=64000,
                             effort="max"),
    "scribe": RoleRoute(model="mistral/large", fallbacks=[], max_tokens=8000),
})


def test_prove_families_runs_the_demos_once_per_family(tmp_path: Path) -> None:
    fake = SmokeFake()
    prove_families(TWO_FAMILY_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    # each adapter family: 2 cache + 1 attachments + 1 streaming (P-010), plus
    # 1 search where the family can search (P-015 — anthropic only, for now).
    # mistral: cache and streaming only, since it has no adapter.
    models = [call["model"] for call in fake.calls]
    assert models.count(SHARED) == 5, "anthropic runs PROVE 5 as well"
    assert [models.count(m) for m in (OPENAI, GEMINI, XAI, OPENROUTER)] == \
        [4, 4, 4, 4]
    assert models.count("mistral/large") == 3


def test_each_family_gets_a_byte_identical_cache_pair(tmp_path: Path) -> None:
    fake = SmokeFake()
    prove_families(TWO_FAMILY_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    for model in (SHARED, OPENAI, GEMINI, XAI, OPENROUTER):
        pair = [call for call in fake.calls if call["model"] == model][:2]
        assert pair[0]["messages"] == pair[1]["messages"], model


def test_adapterless_family_is_skipped_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    fake = SmokeFake()
    prove_families(TWO_FAMILY_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    assert "[skip] mistral: no family adapter" in capsys.readouterr().out
    mistral = [call for call in fake.calls if call["model"] == "mistral/large"]
    assert all(isinstance(call["messages"][-1]["content"], str) for call in mistral)


def test_each_family_carries_its_own_effort_and_meters(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "m.jsonl")
    fake = SmokeFake()
    prove_families(TWO_FAMILY_REGISTRY, ledger, fake, FREE)
    efforts = {c["model"]: c.get("reasoning_effort")
               for c in fake.calls if "reasoning_effort" in c}
    assert (efforts[SHARED], efforts[OPENAI], efforts[GEMINI], efforts[XAI],
            efforts[OPENROUTER]) == ("medium", "high", "low", "high", "max")
    records = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(records) == len(fake.calls)


def test_openai_family_attachments_send_all_three_kinds(tmp_path: Path) -> None:
    fake = SmokeFake()
    ledger = MeterLedger(tmp_path / "m.jsonl")
    prove_attachments(TWO_FAMILY_REGISTRY, ledger, "judge", fake, FREE)
    parts = _messages(fake)[-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "file", "text"]
    pdf = next(p for p in parts if p["type"] == "file")  # T-004: files are pdf-only
    assert pdf["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert "attached file: notes.md" in parts[-1]["text"]


def test_xai_family_attachments_send_image_and_text_but_never_pdf(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """P-009 contract 4, through the smoke path: the refusal is visible.

    xAI's chat API documents text and image input only, so the demo must drop
    the PDF and say so — the family's other two kinds still go.
    """
    fake = SmokeFake()
    prove_attachments(
        TWO_FAMILY_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), "judge_fourth", fake, FREE
    )
    assert "does not accept pdf" in capsys.readouterr().out
    parts = _messages(fake)[-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "text"]
    assert "attached file: notes.md" in parts[-1]["text"]


def test_every_family_gets_its_own_streamed_call(tmp_path: Path) -> None:
    """P-010's acceptance rider: streaming was live-proven on Anthropic only,
    so the flip owes every family a streamed demo of its own."""
    fake = SmokeFake()
    prove_families(TWO_FAMILY_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    streamed = {c["model"] for c in fake.calls if c.get("stream")}
    assert streamed == {SHARED, OPENAI, GEMINI, XAI, OPENROUTER, "mistral/large"}
    for call in fake.calls:
        if call.get("stream"):
            assert call["stream_options"] == {"include_usage": True}


def test_the_aggregator_sends_all_three_attachment_kinds(tmp_path: Path) -> None:
    """Contract 6: the fifth family joins through the existing iteration.

    OpenRouter refuses nothing at the family level, so unlike xAI its
    attachments demo carries the full set — the per-model verdict is the
    matrix's to report, not the adapter's to pre-empt.
    """
    fake = SmokeFake()
    prove_attachments(
        TWO_FAMILY_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), "judge_fifth", fake, FREE
    )
    parts = _messages(fake)[-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "file", "text"]
    assert parts[2]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert "attached file: notes.md" in parts[-1]["text"]
