"""Tests for deck version recording (slides-loop POC, P5)."""

import pytest
from asgiref.sync import sync_to_async

from chat.factories import ChatPresentationLinkFactory, PresentationVersionFactory
from chat.models import PresentationVersion
from chat.presentation_versions import record_version

pytestmark = pytest.mark.django_db(transaction=True)

DECK = {
    "slides": [
        {"index": 0, "content": {"title": "Intro"}},
        {"index": 1, "content": {"title": "Body"}},
    ]
}


@pytest.mark.asyncio
async def test_record_version_numbers_sequentially():
    """Versions are numbered 1, 2, 3 within a deck."""
    link = await sync_to_async(ChatPresentationLinkFactory)()
    v1 = await record_version(link, DECK, "generated")
    v2 = await record_version(link, DECK, "rework")
    assert v1.number == 1
    assert v2.number == 2
    assert v1.source == "generated"
    assert v2.source == "rework"


@pytest.mark.asyncio
async def test_record_version_snapshots_slides():
    """The snapshot captures each slide's index and content."""
    link = await sync_to_async(ChatPresentationLinkFactory)()
    version = await record_version(link, DECK, "generated")
    assert version.slide_count == 2
    assert version.slides == [
        {"index": 0, "content": {"title": "Intro"}},
        {"index": 1, "content": {"title": "Body"}},
    ]


@pytest.mark.asyncio
async def test_record_version_empty_deck():
    """An empty deck records a zero-slide version."""
    link = await sync_to_async(ChatPresentationLinkFactory)()
    version = await record_version(link, {"slides": []}, "generated")
    assert version.slide_count == 0
    assert version.slides == []


@pytest.mark.asyncio
async def test_versions_scoped_per_link():
    """Numbering is independent per deck."""
    link_a = await sync_to_async(ChatPresentationLinkFactory)()
    link_b = await sync_to_async(ChatPresentationLinkFactory)()
    await record_version(link_a, DECK, "generated")
    v_b = await record_version(link_b, DECK, "generated")
    assert v_b.number == 1


def test_version_factory_defaults():
    """The factory produces a valid generated version."""
    version = PresentationVersionFactory()
    assert version.pk is not None
    assert version.source == PresentationVersion.Source.GENERATED
