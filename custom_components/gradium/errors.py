"""Map client errors to what Home Assistant shows, and start reauth on a refused key."""

from __future__ import annotations

import logging
from typing import NoReturn

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .client import (
    GradiumAuthError,
    GradiumConnectionError,
    GradiumCreditsExhaustedError,
    GradiumError,
    GradiumServerError,
    GradiumTimeoutError,
)
from .const import DOMAIN
from .data import GradiumConfigEntry

_LOGGER = logging.getLogger(__package__)

_TRANSLATION_KEYS: tuple[tuple[type[GradiumError], str], ...] = (
    (GradiumAuthError, "invalid_auth"),
    (GradiumCreditsExhaustedError, "credits_exhausted"),
    (GradiumConnectionError, "cannot_connect"),
    (GradiumTimeoutError, "timeout"),
    (GradiumServerError, "server_error"),
)
_FALLBACK_KEY = "server_error"


def translation_key_for(err: GradiumError) -> str:
    """Return the `exceptions` translation key matching the error class."""
    for error_class, key in _TRANSLATION_KEYS:
        if isinstance(err, error_class):
            return key
    return _FALLBACK_KEY


def log_gradium_error(err: GradiumError, action: str) -> None:
    """Log a failed Gradium call; the client guarantees the text never holds the key."""
    _LOGGER.error("Gradium could not %s: %s (%s)", action, err, type(err).__name__)


def raise_for_gradium_error(
    hass: HomeAssistant, entry: GradiumConfigEntry, err: GradiumError
) -> NoReturn:
    """Raise the translated HomeAssistantError for `err`, starting reauth on a refused key."""
    if isinstance(err, GradiumAuthError):
        entry.async_start_reauth(hass)
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=translation_key_for(err),
        translation_placeholders={"error": str(err)},
    ) from err
