"""Client for the Presenton sidecar's self-hosted v1 API (slides-loop POC).

Presenton (https://github.com/presenton/presenton) runs next to Conversations
and owns deck generation, the canvas editor and PPTX export. This client is
the only place that talks to it; the API key stays server-side and never
reaches the browser.

Endpoint shapes follow the published self-hosted OpenAPI (v1): generate is
async (task id -> status polling), edit deep-merges targeted slide content,
derive produces a modified copy while preserving the original.
"""

from urllib.parse import urljoin

from django.conf import settings

import httpx

from core import instrumentation


class PresentonError(Exception):
    """Raised when the sidecar is unreachable or answers with an error."""


class PresentonClient:
    """Async client for one Presenton instance.

    Instantiate per call (cheap): it reads base URL, API key and timeout from
    settings at construction, like ``DocsClient``. When ``PRESENTON_BASE_URL``
    is unset the client is inert and every call raises ``PresentonError``.
    """

    def __init__(self):
        self.base_url = (settings.PRESENTON_BASE_URL or "").rstrip("/")
        self.api_key = settings.PRESENTON_API_KEY
        self.timeout = settings.PRESENTON_API_TIMEOUT
        self.api_url = f"{self.base_url}/api/v1/ppt/" if self.base_url else ""

    @property
    def configured(self) -> bool:
        """Whether a sidecar base URL is configured."""
        return bool(self.base_url)

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(self, method: str, path: str, operation: str, **kwargs):
        if not self.configured:
            raise PresentonError("PRESENTON_BASE_URL is not configured")
        url = urljoin(self.api_url, path)
        try:
            with instrumentation.outgoing_request("presenton", operation) as observed:
                async with httpx.AsyncClient(
                    timeout=self.timeout, headers=self._headers()
                ) as client:
                    response = await client.request(method, url, **kwargs)
                observed.status = response.status_code
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PresentonError(
                f"Presenton {operation} failed with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise PresentonError(f"Presenton {operation} request failed: {exc}") from exc
        return response.json() if response.content else None

    async def generate_async(self, brief: str, **options) -> dict:
        """Start an async generation task; returns the task model (id, status).

        ``options`` are passed through to ``GeneratePresentationRequest``
        (n_slides, language, template, instructions, export_as, ...).
        """
        payload = {"content": brief, **options}
        return await self._request(
            "POST", "presentation/generate/async", "generate_async", json=payload
        )

    async def generation_status(self, task_id: str) -> dict:
        """Return the async task model: status is pending/completed/error."""
        return await self._request("GET", f"presentation/status/{task_id}", "generation_status")

    async def get_presentation(self, presentation_id: str) -> dict:
        """Return one presentation with its slides (PresentationWithSlides)."""
        return await self._request("GET", f"presentation/{presentation_id}", "get_presentation")

    async def edit_presentation(
        self, presentation_id: str, slides: list[dict], export_as: str = "pptx"
    ) -> dict:
        """Deep-merge targeted slide content in place; other slides preserved.

        ``slides`` is a list of ``{"index": int, "content": {...}}``. Returns
        ``{presentation_id, path, edit_path}``.
        """
        return await self._request(
            "POST",
            "presentation/edit",
            "edit_presentation",
            json={
                "presentation_id": presentation_id,
                "slides": slides,
                "export_as": export_as,
            },
        )

    async def derive_presentation(
        self, presentation_id: str, slides: list[dict], export_as: str = "pptx"
    ) -> dict:
        """Create a modified copy, preserving the original (versioning).

        Same payload as ``edit_presentation``; the returned presentation_id is
        a NEW deck.
        """
        return await self._request(
            "POST",
            "presentation/derive",
            "derive_presentation",
            json={
                "presentation_id": presentation_id,
                "slides": slides,
                "export_as": export_as,
            },
        )

    def editor_url(self, presentation_id: str) -> str:
        """Browser URL of the canvas editor for one deck (framable, no token).

        The self-hosted editor has no per-deck scoped tokens (that is Cloud
        v3); in the POC the sidecar runs single-user and the URL is embedded
        in an iframe. See docs/presenton-sidecar.md for the auth posture.
        """
        if not self.configured:
            raise PresentonError("PRESENTON_BASE_URL is not configured")
        return f"{self.base_url}/presentation?id={presentation_id}"

    def export_url(self, path: str) -> str:
        """Absolute URL for an export path returned by the API.

        The API returns server-local paths like ``/app_data/exports/...``;
        they are served by the same origin as the editor.
        """
        if not self.configured:
            raise PresentonError("PRESENTON_BASE_URL is not configured")
        if path.startswith("http"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"
