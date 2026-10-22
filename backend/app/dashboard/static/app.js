// Prajna research dashboard - paper research only, never advice. Read-only API.
"use strict";
const $ = (s) => document.querySelector(s);
const view = $("#view");
let timer = null;
let chart = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 2) => x == null ? "–" :
  `<span class="${x > 0 ? "up" : x < 0 ? "down" : ""}">${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%</span>`;
const num = (x, d = 2) => x == null ? "–" : Number(x).toLocaleString("en-IN", { maximumFractionDigits: d });
const cr = (x) => x == null ? "–" : x >= 1e5 ? `${(x / 1e5).toFixed(2)} L Cr` : `${num(x, 0)} Cr`;
const pill = (t, cls) => t ? `<span class="pill ${esc(cls || t)}">${esc(t)}</span>` : "";
const ACT = { "BUY": "BULLISH", "HOLD / WAIT": "NEUTRAL", "SELL / AVOID": "BEARISH" };
const actionPill = (a) => a ? `<span class="pill ${ACT[a] || ""}"><b>${esc(a)}</b></span>` : "";
const ago = (iso) => { const m = (Date.now() - new Date(iso)) / 60000;
  return m < 60 ? `${Math.round(m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}
function every(ms, fn) { clearInterval(timer); timer = setInterval(fn, ms); }
function setAsOf(t, live) {
  const l = live ? (live.status === "live" ? `● LIVE · quotes ${new Date(live.fetched_at).toLocaleTimeString("en-IN")}`
    : live.status === "after-hours" ? `Market closed · last quotes ${live.fetched_at ? new Date(live.fetched_at).toLocaleTimeString("en-IN") : "–"}`
    : `Live quotes unavailable (${live.error || live.status}) · stored bars`) : "";
  $("#asof").textContent = [l, t ? `features/cache ${new Date(t).toLocaleString("en-IN")}` : ""].filter(Boolean).join(" · ");
}

function stockLink(sym) { return `<a href="#/stock/${encodeURIComponent(sym)}">${esc(sym)}</a>`; }
function rowsTable(rows, cols) {
  return `<div class="tablewrap"><table><thead><tr>${cols.map(c => `<th class="${c.n ? "num" : ""}">${c.h}</th>`).join("")}</tr></thead><tbody>${
    rows.map(r => `<tr class="click" data-sym="${esc(r.symbol)}">${cols.map(c => `<td class="${c.n ? "num" : ""}">${c.f(r)}</td>`).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}
function bindRows() {
  view.querySelectorAll("tr.click[data-sym]").forEach(tr => tr.onclick = () => location.hash = `#/stock/${encodeURIComponent(tr.dataset.sym)}`);
}
const COLS = [
  { h: "Stock", f: r => `${stockLink(r.symbol)}<div class="muted small">${esc((r.name || "").slice(0, 28))}</div>` },
  { h: "Price", n: 1, f: r => `${num(r.close)}<div class="muted small">${esc(r.close_date || "")}${r.price_at ? " " + new Date(r.price_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : ""}</div>` },
  { h: "Change", n: 1, f: r => pct(r.day_change) },
  { h: "5D", n: 1, f: r => pct(r.ret_5d) },
  { h: "20D", n: 1, f: r => pct(r.ret_20d) },
  { h: "Cap", f: r => `${esc(r.cap_bucket || "")}<div class="muted small">${cr(r.cap_cr)}</div>` },
  { h: "Action", f: r => actionPill(r.action) + (r.e5_pick ? pill("E5 pick", "NEUTRAL") : "") + (r.indicators_basis === "live" ? '<span class="muted small"> live</span>' : "") },
];

// ── market ───────────────────────────────────────────────────────────────────────
async function market() {
  const [m, mv, nw, sc, gl] = await Promise.all([api("/api/market"), api("/api/movers?bucket=ALL&period=day&n=8"),
    api("/api/news?hours=24&source=MEDIA&limit=10"), api("/api/sectors"), api("/api/global")]);
  setAsOf(m.as_of, m.live);
  const b = m.breadth, tot = b.advances + b.declines + b.unchanged || 1;
  view.innerHTML = `
  <div class="grid g4">
    ${m.indices.map(i => `<div class="card"><h3>${esc(i.name || i.symbol)}</h3><div class="big">${num(i.close)}</div>
      <div>${pct(i.day_change)} <span class="muted small">close ${esc(i.close_date || "")}</span></div>
      <div class="small muted">5D ${pct(i.ret_5d)} · 20D ${pct(i.ret_20d)}</div></div>`).join("")}
    <div class="card"><h3>Market regime</h3><div class="big">${pill(m.regime.label || "UNKNOWN")}</div>
      <div class="small muted">Nifty 50 vs its 50/200-day averages (regime-v1)</div></div>
    <div class="card"><h3>Breadth (last session)</h3>
      <div class="bar"><i style="width:${100 * b.advances / tot}%;background:var(--up)"></i><i style="width:${100 * b.unchanged / tot}%;background:var(--muted)"></i><i style="width:${100 * b.declines / tot}%;background:var(--down)"></i></div>
      <div class="small" style="margin-top:6px"><span class="up">${b.advances} up</span> · ${b.unchanged} flat · <span class="down">${b.declines} down</span></div></div>
  </div>
  <h2>Global & macro <small>${esc(gl.note)}</small></h2>
  <div class="grid g4">${gl.global.map(g => `<div class="card"><h3>${esc(g.name)}</h3><div class="big">${num(g.ltp)}</div>
    <div>${g.change_bps != null ? `<span class="${g.change_bps > 0 ? "up" : g.change_bps < 0 ? "down" : ""}">${g.change_bps > 0 ? "+" : ""}${g.change_bps} bps</span>` : pct(g.change)} <span class="small muted">${g.at ? new Date(g.at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : esc(g.date || "")}</span></div>
    ${g.basis && g.key && g.key.startsWith("EXT|") ? `<div class="small muted">${esc(g.basis)}</div>` : ""}</div>`).join("")}
    <div class="card"><h3>FII / DII cash (₹ Cr, net)</h3><table>${gl.flows.slice(0, 4).map(f => `<tr><td class="small">${esc(f.date)}</td><td class="num">FII ${f.fii_net == null ? "–" : `<span class="${f.fii_net >= 0 ? "up" : "down"}">${num(f.fii_net, 0)}</span>`}</td><td class="num">DII ${f.dii_net == null ? "–" : `<span class="${f.dii_net >= 0 ? "up" : "down"}">${num(f.dii_net, 0)}</span>`}</td></tr>`).join("")}</table></div>
    <div class="card"><h3>Not available</h3><div class="small muted">${gl.not_available.map(esc).join(", ")}: not available (KOSPI is not offered by Upstox; the dollar index needs FRED_API_KEY in .env)</div></div>
  </div>
  <div class="grid g2">
    <div><h2>Top gainers <small>last session</small></h2><div class="card">${rowsTable(mv.gainers, COLS.slice(0, 3).concat(COLS.slice(5)))}</div></div>
    <div><h2>Top losers <small>last session</small></h2><div class="card">${rowsTable(mv.losers, COLS.slice(0, 3).concat(COLS.slice(5)))}</div></div>
  </div>
  <div class="grid g2">
    <div><h2>Hot topics <small>AI-tagged news, 24 h</small></h2><div class="card">
      ${nw.topics.map(([t, n]) => `<span class="pill">${esc(t.replace(/_/g, " "))} · ${n}</span>`).join("") || '<span class="muted">No AI-tagged news yet</span>'}
      <h3 style="margin-top:12px">Stocks in the news</h3>
      ${nw.stocks.slice(0, 16).map(([s, d]) => `<span class="pill">${stockLink(s)} ${d.items}${d.positive ? ` <span class="up">+${d.positive}</span>` : ""}${d.negative ? ` <span class="down">−${d.negative}</span>` : ""}</span>`).join("")}
    </div></div>
    <div><h2>Sectors <small>median move, last session</small></h2><div class="card heat">${heat(sc.sectors.filter(x => x.stocks >= 5).slice(0, 8).concat(sc.sectors.filter(x => x.stocks >= 5).slice(-8)))}</div></div>
  </div>
  <h2>Latest news <small>${esc(nw.ai_note)}</small></h2><div class="card">${newsList(nw.items.slice(0, 10))}</div>
  <p class="muted small">Prices: the latest stored bar (today's 1m bars once stored after the session, else the last daily close); not a live tick feed. ${esc(m.disclaimer)}</p>`;
  bindRows(); bindHeat();
}

function heat(list) {
  return list.map(s => { const d = s.day ?? 0, a = Math.min(1, Math.abs(d) / 0.03);
    const bg = d >= 0 ? `rgba(46,194,126,${0.15 + 0.6 * a})` : `rgba(242,84,91,${0.15 + 0.6 * a})`;
    return `<div style="background:${bg}" data-sector="${esc(s.sector)}"><b>${esc(s.sector)}</b>${pct(s.day)} <span class="muted">· ${s.stocks}</span><div class="small muted">20D ${pct(s.ret_20d, 1)}</div></div>`; }).join("");
}
function bindHeat() {
  view.querySelectorAll("[data-sector]").forEach(d => d.onclick = () => location.hash = `#/sectors/${encodeURIComponent(d.dataset.sector)}`);
}
function newsList(items) {
  return items.map(n => `<div class="news-item"><div class="t"><a href="${esc(n.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a></div>
    <div class="meta">${esc(n.publisher)} · seen ${ago(n.at)}${n.delay_min != null ? ` · ${n.delay_min} min after publishing` : ""} ${n.stocks ? n.stocks.map(stockLink).join(" ") : ""}
    ${n.ai ? pill(n.ai.impact_direction) + pill(n.ai.potential_impact) + pill((n.ai.event_type || "").replace(/_/g, " "), "x") : ""}</div>
    ${n.summary && n.summary !== n.title ? `<div class="small muted" style="margin-top:3px">${esc(n.summary)}</div>` : ""}
    ${n.ai && n.ai.summary ? `<div class="ai">AI: ${esc(n.ai.summary)}</div>` : ""}</div>`).join("") || '<div class="muted">No news</div>';
}

// ── movers ───────────────────────────────────────────────────────────────────────
let mv = { bucket: "ALL", period: "day" };
async function movers() {
  const d = await api(`/api/movers?bucket=${mv.bucket}&period=${mv.period}&n=20`);
  setAsOf(d.as_of, (await api("/api/health")).live);
  const btn = (k, v, l) => `<button class="${mv[k] === v ? "on" : ""}" data-k="${k}" data-v="${v}">${l}</button>`;
  view.innerHTML = `<div class="controls">${btn("bucket", "ALL", "All")}${btn("bucket", "LARGE", "Large cap")}${btn("bucket", "MID", "Mid cap")}${btn("bucket", "SMALL", "Small cap")}
    <span style="width:16px"></span>${btn("period", "day", "Last session")}${btn("period", "5d", "5 days")}${btn("period", "20d", "20 days")}</div>
  <div class="grid g2">
    <div><h2>Best returns</h2><div class="card">${rowsTable(d.gainers, COLS)}</div></div>
    <div><h2>Worst returns</h2><div class="card">${rowsTable(d.losers, COLS)}</div></div>
    <div><h2>Steadier <small>${esc(d.steadier_rule)}</small></h2><div class="card">${rowsTable(d.steadier, COLS.slice(0, 3).concat([{ h: "Vol 20D", n: 1, f: r => pct(r.volatility_20, 1) }], COLS.slice(5)))}</div></div>
    <div><h2>BUY signals <small>rule-based, not advice</small></h2><div class="card">${rowsTable(d.bullish, COLS)}</div>
      <h2>SELL / AVOID signals</h2><div class="card">${rowsTable(d.bearish, COLS)}</div></div>
  </div><p class="muted small">Cap buckets: SEBI/AMFI rank by market cap (price × shares from annual results): 1–100 large, 101–250 mid, rest small. ${esc(d.disclaimer)}</p>`;
  view.querySelectorAll("button[data-k]").forEach(b => b.onclick = () => { mv[b.dataset.k] = b.dataset.v; movers(); });
  bindRows();
}

// ── sectors ──────────────────────────────────────────────────────────────────────
async function sectors(name) {
  const d = await api("/api/sectors");
  setAsOf(d.as_of);
  let html = `<h2>All sectors <small>median move of their stocks, last session</small></h2><div class="card heat">${heat(d.sectors)}</div>`;
  if (name) {
    const s = await api(`/api/stocks?sector=${encodeURIComponent(name)}`);
    html = `<h2>${esc(name)} <small>${s.count} stocks · by market cap</small></h2><div class="card">${rowsTable(s.rows, COLS)}</div>` + html;
  }
  view.innerHTML = html; bindRows(); bindHeat();
}

// ── news ─────────────────────────────────────────────────────────────────────────
let newsHours = 24, newsSource = "MEDIA";
const SRC = { NSE_ANNOUNCEMENTS: "NSE filings", CNBCTV18_NEWS_SITEMAP: "CNBC-TV18", ET_STOCKS_RSS: "Economic Times",
  MINT_MARKETS_RSS: "Mint", BL_MARKETS_RSS: "BusinessLine", BS_MARKETS_RSS: "Business Standard", SEBI_RSS: "SEBI" };
async function news() {
  const d = await api(`/api/news?hours=${newsHours}&limit=200${newsSource ? "&source=" + newsSource : ""}`);
  const tab = (k, l, n) => `<button class="${newsSource === k ? "on" : ""}" data-s="${k}">${l}${n != null ? ` <span class="muted">${n}</span>` : ""}</button>`;
  const media = d.sources.filter(x => !["NSE_ANNOUNCEMENTS", "SEBI_RSS"].includes(x.source)).reduce((a, x) => a + x.items, 0);
  view.innerHTML = `<div class="controls">${[6, 24, 72, 168].map(h => `<button class="${h === newsHours ? "on" : ""}" data-h="${h}">${h < 48 ? h + " h" : h / 24 + " days"}</button>`).join("")}
    <span class="muted small" style="align-self:center">last poll ${d.last_poll ? ago(d.last_poll) : "–"} · ${d.total} items in ${newsHours} h</span></div>
  <div class="controls">${tab("MEDIA", "Media news", media)}${tab("", "All", d.total)}${d.sources.map(x => tab(x.source, SRC[x.source] || x.source, x.items)).join("")}</div>
  <div class="card"><h3>Sources in this window</h3><table><thead><tr><th>Source</th><th class="num">Items</th><th class="num">AI-tagged</th><th class="num">Linked to a stock</th><th class="num">Median delay (published → seen)</th></tr></thead><tbody>
    ${d.sources.map(x => `<tr><td>${esc(SRC[x.source] || x.source)}</td><td class="num">${x.items}</td><td class="num">${x.ai}</td><td class="num">${x.linked}</td><td class="num">${x.median_delay_min == null ? "–" : x.median_delay_min + " min"}</td></tr>`).join("")}</tbody></table>
    <div class="small muted" style="margin-top:6px">Delay = when Prajna first saw an item minus the publisher's own timestamp (polling 2–5 min in market hours; a feed that publishes late shows a longer delay).</div></div>
  <div class="grid g2"><div><h2>Topics <small>all sources</small></h2><div class="card">${d.topics.map(([t, n]) => `<span class="pill">${esc(t.replace(/_/g, " "))} · ${n}</span>`).join("") || '<span class="muted">None yet</span>'}</div></div>
  <div><h2>Most mentioned stocks <small>all sources</small></h2><div class="card">${d.stocks.map(([s, x]) => `<span class="pill">${stockLink(s)} ${x.items}${x.positive ? ` <span class="up">+${x.positive}</span>` : ""}${x.negative ? ` <span class="down">−${x.negative}</span>` : ""}</span>`).join("")}</div></div></div>
  <h2>${esc(newsSource === "MEDIA" ? "Media news" : newsSource ? SRC[newsSource] || newsSource : "All news")} <small>${esc(d.ai_note)}</small></h2><div class="card">${newsList(d.items)}</div>`;
  view.querySelectorAll("button[data-h]").forEach(b => b.onclick = () => { newsHours = +b.dataset.h; news(); });
  view.querySelectorAll("button[data-s]").forEach(b => b.onclick = () => { newsSource = b.dataset.s; news(); });
}

// ── stock ────────────────────────────────────────────────────────────────────────
let tf = "1d";
async function stock(sym) {
  if (!sym) { view.innerHTML = `<div class="card">Search a stock above (symbol or name).</div>`; return; }
  const d = await api(`/api/stock/${encodeURIComponent(sym)}`);
  setAsOf(null, d.live_status);
  const sg = d.signal, f = d.features || {}, r = d.ranges || {};
  const e5 = d.e5_today;
  const pl = d.plan || {};
  view.innerHTML = `
  <div class="card plan"><h3>Trade plan <span class="muted small">${esc(pl.version || "")} · ${esc(d.indicators_basis || "indicators from the morning snapshot")}</span></h3>
    <div class="grid g4">
      <div><div class="big">${actionPill(pl.action)}</div><div class="small muted">price ${num(pl.price)}</div></div>
      ${pl.entry_zone ? `<div><div class="muted small">ENTRY ZONE</div><div class="big">${num(pl.entry_zone[0])} – ${num(pl.entry_zone[1])}</div></div>` : ""}
      ${pl.exit_zone ? `<div><div class="muted small">EXIT ZONE (if holding)</div><div class="big">${num(pl.exit_zone[0])} – ${num(pl.exit_zone[1])}</div></div>` : ""}
      ${pl.buy_trigger ? `<div><div class="muted small">BUY ONLY ABOVE</div><div class="big">${num(pl.buy_trigger)}</div></div>` : ""}
      <div><div class="muted small">STOP-LOSS</div><div class="big down">${num(pl.stop_loss)}</div>${pl.holding_stop ? `<div class="small muted">holding stop ${num(pl.holding_stop)}</div>` : ""}</div>
      <div><div class="muted small">${pl.action === "SELL / AVOID" ? "DOWNSIDE 1" : "TARGET T1"}</div><div class="big ${pl.action === "SELL / AVOID" ? "down" : "up"}">${num(pl.t1)}</div></div>
      <div><div class="muted small">${pl.action === "SELL / AVOID" ? "DOWNSIDE 2" : "TARGET T2"}</div><div class="big ${pl.action === "SELL / AVOID" ? "down" : "up"}">${num(pl.t2)}</div><div class="small muted">${esc(pl.reward_risk || "")}</div></div>
    </div>
    <div class="grid g2" style="margin-top:10px">
      <div><h3>When to buy</h3>${(pl.when_buy || []).map(x => `<div class="flag green small">${esc(x)}</div>`).join("")}</div>
      <div><h3>When to sell / exit</h3>${(pl.when_sell || []).map(x => `<div class="flag red small">${esc(x)}</div>`).join("")}</div>
    </div>
    <div class="small muted" style="margin-top:8px">How: ${(pl.basis || []).map(esc).join(" · ")}</div>
    <div class="small" style="margin-top:4px;color:#f5d68a">${esc(pl.disclaimer || "")}</div>
  </div>
  <div class="grid g3" style="margin-top:12px">
    <div class="card"><h3>${esc(d.segment)} · ${esc(d.sector || "no sector")}</h3>
      <div class="big">${esc(d.symbol)} <span class="muted" style="font-size:14px">${esc(d.name || "")}</span></div>
      <div id="pricebox">${priceBox(d)}</div>
      <div>${Object.entries(d.returns).map(([k, v]) => `<span class="pill">${k} ${pct(v, 1)}</span>`).join("")}</div></div>
    <div class="card"><h3>Research signal <span class="muted small">${esc(sg.version)}</span></h3>
      <div class="big">${pill(sg.label)} <span class="small muted">score ${sg.score}</span></div>
      <div>${pill(sg.trend)} ${pill(sg.momentum, "x")}</div>
      <ul class="reasons small">${sg.reasons.map(x => `<li><span class="pts ${x.points > 0 ? "up" : "down"}">${x.points > 0 ? "+" : ""}${x.points}</span>${esc(x.why)}</li>`).join("")}</ul>
      <div class="small muted">${esc(sg.disclaimer)}</div></div>
    <div class="card"><h3>Typical ranges <span class="muted small">${esc(r.basis || "")}</span></h3>
      ${r.next_session_q10_q90 ? `<div>Next session (E5 q10–q90): <b>${num(r.next_session_q10_q90.low)} – ${num(r.next_session_q10_q90.high)}</b></div>` : '<div class="muted small">Not in today\'s E5 universe (top 500 by turnover)</div>'}
      ${r.five_day ? `<div style="margin-top:6px">About a week (±ATR×√5): <b>${num(r.five_day.low)} – ${num(r.five_day.high)}</b> <span class="muted small">±${(r.five_day.width_pct * 100).toFixed(1)}%</span></div>` : ""}
      ${e5 ? `<h3 style="margin-top:12px">E5 model today ${e5.selected ? pill("in picks", "NEUTRAL") : ""}</h3>
        <div class="small">P(up) <b>${(e5.prob_up * 100).toFixed(0)}%</b> · expected open→close ${pct(e5.exp_return)} · volatility ${pct(e5.volatility, 1)} · confidence ${(e5.confidence * 100).toFixed(0)}% · rank ${e5.rank}/500</div>
        <div class="small muted">Forward test in progress; its past accuracy stays hidden until session 40.</div>` : ""}</div>
  </div>
  <h2>Chart <small>${d.low_confidence_bars ? `${d.low_confidence_bars} older daily bars have a low-confidence split/bonus basis` : "split/bonus adjusted"}</small></h2>
  <div class="card"><div class="controls">${["1d", "1h", "15m", "5m"].map(t => `<button class="${t === tf ? "on" : ""}" data-tf="${t}">${t.toUpperCase()}</button>`).join("")}
    <span class="small muted">SMA 20 (blue) · SMA 50 (orange) · dashed: entry / SL / T1 / T2 of the plan · markers: candle patterns</span></div><div id="chart"></div></div>
  <div class="grid g2">
    <div><h2>Candle analysis <small>last 15 sessions</small></h2><div class="card">
      <div style="margin-bottom:8px">${(d.candle_read || []).map(x => `<div class="small">• ${esc(x)}</div>`).join("") || '<span class="muted small">No notable pattern in the last 5 candles</span>'}</div>
      <div class="tablewrap"><table><thead><tr><th>Date</th><th class="num">Change</th><th>Candle</th><th class="num">Body</th><th class="num">Vol × avg</th><th>Patterns</th></tr></thead><tbody>
      ${d.candles.slice(-15).reverse().map(c => `<tr><td>${esc(c.date)}</td><td class="num">${pct(c.change)}</td><td>${pill(c.direction === "UP" ? "UP" : c.direction === "DOWN" ? "DOWN" : "FLAT", c.direction === "UP" ? "BULLISH" : c.direction === "DOWN" ? "BEARISH" : "NEUTRAL")}</td>
        <td class="num">${c.body_share == null ? "–" : (c.body_share * 100).toFixed(0) + "%"}</td><td class="num">${c.volume_vs_avg == null ? "–" : c.volume_vs_avg.toFixed(1)}</td><td>${c.patterns.map(p => pill(p.replace(/_/g, " "), "x")).join("")}</td></tr>`).join("")}
      </tbody></table></div></div></div>
    <div><h2>AI note <small>Bedrock, from the facts on this page; never advice</small></h2><div class="card" id="ai">${aiBox(d.ai)}</div>
      <h2>Forensic <small>${esc(d.forensic.basis)}</small></h2><div class="card">
      ${d.forensic.red_flags.map(x => `<div class="flag red">${esc(x)}</div>`).join("")}${d.forensic.green_flags.map(x => `<div class="flag green">${esc(x)}</div>`).join("")}
      ${!d.forensic.red_flags.length && !d.forensic.green_flags.length ? '<span class="muted">No flags from the data held</span>' : ""}</div></div>
  </div>
  <div class="grid g3">
    <div class="card"><h3>Valuation & quality</h3><table>
      ${[["P/E", d.ratios.pe_company, d.ratios.pe_sector], ["P/B", d.ratios.pb_company, d.ratios.pb_sector], ["ROE %", d.ratios.roe, d.ratios.roe_sector], ["ROCE %", d.ratios.roce, d.ratios.roce_sector]]
        .map(([n, c, s]) => `<tr><td>${n}</td><td class="num">${num(c)}</td><td class="num muted">sector ${num(s)}</td></tr>`).join("")}
      <tr><td>Own P/E (TTM)</td><td class="num">${num(f.pe_ttm)}</td><td></td></tr><tr><td>Beta 60D</td><td class="num">${num(f.beta_60)}</td><td></td></tr>
      <tr><td>RSI 14</td><td class="num">${num(f.rsi_14, 1)}</td><td></td></tr><tr><td>52W high</td><td class="num">${pct(f.dist_high_252, 1)}</td><td class="muted">distance</td></tr></table></div>
    <div class="card"><h3>Shareholding</h3><table>${(d.holdings || []).map(h => `<tr><td>${esc(h.category)}</td>${(h.history || []).slice(0, 4).map(x => `<td class="num">${num(x.value)}<div class="muted small">${esc(x.period)}</div></td>`).join("")}</tr>`).join("") || '<tr><td class="muted">No data</td></tr>'}</table></div>
    <div class="card"><h3>Results & corporate actions</h3>
      ${d.results.map(x => `<div class="small">${esc(x.kind)} ${esc(x.meeting_date || x.event_at || "")} ${x.verdict ? pill(x.verdict, x.verdict === "BEAT" ? "BULLISH" : x.verdict === "MISS" ? "BEARISH" : "NEUTRAL") : ""}</div>`).join("") || '<div class="muted small">No results events</div>'}
      <div style="margin-top:8px">${d.actions.map(a => `<div class="small">${esc(a.action_type)} · ex ${esc(a.ex_date || "?")}</div>`).join("") || '<div class="muted small">No corporate actions</div>'}</div></div>
  </div>
  <h2>News <small>last 30 days, linked to this stock</small></h2><div class="card">${newsList(d.news.map(n => ({ ...n, stocks: null })))}</div>
  ${d.profile ? `<h2>Profile</h2><div class="card small">${esc(d.profile)}</div>` : ""}
  <p class="muted small">${esc(d.disclaimer)} Features as of the ${esc(d.features_session || "?")} pre-session snapshot.</p>`;
  view.querySelectorAll("button[data-tf]").forEach(b => b.onclick = () => { tf = b.dataset.tf; drawChart(d); view.querySelectorAll("button[data-tf]").forEach(x => x.classList.toggle("on", x.dataset.tf === tf)); });
  const ab = $("#aibtn"); if (ab) ab.onclick = () => genAI(d.symbol);
  drawChart(d);
}
function priceBox(d) {
  const q = d.live;
  return `<div class="big">${num(d.close)} ${pct(d.day_change)}</div>
    <div class="small muted">${esc(d.price_basis)}${d.price_at ? " · " + new Date(d.price_at).toLocaleString("en-IN") : " · " + esc(d.close_date || "")}</div>
    ${q && q.official_close && q.last_trade != null && Math.abs(q.last_trade - q.ltp) > 0.004 ? `<div class="small muted">last trade ${num(q.last_trade)} (NSE's close is the weighted average of the last 30 minutes, not the last trade)</div>` : ""}
    ${q ? `<div class="small" style="margin-top:4px">O ${num(q.open)} · H ${num(q.high)} · L ${num(q.low)} · prev ${num(q.prev_close)} · vol ${num(q.volume, 0)}
      ${q.lower_circuit ? `<div class="muted">circuit ${num(q.lower_circuit)} – ${num(q.upper_circuit)}</div>` : ""}</div>` : ""}`;
}
async function refreshPrice(sym) {
  try { const r = await api(`/api/quote/${encodeURIComponent(sym)}`); const el = $("#pricebox");
    if (el && r.quote) { const q = r.quote; el.innerHTML = priceBox({ close: q.ltp, day_change: q.change, price_basis: q.official_close ? "NSE official close (bhavcopy)" : "live (Upstox quote)", price_at: q.at, live: q }); }
    setAsOf(null, r.live); } catch (e) { /* keep the last price */ }
}
function aiBox(a) {
  if (a && a.status === "OK") { const o = a.output; return `<div>${esc(o.summary)}</div>
    <div class="grid g3" style="margin-top:8px"><div><h3>Positives</h3>${o.positives.map(x => `<div class="flag green small">${esc(x)}</div>`).join("") || "–"}</div>
    <div><h3>Risks</h3>${o.risks.map(x => `<div class="flag red small">${esc(x)}</div>`).join("") || "–"}</div>
    <div><h3>Watch</h3>${o.watch.map(x => `<div class="small">• ${esc(x)}</div>`).join("") || "–"}</div></div>
    <div class="small muted" style="margin-top:6px">${esc(a.model_id)} · ${esc(a.prompt_version)} · ${new Date(a.generated_at).toLocaleString("en-IN")}</div>`; }
  const st = a ? `<div class="small down">Last attempt: ${esc(a.status)} ${esc(a.error || "")}</div>` : "";
  return `${st}<button class="btn primary" id="aibtn">Generate today's AI note</button> <span class="small muted">one model call per stock per day</span>`;
}
async function genAI(sym) {
  $("#ai").innerHTML = '<span class="muted">Asking the model…</span>';
  try { $("#ai").innerHTML = aiBox(await api(`/api/ai/${encodeURIComponent(sym)}`, { method: "POST" })); }
  catch (e) { $("#ai").innerHTML = `<span class="down">${esc(e.message)}</span>`; }
  const ab = $("#aibtn"); if (ab) ab.onclick = () => genAI(sym);
}
function sma(bars, n) {
  const out = []; let s = 0;
  bars.forEach((b, i) => { s += b.close; if (i >= n) s -= bars[i - n].close; if (i >= n - 1) out.push({ time: b.time, value: s / n }); });
  return out;
}
async function drawChart(d) {
  const el = $("#chart"); if (!el || !window.LightweightCharts) return;
  const c = await api(`/api/candles/${encodeURIComponent(d.symbol)}?tf=${tf}`);
  const bars = c.bars.filter(b => b.open != null && b.close != null);
  if (chart) { chart.remove(); chart = null; }
  chart = LightweightCharts.createChart(el, { layout: { background: { color: "#171e26" }, textColor: "#8b98a5" },
    grid: { vertLines: { color: "#222c37" }, horzLines: { color: "#222c37" } }, timeScale: { timeVisible: tf !== "1d" },
    rightPriceScale: { borderColor: "#2a3542" }, crosshair: { mode: 1 } });
  const cs = chart.addCandlestickSeries({ upColor: "#2ec27e", downColor: "#f2545b", wickUpColor: "#2ec27e", wickDownColor: "#f2545b", borderVisible: false });
  cs.setData(bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
  const vs = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "", color: "#2a3542" });
  vs.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  vs.setData(bars.map(b => ({ time: b.time, value: b.volume || 0, color: b.close >= b.open ? "rgba(46,194,126,.35)" : "rgba(242,84,91,.35)" })));
  chart.addLineSeries({ color: "#4f9dff", lineWidth: 1, priceLineVisible: false }).setData(sma(bars, 20));
  chart.addLineSeries({ color: "#f5a524", lineWidth: 1, priceLineVisible: false }).setData(sma(bars, 50));
  const pl = d.plan || {};
  const line = (p, color, title) => p && cs.createPriceLine({ price: p, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title });
  line(pl.stop_loss, "#f2545b", "SL"); line(pl.t1, "#2ec27e", pl.action === "SELL / AVOID" ? "D1" : "T1");
  line(pl.t2, "#2ec27e", pl.action === "SELL / AVOID" ? "D2" : "T2");
  line(pl.entry, "#4f9dff", "entry"); line(pl.buy_trigger, "#4f9dff", "buy above");
  if (tf === "1d") {
    const keep = new Set(["BULLISH_ENGULFING", "BEARISH_ENGULFING", "HAMMER", "SHOOTING_STAR", "GAP_UP", "GAP_DOWN", "DOJI"]);
    cs.setMarkers(d.candles.filter(x => x.patterns.some(p => keep.has(p))).map(x => {
      const p = x.patterns.find(p => keep.has(p)); const bull = /BULLISH|HAMMER|GAP_UP/.test(p);
      return { time: x.date, position: bull ? "belowBar" : "aboveBar", color: bull ? "#2ec27e" : p === "DOJI" ? "#f5a524" : "#f2545b",
        shape: bull ? "arrowUp" : p === "DOJI" ? "circle" : "arrowDown", text: "" }; }));
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - 260), to: bars.length + 3 });
  } else chart.timeScale().fitContent();
}

// ── report ───────────────────────────────────────────────────────────────────────
async function reportView() {
  const d = await api("/api/report");
  const r0 = d.reports[0];
  const sec = (xs, name) => xs && xs.length ? `<h2>${name}</h2>${xs.map((x, i) => `<div class="card" style="margin-bottom:8px"><b>${i + 1}. ${esc(x.headline)}</b><div style="margin-top:4px">${esc(x.text)}</div><div class="small" style="margin-top:4px"><b>Impact:</b> ${esc(x.impact)}</div></div>`).join("")}` : "";
  const body = r0 && r0.status === "OK" ? (() => { const r = r0.report; return `
    <div class="card"><h3>${esc(r0.date)} · generated ${new Date(r0.generated_at).toLocaleTimeString("en-IN")} · ${esc(r0.model_id)} · ${esc(r0.prompt_version)}</h3><div class="big">${esc(r.title)}</div></div>
    ${sec(r.indian_market, "Indian market")}${sec(r.global_market, "Global market")}
    <div class="grid g2"><div><h2>Key variables to monitor</h2><div class="card">${r.variables_to_monitor.map(x => `<div class="small">• ${esc(x)}</div>`).join("")}</div></div>
    <div><h2>Overall assessment</h2><div class="card">${esc(r.overall)}</div></div></div>
    <h2>From the data <small>not written by AI: today's results and the headlines by theme</small></h2>
    <div class="grid g2"><div class="card"><h3>Results today</h3>${(r0.results_today || []).map(x => `<span class="pill">${stockLink(x.trading_symbol)} ${x.verdict ? pill(x.verdict, x.verdict === "BEAT" ? "BULLISH" : x.verdict === "MISS" ? "BEARISH" : "NEUTRAL") : ""}</span>`).join("") || '<span class="muted small">None parsed</span>'}</div>
    <div class="card"><h3>Headlines by theme</h3>${Object.entries(r0.themes || {}).map(([k, v]) => `<div style="margin-bottom:6px"><b class="small">${esc(k.replace(/_/g, " "))}</b>${v.map(x => `<div class="small">• ${esc(x.title)} <span class="muted">(${esc(x.source)})</span></div>`).join("")}</div>`).join("")}</div></div>
    <p class="muted small">Written by AI from Prajna's facts only (indices, breadth, sectors, movers, global quotes, FII/DII, today's results and media headlines). Missing inputs: ${(r0.not_available || []).map(esc).join(", ")}. A news summary, not a trading recommendation.</p>`; })()
    : `<div class="card">${r0 ? `<span class="down">Last attempt ${esc(r0.status)} ${esc(r0.error || "")}</span>` : "No report yet."}</div>`;
  view.innerHTML = `<div class="controls"><button class="btn primary" id="gen">Generate now</button>
    <span class="small muted" style="align-self:center">Scheduled 08:45 (pre-market) and 16:20 (after the close) Mon–Fri; also sent to Telegram</span></div>${body}
    <h2>Earlier reports</h2><div class="card">${d.reports.slice(1).map(x => `<div class="small">${esc(x.date)} ${esc((x.generated_at || "").slice(11, 16))} · ${esc(x.status)} · ${esc((x.report || {}).title || "")}</div>`).join("") || '<span class="muted small">None</span>'}</div>`;
  $("#gen").onclick = async () => { $("#gen").textContent = "Generating… (about a minute)"; $("#gen").disabled = true;
    try { await api("/api/report/generate", { method: "POST" }); } catch (e) { alert(e.message); } reportView(); };
}

// ── model ────────────────────────────────────────────────────────────────────────
async function model() {
  const d = await api("/api/e5");
  view.innerHTML = `<div class="card"><h3>E5 forward test</h3><div>Day <b>${d.forward_day}</b> of ${d.forward_needed} · session ${esc(d.session)}</div>
    <div class="small muted">${esc(d.note)}</div></div>
    <h2>Today's ranking <small>top 100 of the 500-name universe; picks highlighted</small></h2><div class="card">
    ${d.rows.length ? `<div class="tablewrap"><table><thead><tr><th class="num">Rank</th><th>Stock</th><th>Sector</th><th class="num">P(up)</th><th class="num">Exp. O→C</th><th class="num">Range q10–q90</th><th class="num">Volatility</th><th class="num">Confidence</th><th>Pick</th></tr></thead><tbody>
    ${d.rows.map(r => `<tr class="click" data-sym="${esc(r.trading_symbol)}"><td class="num">${r.rank}</td><td>${stockLink(r.trading_symbol)}</td><td>${esc(r.sector || "")}</td><td class="num">${(r.prob_up * 100).toFixed(0)}%</td>
      <td class="num">${pct(r.exp_return)}</td><td class="num">${pct(r.range_lo, 1)} … ${pct(r.range_hi, 1)}</td><td class="num">${pct(r.volatility, 1)}</td><td class="num">${(r.confidence * 100).toFixed(0)}%</td><td>${r.selected ? pill("pick", "NEUTRAL") : ""}</td></tr>`).join("")}</tbody></table></div>`
    : '<div class="muted">No predictions for today (non-trading day, or before 09:06 IST).</div>'}</div>`;
  bindRows();
}

function about() {
  view.innerHTML = `<div class="card"><h3>What this is</h3>
  <p>A private, read-only research view of Prajna's database: daily and intraday candles (split/bonus adjusted), the Stage 3 features, news from 7 sources with AWS Bedrock enrichment, vendor fundamentals, and the E5 machine-learning model's outputs.</p>
  <h3>How labels are made</h3><ul>
  <li><b>Research signal</b> (dash-signal-v1): +1/−1 for price above/below its 20-, 50- and 200-day averages; RSI bands; MACD sign; 3-day news tone; E5's probability and expected return. ≥ +3 BULLISH, ≤ −3 BEARISH, else NEUTRAL. Every contribution is listed on the stock page.</li>
  <li><b>Ranges</b>: E5's q10–q90 for the next session, and ±ATR×√5 for about a week. Typical ranges, never targets.</li>
  <li><b>Candle patterns</b>: fixed geometric rules (doji, hammer, engulfing, gaps, inside bar, marubozu, volume spike).</li>
  <li><b>Cap buckets</b>: SEBI/AMFI rank by market cap: 1–100 large, 101–250 mid, rest small.</li>
  <li><b>Steadier</b>: large/mid cap, uptrend, lowest 20-day volatility. Lower volatility, not "safe".</li>
  <li><b>AI</b>: Bedrock Nova Pro describes news items and, on request, a stock's facts. It is told not to predict prices or advise.</li></ul>
  <h3>Limits</h3><ul><li>The E5 model is in its 40-session forward test; its past accuracy is hidden until then by design. The development edge was small and not significant.</li>
  <li>Prices update with Prajna's ingestion (daily bars each morning, intraday bars after the session), not tick by tick.</li>
  <li>Paper research only. Not investment advice. No order is ever placed.</li></ul></div>`;
}

// ── router ───────────────────────────────────────────────────────────────────────
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const p = parts[0] || "market", arg = parts[1];
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === `#/${p}`));
  clearInterval(timer);
  try {
    if (p === "market") { await market(); every(30000, market); }
    else if (p === "movers") { await movers(); every(30000, movers); }
    else if (p === "sectors") { await sectors(arg); }
    else if (p === "news") { await news(); every(30000, news); }
    else if (p === "stock") { await stock(arg); if (arg) every(30000, () => refreshPrice(arg)); }
    else if (p === "model") { await model(); every(120000, model); }
    else if (p === "report") { await reportView(); }
    else about();
  } catch (e) { view.innerHTML = `<div class="card down">Could not load: ${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", route);

let st = null;
$("#q").addEventListener("input", (e) => {
  clearTimeout(st); const q = e.target.value.trim(); const box = $("#suggest");
  if (!q) { box.style.display = "none"; return; }
  st = setTimeout(async () => {
    const r = await api(`/api/search?q=${encodeURIComponent(q)}`);
    box.innerHTML = r.map(x => `<div data-s="${esc(x.symbol)}"><b>${esc(x.symbol)}</b> <span class="muted small">${esc(x.name || "")} · ${esc(x.sector || x.segment)}</span></div>`).join("");
    box.style.display = r.length ? "block" : "none";
    box.querySelectorAll("div[data-s]").forEach(d => d.onclick = () => { location.hash = `#/stock/${encodeURIComponent(d.dataset.s)}`; box.style.display = "none"; e.target.value = ""; });
  }, 200);
});
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.value.trim()) { location.hash = `#/stock/${encodeURIComponent(e.target.value.trim().toUpperCase())}`; $("#suggest").style.display = "none"; } });
route();
