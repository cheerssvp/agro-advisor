"""Supported output languages for the advisory + voice.

One source of truth shared by cli.py, api.py, and streamlit_app.py. Each
entry maps a human-facing label to:
  - `name`: how the advisory_writer agent should refer to the language
    (passed into the prompt; Gemini writes the final advisory in it)
  - `tts`: the gTTS language code for the "Listen" audio

Languages chosen to cover the states the data tools support (Punjabi,
Hindi-belt, Tamil, Telugu, Bengali, etc.) -- the whole point is that a
low-literacy farmer can read/hear the advice in their own language, not
just English.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    label: str  # shown in the UI dropdown
    name: str  # natural-language name handed to the writer agent
    tts: str  # gTTS language code


LANGUAGES: dict[str, Language] = {
    "English": Language("English", "English", "en"),
    "हिंदी (Hindi)": Language("हिंदी (Hindi)", "Hindi", "hi"),
    "ਪੰਜਾਬੀ (Punjabi)": Language("ਪੰਜਾਬੀ (Punjabi)", "Punjabi", "pa"),
    "தமிழ் (Tamil)": Language("தமிழ் (Tamil)", "Tamil", "ta"),
    "తెలుగు (Telugu)": Language("తెలుగు (Telugu)", "Telugu", "te"),
    "বাংলা (Bengali)": Language("বাংলা (Bengali)", "Bengali", "bn"),
    "मराठी (Marathi)": Language("मराठी (Marathi)", "Marathi", "mr"),
    "ગુજરાતી (Gujarati)": Language("ગુજરાતી (Gujarati)", "Gujarati", "gu"),
    "ಕನ್ನಡ (Kannada)": Language("ಕನ್ನಡ (Kannada)", "Kannada", "kn"),
}

DEFAULT_LANGUAGE = "English"


def resolve_language(name_or_label: str | None) -> Language:
    """Resolves a UI label OR a bare language name (e.g. 'Hindi') to a
    Language, falling back to English for anything unrecognized."""
    if not name_or_label:
        return LANGUAGES[DEFAULT_LANGUAGE]
    if name_or_label in LANGUAGES:
        return LANGUAGES[name_or_label]
    for lang in LANGUAGES.values():
        if lang.name.lower() == name_or_label.strip().lower():
            return lang
    return LANGUAGES[DEFAULT_LANGUAGE]
