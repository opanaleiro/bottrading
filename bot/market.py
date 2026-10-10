"""Synthetic demo prices and verified public spot market data from Kraken.

No exchange credentials are required and no order endpoint is used. Real-data
errors are surfaced to the caller; synthetic prices never replace real quotes.
"""

from __future__ import annotations

import asyncio
import math
import random
import time

import httpx


ASSETS = (
    ("BTC", "XBTUSD", 62500.0), ("ETH", "ETHUSD", 2750.0),
    ("SOL", "SOLUSD", 148.0), ("XRP", "XRPUSD", 0.59),
    ("ADA", "ADAUSD", 0.37), ("DOGE", "XDGUSD", 0.115),
    ("DOT", "DOTUSD", 4.75), ("AVAX", "AVAXUSD", 27.4),
    ("LINK", "LINKUSD", 11.9), ("LTC", "LTCUSD", 67.0),
    ("BCH", "BCHUSD", 345.0), ("UNI", "UNIUSD", 6.45),
    ("ATOM", "ATOMUSD", 4.6), ("NEAR", "NEARUSD", 4.2),
    ("AAVE", "AAVEUSD", 139.0), ("XLM", "XLMUSD", 0.098),
)
KRAKEN_BASE_URL = "https://api.kraken.com/0/public"
HISTORY_TTL_SECONDS = 60
OHLC_REQUEST_INTERVAL_SECONDS = 1.05
_history_cache: dict[str, tuple[float, list[list]]] = {}
_pair_keys: dict[str, str] = {}


class MarketDataError(RuntimeError):
    """The requested real market snapshot could not be verified completely."""


def _demo_price(asset_index: int, base: float, candle_index: int) -> float:
    # Independent seeded noise keeps repeated requests reproducible. The
    # common cycle loosely models correlation between crypto assets.
    noise = random.Random(1777 + asset_index * 100003 + candle_index).gauss(0, 0.0017)
    common = 0.012 * math.sin(candle_index / 25)
    cycle = 0.014 * math.sin(candle_index / (12 + asset_index % 5) + asset_index * 0.63)
    short_cycle = 0.003 * math.sin(candle_index / 3.2 + asset_index)
    return base * math.exp(common + cycle + short_cycle + noise)


async def fetch_demo_markets(step: int) -> list[dict]:
    """Return 16 explicitly synthetic deterministic 15-minute histories.

    Each step advances one synthetic candle; demo time is accelerated and
    these prices should never be presented as live market observations.
    """
    end = 200 + max(0, int(step))
    markets = []
    for index, (asset, _pair, base) in enumerate(ASSETS):
        history = [_demo_price(index, base, candle) for candle in range(end - 96, end + 1)]
        markets.append({
            "symbol": f"{asset}/USD",
            "price": history[-1],
            "change_pct": (history[-1] / history[0] - 1) * 100,
            "candles": history,
            "source": "demo",
            "change_period": "24h_approx",
            "interval_minutes": 15,
            "synthetic": True,
        })
    return markets


async def _public(client: httpx.AsyncClient, endpoint: str, params: dict | None = None) -> dict:
    try:
        response = await client.get(f"{KRAKEN_BASE_URL}/{endpoint}", params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise MarketDataError(f"Kraken {endpoint}: no se pudo obtener una respuesta válida ({type(error).__name__}).") from error
    if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("result"), dict):
        detail = ", ".join(str(item) for item in payload.get("error", [])) if isinstance(payload, dict) else "formato inesperado"
        raise MarketDataError(f"Kraken {endpoint}: {detail or 'respuesta incompleta'}.")
    return payload["result"]


async def _resolve_pairs(client: httpx.AsyncClient) -> dict[str, str]:
    if _pair_keys:
        return dict(_pair_keys)
    requested = {pair: asset for asset, pair, _base in ASSETS}
    data = await _public(client, "AssetPairs", {"pair": ",".join(requested)})
    mapping = {}
    for key, pair_data in data.items():
        if not isinstance(pair_data, dict):
            continue
        alternative = pair_data.get("altname")
        if alternative in requested:
            mapping[requested[alternative]] = key
    if len(mapping) != len(ASSETS):
        missing = sorted({asset for asset, _, _ in ASSETS} - mapping.keys())
        raise MarketDataError(f"Kraken: pares USD no disponibles: {', '.join(missing)}.")
    _pair_keys.update(mapping)
    return mapping


def _validated_history(rows: list, symbol: str) -> list[list]:
    if not isinstance(rows, list) or len(rows) < 97:
        raise MarketDataError(f"Kraken {symbol}: menos de 97 velas para el análisis.")
    valid = []
    previous_timestamp = 0
    for row in rows:
        try:
            timestamp = int(row[0])
            close = float(row[4])
        except (TypeError, ValueError, IndexError, OverflowError) as error:
            raise MarketDataError(f"Kraken {symbol}: vela inválida.") from error
        if timestamp <= previous_timestamp or not math.isfinite(close) or close <= 0:
            raise MarketDataError(f"Kraken {symbol}: historial desordenado o precio inválido.")
        previous_timestamp = timestamp
        valid.append([timestamp, close])
    return valid


async def fetch_kraken_markets() -> list[dict]:
    """Fetch one all-real snapshot, with fresh tickers and cached 15m OHLC.

    Histories are cached for one minute to respect public API rate limits.
    Tickers are fetched on every call. A failed asset invalidates the snapshot
    so the broker cannot accidentally trade stale or mixed demo prices.
    """
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False, headers={"User-Agent": "bottrading-paper/1.0"}) as client:
        pairs = await _resolve_pairs(client)
        async def history(asset: str) -> tuple[str, list[list]]:
            cached = _history_cache.get(asset)
            if cached is not None and time.monotonic() - cached[0] < HISTORY_TTL_SECONDS:
                return asset, cached[1]
            # Avoid bursts against the public endpoint. Warm-up needs ~17s,
            # then most cycles reuse histories and only read a fresh ticker.
            await asyncio.sleep(OHLC_REQUEST_INTERVAL_SECONDS)
            result = await _public(client, "OHLC", {"pair": pairs[asset], "interval": 15})
            rows = result.get(pairs[asset])
            # Kraken returns canonical pair names; fallback only selects the
            # sole OHLC array returned for the requested pair, never another
            # asset from a bulk response.
            if rows is None:
                candidates = [value for key, value in result.items() if key != "last"]
                rows = candidates[0] if len(candidates) == 1 else None
            verified = _validated_history(rows, asset)
            _history_cache[asset] = (time.monotonic(), verified)
            return asset, verified

        histories = {}
        for asset, _, _ in ASSETS:
            symbol, rows = await history(asset)
            histories[symbol] = rows
        # Read quotes after any history warm-up, so execution uses a current
        # snapshot rather than prices read before the OHLC requests.
        tickers = await _public(client, "Ticker", {"pair": ",".join(pairs.values())})
        cutoff = time.time() - 86400
        markets = []
        for asset, _requested, _base in ASSETS:
            try:
                ticker = tickers[pairs[asset]]
                price = float(ticker["c"][0])
            except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
                raise MarketDataError(f"Kraken {asset}: precio ticker ausente o inválido.") from error
            if not math.isfinite(price) or price <= 0:
                raise MarketDataError(f"Kraken {asset}: precio actual inválido.")
            rows = histories[asset]
            if time.time() - rows[-1][0] > 1800:
                raise MarketDataError(f"Kraken {asset}: el historial tiene más de 30 minutos de retraso.")
            past_rows = [row for row in rows if row[0] <= cutoff]
            if not past_rows:
                raise MarketDataError(f"Kraken {asset}: historial insuficiente para el cambio de 24 horas.")
            candles = [row[1] for row in rows[-97:]]
            candles[-1] = price
            markets.append({
                "symbol": f"{asset}/USD",
                "price": price,
                "change_pct": (price / past_rows[-1][1] - 1) * 100,
                "candles": candles,
                "source": "kraken",
                "change_period": "24h_approx",
                "interval_minutes": 15,
                "synthetic": False,
            })
        return markets
