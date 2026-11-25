import json
import re
import threading
import time
from datetime import datetime

import requests

import config

try:
    import ccxt
except Exception:
    ccxt = None

DATA_API = "https://data-api.binance.vision/api/v3"


def market_symbol(symbol):
    return symbol.replace("/", "").upper()


def fetch_klines(symbol, interval="1h", limit=120):
    response = requests.get(
        f"{DATA_API}/klines",
        params={"symbol": market_symbol(symbol), "interval": interval, "limit": limit},
        timeout=15,
    )
    response.raise_for_status()
    rows = response.json()
    return [
        {
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
    ]


def fetch_ticker(symbol):
    response = requests.get(
        f"{DATA_API}/ticker/24hr",
        params={"symbol": market_symbol(symbol)},
        timeout=15,
    )
    response.raise_for_status()
    row = response.json()
    return {
        "symbol": symbol,
        "price": float(row["lastPrice"]),
        "change_percent": float(row["priceChangePercent"]),
        "high": float(row["highPrice"]),
        "low": float(row["lowPrice"]),
        "volume": float(row["quoteVolume"]),
    }


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for previous, current in zip(values[-period - 1:-1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + average_gain / average_loss))


def build_snapshot(symbol, candles, ticker):
    closes = [c["close"] for c in candles]
    last = closes[-1]
    return {
        "symbol": symbol,
        "price": round(last, 6),
        "change_24h": round(ticker["change_percent"], 3),
        "high_24h": round(ticker["high"], 6),
        "low_24h": round(ticker["low"], 6),
        "sma_20": round(sma(closes, 20), 6) if sma(closes, 20) else None,
        "sma_50": round(sma(closes, 50), 6) if sma(closes, 50) else None,
        "rsi_14": round(rsi(closes), 2) if rsi(closes) is not None else None,
        "recent_closes": [round(value, 6) for value in closes[-24:]],
    }


PROMPT = """You are a cautious crypto trading analyst. Analyze the market snapshot and decide.
Reply with ONLY a JSON object and no markdown, exactly in this shape:
{"action":"buy"|"sell"|"hold","confidence":0.0,"reason":"one short sentence"}

Rules:
- Use the moving averages and RSI to judge trend and momentum.
- Be conservative: prefer "hold" when signals are mixed or weak.
- confidence must be a number between 0 and 1.
- reason must be one sentence under 140 characters.

Market snapshot:
"""


def ask_ai(snapshot, settings):
    fallback = {
        "action": "hold",
        "confidence": 0.0,
        "reason": "AI unavailable - no trade placed",
        "model": settings.get("model", ""),
        "error": True,
    }
    url = settings.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
    try:
        response = requests.post(
            f"{url}/api/generate",
            json={
                "model": settings.get("model", "qwen2.5:3b"),
                "prompt": PROMPT + json.dumps(snapshot),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.15, "num_predict": 180},
            },
            timeout=120,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        decision = json.loads(cleaned)
        action = str(decision.get("action", "hold")).lower()
        if action not in ("buy", "sell", "hold"):
            action = "hold"
        confidence = float(decision.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        return {
            "action": action,
            "confidence": round(confidence, 3),
            "reason": str(decision.get("reason", ""))[:300],
            "model": settings.get("model", ""),
            "error": False,
        }
    except Exception as exc:
        fallback["reason"] = f"AI unavailable: {type(exc).__name__}: {exc}"[:300]
        return fallback


def list_models(settings):
    url = settings.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
    try:
        response = requests.get(f"{url}/api/tags", timeout=8)
        response.raise_for_status()
        return [row["name"] for row in response.json().get("models", [])]
    except Exception:
        return []


def get_exchange(settings):
    if ccxt is None:
        raise RuntimeError("ccxt is not installed")
    exchange_id = settings.get("exchange") or "binanceus"
    if not hasattr(ccxt, exchange_id):
        raise RuntimeError(f"Unknown exchange: {exchange_id}")
    return getattr(ccxt, exchange_id)(
        {
            "apiKey": settings.get("api_key", ""),
            "secret": settings.get("api_secret", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )


def fetch_live_balance(settings):
    if not settings.get("api_key") or not settings.get("api_secret"):
        return None
    try:
        exchange = get_exchange(settings)
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {}) or {}
        return {
            "free": float(usdt.get("free", 0.0)),
            "total": float(usdt.get("total", 0.0)),
            "exchange": settings.get("exchange"),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "exchange": settings.get("exchange")}


def record_trade(state, trade):
    state.setdefault("trades", []).append(trade)
    state["trades"] = state["trades"][-500:]


def paper_fill(state, symbol, side, amount, price):
    paper = state["paper"]
    positions = paper.setdefault("positions", {})
    cost = amount * price
    held = positions.get(symbol, {"amount": 0.0, "avg_price": 0.0})
    if side == "buy":
        paper["cash"] -= cost
        total_cost = held["amount"] * held["avg_price"] + cost
        held["amount"] += amount
        held["avg_price"] = total_cost / held["amount"] if held["amount"] else 0.0
    else:
        sell_amount = min(amount, held["amount"])
        if sell_amount <= 0:
            raise ValueError("Not enough position to sell")
        paper["cash"] += sell_amount * price
        pnl = (price - held["avg_price"]) * sell_amount
        paper["realized_pnl"] += pnl
        state["daily_pnl"] = state.get("daily_pnl", 0.0) + pnl
        held["amount"] -= sell_amount
        if held["amount"] <= 1e-12:
            positions.pop(symbol, None)
    if held["amount"] > 0:
        positions[symbol] = held
    return round(cost, 4)


def execute_trade(symbol, side, amount_usdt, settings, state, price=None):
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if price is None:
        ticker = fetch_ticker(symbol)
        price = ticker["price"]
    amount_usdt = float(amount_usdt)
    if amount_usdt <= 0:
        raise ValueError("amount must be positive")

    mode = settings.get("mode", "live")
    live = mode == "live" and bool(settings.get("api_key")) and bool(settings.get("api_secret"))
    trade = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "side": side,
        "price": round(price, 8),
        "amount_usdt": round(amount_usdt, 4),
        "amount": round(amount_usdt / price, 8),
        "mode": "LIVE" if live else "PAPER",
        "source": "auto" if settings.get("_auto") else "manual",
        "id": "",
    }

    if live:
        exchange = get_exchange(settings)
        amount = amount_usdt / price
        amount = exchange.amount_to_precision(symbol, amount)
        if side == "buy":
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.create_market_sell_order(symbol, amount)
        trade["id"] = str(order.get("id", ""))
        trade["price"] = float(order.get("average") or order.get("price") or price)
    else:
        paper_fill(state, symbol, side, trade["amount"], price)

    record_trade(state, trade)
    config.append_log(
        state,
        f"{trade['mode']} {side.upper()} {symbol} {trade['amount_usdt']} USDT @ {trade['price']}",
        "trade",
    )
    return trade


class TradingEngine:
    def __init__(self):
        self.running = False
        self.thread = None

    def is_running(self):
        return self.running

    def start(self):
        if self.running:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        return True

    def _loop(self):
        while self.running:
            settings = config.load_settings()
            try:
                self.run_cycle(settings)
            except Exception as exc:
                state = config.load_state()
                config.append_log(state, f"Engine cycle error: {type(exc).__name__}: {exc}", "error")
                config.save_state(state)
            delay = max(10, int(settings.get("interval_seconds", 60)))
            for _ in range(delay):
                if not self.running:
                    break
                time.sleep(1)

    def run_cycle(self, settings=None):
        settings = settings or config.load_settings()
        state = config.load_state()
        results = []
        for symbol in settings.get("symbols", []):
            if not self.running and settings.get("_auto"):
                break
            try:
                candles = fetch_klines(symbol)
                ticker = fetch_ticker(symbol)
                snapshot = build_snapshot(symbol, candles, ticker)
                decision = ask_ai(snapshot, settings)
                entry = {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": symbol,
                    "price": snapshot["price"],
                    "rsi": snapshot["rsi_14"],
                    "sma20": snapshot["sma_20"],
                    "sma50": snapshot["sma_50"],
                    **decision,
                }
                state.setdefault("decisions", []).insert(0, entry)
                state["decisions"] = state["decisions"][-300:]
                config.append_log(
                    state,
                    f"{symbol} AI says {decision['action'].upper()} ({decision['confidence']:.2f}): {decision['reason']}",
                    "ai",
                )
                if (
                    settings.get("auto_trade")
                    and not decision.get("error")
                    and decision["action"] != "hold"
                    and decision["confidence"] >= float(settings.get("min_confidence", 0.6))
                ):
                    limit = float(settings.get("max_order_usdt", 50))
                    if abs(state.get("daily_pnl", 0.0)) >= float(settings.get("max_daily_loss_usdt", 100)):
                        config.append_log(state, "Daily loss limit reached - trade skipped", "error")
                    else:
                        auto_settings = dict(settings)
                        auto_settings["_auto"] = True
                        trade = execute_trade(
                            symbol, decision["action"], limit, auto_settings, state, snapshot["price"]
                        )
                        entry["trade"] = trade
            except Exception as exc:
                config.append_log(
                    state,
                    f"{symbol} cycle error: {type(exc).__name__}: {exc}",
                    "error",
                )
            results.append(entry)
        config.save_state(state)
        return results


ENGINE = TradingEngine()
