import os
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
import engine

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

app = FastAPI(title="AI Crypto Trading Terminal", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))


@app.get("/api/status")
def status():
    settings = config.load_settings()
    state = config.load_state()
    paper = state.get("paper", {})
    positions = paper.get("positions", {})
    unrealized = 0.0
    for symbol, position in positions.items():
        try:
            price = engine.fetch_ticker(symbol)["price"]
            unrealized += (price - position.get("avg_price", 0.0)) * position.get("amount", 0.0)
        except Exception:
            pass
    return {
        "mode": settings.get("mode"),
        "auto_trade": settings.get("auto_trade"),
        "engine_running": engine.ENGINE.is_running(),
        "exchange": settings.get("exchange"),
        "keys_configured": bool(settings.get("api_key") and settings.get("api_secret")),
        "model": settings.get("model"),
        "ollama_models": engine.list_models(settings),
        "paper": {
            "cash": paper.get("cash", 0.0),
            "positions": positions,
            "realized_pnl": paper.get("realized_pnl", 0.0),
            "unrealized_pnl": unrealized,
            "equity": paper.get("cash", 0.0)
            + sum(p.get("amount", 0.0) * p.get("avg_price", 0.0) for p in positions.values())
            + unrealized,
        },
        "daily_pnl": state.get("daily_pnl", 0.0),
        "counts": {
            "trades": len(state.get("trades", [])),
            "decisions": len(state.get("decisions", [])),
        },
        "balance": engine.fetch_live_balance(settings),
    }


@app.get("/api/settings")
def get_settings():
    return config.public_settings(config.load_settings())


@app.post("/api/settings")
def set_settings(patch: dict = Body(...)):
    patch = dict(patch)
    for secret_key in ("api_key", "api_secret"):
        if secret_key in patch and patch[secret_key] in ("", "********"):
            patch.pop(secret_key)
    settings = config.save_settings(patch)
    state = config.load_state()
    config.append_log(state, "Settings updated", "info")
    config.save_state(state)
    return config.public_settings(settings)


@app.get("/api/markets")
def markets():
    settings = config.load_settings()
    rows = []
    for symbol in settings.get("symbols", []):
        try:
            rows.append(engine.fetch_ticker(symbol))
        except Exception as exc:
            rows.append({"symbol": symbol, "error": str(exc)})
    return rows


@app.get("/api/klines")
def klines(symbol: str, interval: str = "1h", limit: int = 120):
    try:
        return engine.fetch_klines(symbol, interval, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/analyze")
def analyze(payload: dict = Body(...)):
    symbol = payload.get("symbol") or config.load_settings().get("symbols", ["BTC/USDT"])[0]
    try:
        candles = engine.fetch_klines(symbol)
        ticker = engine.fetch_ticker(symbol)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data unavailable: {exc}")
    snapshot = engine.build_snapshot(symbol, candles, ticker)
    settings = config.load_settings()
    decision = engine.ask_ai(snapshot, settings)
    entry = {
        "time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "price": snapshot["price"],
        "rsi": snapshot["rsi_14"],
        "sma20": snapshot["sma_20"],
        "sma50": snapshot["sma_50"],
        **decision,
    }
    state = config.load_state()
    state.setdefault("decisions", []).insert(0, entry)
    state["decisions"] = state["decisions"][-300:]
    config.append_log(
        state,
        f"{symbol} manual analysis: {decision['action'].upper()} ({decision['confidence']:.2f})",
        "ai",
    )
    config.save_state(state)
    return entry


@app.post("/api/trade")
def trade(payload: dict = Body(...)):
    symbol = payload.get("symbol")
    side = payload.get("side")
    amount = payload.get("amount_usdt")
    if not symbol or not side or not amount:
        raise HTTPException(status_code=400, detail="symbol, side and amount_usdt are required")
    state = config.load_state()
    try:
        result = engine.execute_trade(symbol, side, amount, config.load_settings(), state)
    except Exception as exc:
        config.append_log(state, f"Trade failed: {type(exc).__name__}: {exc}", "error")
        config.save_state(state)
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")
    config.save_state(state)
    return result


@app.post("/api/engine")
def engine_control(payload: dict = Body(...)):
    action = payload.get("action")
    if action == "start":
        engine.ENGINE.start()
    elif action == "stop":
        engine.ENGINE.stop()
    elif action == "cycle":
        engine.ENGINE.run_cycle()
    else:
        raise HTTPException(status_code=400, detail="action must be start, stop or cycle")
    return {"engine_running": engine.ENGINE.is_running()}


@app.post("/api/emergency")
def emergency_stop():
    engine.ENGINE.stop()
    settings = config.save_settings({"auto_trade": False})
    state = config.load_state()
    config.append_log(state, "EMERGENCY STOP: engine stopped and auto-trade disabled", "error")
    config.save_state(state)
    return {"status": "stopped", "auto_trade": settings.get("auto_trade")}


@app.post("/api/paper/reset")
def reset_paper():
    state = config.load_state()
    state["paper"] = config.initial_state()["paper"]
    state["daily_pnl"] = 0.0
    state["trades"] = []
    config.append_log(state, "Paper account reset", "info")
    config.save_state(state)
    return {"status": "ok"}


@app.get("/api/state")
def get_state():
    return config.load_state()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"AI Crypto Terminal: http://127.0.0.1:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
