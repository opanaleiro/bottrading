"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const usd = (value, digits = 2) => new Intl.NumberFormat("es-ES", {style:"currency",currency:"USD",minimumFractionDigits:digits,maximumFractionDigits:digits}).format(number(value));
const price = (value) => usd(value, number(value) >= 100 ? 2 : number(value) >= 1 ? 3 : 6);
const pct = (value, signed = false) => `${signed && number(value) > 0 ? "+" : ""}${number(value).toLocaleString("es-ES", {minimumFractionDigits:2,maximumFractionDigits:2})} %`;
const signedUsd = (value) => `${number(value) > 0 ? "+" : ""}${usd(value)}`;
const tone = (value) => number(value) > 0 ? "positive" : number(value) < 0 ? "negative" : "muted";
const utcTime = (value, date = false) => {
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {timeZone:"UTC",...(date ? {day:"2-digit",month:"short"} : {}),hour:"2-digit",minute:"2-digit",hour12:false}).format(time);
};
const coinNames = {BTC:"Bitcoin",ETH:"Ethereum",SOL:"Solana",XRP:"XRP",ADA:"Cardano",AVAX:"Avalanche",DOT:"Polkadot",LINK:"Chainlink",DOGE:"Dogecoin",LTC:"Litecoin",BCH:"Bitcoin Cash",UNI:"Uniswap",ATOM:"Cosmos",XLM:"Stellar",AAVE:"Aave",NEAR:"NEAR",POL:"Polygon",MATIC:"Polygon",TRX:"TRON",BNB:"BNB"};
const coinBase = (symbol) => String(symbol || "").split(/[/-]/)[0].replace(/USDT$|USD$/, "");
const coinName = (symbol) => coinNames[coinBase(symbol)] || coinBase(symbol);
const coinIcon = (symbol, small = false) => {
  const base = coinBase(symbol);
  const colors = ["amber","violet","blue","emerald","rose"];
  const color = colors[[...base].reduce((sum, char) => sum + char.charCodeAt(0), 0) % colors.length];
  return `<span class="coin-icon ${color}${small ? " coin-small" : ""}">${escapeHtml(base === "BTC" ? "₿" : base === "ETH" ? "Ξ" : base.slice(0,1))}</span>`;
};
const signalLabel = (signal) => ({buy:"Comprar",sell:"Vender",wait:"Esperar"}[signal] || "Esperar");
const signalChip = (signal) => `<span class="signal signal-${["buy","sell"].includes(signal) ? signal : "wait"}"><i></i>${signalLabel(signal)}</span>`;

let state = null;
let selectedSymbol = null;
let pending = false;
let drawerOpen = false;
let closingId = null;
let noticeTimer;
let lastConnected = false;
let activeView = "overview";
const viewCopy = {
  overview:{title:"Vista general",eyebrow:"TU ESTRATEGIA, EN PERSPECTIVA",description:"Observa el mercado. Prueba ideas. Aprende de cada operación."},
  market:{title:"Mercado",eyebrow:"DE LOS DATOS A LA DECISIÓN",description:"Cada activo, cada indicador y el razonamiento detrás de cada señal."},
  lab:{title:"Laboratorio",eyebrow:"IDEAS QUE SE PONEN A PRUEBA",description:"Explora hipótesis y sigue la evidencia que deja tu estrategia."},
  activity:{title:"Actividad",eyebrow:"CADA DECISIÓN DEJA UN RASTRO",description:"Consulta las operaciones cerradas y lo que está haciendo el motor."}
};

function changeView() {
  const wanted = location.hash.slice(1);
  activeView = Object.hasOwn(viewCopy, wanted) ? wanted : "overview";
  $$(".view").forEach((element) => { element.hidden = element.id !== `view-${activeView}`; });
  $$("[data-view]").forEach((element) => {
    element.classList.toggle("active", element.dataset.view === activeView);
    if (element.dataset.view === activeView) element.setAttribute("aria-current", "page"); else element.removeAttribute("aria-current");
  });
  const copy = viewCopy[activeView];
  $("#page-title").innerHTML = `${escapeHtml(copy.title)}<span class="heading-dot">.</span>`;
  $("#page-eyebrow").textContent = copy.eyebrow;
  $("#page-description").textContent = copy.description;
  $("#breadcrumb-current").textContent = copy.title;
  document.title = `${copy.title} · Vector Trading Lab`;
}

function showNotice(message, error = false, persistent = false) {
  clearTimeout(noticeTimer);
  const notice = $("#notice");
  notice.textContent = message;
  notice.className = `notice${error ? " notice-error" : ""}`;
  notice.hidden = false;
  if (drawerOpen && error) {
    $("#drawer-notice").textContent = message;
    $("#drawer-notice").hidden = false;
  }
  if (error && $("#reset-dialog").open) {
    $("#reset-notice").textContent = message;
    $("#reset-notice").hidden = false;
  }
  if (error && $("#close-dialog").open) {
    $("#close-notice").textContent = message;
    $("#close-notice").hidden = false;
  }
  if (!persistent) noticeTimer = setTimeout(() => { notice.hidden = true; }, 8500);
}

function setConnected(connected) {
  lastConnected = connected;
  const element = $("#connection-status");
  element.classList.toggle("offline", !connected);
  element.innerHTML = `<i></i>${connected ? "Conectado" : "Sin conexión"}`;
}

async function request(path, method = "GET", body) {
  const response = await fetch(path, {method,cache:"no-store",headers:body !== undefined ? {"Content-Type":"application/json"} : undefined,body:body !== undefined ? JSON.stringify(body) : undefined});
  let payload;
  try { payload = await response.json(); } catch { throw new Error(`El servidor devolvió una respuesta no válida (HTTP ${response.status}).`); }
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `La operación no pudo completarse (HTTP ${response.status}).`);
  return payload;
}

async function perform(path, body, success) {
  if (pending) return false;
  pending = true;
  setBusy();
  try {
    const snapshot = await request(path, "POST", body);
    state = snapshot;
    setConnected(true);
    render();
    if (success) showNotice(success);
    return true;
  } catch (error) {
    showNotice(error.message || "No se pudo completar la operación.", true);
    return false;
  } finally {
    pending = false;
    setBusy();
  }
}

function setBusy() {
  $$('button:not([data-action="close-settings"]):not([data-action="cancel-reset"]):not([data-action="cancel-close"])').forEach((button) => {
    button.disabled = pending || !state;
  });
  $("#toggle-button").classList.toggle("loading", pending);
  $("#cycle-button").disabled = pending || !state || !!state.meta?.running;
  $("#cycle-button").title = state?.meta?.running ? "Pausa el motor para realizar un análisis manual." : "Realizar un ciclo de análisis y operaciones simuladas.";
  $("#aggressiveness").disabled = pending || !state;
  if (state && drawerOpen) $("#market-source").disabled = pending || state.meta?.running || (state.positions || []).length > 0 || (state.trades || []).length > 0;
}

function render() {
  if (!state) return;
  const {meta = {},settings = {},portfolio = {}} = state;
  const positions = state.positions || [];
  const assets = state.assets || [];
  const running = !!meta.running;
  $("#engine-status").textContent = meta.error ? "El motor necesita atención" : meta.risk_halted ? "Bloqueo de riesgo · sin nuevas entradas" : running ? "Motor activo" : "Motor en pausa";
  $("#engine-update").textContent = meta.error || (meta.updated_at ? `Última actualización · ${utcTime(meta.updated_at)} UTC` : "Listo para el primer análisis");
  $("#engine-orb").className = `engine-orb${running && !meta.error && !meta.risk_halted ? " running" : ""}${meta.error ? " error" : meta.risk_halted ? " risk" : ""}`;
  $("#source-label").textContent = meta.market_source === "kraken" ? "KRAKEN · COTIZACIONES REALES" : "DEMO · DATOS SINTÉTICOS";
  $("#source-label").classList.toggle("demo", meta.market_source !== "kraken");
  $("#ai-label").textContent = meta.ai_provider === "claude" ? "IA · CLAUDE" : "MOTOR · REGLAS TÉCNICAS";
  $("#toggle-button").innerHTML = running ? '<span class="pause-icon">Ⅱ</span>Pausar bot' : '<svg class="play-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7z"/></svg>Iniciar bot';
  $("#toggle-button").classList.toggle("is-running", running);
  $("#asset-count").textContent = assets.length;
  $("#market-asset-count").textContent = `${assets.length} activos`;
  $("#position-count").textContent = positions.length;
  $("#mode-help").textContent = settings.operation_mode === "close_only" ? "Gestiona las salidas; no abre nuevas posiciones." : "Analiza oportunidades y gestiona posiciones.";
  $$("[data-mode]").forEach((element) => {
    const selected = element.dataset.mode === settings.operation_mode;
    element.classList.toggle("selected", selected);
    element.setAttribute("aria-pressed", String(selected));
  });
  if (document.activeElement !== $("#aggressiveness")) $("#aggressiveness").value = settings.aggressiveness ?? 4;
  updateAggressionLabel();
  $("#strategy-facts").innerHTML = `<div><span>Intervalo de análisis</span><strong>${escapeHtml(settings.cycle_seconds)} s</strong></div><div><span>Límite de pérdida diaria</span><strong>${pct(settings.daily_loss_limit_pct)}</strong></div><div><span>Posiciones máximas</span><strong>${escapeHtml(settings.max_positions)}</strong></div>`;
  const exposure = positions.reduce((total, position) => total + Math.abs(number(position.notional)), 0);
  const todayClass = tone(portfolio.today_pnl);
  $("#metrics").innerHTML = `<article class="metric-card"><span class="metric-label">Patrimonio virtual <span class="metric-icon">◈</span></span><strong class="metric-value">${usd(portfolio.equity)}</strong><span class="metric-caption">${usd(portfolio.cash)} de efectivo virtual</span></article><article class="metric-card"><span class="metric-label">Resultado de hoy <span class="metric-icon"><svg class="arrow-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M7 7h10v10"/></svg></span></span><strong class="metric-value ${todayClass}">${signedUsd(portfolio.today_pnl)}</strong><span class="metric-caption"><span class="${todayClass}">${pct(portfolio.today_return_pct, true)}</span> <span class="metric-separator">·</span> Día UTC</span></article><article class="metric-card"><span class="metric-label">Posiciones abiertas <span class="metric-icon">⇄</span></span><strong class="metric-value">${positions.length}<span class="metric-denominator"> / ${escapeHtml(settings.max_positions)}</span></strong><span class="metric-caption">${usd(exposure)} de exposición virtual</span></article><article class="metric-card"><span class="metric-label">Drawdown actual <span class="metric-icon">⌁</span></span><strong class="metric-value${number(portfolio.drawdown_pct) > 0 ? " negative" : ""}">${pct(portfolio.drawdown_pct)}</strong><span class="metric-caption">Desde el máximo del patrimonio</span></article>`;
  const totalReturn = number(settings.initial_balance) ? (number(portfolio.equity) / number(settings.initial_balance) - 1) * 100 : 0;
  $("#chart-summary").innerHTML = `<strong>${usd(portfolio.equity)}</strong><span class="return-pill ${tone(totalReturn)}">${pct(totalReturn, true)}</span><span class="chart-unit">Patrimonio virtual · USD</span>`;
  renderChart(state.equity_history || []);
  renderPositions(positions);
  renderAssets(assets);
  renderExperiments(state.experiments || []);
  renderNews(state.news || []);
  renderTrades(state.trades || []);
  renderEvents(state.events || []);
  $("#quotes-note").textContent = meta.market_source === "kraken" ? "Cotizaciones de Kraken. Variación aproximada de 24 horas. Todas las operaciones siguen siendo simuladas." : "DEMO: precios y variaciones sintéticos para probar el sistema. No representan el mercado real.";
  if (drawerOpen) {
    $("#market-source").disabled = running || positions.length > 0 || (state.trades || []).length > 0 || pending;
    $("#source-help").textContent = positions.length || (state.trades || []).length ? "Reinicia la simulación para cambiar de fuente sin mezclar posiciones o resultados de mercados diferentes." : running ? "Pausa el motor antes de cambiar de fuente." : "Puedes usar precios sintéticos o cotizaciones públicas de Kraken.";
  }
  setBusy();
}

function renderChart(history) {
  const points = history.filter((point) => Number.isFinite(Number(point.equity)) && !Number.isNaN(new Date(point.time).getTime()));
  if (points.length < 2) {
    $("#equity-chart").innerHTML = '<div class="chart-empty"><span class="chart-empty-icon">⌁</span><strong>Tu curva está por comenzar</strong><span>El historial necesita al menos dos observaciones.<br>Inicia el motor o pulsa «Analizar ahora».</span></div>';
    $("#chart-period").textContent = points.length ? `${utcTime(points[0].time, true)} UTC · 1 observación` : "Sin historial";
    return;
  }
  const width = 900, height = 220, top = 18, bottom = 28, right = 86, left = 6;
  const values = points.map((point) => number(point.equity));
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high - low) * .17, Math.abs(high) * .0003, .1);
  const min = low - padding, max = high + padding;
  const firstTime = new Date(points[0].time).getTime(), lastTime = new Date(points.at(-1).time).getTime();
  const pointX = (point, index) => left + (lastTime === firstTime ? index / (points.length - 1) : (new Date(point.time).getTime() - firstTime) / (lastTime - firstTime)) * (width - left - right);
  const pointY = (value) => top + (max - value) / (max - min) * (height - top - bottom);
  const path = points.map((point, index) => `${index ? "L" : "M"}${pointX(point,index).toFixed(2)},${pointY(number(point.equity)).toFixed(2)}`).join(" ");
  const lastX = pointX(points.at(-1),points.length - 1), lastY = pointY(values.at(-1));
  let grid = "";
  for (let i = 0; i < 4; i++) {
    const y = top + i * (height - top - bottom) / 3;
    const value = max - i * (max - min) / 3;
    grid += `<line x1="${left}" y1="${y}" x2="${width-right}" y2="${y}" class="chart-grid-line"/><text x="${width-right+14}" y="${y+4}" class="chart-axis-label">${escapeHtml(usd(value,0))}</text>`;
  }
  $("#equity-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Historial del patrimonio virtual. ${escapeHtml(usd(values[0]))} al inicio y ${escapeHtml(usd(values.at(-1)))} en la última observación."><defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#69ddba" stop-opacity=".19"/><stop offset="100%" stop-color="#69ddba" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${path} L${lastX},${height-bottom} L${left},${height-bottom} Z" fill="url(#equity-fill)"/><path d="${path}" fill="none" stroke="#69ddba" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${lastX}" cy="${lastY}" r="6" fill="#69ddba" opacity=".2"/><circle cx="${lastX}" cy="${lastY}" r="3" fill="#69ddba"/><text x="${left}" y="${height-4}" class="chart-axis-label">${escapeHtml(utcTime(points[0].time))}</text><text x="${lastX}" y="${height-4}" text-anchor="end" class="chart-axis-label">${escapeHtml(utcTime(points.at(-1).time))}</text></svg>`;
  $("#chart-period").textContent = `${utcTime(points[0].time,true)} – ${utcTime(points.at(-1).time,true)} UTC`;
}

function renderPositions(positions) {
  if (!positions.length) {
    $("#positions-content").innerHTML = '<div class="empty-state compact"><span class="empty-symbol">⇄</span><h3>No hay posiciones abiertas</h3><p>El motor abrirá posiciones virtuales cuando una señal supere los filtros de riesgo.</p></div>';
    return;
  }
  $("#positions-content").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Activo / dirección</th><th>Entrada</th><th>Precio actual</th><th>Exposición</th><th>Stop / objetivo</th><th>P&amp;L virtual</th><th><span class="sr-only">Acciones</span></th></tr></thead><tbody>${positions.map((position) => `<tr><td><div class="asset-cell">${coinIcon(position.symbol,true)}<div><strong>${escapeHtml(coinBase(position.symbol))}</strong><small>${position.side === "short" ? "Corto" : "Largo"} · ${number(position.quantity).toLocaleString("es-ES",{maximumFractionDigits:6})}</small></div></div></td><td>${price(position.entry_price)}</td><td>${price(position.current_price)}</td><td>${usd(position.notional)}</td><td><div class="dual-number"><span class="muted">${price(position.stop_loss)}</span><span>${price(position.take_profit)}</span></div></td><td class="${tone(position.unrealized_pnl)}">${signedUsd(position.unrealized_pnl)}</td><td><button class="table-button" data-close="${escapeHtml(position.id)}" aria-label="Cerrar posición de ${escapeHtml(position.symbol)}">Cerrar <svg class="arrow-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M7 7h10v10"/></svg></button></td></tr>`).join("")}</tbody></table></div>`;
}

function renderAssets(assets) {
  $("#asset-mini-grid").innerHTML = assets.length ? assets.map((asset) => `<button class="asset-mini" data-asset="${escapeHtml(asset.symbol)}"><div class="asset-mini-heading">${coinIcon(asset.symbol,true)}<strong>${escapeHtml(coinBase(asset.symbol))}</strong><span class="${tone(asset.change_pct)}">${pct(asset.change_pct,true)}</span></div><div class="asset-mini-price">${price(asset.price)}</div><div class="asset-mini-foot"><span>${escapeHtml(coinName(asset.symbol))}</span>${signalChip(asset.signal)}</div></button>`).join("") : '<div class="empty-state compact"><h3>Sin cotizaciones todavía</h3><p>Analiza el mercado para obtener el primer conjunto de precios.</p></div>';
  $("#asset-list").innerHTML = assets.length ? `<div class="asset-list-labels"><span>Activo / precio</span><span>Cambio · 24 h aprox.</span></div>${assets.map((asset) => `<button class="asset-row${asset.symbol === selectedSymbol ? " selected" : ""}" data-asset="${escapeHtml(asset.symbol)}"><div class="asset-cell">${coinIcon(asset.symbol)}<div><strong>${escapeHtml(coinBase(asset.symbol))}<span class="asset-pair"> / USD</span></strong><small>${escapeHtml(coinName(asset.symbol))}</small></div></div><div class="asset-row-data"><strong>${price(asset.price)}</strong><small class="${tone(asset.change_pct)}">${pct(asset.change_pct,true)}</small></div>${signalChip(asset.signal)}<span class="asset-chevron">›</span></button>`).join("")}` : '<div class="empty-state compact"><h3>Sin datos de mercado</h3><p>Las cotizaciones aparecerán después de un análisis.</p></div>';
  if (assets.length && !assets.some((asset) => asset.symbol === selectedSymbol)) selectedSymbol = assets[0].symbol;
  const selected = assets.find((asset) => asset.symbol === selectedSymbol);
  if (selected) renderAssetDetail(selected);
}

function renderAssetDetail(asset) {
  const indicators = asset.indicators || {};
  const confidence = Math.max(0,Math.min(1,number(asset.confidence))) * 100;
  const steps = asset.pipeline || [];
  const statusTone = (status) => ["blocked","error","rejected","failed"].includes(status) ? "blocked" : ["waiting","pending","skipped","idle","wait","unavailable"].includes(status) ? "waiting" : "complete";
  $("#asset-detail").innerHTML = `<div class="detail-heading">${coinIcon(asset.symbol)}<div><h2>${escapeHtml(coinName(asset.symbol))}</h2><span>${escapeHtml(asset.symbol)} · ${state.meta?.market_source === "kraken" ? "Kraken" : "DEMO sintético"}</span></div>${signalChip(asset.signal)}</div><div class="detail-price"><strong>${price(asset.price)}</strong><span class="${tone(asset.change_pct)}">${pct(asset.change_pct,true)} <small>24 h aprox.</small></span></div><div class="indicator-grid"><div><span>RSI (14)</span><strong>${number(indicators.rsi).toFixed(1)}</strong></div><div><span>Volatilidad</span><strong>${pct(indicators.volatility_pct)}</strong></div><div><span>EMA rápida</span><strong>${price(indicators.ema_fast)}</strong></div><div><span>EMA lenta</span><strong>${price(indicators.ema_slow)}</strong></div><div><span>Momentum</span><strong class="${tone(indicators.momentum_pct)}">${pct(indicators.momentum_pct,true)}</strong></div><div><span>Confianza de señal</span><strong>${confidence.toFixed(0)} %</strong></div></div><div class="decision-card"><div class="eyebrow">RAZONAMIENTO DEL MOTOR</div><p>${escapeHtml(asset.reason || "No hay un razonamiento disponible para este activo.")}</p><div class="confidence-track"><span style="width:${confidence.toFixed(1)}%"></span></div><small>La confianza es una puntuación del motor, no una probabilidad de beneficio.</small></div><div class="pipeline-header"><h3>Recorrido de la decisión</h3><span>${steps.length} etapas</span></div><ol class="pipeline">${steps.length ? steps.map((step,index) => `<li class="${statusTone(step.status)}"><span class="pipeline-step">${statusTone(step.status) === "complete" ? "✓" : index + 1}</span><div><div class="pipeline-title"><strong>${escapeHtml(step.name)}</strong><span>${escapeHtml(translateStatus(step.status))}</span></div><p>${escapeHtml(step.detail || "Sin detalle")}</p></div></li>`).join("") : '<li class="waiting"><span class="pipeline-step">…</span><div><strong>Pendiente de análisis</strong><p>El motor mostrará las etapas después del próximo ciclo.</p></div></li>'}</ol>`;
  $$(".asset-row").forEach((element) => element.classList.toggle("selected", element.dataset.asset === asset.symbol));
}

function translateStatus(status) {
  return ({ok:"Completado",complete:"Completado",completed:"Completado",passed:"Superado",success:"Completado",ready:"Listo",blocked:"Bloqueado",rejected:"Descartado",failed:"Fallido",error:"Error",waiting:"En espera",pending:"Pendiente",skipped:"Omitido",idle:"En pausa",wait:"En espera",warning:"Atención",unavailable:"No disponible",paper:"Simulación"})[status] || status || "Pendiente";
}

function renderExperiments(experiments) {
  const statuses = {testing:{label:"En prueba",className:"testing"},insufficient:{label:"Muestra insuficiente",className:"insufficient"},promising:{label:"Indicios favorables",className:"promising"},rejected:{label:"Descartada",className:"rejected"}};
  $("#experiments-content").innerHTML = experiments.length ? `<div class="experiments-list">${experiments.map((experiment,index) => {
    const status = statuses[experiment.status] || statuses.testing;
    const hasSamples = number(experiment.samples) > 0;
    return `<article class="experiment"><div class="experiment-top"><span class="experiment-number">H${String(index+1).padStart(2,"0")}</span><span class="experiment-status ${status.className}">${status.label}</span></div><h3>${escapeHtml(experiment.title)}</h3><p>${escapeHtml(experiment.note || "Recopilando observaciones de la simulación.")}</p><div class="experiment-metrics"><div><span>Muestra</span><strong>${number(experiment.samples)} <small>oper.</small></strong></div><div><span>Tasa de acierto</span><strong>${hasSamples ? pct(experiment.win_rate) : "—"}</strong></div><div><span>P&amp;L medio</span><strong class="${hasSamples ? tone(experiment.avg_pnl) : "muted"}">${hasSamples ? signedUsd(experiment.avg_pnl) : "—"}</strong></div></div></article>`;
  }).join("")}</div><div class="panel-footnote">Los resultados describen esta simulación. Una muestra favorable no demuestra rentabilidad futura ni aprendizaje autónomo.</div>` : '<div class="empty-state"><span class="empty-symbol">✳</span><h3>Las hipótesis necesitan observaciones</h3><p>Los experimentos aparecerán cuando el motor tenga datos de la estrategia.</p></div>';
}

function renderNews(news) {
  $("#news-content").innerHTML = news.length ? `<div class="eyebrow news-list-label">CONTEXTO AÑADIDO</div>${news.map((item) => `<article class="news-item"><div><span class="news-badge">Manual · sin verificar</span><time>${utcTime(item.created_at,true)} UTC</time></div><p>${escapeHtml(item.text)}</p></article>`).join("")}` : '<div class="news-empty"><span>↳</span><p>Aún no has añadido contexto.<br>Los indicadores funcionan sin titulares.</p></div>';
}

function renderTrades(trades) {
  $("#trade-count").textContent = `${trades.length} operaciones`;
  $("#trades-content").innerHTML = trades.length ? `<div class="table-wrap"><table><thead><tr><th>Activo</th><th>Dirección</th><th>Entrada / salida</th><th>P&amp;L neto</th><th>Comisiones</th><th>Cierre · UTC</th><th>Motivo</th></tr></thead><tbody>${trades.map((trade) => `<tr><td><div class="asset-cell">${coinIcon(trade.symbol,true)}<strong>${escapeHtml(coinBase(trade.symbol))}</strong></div></td><td>${trade.side === "short" ? "Corto" : "Largo"}</td><td><div class="dual-number"><span class="muted">${price(trade.entry_price)}</span><span>${price(trade.exit_price)}</span></div></td><td class="${tone(trade.pnl)}">${signedUsd(trade.pnl)}</td><td>${usd(trade.fees)}</td><td class="muted">${utcTime(trade.closed_at,true)}</td><td class="trade-reason">${escapeHtml(trade.reason || "—")}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty-state"><span class="empty-symbol">↗</span><h3>Tu historial está en blanco</h3><p>Las operaciones cerradas aparecerán aquí con su resultado y sus comisiones virtuales.</p></div>';
}

function renderEvents(events) {
  $("#events-content").innerHTML = events.length ? `<div class="events-list">${events.slice(0,100).map((event) => `<div class="event-row"><time>${utcTime(event.time,true)} <span>UTC</span></time><span class="event-level ${["error","warning"].includes(event.level) ? escapeHtml(event.level) : "info"}">${({error:"Error",warning:"Aviso",info:"Info",success:"OK"})[event.level] || "Info"}</span><p>${escapeHtml(event.message)}</p></div>`).join("")}</div>` : '<div class="empty-state compact"><h3>El registro está listo</h3><p>Los próximos análisis y acciones se mostrarán aquí.</p></div>';
}

function updateAggressionLabel() {
  const slider = $("#aggressiveness");
  $("#aggression-value").textContent = `${slider.value} / 10`;
  slider.style.setProperty("--range-fill", `${(number(slider.value)-1)/9*100}%`);
}

function openSettings() {
  if (!state) return;
  const settings = state.settings || {};
  $("#drawer-notice").hidden = true;
  $("#market-source").value = settings.market_source || "demo";
  $("#cycle-seconds").value = settings.cycle_seconds || 60;
  $("#max-positions").value = settings.max_positions || 4;
  $("#daily-loss").value = settings.daily_loss_limit_pct || 3;
  $("#ai-enabled").checked = !!settings.ai_enabled;
  $("#ai-help").textContent = state.meta?.ai_available ? "Claude está disponible. La clave permanece en el servidor y nunca se introduce en este panel." : "Sin clave de Claude. El motor de reglas técnicas sigue disponible. Configura ANTHROPIC_API_KEY de forma segura en las variables del entorno para habilitar la IA.";
  drawerOpen = true;
  $("#drawer-backdrop").hidden = false;
  $("#settings-drawer").hidden = false;
  document.body.classList.add("drawer-is-open");
  render();
  $("[data-action='close-settings']").focus();
}

function closeSettings() {
  drawerOpen = false;
  $("#drawer-backdrop").hidden = true;
  $("#settings-drawer").hidden = true;
  document.body.classList.remove("drawer-is-open");
  $("[data-action='settings']").focus();
}

document.addEventListener("click", async (event) => {
  const assetButton = event.target.closest("[data-asset]");
  if (assetButton && state) {
    selectedSymbol = assetButton.dataset.asset;
    const asset = (state.assets || []).find((item) => item.symbol === selectedSymbol);
    if (asset) renderAssetDetail(asset);
    if (activeView !== "market") location.hash = "market";
    return;
  }
  const modeButton = event.target.closest("[data-mode]");
  if (modeButton && state && modeButton.dataset.mode !== state.settings?.operation_mode) {
    await perform("/api/settings", {operation_mode:modeButton.dataset.mode}, "Modo de operación actualizado.");
    return;
  }
  const closeButton = event.target.closest("[data-close]");
  if (closeButton && state) {
    const position = (state.positions || []).find((item) => String(item.id) === closeButton.dataset.close);
    if (!position) return;
    closingId = position.id;
    $("#close-notice").hidden = true;
    $("#close-title").textContent = `Cerrar posición de ${coinBase(position.symbol)}`;
    $("#close-description").textContent = `Se cerrará la posición virtual al precio disponible en el motor. Resultado no realizado actual: ${signedUsd(position.unrealized_pnl)}; puede variar hasta el cierre. Se aplican comisiones simuladas.`;
    $("#close-dialog").showModal();
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button) return;
  switch (button.dataset.action) {
    case "settings": openSettings(); break;
    case "close-settings": closeSettings(); break;
    case "toggle": if (state) await perform(state.meta?.running ? "/api/stop" : "/api/start", undefined, state.meta?.running ? "Motor en pausa. Tus posiciones virtuales siguen abiertas." : "Motor iniciado. Operaciones exclusivamente simuladas."); break;
    case "cycle": await perform("/api/cycle", undefined, "Análisis completado."); break;
    case "reset-dialog": $("#reset-notice").hidden = true; $("#reset-balance").value = state?.settings?.initial_balance || 10000; $("#reset-dialog").showModal(); break;
    case "cancel-reset": $("#reset-dialog").close(); break;
    case "cancel-close": $("#close-dialog").close(); closingId = null; break;
  }
});

$("#aggressiveness").addEventListener("input", updateAggressionLabel);
$("#aggressiveness").addEventListener("change", async () => {
  const value = number($("#aggressiveness").value);
  const ok = await perform("/api/settings", {aggressiveness:value}, `Agresividad ajustada a ${value} / 10.`);
  if (!ok && state) { $("#aggressiveness").value = state.settings.aggressiveness; updateAggressionLabel(); }
});
$("#ai-enabled").addEventListener("change", () => {
  if ($("#ai-enabled").checked && !state?.meta?.ai_available) {
    $("#ai-enabled").checked = false;
    $("#ai-help").classList.add("attention");
    showNotice("Claude requiere ANTHROPIC_API_KEY en las variables del entorno del servidor. No introduzcas claves en el panel ni en el chat.", true);
  }
});
$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const settings = {cycle_seconds:number($("#cycle-seconds").value),max_positions:number($("#max-positions").value),daily_loss_limit_pct:number($("#daily-loss").value),ai_enabled:$("#ai-enabled").checked};
  if (!$("#market-source").disabled) settings.market_source = $("#market-source").value;
  if (await perform("/api/settings", settings, "Configuración guardada.")) closeSettings();
});
$("#news-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#news-text").value.trim();
  if (!text) return;
  if (await perform("/api/news", {text}, "Contexto manual añadido. El contenido no está verificado.")) $("#news-text").value = "";
});
$("#reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (await perform("/api/reset", {initial_balance:number($("#reset-balance").value)}, "Nueva simulación preparada. El motor queda en pausa.")) { $("#reset-dialog").close(); closeSettings(); }
});
$("#close-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (closingId == null) return;
  if (await perform(`/api/positions/${encodeURIComponent(closingId)}/close`, undefined, "Posición virtual cerrada.")) { $("#close-dialog").close(); closingId = null; }
});
$("#drawer-backdrop").addEventListener("click", closeSettings);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && drawerOpen && !$("#reset-dialog").open && !$("#close-dialog").open) closeSettings();
  if (event.key === "Tab" && drawerOpen && !$("#reset-dialog").open && !$("#close-dialog").open) {
    const focusable = [...$("#settings-drawer").querySelectorAll("button:not(:disabled),input:not(:disabled),select:not(:disabled)")];
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { last?.focus(); event.preventDefault(); }
    else if (!event.shiftKey && document.activeElement === last) { first?.focus(); event.preventDefault(); }
  }
});
window.addEventListener("hashchange", changeView);

async function poll() {
  if (pending) return;
  try {
    const snapshot = await request("/api/state");
    if (pending) return;
    state = snapshot;
    if (!lastConnected) { $("#notice").hidden = true; setConnected(true); }
    render();
  } catch (error) {
    setConnected(false);
    showNotice(`No se puede conectar con el motor. ${error.message}`, true, true);
  }
}

changeView();
setBusy();
poll();
setInterval(poll, 5000);
