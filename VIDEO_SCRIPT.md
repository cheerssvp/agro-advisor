# AgroAdvisor — Video Script (target: 4:30–5:00)

Narration written for ~140 wpm. Read each block once at a natural pace to
check timing before recording — adjust by trimming sentences, not by reading
faster.

---

### Scene 1 — The problem (0:00–0:30)
**On screen:** Title card "AgroAdvisor" → cut to a photo of a diseased crop leaf, or a slide with the three farmer questions.

> "A smallholder farmer in Punjab finds a diseased leaf in their field. Three questions follow immediately: Is this serious enough to spray for? Is today actually safe to spray — or will wind or rain ruin it? And is today's mandi price even fair? Generic photo-diagnosis tools answer the first question and stop there. AgroAdvisor answers all three — using real government data, fetched live, not a cached demo dataset."

---

### Scene 2 — Architecture, in one breath (0:30–1:10)
**On screen:** Architecture diagram from the README — highlight each box as it's named.

> "Now let's see how the multi-agent orchestration actually worked. If we open this trace panel at the bottom... *[Click to expand the trace panel]*... we can see exactly what the Google ADK agents did.

*   *Step 1*: The Crop Health Agent diagnosed the photo.
*   *Step 2 & 3*: The Weather and Market agents ran **in parallel** via the ADK `Workflow` graph.

Most importantly, you can see the **live data** they pulled. These aren't hallucinations. The Weather agent fetched today's actual wind speeds using our custom MCP server, and the Market agent fetched today's real mandi price from `data.gov.in` using an MCP tool call. 

*[Briefly switch to the terminal window showing the FastMCP server logs]*
You can see the MCP tools being invoked live right here in the terminal. If you don't have the API keys configured, the system gracefully falls back to bundled sample data, so anyone can clone and run this instantly."

---

### Scene 3 — Live demo: submit & diagnose (1:10–2:00)
**On screen:** Screen-record the actual Streamlit app. Upload a real leaf photo (e.g. `sample_data/Paddy.jpeg`), fill location/crop/pincode, hit submit.

> "Let's run it live. I upload a real photo of a rice leaf, give my location, crop, and pincode, and submit. Behind the scenes, four agents are now running — vision diagnosis, a live weather call, a live government price lookup — and the result comes back as three color-coded cards: what to do now, what to avoid, and the next step, each with a confidence rating."

**Pause on screen** while the cards render — let the audience actually read one card.

---

### Scene 4 — The real-time data angle (2:00–2:50)
**On screen:** Open the "How the agents decided this" trace panel — scroll through all four steps.

> "Here's the part that matters most: this trace panel shows exactly what each agent did and why. The weather agent didn't guess — it called Open-Meteo's live forecast right now and computed today's actual safe spray window. The market agent didn't guess either — it called the Government of India's data.gov.in Agmarknet API and pulled today's real mandi price against MSP. And before any of that, the weather agent checked India's official IMD severe-weather alert feed for anything active right now. None of this is baked into a dataset. Ask again tomorrow, after the price moves or a storm warning is issued, and you'll get a different, correct answer — because it's grounded in live tool calls, not the model's training data."

---

### Scene 5 — Safety guardrail + voice (2:50–3:40)
**On screen:** Scroll to the KVK link in the advisory; then switch language dropdown to Hindi, resubmit or show a pre-recorded Hindi result, click "🔊 Listen."

> "Notice the advisory never names a specific pesticide or dose — it defers that to the farmer's real, nearest Krishi Vigyan Kendra, resolved from their pincode to an actual named center with a working link. And because many farmers don't read English — or don't read at all — the same advisory can be generated in Hindi, Punjabi, Tamil, and six other languages, with a Listen button that reads it aloud."

**Play a few seconds of the Hindi audio.**

---

### Scene 6 — Why this isn't just a demo (3:40–4:15)
**On screen:** Quick bullet slide, or stay on the trace panel.

> "Two independent live government APIs, not sample data. Cross-agent reasoning that connects disease severity, today's weather window, and today's price into one decision — not three outputs stapled together. Confidence scoring so a farmer knows when to act versus verify locally. And a visible multi-agent trace, so none of this is a black box."

---

### Scene 7 — Close (4:15–4:45)
**On screen:** GitHub repo URL + Kaggle writeup link on screen.

> "AgroAdvisor — built with Google ADK, an MCP server for real-time government data, FastAPI and Streamlit, and Gemini vision. Code, README, and tests are on GitHub; the full writeup is linked below. Thanks for watching."

---

## Recording checklist
- [ ] Record screen at 1080p+ (QuickTime: File → New Screen Recording)
- [ ] Have a real sample photo ready (`sample_data/Paddy.jpeg` or `wheatleaf.jpeg`) — already verified to produce a confident, correct diagnosis
- [ ] Run a Hindi request *before* recording so the "Listen" click is instant, not a 60–70s wait on camera
- [ ] Either narrate live while recording, or record screen silently and lay the generated voiceover track under it afterward (ffmpeg command available on request)
- [ ] Trim dead air around the agent-processing spinner (30–60s) in the edit — don't make viewers wait on camera
