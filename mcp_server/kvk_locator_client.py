"""Helps a farmer find their nearest Krishi Vigyan Kendra (KVK) from a pincode.

Two free, keyless public sources, chained together:
  1. India Post's pincode API (https://api.postalpincode.in) resolves a 6-digit
     pincode to district + state.
  2. ICAR (icar.org.in) publishes a static, per-state HTML table of every KVK
     with its address (which names the district) and host organization --
     unlike the JS-rendered kvk.icar.gov.in portal, these pages are plain
     server-rendered HTML and reliably reachable.

The district match is a best-effort substring search over ICAR's published
address text (district naming isn't consistently formatted across states --
some say "Distt. X", others just "X District" or "X, <State>"), so the
*state listing page link* is always returned even when an exact district
match isn't found -- that link alone is enough for a farmer to find their KVK
by eye, which is the actual goal here, not perfect automated matching.
"""

from __future__ import annotations

import html
import re

import httpx

from mcp_server.agmarknet_client import STATE_TO_AGMARKNET

PINCODE_API_URL = "https://api.postalpincode.in/pincode/{pincode}"
REQUEST_TIMEOUT_SECONDS = 10.0
REQUEST_HEADERS = {"User-Agent": "agro-advisor-capstone/1.0"}

# ICAR (icar.org.in) node IDs for each state's KVK listing page. Only the
# states this project otherwise supports (see STATE_TO_AGMARKNET) have a
# curated link; other states fall back to the general KVK index page.
STATE_TO_ICAR_KVK_PAGE = {
    "andhra_pradesh": "https://icar.org.in/en/node/15047",
    "punjab": "https://icar.org.in/en/node/15016",
    "uttar_pradesh": "https://icar.org.in/en/node/15021",
    "maharashtra": "https://icar.org.in/en/node/15040",
    "madhya_pradesh": "https://icar.org.in/en/node/15044",
    "gujarat": "https://icar.org.in/en/node/15041",
    "karnataka": "https://icar.org.in/en/node/15049",
    "west_bengal": "https://icar.org.in/en/node/15031",
    "bihar": "https://icar.org.in/en/node/15022",
    "rajasthan": "https://icar.org.in/en/node/15020",
    "tamil_nadu": "https://icar.org.in/en/node/15045",
}

GENERAL_KVK_INDEX_URL = "https://icar.org.in/en/krishi-vigyan-kendras"

# India Post's full state name -> our internal state key (reuses the same
# mapping already used for live mandi prices, for consistency).
_AGMARKNET_TO_STATE_KEY = {v.lower(): k for k, v in STATE_TO_AGMARKNET.items()}

_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*\d+\.\s*</td>\s*"
    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_cell(cell_html: str) -> str:
    text = _TAG_RE.sub(" ", cell_html)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


async def resolve_pincode(pincode: str) -> dict | None:
    """Resolves a 6-digit Indian pincode to district + our internal state key.

    Returns None if the pincode is invalid, not found, or the state isn't one
    we recognize (see STATE_TO_AGMARKNET) -- callers should treat that as
    "couldn't resolve", not a hard error.
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=REQUEST_HEADERS) as client:
            resp = await client.get(PINCODE_API_URL.format(pincode=pincode.strip()))
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not payload or payload[0].get("Status") != "Success":
        return None

    post_offices = payload[0].get("PostOffice") or []
    if not post_offices:
        return None

    district = post_offices[0].get("District")
    state_name = post_offices[0].get("State", "")
    state_key = _AGMARKNET_TO_STATE_KEY.get(state_name.strip().lower())
    if not district or not state_key:
        return None

    return {"district": district, "state": state_key}


async def find_kvk_for_district(state: str, district: str) -> dict | None:
    """Best-effort match of `district` against ICAR's published KVK list for `state`.

    Returns None if the state has no curated ICAR page, the page can't be
    fetched, or no row's address text mentions the district -- callers should
    still show `STATE_TO_ICAR_KVK_PAGE`/`GENERAL_KVK_INDEX_URL` as a fallback.
    """
    page_url = STATE_TO_ICAR_KVK_PAGE.get(state.strip().lower())
    if not page_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=REQUEST_HEADERS) as client:
            resp = await client.get(page_url)
            resp.raise_for_status()
            page_html = resp.text
    except httpx.HTTPError:
        return None

    district_lower = district.strip().lower()
    for address_html, host_org_html, year_html in _ROW_RE.findall(page_html):
        address = _clean_cell(address_html)
        if district_lower in address.lower():
            return {
                "address": address,
                "host_organization": _clean_cell(host_org_html),
                "year_of_sanction": _clean_cell(year_html),
            }

    return None


async def get_kvk_for_pincode(pincode: str) -> dict:
    """End-to-end: pincode -> district/state -> (best-effort KVK match + a
    state listing link the farmer can always click through to, even when the
    automated match misses)."""
    resolved = await resolve_pincode(pincode)
    if not resolved:
        return {
            "error": f"Could not resolve pincode {pincode!r} to a supported district/state",
            "kvk_locator_url": GENERAL_KVK_INDEX_URL,
        }

    district, state = resolved["district"], resolved["state"]
    match = await find_kvk_for_district(state, district)
    page_url = STATE_TO_ICAR_KVK_PAGE.get(state, GENERAL_KVK_INDEX_URL)

    return {
        "district": district,
        "state": state,
        "matched_kvk": match,
        "kvk_locator_url": page_url,
        "source": "ICAR (icar.org.in) published KVK list, best-effort district text match",
    }
