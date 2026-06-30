"""Live severe weather alerts via IMD's official CAP feed.

Public domain, no API key, no registration: India Meteorological Department
publishes cyclone/heavy-rainfall/hailstorm/etc. warnings as signed CAP
(Common Alerting Protocol) XML, indexed by an RSS feed --
https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml. This is the same
official alerting channel used by Google Public Alerts / alert-hub.org.

Unlike the Open-Meteo forecast (which only estimates rain/wind), this is IMD's
own human-issued warning for a named event (e.g. "Heavy to very heavy
rainfall", "Cyclonic storm"), with severity/urgency/certainty and an official
suggested action -- useful for catching real threats a generic forecast won't
flag as urgent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx

from mcp_server.agmarknet_client import STATE_TO_AGMARKNET

RSS_URL = "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml"
REQUEST_TIMEOUT_SECONDS = 10.0
REQUEST_HEADERS = {"User-Agent": "agro-advisor-capstone/1.0"}
# The feed is India-wide and not filterable server-side, so we fetch the most
# recent N alerts and filter client-side by area name.
MAX_ITEMS_TO_CHECK = 25

CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


def _parse_cap_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def _get_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        return None


def _parse_alert(cap_xml: str) -> dict | None:
    try:
        root = ET.fromstring(cap_xml)
    except ET.ParseError:
        return None

    info = root.find("cap:info", CAP_NS)
    if info is None:
        return None

    def field(path: str) -> str:
        return (info.findtext(path, default="", namespaces=CAP_NS) or "").strip()

    return {
        "event": field("cap:event"),
        "severity": field("cap:severity"),
        "urgency": field("cap:urgency"),
        "certainty": field("cap:certainty"),
        "headline": field("cap:headline"),
        "description": field("cap:description"),
        "instruction": field("cap:instruction"),
        "area": field("cap:area/cap:areaDesc"),
        "onset": field("cap:onset"),
        "expires": field("cap:expires"),
    }


async def get_active_alerts(state: str) -> list[dict]:
    """Returns active (not-yet-expired) IMD alerts whose area mentions `state`.

    `state` may be our internal key (e.g. "punjab") or the full name -- it's
    matched against IMD's area name case-insensitively. Returns [] if the feed
    is unreachable, nothing matches, or every match has already expired -- the
    caller should treat that as "no alert", not an error.
    """
    state_name = STATE_TO_AGMARKNET.get(state.strip().lower(), state).lower()

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=REQUEST_HEADERS) as client:
        rss_text = await _get_text(client, RSS_URL)
        if not rss_text:
            return []

        try:
            rss_root = ET.fromstring(rss_text)
        except ET.ParseError:
            return []

        links = [
            link
            for item in rss_root.findall(".//item")[:MAX_ITEMS_TO_CHECK]
            if (link := item.findtext("link"))
        ]

        cap_docs = [doc for link in links if (doc := await _get_text(client, link))]

    now = datetime.now(timezone.utc)
    alerts = []
    for doc in cap_docs:
        alert = _parse_alert(doc)
        if not alert or state_name not in alert["area"].lower():
            continue

        expires = _parse_cap_datetime(alert["expires"])
        if expires and expires < now:
            continue

        alerts.append(alert)

    return alerts
