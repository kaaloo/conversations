"""Version history for sidecar decks (slides-loop POC, P5).

Lists the deck's recorded versions, restores one by re-applying its slide
content to the live deck (deep-merge edit), and exports the current deck.
Owner-scoped via the conversation viewset.
"""

from django.shortcuts import get_object_or_404

import structlog
from asgiref.sync import async_to_sync
from rest_framework import decorators, status
from rest_framework.response import Response

from chat import models, serializers
from chat.presentation_versions import record_version
from chat.presenton_client import PresentonClient, PresentonError

logger = structlog.get_logger(__name__)


class PresentationVersionsMixin:
    """Adds deck version actions to a conversation viewset."""

    def _get_deck_link(self, request, pk, link_id):  # pylint: disable=unused-argument
        conversation = self.get_object()
        return get_object_or_404(models.ChatPresentationLink, pk=link_id, conversation=conversation)

    @decorators.action(
        methods=["get"],
        detail=True,
        url_path="presentations/(?P<link_id>[^/.]+)/versions",
        url_name="presentation-versions",
    )
    def presentation_versions(self, request, pk, link_id=None):
        """List the deck's versions, newest first."""
        link = self._get_deck_link(request, pk, link_id)
        versions = link.versions.all().order_by("-number")
        data = serializers.PresentationVersionReadSerializer(versions, many=True).data
        return Response(data)

    @decorators.action(
        methods=["post"],
        detail=True,
        url_path="presentations/(?P<link_id>[^/.]+)/versions/(?P<number>[0-9]+)/restore",
        url_name="presentation-version-restore",
    )
    def presentation_version_restore(self, request, pk, link_id=None, number=None):
        """Restore a version by re-applying its content to the live deck.

        The sidecar's v1 edit endpoint deep-merges slide content and has no
        replacement operation, so restore reverts the content of the slides
        present in the snapshot but cannot remove slides or content keys that
        were added after it. The response flags that case so the caller knows
        the result is a merge, not a byte-for-byte rollback.
        """
        link = self._get_deck_link(request, pk, link_id)
        version = get_object_or_404(models.PresentationVersion, link=link, number=number)

        client = PresentonClient()
        slides = [
            {"index": s["index"], "content": s["content"]}
            for s in version.slides
            if s.get("index") is not None
        ]
        try:
            live_deck = async_to_sync(client.get_presentation)(str(link.presentation_id))
            live_indices = {s.get("index") for s in live_deck.get("slides", [])}
            snapshot_indices = {s["index"] for s in slides}
            extra_slides = sorted(live_indices - snapshot_indices)
            async_to_sync(client.edit_presentation)(
                str(link.presentation_id), slides, export_as="pptx"
            )
            deck = async_to_sync(client.get_presentation)(str(link.presentation_id))
        except PresentonError as exc:
            logger.warning("presenton_restore_failed", error_type=type(exc).__name__)
            return Response(
                {"detail": "The deck could not be restored. Try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        new_version = async_to_sync(record_version)(link, deck, "restore")
        logger.info(
            "presentation_version_restored",
            link_id=str(link.pk),
            restored_from=version.number,
            new_version=new_version.number,
            extra_slides=extra_slides,
        )
        data = serializers.PresentationVersionReadSerializer(new_version).data
        if extra_slides:
            data["note"] = (
                "The sidecar merges content on restore; slides added after this version were kept."
            )
        return Response(data, status=status.HTTP_201_CREATED)

    @decorators.action(
        methods=["get"],
        detail=True,
        url_path="presentations/(?P<link_id>[^/.]+)/export",
        url_name="presentation-export",
    )
    def presentation_export(self, request, pk, link_id=None):
        """Return a fresh export URL for the current deck."""
        link = self._get_deck_link(request, pk, link_id)
        client = PresentonClient()
        try:
            result = async_to_sync(client.edit_presentation)(
                str(link.presentation_id), [], export_as="pptx"
            )
        except PresentonError as exc:
            logger.warning("presenton_export_failed", error_type=type(exc).__name__)
            return Response(
                {"detail": "The deck could not be exported. Try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        path = result.get("path")
        return Response({"download_url": client.export_url(path) if path else None})
