"""Tests for the sidecar deck generation tool (slides-loop POC, P3).

The Presenton client is mocked: these tests prove the tool's orchestration
(poll, link creation, card metadata, error translation), not the sidecar's
behavior (the live P1 spike covers that).
"""

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.usage import RunUsage

from chat.clients.schema import ContextDeps
from chat.factories import ChatConversationFactory
from chat.models import ChatPresentationLink
from chat.presenton_client import PresentonError
from chat.tools.generate_presentation_sidecar import generate_presentation_sidecar

# transaction=True is required so writes done via sync_to_async (which run on
# a worker thread with their own connection) are visible to the test, matching
# the convention in test_document_summarize.py.
pytestmark = pytest.mark.django_db(transaction=True)

CARD = {
    "presentation_id": "11111111-1111-1111-1111-111111111111",
    "title": "A Deck Title",
    "slide_count": 4,
}


@pytest.fixture(name="ctx")
def ctx_fixture():
    """A RunContext-shaped object carrying a real conversation."""
    conversation = ChatConversationFactory()
    return RunContext(
        model="test",
        usage=RunUsage(input_tokens=0, output_tokens=0),
        deps=ContextDeps(conversation=conversation, user=conversation.owner),
        max_retries=2,
        retries={},
        tool_name="generate_presentation_sidecar",
    )


@pytest.fixture(name="mock_client")
def mock_client_fixture():
    """Patch PresentonClient where the tool constructs it."""
    with patch("chat.tools.generate_presentation_sidecar.PresentonClient") as mock_cls:
        client = mock_cls.return_value
        client.generate_async = AsyncMock(return_value={"id": "task-1"})
        client.generation_status = AsyncMock(
            return_value={
                "status": "completed",
                "data": {
                    "presentation_id": CARD["presentation_id"],
                    "path": "/app_data/exports/deck.pptx",
                },
            }
        )
        client.get_presentation = AsyncMock(
            return_value={"title": CARD["title"], "n_slides": 4, "slides": [{}] * 4}
        )
        client.editor_url.return_value = (
            f"http://presenton.test/presentation?id={CARD['presentation_id']}"
        )
        client.export_url.return_value = "http://presenton.test/app_data/exports/deck.pptx"
        yield client


@pytest.mark.asyncio
async def test_generation_creates_link_and_card(ctx, mock_client):
    """A successful generation persists a link and returns card metadata."""
    result = await generate_presentation_sidecar(ctx, "a brief")

    mock_client.generate_async.assert_awaited_once_with("a brief", export_as="pptx")
    link = await sync_to_async(ChatPresentationLink.objects.get)(conversation=ctx.deps.conversation)
    assert str(link.presentation_id) == CARD["presentation_id"]
    assert link.title == CARD["title"]

    card = result.metadata["presentation"]
    assert card["presentation_id"] == CARD["presentation_id"]
    assert card["link_id"] == str(link.pk)
    assert card["slide_count"] == 4
    assert card["editor_url"].endswith(CARD["presentation_id"])
    assert card["download_url"].endswith("deck.pptx")


@pytest.mark.asyncio
async def test_empty_brief_retries(ctx, mock_client):
    """An empty brief is a model-retryable input error, no sidecar call."""
    with pytest.raises(ModelRetry):
        await generate_presentation_sidecar(ctx, "   ")
    mock_client.generate_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_sidecar_failure_retries(ctx, mock_client):
    """A sidecar error during generation is retryable."""
    mock_client.generate_async.side_effect = PresentonError("boom")
    with pytest.raises(ModelRetry):
        await generate_presentation_sidecar(ctx, "a brief")
    assert not await sync_to_async(ChatPresentationLink.objects.exists)()


@pytest.mark.asyncio
async def test_task_error_retries(ctx, mock_client):
    """A completed-with-error task is retryable."""
    mock_client.generation_status.return_value = {
        "status": "error",
        "error": {"message": "provider down"},
    }
    with pytest.raises(ModelRetry):
        await generate_presentation_sidecar(ctx, "a brief")


@pytest.mark.asyncio
async def test_missing_presentation_id_cannot_retry(ctx, mock_client):
    """A completed task without a presentation id soft-fails (no retry).

    The last_model_retry_soft_fail decorator converts ModelCannotRetry into a
    message string for the model, so the tool returns that message rather than
    raising.
    """
    mock_client.generation_status.return_value = {"status": "completed", "data": {}}
    result = await generate_presentation_sidecar(ctx, "a brief")
    assert isinstance(result, str)
    assert "id is missing" in result
    assert not await sync_to_async(ChatPresentationLink.objects.exists)()


@pytest.mark.asyncio
async def test_polls_until_completed(ctx, mock_client):
    """Pending statuses are polled until completion."""
    mock_client.generation_status = AsyncMock(
        side_effect=[
            {"status": "pending"},
            {"status": "pending"},
            {
                "status": "completed",
                "data": {"presentation_id": CARD["presentation_id"], "path": "/x.pptx"},
            },
        ]
    )
    with patch(
        "chat.tools.generate_presentation_sidecar.asyncio.sleep", new=AsyncMock()
    ) as mock_sleep:
        result = await generate_presentation_sidecar(ctx, "a brief")
    assert mock_client.generation_status.await_count == 3
    assert mock_sleep.await_count == 2
    assert result.metadata["presentation"]["presentation_id"] == CARD["presentation_id"]


@pytest.mark.asyncio
async def test_long_title_trimmed(ctx, mock_client):
    """The card title is capped so a verbose sidecar title stays readable."""
    mock_client.get_presentation.return_value = {
        "title": "T" * 300,
        "n_slides": 1,
        "slides": [{}],
    }
    await generate_presentation_sidecar(ctx, "a brief")
    link = await sync_to_async(ChatPresentationLink.objects.get)(conversation=ctx.deps.conversation)
    assert len(link.title) == 80
