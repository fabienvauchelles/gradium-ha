"""Gradium REST API: the voice listing and the credit balance.

Both are plain authenticated reads; the credit balance also serves as the API
key check.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import aiohttp

from .const import API_KEY_HEADER
from .errors import (
    GradiumAuthError,
    GradiumConnectionError,
    GradiumServerError,
    GradiumTimeoutError,
)
from .models import Credits, Endpoint, Voice

_AUTH_STATUSES = {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}


class GradiumRestApi:
    """Authenticated GET requests against the Gradium REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        endpoint: Endpoint,
        timeout: float,
    ) -> None:
        """Store the shared session, the key and the total time budget of a call."""
        self._session = session
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout

    async def get_json(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        """GET `path` below the REST base and return the decoded JSON body."""
        try:
            async with asyncio.timeout(self._timeout):
                return await self._fetch(path, params)
        except TimeoutError as err:
            raise GradiumTimeoutError(
                f"Gradium did not answer GET {path} in time (connect, {self._timeout} s)"
            ) from err
        except aiohttp.ClientError as err:
            raise GradiumConnectionError(f"Cannot reach Gradium for GET {path}: {err}") from err

    async def _fetch(self, path: str, params: Mapping[str, str] | None) -> Any:
        """Run the request and check its status; network errors propagate."""
        url = f"{self._endpoint.rest_base}{path}"
        headers = {API_KEY_HEADER: self._api_key}
        async with self._session.get(url, params=params, headers=headers) as response:
            _raise_for_status(response.status, path)
            try:
                return await response.json(content_type=None)
            except ValueError as err:
                raise GradiumServerError(
                    f"Gradium answered GET {path} with a body that is not JSON"
                ) from err


def _raise_for_status(status: int, path: str) -> None:
    """Map a non-2xx status to a typed error."""
    if status in _AUTH_STATUSES:
        raise GradiumAuthError(f"Gradium refused the API key (HTTP {status} on GET {path})")
    if not HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        raise GradiumServerError(f"Gradium answered GET {path} with HTTP {status}", status)


def parse_voices(payload: Any) -> list[Voice]:
    """Build the voices of a `/voices/` payload, a JSON array of voice objects."""
    if not isinstance(payload, list):
        raise GradiumServerError("Gradium voice list is not a JSON array")
    return [_parse_voice(item) for item in payload]


def parse_credits(payload: Any) -> Credits:
    """Build the credit balance of a `/usages/credits` payload."""
    if not isinstance(payload, dict):
        raise GradiumServerError("Gradium credit balance is not a JSON object")
    return Credits(
        remaining=_required_int(payload, "remaining_credits", "credit balance"),
        allocated=_required_int(payload, "allocated_credits", "credit balance"),
        billing_period=_optional_str(payload, "billing_period"),
        plan_name=_optional_str(payload, "plan_name"),
    )


def _parse_voice(item: Any) -> Voice:
    """Build one voice; `uid`, `name` and `is_catalog` are required."""
    if not isinstance(item, dict):
        raise GradiumServerError("Gradium voice entry is not a JSON object")
    is_catalog = item.get("is_catalog")
    if not isinstance(is_catalog, bool):
        raise GradiumServerError("Gradium voice entry lacks a boolean is_catalog field")
    return Voice(
        uid=_required_str(item, "uid", "voice entry"),
        name=_required_str(item, "name", "voice entry"),
        language=_optional_str(item, "language"),
        gender=_optional_str(item, "gender"),
        description=_optional_str(item, "description"),
        is_catalog=is_catalog,
    )


def _required_str(payload: dict[str, Any], key: str, what: str) -> str:
    """Return a non-empty string field or raise naming the missing field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GradiumServerError(f"Gradium {what} lacks a {key} string")
    return value


def _required_int(payload: dict[str, Any], key: str, what: str) -> int:
    """Return an integer field (booleans excluded) or raise naming the missing field."""
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise GradiumServerError(f"Gradium {what} lacks a {key} integer")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    """Return a non-empty string field, None when absent, null or empty."""
    value = payload.get(key)
    return value if isinstance(value, str) and value else None
