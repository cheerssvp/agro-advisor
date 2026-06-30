"""Security features for the AgroAdvisor agents.

Two concerns, kept deliberately separate from agent logic:
  1. Input validation for user-supplied photos before they reach the vision model.
  2. Rate limiting on outbound MCP tool calls, wired in as an ADK
     `before_tool_callback` so it applies uniformly without touching tool code.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from google.adk.tools.base_tool import BaseTool
from google.adk.agents.context import Context

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


class GuardrailError(Exception):
    """Raised when user-supplied input fails a security check."""


def validate_photo(path: Path) -> bytes:
    """Validates a user-supplied photo and returns its bytes if safe.

    Checks: file exists, extension allow-list, size cap, and that the bytes
    actually decode as an image (rejects disguised/corrupt files) before they
    are ever sent to the vision model.
    """
    from PIL import Image, UnidentifiedImageError

    if not path.exists():
        raise GuardrailError(f"Photo not found: {path}")

    if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise GuardrailError(
            f"Unsupported file type {path.suffix!r}. Allowed: {sorted(ALLOWED_IMAGE_EXTENSIONS)}"
        )

    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise GuardrailError(f"Photo too large ({size} bytes, max {MAX_IMAGE_BYTES})")

    data = path.read_bytes()
    try:
        Image.open(path).verify()
    except UnidentifiedImageError as exc:
        raise GuardrailError(f"File is not a valid image: {path}") from exc

    return data


class ToolRateLimiter:
    """Caps how many times each MCP tool may be called within a time window.

    Used as an ADK `before_tool_callback`: returning a dict short-circuits the
    real tool call and that dict becomes the tool's result, so a misbehaving
    or looping agent can't hammer an external API indefinitely.
    """

    def __init__(self, max_calls: int = 5, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def __call__(self, tool: BaseTool, args: dict, tool_context: Context) -> dict | None:
        now = time.monotonic()
        history = self._calls[tool.name]
        history[:] = [t for t in history if now - t < self.window_seconds]

        if len(history) >= self.max_calls:
            return {
                "error": (
                    f"Rate limit exceeded for tool {tool.name!r}: "
                    f"max {self.max_calls} calls per {self.window_seconds:.0f}s"
                )
            }

        history.append(now)
        return None


# Shared across agents so the cap applies per-tool, regardless of which
# agent is calling it.
default_rate_limiter = ToolRateLimiter()
