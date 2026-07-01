"""Shared multi-agent advisory pipeline -- used by both cli.py and api.py.

Callers (cli.py, api.py) are responsible for `load_dotenv()` and
`setup_langsmith_tracing()` *before* importing this module, since importing
`agents.orchestrator` builds the agents (reading env vars like GEMINI_MODEL)
at import time.
"""

from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Callable

from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.orchestrator import root_agent
from security.guardrails import validate_photo

APP_NAME = "agro-advisor"

OnEvent = Callable[[str, str], None]


@dataclass
class AdvisoryResult:
    """The final farmer-facing advisory plus each sub-agent's own output --
    the latter is the 'behind the scenes' trace that makes the multi-agent
    pipeline (and the live data each agent pulled) visible in the UI."""

    final: str
    crop_health: str
    weather: str
    market: str


def build_message(
    photo_path: Path, location: str, crop: str, pincode: str | None, language: str = "English"
) -> types.Content:
    image_bytes = validate_photo(photo_path)
    mime_type = mimetypes.guess_type(photo_path.name)[0] or "image/jpeg"

    prompt = (
        f"Crop: {crop}\n"
        f"Location: {location}\n"
        + (f"Pincode: {pincode}\n" if pincode else "")
        + f"Output language: {language}\n"
        + "Here is a photo of the crop. Diagnose its health, then advise on weather "
        "and market timing for selling this crop."
    )
    return types.Content(
        role="user",
        parts=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
    )


async def stream_advisory(
    photo_path: Path,
    location: str,
    crop: str,
    pincode: str | None = None,
    language: str = "English",
) -> AsyncGenerator[dict, None]:
    """Runs the full multi-agent pipeline and yields intermediate agent events,
    followed by a final result.
    """
    message = build_message(photo_path, location, crop, pincode, language)

    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    user_id, session_id = "local-farmer", str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        if event.author and event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts)
            if text.strip():
                yield {"type": "event", "author": event.author, "text": text.strip()}

    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    state = session.state
    yield {
        "type": "final",
        "result": AdvisoryResult(
            final=state.get("final_advisory", "(no advisory produced)"),
            crop_health=state.get("crop_diagnosis", ""),
            weather=state.get("weather_advice", ""),
            market=state.get("market_advice", ""),
        )
    }

async def run_advisory(
    photo_path: Path,
    location: str,
    crop: str,
    pincode: str | None = None,
    language: str = "English",
    on_event: OnEvent | None = None,
) -> AdvisoryResult:
    """Convenience wrapper for backwards compatibility with cli.py."""
    result = None
    async for event in stream_advisory(photo_path, location, crop, pincode, language):
        if event["type"] == "event" and on_event:
            on_event(event["author"], event["text"])
        elif event["type"] == "final":
            result = event["result"]
    if result is None:
        raise RuntimeError("No final result produced by stream_advisory.")
    return result
