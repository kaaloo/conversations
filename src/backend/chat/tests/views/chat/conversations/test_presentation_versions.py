"""Tests for the deck version endpoints (slides-loop POC, P5)."""

from unittest.mock import AsyncMock, patch

import pytest
from rest_framework import status

from core.factories import UserFactory

from chat.factories import (
    ChatConversationFactory,
    ChatPresentationLinkFactory,
    PresentationVersionFactory,
)
from chat.models import PresentationVersion
from chat.presenton_client import PresentonError

pytestmark = pytest.mark.django_db

DECK = {
    "slides": [
        {"index": 0, "content": {"title": "Intro"}},
        {"index": 1, "content": {"title": "Body"}},
    ]
}


@pytest.fixture(name="conversation")
def conversation_fixture():
    """A conversation owned by a fresh user."""
    return ChatConversationFactory()


@pytest.fixture(name="link")
def link_fixture(conversation):
    """A deck link belonging to the conversation."""
    return ChatPresentationLinkFactory(conversation=conversation)


@pytest.fixture(name="auth_client")
def auth_client_fixture(api_client, conversation):
    """An API client logged in as the conversation's owner."""
    api_client.force_login(conversation.owner)
    return api_client


def _versions_url(conversation, link):
    return f"/api/v1.0/chats/{conversation.pk}/presentations/{link.pk}/versions/"


def test_list_versions(auth_client, conversation, link):
    """GET returns the deck's versions, newest first."""
    PresentationVersionFactory(link=link, number=1, slide_count=2)
    PresentationVersionFactory(link=link, number=2, slide_count=3)
    response = auth_client.get(_versions_url(conversation, link))
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert [v["number"] for v in data] == [2, 1]


def test_restore_version(auth_client, conversation, link):
    """POST restore re-applies the snapshot and records a new version."""
    version = PresentationVersionFactory(
        link=link,
        number=1,
        slides=[{"index": 0, "content": {"title": "Old"}}],
        slide_count=1,
    )
    with patch("chat.views.presentation_versions.PresentonClient") as mock_cls:
        client = mock_cls.return_value
        client.edit_presentation = AsyncMock(return_value={"path": "/x.pptx"})
        client.get_presentation = AsyncMock(return_value=DECK)
        url = _versions_url(conversation, link) + f"{version.number}/restore/"
        response = auth_client.post(url)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["number"] == 2
    assert response.json()["source"] == "restore"
    client.edit_presentation.assert_awaited_once()
    assert PresentationVersion.objects.filter(link=link, number=2).exists()


def test_restore_sidecar_failure(auth_client, conversation, link):
    """A sidecar failure on restore returns 502."""
    version = PresentationVersionFactory(link=link, number=1, slides=[], slide_count=0)
    with patch("chat.views.presentation_versions.PresentonClient") as mock_cls:
        client = mock_cls.return_value
        client.edit_presentation = AsyncMock(side_effect=PresentonError("boom"))
        url = _versions_url(conversation, link) + f"{version.number}/restore/"
        response = auth_client.post(url)
    assert response.status_code == status.HTTP_502_BAD_GATEWAY


def test_export(auth_client, conversation, link):
    """GET export returns a fresh download URL."""
    with patch("chat.views.presentation_versions.PresentonClient") as mock_cls:
        client = mock_cls.return_value
        client.edit_presentation = AsyncMock(return_value={"path": "/app_data/x.pptx"})
        client.export_url.return_value = "http://localhost:5001/app_data/x.pptx"
        url = f"/api/v1.0/chats/{conversation.pk}/presentations/{link.pk}/export/"
        response = auth_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["download_url"] == "http://localhost:5001/app_data/x.pptx"


def test_versions_scoped_to_owner(api_client, conversation, link):
    """Another user cannot list the deck's versions."""
    api_client.force_login(UserFactory())
    response = api_client.get(_versions_url(conversation, link))
    assert response.status_code == status.HTTP_404_NOT_FOUND
