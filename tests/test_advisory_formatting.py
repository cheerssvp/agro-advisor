"""Offline tests for advisory_formatting.py -- pure markdown parsing, no
Streamlit/network/agent calls involved."""

from __future__ import annotations

from advisory_formatting import confidence_color, parse_advisory

SAMPLE_ADVISORY = """## Crop Health
✅ Do now: Your wheat has rust that can spread; contact KVK Samrala for fungicide product and amount.
⚠️ Avoid: Do not delay treatment, as the disease can spread fast.
📅 Next step: Get specific fungicide details from Krishi Vigyan Kendra, Samrala.
🔎 Confidence: HIGH confidence that your crop has wheat rust disease.

## Weather
✅ Do now: Spray today afternoon if wind is calm and no rain comes.
⚠️ Avoid: Spraying tomorrow or the day after due to high wind or rain.
📅 Next step: Check the rain forecast again very close to today's afternoon spray time.
🔎 Confidence: LOW confidence in today's rain forecast.

## Market
✅ Do now: You can wait to sell if you have dry storage and don't need cash right now.
⚠️ Avoid: Expecting a large price increase soon, as the trend is stable.
📅 Next step: Confirm current prices with your local mandi committee.
🔎 Confidence: MEDIUM confidence in this sample price figure.
"""


def test_parse_advisory_extracts_all_sections_and_fields():
    sections = parse_advisory(SAMPLE_ADVISORY)
    assert set(sections) == {"Crop Health", "Weather", "Market"}

    crop_health = sections["Crop Health"]
    assert "rust" in crop_health["do_now"]
    assert "delay treatment" in crop_health["avoid"]
    assert "Krishi Vigyan Kendra" in crop_health["next_step"]
    assert "HIGH" in crop_health["confidence"]


def test_parse_advisory_strips_english_labels():
    sections = parse_advisory(SAMPLE_ADVISORY)
    # The "Do now:" / "Avoid:" labels are stripped, leaving just the content.
    assert not sections["Crop Health"]["do_now"].lower().startswith("do now")
    assert not sections["Crop Health"]["avoid"].lower().startswith("avoid")


# A Hindi advisory: headings + bullet labels translated, but the emoji bullets
# and the HIGH/LOW confidence token kept (exactly as the writer is instructed).
HINDI_ADVISORY = """## फसल स्वास्थ्य
✅ अभी करें: आपकी गेहूं की फसल में रतुआ रोग है, तुरंत KVK से संपर्क करें।
⚠️ बचें: इलाज में देरी न करें।
📅 अगला कदम: सही दवा के लिए कृषि विज्ञान केंद्र से पूछें।
🔎 विश्वास: HIGH, हमें रतुआ रोग का पूरा यकीन है।

## मौसम
✅ अभी करें: आज दोपहर छिड़काव करें।
⚠️ बचें: कल छिड़काव न करें।
📅 अगला कदम: छिड़काव से पहले मौसम देखें।
🔎 विश्वास: LOW, आज बारिश का पूर्वानुमान अनिश्चित है।

## बाज़ार
✅ अभी करें: अभी कीमत MSP से ऊपर है।
⚠️ बचें: केवल इस कीमत पर भरोसा न करें।
📅 अगला कदम: अपनी मंडी में आज की कीमत जांचें।
🔎 विश्वास: MEDIUM, यह एक नमूना कीमत है।
"""


def test_parse_advisory_is_language_agnostic():
    sections = parse_advisory(HINDI_ADVISORY)
    # Three sections parsed even though the headings are in Hindi.
    assert len(sections) == 3
    first = next(iter(sections.values()))
    # All four emoji-keyed fields extracted from the Hindi text.
    assert set(first) == {"do_now", "avoid", "next_step", "confidence"}
    # Confidence colour still detectable because HIGH/LOW/MEDIUM stay English.
    assert "HIGH" in first["confidence"]
    assert confidence_color(first["confidence"]) == "#16a34a"


def test_parse_advisory_returns_empty_for_unrecognized_format():
    assert parse_advisory("Just some plain text, not our markdown format.") == {}


def test_confidence_color_maps_known_levels():
    assert confidence_color("HIGH confidence here") == "#16a34a"
    assert confidence_color("medium confidence") == "#d97706"
    assert confidence_color("Low confidence") == "#dc2626"
    assert confidence_color("unclear") == "#6b7280"
