import json
import os
import threading
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
STATE_PATH = DATA_DIR / "state.json"

LOCK = threading.RLock()

DEFAULTS = {
    "exchange": "binanceus",
    "api_key": "",
    "api_secret": "",
    "mode": "live",
    "model": "qwen2.5:3b",
    "ollama_url": "http://127.0.0.1:11434",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "interval_seconds": 60,
    "max_order_usdt": 50.0,
    "max_daily_loss_usdt": 100.0,
    "min_confidence": 0.6,
    "auto_trade": False,
}


def initial_state():
    return {
        "paper": {
            "cash": 10000.0,
            "positions": {},
            "realized_pnl": 0.0,
        },
        "trades": [],
        "decisions": [],
        "logs": [],
        "day": datetime.now().strftime("%Y-%m-%d"),
        "daily_pnl": 0.0,
    }


def ensure_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings():
    ensure_data()
    with LOCK:
        settings = dict(DEFAULTS)
        if SETTINGS_PATH.exists():
            try:
                saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
            except Exception:
                pass
        return settings


def save_settings(patch):
    ensure_data()
    with LOCK:
        settings = load_settings()
        for key, value in patch.items():
            if key in DEFAULTS:
                settings[key] = value
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return settings


def public_settings(settings):
    result = dict(settings)
    result["api_key_set"] = bool(result.get("api_key"))
    result["api_secret_set"] = bool(result.get("api_secret"))
    result["api_key"] = ("*" * 8 + result["api_key"][-4:]) if result.get("api_key") else ""
    result["api_secret"] = "********" if result.get("api_secret") else ""
    return result


def load_state():
    ensure_data()
    with LOCK:
        state = initial_state()
        if STATE_PATH.exists():
            try:
                saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    for key in state:
                        if key in saved:
                            state[key] = saved[key]
            except Exception:
                pass
        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("day") != today:
            state["day"] = today
            state["daily_pnl"] = 0.0
        return state


def save_state(state):
    ensure_data()
    with LOCK:
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_log(state, message, level="info"):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": str(message),
    }
    state.setdefault("logs", []).append(entry)
    state["logs"] = state["logs"][-300:]
    return entry
