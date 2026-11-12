"""Streamed tool results must carry the deck card, not just the confirmation text.

Regression for the P3 review finding: the live stream forwarded only chart
metadata, so a generated deck's card appeared on reload but never in the
active chat.
"""

from unittest.mock import MagicMock

from pydantic_ai.messages import FunctionToolResultEvent, ToolReturnPart

from chat.turn import event_mapper as event_mapper_module
from chat.turn.event_mapper import TurnEventMapper

CARD = {
    "presentation_id": "11111111-1111-1111-1111-111111111111",
    "link_id": "22222222-2222-2222-2222-222222222222",
    "title": "A Deck",
    "slide_count": 4,
    "editor_url": "http://presenton.test/presentation?id=11111111",
    "download_url": "http://presenton.test/deck.pptx",
}


def _mapper() -> TurnEventMapper:
    """A mapper with only the attributes _tool_result_events touches."""
    mapper = TurnEventMapper.__new__(TurnEventMapper)
    mapper._datagouv = MagicMock()
    mapper._datagouv.take_outage.return_value = False
    mapper.state = event_mapper_module.StreamingState()
    return mapper


def _result_event(metadata) -> FunctionToolResultEvent:
    return FunctionToolResultEvent(
        part=ToolReturnPart(
            tool_call_id="call-1",
            tool_name="generate_presentation_sidecar",
            content="The presentation was generated.",
            metadata=metadata,
        )
    )


def _tool_results(events):
    return [e for e in events if isinstance(e, event_mapper_module.events_v4.ToolResultPart)]


def test_presentation_metadata_forwarded_in_stream():
    """The deck card reaches the live stream as {presentation: card}."""
    mapper = _mapper()
    events = list(mapper._tool_result_events(_result_event({"presentation": CARD})))
    results = _tool_results(events)
    assert len(results) == 1
    assert results[0].result == {"presentation": CARD}


def test_chart_metadata_still_forwarded():
    """The existing chart path is unchanged."""
    mapper = _mapper()
    chart = {"type": "bar", "title": "T", "labels": [], "series": [], "total": 0}
    events = list(mapper._tool_result_events(_result_event({"chart": chart})))
    results = _tool_results(events)
    assert results[0].result == {"chart": chart}


def test_plain_result_unchanged():
    """A tool return without card/chart metadata streams its text content."""
    mapper = _mapper()
    events = list(mapper._tool_result_events(_result_event(None)))
    results = _tool_results(events)
    assert results[0].result == "The presentation was generated."
