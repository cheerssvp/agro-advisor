import base64
import csv
import json
import os
from pathlib import Path

import requests
import streamlit as st

from advisory_formatting import SECTION_ICONS_BY_POSITION, confidence_color, parse_advisory
from languages import DEFAULT_LANGUAGE, LANGUAGES

API_BASE_URL = os.environ.get("AGRO_ADVISOR_API_URL", "http://localhost:8000")
MARKET_DATA_PATH = Path(__file__).parent / "mcp_server" / "market_data.csv"


def _get_base64_image(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        return ""
    with path.open("rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()


def _known_crops() -> list[str]:
    with MARKET_DATA_PATH.open(newline="") as f:
        crops = {row["crop"] for row in csv.DictReader(f)}
    return sorted(crops)


def render_confidence_badge(text: str) -> None:
    color = confidence_color(text)
    st.markdown(
        f"<span style='background:{color}1a;color:{color};padding:3px 10px;"
        f"border-radius:999px;font-size:0.85em;font-weight:600;'>"
        f"🔎 {text}</span>",
        unsafe_allow_html=True,
    )


# The multi-agent pipeline, in execution order, for the "trace" panel. Each
# step names the agent, the data source/tool it uses, and the session-state
# key holding its raw output. Steps 2 and 3 run in parallel (ADK ParallelAgent).
TRACE_STEPS = [
    ("1", "🌾 Crop Health Agent", "Gemini vision -- diagnoses the photo", "crop_health", False),
    ("2", "🌦️ Weather Agent", "MCP tools: Open-Meteo forecast + IMD severe-weather alerts", "weather", True),
    ("3", "💰 Market Agent", "MCP tool: data.gov.in / Agmarknet mandi price vs. MSP", "market", True),
    ("4", "✍️ Advisory Writer", "synthesizes all three + translates to your language", None, False),
]


def render_trace(trace: dict) -> None:
    with st.expander("🔬 How the agents decided this (multi-agent trace)"):
        st.caption(
            "AgroAdvisor isn't one prompt -- it's an ADK pipeline of four agents. "
            "Steps 2 and 3 run in parallel. Raw agent reasoning shown in English."
        )
        for num, title, source, key, parallel in TRACE_STEPS:
            tag = " &nbsp;`runs in parallel`" if parallel else ""
            st.markdown(f"**{num}. {title}**{tag}", unsafe_allow_html=True)
            st.caption(source)
            if key and trace.get(key):
                st.info(trace[key])
            elif key is None:
                st.caption("→ produced the colour-coded advisory cards above.")


def render_advisory(advisory_text: str) -> None:
    sections = parse_advisory(advisory_text)
    if not sections:
        st.markdown(advisory_text)
        return

    columns = st.columns(len(sections))
    for i, (col, (heading, fields)) in enumerate(zip(columns, sections.items())):
        icon = SECTION_ICONS_BY_POSITION[i] if i < len(SECTION_ICONS_BY_POSITION) else "📋"
        with col:
            with st.container(border=True):
                st.subheader(f"{icon} {heading}")
                if fields.get("do_now"):
                    st.success(fields["do_now"], icon="✅")
                if fields.get("avoid"):
                    st.warning(fields["avoid"], icon="⚠️")
                if fields.get("next_step"):
                    st.info(fields["next_step"], icon="📅")
                if fields.get("confidence"):
                    render_confidence_badge(fields["confidence"])


st.set_page_config(page_title="AgroAdvisor", page_icon="🌱", layout="wide")

banner_base64 = _get_base64_image("assets/sidebar.png")

# Custom CSS to style the sidebar background and replace Streamlit's default running icon (bicycle) with a growing plant emoji
st.markdown(
    f"""
    <style>
    /* Hide the default running/cycling icon inside the status widget */
    [data-testid="stStatusWidget"]:has(div) > div {{
        display: none !important;
    }}
    /* Inject the growing plant emoji in its place */
    [data-testid="stStatusWidget"]:has(div)::before {{
        content: "🌱";
        font-size: 24px;
        display: inline-block;
        animation: grow-plant 1.5s infinite ease-in-out;
    }}
    @keyframes grow-plant {{
        0%, 100% {{ transform: scale(0.8); }}
        50% {{ transform: scale(1.2); }}
    }}
    /* Set glassmorphic forest green background for the sidebar */
    [data-testid="stSidebar"] {{
        background-image: linear-gradient(rgba(10, 30, 15, 0.88), rgba(10, 30, 15, 0.88)), url("data:image/png;base64,{banner_base64}");
        background-size: cover;
        background-position: center;
    }}
    [data-testid="stSidebar"] > div:first-child {{
        background-color: transparent !important;
    }}
    /* Text readability styling for dark sidebar background */
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {{
        color: #f0fff4 !important;
    }}
    [data-testid="stSidebar"] strong {{
        color: #8ce99a !important;
    }}
    /* Specific styling for captions to ensure high contrast and premium italicized look */
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] span,
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] small * {{
        color: #ffffff !important;
        font-style: italic !important;
        font-size: 0.88rem !important;
        line-height: 1.4 !important;
    }}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] strong,
    [data-testid="stSidebar"] small strong {{
        color: #a3f7b5 !important;
        font-style: italic !important;
        font-weight: bold !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

with st.sidebar:
    st.header("🌱 AgroAdvisor")
    st.caption("A multi-agent advisory system for Indian smallholder farmers.")
    st.markdown(
        "- 🧠 **Crop health** -- diagnosed from your photo (Gemini vision)\n"
        "- 🌦️ **Weather** -- live forecast + official IMD severe alerts\n"
        "- 💰 **Market** -- live government mandi prices vs. MSP\n"
        "- 📍 **KVK locator** -- your nearest agricultural extension centre\n"
        "- 🗣️ **Your language** -- advice you can read *and* hear"
    )
    st.caption(
        "Built with the modern **Google ADK Workflow API** (orchestrating agents in parallel), "
        "powered by real-time **MCP tools**, using **SSE Streaming** for live UI thought feeds, "
        "and backed by a **Test-Driven** suite of 47 integration tests."
    )

st.title("🌱 AgroAdvisor")
st.caption(
    "Upload a photo of your crop, your location, and crop name -- get crop "
    "health, weather, and market advice in your own language, by text and voice."
)

with st.form("advisory_form"):
    left, right = st.columns([1, 1.4])
    with left:
        photo = st.file_uploader(
            "Photo of your crop (leaf/plant)", type=["jpg", "jpeg", "png", "webp"]
        )
        if photo:
            st.image(photo, caption=photo.name, width=220)
    with right:
        location = st.text_input(
            "Location (village/district/state)", placeholder="Ludhiana, Punjab, India"
        )
        crop = st.selectbox("Crop", options=_known_crops())
        pincode = st.text_input(
            "Pincode (optional -- to find your nearest KVK)", placeholder="141001", max_chars=6
        )
        language_label = st.selectbox(
            "Language", options=list(LANGUAGES), index=list(LANGUAGES).index(DEFAULT_LANGUAGE)
        )
    submitted = st.form_submit_button("Get Advisory", use_container_width=True)

if submitted:
    if not photo or not location or not crop:
        st.error("Please provide a photo, location, and crop.")
    else:
        with st.status("Running multi-agent advisory...", expanded=True) as status:
            try:
                response = requests.post(
                    f"{API_BASE_URL}/advisory",
                    files={"photo": (photo.name, photo.getvalue(), photo.type)},
                    data={
                        "location": location,
                        "crop": crop,
                        "pincode": pincode or "",
                        "language": LANGUAGES[language_label].name,
                    },
                    timeout=120,
                    stream=True,
                )
            except requests.RequestException as exc:
                status.update(label="API Error", state="error", expanded=True)
                st.error(f"Could not reach the AgroAdvisor API at {API_BASE_URL}: {exc}")
            else:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if not line:
                            continue
                        decoded_line = line.decode("utf-8")
                        if decoded_line.startswith("data: "):
                            data_str = decoded_line[6:]
                            try:
                                payload = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                                
                            if payload.get("type") == "event":
                                author = payload.get("author", "Agent")
                                text = payload.get("text", "")
                                # Show which agent is currently generating
                                status.write(f"**{author}** updated...")
                            elif payload.get("type") == "error":
                                status.update(label="Error running advisory", state="error", expanded=True)
                                st.error(f"Request rejected: {payload.get('detail')}")
                                st.session_state.pop("advisory", None)
                                break
                            elif payload.get("type") == "final":
                                status.update(label="Advisory complete!", state="complete", expanded=False)
                                st.session_state["advisory"] = payload["advisory"]
                                st.session_state["advisory_trace"] = payload.get("trace", {})
                                st.session_state["advisory_language"] = language_label
                                st.session_state.pop("advisory_audio", None)
                                break
                else:
                    status.update(label="API Error", state="error", expanded=True)
                    try:
                        detail = response.json().get("detail", response.text)
                    except Exception:
                        detail = response.text
                    st.error(f"Request rejected: {detail}")
                    st.session_state.pop("advisory", None)

if st.session_state.get("advisory"):
    st.divider()
    render_advisory(st.session_state["advisory"])

    language_label = st.session_state.get("advisory_language", DEFAULT_LANGUAGE)
    if st.button(f"🔊 Listen ({language_label})"):
        with st.spinner("Generating audio..."):
            try:
                audio_resp = requests.post(
                    f"{API_BASE_URL}/tts",
                    data={
                        "text": st.session_state["advisory"],
                        "language": LANGUAGES[language_label].name,
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                st.error(f"Could not reach the AgroAdvisor API at {API_BASE_URL}: {exc}")
            else:
                if audio_resp.status_code == 200:
                    st.session_state["advisory_audio"] = audio_resp.content
                else:
                    st.error("Could not generate audio for this advisory.")

    if st.session_state.get("advisory_audio"):
        st.audio(st.session_state["advisory_audio"], format="audio/mp3")

    if st.session_state.get("advisory_trace"):
        render_trace(st.session_state["advisory_trace"])
