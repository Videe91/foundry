import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.common import SourceKind
from foundry.domain.evidence import DigRecord, EvidenceItem, evidence_from_dig, evidence_item

OBSERVED_AT = datetime(2026, 9, 9, tzinfo=UTC)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _item(
    *,
    evidence_id: str = "EVD-1",
    source_kind: SourceKind = SourceKind.HUMAN,
    source_ref: str = "human://alice",
    content: str = "Retries must be three.",
    scope: tuple[str, ...] = (),
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id="PROJ-1",
        source_kind=source_kind,
        source_ref=source_ref,
        content=content,
        observed_at=OBSERVED_AT,
        scope=scope,
    )


def test_new_source_kinds_exist() -> None:
    assert SourceKind.TICKET.value == "TICKET"
    assert SourceKind.PULL_REQUEST.value == "PULL_REQUEST"
    assert SourceKind.AGENT_CONVERSATION.value == "AGENT_CONVERSATION"


def test_existing_source_kinds_unchanged() -> None:
    expected = {"HUMAN", "DOCUMENT", "CODE", "TEST", "RUNTIME", "RESEARCH", "SYSTEM"}
    assert expected <= {kind.value for kind in SourceKind}


def test_factory_computes_content_hash() -> None:
    item = _item()
    assert item.content_sha256 == _sha256("Retries must be three.")
    assert item.evidence_id == "EVD-1"
    assert item.project_id == "PROJ-1"
    assert item.scope == ()
    assert item.source_kind is SourceKind.HUMAN
    assert item.source_ref == "human://alice"
    assert item.observed_at == OBSERVED_AT


def test_explicit_matching_hash_is_accepted() -> None:
    item = EvidenceItem(
        evidence_id="EVD-1",
        project_id="PROJ-1",
        source_kind=SourceKind.CODE,
        source_ref="repo://svc/x.py#L1-L9",
        content="def x(): ...",
        content_sha256=_sha256("def x(): ..."),
        observed_at=OBSERVED_AT,
    )
    assert item.content_sha256 == _sha256("def x(): ...")


def test_tampered_hash_is_rejected() -> None:
    wrong = _sha256("something else")
    with pytest.raises(ValidationError, match="content_sha256"):
        EvidenceItem(
            evidence_id="EVD-1",
            project_id="PROJ-1",
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/x.py#L1-L9",
            content="def x(): ...",
            content_sha256=wrong,
            observed_at=OBSERVED_AT,
        )


def test_malformed_hash_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="EVD-1",
            project_id="PROJ-1",
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/x.py#L1-L9",
            content="def x(): ...",
            content_sha256="not-a-hash",
            observed_at=OBSERVED_AT,
        )


def test_empty_content_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _item(content="")


def test_empty_evidence_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _item(evidence_id="")


def test_empty_source_ref_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _item(source_ref="")


def test_evidence_item_is_frozen() -> None:
    item = _item()
    with pytest.raises(ValidationError):
        item.content = "changed"  # type: ignore[misc]


def test_any_evidence_builds_through_the_same_constructor() -> None:
    # Test L: human text, code and tests are all just evidence.
    human = _item(evidence_id="EVD-H", source_kind=SourceKind.HUMAN, source_ref="human://alice")
    code = _item(
        evidence_id="EVD-C",
        source_kind=SourceKind.CODE,
        source_ref="repo://svc/retry.py#L1-L9",
        content="MAX_RETRIES = 3",
    )
    test = _item(
        evidence_id="EVD-T",
        source_kind=SourceKind.TEST,
        source_ref="repo://tests/test_retry.py#L10-L20",
        content="assert retries == 3",
    )
    ticket = _item(
        evidence_id="EVD-K",
        source_kind=SourceKind.TICKET,
        source_ref="ticket://PROJ-12",
        content="Retry policy: three attempts.",
    )
    pull_request = _item(
        evidence_id="EVD-P",
        source_kind=SourceKind.PULL_REQUEST,
        source_ref="pr://svc/42",
        content="Bump retries to three.",
    )
    conversation = _item(
        evidence_id="EVD-A",
        source_kind=SourceKind.AGENT_CONVERSATION,
        source_ref="agent://session-7",
        content="Agent proposed three retries.",
    )
    items = (human, code, test, ticket, pull_request, conversation)
    assert all(isinstance(item, EvidenceItem) for item in items)
    assert {item.source_kind for item in items} == {
        SourceKind.HUMAN,
        SourceKind.CODE,
        SourceKind.TEST,
        SourceKind.TICKET,
        SourceKind.PULL_REQUEST,
        SourceKind.AGENT_CONVERSATION,
    }
    for item in items:
        assert item.content_sha256 == _sha256(item.content)


def test_scope_is_preserved() -> None:
    item = _item(scope=("checkout", "payments"))
    assert item.scope == ("checkout", "payments")


def test_evidence_from_dig_preserves_locator_kind_and_scope() -> None:
    record = DigRecord(
        locator="repo://svc/x.py#L1-L9",
        kind=SourceKind.CODE,
        content="def x(): ...",
        scope=("svc",),
        observed_at=OBSERVED_AT,
    )
    item = evidence_from_dig(record, project_id="PROJ-1", evidence_id="EVD-9")
    assert item.evidence_id == "EVD-9"
    assert item.project_id == "PROJ-1"
    assert item.source_ref == "repo://svc/x.py#L1-L9"
    assert item.source_kind is SourceKind.CODE
    assert item.scope == ("svc",)
    assert item.content == "def x(): ..."
    assert item.observed_at == OBSERVED_AT
    assert item.content_sha256 == _sha256("def x(): ...")


def test_dig_record_scope_defaults_to_project_wide() -> None:
    record = DigRecord(
        locator="ticket://PROJ-12",
        kind=SourceKind.TICKET,
        content="Retry policy: three attempts.",
        observed_at=OBSERVED_AT,
    )
    assert record.scope == ()
    item = evidence_from_dig(record, project_id="PROJ-1", evidence_id="EVD-10")
    assert item.scope == ()


def test_dig_record_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DigRecord(
            locator="ticket://PROJ-12",
            kind=SourceKind.TICKET,
            content="x",
            observed_at=OBSERVED_AT,
            extra="nope",  # type: ignore[call-arg]
        )
