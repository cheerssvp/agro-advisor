"""Offline smoke tests for the FastAPI backend (api.py).

Only exercises paths that don't need a real Gemini API call: health check and
guardrail rejection (which fails before any agent/network call happens). The
success path is covered manually/live -- see README -- since it needs a real
API key and isn't deterministic/free to run in CI.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_advisory_rejects_disallowed_extension():
    response = client.post(
        "/advisory",
        files={"photo": ("leaf.txt", b"not an image", "text/plain")},
        data={"location": "Ludhiana, Punjab, India", "crop": "wheat"},
    )
    assert response.status_code == 200
    assert "data: " in response.text
    assert "Unsupported file type" in response.text


def test_advisory_requires_required_fields():
    response = client.post(
        "/advisory",
        files={"photo": ("leaf.jpg", b"fake bytes", "image/jpeg")},
        data={"location": "Ludhiana, Punjab, India"},  # missing crop
    )
    assert response.status_code == 422


def test_advisory_success_returns_trace(monkeypatch):
    import api
    import json
    from advisor import AdvisoryResult

    async def fake_stream_advisory(photo_path, location, crop, pincode, language):
        yield {"type": "event", "author": "Mock", "text": "progress"}
        yield {
            "type": "final",
            "result": AdvisoryResult(
                final="## Crop Health\n✅ Do now: spray",
                crop_health="rust, severe",
                weather="spray this afternoon",
                market="₹24.5/kg, above MSP",
            )
        }

    monkeypatch.setattr(api, "stream_advisory", fake_stream_advisory)

    response = client.post(
        "/advisory",
        files={"photo": ("leaf.jpg", b"fakejpegbytes", "image/jpeg")},
        data={"location": "Ludhiana, Punjab, India", "crop": "wheat", "language": "Hindi"},
    )
    assert response.status_code == 200
    lines = [line for line in response.text.split("\n") if line.startswith("data: ")]
    assert len(lines) == 2
    body = json.loads(lines[-1][6:])
    assert body["language"] == "Hindi"
    assert body["trace"] == {
        "crop_health": "rust, severe",
        "weather": "spray this afternoon",
        "market": "₹24.5/kg, above MSP",
    }


def test_tts_rejects_empty_text():
    # Emoji/markdown-only text strips to nothing -> 400 before any gTTS call.
    response = client.post("/tts", data={"text": "✅ 📅 🔎 ##", "language": "Hindi"})
    assert response.status_code == 400


def test_tts_returns_audio(monkeypatch):
    import api

    class FakeTTS:
        def __init__(self, text, lang):
            self.text = text
            self.lang = lang
            assert lang == "hi"  # "Hindi" resolved to the gTTS code

        def write_to_fp(self, fp):
            fp.write(b"ID3fake-mp3-bytes")

    monkeypatch.setattr("gtts.gTTS", FakeTTS)

    response = client.post(
        "/tts", data={"text": "अभी छिड़काव करें", "language": "Hindi"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3fake-mp3-bytes"
