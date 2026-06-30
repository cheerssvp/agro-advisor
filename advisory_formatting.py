"""Pure parsing helpers for the agent's fixed advisory markdown format.

Separated from streamlit_app.py (which executes as a script with side
effects on import) so this logic is testable in isolation.
"""

from __future__ import annotations

import re

# Positional icons: the orchestrator always emits exactly these three sections
# in this order. Keyed by position rather than heading text so the cards still
# get the right icon even when the headings are translated to another language.
SECTION_ICONS_BY_POSITION = ["🌾", "🌦️", "💰"]
CONFIDENCE_COLORS = {"HIGH": "#16a34a", "MEDIUM": "#d97706", "LOW": "#dc2626"}

_SECTION_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
# Split on the emoji bullets only -- these are stable across languages, so
# parsing keeps working when the advisory text itself is Hindi/Tamil/etc.
_MARKER_RE = re.compile(r"(✅|⚠️|📅|🔎)")
_EMOJI_TO_KEY = {"✅": "do_now", "⚠️": "avoid", "📅": "next_step", "🔎": "confidence"}
# Strips an optional leading "Label:" after the emoji (English "Do now:" or a
# translated equivalent like "अभी करें:") so the card shows just the content.
_LEADING_LABEL_RE = re.compile(r"^[^:\n]{0,40}:\s*")


def _parse_section_body(body: str) -> dict[str, str]:
    parts = _MARKER_RE.split(body)
    result = {}
    for i in range(1, len(parts) - 1, 2):
        emoji, text = parts[i], parts[i + 1].strip()
        key = _EMOJI_TO_KEY.get(emoji)
        if key:
            result[key] = _LEADING_LABEL_RE.sub("", text).strip()
    return result


def parse_advisory(markdown_text: str) -> dict[str, dict[str, str]]:
    """Splits the agent's fixed `## Heading` / emoji-bullet markdown format
    into structured sections, e.g. {"Crop Health": {"do_now": ..., "avoid":
    ..., "next_step": ..., "confidence": ...}, ...}. Returns {} if the text
    doesn't match the expected format -- callers should fall back to
    rendering the raw markdown in that case."""
    parts = _SECTION_HEADING_RE.split(markdown_text)
    sections = {}
    for i in range(1, len(parts) - 1, 2):
        heading, body = parts[i].strip(), parts[i + 1]
        parsed = _parse_section_body(body)
        if parsed:
            sections[heading] = parsed
    return sections


def confidence_color(text: str) -> str:
    for level, color in CONFIDENCE_COLORS.items():
        if level in text.upper():
            return color
    return "#6b7280"
