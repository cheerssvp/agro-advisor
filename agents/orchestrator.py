"""Root multi-agent orchestrator.

Pipeline:
  1. crop_health_agent diagnoses the photo                       -> state.crop_diagnosis
  2. weather_agent and market_agent run in parallel (independent) -> state.weather_advice, state.market_advice
  3. advisory_writer synthesizes all three into one farmer-facing message
"""

from __future__ import annotations

import os

import re
from typing import Any
from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.workflow import Workflow, JoinNode, START
from google.genai import types

from agents.crop_health_agent import crop_health_agent
from agents.market_agent import market_agent
from agents.weather_agent import weather_agent

def parse_input(node_input: types.Content) -> Event:
    text = "".join(p.text or "" for p in node_input.parts)
    print(f"DEBUG parse_input text: {text!r}")
    
    crop_match = re.search(r"Crop:\s*(.*)", text)
    loc_match = re.search(r"Location:\s*(.*)", text)
    pin_match = re.search(r"Pincode:\s*(.*)", text)
    lang_match = re.search(r"Output language:\s*(.*)", text)
    
    state_delta = {}
    if crop_match:
        state_delta["crop"] = crop_match.group(1).strip()
    if loc_match:
        state_delta["location"] = loc_match.group(1).strip()
    if pin_match:
        state_delta["pincode"] = pin_match.group(1).strip()
    if lang_match:
        state_delta["language"] = lang_match.group(1).strip()
        
    print(f"DEBUG parse_input state_delta: {state_delta}")
    
    # Force crop_health_agent to reason in English for consistency in trace
    clean_text = re.sub(r"Output language:\s*(.*)", "Output language: English", text)
    clean_parts = []
    for p in node_input.parts:
        if p.text:
            clean_parts.append(types.Part.from_text(text=clean_text))
        else:
            clean_parts.append(p)
            
    clean_input = types.Content(role=node_input.role, parts=clean_parts)
    return Event(output=clean_input, state=state_delta)

def prepare_weather_input(ctx: Context, node_input: Any) -> str:
    location = ctx.state.get("location", "")
    pincode = ctx.state.get("pincode", "")
    res = (
        f"Location: {location}\n"
        + (f"Pincode: {pincode}\n" if pincode else "")
    )
    print(f"DEBUG prepare_weather_input output: {res!r}")
    return res

def prepare_market_input(ctx: Context, node_input: Any) -> str:
    crop = ctx.state.get("crop", "")
    location = ctx.state.get("location", "")
    res = f"Crop: {crop}\nLocation: {location}\n"
    print(f"DEBUG prepare_market_input output: {res!r}")
    return res

advisory_writer = LlmAgent(
    name="advisory_writer",
    model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    mode="single_turn",
    description="Combines diagnosis, weather, and market advice into one advisory.",
    instruction=(
        "You are writing the final advisory for a smallholder farmer with limited literacy. "
        "You are given three findings:\n\n"
        "Crop diagnosis: {crop_diagnosis}\n\n"
        "Weather guidance: {weather_advice}\n\n"
        "Market guidance: {market_advice}\n\n"
        "Output language: {language}\n\n"
        "Do NOT just repeat them separately. CONNECT them where it matters:\n"
        "- Under Crop Health, when recommending the local Krishi Vigyan Kendra (KVK), always include both the KVK location name and its district (e.g., 'KVK Usilampatti, Thanjavur' or 'KVK Bichpuri, Agra') so the farmer does not confuse it with towns of the same name in other districts.\n"
        "- If the diagnosis shows a disease/pest that can SPREAD and the weather is warm, humid "
        "or rain is coming, warn that it may spread faster and to act sooner -- but tie any "
        "spraying to the SAFE spray window the weather guidance gives (right day/time, low wind, "
        "before rain). If the only safe spray window is days away and the disease is spreading, "
        "say that plainly.\n"
        "- If the crop damage is only MILD, lean towards 'watch and confirm with KVK' rather than "
        "spending money on a spray straight away.\n"
        "- For the market, keep any 'hold for a better price' as an option that depends on having "
        "storage and not needing cash now -- never a firm push to wait.\n"
        "- Each finding states how confident it is (diagnosis: LOW/MEDIUM/HIGH; weather: rain "
        "forecast confidence; market: HIGH if live government data, LOW if sample/illustrative). "
        "Carry that into a one-line confidence note per section -- if confidence is low, nudge the "
        "farmer to double-check (with KVK, closer to spray time, or at their local mandi) rather "
        "than act on the number alone.\n\n"
        "Write in very simple language a farmer can act on in 30 seconds. Use EXACTLY this "
        "structure, with these emoji bullets under each heading:\n"
        "## Crop Health\n"
        "✅ Do now: ...\n"
        "⚠️ Avoid: ...\n"
        "📅 Next step: ...\n"
        "🔎 Confidence: ...\n"
        "## Weather\n"
        "✅ Do now: ...\n"
        "⚠️ Avoid: ...\n"
        "📅 Next step: ...\n"
        "🔎 Confidence: ...\n"
        "## Market\n"
        "✅ Do now: ...\n"
        "⚠️ Avoid: ...\n"
        "📅 Next step: ...\n"
        "🔎 Confidence: ...\n\n"
        "Each bullet is one short, plain sentence. Keep the whole thing under 220 words.\n\n"
        "LANGUAGE: Write the ENTIRE advisory in the specified Output language (the headings after ##, and every bullet's text), "
        "so a farmer who reads only that language can act on it. If the language is English, write in English. "
        "TWO things must stay exactly as shown regardless of language, because software parses "
        "them: (1) the four emoji at the start of each bullet -- ✅ ⚠️ 📅 🔎 -- and (2) the "
        "confidence RATING token itself, which must remain one of the English words HIGH, "
        "MEDIUM, or LOW (you may translate the short explanation after it, but keep that one "
        "capitalized English word). Keep the `## ` markdown before each heading too."
    ),
    output_key="final_advisory",
)

join = JoinNode(name="merge")

orchestrator = Workflow(
    name="orchestrator",
    edges=[
        (START, parse_input),
        (parse_input, (crop_health_agent, prepare_weather_input, prepare_market_input)),
        (prepare_weather_input, weather_agent),
        (prepare_market_input, market_agent),
        ((crop_health_agent, weather_agent, market_agent), join),
        (join, advisory_writer),
    ],
)

root_agent = orchestrator
