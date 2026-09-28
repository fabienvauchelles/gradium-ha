"""Tell a refused API key apart from the other refusals sharing close code 1008.

Gradium answers a bad key, a missing subscription, an empty credit balance and
a request refused on policy with the same code 1008, with or without a JSON
error first; only the free text differs ("Invalid or expired API key" for a
wrong key and "No authentication provided." for a missing one, see
docs/protocol.md). Free text is no contract, so the credit balance settles it:
the REST read answers 401 to a bad key.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .errors import (
    GradiumAuthError,
    GradiumCreditsExhaustedError,
    GradiumError,
    GradiumPolicyError,
    GradiumServerError,
)
from .models import Credits


async def resolve_refusal(
    refusal: GradiumPolicyError, read_credits: Callable[[], Awaitable[Credits]]
) -> GradiumError:
    """Return the error `refusal` really is, after one credit read.

    The credit read refused: the key is bad, which starts a reauth upstream.
    No credit left: the key is fine and a reauth would not help. Anything else,
    including a credit read that failed for another reason, stays a server
    error carrying the server's message, so no reauth loop can start on a guess.
    """
    try:
        credits = await read_credits()
    except GradiumAuthError as err:
        return GradiumAuthError(f"Gradium refused the API key: {refusal.detail} ({err})")
    except GradiumError as err:
        return GradiumServerError(
            f"{refusal} (the credit check that followed failed too: {err})", refusal.code
        )
    if credits.remaining <= 0:
        return GradiumCreditsExhaustedError(
            f"Gradium has no credit left on this account: {refusal.detail}"
        )
    return GradiumServerError(str(refusal), refusal.code)
