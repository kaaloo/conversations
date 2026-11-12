"""Slide-anchored comments on sidecar decks (slides-loop POC, P4).

Comments are the rework bridge: the user pins feedback to a slide in the deck
card, and the ``revise_presentation_sidecar`` tool consumes the unresolved
ones. These endpoints live on the conversation viewset (owner-scoped) so the
deck's comments inherit the conversation's access control.
"""

from django.shortcuts import get_object_or_404

import structlog
from rest_framework import decorators, status
from rest_framework.response import Response

from chat import models, serializers

logger = structlog.get_logger(__name__)


class PresentationCommentsMixin:
    """Adds deck-comment actions to a conversation viewset."""

    def _get_deck_link(self, request, pk, link_id):  # pylint: disable=unused-argument
        """Resolve a deck link owned by the conversation's owner."""
        conversation = self.get_object()
        return get_object_or_404(
            models.ChatPresentationLink,
            pk=link_id,
            conversation=conversation,
        )

    @decorators.action(
        methods=["get", "post"],
        detail=True,
        url_path="presentations/(?P<link_id>[^/.]+)/comments",
        url_name="presentation-comments",
    )
    def presentation_comments(self, request, pk, link_id=None):
        """List (GET) or pin (POST) comments on one deck."""
        link = self._get_deck_link(request, pk, link_id)

        if request.method == "GET":
            comments = link.comments.all()
            data = serializers.PresentationCommentReadSerializer(comments, many=True).data
            return Response(data)

        serializer = serializers.PresentationCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = models.PresentationComment.objects.create(
            link=link,
            author=request.user,
            slide_index=serializer.validated_data["slide_index"],
            field=serializer.validated_data.get("field", ""),
            body=serializer.validated_data["body"],
        )
        logger.info(
            "presentation_comment_created",
            link_id=str(link.pk),
            slide_index=comment.slide_index,
        )
        return Response(
            serializers.PresentationCommentReadSerializer(comment).data,
            status=status.HTTP_201_CREATED,
        )

    @decorators.action(
        methods=["post"],
        detail=True,
        url_path="presentations/(?P<link_id>[^/.]+)/comments/(?P<comment_id>[^/.]+)/resolve",
        url_name="presentation-comment-resolve",
    )
    def presentation_comment_resolve(self, request, pk, link_id=None, comment_id=None):
        """Mark one comment resolved (manual override of the rework bridge)."""
        link = self._get_deck_link(request, pk, link_id)
        comment = get_object_or_404(models.PresentationComment, pk=comment_id, link=link)
        comment.resolved = True
        comment.save(update_fields=["resolved", "updated_at"])
        return Response(serializers.PresentationCommentReadSerializer(comment).data)
