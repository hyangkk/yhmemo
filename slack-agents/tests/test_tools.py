"""
Tests for core/tools.py
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tools import (
    _resolve_coords, _resolve_crypto_id, _current_time,
    execute_tool, execute_tool_calls,
    CITY_COORDS, CRYPTO_IDS,
)


# ── _resolve_coords ──────────────────────────────────────

def test_resolve_coords_known_city_seoul():
    lat, lon, name = _resolve_coords("서울")
    assert lat == CITY_COORDS["서울"][0]
    assert lon == CITY_COORDS["서울"][1]
    assert name == "서울"


def test_resolve_coords_known_city_busan():
    lat, lon, name = _resolve_coords("부산")
    assert lat == CITY_COORDS["부산"][0]
    assert lon == CITY_COORDS["부산"][1]


def test_resolve_coords_known_city_tokyo():
    lat, lon, name = _resolve_coords("tokyo")
    assert lat == CITY_COORDS["tokyo"][0]
    assert lon == CITY_COORDS["tokyo"][1]


def test_resolve_coords_case_insensitive():
    lat, lon, name = _resolve_coords("TOKYO")
    assert lat == CITY_COORDS["tokyo"][0]


def test_resolve_coords_with_whitespace():
    lat, lon, name = _resolve_coords("  서울  ")
    assert lat == CITY_COORDS["서울"][0]


def test_resolve_coords_default_unknown_city():
    """Unknown city defaults to Seoul coordinates."""
    lat, lon, name = _resolve_coords("unknown_city_xyz")
    assert lat == 37.5665  # Seoul lat
    assert lon == 126.978  # Seoul lon
    assert name == "unknown_city_xyz"


def test_resolve_coords_partial_match():
    """Partial match should work (e.g., 'san' matches 'san francisco')."""
    lat, lon, name = _resolve_coords("san francisco")
    assert lat == CITY_COORDS["san francisco"][0]


# ── _resolve_crypto_id ───────────────────────────────────

def test_resolve_crypto_id_korean_name():
    assert _resolve_crypto_id("비트코인") == "bitcoin"
    assert _resolve_crypto_id("이더리움") == "ethereum"
    assert _resolve_crypto_id("금") == "pax-gold"


def test_resolve_crypto_id_english_name():
    assert _resolve_crypto_id("bitcoin") == "bitcoin"
    assert _resolve_crypto_id("ethereum") == "ethereum"


def test_resolve_crypto_id_ticker():
    assert _resolve_crypto_id("btc") == "bitcoin"
    assert _resolve_crypto_id("eth") == "ethereum"
    assert _resolve_crypto_id("xrp") == "ripple"
    assert _resolve_crypto_id("sol") == "solana"


def test_resolve_crypto_id_case_insensitive():
    assert _resolve_crypto_id("BTC") == "bitcoin"
    assert _resolve_crypto_id("ETH") == "ethereum"


def test_resolve_crypto_id_unknown_returns_input():
    assert _resolve_crypto_id("unknown_coin") == "unknown_coin"


def test_resolve_crypto_id_with_whitespace():
    assert _resolve_crypto_id("  btc  ") == "bitcoin"


# ── _current_time ────────────────────────────────────────

def test_current_time_returns_kst_format():
    result = _current_time()
    assert "KST" in result
    # Should contain date in YYYY-MM-DD format
    assert "-" in result
    # Should contain day of week in Korean
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    assert any(wd in result for wd in weekdays)
    # Should contain time in HH:MM:SS format
    assert ":" in result


# ── execute_tool dispatching ─────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_dispatches_now():
    result = await execute_tool("now", [])
    assert "KST" in result


@pytest.mark.asyncio
async def test_execute_tool_unknown_tool():
    result = await execute_tool("nonexistent_tool", [])
    assert "알 수 없는 도구" in result


@pytest.mark.asyncio
async def test_execute_tool_handles_exception():
    """Tool that raises should return error string."""
    with patch("core.tools._weather", side_effect=Exception("API down")):
        result = await execute_tool("weather", ["서울"])
        assert "오류" in result or "API down" in result


# ── execute_tool_calls ───────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_calls_combines_results():
    """Multiple tool calls should be combined."""
    with patch("core.tools._weather", new_callable=AsyncMock, return_value="Weather: Sunny"), \
         patch("core.tools._crypto_price", new_callable=AsyncMock, return_value="BTC: $50000"):
        tool_calls = [
            {"tool": "weather", "args": ["서울"]},
            {"tool": "crypto", "args": ["비트코인"]},
        ]
        result = await execute_tool_calls(tool_calls)
        assert "[weather]" in result
        assert "[crypto]" in result
        assert "Sunny" in result
        assert "BTC" in result


@pytest.mark.asyncio
async def test_execute_tool_calls_empty():
    result = await execute_tool_calls([])
    assert result == ""


@pytest.mark.asyncio
async def test_execute_tool_calls_single():
    with patch("core.tools._current_time", return_value="2026-03-06 (목) 10:00:00 KST"):
        result = await execute_tool_calls([{"tool": "now", "args": []}])
        assert "[now]" in result
        assert "2026-03-06" in result


# ── Weather tool (mocked httpx) ──────────────────────────

@pytest.mark.asyncio
async def test_weather_tool_mocked():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "current": {
            "temperature_2m": 15.5,
            "apparent_temperature": 13.2,
            "relative_humidity_2m": 55,
            "wind_speed_10m": 12.3,
            "precipitation": 0,
            "weather_code": 1,
        },
        "daily": {
            "time": ["2026-03-06", "2026-03-07", "2026-03-08"],
            "temperature_2m_max": [18.0, 20.0, 22.0],
            "temperature_2m_min": [8.0, 10.0, 12.0],
            "sunrise": ["2026-03-06T06:30", "2026-03-07T06:29", "2026-03-08T06:28"],
            "sunset": ["2026-03-06T18:20", "2026-03-07T18:21", "2026-03-08T18:22"],
            "uv_index_max": [5.0, 6.0, 4.0],
            "precipitation_sum": [0, 0, 2.5],
            "weather_code": [1, 3, 61],
        },
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("core.tools.httpx.AsyncClient", return_value=mock_client):
        result = await execute_tool("weather", ["서울"])
        assert "15.5" in result
        assert "서울" in result


# ── Exchange rate tool (mocked httpx) ────────────────────

@pytest.mark.asyncio
async def test_exchange_tool_mocked():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "rates": {"KRW": 1350.50, "JPY": 150.25},
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("core.tools.httpx.AsyncClient", return_value=mock_client):
        result = await execute_tool("exchange", ["USD", "KRW"])
        assert "1,350.50" in result
        assert "USD" in result
        assert "KRW" in result


# ── Crypto tool (mocked httpx) ───────────────────────────

@pytest.mark.asyncio
async def test_crypto_tool_mocked():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "bitcoin": {
            "usd": 50000.0,
            "krw": 67500000,
            "usd_24h_change": 2.5,
            "usd_market_cap": 950000000000,
        }
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("core.tools.httpx.AsyncClient", return_value=mock_client):
        result = await execute_tool("crypto", ["비트코인"])
        assert "50,000" in result
        assert "비트코인" in result
        assert "2.5" in result or "2.50" in result


# ── execute_tool default args ────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_weather_default_location():
    """Weather with no args defaults to Seoul."""
    with patch("core.tools._weather", new_callable=AsyncMock, return_value="Seoul weather") as mock_weather:
        await execute_tool("weather", [])
        mock_weather.assert_called_once_with("서울")


@pytest.mark.asyncio
async def test_execute_tool_exchange_default_currencies():
    """Exchange with no args defaults to USD/KRW."""
    with patch("core.tools._exchange_rate", new_callable=AsyncMock, return_value="rate") as mock_ex:
        await execute_tool("exchange", [])
        mock_ex.assert_called_once_with("USD", "KRW")


@pytest.mark.asyncio
async def test_execute_tool_crypto_default_asset():
    """Crypto with no args defaults to bitcoin."""
    with patch("core.tools._crypto_price", new_callable=AsyncMock, return_value="price") as mock_cp:
        await execute_tool("crypto", [])
        mock_cp.assert_called_once_with("비트코인")
