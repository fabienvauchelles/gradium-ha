"""Runtime data kept on the config entry, and the language and voice rules of the adapters."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .client import GradiumClient, Voice
from .const import LANGUAGE_REGIONS, SUPPORTED_LANGUAGES


@dataclass(slots=True)
class GradiumRuntimeData:
    """What a loaded entry holds: the client and the voice list read at setup."""

    client: GradiumClient
    voices: list[Voice]


type GradiumConfigEntry = ConfigEntry[GradiumRuntimeData]


def base_language(language: str) -> str:
    """Return the primary subtag of a language tag: "fr-FR" gives "fr"."""
    return language.replace("_", "-").split("-", 1)[0].lower()


def supported_language_tags() -> list[str]:
    """Return every language tag the STT entity accepts: each base code, then its regions."""
    return [
        tag
        for base in SUPPORTED_LANGUAGES
        for tag in (base, *(f"{base}-{region}" for region in LANGUAGE_REGIONS.get(base, ())))
    ]


def voices_for_language(voices: list[Voice], language: str) -> list[Voice]:
    """Return the catalog voices speaking `language` plus every custom voice, sorted by name.

    Custom voices carry no reliable language, so they are always offered.
    """
    wanted = base_language(language)
    selected = [
        voice
        for voice in voices
        if not voice.is_catalog
        or (voice.language is not None and base_language(voice.language) == wanted)
    ]
    return sorted(selected, key=lambda voice: voice.name.casefold())
