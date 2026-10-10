"""Explainable technical analysis and fully collateralised paper-trading risk.

This module has no network access and never places real orders. The strategy is
an inspectable baseline, not a prediction of future returns or an AI model.
"""

from __future__ import annotations

import math
import statistics
from typing import Any


MIN_CANDLES = 60


def _aggression(value: int) -> int:
    return max(1, min(10, int(value)))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def ema(prices: list[float], period: int) -> float:
    """Exponential moving average, seeded from the oldest observation."""
    if not prices or period < 1:
        raise ValueError("EMA necesita precios y un periodo positivo.")
    value = prices[0]
    weight = 2 / (period + 1)
    for price in prices[1:]:
        value += weight * (price - value)
    return value


def rsi(prices: list[float], period: int = 14) -> float:
    """Wilder RSI; a flat market has a neutral RSI of 50."""
    if len(prices) <= period or period < 1:
        raise ValueError("RSI necesita al menos periodo + 1 precios.")
    changes = [right - left for left, right in zip(prices, prices[1:])]
    gain = sum(max(change, 0) for change in changes[:period]) / period
    loss = sum(max(-change, 0) for change in changes[:period]) / period
    for change in changes[period:]:
        gain = (gain * (period - 1) + max(change, 0)) / period
        loss = (loss * (period - 1) + max(-change, 0)) / period
    if gain == loss == 0:
        return 50.0
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def _pipeline(source: str) -> list[dict[str, str]]:
    return [
        {"name": "Mercado", "status": "ok", "detail": "Precios sintéticos" if source == "demo" else "Mercado spot público de Kraken"},
        {"name": "Derivados", "status": "unavailable", "detail": "Sin proveedor conectado"},
        {"name": "Volatilidad", "status": "ok", "detail": "Desviación de los retornos por vela"},
        {"name": "DEX", "status": "unavailable", "detail": "Sin proveedor conectado"},
        {"name": "Blockchain", "status": "unavailable", "detail": "Sin proveedor conectado"},
        {"name": "Sentimiento", "status": "unavailable", "detail": "Sin proveedor conectado"},
        {"name": "Noticias", "status": "unavailable", "detail": "Sin proveedor conectado"},
        {"name": "Macro", "status": "unavailable", "detail": "Sin proveedor conectado"},
        {"name": "Motor de datos", "status": "ok", "detail": "Historial ordenado y validado"},
        {"name": "Indicadores", "status": "ok", "detail": "EMA 12/26, RSI 14 y momentum"},
        {"name": "Filtros", "status": "ok", "detail": "Confluencia técnica y control de sobrecompra/sobreventa"},
        {"name": "Analista IA", "status": "unavailable", "detail": "No hay modelo de IA conectado; señal técnica explicable"},
        {"name": "Riesgo", "status": "pending", "detail": "Se aplica con el saldo y las posiciones actuales"},
        {"name": "Ejecución", "status": "paper", "detail": "Solo simulación; ninguna orden real"},
        {"name": "Posición", "status": "pending", "detail": "Stop y objetivo vigilados durante los ciclos del bot"},
    ]


def analyze_market(market: dict, aggressiveness: int) -> dict:
    """Return an explainable buy/sell/wait decision from one market snapshot.

Sell is a proposed simulated short, not an instruction to borrow real assets.
Confidence expresses indicator agreement and is not a win probability.
"""
    source = market.get("source", "unknown")
    pipeline = _pipeline(source)
    price = _number(market.get("price"))
    candles = [_number(value) for value in market.get("candles", [])]
    result = {
        "symbol": str(market.get("symbol", "?")),
        "price": price if price is not None else 0.0,
        "change_pct": _number(market.get("change_pct")) or 0.0,
        "signal": "wait",
        "confidence": 0.0,
        "indicators": {"rsi": 0.0, "ema_fast": 0.0, "ema_slow": 0.0, "volatility_pct": 0.0, "momentum_pct": 0.0},
        "reason": "Datos insuficientes o inválidos: se necesitan 60 precios positivos.",
        "pipeline": pipeline,
    }
    if price is None or price <= 0 or len(candles) < MIN_CANDLES or any(value is None or value <= 0 for value in candles):
        for stage in pipeline:
            if stage["status"] == "ok":
                stage["status"] = "error" if stage["name"] in ("Mercado", "Motor de datos") else "pending"
                stage["detail"] = "Esperando un historial válido"
        return result

    # Current quote replaces the still-open candle, rather than adding an
    # extra return on every polling cycle.
    prices = [float(value) for value in candles]
    prices[-1] = price
    fast = ema(prices, 12)
    slow = ema(prices, 26)
    strength = rsi(prices)
    returns = [100 * math.log(right / left) for left, right in zip(prices, prices[1:])]
    volatility = statistics.stdev(returns)
    momentum = 100 * (prices[-1] / prices[-7] - 1)
    trend = 100 * (fast / slow - 1)
    aggression = _aggression(aggressiveness)
    threshold = 0.04 + (10 - aggression) * 0.014
    momentum_threshold = threshold * 0.65
    signal = "wait"
    if trend > threshold and momentum > momentum_threshold and 30 - aggression <= strength <= 70 + aggression:
        signal = "buy"
    elif trend < -threshold and momentum < -momentum_threshold and 30 - aggression <= strength <= 70 + aggression:
        signal = "sell"

    # Scale agreement to recent noise; deliberately cap confidence below 1.
    agreement = min(1.0, abs(trend) / max(0.08, volatility * 1.8))
    momentum_agreement = min(1.0, abs(momentum) / max(0.15, volatility * 2.5))
    confidence = min(0.92, 0.5 + 0.24 * agreement + 0.18 * momentum_agreement) if signal != "wait" else 0.35
    if signal == "buy":
        reason = "EMA rápida sobre la lenta, momentum positivo y RSI dentro del filtro: candidato long simulado."
    elif signal == "sell":
        reason = "EMA rápida bajo la lenta, momentum negativo y RSI dentro del filtro: candidato short simulado."
    elif strength > 70 + aggression:
        reason = "RSI elevado: se espera para evitar perseguir una subida."
    elif strength < 30 - aggression:
        reason = "RSI bajo: se espera para evitar perseguir una caída."
    else:
        reason = "La tendencia y el momentum no coinciden con suficiente fuerza."
    result.update(
        signal=signal,
        confidence=round(confidence, 4),
        indicators={
            "rsi": round(strength, 3),
            "ema_fast": round(fast, 10),
            "ema_slow": round(slow, 10),
            "volatility_pct": round(volatility, 5),
            "momentum_pct": round(momentum, 4),
        },
        reason=reason,
    )
    pipeline[10]["detail"] = reason
    return result


def risk_plan(equity: float, cash: float, price: float, volatility_pct: float, aggressiveness: int, positions_count: int, confidence: float) -> dict | None:
    """Size a fully cash-reserved paper position with an equity risk budget.

The same collateral rule applies to simulated longs and shorts. Stop distance
limits intended loss, but fills after price gaps can exceed that amount.
"""
    values = [_number(value) for value in (equity, cash, price, volatility_pct, confidence)]
    if any(value is None for value in values):
        return None
    equity, cash, price, volatility_pct, confidence = values
    if equity <= 0 or cash <= 0 or price <= 0 or volatility_pct < 0 or not 0 <= confidence <= 1 or positions_count < 0:
        return None
    aggression = _aggression(aggressiveness)
    if positions_count >= 2 + (aggression - 1) * 4 // 9 or confidence < 0.5:
        return None
    scale = (aggression - 1) / 9
    stop_distance = min(8.0, max(0.8, volatility_pct * (2.8 - aggression * 0.06)))
    risk_budget = equity * (0.0025 + scale * 0.0075) * (0.5 + confidence * 0.5)
    allocation_cap = equity * (0.05 + scale * 0.11)
    # Preserve spare cash for fees rather than allowing rounding or commission
    # to create an implicitly leveraged position.
    notional = min(risk_budget / (stop_distance / 100), allocation_cap, cash * 0.985)
    if notional < 10:
        return None
    return {
        "quantity": notional / price,
        "notional": notional,
        "stop_distance_pct": stop_distance,
        "take_distance_pct": stop_distance * (1.4 + aggression * 0.06),
    }


def exit_reason(position: dict, price: float, close_only: bool = False) -> str | None:
    """Return a stop/target/close-only reason, checking both long and short."""
    if close_only:
        return "close_only"
    price = _number(price)
    if price is None or price <= 0:
        return None
    direction = position.get("direction", position.get("side", "long"))
    is_short = direction in ("short", "sell")
    stop = _number(position.get("stop_price", position.get("stop_loss")))
    take = _number(position.get("take_price", position.get("take_profit")))
    if stop is not None and stop > 0 and (price >= stop if is_short else price <= stop):
        return "stop_loss"
    if take is not None and take > 0 and (price <= take if is_short else price >= take):
        return "take_profit"
    return None
