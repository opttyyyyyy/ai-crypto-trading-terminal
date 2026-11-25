const $ = (id) => document.getElementById(id);
let currentSymbol = "BTC/USDT";
let currentTf = "1h";
let candles = [];
let currentTab = "orders";
let statusCache = null;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (el.className = "toast"), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body;
  try { body = await response.json(); } catch (e) { body = null; }
  if (!response.ok) {
    throw new Error((body && (body.detail || body.message)) || `HTTP ${response.status}`);
  }
  return body;
}

function post(path, payload) {
  return api(path, { method: "POST", body: JSON.stringify(payload || {}) });
}

function setChip(id, text, state) {
  const el = $(id);
  el.textContent = text;
  el.className = "chip" + (state ? " " + state : "");
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    statusCache = s;
    const keys = s.keys_configured;
    setChip("status-mode", `MODE ${String(s.mode).toUpperCase()}${!keys && s.mode === "live" ? " (NO KEYS)" : ""}`,
      s.mode === "live" && keys ? "bad" : "warn");
    setChip("status-engine", `ENGINE ${s.engine_running ? "RUNNING" : "STOPPED"}`, s.engine_running ? "ok" : "");
    setChip("status-ai", `AI ${s.ollama_models && s.ollama_models.length ? s.model : "OFFLINE"}`,
      s.ollama_models && s.ollama_models.length ? "ok" : "bad");
    setChip("status-exchange", `EXCHANGE ${String(s.exchange).toUpperCase()}`, "ok");

    const p = s.paper || {};
    $("ac-equity").textContent = fmt(p.equity);
    $("ac-cash").textContent = fmt(p.cash);
    $("ac-realized").textContent = fmt(p.realized_pnl);
    $("ac-realized").className = (p.realized_pnl || 0) >= 0 ? "up" : "down";
    $("ac-unrealized").textContent = fmt(p.unrealized_pnl);
    $("ac-unrealized").className = (p.unrealized_pnl || 0) >= 0 ? "up" : "down";
    $("ac-daily").textContent = fmt(s.daily_pnl);
    $("ac-daily").className = (s.daily_pnl || 0) >= 0 ? "up" : "down";
    $("ac-balance").textContent = s.balance && s.balance.error
      ? "error"
      : s.balance ? `${fmt(s.balance.free)} USDT` : "not connected";
    $("auto-toggle").checked = !!s.auto_trade;
  } catch (e) {
    setChip("status-ai", "API OFFLINE", "bad");
  }
}

async function refreshMarkets() {
  try {
    const rows = await api("/api/markets");
    const list = $("markets-list");
    list.innerHTML = "";
    for (const row of rows) {
      if (row.error) continue;
      const div = document.createElement("div");
      div.className = "market-row" + (row.symbol === currentSymbol ? " active" : "");
      const up = row.change_percent >= 0;
      div.innerHTML = `<div><div class="market-sym">${row.symbol}</div>
        <div class="market-chg ${up ? "up" : "down"}">${up ? "+" : ""}${fmt(row.change_percent)}%</div></div>
        <div class="market-price">${fmt(row.price, row.price < 10 ? 4 : 2)}</div>`;
      div.onclick = () => {
        currentSymbol = row.symbol;
        $("order-symbol").value = row.symbol;
        $("chart-title").textContent = row.symbol;
        refreshMarkets();
        refreshChart();
      };
      list.appendChild(div);
    }
    const symbols = rows.filter((r) => !r.error).map((r) => r.symbol);
    const select = $("order-symbol");
    if (select.dataset.sig !== symbols.join(",")) {
      select.innerHTML = symbols.map((s) => `<option value="${s}">${s}</option>`).join("");
      select.dataset.sig = symbols.join(",");
    }
    if (symbols.includes(currentSymbol)) select.value = currentSymbol;
    const active = rows.find((r) => r.symbol === currentSymbol);
    if (active) {
      $("chart-price").textContent = fmt(active.price, active.price < 10 ? 4 : 2);
      $("chart-price").className = "chart-price " + (active.change_percent >= 0 ? "up" : "down");
      $("chart-change").textContent = `${active.change_percent >= 0 ? "+" : ""}${fmt(active.change_percent)}% 24h`;
      $("order-price").textContent = `Last ${fmt(active.price)}`;
    }
  } catch (e) { /* keep last data */ }
}

async function refreshChart() {
  try {
    candles = await api(`/api/klines?symbol=${encodeURIComponent(currentSymbol)}&interval=${currentTf}&limit=100`);
    drawChart();
  } catch (e) { /* keep last chart */ }
}

function drawChart() {
  const canvas = $("chart");
  if (!canvas || !candles.length) return;
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const pad = { l: 8, r: 62, t: 12, b: 22 };
  const plotW = width - pad.l - pad.r;
  const plotH = height - pad.t - pad.b;
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);
  let max = Math.max(...highs);
  let min = Math.min(...lows);
  const range = max - min || 1;
  max += range * 0.08;
  min -= range * 0.08;
  const y = (price) => pad.t + (max - price) / (max - min) * plotH;
  const step = plotW / candles.length;
  const bodyW = Math.max(1, Math.min(9, step * 0.65));

  ctx.strokeStyle = "#182130";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const lineY = pad.t + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, lineY);
    ctx.lineTo(pad.l + plotW, lineY);
    ctx.stroke();
    const label = (max - (max - min) * (i / 4)).toFixed(2);
    ctx.fillStyle = "#5f7186";
    ctx.font = "10px Consolas, monospace";
    ctx.fillText(label, pad.l + plotW + 6, lineY + 3);
  }

  candles.forEach((c, i) => {
    const x = pad.l + step * i + step / 2;
    const up = c.close >= c.open;
    ctx.strokeStyle = up ? "#16c784" : "#ea3943";
    ctx.fillStyle = up ? "rgba(22,199,132,.55)" : "rgba(234,57,67,.55)";
    ctx.beginPath();
    ctx.moveTo(x, y(c.high));
    ctx.lineTo(x, y(c.low));
    ctx.stroke();
    const top = y(Math.max(c.open, c.close));
    const bottom = y(Math.min(c.open, c.close));
    ctx.fillRect(x - bodyW / 2, top, bodyW, Math.max(1, bottom - top));
  });

  const closes = candles.map((c) => c.close);
  const sma = (period) => {
    if (closes.length < period) return null;
    const values = [];
    for (let i = period - 1; i < closes.length; i++) {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += closes[j];
      values.push({ x: pad.l + step * i + step / 2, y: y(sum / period) });
    }
    return values;
  };
  [[20, "#4c8dff"], [50, "#f0b90b"]].forEach(([period, color]) => {
    const values = sma(period);
    if (!values) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    values.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
  });

  ctx.fillStyle = "#5f7186";
  ctx.font = "10px Consolas, monospace";
  ctx.fillText(new Date(candles[0].time).toLocaleTimeString(), pad.l, height - 5);
  ctx.fillText(new Date(candles[candles.length - 1].time).toLocaleTimeString(), pad.l + plotW - 70, height - 5);
}

function tableFrom(columns, rows, renderRow) {
  if (!rows || !rows.length) return `<div class="empty">No records yet</div>`;
  const head = columns.map((c) => `<th>${c}</th>`).join("");
  const body = rows.map(renderRow).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function refreshState() {
  try {
    const s = await api("/api/state");
    const body = $("tab-body");
    if (currentTab === "orders") {
      const positions = Object.entries((s.paper && s.paper.positions) || {}).map(([symbol, p]) => ({
        symbol, amount: p.amount, avg_price: p.avg_price,
      }));
      body.innerHTML = tableFrom(["Symbol", "Amount", "Avg price", "Value"], positions,
        (p) => `<tr><td>${p.symbol}</td><td>${fmt(p.amount, 6)}</td><td>${fmt(p.avg_price)}</td><td>${fmt(p.amount * p.avg_price)}</td></tr>`);
    } else if (currentTab === "trades") {
      const trades = (s.trades || []).slice().reverse();
      body.innerHTML = tableFrom(["Time", "Mode", "Side", "Symbol", "Amount", "Price", "ID"], trades,
        (t) => `<tr><td>${t.time}</td><td>${t.mode}</td><td class="${t.side === "buy" ? "up" : "down"}">${t.side.toUpperCase()}</td>
          <td>${t.symbol}</td><td>${fmt(t.amount_usdt)} USDT</td><td>${fmt(t.price)}</td><td>${t.id || "—"}</td></tr>`);
    } else if (currentTab === "decisions") {
      const rows = (s.decisions || []).slice(0, 60);
      body.innerHTML = tableFrom(["Time", "Symbol", "Action", "Conf.", "RSI", "Reason"], rows,
        (d) => `<tr><td>${d.time}</td><td>${d.symbol}</td><td class="${d.action === "buy" ? "up" : d.action === "sell" ? "down" : ""}">${String(d.action).toUpperCase()}</td>
          <td>${d.confidence === undefined ? "—" : d.confidence.toFixed(2)}</td><td>${d.rsi === null ? "—" : fmt(d.rsi)}</td><td>${d.reason || ""}</td></tr>`);
    } else {
      const rows = (s.logs || []).slice(-80).reverse();
      body.innerHTML = tableFrom(["Time", "Level", "Message"], rows,
        (l) => `<tr><td>${l.time}</td><td>${l.level}</td><td>${l.message}</td></tr>`);
    }
    const latest = (s.decisions || [])[0];
    if (latest) {
      const action = String(latest.action).toUpperCase();
      $("ai-action").textContent = action;
      $("ai-action").className = "ai-action " + latest.action;
      $("ai-symbol").textContent = latest.symbol;
      $("ai-time").textContent = latest.time;
      $("ai-confidence").textContent = `Confidence ${(latest.confidence || 0).toFixed(2)} — ${latest.model || ""}`;
      $("ai-confidence-bar").style.width = `${(latest.confidence || 0) * 100}%`;
      $("ai-reason").textContent = latest.reason || "";
    }
  } catch (e) { /* keep last data */ }
}

async function refreshSettings() {
  try {
    const s = await api("/api/settings");
    $("set-exchange").value = s.exchange;
    $("set-mode").value = s.mode;
    $("set-api-key").value = s.api_key || "";
    $("set-api-secret").value = s.api_secret || "";
    $("set-symbols").value = (s.symbols || []).join(", ");
    $("set-interval").value = s.interval_seconds;
    $("set-max-order").value = s.max_order_usdt;
    $("set-max-loss").value = s.max_daily_loss_usdt;
    $("set-min-confidence").value = s.min_confidence;
    const select = $("set-model");
    const models = statusCache && statusCache.ollama_models ? statusCache.ollama_models : [];
    if (select.dataset.sig !== models.join(",")) {
      select.innerHTML = models.map((m) => `<option value="${m}">${m}</option>`).join("");
      if (!models.includes(s.model)) select.innerHTML += `<option value="${s.model}">${s.model}</option>`;
      select.dataset.sig = models.join(",");
    }
    select.value = s.model;
  } catch (e) { /* ignore */ }
}

async function refreshAll() {
  await refreshStatus();
  await refreshMarkets();
  await refreshState();
}

document.querySelectorAll("#tf-buttons button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("#tf-buttons button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentTf = btn.dataset.tf;
    refreshChart();
  };
});

document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentTab = btn.dataset.tab;
    refreshState();
  };
});

document.querySelectorAll(".quick button").forEach((btn) => {
  btn.onclick = () => ($("order-amount").value = btn.dataset.amt);
});

$("btn-buy").onclick = async () => {
  try {
    const r = await post("/api/trade", {
      symbol: $("order-symbol").value,
      side: "buy",
      amount_usdt: Number($("order-amount").value),
    });
    toast(`${r.mode} BUY placed — ${r.amount_usdt} USDT`);
    refreshAll();
  } catch (e) { toast(e.message, true); }
};

$("btn-sell").onclick = async () => {
  try {
    const r = await post("/api/trade", {
      symbol: $("order-symbol").value,
      side: "sell",
      amount_usdt: Number($("order-amount").value),
    });
    toast(`${r.mode} SELL placed — ${r.amount_usdt} USDT`);
    refreshAll();
  } catch (e) { toast(e.message, true); }
};

$("btn-analyze").onclick = async () => {
  toast("Asking local AI…");
  $("btn-analyze").disabled = true;
  try {
    const d = await post("/api/analyze", { symbol: $("order-symbol").value });
    toast(`${d.symbol}: ${d.action.toUpperCase()} (${d.confidence})`);
    refreshState();
  } catch (e) { toast(e.message, true); }
  finally { $("btn-analyze").disabled = false; }
};

$("auto-toggle").onchange = async (event) => {
  try {
    await post("/api/settings", { auto_trade: event.target.checked });
    toast(`Auto trade ${event.target.checked ? "enabled" : "disabled"}`);
    refreshStatus();
  } catch (e) { toast(e.message, true); }
};

async function engineAction(action) {
  try {
    await post("/api/engine", { action });
    toast(`Engine ${action} issued`);
    refreshStatus();
    if (action === "cycle") refreshState();
  } catch (e) { toast(e.message, true); }
}
$("btn-engine-start").onclick = () => engineAction("start");
$("btn-engine-stop").onclick = () => engineAction("stop");
$("btn-engine-cycle").onclick = () => engineAction("cycle");

$("btn-emergency").onclick = async () => {
  if (!confirm("Stop the engine and disable auto trading?")) return;
  try {
    await post("/api/emergency", {});
    toast("Emergency stop complete");
    refreshStatus();
  } catch (e) { toast(e.message, true); }
};

$("btn-save-settings").onclick = async () => {
  const payload = {
    exchange: $("set-exchange").value,
    mode: $("set-mode").value,
    model: $("set-model").value,
    symbols: $("set-symbols").value.split(",").map((s) => s.trim()).filter(Boolean),
    interval_seconds: Number($("set-interval").value),
    max_order_usdt: Number($("set-max-order").value),
    max_daily_loss_usdt: Number($("set-max-loss").value),
    min_confidence: Number($("set-min-confidence").value),
  };
  if ($("set-api-key").value && $("set-api-key").value !== "********") payload.api_key = $("set-api-key").value;
  if ($("set-api-secret").value && $("set-api-secret").value !== "********") payload.api_secret = $("set-api-secret").value;
  try {
    await post("/api/settings", payload);
    toast("Settings saved");
    refreshAll();
    refreshSettings();
  } catch (e) { toast(e.message, true); }
};

$("btn-reset-paper").onclick = async () => {
  if (!confirm("Reset the paper account and clear trade history?")) return;
  try {
    await post("/api/paper/reset", {});
    toast("Paper account reset");
    refreshAll();
  } catch (e) { toast(e.message, true); }
};

window.addEventListener("resize", drawChart);
refreshSettings();
refreshAll();
refreshChart();
setInterval(refreshAll, 5000);
setInterval(refreshChart, 15000);
