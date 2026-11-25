# BOTTY — AI Crypto Trading Terminal

[![Install with Pinokio](https://badges.pinokio.co/install.svg)](https://pinokio.co/resolve?url=https://github.com/opttyyyyyy/ai-crypto-trading-terminal)

A local, browser-based crypto trading terminal that uses a **free local AI model** (Ollama) to analyze live market data and decide when to buy, sell, or hold. It ships with a one-click Pinokio launcher providing Install, Start, Update, and Reset actions.

> **Risk warning:** Trading with real funds can lose money. This software is provided as-is, with no warranty. Start in PAPER mode with small limits, and never fund an API key with more than you are willing to lose.

## What it does

- Streams live prices and candlestick data from Binance's public market-data API (no account required).
- Computes indicators (SMA 20/50, RSI 14) and sends a compact market snapshot to a local Ollama model.
- Shows the AI's action, confidence, and one-sentence reasoning in the terminal.
- Supports **manual orders** and an **auto-trade engine** that runs on a configurable interval.
- Supports **LIVE** orders (via CCXT on Binance.US / Binance / Kraken / Coinbase) and **PAPER** simulation.
- Tracks positions, realized/unrealized PnL, daily PnL, trade history, AI decisions, and an event log.
- Includes a red **EMERGENCY STOP** that kills the engine and disables auto-trading.

## Requirements

- Pinokio desktop.
- Ollama running on the machine (Windows/macOS/Linux). If you use Pinokio, the Ollama app can be started from the Pinokio library; otherwise install it from <https://ollama.com/download>.
- `install.js` pulls `qwen2.5:3b` automatically. Any other cached Ollama model can be selected in Settings.

## How to use

1. In Pinokio, open the app and click **Install**. This creates `app/env`, installs Python dependencies, and pulls the local AI model.
2. Click **Start**. Pinokio opens the terminal in your browser automatically.
3. In the right-hand **Settings** panel:
   - Choose `PAPER` or `LIVE` mode.
   - For live trading, enter your exchange **API key** and **API secret**. Create keys with trading permission only and **disable withdrawal** permission.
   - Pick the exchange, AI model, symbols, cycle interval, max order size, daily loss limit, and minimum AI confidence.
   - Click **Save Settings**.
4. Use **AI ANALYZE** to get a one-off signal without trading.
5. Use the **AUTO TRADE** switch plus **START ENGINE** to let the AI trade continuously. Use **EMERGENCY STOP** at any time.
6. **Update** refreshes Python dependencies. **Reset** deletes `app/env` and `app/data` (settings, paper account, and history).

> Market data comes from `data-api.binance.vision`, which works in regions where `api.binance.com` is blocked. Live order routing uses CCXT and the exchange selected in Settings. If Binance Global is unavailable in your region, choose **Binance.US** in Settings.

## Where data is stored

- `app/data/settings.json` — your settings, including exchange keys (gitignored).
- `app/data/state.json` — paper account, trades, decisions, logs (gitignored).

Both are created on first run and removed by **Reset**.

## API

The server binds to `127.0.0.1` on the port Pinokio assigns. The examples below assume `PORT=8000`; substitute your actual port (shown in the Pinokio "Open Trading Terminal" tab).

### Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/status` | Mode, engine state, AI state, account summary, exchange balance |
| GET | `/api/settings` | Current settings with masked secrets |
| POST | `/api/settings` | Update settings (partial JSON body) |
| GET | `/api/markets` | 24h ticker for configured symbols |
| GET | `/api/klines?symbol=BTC/USDT&interval=1h&limit=100` | Candlestick data |
| POST | `/api/analyze` | `{"symbol":"BTC/USDT"}` — one-off AI decision |
| POST | `/api/trade` | `{"symbol":"BTC/USDT","side":"buy","amount_usdt":10}` |
| POST | `/api/engine` | `{"action":"start"|"stop"|"cycle"}` |
| POST | `/api/emergency` | Stop engine and disable auto-trade |
| POST | `/api/paper/reset` | Reset paper account and history |
| GET | `/api/state` | Positions, trades, decisions, logs |

### JavaScript

```javascript
const BASE = "http://127.0.0.1:8000";

async function post(path, body) {
  const response = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

const status = await (await fetch(BASE + "/api/status")).json();
console.log(status.mode, status.engine_running);

const signal = await post("/api/analyze", { symbol: "BTC/USDT" });
console.log(signal.action, signal.confidence, signal.reason);

const trade = await post("/api/trade", {
  symbol: "BTC/USDT", side: "buy", amount_usdt: 10,
});
console.log(trade);
```

### Python

```python
import requests

BASE = "http://127.0.0.1:8000"

status = requests.get(f"{BASE}/api/status", timeout=10).json()
print(status["mode"], status["engine_running"])

signal = requests.post(
    f"{BASE}/api/analyze", json={"symbol": "BTC/USDT"}, timeout=180
).json()
print(signal["action"], signal["confidence"], signal["reason"])

trade = requests.post(
    f"{BASE}/api/trade",
    json={"symbol": "BTC/USDT", "side": "buy", "amount_usdt": 10},
    timeout=30,
).json()
print(trade)
```

### Curl

```bash
curl -s http://127.0.0.1:8000/api/status

curl -s -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC/USDT"}'

curl -s -X POST http://127.0.0.1:8000/api/trade \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC/USDT","side":"buy","amount_usdt":10}'
```

## Notes

- The Python backend, frontend, and launcher are entirely local; no hosted service is required.
- Indicator values and AI output are informational, not financial advice.
- Live order execution depends on the exchange API being reachable from your network and on your API key permissions.
