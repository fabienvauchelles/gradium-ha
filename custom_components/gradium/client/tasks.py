"""Cleanup of the helper tasks a streaming session runs next to its main loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


async def stop_task(task: asyncio.Task[Any] | None) -> None:
    """Cancel `task` if it is still running and wait until it has ended.

    Only the task's own cancellation is absorbed: `asyncio.wait` never raises
    the task's outcome, while a cancellation of the caller still propagates.
    An error the task ended with is retrieved and logged at debug level, since
    by then the caller is already raising the error that ended the session.
    """
    if task is None:
        return
    if not task.done():
        task.cancel()
        await asyncio.wait((task,))
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        _LOGGER.debug(
            "Gradium session helper task %s ended with %s: %s",
            task.get_name(),
            type(error).__name__,
            error,
        )
