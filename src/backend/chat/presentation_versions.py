"""Version recording for sidecar decks (slides-loop POC, P5).

Presenton mutates decks in place, so Conversations keeps its own history.
These helpers snapshot the deck's slide content into a PresentationVersion
row at generation, rework and restore time.
"""

from django.db import transaction
from django.db.models import Max

from asgiref.sync import sync_to_async

from chat.models import ChatPresentationLink, PresentationVersion


def _snapshot_slides(deck: dict) -> list:
    """Extract the slide content snapshot from a sidecar deck payload."""
    return [
        {"index": slide.get("index"), "content": slide.get("content") or {}}
        for slide in deck.get("slides", [])
    ]


@sync_to_async
def record_version(link: ChatPresentationLink, deck: dict, source: str) -> PresentationVersion:
    """Append a new version snapshot for the deck, numbered sequentially."""
    with transaction.atomic():
        # Lock the parent deck row so concurrent recordings serialize their
        # read of the current maximum; otherwise two transactions could pick
        # the same next number and one would hit the unique constraint.
        ChatPresentationLink.objects.select_for_update().get(pk=link.pk)
        next_number = (
            PresentationVersion.objects.filter(link=link).aggregate(Max("number"))["number__max"]
            or 0
        ) + 1
        slides = _snapshot_slides(deck)
        return PresentationVersion.objects.create(
            link=link,
            number=next_number,
            source=source,
            slides=slides,
            slide_count=len(slides),
        )
