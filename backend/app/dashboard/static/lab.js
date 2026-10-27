// Strategy Lab views (user 2026-10-27). Paper/shadow research only; never advice.
// Uses app.js helpers (esc, num, api, view, every, setAsOf, stockLink, pill) at call time.
"use strict";
let labChart = null;
const inr = (x) => x == null ? "–" : `<span class="${x > 0 ? "up" : x < 0 ? "down" : ""}">${x > 0 ? "+" : x < 0 ? "−" : ""}₹${Math.abs(Number(x)).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</span>`;
const pct1 = (x) => x == null ? "–" : `${(x * 100).toFixed(1)}%`;
const rr = (x) => x == null ? "–" : `<span class="${x > 0 ? "up" : x < 0 ? "down" : ""}">${x > 0 ? "+" : ""}${Number(x).toFixed(2)}R</span>`;
const hhmm = (iso) => iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "–";
const sideTxt = (s) => s > 0 ? '<span class="up">LONG</span>' : '<span class="down">SHORT</span>';
const LAB_TABS = [["overview", "Strategies"], ["today", "Today & forensic"], ["regime", "Regime"],
  ["history", "History"], ["brief", "Morning brief"], ["health", "Health"]];
const CLASS_TONE = { TARGET_HIT: "BULLISH", CLOSE_WIN: "BULLISH", TIME_EXIT_WIN: "BULLISH", OPEN_GAIN: "BULLISH",
  NOT_FILLED: "", NO_DATA: "" };
const classPill = (c) => `<span class="pill ${CLASS_TONE[c] ?? "BEARISH"}">${esc(c)}</span>`;

function labNav(cur) {
  return `<div class="controls labtabs">${LAB_TABS.map(([k, t]) =>
    `<button class="${k === cur ? "on" : ""}" onclick="location.hash='#/lab/${k}'">${t}</button>`).join("")}</div>
  <div class="card small lab-note">Daily profit/loss is shown by the admin's decision of 27 Oct 2026. The locked P1/P2 (60 and 250 sessions),
  E5 (40) and E6 checkpoints run unchanged, and <b>no rule may be changed because of these daily numbers</b>; a change is a new version
  with its own forward test. Paper/shadow only: no order is ever placed.</div>`;
}

async function labView(sub, arg) {
  sub = sub || "overview";
  const head = `<h2>Strategy Lab <small>paper / shadow research</small></h2>${labNav(sub)}`;
  view.innerHTML = head + '<div id="labbody" class="loading">Loading…</div>';
  const body = $("#labbody");
  try {
    if (sub === "overview") await labOverview(body);
    else if (sub === "today") await labToday(body, arg);
    else if (sub === "regime") await labRegime(body);
    else if (sub === "history") await labHistory(body, arg);
    else if (sub === "brief") await labBrief(body, arg);
    else if (sub === "health") await labHealth(body);
    else if (sub === "trade") await labTrade(body, arg);
    body.classList.remove("loading");
  } catch (e) { body.innerHTML = `<div class="card down">Could not load: ${esc(e.message)}</div>`; }
}

function spark(curve) {
  const pts = curve.filter(p => p.eq != null);
  if (pts.length < 2) return '<div class="muted small">not enough sessions yet</div>';
  const w = 220, h = 44, ys = pts.map(p => p.eq), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${(i / (pts.length - 1) * w).toFixed(1)},${(h - 4 - (p.eq - lo) / span * (h - 8)).toFixed(1)}`).join("");
  const up = ys[ys.length - 1] >= ys[0];
  return `<svg width="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="spark"><path d="${d}" fill="none" stroke="${up ? "var(--up)" : "var(--down)"}" stroke-width="1.6"/></svg>`;
}

async function labOverview(body) {
  const o = await api("/api/lab/overview");
  const fam = {};
  o.strategies.forEach(s => (fam[s.family] = fam[s.family] || []).push(s));
  const card = (s) => {
    const l = s.last || {};
    const sw = s.switchable ? `<label class="switch"><input type="checkbox" data-sw="${esc(s.strategy)}" ${s.enabled ? "checked" : ""}><span>${s.enabled ? "ON" : "OFF"}</span></label>` : '<span class="muted small">monitor (no switch)</span>';
    return `<div class="card lab-card ${s.enabled === false ? "off" : ""}">
      <div class="lab-card-h"><b>${esc(s.strategy)}</b>${sw}</div>
      <div class="small muted">${esc(s.title)}</div>
      <div class="lab-kpis">
        <div><span class="muted small">Last session ${esc(l.session_date || "–")}</span><div class="big">${inr(l.net_inr)}</div><span class="small">${l.trades ?? 0} trades · ${l.wins ?? 0} won</span></div>
        <div><span class="muted small">Since ${esc(s.first || "–")}</span><div class="big">${inr(s.net_inr)}</div><span class="small">${s.trades} trades · hit ${pct1(s.hit_rate)}</span></div>
      </div>
      ${spark(s.curve)}
      <div class="small">Equity ${s.equity_inr == null ? "–" : "₹" + num(s.equity_inr, 0)} · max drawdown ${pct1(s.max_drawdown)}
        ${s.look ? `· <span class="pill NEUTRAL">look: ${esc(s.look)}</span>` : ""}</div>
      <div class="small"><a href="#/lab/history/${encodeURIComponent(s.strategy)}">history</a> · <a href="#/lab/today">today</a>${s.switch_reason ? ` · <span class="muted">last switch: ${esc(s.switch_reason)}</span>` : ""}</div>
    </div>`;
  };
  const names = { P1: "P1 · regime-aware shadow strategies (S1 breakout, S2 mean reversion)", PAPER: "Paper book", E5: "E5 · ML model (forward test)", E6: "E6 · post-results monitor" };
  body.innerHTML = Object.keys(fam).map(f => `<h2>${esc(names[f] || f)}</h2><div class="grid g3">${fam[f].map(card).join("")}</div>`).join("")
    + `<div class="card small muted" style="margin-top:12px">${esc(o.note)}</div>`;
  body.querySelectorAll("input[data-sw]").forEach(cb => cb.onchange = async () => {
    const on = cb.checked, st = cb.dataset.sw;
    cb.checked = !on;
    labSwitchForm(st, on);
  });
}

function labSwitchForm(strategy, on) {
  const box = document.createElement("div");
  box.className = "modal";
  const tok = sessionStorage.getItem("prajna_token") || "";
  box.innerHTML = `<div class="card modal-card"><h3>Switch ${esc(strategy)} ${on ? "ON" : "OFF"}</h3>
    ${!on ? '<div class="small warn-text">If this strategy is in a locked forward test (P1), switching it off stops its record and is logged as a protocol deviation.</div>' : ""}
    <label class="small">Reason (kept in the audit log)<input id="sw-reason" class="inp" placeholder="e.g. paused while reviewing slippage"></label>
    <label class="small">Write token ${tok ? "(remembered for this browser session)" : ""}<input id="sw-token" class="inp" type="password" value="${esc(tok)}" autocomplete="off"></label>
    <div class="controls"><button class="btn primary" id="sw-go">Switch ${on ? "on" : "off"}</button><button class="btn" id="sw-cancel">Cancel</button></div>
    <div id="sw-msg" class="small"></div></div>`;
  document.body.appendChild(box);
  box.querySelector("#sw-cancel").onclick = () => box.remove();
  box.querySelector("#sw-go").onclick = async () => {
    const reason = box.querySelector("#sw-reason").value.trim(), token = box.querySelector("#sw-token").value;
    const msg = box.querySelector("#sw-msg");
    if (reason.length < 3) { msg.innerHTML = '<span class="down">Write a reason first.</span>'; return; }
    try {
      const r = await api("/api/lab/switch", { method: "POST", headers: { "Content-Type": "application/json", "X-Prajna-Token": token },
        body: JSON.stringify({ strategy, on, reason }) });
      try { sessionStorage.setItem("prajna_token", token); } catch (_) { /* storage blocked */ }
      msg.innerHTML = `<span class="up">${esc(r.status)}</span> ${r.warning ? `<div class="warn-text">${esc(r.warning)}</div>` : ""}`;
      setTimeout(() => { box.remove(); labView("overview"); }, r.warning ? 2500 : 700);
    } catch (e) { msg.innerHTML = `<span class="down">${esc(e.message)}</span>`; }
  };
}

async function labToday(body, date) {
  const d = await api(`/api/lab/day${date ? `?date=${encodeURIComponent(date)}` : ""}`);
  const o = await api("/api/lab/overview");
  const picker = `<div class="controls"><span class="muted small">Session</span><select id="labdate">${o.dates.map(x => `<option ${x === d.date ? "selected" : ""}>${x}</option>`).join("")}</select></div>`;
  if (!d.available) { body.innerHTML = picker + '<div class="card muted">No lab run for this session yet (the lab builds at 15:55 and 22:45).</div>'; bindDate(); return; }
  const mk = d.forensics._MARKET;
  const pre = mk ? mk.thought.regime_pre : null, opn = mk ? mk.thought.regime_open : null;
  const cps = mk ? mk.happened.checkpoints : {};
  const market = mk ? `<div class="card"><h3>Market story · ${esc(d.date)}</h3>
      <div>Morning regime ${pill(pre && pre.state)} <span class="small muted">${esc(pre && pre.rule || "")}</span> · at the open ${pill(opn && opn.state)}</div>
      <table class="small"><tr>${Object.keys(cps).map(c => `<th>${esc(c)}</th>`).join("")}</tr><tr>${Object.values(cps).map(v => `<td>${esc(v.day_type || v.state)}<div class="muted">${v.features && v.features.nifty_from_open != null ? "Nifty " + pct1(v.features.nifty_from_open) : ""}${v.features && v.features.breadth_above_open != null ? " · breadth " + pct1(v.features.breadth_above_open) : ""}</div></td>`).join("")}</tr></table></div>` : "";
  const section = (sd) => {
    const f = d.forensics[sd.strategy] || {}, t = d.titles[sd.strategy] || {};
    const tr = d.trades.filter(x => x.strategy === sd.strategy);
    const real = tr.filter(x => !x.is_placebo), plc = tr.filter(x => x.is_placebo);
    const th = f.thought || {};
    const rows = real.map(x => `<tr class="click" data-trade="${x.id}">
        <td>${stockLink(x.symbol || x.instrument_key)}<div class="muted small">${esc((x.sector || "").slice(0, 22))}</div></td>
        <td>${sideTxt(x.side)}</td><td>${hhmm(x.entry_at)} → ${hhmm(x.exit_at)}</td>
        <td class="num">${num(x.entry_px)} → ${num(x.exit_px)}</td>
        <td class="num">${x.stop != null ? num(x.stop) : "–"} / ${x.target != null ? num(x.target) : "–"}</td>
        <td>${esc(x.exit_reason)}</td><td class="num">${inr(x.net_inr)}<div class="small">${x.net_r != null ? rr(x.net_r) : ""}</div></td>
        <td>${classPill(x.outcome_class)}</td>
        <td class="num">${x.mfe_pct != null ? `<span class="up">${pct1(x.mfe_pct)}</span> / <span class="down">${pct1(x.mae_pct)}</span>` : "–"}</td>
        <td class="small">${x.n_before ? `${x.n_before} news${x.first_news_lag_min != null ? ` · ${labLag(x.first_news_lag_min)} before` : ""}` : "–"}${x.n_after ? ` · <span class="warn-text">${x.n_after} during</span>` : ""}</td>
        <td>${x.ai_verdict ? pill(x.ai_verdict, x.ai_verdict === "PASS" ? "BULLISH" : "BEARISH") : "–"}</td></tr>`).join("");
    return `<div class="card lab-day">
      <div class="lab-card-h"><b>${esc(sd.strategy)}</b>${sd.enabled === false ? pill("OFF", "BEARISH") : ""}<span class="right">${inr(sd.net_inr)} · ${sd.trades} trades · ${sd.wins} won${sd.placebo_net_inr != null ? ` · placebo ${inr(sd.placebo_net_inr)}` : ""}</span></div>
      <div class="small muted">${esc(t.title || "")}</div>
      <div class="grid g3 lab-socha">
        <div><h3>Kya socha tha (plan)</h3><div class="small">${labThought(th, sd)}</div></div>
        <div><h3>Kya hua (result)</h3><div class="small">${labHappened(sd, real)}</div></div>
        <div><h3>Kyun (why)</h3><ul class="small reasons">${(f.why || []).map(w => `<li>${esc(w.en)}<div class="muted">${esc(w.hi)}</div></li>`).join("") || "<li>–</li>"}</ul></div>
      </div>
      ${real.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Side</th><th>Time</th><th class="num">Entry → exit</th><th class="num">Stop / target</th><th>Exit</th><th class="num">Net</th><th>Outcome</th><th class="num">Best / worst</th><th>News</th><th>AI</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
      ${plc.length ? `<div class="small muted">Placebo (random stocks, same rules): ${plc.length} trades, net ${inr(plc.reduce((a, x) => a + (x.net_inr || 0), 0))}</div>` : ""}
    </div>`;
  };
  const brief = d.forensics._BRIEF;
  body.innerHTML = picker + market + d.strategies.map(section).join("")
    + (brief ? `<div class="card"><h3>Morning brief check</h3><div class="small">${(brief.why || []).map(w => `${esc(w.en)} <span class="muted">${esc(w.hi)}</span>`).join("")}</div></div>` : "")
    + `<div class="small muted">Built ${new Date(d.built_at).toLocaleString("en-IN")} · click a trade for its full forensic and chart.</div>`;
  body.querySelectorAll("tr[data-trade]").forEach(tr => tr.onclick = (e) => { if (e.target.tagName !== "A") location.hash = `#/lab/trade/${tr.dataset.trade}`; });
  bindDate();
}
function labLag(m) { return m < 90 ? `${Math.round(m)} min` : m < 2880 ? `${(m / 60).toFixed(1)} h` : `${(m / 1440).toFixed(1)} d`; }
function bindDate() { const s = $("#labdate"); if (s) s.onchange = () => location.hash = `#/lab/today/${s.value}`; }
function labThought(th, sd) {
  const c = th.counts || {};
  const parts = [];
  if (th.regime_pre) parts.push(`Morning regime <b>${esc(th.regime_pre)}</b>${th.regime_rule ? ` <span class="muted">(${esc(th.regime_rule)})</span>` : ""}; built for ${esc(th.tool)} days.`);
  if (c.candidates != null) parts.push(`${c.candidates} candidates passed the setup, ${c.taken} taken, ${c.skips} rejected.`);
  if (c.targets != null) parts.push(`Rule: ${esc(c.rule || "")} · ${c.targets} targets, ${c.filled} filled.`);
  if (c.switched_off) parts.push("Switched off by the admin.");
  const sk = Object.entries((sd.detail || {}).skips || {}).sort((a, b) => b[1] - a[1]).slice(0, 4);
  if (sk.length) parts.push("Rejected by: " + sk.map(([k, n]) => `${esc(k)} (${n})`).join(", "));
  (th.candidates || []).slice(0, 6).forEach(x => parts.push(`${esc(x.symbol)} ${x.side > 0 ? "long" : "short"} @ ${num(x.entry)}${x.stop != null ? `, stop ${num(x.stop)}, target ${num(x.target)}` : ""}${x.plan_rrr ? `, RRR ${Number(x.plan_rrr).toFixed(1)}` : ""}`));
  return parts.map(p => `<div>${p}</div>`).join("") || "–";
}
function labHappened(sd, real) {
  const cls = Object.entries((sd.detail || {}).classes || {}).map(([k, n]) => `${classPill(k)}×${n}`).join(" ");
  return `<div>Day type <b>${esc(sd.day_type || "–")}</b> · net ${inr(sd.net_inr)}${sd.net_r != null ? ` (${rr(sd.net_r)})` : ""}</div>
    <div>Equity ₹${num(sd.equity_inr, 0)} · drawdown ${pct1(sd.drawdown)}</div><div>${cls || "no trades"}</div>
    ${sd.detail && sd.detail.best ? `<div>Best ${esc(sd.detail.best)} · worst ${esc(sd.detail.worst)}</div>` : ""}`;
}

async function labTrade(body, id) {
  const t = await api(`/api/lab/trade/${encodeURIComponent(id)}`);
  const p = t.plan || {}, path = t.path || {};
  const news = (arr, label) => (arr || []).length ? `<h3>${label}</h3>${arr.map(n => `<div class="news-item"><div class="t">${esc(n.title)}</div>
      <div class="meta">${esc(n.source)} · published ${n.published_at ? new Date(n.published_at).toLocaleString("en-IN") : "–"} · knowable ${new Date(n.knowable_at).toLocaleString("en-IN")}
      ${n.impact ? ` · ${pill(n.impact)}` : ""}${n.direction ? pill(n.direction) : ""}${n.event_type ? ` · ${esc(n.event_type)}` : ""}</div>
      ${n.summary ? `<div class="ai">${esc(n.summary)}</div>` : ""}${n.url ? `<div class="small"><a href="${esc(n.url)}" target="_blank" rel="noopener">source</a></div>` : ""}</div>`).join("")}` : "";
  const ck = p.checklist ? Object.entries(p.checklist).map(([k, v]) => `<li>${v ? "✔" : "✘"} ${esc(k)}</li>`).join("") : "";
  const ev = p.evidence ? Object.entries(p.evidence).filter(([k]) => !["mirror_of", "draw_seq"].includes(k)).slice(0, 14).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${esc(typeof v === "number" ? Number(v).toFixed(4) : JSON.stringify(v))}</td></tr>`).join("") : "";
  body.innerHTML = `<div class="controls"><button class="btn" onclick="history.back()">← back</button></div>
    <div class="grid g2">
      <div class="card"><h3>${esc(t.symbol || t.instrument_key)} · ${esc(t.strategy)} · ${esc(t.session_date)}</h3>
        <div class="small muted">${esc(t.title || "")}</div>
        <div class="big">${inr(t.net_inr)} ${t.net_r != null ? rr(t.net_r) : ""}</div>
        <div>${sideTxt(t.side)} · ${classPill(t.outcome_class)} <span class="small muted">${esc(t.outcome_rule)}</span></div>
        <div id="chart" style="height:380px;margin-top:8px"></div>
        <div class="small muted">Blue: entry · red: stop · green: target · arrows: entry and exit</div></div>
      <div class="card"><h3>Plan vs what happened</h3><table>
        <tr><td>Signal</td><td class="num">${hhmm(t.signal_at)}</td></tr>
        <tr><td>Entry</td><td class="num">${hhmm(t.entry_at)} @ ${num(t.entry_px)}</td></tr>
        <tr><td>Stop / target</td><td class="num">${t.stop != null ? num(t.stop) : "–"} / ${t.target != null ? num(t.target) : "–"}</td></tr>
        <tr><td>Exit</td><td class="num">${hhmm(t.exit_at)} @ ${num(t.exit_px)} (${esc(t.exit_reason)})</td></tr>
        <tr><td>Qty</td><td class="num">${num(t.qty, 0)}</td></tr>
        <tr><td>Best / worst move inside the trade</td><td class="num"><span class="up">${pct1(t.mfe_pct)}</span> / <span class="down">${pct1(t.mae_pct)}</span>${t.mfe_r != null ? ` (${Number(t.mfe_r).toFixed(2)}R / ${Number(t.mae_r).toFixed(2)}R)` : ""}</td></tr>
        <tr><td>Target traded after the exit</td><td class="num">${t.target_after_exit == null ? "–" : t.target_after_exit ? "yes" : "no"}</td></tr>
        <tr><td>Nifty during the trade</td><td class="num">${pct1(path.index_move)}</td></tr>
        <tr><td>Regime / day type</td><td class="num">${esc(t.regime_state || "–")} / ${esc(t.day_type || "–")}</td></tr>
        <tr><td>AI reviewer (P2)</td><td class="num">${esc(t.ai_verdict || "–")}${p.ai_reasons && p.ai_reasons.length ? " · " + esc(p.ai_reasons.join(", ")) : ""}</td></tr>
        <tr><td>News before the signal</td><td class="num">${(t.news_before || []).length}${t.first_news_lag_min != null ? ` · latest ${labLag(t.first_news_lag_min)} before` : ""}</td></tr>
        ${p.rrr ? `<tr><td>Planned reward/risk</td><td class="num">${Number(p.rrr).toFixed(2)}</td></tr>` : ""}
        ${p.rank ? `<tr><td>Rank / score</td><td class="num">${p.rank} / ${p.score != null ? Number(p.score).toFixed(4) : "–"}</td></tr>` : ""}
        ${p.prob_up != null ? `<tr><td>Model P(up) / exp. return</td><td class="num">${pct1(p.prob_up)} / ${pct1(p.exp_return)}</td></tr>` : ""}
      </table>
      ${ck ? `<h3>Checklist (${p.checklist_score}/6)</h3><ul class="small reasons">${ck}</ul>` : ""}
      ${ev ? `<h3>Signal facts</h3><table class="small">${ev}</table>` : ""}
      ${p.ai_note ? `<h3>AI note</h3><div class="small">${esc(p.ai_note)}</div>` : ""}</div>
    </div>
    <div class="card">${news(t.news_before, "News before the signal") || '<div class="muted small">No linked news in the 48 h before the signal.</div>'}${news(t.news_after, "News that arrived during the trade")}</div>`;
  const el = $("#chart");
  if (!el || !window.LightweightCharts || !t.candles.length) return;
  if (labChart) { labChart.remove(); labChart = null; }
  labChart = LightweightCharts.createChart(el, { layout: { background: { color: "#171e26" }, textColor: "#8b98a5" },
    grid: { vertLines: { color: "#222c37" }, horzLines: { color: "#222c37" } }, timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: "#2a3542" }, crosshair: { mode: 1 } });
  const cs = labChart.addCandlestickSeries({ upColor: "#2ec27e", downColor: "#f2545b", wickUpColor: "#2ec27e", wickDownColor: "#f2545b", borderVisible: false });
  cs.setData(t.candles.filter(b => b.open != null));
  const line = (px, color, title) => px != null && cs.createPriceLine({ price: Number(px), color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title });
  line(t.entry_px, "#4f9dff", "entry"); line(t.stop, "#f2545b", "stop"); line(t.target, "#2ec27e", "target");
  const off = t.chart_offset_s || 0, mk = [];
  const near = (iso) => { const s = Math.floor(new Date(iso).getTime() / 1000) + off; let best = null;
    for (const b of t.candles) { if (b.time <= s) best = b.time; } return best; };
  if (t.entry_at) mk.push({ time: near(t.entry_at), position: t.side > 0 ? "belowBar" : "aboveBar", color: "#4f9dff", shape: t.side > 0 ? "arrowUp" : "arrowDown", text: "entry" });
  if (t.exit_at) mk.push({ time: near(t.exit_at), position: t.side > 0 ? "aboveBar" : "belowBar", color: "#f5a524", shape: t.side > 0 ? "arrowDown" : "arrowUp", text: "exit" });
  cs.setMarkers(mk.filter(m => m.time != null).sort((a, b) => a.time - b.time));
  labChart.timeScale().fitContent();
}

async function labRegime(body) {
  const r = await api("/api/lab/regime");
  const strategies = [...new Set(r.cells.map(c => c.strategy))];
  const grid = (axis) => {
    const vals = [...new Set(r.cells.filter(c => c.axis === axis).map(c => c.value))].sort();
    const cell = (s, v) => { const c = r.cells.find(x => x.strategy === s && x.axis === axis && x.value === v);
      if (!c) return '<td class="muted">–</td>';
      const tone = c.avg_net_inr > 0 ? "rgba(46,194,126,.18)" : "rgba(242,84,91,.18)";
      return `<td class="num" style="background:${c.too_few ? "transparent" : tone}">${inr(c.avg_net_inr)}<div class="small muted">${c.trades} trades · hit ${pct1(c.hit_rate)}${c.avg_r != null ? ` · ${rr(c.avg_r)}` : ""}</div>${c.too_few ? '<div class="small warn-text">too few</div>' : c.ci95_avg_net ? `<div class="small muted">95% ${inr(c.ci95_avg_net[0])}…${inr(c.ci95_avg_net[1])}</div>` : ""}</td>`; };
    return `<div class="tablewrap"><table><thead><tr><th>Strategy</th>${vals.map(v => `<th class="num">${esc(v)}</th>`).join("")}</tr></thead>
      <tbody>${strategies.map(s => `<tr><td>${esc(s)}</td>${vals.map(v => cell(s, v)).join("")}</tr>`).join("")}</tbody></table></div>`;
  };
  body.innerHTML = r.cells.length ? `<div class="card small muted">${esc(r.note)} Average net per trade; colour only when ≥ ${r.few} trades. Paper and E5 trades use the day's P1 regime.</div>
    <h2>By morning regime</h2><div class="card">${grid("regime")}</div>
    <h2>By realised day type</h2><div class="card">${grid("day_type")}</div>` : '<div class="card muted">No trades yet.</div>';
}

async function labHistory(body, strategy) {
  const o = await api("/api/lab/overview");
  strategy = strategy || (o.strategies[0] || {}).strategy;
  const h = await api(`/api/lab/history/${encodeURIComponent(strategy)}`);
  const sel = `<div class="controls"><select id="labstrat">${o.strategies.map(s => `<option ${s.strategy === strategy ? "selected" : ""}>${esc(s.strategy)}</option>`).join("")}</select>
    <button class="btn" id="labcsv">Download CSV</button></div>`;
  const s = o.strategies.find(x => x.strategy === strategy) || { curve: [] };
  body.innerHTML = sel + `<div class="card"><h3>Equity · ${esc(strategy)}</h3>${spark(s.curve)}</div>
    <div class="card"><div class="tablewrap"><table><thead><tr><th>Session</th><th class="num">Trades</th><th class="num">Won</th><th class="num">Net</th><th class="num">R</th><th class="num">Placebo</th><th>Regime</th><th>Day</th><th class="num">Equity</th><th class="num">DD</th><th>Outcomes</th></tr></thead>
    <tbody>${h.map(x => `<tr class="click" onclick="location.hash='#/lab/today/${x.session_date}'"><td>${esc(x.session_date)}</td><td class="num">${x.trades}</td><td class="num">${x.wins}</td><td class="num">${inr(x.net_inr)}</td><td class="num">${x.net_r != null ? rr(x.net_r) : "–"}</td><td class="num">${x.placebo_net_inr != null ? inr(x.placebo_net_inr) : "–"}</td><td>${esc(x.regime_pre || "–")}</td><td>${esc(x.day_type || "–")}</td><td class="num">${num(x.equity_inr, 0)}</td><td class="num">${pct1(x.drawdown)}</td><td class="small">${Object.entries((x.detail || {}).classes || {}).map(([k, n]) => `${esc(k)}×${n}`).join(" ")}</td></tr>`).join("")}</tbody></table></div></div>`;
  $("#labstrat").onchange = (e) => location.hash = `#/lab/history/${encodeURIComponent(e.target.value)}`;
  $("#labcsv").onclick = () => {
    const cols = ["session_date", "trades", "wins", "losses", "net_inr", "net_r", "placebo_net_inr", "regime_pre", "day_type", "equity_inr", "drawdown"];
    const csv = [cols.join(",")].concat(h.map(x => cols.map(c => x[c] ?? "").join(","))).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${strategy}_history.csv`; a.click();
  };
}

async function labBrief(body, date) {
  const b = await api(`/api/lab/brief${date ? `?date=${encodeURIComponent(date)}` : ""}`);
  const g = b.previous_grade;
  const gradeHtml = g ? `<div class="card"><h3>Previous brief (${esc(g.date)}) · how it did</h3><div class="small">${(g.why || []).map(w => `${esc(w.en)} <span class="muted">${esc(w.hi)}</span>`).join("")}</div>
      <div class="tablewrap"><table class="small"><tr><th>Stock</th><th>Setup</th><th>Side</th><th>Triggered</th><th class="num">Open→close</th><th>Right way</th></tr>
      ${(g.happened.grades || []).map(x => `<tr><td>${esc(x.symbol)}</td><td>${esc(x.strategy)}</td><td>${sideTxt(x.side)}</td><td>${x.triggered ? "yes" : "no"}</td><td class="num">${pct1(x.open_to_close)}</td><td>${x.right_way == null ? "–" : x.right_way ? '<span class="up">yes</span>' : '<span class="down">no</span>'}</td></tr>`).join("")}</table></div></div>` : "";
  if (!b.available) { body.innerHTML = `<div class="card muted">No brief for ${esc(b.date)} yet (built at 08:30, updated 09:10 on trading days).</div>` + gradeHtml; return; }
  const rg = b.regime || {}, ev = b.events || {}, c = b.candidates || {};
  const cand = (x) => `<div class="card plan"><div class="lab-card-h"><b>${stockLink(x.symbol)}</b>${sideTxt(x.side)}<span class="right small muted">${esc(x.sector || "")}</span></div>
      <div class="small">Close ₹${num(x.close)} · ADX ${x.adx14 != null ? Number(x.adx14).toFixed(0) : "–"} · ATR ${pct1(x.atr_pct)} · RSI ${x.rsi14 != null ? Number(x.rsi14).toFixed(0) : "–"}${x.zone ? ` · zone ₹${num(x.zone)} (${pct1(x.zone_dist)})` : ""}</div>
      <ul class="small reasons">${(x.why || []).map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      <div class="small"><b>Trigger:</b> ${esc(x.trigger)}</div><div class="small"><b>Invalidate:</b> ${esc(x.invalidate)}</div></div>`;
  body.innerHTML = `<div class="card warn-box small">${esc(b.disclaimer)}</div>
    <div class="grid g3">
      <div class="card"><h3>Today's regime (P1 engine)</h3><div class="big">${pill(rg.state)}</div><div class="small muted">${esc(rg.rule || "")}</div>
        <div class="small">${esc(rg.note || "")}</div><div class="small muted">ADX ${rg.features && rg.features.nifty_adx14 != null ? Number(rg.features.nifty_adx14).toFixed(0) : "–"} · VIX ${rg.features ? num(rg.features.vix_close) : "–"} (pct ${rg.features ? pct1(rg.features.vix_pct252) : "–"}) · Nifty yesterday ${rg.features ? pct1(rg.features.nifty_ret_1d) : "–"}</div></div>
      <div class="card"><h3>Events</h3><div class="small">${(ev.calendar || []).map(x => pill(x, "NEUTRAL")).join("") || "no macro event"}</div>
        <div class="small"><b>Results today</b> (excluded): ${(ev.results_today || []).map(esc).join(", ") || "none"}</div>
        <div class="small"><b>Corporate actions</b>: ${(ev.corporate_actions || []).map(x => `${esc(x.symbol)} ${esc(x.type)}`).join(", ") || "none"}</div></div>
      <div class="card"><h3>E5 model picks (09:06)</h3>${(c.E5 || []).length ? `<table class="small">${c.E5.map(x => `<tr><td>${esc(x.trading_symbol)}</td><td class="num">P(up) ${pct1(x.prob_up)}</td><td class="num">exp ${pct1(x.exp_return)}</td></tr>`).join("")}</table>` : '<div class="small muted">not made yet (09:06) or no pick today</div>'}
        <div class="small muted" style="margin-top:6px">Gap fade: ${esc(c.gap_fade || "")}</div></div>
    </div>
    <h2>S1 breakout watchlist <small>trend setups${rg.tools && rg.tools.S1 ? "" : " · today's regime does not favour S1"}</small></h2><div class="grid g3">${(c.S1 || []).map(cand).join("") || '<div class="muted">none</div>'}</div>
    <h2>S2 mean-reversion watchlist <small>near support / resistance${rg.tools && rg.tools.S2 ? "" : " · today's regime does not favour S2"}</small></h2><div class="grid g3">${(c.S2 || []).map(cand).join("") || '<div class="muted">none</div>'}</div>
    <h2>High-impact news (24 h)</h2><div class="card">${(b.news || []).map(n => `<div class="news-item"><div class="t">${esc(n.symbol || "")} · ${esc(n.title)}</div><div class="meta">${esc(n.source)} · ${new Date(n.knowable_at).toLocaleString("en-IN")} ${n.direction ? pill(n.direction) : ""}</div>${n.summary ? `<div class="ai">${esc(n.summary)}</div>` : ""}</div>`).join("") || '<div class="muted small">none</div>'}</div>`
    + gradeHtml;
}

async function labHealth(body) {
  const h = await api("/api/lab/health");
  const sw = await api("/api/lab/switches");
  const row = (k, v) => `<tr><td>${esc(k)}</td><td class="num">${v == null ? '<span class="down">never</span>' : esc(typeof v === "string" && v.includes("T") ? new Date(v).toLocaleString("en-IN") : JSON.stringify(v))}</td></tr>`;
  body.innerHTML = `<div class="grid g2"><div class="card"><h3>Jobs (last success)</h3><table>${Object.entries(h).map(([k, v]) => row(k, v)).join("")}</table></div>
    <div class="card"><h3>Switch log</h3><table class="small"><tr><th>When</th><th>Strategy</th><th>State</th><th>Reason</th></tr>
    ${sw.history.map(x => `<tr><td>${new Date(x.at).toLocaleString("en-IN")}</td><td>${esc(x.strategy)}</td><td>${x.enabled ? "ON" : "OFF"}</td><td>${esc(x.reason)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">no switch yet</td></tr>'}</table></div></div>`;
}
