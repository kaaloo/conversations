"""Rework a sidecar deck from slide-anchored comments (slides-loop POC, P4).

The rework bridge: the user pins feedback to slides in the deck card, then
asks the assistant to revise. This tool reads the *live* deck from the
sidecar (so manual edits are respected), applies each unresolved comment via
Presenton's AI slide edit, and marks the comments resolved. Untouched slides
are preserved because the AI edit targets one slide at a time.
"""

import structlog
from asgiref.sync import sync_to_async
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ToolReturn

from core.log_fields import safe_error_fields

from chat.models import ChatPresentationLink, PresentationComment
from chat.presentation_versions import record_version
from chat.presenton_client import PresentonClient, PresentonError
from chat.tools.exceptions import ModelCannotRetry
from chat.tools.utils import last_model_retry_soft_fail

logger = structlog.get_logger(__name__)


@sync_to_async
def _get_link(conversation, presentation_id: str) -> ChatPresentationLink | None:
    return ChatPresentationLink.objects.filter(
        conversation=conversation, presentation_id=presentation_id
    ).first()


@sync_to_async
def _latest_link(conversation) -> ChatPresentationLink | None:
    """The conversation's most recent deck, when no id is supplied."""
    return (
        ChatPresentationLink.objects.filter(conversation=conversation)
        .order_by("-created_at")
        .first()
    )


@sync_to_async
def _unresolved_comments(link: ChatPresentationLink) -> list[PresentationComment]:
    return list(link.comments.filter(resolved=False).order_by("slide_index", "created_at"))


@sync_to_async
def _mark_resolved(comment_ids: list) -> None:
    PresentationComment.objects.filter(pk__in=comment_ids).update(resolved=True)


def _build_prompt(comment: PresentationComment, instruction: str) -> str:
    """Combine the pinned feedback and the user's instruction for one slide."""
    target = f"the '{comment.field}' field" if comment.field else "this slide"
    parts = [f"Revise {target} of this slide."]
    parts.append(f"Feedback to address: {comment.body}")
    if instruction.strip():
        parts.append(f"Additional instruction: {instruction.strip()}")
    parts.append("Keep everything else on the slide unchanged.")
    return "\n".join(parts)


@last_model_retry_soft_fail
async def revise_presentation_sidecar(
    ctx: RunContext, presentation_id: str = "", instruction: str = ""
) -> ToolReturn:
    """
    Rework a presentation using the comments pinned to its slides.

    Args:
        presentation_id: The deck to revise. Optional — defaults to the most
            recent deck generated in this conversation.
        instruction: Optional overall guidance to apply alongside the comments.

    Returns:
        ToolReturn: confirmation carrying the refreshed deck card metadata.
    """
    if presentation_id:
        link = await _get_link(ctx.deps.conversation, presentation_id)
    else:
        link = await _latest_link(ctx.deps.conversation)
    if link is None:
        raise ModelCannotRetry("No presentation belongs to this conversation. Generate one first.")

    comments = await _unresolved_comments(link)
    if not comments:
        return ToolReturn(
            return_value=(
                "There are no unresolved comments on this presentation. Ask the "
                "user to pin feedback to a slide first, or give a specific change "
                "to make."
            ),
        )

    client = PresentonClient()
    try:
        deck = await client.get_presentation(str(link.presentation_id))
    except PresentonError as exc:
        logger.warning("presenton_rework_get_failed", **safe_error_fields(exc))
        raise ModelRetry("The presentation could not be read for revision.") from exc

    slides = deck.get("slides", [])
    by_index = {s.get("index"): s for s in slides}

    resolved_ids = []
    edited_slides = set()
    for comment in comments:
        slide = by_index.get(comment.slide_index)
        if slide is None or not slide.get("id"):
            logger.warning(
                "presenton_rework_slide_missing",
                slide_index=comment.slide_index,
                presentation_id=str(link.presentation_id),
            )
            continue
        prompt = _build_prompt(comment, instruction)
        try:
            edited = await client.edit_slide_ai(str(slide["id"]), prompt)
        except PresentonError as exc:
            logger.warning("presenton_rework_edit_failed", **safe_error_fields(exc))
            raise ModelRetry("A slide could not be revised. Try again.") from exc
        # Presenton assigns a new UUID on every successful edit and returns the
        # updated slide; track it so a second comment on the same slide targets
        # the current id instead of the stale one (which would 404).
        if isinstance(edited, dict) and edited.get("id"):
            by_index[comment.slide_index] = edited
        # Persist immediately: Presenton has already committed this edit, so a
        # later comment's failure must not leave this one unresolved (a retry
        # would reapply it and compound non-idempotent changes).
        await _mark_resolved([comment.pk])
        resolved_ids.append(comment.pk)
        edited_slides.add(comment.slide_index)

    # Snapshot the revised deck so the version history reflects the rework.
    if resolved_ids:
        try:
            revised_deck = await client.get_presentation(str(link.presentation_id))
            await record_version(link, revised_deck, "rework")
        except PresentonError as exc:
            logger.warning("presenton_rework_snapshot_failed", **safe_error_fields(exc))

    # Re-export so the card's download link reflects the revised deck.
    download_url = None
    try:
        result = await client.edit_presentation(str(link.presentation_id), [], export_as="pptx")
        if result.get("path"):
            download_url = client.export_url(result["path"])
    except PresentonError as exc:
        logger.warning("presenton_rework_export_failed", **safe_error_fields(exc))

    card = {
        "presentation_id": str(link.presentation_id),
        "link_id": str(link.pk),
        "title": link.title,
        "slide_count": len(slides),
        "editor_url": client.editor_url(str(link.presentation_id)),
        "download_url": download_url,
    }

    logger.info(
        "presenton_deck_revised",
        presentation_id=str(link.presentation_id),
        comments_resolved=len(resolved_ids),
        slides_edited=sorted(edited_slides),
        conversation_id=ctx.deps.conversation.pk,
    )

    return ToolReturn(
        return_value=(
            f"The presentation '{link.title}' was revised: {len(resolved_ids)} "
            f"comment(s) addressed across {len(edited_slides)} slide(s). The deck "
            "card in the chat is up to date. Tell the user the changes are ready "
            "to review; do not restate the deck's content."
        ),
        metadata={"presentation": card},
    )
