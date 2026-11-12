"""Factories for chat application."""

from uuid import uuid4

import factory.django

from core.factories import UserFactory

from . import models


class ChatProjectFactory(factory.django.DjangoModelFactory):
    """Factory for creating Project instances."""

    title = factory.Sequence(lambda n: f"title {n}")
    owner = factory.SubFactory(UserFactory)
    icon = factory.fuzzy.FuzzyChoice(models.ChatProjectIcon)
    color = factory.fuzzy.FuzzyChoice(models.ChatProjectColor)

    class Meta:
        model = models.ChatProject
        skip_postgeneration_save = True

    @factory.post_generation
    def number_of_conversations(self, create, extracted, **kwargs):
        """Create attached conversations for the project."""
        if not create or not extracted:
            return

        if not isinstance(extracted, int):
            raise TypeError("number_of_conversations must be an integer")
        ChatConversationFactory.create_batch(extracted, project=self, owner=self.owner)


class ChatConversationFactory(factory.django.DjangoModelFactory):
    """Factory for creating ChatConversation instances."""

    owner = factory.SubFactory(UserFactory)

    class Meta:
        model = models.ChatConversation


class ChatConversationAttachmentFactory(factory.django.DjangoModelFactory):
    """Factory for creating ChatConversationAttachment instances."""

    conversation = factory.SubFactory(ChatConversationFactory)
    uploaded_by = factory.SubFactory(UserFactory)
    key = factory.LazyAttribute(
        lambda obj: f"{obj.conversation.pk}/attachments/{uuid4()}.{obj.file_name.split('.')[-1]}"
    )
    file_name = factory.Faker("file_name")
    content_type = factory.Faker("mime_type")

    class Meta:
        model = models.ChatConversationAttachment


class ChatProjectAttachmentFactory(factory.django.DjangoModelFactory):
    """Factory for creating project-scoped attachment instances."""

    conversation = None
    project = factory.SubFactory(ChatProjectFactory)
    uploaded_by = factory.SubFactory(UserFactory)
    key = factory.LazyAttribute(
        lambda obj: f"{obj.project.pk}/attachments/{uuid4()}.{obj.file_name.split('.')[-1]}"
    )
    file_name = factory.Faker("file_name")
    content_type = factory.Faker("mime_type")

    class Meta:
        model = models.ChatConversationAttachment


class ChatPresentationLinkFactory(factory.django.DjangoModelFactory):
    """Factory for conversation-to-Presenton deck links (slides-loop POC)."""

    conversation = factory.SubFactory(ChatConversationFactory)
    presentation_id = factory.LazyFunction(uuid4)
    title = factory.Sequence(lambda n: f"deck {n}")

    class Meta:
        model = models.ChatPresentationLink


class PresentationCommentFactory(factory.django.DjangoModelFactory):
    """Factory for slide-anchored deck comments (slides-loop POC, P4)."""

    link = factory.SubFactory(ChatPresentationLinkFactory)
    author = factory.SubFactory(UserFactory)
    slide_index = factory.Sequence(lambda n: n)
    field = ""
    body = factory.Sequence(lambda n: f"feedback {n}")
    resolved = False

    class Meta:
        model = models.PresentationComment


class PresentationVersionFactory(factory.django.DjangoModelFactory):
    """Factory for deck version snapshots (slides-loop POC, P5)."""

    link = factory.SubFactory(ChatPresentationLinkFactory)
    number = factory.Sequence(lambda n: n + 1)
    source = models.PresentationVersion.Source.GENERATED
    slides = factory.LazyFunction(list)
    slide_count = 0

    class Meta:
        model = models.PresentationVersion
