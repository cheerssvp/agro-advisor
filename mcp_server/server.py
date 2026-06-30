"""MCP server exposing weather and market-price tools to the ADK agents.

Run standalone for manual testing: `uv run python -m mcp_server.server`
The ADK agents connect to this same module over stdio via McpToolset.
"""

from __future__ import annotations

import csv
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_server.agmarknet_client import get_live_modal_price
from mcp_server.imd_alerts_client import get_active_alerts
from mcp_server.kvk_locator_client import get_kvk_for_pincode
from mcp_server.weather_client import WeatherLookupError, get_forecast

MARKET_DATA_PATH = Path(__file__).parent / "market_data.csv"

mcp = FastMCP("agro-advisor-tools")


def _crop_msp(crop_key: str) -> float | None:
    """MSP is set nationally per crop, not per state -- look it up by crop alone
    so it's available even when a live price comes from a state not in our
    bundled sample rows."""
    with MARKET_DATA_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["crop"].lower() == crop_key:
                msp_raw = row.get("msp_per_kg_inr", "").strip()
                return float(msp_raw) if msp_raw else None
    return None


@mcp.tool()
async def get_weather(location: str) -> dict:
    """Get a 3-day weather forecast for a location (e.g. "Ludhiana, Punjab, India").

    Returns daily min/max temperature (Celsius) and rain probability (%),
    sourced live from the free Open-Meteo API.
    """
    try:
        return await get_forecast(location)
    except WeatherLookupError as exc:
        return {"error": str(exc)}


@mcp.tool()
async def get_severe_weather_alerts(state: str) -> dict:
    """Get active official IMD severe weather alerts for an Indian state.

    Sourced live, free, no API key, from the India Meteorological
    Department's public CAP (Common Alerting Protocol) warning feed -- the
    same official channel used for cyclone, heavy-rainfall, hailstorm, and
    similar warnings. This is a human-issued warning for a named event, not a
    forecast estimate, so it should take priority over routine wind/rain
    spray-safety guidance when present.

    State examples: andhra_pradesh, punjab, uttar_pradesh, maharashtra, madhya_pradesh,
    gujarat, karnataka, west_bengal, bihar, rajasthan, tamil_nadu.

    Returns an empty `active_alerts` list when there is no current alert for
    that state, or when the feed can't be reached -- this is the normal case
    most of the time and should not be treated as an error.
    """
    alerts = await get_active_alerts(state)
    return {"state": state, "active_alerts": alerts, "count": len(alerts)}


@mcp.tool()
async def get_market_price(crop: str, state: str) -> dict:
    """Look up a mandi price, trend, and MSP for a crop in an Indian state.

    Tries a LIVE lookup first, against the Indian government's data.gov.in
    daily mandi price API (Agmarknet data, Ministry of Agriculture & Farmers
    Welfare) -- requires the DATA_GOV_API_KEY env var (free signup at
    https://www.data.gov.in). If that's unset, or there's no live data for
    this crop+state today, falls back to a small bundled sample dataset
    (mcp_server/market_data.csv), clearly labeled as such in `source`.
    Sugarcane always uses the sample data (it's FRP-priced at the factory
    gate, not commonly mandi-traded under this dataset).

    State examples: andhra_pradesh, punjab, uttar_pradesh, maharashtra, madhya_pradesh,
    gujarat, karnataka, west_bengal, bihar, rajasthan, tamil_nadu.

    `msp_per_kg_inr` is null for crops with no government Minimum Support Price
    (e.g. most perishables like onion/potato/tomato) -- this absence is itself
    important information: there's no government price floor for those crops.
    Live results have no `trend` (today's snapshot only, not historical).
    """
    crop_key, state_key = crop.strip().lower(), state.strip().lower()

    live = await get_live_modal_price(crop_key, state_key)
    if live:
        return {
            "crop": crop_key,
            "state": state_key,
            "price_per_kg_inr": live["price_per_kg_inr"],
            "trend": None,
            "msp_per_kg_inr": _crop_msp(crop_key),
            "live": True,
            "source": (
                f"live data.gov.in/Agmarknet mandi data, averaged across "
                f"{live['markets_count']} markets, as of {live['as_of']}"
            ),
        }

    with MARKET_DATA_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["crop"].lower() == crop_key and row["state"].lower() == state_key:
                msp_raw = row.get("msp_per_kg_inr", "").strip()
                return {
                    "crop": row["crop"],
                    "state": row["state"],
                    "price_per_kg_inr": float(row["price_per_kg_inr"]),
                    "trend": row["trend"],
                    "msp_per_kg_inr": float(msp_raw) if msp_raw else None,
                    "live": False,
                    "source": (
                        "sample dataset (illustrative mandi price and MSP, "
                        "not live data -- confirm locally)"
                    ),
                }
    return {"error": f"No live or sample price data for {crop!r} in {state!r}"}


@mcp.tool()
async def get_kvk_locator(pincode: str) -> dict:
    """Find the farmer's nearest Krishi Vigyan Kendra (KVK) from a 6-digit pincode.

    Free, keyless, two-step lookup: resolves the pincode to a district/state
    via India Post, then best-effort matches it against ICAR's published
    per-state KVK list (icar.org.in) -- KVKs are India's official local
    agricultural extension centres, the right place for a farmer to confirm a
    specific pesticide/fungicide product and dose.

    Always returns a `kvk_locator_url` the farmer can click through to (the
    state's KVK listing page, or the general ICAR KVK index if the pincode or
    state couldn't be resolved) even when `matched_kvk` is null -- district
    name spelling can differ slightly between India Post and ICAR's published
    text, so an exact match isn't guaranteed, but the link always is.
    """
    return await get_kvk_for_pincode(pincode)


if __name__ == "__main__":
    mcp.run()
