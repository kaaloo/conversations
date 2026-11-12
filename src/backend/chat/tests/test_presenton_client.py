"""Tests for the Presenton sidecar client (slides-loop POC, P2).

The HTTP boundary is mocked with httpx.MockTransport-shaped patches: these
tests prove URL construction, auth headers, payload shapes and error
translation, not Presenton's behavior (the live spike in bin/presenton-spike
covers that).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from chat.presenton_client import PresentonClient, PresentonError


@pytest.fixture(name="presenton_settings")
def presenton_settings_fixture(settings):
    """Configure a sidecar endpoint for the client."""
    settings.PRESENTON_BASE_URL = "http://presenton.example.com/"
    settings.PRESENTON_API_KEY = "sk-presenton-test"
    settings.PRESENTON_API_TIMEOUT = 15
    return settings


@pytest.fixture(name="client")
def client_fixture(presenton_settings):  # pylint: disable=unused-argument
    """Instantiate a PresentonClient with test settings."""
    return PresentonClient()


def _fake_response(json_body=None, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = b"{}" if json_body is not None else b""
    response.json.return_value = json_body
    response.raise_for_status.return_value = None
    return response


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_client_builds_api_url(presenton_settings):  # pylint: disable=unused-argument
    """Trailing slashes on the base URL must not double up in the API URL."""
    assert PresentonClient().api_url == "http://presenton.example.com/api/v1/ppt/"


def test_client_unconfigured_is_inert(settings):
    """Without PRESENTON_BASE_URL the client is inert and calls raise."""
    settings.PRESENTON_BASE_URL = None
    client = PresentonClient()
    assert client.configured is False
    with pytest.raises(PresentonError, match="not configured"):
        client.editor_url("some-id")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_unconfigured_request_raises(settings):
    """An unconfigured client must fail before any HTTP call."""
    settings.PRESENTON_BASE_URL = None
    with pytest.raises(PresentonError, match="not configured"):
        await PresentonClient().get_presentation("some-id")


# ---------------------------------------------------------------------------
# Request plumbing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_generate_async_posts_brief_and_options(client):
    """generate_async posts the brief plus pass-through options to the v1 path."""
    fake = _fake_response({"id": "task-1", "status": "pending"})
    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake)) as mock_req:
        result = await client.generate_async("a brief", n_slides=4, language="English")
    assert result == {"id": "task-1", "status": "pending"}
    args, kwargs = mock_req.call_args
    assert args[0] == "POST"
    assert args[1] == "http://presenton.example.com/api/v1/ppt/presentation/generate/async"
    assert kwargs["json"] == {"content": "a brief", "n_slides": 4, "language": "English"}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_api_key_sent_as_bearer(client):
    """The API key must travel as a Bearer header, never in the URL."""
    fake = _fake_response({"id": "p-1", "slides": []})
    real_init = httpx.AsyncClient.__init__
    captured = {}

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake)):
        with patch.object(httpx.AsyncClient, "__init__", spy_init):
            await client.get_presentation("p-1")
    headers = captured["headers"]
    assert headers["Authorization"] == "Bearer sk-presenton-test"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_no_auth_header_without_key(presenton_settings):
    """DISABLE_AUTH sidecars need no key; the header must then be absent."""
    presenton_settings.PRESENTON_API_KEY = None
    fake = _fake_response({"id": "p-1", "slides": []})
    real_init = httpx.AsyncClient.__init__
    captured = {}

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake)):
        with patch.object(httpx.AsyncClient, "__init__", spy_init):
            await PresentonClient().get_presentation("p-1")
    headers = captured["headers"]
    assert "Authorization" not in headers


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_edit_presentation_payload(client):
    """edit sends presentation_id, targeted slides and export_as."""
    fake = _fake_response({"presentation_id": "p-1", "path": "/x.pptx", "edit_path": "/e"})
    slides = [{"index": 0, "content": {"title": "New"}}]
    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake)) as mock_req:
        await client.edit_presentation("p-1", slides)
    args, kwargs = mock_req.call_args
    assert args[1].endswith("/presentation/edit")
    assert kwargs["json"] == {
        "presentation_id": "p-1",
        "slides": slides,
        "export_as": "pptx",
    }


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_derive_presentation_payload(client):
    """derive uses the same payload shape on the derive path."""
    fake = _fake_response({"presentation_id": "p-2", "path": "/x.pptx", "edit_path": "/e"})
    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake)) as mock_req:
        result = await client.derive_presentation("p-1", [{"index": 0, "content": {}}])
    assert result["presentation_id"] == "p-2"
    assert mock_req.call_args.args[1].endswith("/presentation/derive")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_http_error_translated(client):
    """HTTP errors surface as PresentonError, not raw httpx exceptions."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 500
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=response
    )
    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=response)):
        with pytest.raises(PresentonError, match="HTTP 500"):
            await client.get_presentation("p-1")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_transport_error_translated(client):
    """Connection failures surface as PresentonError."""
    with patch(
        "httpx.AsyncClient.request",
        new=AsyncMock(side_effect=httpx.ConnectError("refused")),
    ):
        with pytest.raises(PresentonError, match="request failed"):
            await client.get_presentation("p-1")


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def test_editor_url(client):
    """The editor URL is the framable self-hosted page, no token parameter."""
    assert client.editor_url("abc") == "http://presenton.example.com/presentation?id=abc"


def test_export_url_relative_and_absolute(client):
    """Server-local export paths become absolute; absolute URLs pass through."""
    assert (
        client.export_url("/app_data/exports/x.pptx")
        == "http://presenton.example.com/app_data/exports/x.pptx"
    )
    assert client.export_url("http://other/x.pptx") == "http://other/x.pptx"
