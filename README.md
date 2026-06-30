# AgroAdvisor

A multi-agent advisory system for **Indian smallholder farmers**, built for Kaggle's
**AI Agents: Intensive Vibe Coding Capstone Project** (track: *Agents for Good*).

Send a photo of a crop, a location (village/district/state), a crop name, and
optionally a pincode -- get back a short advisory covering **crop health**
(diagnosed from the photo, with a direct link to the farmer's nearest KVK),
**weather** (is it safe to spray/irrigate this week?), and **market** (sell now
or hold, in ₹/kg?) -- **in the farmer's own language, by text and voice**
(English, Hindi, Punjabi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada).

## Problem

India has over 100 million smallholder farmers who often make high-stakes
decisions -- spray now or wait for the monsoon to pass, sell the harvest now
at the local mandi or hold for a better price, what's wrong with this plant --
without easy, low-cost access to an expert. Each of those decisions draws on a
different kind of information (visual diagnosis, weather data, mandi price
data). A single agent can't specialize in all three well; a **multi-agent
system** that delegates each concern to a focused sub-agent and then
synthesizes the result is a natural fit.

## Architecture

```
                         ┌────────────────────┐
   photo + crop +        │   crop_health_agent │  -> state.crop_diagnosis
   location + pincode    │  (Gemini vision)    │ ──MCP──> get_kvk_locator()
        │                └────────────────────┘
        │                          │
        ▼                          ▼
┌───────────────┐         ┌──────────────────────────────┐
│  orchestrator │ ──run──>│   Parallel branches          │
│ (Workflow     │         │  ┌───────────────────────┐    │
│  Graph)       │         │  │ weather_agent ──MCP──> │ get_weather()
│               │         │  │               ──MCP──> │ get_severe_weather_alerts()
│               │         │  │ market_agent  ──MCP──> │ get_market_price()
└───────────────┘         │  └───────────────────────┘    │
        │                 └──────────────┬───────────────┘
        │                                │
        │                                ▼
        │                     ┌────────────────────┐
        │                     │  JoinNode (merge)  │
        │                     └──────────┬─────────┘
        ▼                                │
┌────────────────┐                       │
│ advisory_writer│ <─────────────────────┘
│  (synthesis)   │
└────────────────┘
        │
        ▼
   final advisory (printed by cli.py)
```

- `agents/crop_health_agent.py` -- Gemini multimodal vision agent; takes the
  photo directly (no separate CV training pipeline) and diagnoses disease/pest/
  deficiency signs, scoped strictly to plants (refuses non-plant images or
  medical-advice requests). If a pincode is given, it also calls
  `get_kvk_locator` to name the farmer's actual nearest KVK and link to it.
- `agents/weather_agent.py` / `agents/market_agent.py` -- each wraps **one**
  tool from the local MCP server (least-privilege: each agent only sees the
  tool it needs).
- `agents/orchestrator.py` -- a graph-based `Workflow` pipeline (diagnose -> advise in parallel -> join -> write). The weather and market agents run concurrently after crop health diagnosis, and are fanned-in using a `JoinNode` before the final synthesis. This is the **multi-agent system** concept.
  The final `advisory_writer` doesn't just staple the three findings together --
  it **cross-reasons** between them (e.g. a spreading disease + warm/wet weather
  -> act sooner, but only within the safe spray window; mild damage -> watch and
  confirm with KVK rather than spend on a spray straight away) and writes the
  result in a farmer-friendly ✅ Do now / ⚠️ Avoid / 📅 Next step / 🔎 Confidence
  format -- each section states how much to trust it, so low confidence nudges
  the farmer to double-check rather than act blindly.
- `mcp_server/server.py` -- a standalone **MCP server** (stdio transport)
  exposing `get_weather` (live, via the free Open-Meteo API),
  `get_severe_weather_alerts` (live, via IMD's official CAP alert feed),
  `get_market_price` (live government mandi prices when configured, falling
  back to a small bundled sample dataset otherwise -- see below), and
  `get_kvk_locator` (live, pincode -> nearest KVK -- see below).

### Agronomy-specific reasoning

- **Spray-safe weather advice**: `get_weather` returns more than rain
  probability -- it also returns daily max **wind speed** and an hourly
  summary of today's morning vs. afternoon wind and when rain is expected.
  `weather_agent` uses these to give *spray-safe* guidance: never spray above
  ~15 km/h wind (drift wastes chemical and is unsafe), pick the calmer part of
  the day, and finish before rain arrives (rain soon after spraying washes it
  off, so the farmer pays twice). Wind/rain-timing is the difference between
  "this week looks OK" and advice that won't cost the farmer money.
- **Official severe weather alerts**: `get_severe_weather_alerts` calls the
  India Meteorological Department's public CAP (Common Alerting Protocol)
  warning feed -- the same official channel behind cyclone/heavy-rainfall/
  hailstorm warnings, free and keyless. Unlike the Open-Meteo forecast (a
  statistical estimate), this is a human-issued warning for a named event.
  `weather_agent` checks it first: a Severe/Extreme alert overrides the
  routine spray-safety advice entirely (don't spray, don't irrigate, follow
  IMD's instruction), while Moderate/Minor alerts are mentioned as a caution
  alongside the routine guidance. No alert -> no mention, so the advisory
  never manufactures a caution IMD hasn't actually issued.
- **Crop severity + spread risk**: `crop_health_agent` always states a severity
  (mild / moderate / severe) and whether the problem can spread, so the farmer
  can judge urgency and the synthesis step can connect it to the weather.
- **Nearest KVK locator**: the pesticide-safety guardrail above tells the
  farmer to "confirm with your local KVK" -- `get_kvk_locator` turns that into
  an actual destination. It resolves a 6-digit pincode to a district via
  [India Post's free pincode API](https://api.postalpincode.in), then
  best-effort matches that district against ICAR's published per-state KVK
  list ([icar.org.in](https://icar.org.in/en/krishi-vigyan-kendras) -- a
  static, server-rendered table, unlike the JS-rendered `kvk.icar.gov.in`
  portal which wasn't reliably reachable while building this). When a
  district match is found, `crop_health_agent` names that specific KVK's
  address and host organization; either way, it always includes a clickable
  link to the state's full KVK list so the farmer never hits a dead end.
  Optional -- the diagnosis works exactly the same without a pincode.
- **Live-first market data**: `get_market_price` tries a live lookup against
  the Indian government's [data.gov.in daily mandi price API](https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi)
  (Agmarknet data, Ministry of Agriculture & Farmers Welfare) first --
  today's modal price, averaged across all reporting markets in that state.
  If `DATA_GOV_API_KEY` isn't set, or there's no live data for that
  crop+state today (e.g. sugarcane, which is FRP-priced at the factory gate
  and not mandi-traded under this dataset), it falls back to the bundled
  sample CSV. The `live` field in the tool result and the `source` string
  tell you which one was used.
- **MSP-aware market guidance**: `get_market_price` also returns an indicative
  Minimum Support Price (MSP) for crops that have one (MSP is set nationally
  per crop, not per state, so it's looked up independently of the live/sample
  price path). `market_agent` checks the mandi price against it: if the mandi
  price is *below* MSP, it leads with that and points the farmer toward
  government procurement (FCI / PM-AASHA) instead of giving generic sell/hold
  trend advice -- for MSP-notified crops, that comparison matters more than
  the trend. Perishables with no MSP (onion, potato, tomato, turmeric) are
  explicitly flagged as having no government price floor. Live results have
  no day-over-day `trend` (today's snapshot only); sample results do. Any
  "hold for a better price" advice is framed only as an option that depends on
  the farmer having dry storage and not needing cash now (many smallholders
  must sell at harvest to repay loans), and notes that a state-wide average
  may differ from the farmer's own mandi once transport/commission are counted.
- **Multilingual + voice output**: the real adoption barrier for a smallholder
  farmer isn't the model's accuracy -- it's that the advice arrives in English
  text they may not read. The `advisory_writer` writes the **entire advisory
  in the farmer's chosen language** (Hindi, Punjabi, Tamil, Telugu, Bengali,
  Marathi, Gujarati, Kannada, or English), and the Web UI's "🔊 Listen" button
  plays it as **audio** (via gTTS, free/keyless) so a farmer who can't read can
  still hear it. The structure markers the UI parses (the ✅/⚠️/📅/🔎 emoji and
  the HIGH/MEDIUM/LOW confidence token) are deliberately kept stable across
  languages, so translation never breaks the card layout (`languages.py`,
  `advisory_formatting.py`).
- **Confidence scoring**: each sub-agent states how much to trust its own
  output, and `advisory_writer` surfaces it as a `🔎 Confidence` line per
  section. `crop_health_agent` rates its diagnosis LOW/MEDIUM/HIGH based on
  photo clarity and symptom specificity (low confidence pushes the farmer
  towards KVK confirmation instead of acting alone). `get_weather` computes
  `today_rain_forecast_confidence` from how close today's rain probability is
  to 50% (near 50% = genuinely uncertain, near 0%/100% = confident) -- a
  heuristic since Open-Meteo's free tier doesn't expose ensemble variance.
  `market_agent` reports HIGH confidence for live government data and
  LOW for the illustrative sample fallback.

### Edge case handling

| Case | Where it's handled |
|---|---|
| No image / bad image | `cli.py` makes `--photo` a required arg; `security/guardrails.py`'s `validate_photo()` rejects a missing file, disallowed extension, or bytes that don't actually decode as an image (Pillow check) -- all raise `GuardrailError` before anything reaches the vision model. `cli.py`'s `main()` catches it and exits with a clear message instead of crashing. `crop_health_agent`'s instructions also tell it to say so plainly (not guess) if the image isn't a plant at all. |
| Unknown crop | `get_market_price` (`mcp_server/server.py`) returns `{"error": ...}` instead of raising when the crop/state combination has no live or sample data. `market_agent`'s instructions explicitly tell it not to invent a price on an `error` result and to point the farmer to their local mandi/KVK instead. Covered by `test_get_market_price_unknown_crop`. |
| Location mismatch (unresolvable place name) | `get_forecast` (`mcp_server/weather_client.py`) raises `WeatherLookupError` once all geocoding fallback candidates fail; `get_weather` catches it and returns `{"error": ...}`. `weather_agent`'s instructions tell it not to invent a forecast on an `error` result and to ask for a nearby town/district/state instead. Covered by `test_get_weather_returns_error_for_unresolvable_location`. |
| No-MSP crop | `msp_per_kg_inr` is `null` for perishables with no government price floor (onion, potato, tomato, turmeric). `market_agent` treats that absence as meaningful information itself -- it says plainly there's no MSP and falls back to trend-based guidance only. Covered by `test_get_market_price_no_msp_crop`. |

## Security features

- All secrets (`GOOGLE_API_KEY`) come from environment variables / `.env`,
  which is git-ignored. `.env.example` only has placeholders. No keys are
  hardcoded anywhere in the code.
- `security/guardrails.py`:
  - `validate_photo()` checks file existence, extension allow-list, size cap,
    and that the bytes actually decode as an image (via Pillow) before
    anything reaches the vision model -- rejects disguised/corrupt uploads.
  - `ToolRateLimiter` is wired in as an ADK `before_tool_callback` on both MCP
    agents, capping each tool to 5 calls/60s. Since `before_tool_callback` can
    short-circuit the real tool call, a misbehaving or looping agent can't
    hammer the external weather API indefinitely.
- `crop_health_agent`'s instructions explicitly scope it to plant health only
  and forbid human/medical advice, as a basic guardrail against misuse.
- `crop_health_agent` never names a specific pesticide/fungicide brand, active
  ingredient, or dosage -- an LLM can't verify current local registration,
  banned-chemical status, or correct dose, and getting that wrong can damage
  the crop or be unsafe. It names only the treatment *category* and always
  directs the farmer to confirm the specific product/dose with their local
  Krishi Vigyan Kendra (KVK), extension officer, or a licensed agri-input
  dealer before applying anything.

## Observability (optional)

`observability.py` activates ADK's **built-in** OpenTelemetry instrumentation
(`google.adk.telemetry.tracer`, already in the library -- it just has no
exporter wired up by default outside `adk web`/`adk api_server`) and points
it at [LangSmith](https://smith.langchain.com), which accepts raw OTLP traces
directly -- no `langsmith` SDK or LangChain dependency needed. Per-agent and
per-tool-call spans (crop diagnosis, weather lookup, market lookup, IMD
alerts, the final synthesis) show up in the LangSmith UI as a single trace
tree per run.

Set `LANGSMITH_API_KEY` (free tier at https://smith.langchain.com) in `.env`
to turn it on; leave it unset and the app behaves exactly as before --
tracing is purely additive, never required.

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo-url>
cd agro-advisor
uv sync

cp .env.example .env
# edit .env and add your Gemini API key (free at https://aistudio.google.com/apikey)
# optionally also add a free data.gov.in API key (https://www.data.gov.in -> sign up
# -> My Account -> API Key) for live mandi prices instead of the sample dataset.
```

## Running the demo

```bash
uv run python cli.py --photo sample_data/sample_leaf.jpg --location "Ludhiana, Punjab, India" --crop wheat --pincode 141001 --language Hindi
```

(`--pincode` is optional -- omit it and the advisory is identical except for a
generic "confirm with your local KVK" instead of a named one. `--language`
defaults to English; pass `Hindi`, `Punjabi`, `Tamil`, etc. to get the
advisory in that language. Voice output is available in the Web UI below.)

(`sample_data/sample_leaf.jpg` is a placeholder graphic, not a real diseased
leaf. For a meaningful diagnosis, swap in a real photo -- `sample_data/wheatleaf.jpeg`
(wheat rust) and `sample_data/Paddy.jpeg` (rice blast) are real, verified
examples; see Tests below.)

The ADK agents launch the MCP server themselves as a subprocess over stdio --
no separate process needs to be started manually. To test the MCP server in
isolation:

```bash
uv run python -m mcp_server.server
```

## Web UI

A farmer-facing form, backed by a reusable HTTP API (so the same backend
could later sit behind a WhatsApp bot or mobile app, not just this form):

- `api.py` -- a **FastAPI** backend exposing `POST /advisory` (multipart
  photo + location + crop + optional pincode + language -> the advisory text),
  `POST /tts` (advisory text + language -> spoken MP3 audio, via gTTS), and
  `GET /healthz`. It owns the actual ADK agents; the multi-agent pipeline logic
  itself lives in `advisor.py`, shared with `cli.py`.
- `streamlit_app.py` -- a thin Streamlit client: a guided form (photo
  uploader, location, a crop dropdown sourced from `mcp_server/market_data.csv`,
  optional pincode, and a **language** selector) that calls the API, renders the
  advisory as colour-coded cards, offers a **🔊 Listen** button that plays the
  advisory as audio, and includes a **🔬 multi-agent trace** panel (see below).
  Deliberately a fixed form rather than open-ended chat -- it doesn't ask the
  farmer to know what to type.

The `/advisory` response also returns a `trace` (each sub-agent's own raw
output), which the UI shows in an expandable **"How the agents decided this"**
panel: a four-step pipeline (1. Crop Health Agent → 2. Weather Agent ∥ 3. Market
Agent → 4. Advisory Writer) where each step names the agent, the live data
source/tool it used, and the concrete evidence it pulled (the actual wind km/h,
₹/kg, MSP, KVK match). This makes the multi-agent orchestration -- and the fact
that the numbers are real live data, not hallucinated -- visible instead of
buried in code.

Run both (in separate terminals):

```bash
uv run uvicorn api:app --reload
uv run streamlit run streamlit_app.py
```

Then open the Streamlit URL it prints (typically http://localhost:8501).
`AGRO_ADVISOR_API_URL` (default `http://localhost:8000`) points the Streamlit
client at the API if you run it elsewhere.

## Tests

```bash
uv run pytest tests/ -v
```

`tests/test_agents_smoke.py` covers guardrails, MCP tool logic, and agent
wiring offline (mocked HTTP, no live API key needed) -- it does not call the
real Gemini API.

`tests/test_api.py` covers the FastAPI backend offline: health check,
guardrail rejection (a bad photo extension fails before any agent/network
call happens), the `/tts` endpoint (empty-text rejection + a mocked-gTTS
audio response), and the `/advisory` response shape including the multi-agent
`trace` (with the pipeline mocked, so no Gemini call). The real `/advisory`
success path is verified live/manually -- see Web UI above.

`tests/test_advisory_formatting.py` covers the markdown parser the UI uses,
including a **Hindi** advisory fixture that proves parsing stays correct when
the text is translated (the emoji + HIGH/MEDIUM/LOW markers are language-agnostic).

`tests/test_live_diagnosis.py` is a separate, optional **live** integration
test: it sends two real diseased-leaf photos (`sample_data/wheatleaf.jpeg` --
wheat rust, `sample_data/Paddy.jpeg` -- rice blast) through the actual
`crop_health_agent` and asserts the real diagnosis names the correct disease.
It auto-skips unless `GOOGLE_API_KEY` is set (it costs quota and isn't fully
deterministic, so it's kept out of the default offline suite), but with a
real key it's concrete proof the vision diagnosis works on genuine symptoms,
not just the placeholder graphic.

## Rubric concepts demonstrated

| Concept | Where |
|---|---|
| Multi-agent system (ADK) | `agents/orchestrator.py` -- `Workflow` graph containing a parallel fan-out of two sub-agents, a vision sub-agent, a `JoinNode` to fan-in, and a synthesis agent |
| MCP Server | `mcp_server/server.py` -- standalone FastMCP server, connected to via `McpToolset` in `agents/weather_agent.py` / `agents/market_agent.py` |
| Security features | `security/guardrails.py` -- input validation + rate limiting; env-based secrets; scoped agent instructions |

## Known limitations / sample data disclosure

- Market price is **live** (today's government mandi data via data.gov.in/
  Agmarknet) when `DATA_GOV_API_KEY` is configured and there's data for that
  crop+state today; otherwise it falls back to `mcp_server/market_data.csv`,
  a small **illustrative sample dataset** of Indian crops and states (wheat,
  rice, cotton, sugarcane, maize, soybean, mustard, gram, groundnut, onion,
  potato, tomato, turmeric across Andhra Pradesh, Punjab, Uttar Pradesh,
  Maharashtra, Madhya Pradesh, Gujarat, Karnataka, West Bengal, Bihar,
  Rajasthan, Tamil Nadu),
  inspired by typical mandi price ranges -- not live data. The agent always
  discloses which one was used (`live: true/false` and the `source` string).
  Sugarcane always uses the sample data (FRP-priced at the factory gate, not
  mandi-traded under this dataset). Even live prices are a state-wide average
  across reporting markets, not the farmer's exact local mandi -- still worth
  confirming locally.
- `msp_per_kg_inr` always comes from the bundled sample dataset (data.gov.in's
  daily price feed doesn't include MSP), inspired by recent MSP figures but
  not guaranteed to match the current year's official MSP (revised annually
  by the government) -- the agent always tells the farmer to confirm it
  locally or at https://dmi.gov.in. Crops with no government MSP (most
  perishables) report `null` for this field, which the agent treats as
  meaningful information in itself.
- `crop_health_agent` never names a specific pesticide/product/dose -- see
  Security features above.
- `sample_data/sample_leaf.jpg` is a generated placeholder graphic for testing
  the file-handling pipeline end-to-end, not a real plant photo. Real-photo
  diagnosis accuracy is separately verified with `sample_data/wheatleaf.jpeg`
  and `sample_data/Paddy.jpeg` (see Tests).
- `crop_health_agent` uses Gemini's general-purpose vision, not a model
  fine-tuned on an agricultural dataset -- it correctly named wheat rust and
  rice blast on the two real photos tested, but accuracy on other diseases,
  poor lighting, or unusual angles is unverified. This is exactly why every
  diagnosis carries a LOW/MEDIUM/HIGH confidence rating and a "confirm with
  KVK" deferral rather than being presented as ground truth.
- `get_severe_weather_alerts` matches an Indian state name against IMD's
  free-text alert area description, and only checks the ~25 most recent
  India-wide alerts on the feed -- a real but narrow/lower-rate alert could in
  principle scroll off before being checked. Absence of an alert is reported
  as "no current alert", not "guaranteed safe" -- the routine spray-safety
  wind/rain guidance still applies regardless.
- `get_kvk_locator`'s district match is **best-effort text matching**, not an
  exact lookup: India Post and ICAR's published list don't always spell a
  district identically (e.g. India Post's "Ananthapur" vs. ICAR's
  "Anantapur"), so a real district can occasionally go unmatched. The
  `kvk_locator_url` link to the full state listing is always returned
  regardless, so the farmer can still find their KVK by eye in that case.
  Coverage is limited to the same 11 states as the market/weather tools above
  -- other states fall back to ICAR's general KVK index page.
- **Translation and voice are best-effort, not professionally verified.** The
  advisory is translated by Gemini and read aloud by gTTS -- good enough to be
  genuinely useful, but agricultural terms could occasionally be rendered
  awkwardly, and gTTS is a generic (not farming-tuned) voice that needs
  internet. The structural markers (✅/⚠️/📅/🔎 and HIGH/MEDIUM/LOW) are pinned
  to stay constant across languages so the UI never mis-parses a translated
  advisory, but the prose itself should be treated as a helpful translation,
  not a certified one.
- No live public endpoint is deployed (not required by the competition
  rubric); run locally via the CLI above.
