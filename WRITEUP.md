# AgroAdvisor — Multi-Agent Crop Advisory for Smallholder Indian Farmers

**Subtitle:** Real-time government data via MCP, cross-agent safety reasoning, and multilingual voice advice — from a single leaf photo
**Track:** Agents for Good

---

## The Problem

Smallholder farmers across India make high-stakes decisions every week with almost no reliable, localized support: Is this leaf disease serious enough to spray for? Is today safe to spray, or will wind drift the chemical or rain wash it off before it works? Is today's mandi price actually fair, or should the crop be held? Where is the nearest government extension officer who can confirm a diagnosis before money is spent on the wrong treatment? Generic "upload a photo, get a disease name" tools answer none of this — and worse, an LLM asked directly about "today's wheat price in Ludhiana" will either refuse or confidently make something up, since its training data has a fixed cutoff and no idea what mandi prices or weather look like *right now*.

## The Solution

AgroAdvisor is a four-agent advisory pipeline built on Google's Agent Development Kit (ADK), orchestrated using the graph-based `Workflow` API: `START -> crop_health_agent -> parallel(weather_agent, market_agent) -> JoinNode -> advisory_writer`. The agents reason; they don't *know* anything about today's weather or today's price on their own. Every fact that matters — wind speed, rain probability, mandi price, an active severe-weather warning — is fetched at the moment of the request through a dedicated **MCP (Model Context Protocol) server** that wraps live external data sources as callable tools. This is the architectural decision the rest of the project depends on: it decouples agent *reasoning* from data *freshness*, so the advisory a farmer reads this afternoon reflects this afternoon's actual conditions, not a snapshot from whenever the model was trained or a number rendered into a demo dataset.

Concretely, the MCP server (`mcp_server/server.py`) exposes:
- `get_weather_forecast` → queries Open-Meteo's live forecast API at request time and computes a same-day spray-safety window from the actual hourly wind and rain data returned.
- `get_severe_weather_alerts` → queries the India Meteorological Department's official CAP (Common Alerting Protocol) feed live, checking for currently-active (not expired) Severe/Extreme warnings for the farmer's state.
- `get_market_price` → queries the Government of India's data.gov.in/Agmarknet API live for today's actual mandi price, compared against MSP. A static sample CSV exists only as a last-resort fallback for the rare day a crop+state has no live entry yet — and the advisory explicitly discloses which source was used, so a farmer is never told stale data is current.
- `get_kvk_locator` → resolves a pincode to a district via India Post's live API, then matches it against ICAR's live-rendered KVK directory pages.

On top of this real-time data layer, the four agents add the reasoning a raw API response can't: **Crop Health Agent** diagnoses the uploaded photo via Gemini vision, stating severity and confidence, and never names a specific pesticide or dose — it defers that decision to the real, named KVK resolved by the locator tool. **Weather Agent** turns the live forecast into a concrete go/no-go recommendation (never spray above ~15 km/h wind; time it around today's actual rain), and lets a live, currently-active IMD severe alert override all routine advice. **Market Agent** turns today's live price into a sell/hold recommendation, honestly caveated against storage cost and cash-flow reality. **Advisory Writer** cross-reasons across all three — a spreading disease in today's warm, wet weather means act sooner, but only inside the safe spray window the weather tool just computed — and outputs a structured ✅ Do now / ⚠️ Avoid / 📅 Next step / 🔎 Confidence advisory.

The system covers 11 Indian states and 13 crops.

## What Makes This More Than a Demo

*Real-time data, fetched live, every single request — this is the core differentiator.* Two independent, free, keyless Indian government endpoints (data.gov.in/Agmarknet for mandi prices, IMD's CAP feed for severe alerts) plus Open-Meteo for forecasts are called fresh through MCP on every advisory, not baked into a dataset or cached. A farmer querying twice in the same day, once before and once after a price moves or a storm warning is issued, gets two different, correct answers — because the agents are grounded in live tool calls, not the LLM's static knowledge.

*A safety guardrail with a real destination.* "Consult your local KVK" is a common throwaway line in agri-tech demos. AgroAdvisor instead resolves a real pincode to a real district to a real, named KVK with a working ICAR link.

*Genuine cross-agent reasoning.* The weather agent's wind/rain timing, the market agent's MSP/hold-vs-sell logic, and the crop health agent's severity/confidence feed into one synthesis step that explicitly connects them, not three outputs stapled under separate headings.

*Confidence scoring, not false certainty.* Each section reports HIGH/MEDIUM/LOW from an independent signal — photo clarity, rain-probability uncertainty, live-vs-sample sourcing — so a farmer knows when to act immediately versus verify locally.

*Built for the actual end user.* The advisory writer translates into the farmer's own language (Hindi, Punjabi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, or English) while keeping parsing-critical emoji/confidence tokens untranslated, then a "Listen" button converts it to speech via gTTS — so a farmer who can't read can still hear the advice.

*Visible orchestration.* A "How the agents decided this" trace panel shows all four pipeline steps in execution order, marks the two that run in parallel, and shows each agent's raw reasoning with the concrete live evidence behind it (actual wind km/h, actual ₹/kg, actual MSP comparison, the named KVK) — proof the advisory is grounded in real-time tool calls, not hallucinated.

## Concepts Demonstrated

- **Multi-agent system (Google ADK):** four specialized agents with explicit sequential/parallel orchestration via the `Workflow` graph API.
- **MCP Server:** the project's real-time data plane — a FastMCP server exposing live weather, severe-alert, market, and KVK-locator tools, cleanly separating "what's true right now" (fetched live via MCP) from "what should we do about it" (agent reasoning) — the architecture choice that keeps every advisory current instead of stale.
- **Test-Driven Agent Development (The Quality Flywheel):** The project maintains 47 passing unit and integration tests to ensure deterministic orchestration, robust MCP tool parsing, and safety guardrail enforcement.
- **Security features:** a pesticide-safety guardrail baked into agent instructions, input validation on uploaded photos, and a credential-leak guardrail enforced via Claude Code hooks that automatically redacts API keys/tokens from command output, after a real incident during development made the risk concrete.

## Tech Stack

Google ADK (`google-adk`) for agent orchestration and Gemini vision for diagnosis; `mcp`/FastMCP for the real-time tool server; FastAPI as a reusable backend with a separate Streamlit frontend; gTTS for free, keyless text-to-speech; Google ADK's built-in OpenTelemetry tracer exporting to LangSmith over OTLP for observability.

The architecture is explicitly designed for **deployment readiness** — the FastAPI backend and ADK orchestrator can be instantly deployed to production using `adk deploy` (to Google Cloud Run) when moving past the hackathon prototype stage.
## Demo

[YouTube video link] — problem, four-agent architecture, a live end-to-end run hitting all four MCP tools in real time, and the multi-agent trace panel.

[GitHub Repository](https://github.com/cheerssvp/agro-advisor) — full source, README with architecture diagram, setup instructions, test suite.

## Limitations & What's Next

Diagnosis uses general-purpose Gemini vision, not an agriculture-fine-tuned model — verified accurate on real wheat-rust and rice-blast photos, but unverified on others, which is why confidence scoring and KVK-deferral exist rather than presenting diagnosis as certain. Pincode-to-KVK matching is best-effort (postal vs. ICAR district-name spelling sometimes differs) and falls back to a working general directory link rather than failing. The IMD feed carries a rolling ~25-item window, so very old alerts can age out — this affects feed coverage only, not the live-fetch/expiry logic itself. The highest-leverage next addition: value-quantification, turning "today's price is ₹2/kg above MSP" into an estimated ₹ amount at stake for the farmer's likely harvest.
