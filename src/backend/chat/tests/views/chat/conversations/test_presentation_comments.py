"""Tests for the slide-anchored deck comment endpoints (slides-loop POC, P4)."""

import pytest
from rest_framework import status

from core.factories import UserFactory

from chat.factories import (
    ChatConversationFactory,
    ChatPresentationLinkFactory,
    PresentationCommentFactory,
)
from chat.models import PresentationComment

pytestmark = pytest.mark.django_db


@pytest.fixture(name="conversation")
def conversation_fixture():
    return ChatConversationFactory()


@pytest.fixture(name="link")
def link_fixture(conversation):
    return ChatPresentationLinkFactory(conversation=conversation)


@pytest.fixture(name="auth_client")
def auth_client_fixture(api_client, conversation):
    api_client.force_login(conversation.owner)
    return api_client


def _comments_url(conversation, link):
    return f"/api/v1.0/chats/{conversation.pk}/presentations/{link.pk}/comments/"


def test_create_comment(auth_client, conversation, link):
    """POST pins a comment to a slide and returns it."""
    response = auth_client.post(
        _comments_url(conversation, link),
        {"slide_index": 2, "field": "title", "body": "shorten this"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["slide_index"] == 2
    assert data["field"] == "title"
    assert data["body"] == "shorten this"
    assert data["resolved"] is False
    assert PresentationComment.objects.filter(link=link).count() == 1


def test_create_comment_whole_slide(auth_client, conversation, link):
    """The field is optional; omitting it targets the whole slide."""
    response = auth_client.post(
        _comments_url(conversation, link),
        {"slide_index": 0, "body": "rework this slide"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["field"] == ""


def test_create_comment_invalid_slide_index(auth_client, conversation, link):
    """A negative slide index is rejected."""
    response = auth_client.post(
        _comments_url(conversation, link),
        {"slide_index": -1, "body": "bad"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_list_comments(auth_client, conversation, link):
    """GET returns the deck's comments."""
    PresentationCommentFactory(link=link, slide_index=0, body="first")
    PresentationCommentFactory(link=link, slide_index=1, body="second")
    response = auth_client.get(_comments_url(conversation, link))
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 2
    assert {c["body"] for c in data} == {"first", "second"}


def test_resolve_comment(auth_client, conversation, link):
    """POST resolve marks a comment resolved."""
    comment = PresentationCommentFactory(link=link, resolved=False)
    url = _comments_url(conversation, link) + f"{comment.pk}/resolve/"
    response = auth_client.post(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["resolved"] is True
    comment.refresh_from_db()
    assert comment.resolved is True


def test_comments_scoped_to_owner(api_client, conversation, link):
    """Another user cannot read or write the deck's comments."""
    other = UserFactory()
    api_client.force_login(other)
    response = api_client.get(_comments_url(conversation, link))
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_comments_require_auth(api_client, conversation, link):
    """Anonymous requests are rejected."""
    response = api_client.get(_comments_url(conversation, link))
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )
