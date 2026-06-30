"""Offline smoke tests: guardrails, MCP tool logic, and agent wiring.

Deliberately does not call the real Gemini API or the network -- that's
covered by a manual end-to-end CLI run (see README) since it needs a live
API key and isn't deterministic/free to run in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from mcp_server.server import get_kvk_locator, get_market_price, get_severe_weather_alerts, get_weather
from mcp_server.weather_client import _geocoding_candidates, _rain_confidence, _today_spray_summary
from security.guardrails import GuardrailError, ToolRateLimiter, validate_photo

SAMPLE_PHOTO = Path(__file__).parent.parent / "sample_data" / "sample_leaf.jpg"


def test_validate_photo_accepts_real_image():
    data = validate_photo(SAMPLE_PHOTO)
    assert len(data) > 0


def test_validate_photo_rejects_missing_file(tmp_path):
    with pytest.raises(GuardrailError):
        validate_photo(tmp_path / "does_not_exist.jpg")


def test_validate_photo_rejects_disallowed_extension(tmp_path):
    bad_file = tmp_path / "leaf.txt"
    bad_file.write_text("not an image")
    with pytest.raises(GuardrailError):
        validate_photo(bad_file)


def test_validate_photo_rejects_disguised_file(tmp_path):
    fake_image = tmp_path / "leaf.jpg"
    fake_image.write_bytes(b"this is not actually jpeg data")
    with pytest.raises(GuardrailError):
        validate_photo(fake_image)


def test_rate_limiter_blocks_after_threshold():
    limiter = ToolRateLimiter(max_calls=2, window_seconds=60)

    class FakeTool:
        name = "get_weather"

    tool = FakeTool()
    assert limiter(tool, {}, None) is None
    assert limiter(tool, {}, None) is None
    blocked = limiter(tool, {}, None)
    assert blocked is not None
    assert "Rate limit exceeded" in blocked["error"]


@pytest.mark.asyncio
async def test_get_market_price_known_crop(monkeypatch):
    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)
    result = await get_market_price("wheat", "punjab")
    assert result["crop"] == "wheat"
    assert result["live"] is False
    assert "price_per_kg_inr" in result


@pytest.mark.asyncio
async def test_get_market_price_known_crop_andhra_pradesh(monkeypatch):
    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)
    result = await get_market_price("groundnut", "andhra_pradesh")
    assert result["state"] == "andhra_pradesh"
    assert result["live"] is False
    assert result["msp_per_kg_inr"] == 67.8


@pytest.mark.asyncio
async def test_get_market_price_below_msp_crop(monkeypatch):
    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)
    result = await get_market_price("rice", "punjab")
    assert result["msp_per_kg_inr"] is not None
    assert result["price_per_kg_inr"] < result["msp_per_kg_inr"]


@pytest.mark.asyncio
async def test_get_market_price_no_msp_crop(monkeypatch):
    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)
    result = await get_market_price("onion", "maharashtra")
    assert result["msp_per_kg_inr"] is None


@pytest.mark.asyncio
async def test_get_market_price_unknown_crop(monkeypatch):
    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)
    result = await get_market_price("durian", "atlantis")
    assert "error" in result


@pytest.mark.asyncio
async def test_get_market_price_prefers_live_data(monkeypatch):
    import mcp_server.server as server_module

    async def fake_live(crop, state):
        return {"price_per_kg_inr": 25.5, "markets_count": 7, "as_of": "2026-06-21"}

    monkeypatch.setattr(server_module, "get_live_modal_price", fake_live)
    result = await get_market_price("wheat", "punjab")
    assert result["live"] is True
    assert result["price_per_kg_inr"] == 25.5
    assert result["trend"] is None
    assert result["msp_per_kg_inr"] == 22.75  # still sourced from the sample CSV
    assert "7 markets" in result["source"]


@pytest.mark.asyncio
async def test_get_market_price_falls_back_when_live_unavailable(monkeypatch):
    import mcp_server.server as server_module

    async def fake_live(crop, state):
        return None

    monkeypatch.setattr(server_module, "get_live_modal_price", fake_live)
    result = await get_market_price("wheat", "punjab")
    assert result["live"] is False
    assert "sample dataset" in result["source"]


@pytest.mark.asyncio
async def test_get_live_modal_price_returns_none_without_api_key(monkeypatch):
    from mcp_server.agmarknet_client import get_live_modal_price

    monkeypatch.delenv("DATA_GOV_API_KEY", raising=False)
    assert await get_live_modal_price("wheat", "punjab") is None


@pytest.mark.asyncio
async def test_get_live_modal_price_returns_none_for_sugarcane(monkeypatch):
    from mcp_server.agmarknet_client import get_live_modal_price

    monkeypatch.setenv("DATA_GOV_API_KEY", "fake-key-for-test")
    assert await get_live_modal_price("sugarcane", "uttar_pradesh") is None


@pytest.mark.asyncio
async def test_get_live_modal_price_averages_records(monkeypatch):
    import mcp_server.agmarknet_client as agmarknet_module

    monkeypatch.setenv("DATA_GOV_API_KEY", "fake-key-for-test")

    payload = {
        "records": [
            {"modal_price": "2500", "arrival_date": "20/06/2026"},
            {"modal_price": "2600", "arrival_date": "21/06/2026"},
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await agmarknet_module.get_live_modal_price("wheat", "punjab")
    assert result["price_per_kg_inr"] == 25.5  # avg(2500, 2600) / 100
    assert result["markets_count"] == 2
    assert result["as_of"] == "2026-06-21"


@pytest.mark.asyncio
async def test_get_weather_uses_mocked_http(monkeypatch):
    geo_payload = {"results": [{"name": "Testville", "country": "Testland", "latitude": 1.0, "longitude": 2.0}]}
    forecast_payload = {
        "daily": {
            "time": ["2026-01-01"],
            "temperature_2m_max": [30.0],
            "temperature_2m_min": [20.0],
            "precipitation_probability_max": [10],
        }
    }

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            if "geocoding" in url:
                return FakeResponse(geo_payload)
            return FakeResponse(forecast_payload)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await get_weather("Testville")
    assert result["resolved_location"] == "Testville, Testland"
    assert result["max_temp_c"] == [30.0]


def test_today_spray_summary_picks_calmer_window_and_rain_onset():
    hourly = {
        "time": [
            "2026-06-20T08:00",  # morning, calm
            "2026-06-20T09:00",  # morning, calm
            "2026-06-20T13:00",  # afternoon, windy
            "2026-06-20T15:00",  # afternoon, rain likely
            "2026-06-21T08:00",  # next day -- must be ignored
        ],
        "wind_speed_10m": [8.0, 9.0, 22.0, 20.0, 5.0],
        "precipitation_probability": [0, 10, 30, 70, 0],
    }
    summary = _today_spray_summary(hourly, "2026-06-20")
    assert summary["morning_max_wind_kmh"] == 9.0
    assert summary["afternoon_max_wind_kmh"] == 22.0
    assert summary["rain_expected_from"] == "15:00"


def test_today_spray_summary_handles_empty_data():
    summary = _today_spray_summary({}, "2026-06-20")
    assert summary["morning_max_wind_kmh"] is None
    assert summary["afternoon_max_wind_kmh"] is None
    assert summary["rain_expected_from"] is None


def test_rain_confidence_levels():
    assert _rain_confidence(None) == "unknown"
    assert _rain_confidence(5) == "high"
    assert _rain_confidence(95) == "high"
    assert _rain_confidence(30) == "medium"
    assert _rain_confidence(70) == "medium"
    assert _rain_confidence(50) == "low"


@pytest.mark.asyncio
async def test_get_weather_returns_error_for_unresolvable_location(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": []}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await get_weather("Xyzzyplonkfoobar123")
    assert "error" in result


def test_geocoding_candidates_falls_back_to_shorter_prefixes():
    assert _geocoding_candidates("Amritsar, Punjab, India") == [
        "Amritsar, Punjab, India",
        "Amritsar, Punjab",
        "Amritsar",
    ]
    assert _geocoding_candidates("Amritsar") == ["Amritsar"]


def test_orchestrator_wires_all_three_sub_agents():
    from agents.orchestrator import orchestrator

    node_names = {node.name for node in orchestrator.graph.nodes}
    assert "crop_health_agent" in node_names
    assert "weather_agent" in node_names
    assert "market_agent" in node_names
    assert "advisory_writer" in node_names
    assert "merge" in node_names


RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><link>https://fake.example/cap-active-punjab.xml</link></item>
<item><link>https://fake.example/cap-expired-punjab.xml</link></item>
<item><link>https://fake.example/cap-active-kerala.xml</link></item>
</channel></rss>"""


def _cap_fixture(area: str, severity: str, expires: str) -> str:
    return f"""<?xml version="1.0"?>
<cap:alert xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <cap:info>
    <cap:event>Heavy rainfall</cap:event>
    <cap:severity>{severity}</cap:severity>
    <cap:urgency>Expected</cap:urgency>
    <cap:certainty>Likely</cap:certainty>
    <cap:headline>Heavy rainfall warning</cap:headline>
    <cap:description>Very heavy rain expected</cap:description>
    <cap:instruction>Avoid low-lying areas</cap:instruction>
    <cap:onset>2026-01-01T00:00:00+05:30</cap:onset>
    <cap:expires>{expires}</cap:expires>
    <cap:area><cap:areaDesc>{area}</cap:areaDesc></cap:area>
  </cap:info>
</cap:alert>"""


@pytest.mark.asyncio
async def test_get_active_alerts_filters_by_state_and_expiry(monkeypatch):
    import mcp_server.imd_alerts_client as imd_module

    docs = {
        "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml": RSS_FIXTURE,
        "https://fake.example/cap-active-punjab.xml": _cap_fixture(
            "Punjab", "Severe", "2099-01-01T00:00:00+05:30"
        ),
        "https://fake.example/cap-expired-punjab.xml": _cap_fixture(
            "Punjab", "Minor", "2000-01-01T00:00:00+05:30"
        ),
        "https://fake.example/cap-active-kerala.xml": _cap_fixture(
            "Kerala", "Severe", "2099-01-01T00:00:00+05:30"
        ),
    }

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return FakeResponse(docs[url])

    monkeypatch.setattr(imd_module.httpx, "AsyncClient", FakeAsyncClient)

    alerts = await imd_module.get_active_alerts("punjab")
    assert len(alerts) == 1
    assert alerts[0]["area"] == "Punjab"
    assert alerts[0]["severity"] == "Severe"


@pytest.mark.asyncio
async def test_get_active_alerts_returns_empty_when_feed_unreachable(monkeypatch):
    import mcp_server.imd_alerts_client as imd_module

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(imd_module.httpx, "AsyncClient", FakeAsyncClient)

    assert await imd_module.get_active_alerts("punjab") == []


@pytest.mark.asyncio
async def test_get_severe_weather_alerts_tool_wraps_client(monkeypatch):
    import mcp_server.server as server_module

    async def fake_alerts(state):
        return [{"event": "Heavy rainfall", "severity": "Severe"}]

    monkeypatch.setattr(server_module, "get_active_alerts", fake_alerts)
    result = await get_severe_weather_alerts("punjab")
    assert result["count"] == 1
    assert result["active_alerts"][0]["severity"] == "Severe"


PUNJAB_KVK_TABLE_FIXTURE = """
<table><tbody><tr><td><strong>S. No.</strong></td>
<td><strong>Address of Krishi Vigyan Kendras</strong></td>
<td><strong>Host Organization</strong></td>
<td><strong>Year of Sanction</strong></td>
</tr><tr><td colspan="4"><strong>Punjab (2)</strong></td>
</tr><tr><td>1.</td>
<td>Krishi Vigyan Kendra,<br />
Samrala,<br />
Distt. Ludhiana-141 114</td>
<td>Vice-Chancellor,<br />
Punjab Agricultural University,<br />
Ludhiana-141 004</td>
<td>2004<br />
SAU</td>
</tr><tr><td>2.</td>
<td>Krishi Vigyan Kendra,<br />
Usman,<br />
Dist Amritsar-143 001</td>
<td>Vice-Chancellor,<br />
Punjab Agricultural University,<br />
Ludhiana-141 004</td>
<td>2004<br />
SAU</td>
</tr></tbody></table>
"""


@pytest.mark.asyncio
async def test_resolve_pincode_known(monkeypatch):
    import mcp_server.kvk_locator_client as kvk_module

    payload = [
        {
            "Status": "Success",
            "PostOffice": [{"District": "Ludhiana", "State": "Punjab"}],
        }
    ]

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(kvk_module.httpx, "AsyncClient", FakeAsyncClient)

    result = await kvk_module.resolve_pincode("141001")
    assert result == {"district": "Ludhiana", "state": "punjab"}


@pytest.mark.asyncio
async def test_resolve_pincode_unresolvable(monkeypatch):
    import mcp_server.kvk_locator_client as kvk_module

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"Status": "Error", "PostOffice": None}]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(kvk_module.httpx, "AsyncClient", FakeAsyncClient)

    assert await kvk_module.resolve_pincode("000000") is None


@pytest.mark.asyncio
async def test_find_kvk_for_district_matches_row(monkeypatch):
    import mcp_server.kvk_locator_client as kvk_module

    class FakeResponse:
        text = PUNJAB_KVK_TABLE_FIXTURE

        def raise_for_status(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(kvk_module.httpx, "AsyncClient", FakeAsyncClient)

    match = await kvk_module.find_kvk_for_district("punjab", "Amritsar")
    assert match is not None
    assert "Amritsar" in match["address"]
    assert "Punjab Agricultural University" in match["host_organization"]


@pytest.mark.asyncio
async def test_find_kvk_for_district_no_match_returns_none(monkeypatch):
    import mcp_server.kvk_locator_client as kvk_module

    class FakeResponse:
        text = PUNJAB_KVK_TABLE_FIXTURE

        def raise_for_status(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(kvk_module.httpx, "AsyncClient", FakeAsyncClient)

    assert await kvk_module.find_kvk_for_district("punjab", "Nonexistentpur") is None


@pytest.mark.asyncio
async def test_find_kvk_for_district_unsupported_state_returns_none():
    from mcp_server.kvk_locator_client import find_kvk_for_district

    assert await find_kvk_for_district("telangana", "Hyderabad") is None


@pytest.mark.asyncio
async def test_get_kvk_for_pincode_falls_back_when_unresolvable(monkeypatch):
    import mcp_server.kvk_locator_client as kvk_module

    async def fake_resolve(pincode):
        return None

    monkeypatch.setattr(kvk_module, "resolve_pincode", fake_resolve)

    result = await kvk_module.get_kvk_for_pincode("999999")
    assert "error" in result
    assert result["kvk_locator_url"] == kvk_module.GENERAL_KVK_INDEX_URL


@pytest.mark.asyncio
async def test_get_kvk_locator_tool_wraps_client(monkeypatch):
    import mcp_server.server as server_module

    async def fake_get_kvk(pincode):
        return {"district": "Ludhiana", "state": "punjab", "matched_kvk": None, "kvk_locator_url": "x"}

    monkeypatch.setattr(server_module, "get_kvk_for_pincode", fake_get_kvk)
    result = await get_kvk_locator("141001")
    assert result["district"] == "Ludhiana"


def test_setup_langsmith_tracing_is_noop_without_api_key(monkeypatch):
    from observability import setup_langsmith_tracing

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert setup_langsmith_tracing() is False
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ


def test_setup_langsmith_tracing_sets_otel_env_and_activates(monkeypatch):
    import observability

    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("LANGSMITH_PROJECT", "agro-advisor-test")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    calls = []
    monkeypatch.setattr(
        "google.adk.telemetry.setup.maybe_set_otel_providers",
        lambda: calls.append(True),
    )

    assert observability.setup_langsmith_tracing() is True
    assert calls == [True]
    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == observability.LANGSMITH_OTEL_ENDPOINT
    assert os.environ["OTEL_EXPORTER_OTLP_HEADERS"] == (
        "x-api-key=fake-key-for-test,Langsmith-Project=agro-advisor-test"
    )
