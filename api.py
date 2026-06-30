"""FastAPI backend exposing the multi-agent advisory pipeline over HTTP.

A thin client (streamlit_app.py, or any future WhatsApp bot / mobile app)
calls POST /advisory; this process owns the actual ADK agents/MCP server.

Run with: uv run uvicorn api:app --reload
"""

from __future__ import annotations

import io
import json
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before importing agents.* -- they read env vars at import time

from observability import flush_tracing, setup_langsmith_tracing

setup_langsmith_tracing()  # no-op unless LANGSMITH_API_KEY is set

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from advisor import run_advisory, stream_advisory
from languages import resolve_language
from security.guardrails import GuardrailError

# Markdown/structure noise we don't want the text-to-speech voice to read out.
_TTS_STRIP_RE = re.compile(r"[#*`✅⚠️📅🔎🌾🌦️💰]")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    flush_tracing()


app = FastAPI(title="AgroAdvisor API", lifespan=lifespan)

# Local demo only (no live public endpoint per the project's scope) -- open
# CORS so a separately-running Streamlit/other client can call this freely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/advisory")
async def advisory(
    photo: UploadFile = File(...),
    location: str = Form(...),
    crop: str = Form(...),
    pincode: str | None = Form(None),
    language: str = Form("English"),
) -> StreamingResponse:
    suffix = Path(photo.filename or "").suffix or ".jpg"
    photo_bytes = await photo.read()
    lang = resolve_language(language)

    async def generate():
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(photo_bytes)
            tmp.flush()
            try:
                async for event in stream_advisory(
                    Path(tmp.name), location, crop, pincode or None, lang.name
                ):
                    if event["type"] == "final":
                        result = event["result"]
                        payload = {
                            "type": "final",
                            "advisory": result.final,
                            "language": lang.name,
                            "trace": {
                                "crop_health": result.crop_health,
                                "weather": result.weather,
                                "market": result.market,
                            },
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                    else:
                        yield f"data: {json.dumps(event)}\n\n"
            except GuardrailError as exc:
                yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/tts")
async def tts(text: str = Form(...), language: str = Form("English")) -> Response:
    """Text-to-speech for the advisory, so a low-literacy farmer can LISTEN.

    Uses gTTS (free, keyless, supports Hindi/Punjabi/Tamil/Telugu/etc.).
    Strips markdown/emoji noise first so the voice reads clean sentences.
    Returns audio/mpeg bytes.
    """
    from gtts import gTTS

    clean = _TTS_STRIP_RE.sub("", text).strip()
    if not clean:
        raise HTTPException(status_code=400, detail="No text to speak")

    lang = resolve_language(language)
    try:
        buffer = io.BytesIO()
        gTTS(text=clean, lang=lang.tts).write_to_fp(buffer)
    except Exception as exc:  # gTTS raises various network/value errors
        raise HTTPException(status_code=502, detail=f"Text-to-speech failed: {exc}") from exc

    return Response(content=buffer.getvalue(), media_type="audio/mpeg")
