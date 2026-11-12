"""Tests for the sidecar rework tool (slides-loop POC, P4).

The Presenton client is mocked: these tests prove the tool reads the live
deck, applies unresolved comments via AI slide edit, marks them resolved,
and leaves already-resolved comments alone.
"""

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.usage import RunUsage

from chat.clients.schema import ContextDeps
from chat.factories import (
    ChatConversationFactory,
    ChatPresentationLinkFactory,
    PresentationCommentFactory,
)
from chat.models import PresentationComment
from chat.presenton_client import PresentonError
from chat.tools.revise_presentation_sidecar import revise_presentation_sidecar

pytestmark = pytest.mark.django_db(transaction=True)

DECK = {
    "title": "A Deck",
    "n_slides": 2,
    "slides": [
        {"id": "slide-0", "index": 0, "content": {"title": "Intro"}},
        {"id": "slide-1", "index": 1, "content": {"title": "Body"}},
    ],
}


@pytest.fixture(name="ctx")
def ctx_fixture():
    """A RunContext carrying a real conversation."""
    conversation = ChatConversationFactory()
    return RunContext(
        model="test",
        usage=RunUsage(input_tokens=0, output_tokens=0),
        deps=ContextDeps(conversation=conversation, user=conversation.owner),
        max_retries=2,
        retries={},
        tool_name="revise_presentation_sidecar",
    )


@pytest.fixture(name="link")
def link_fixture(ctx):
    """A deck link belonging to the context's conversation."""
    return ChatPresentationLinkFactory(
        conversation=ctx.deps.conversation, presentation_id="11111111-1111-1111-1111-111111111111"
    )


@pytest.fixture(name="mock_client")
def mock_client_fixture():
    """Patch PresentonClient where the rework tool constructs it."""
    with patch("chat.tools.revise_presentation_sidecar.PresentonClient") as mock_cls:
        client = mock_cls.return_value
        client.get_presentation = AsyncMock(return_value=DECK)
        client.edit_slide_ai = AsyncMock(return_value={})
        client.edit_presentation = AsyncMock(return_value={"path": "/app_data/exports/deck.pptx"})
        client.editor_url.return_value = "http://presenton.test/presentation?id=11111111"
        client.export_url.return_value = "http://presenton.test/deck.pptx"
        yield client


@pytest.mark.asyncio
async def test_rework_applies_comments_and_resolves(ctx, link, mock_client):
    """Unresolved comments are applied via AI slide edit and marked resolved."""
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    comment = await sync_to_async(PresentationCommentFactory)(
        link=link, slide_index=1, body="shorten the body"
    )

    result = await revise_presentation_sidecar(ctx, "11111111-1111-1111-1111-111111111111")

    # Read once to apply comments, once more to snapshot the revised deck.
    assert mock_client.get_presentation.await_count == 2
    mock_client.get_presentation.assert_awaited_with("11111111-1111-1111-1111-111111111111")
    mock_client.edit_slide_ai.assert_awaited_once()
    args = mock_client.edit_slide_ai.await_args.args
    assert args[0] == "slide-1"
    assert "shorten the body" in args[1]
    refreshed = await sync_to_async(PresentationComment.objects.get)(pk=comment.pk)
    assert refreshed.resolved is True
    assert (
        result.metadata["presentation"]["presentation_id"] == "11111111-1111-1111-1111-111111111111"
    )


@pytest.mark.asyncio
async def test_rework_skips_resolved_comments(ctx, link, mock_client):
    """Already-resolved comments are not re-applied."""
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    await sync_to_async(PresentationCommentFactory)(link=link, slide_index=0, resolved=True)

    result = await revise_presentation_sidecar(ctx, "11111111-1111-1111-1111-111111111111")

    mock_client.edit_slide_ai.assert_not_awaited()
    assert "no unresolved comments" in result.return_value


@pytest.mark.asyncio
async def test_rework_unknown_deck_cannot_retry(ctx, mock_client):  # pylint: disable=unused-argument
    """A deck id not belonging to the conversation soft-fails (no retry).

    The last_model_retry_soft_fail decorator converts ModelCannotRetry into a
    message string for the model, so the tool returns that message.
    """
    result = await revise_presentation_sidecar(ctx, "99999999-9999-9999-9999-999999999999")
    assert isinstance(result, str)
    assert "No presentation belongs to this conversation" in result


@pytest.mark.asyncio
async def test_rework_sidecar_failure_retries(ctx, link, mock_client):
    """A sidecar read failure is retryable."""
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    await sync_to_async(PresentationCommentFactory)(link=link, slide_index=0)
    mock_client.get_presentation.side_effect = PresentonError("boom")

    with pytest.raises(ModelRetry):
        await revise_presentation_sidecar(ctx, "11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
async def test_rework_missing_slide_skipped(ctx, link, mock_client):
    """A comment targeting a slide index that no longer exists is skipped."""
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    comment = await sync_to_async(PresentationCommentFactory)(
        link=link, slide_index=99, body="gone"
    )

    await revise_presentation_sidecar(ctx, "11111111-1111-1111-1111-111111111111")

    mock_client.edit_slide_ai.assert_not_awaited()
    refreshed = await sync_to_async(PresentationComment.objects.get)(pk=comment.pk)
    assert refreshed.resolved is False


@pytest.mark.asyncio
async def test_rework_tracks_replacement_slide_id(ctx, link, mock_client):
    """Two comments on one slide use the replacement id after the first edit.

    Presenton assigns a new UUID on every successful edit; reusing the stale
    id for the second comment would 404.
    """
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    await sync_to_async(PresentationCommentFactory)(link=link, slide_index=1, body="first")
    await sync_to_async(PresentationCommentFactory)(link=link, slide_index=1, body="second")
    # The first edit returns a replacement slide with a new id.
    mock_client.edit_slide_ai = AsyncMock(
        side_effect=[
            {"id": "slide-1-new", "index": 1, "content": {}},
            {"id": "slide-1-newer", "index": 1, "content": {}},
        ]
    )

    await revise_presentation_sidecar(ctx, "11111111-1111-1111-1111-111111111111")

    calls = mock_client.edit_slide_ai.await_args_list
    assert len(calls) == 2
    assert calls[0].args[0] == "slide-1"
    assert calls[1].args[0] == "slide-1-new"


@pytest.mark.asyncio
async def test_rework_persists_completed_comments_on_later_failure(ctx, link, mock_client):
    """A later edit failure must not un-resolve earlier successful comments.

    Presenton commits each edit immediately, so reapplying an already-applied
    comment on retry would compound non-idempotent changes.
    """
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    first = await sync_to_async(PresentationCommentFactory)(
        link=link, slide_index=0, body="first"
    )
    second = await sync_to_async(PresentationCommentFactory)(
        link=link, slide_index=1, body="second"
    )
    mock_client.edit_slide_ai = AsyncMock(
        side_effect=[{"id": "slide-0-new", "index": 0}, PresentonError("boom")]
    )

    with pytest.raises(ModelRetry):
        await revise_presentation_sidecar(ctx, "11111111-1111-1111-1111-111111111111")

    first_refreshed = await sync_to_async(PresentationComment.objects.get)(pk=first.pk)
    second_refreshed = await sync_to_async(PresentationComment.objects.get)(pk=second.pk)
    assert first_refreshed.resolved is True
    assert second_refreshed.resolved is False


@pytest.mark.asyncio
async def test_rework_defaults_to_latest_deck(ctx, link, mock_client):
    """Without an id, the tool revises the conversation's most recent deck.

    The model never sees the deck UUID (it lives in tool metadata, not the
    model-visible return), so the common flow must not require it.
    """
    link.presentation_id = "11111111-1111-1111-1111-111111111111"
    await sync_to_async(link.save)()
    await sync_to_async(PresentationCommentFactory)(link=link, slide_index=1, body="shorten")

    result = await revise_presentation_sidecar(ctx)

    mock_client.get_presentation.assert_awaited_with("11111111-1111-1111-1111-111111111111")
    assert (
        result.metadata["presentation"]["presentation_id"] == "11111111-1111-1111-1111-111111111111"
    )


@pytest.mark.asyncio
async def test_rework_no_deck_soft_fails(ctx, mock_client):
    """With no deck in the conversation, the tool soft-fails with guidance."""
    result = await revise_presentation_sidecar(ctx)
    assert isinstance(result, str)
    assert "Generate one first" in result
