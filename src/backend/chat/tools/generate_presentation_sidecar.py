"""Slide deck generation via the Presenton sidecar (slides-loop POC, P3).

Unlike the native ``generate_presentation`` tool (one-off PPTX download), this
tool creates a durable deck in the sidecar, links it to the conversation, and
returns metadata the frontend renders as a deck card with an embedded editor.
"""

import asyncio

import structlog
from asgiref.sync import sync_to_async
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ToolReturn

from core.log_fields import safe_error_fields

from chat.models import ChatPresentationLink
from chat.presentation_versions import record_version
from chat.presenton_client import PresentonClient, PresentonError
from chat.tools.exceptions import ModelCannotRetry
from chat.tools.utils import last_model_retry_soft_fail

logger = structlog.get_logger(__name__)

# Bounded poll: generation runs a full outline + per-slide pipeline on the
# configured provider. Keep the ceiling generous but finite so a stuck task
# cannot hold a turn forever.
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 600

# The sidecar sometimes returns the whole cover content as the deck title;
# keep the card label short.
MAX_TITLE_LENGTH = 80


@sync_to_async
def _create_link(conversation, presentation_id: str, title: str) -> ChatPresentationLink:
    return ChatPresentationLink.objects.create(
        conversation=conversation,
        presentation_id=presentation_id,
        title=title[:MAX_TITLE_LENGTH],
    )


async def _await_generation(client: PresentonClient, task_id: str) -> dict:
    """Poll the async task until it completes; raise on error or timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_TIMEOUT_SECONDS
    while True:
        status = await client.generation_status(task_id)
        state = status.get("status")
        if state == "completed":
            return status
        if state == "error":
            raise PresentonError(f"generation task failed: {status.get('error') or status}")
        if loop.time() > deadline:
            raise PresentonError(f"generation timed out after {POLL_TIMEOUT_SECONDS}s")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@last_model_retry_soft_fail
async def generate_presentation_sidecar(ctx: RunContext, brief: str) -> ToolReturn:
    """
    Generate a slide deck in the presentation sidecar and open it in the chat.

    Args:
        brief: What the deck must cover, in the user's own terms. Include the
            subject, the audience and any structure the user asked for.

    Returns:
        ToolReturn: confirmation carrying the deck card metadata (editor and
        download URLs).
    """
    if not brief.strip():
        raise ModelRetry("The brief is empty. Describe what the presentation must cover.")

    client = PresentonClient()
    try:
        task = await client.generate_async(brief, export_as="pptx")
        status = await _await_generation(client, task["id"])
    except PresentonError as exc:
        logger.warning("presenton_generation_failed", **safe_error_fields(exc))
        raise ModelRetry("The presentation could not be generated. Try again.") from exc

    data = status.get("data") or {}
    presentation_id = data.get("presentation_id")
    if not presentation_id:
        logger.error("presenton_generation_missing_id", task_id=task["id"])
        raise ModelCannotRetry("The presentation was generated but its id is missing.")

    try:
        deck = await client.get_presentation(presentation_id)
    except PresentonError as exc:
        logger.warning("presenton_get_failed", **safe_error_fields(exc))
        raise ModelRetry("The presentation was generated but could not be read.") from exc

    title = (deck.get("title") or "").strip() or "Presentation"
    link = await _create_link(ctx.deps.conversation, presentation_id, title)
    await record_version(link, deck, "generated")

    card = {
        "presentation_id": str(presentation_id),
        "link_id": str(link.pk),
        "title": link.title,
        "slide_count": deck.get("n_slides") or len(deck.get("slides", [])),
        "editor_url": client.editor_url(str(presentation_id)),
        "download_url": client.export_url(data["path"]) if data.get("path") else None,
    }

    logger.info(
        "presenton_deck_generated",
        presentation_id=str(presentation_id),
        slides=card["slide_count"],
        conversation_id=ctx.deps.conversation.pk,
    )

    return ToolReturn(
        return_value=(
            f"The presentation '{link.title}' was generated with "
            f"{card['slide_count']} slides and opened in the chat as an editable "
            "deck card. Tell the user they can edit it inline or download it; "
            "do not restate the deck's content."
        ),
        metadata={"presentation": card},
    )
