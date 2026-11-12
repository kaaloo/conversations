"""Tests for deck-card metadata attachment on reload (POC, P3)."""

from pydantic_ai.messages import ModelRequest, ToolReturnPart

from chat.ai_sdk_types import ToolUIPart, UIMessage
from chat.clients.pydantic_ui_message_converter import (
    attach_tool_presentations,
    tool_presentation,
)

CARD = {"presentation_id": "p-1", "title": "Deck", "slide_count": 3}


def _request_with_return(tool_call_id: str, metadata) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_call_id=tool_call_id,
                tool_name="generate_presentation_sidecar",
                content="generated",
                metadata=metadata,
            )
        ],
        kind="request",
    )


def _ui_message_with_tool_part(tool_call_id: str) -> UIMessage:
    return UIMessage(
        id="m-1",
        role="assistant",
        parts=[
            ToolUIPart(
                type="tool-generate_presentation_sidecar",
                toolCallId=tool_call_id,
                state="input-available",
            )
        ],
    )


def test_tool_presentation_reads_metadata():
    """The card is read from the tool return's presentation metadata key."""
    part = ToolReturnPart(
        tool_call_id="c-1",
        tool_name="generate_presentation_sidecar",
        content="ok",
        metadata={"presentation": CARD},
    )
    assert tool_presentation(part) == CARD


def test_tool_presentation_none_without_metadata():
    """Returns without presentation metadata yield None."""
    part = ToolReturnPart(tool_call_id="c-1", tool_name="other", content="ok", metadata=None)
    assert tool_presentation(part) is None


def test_attach_sets_output_and_state():
    """The matching tool part gets the card as output and becomes available."""
    ui_message = _ui_message_with_tool_part("c-1")
    request = _request_with_return("c-1", {"presentation": CARD})

    attach_tool_presentations(ui_message, request)

    part = ui_message.parts[0]
    assert part.state == "output-available"
    assert part.output == {"presentation": CARD}


def test_attach_ignores_unrelated_tool_returns():
    """A return without presentation metadata leaves the part untouched."""
    ui_message = _ui_message_with_tool_part("c-1")
    request = _request_with_return("c-1", {"chart": {"data": []}})

    attach_tool_presentations(ui_message, request)

    part = ui_message.parts[0]
    assert part.state == "input-available"
    assert part.output is None


def test_attach_matches_by_tool_call_id():
    """Only the part whose toolCallId matches the return is updated."""
    ui_message = _ui_message_with_tool_part("c-1")
    request = _request_with_return("c-OTHER", {"presentation": CARD})

    attach_tool_presentations(ui_message, request)

    assert ui_message.parts[0].output is None
