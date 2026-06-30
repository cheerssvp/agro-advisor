"""Live mandi prices via data.gov.in's Agmarknet-sourced daily price API.

Free API key (instant signup): https://www.data.gov.in -> register -> My Account -> API Key.
Resource: "Current Daily Price of Various Commodities from Various Markets (Mandi)",
published by the Ministry of Agriculture & Farmers Welfare. Reports today's modal
price per market, in Rupees per QUINTAL (100 kg) -- converted to ₹/kg here.

If DATA_GOV_API_KEY is unset, or the live call fails/has no data for a crop+state
combination, callers should fall back to the bundled sample CSV (see server.py).
"""

from __future__ import annotations

import os
from datetime import datetime

import httpx

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
REQUEST_TIMEOUT_SECONDS = 10.0
QUINTAL_KG = 100

# data.gov.in rejects requests with no User-Agent header (httpx sends none by default).
REQUEST_HEADERS = {"User-Agent": "agro-advisor-capstone/1.0"}

# Maps our internal crop keys to the exact Commodity spelling Agmarknet uses.
# Sugarcane has no entry: it's FRP-priced at the factory gate, not commonly
# mandi-traded under this dataset, so it always uses the sample CSV.
CROP_TO_COMMODITY = {
    "wheat": "Wheat",
    "rice": "Rice",
    "cotton": "Cotton",
    "maize": "Maize",
    "soybean": "Soyabean",
    "mustard": "Mustard",
    "gram": "Gram",
    "groundnut": "Groundnut",
    "onion": "Onion",
    "potato": "Potato",
    "tomato": "Tomato",
    "turmeric": "Turmeric",
}

# Maps our internal state keys to Agmarknet's State spelling.
STATE_TO_AGMARKNET = {
    "andhra_pradesh": "Andhra Pradesh",
    "punjab": "Punjab",
    "uttar_pradesh": "Uttar Pradesh",
    "maharashtra": "Maharashtra",
    "madhya_pradesh": "Madhya Pradesh",
    "gujarat": "Gujarat",
    "karnataka": "Karnataka",
    "west_bengal": "West Bengal",
    "bihar": "Bihar",
    "rajasthan": "Rajasthan",
    "tamil_nadu": "Tamil Nadu",
}


def _parse_arrival_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d/%m/%Y")
    except (ValueError, TypeError):
        return None


async def get_live_modal_price(crop: str, state: str) -> dict | None:
    """Returns today's average modal price (₹/kg) for crop+state, or None.

    Returns None (caller should fall back to the sample CSV) when: no API key
    is configured, the crop/state isn't in our live-data mapping, the request
    fails, or there's no data for that combination today.
    """
    api_key = os.environ.get("DATA_GOV_API_KEY")
    if not api_key:
        return None

    commodity = CROP_TO_COMMODITY.get(crop.strip().lower())
    agmarknet_state = STATE_TO_AGMARKNET.get(state.strip().lower())
    if not commodity or not agmarknet_state:
        return None

    params = {
        "api-key": api_key,
        "format": "json",
        "limit": "50",
        "filters[state.keyword]": agmarknet_state,
        "filters[commodity]": commodity,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=REQUEST_HEADERS) as client:
            resp = await client.get(BASE_URL, params=params)
            resp.raise_for_status()
            records = resp.json().get("records", [])
    except (httpx.HTTPError, ValueError):
        return None

    if not records:
        return None

    modal_prices = []
    arrival_dates = []
    for record in records:
        try:
            modal_prices.append(float(record["modal_price"]))
        except (KeyError, TypeError, ValueError):
            continue
        parsed_date = _parse_arrival_date(record.get("arrival_date", ""))
        if parsed_date:
            arrival_dates.append(parsed_date)

    if not modal_prices:
        return None

    avg_price_per_kg = (sum(modal_prices) / len(modal_prices)) / QUINTAL_KG
    as_of = max(arrival_dates).strftime("%Y-%m-%d") if arrival_dates else "unknown"

    return {
        "price_per_kg_inr": round(avg_price_per_kg, 2),
        "markets_count": len(modal_prices),
        "as_of": as_of,
    }
