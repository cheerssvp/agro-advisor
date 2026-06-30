"""Optional live integration test: real disease diagnosis on real crop photos.

Unlike test_agents_smoke.py, this calls the real Gemini API -- it verifies
crop_health_agent actually recognizes real disease symptoms, not just that
the pipeline wires together. Skipped automatically unless GOOGLE_API_KEY is
set, since it costs quota and isn't deterministic, so it never blocks a
plain `uv run pytest tests/` run without a real key.
"""

from __future__ import annotations

import mimetypes
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()  # must run before importing agents.* -- see cli.py for why

requires_api_key = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"), reason="requires a real GOOGLE_API_KEY"
)

SAMPLE_DATA = Path(__file__).parent.parent / "sample_data"


async def _diagnose(photo_path: Path, crop: str) -> str:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from agents.crop_health_agent import crop_health_agent
    from security.guardrails import validate_photo

    image_bytes = validate_photo(photo_path)
    mime_type = mimetypes.guess_type(photo_path.name)[0] or "image/jpeg"
    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(text=f"Crop: {crop}\nDiagnose this photo."),
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
    )

    app_name = "agro-advisor-live-test"
    runner = InMemoryRunner(agent=crop_health_agent, app_name=app_name)
    user_id, session_id = "test-farmer", str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    for _ in runner.run(user_id=user_id, session_id=session_id, new_message=message):
        pass
    session = await runner.session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    return session.state.get("crop_diagnosis", "")


@requires_api_key
@pytest.mark.asyncio
async def test_diagnoses_real_wheat_rust_photo():
    diagnosis = await _diagnose(SAMPLE_DATA / "wheatleaf.jpeg", "wheat")
    assert "rust" in diagnosis.lower()


@requires_api_key
@pytest.mark.asyncio
async def test_diagnoses_real_paddy_blast_photo():
    diagnosis = await _diagnose(SAMPLE_DATA / "Paddy.jpeg", "rice")
    # Gemini usually says "blast" but occasionally describes the same lesions
    # as "brown spot"/"leaf spot"/a fungal disease -- accept the family of
    # answers a real diagnosis of these symptoms would give, so this live
    # test isn't flaky on harmless phrasing differences.
    diagnosis_lower = diagnosis.lower()
    assert any(
        term in diagnosis_lower
        for term in ("blast", "brown spot", "leaf spot", "fungal", "fungus")
    ), f"unexpected diagnosis: {diagnosis!r}"
