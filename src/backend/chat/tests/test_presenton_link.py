"""Tests for the conversation-to-Presenton deck link (slides-loop POC, P2)."""

import pytest

from chat.factories import ChatConversationFactory, ChatPresentationLinkFactory
from chat.models import ChatPresentationLink

pytestmark = pytest.mark.django_db()


def test_link_factory_creates_valid_row():
    """The factory produces a persisted link with a UUID presentation id."""
    link = ChatPresentationLinkFactory()
    assert isinstance(link, ChatPresentationLink)
    assert link.pk is not None
    assert link.presentation_id is not None
    assert link.conversation_id is not None


def test_link_attached_to_conversation():
    """A link is reachable from its conversation's reverse relation."""
    conversation = ChatConversationFactory()
    link = ChatPresentationLinkFactory(conversation=conversation)
    assert list(conversation.presentation_links.all()) == [link]


def test_links_cascade_on_conversation_delete():
    """Deleting the conversation removes its deck links."""
    link = ChatPresentationLinkFactory()
    conversation = link.conversation
    conversation.delete()
    assert not ChatPresentationLink.objects.filter(pk=link.pk).exists()


def test_multiple_links_per_conversation():
    """A conversation can hold several decks, newest first."""
    conversation = ChatConversationFactory()
    first = ChatPresentationLinkFactory(conversation=conversation)
    second = ChatPresentationLinkFactory(conversation=conversation)
    links = list(conversation.presentation_links.all())
    assert links == [second, first]
