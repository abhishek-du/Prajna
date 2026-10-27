// Research Desk views (user 2026-10-27). LLM-led research suggestions; paper only, never advice.
// Uses app.js helpers (esc, num, api, view, pill, stockLink) and lab.js (inr, pct1, hhmm).
"use strict";
const DESK_TABS = [["board", "Watchlist & live"], ["all", "All verdicts"], ["log", "Watchlist log"], ["accuracy", "Accuracy"]];
const DEC_TONE = { STRONG_BUY: "BULLISH", BUY: "BULLISH", WATCH: "NEUTRAL", AVOID: "BEARISH", SELL: "BEARISH" };
const decPill = (d) => d ? `<span class="pill ${DEC_TONE[d] || ""}"><b>${esc(d)}</b></span>` : "";
const scoreBar = (x) => x == null ? "–" : `<div class="scorebar"><i style="width:${x}%;background:${x >= 70 ? "var(--up)" : x >= 50 ? "var(--warn)" : "var(--down)"}"></i><span>${x}</span></div>`;

function deskNav(cur) {
  return `<div class="controls labtabs">${DESK_TABS.map(([k, t]) =>
    `<button class="${k === cur ? "on" : ""}" onclick="location.hash='#/desk/${k}'">${t}</button>`).join("")}</div>`;
}

async function deskView(sub, arg) {
  sub = sub || "board";
  view.innerHTML = `<h2>Research Desk <small>LLM-led investigation · rules shown alongside · paper only</small></h2>${deskNav(sub === "stock" ? "" : sub)}<div id="deskbody" class="loading">Loading…</div>`;
  const body = $("#deskbody");
  try {
    if (sub === "board") await deskBoard(body);
    else if (sub === "all") await deskAll(body, arg);
    else if (sub === "stock") await deskStock(body, arg);
    else if (sub === "log") await deskLog(body);
    else if (sub === "accuracy") await deskAccuracy(body);
    body.classList.remove("loading");
  } catch (e) { body.innerHTML = `<div class="card down">Could not load: ${esc(e.message)}</div>`; }
}

function stateOf(r) {
  const ks = new Set((r.events || []).map(e => e.kind));
  if (ks.has("STOP")) return pill("STOPPED", "BEARISH");
  if (ks.has("T2")) return pill("T2 HIT", "BULLISH");
  if (ks.has("T1")) return pill("T1 HIT", "BULLISH");
  if (ks.has("INVALIDATED")) return pill("INVALIDATED", "BEARISH");
  if (ks.has("EXPIRED")) return pill("EXPIRED", "NEUTRAL");
  if (ks.has("ENTRY_TRIGGERED")) return pill("IN TRADE", "NEUTRAL");
  return pill("WAITING ENTRY", "");
}
const away = (p, lvl) => p == null || lvl == null ? "" : `<div class="small muted">${((lvl / p - 1) * 100).toFixed(1)}%</div>`;

async function deskBoard(body) {
  const w = await api("/api/desk/watch");
  const rows = w.watchlist.map(r => {
    const p = r.live ? r.live.ltp : null;
    return `<tr class="click" data-sym="${esc(r.symbol)}">
      <td><b>${esc(r.symbol)}</b><div class="small muted">added ${r.added_at ? new Date(r.added_at).toLocaleString("en-IN") : "–"}</div></td>
      <td>${decPill(r.decision)}<div class="small muted">${esc(r.horizon || "")}</div></td><td>${scoreBar(r.score)}</td>
      <td class="num">${p == null ? "–" : num(p)}<div class="small">${r.live && r.live.change != null ? pct(r.live.change) : ""}</div></td>
      <td class="num">${num(r.entry_lo)} – ${num(r.entry_hi)}${away(p, r.entry_hi)}</td>
      <td class="num down">${num(r.stop)}${away(p, r.stop)}</td><td class="num up">${num(r.t1)}${away(p, r.t1)}</td><td class="num up">${num(r.t2)}${away(p, r.t2)}</td>
      <td>${stateOf(r)}<div class="small muted">${(r.events || []).map(e => `${esc(e.kind)} ${hhmm(e.at)} @${num(e.price)}`).join(" · ")}</div></td></tr>`;
  }).join("");
  body.innerHTML = `<div class="card warn-box small">${esc(w.disclaimer)} Stocks join automatically at score ≥ ${w.add_score} with a BUY decision and leave below ${w.remove_score}, on AVOID/SELL, at the stop, at T2, on invalidation or when stale.</div>
    <div class="card"><h3>Watchlist (${w.watchlist.length}) · live ${esc(w.live_status.status)} ${w.live_status.fetched_at ? new Date(w.live_status.fetched_at).toLocaleTimeString("en-IN") : ""}</h3>
    ${w.watchlist.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Call</th><th>Score</th><th class="num">Live</th><th class="num">Entry zone</th><th class="num">Stop</th><th class="num">T1</th><th class="num">T2</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="muted">The watchlist is empty: no stock has a BUY verdict with a high enough score yet (the desk runs at 19:45, 08:40, 11:00 and 13:30).</div>'}</div>`;
  body.querySelectorAll("tr[data-sym]").forEach(tr => tr.onclick = () => location.hash = `#/desk/stock/${encodeURIComponent(tr.dataset.sym)}`);
  every(30000, () => deskView("board"));
}

async function deskAll(body, decision) {
  const d = await api(`/api/desk/verdicts${decision ? `?decision=${encodeURIComponent(decision)}` : ""}`);
  const run = d.run || {};
  const filt = `<div class="controls">${["", "STRONG_BUY", "BUY", "WATCH", "AVOID", "SELL"].map(x =>
    `<button class="${(decision || "") === x ? "on" : ""}" onclick="location.hash='#/desk/all/${x}'">${x || "All"} ${x ? `(${d.mix[x] || 0})` : ""}</button>`).join("")}</div>`;
  body.innerHTML = filt + `<div class="small muted">Last run: ${esc(run.kind || "–")} ${esc(run.session_date || "")} · ${run.created_at ? new Date(run.created_at).toLocaleString("en-IN") : ""} · ${run.counts ? `${run.counts.investigated} investigated, ${run.counts.conflicts} override the rules` : ""}</div>
    <div class="card"><div class="tablewrap" style="max-height:none"><table><thead><tr><th>Stock</th><th>Call</th><th>Score</th><th>Why it moved</th><th class="num">Entry</th><th class="num">Stop</th><th class="num">T1 / T2</th><th>Rules</th></tr></thead><tbody>
    ${d.verdicts.map(v => `<tr class="click" data-sym="${esc(v.symbol)}"><td><b>${esc(v.symbol)}</b></td><td>${decPill(v.decision || v.status)}</td><td>${scoreBar(v.score)}</td>
      <td class="small" style="white-space:normal;max-width:420px">${pill(v.driver || "", "NEUTRAL")} ${esc((v.why || "").slice(0, 160))}</td>
      <td class="num">${v.entry_lo != null ? `${num(v.entry_lo)}–${num(v.entry_hi)}` : "–"}</td><td class="num">${num(v.stop)}</td><td class="num">${v.t1 != null ? `${num(v.t1)} / ${num(v.t2)}` : "–"}</td>
      <td class="small">${decPill(v.rule_decision)}${(v.conflicts || []).length ? `<div class="down">override: ${esc(v.conflicts.join(", "))}</div>` : ""}<div class="muted">${esc((v.rule_flags || []).join(" "))}</div></td></tr>`).join("")}
    </tbody></table></div></div>`;
  body.querySelectorAll("tr[data-sym]").forEach(tr => tr.onclick = () => location.hash = `#/desk/stock/${encodeURIComponent(tr.dataset.sym)}`);
}

async function deskStock(body, sym) {
  const d = await api(`/api/desk/stock/${encodeURIComponent(sym)}`);
  const v = d.verdict, p = d.dossier || {}, ev = p.evidence || {}, px = ev.px || {}, at = ev.attr || {}, rule = ev.rule || {};
  const pov = v.pov || {};
  const lb = v.levels_basis || {};
  const bar = (k, label) => `<div class="povrow"><span>${label}</span>${scoreBar(pov[k])}</div>`;
  const news = (ev.news || []).map(n => `<div class="news-item"><div class="t">${(v.evidence_ids || []).includes(n.id) ? "★ " : ""}${esc(n.title)}</div>
    <div class="meta">${esc(n.id)} · ${esc(n.source)} · ${esc(n.published_at)} · ${n.hours_before_last_close != null ? `${n.hours_before_last_close} h before the last close` : ""} ${n.impact ? pill(n.impact) : ""}${n.direction ? pill(n.direction) : ""}${n.event_type ? " · " + esc(n.event_type) : ""}</div>
    ${n.summary ? `<div class="ai">${esc(n.summary)}</div>` : ""}${n.url ? `<div class="small"><a href="${esc(n.url)}" target="_blank" rel="noopener">source</a></div>` : ""}</div>`).join("");
  const attrBar = () => { const parts = [["market", at.market_part], ["sector", at.sector_part], ["stock-specific", at.stock_part]];
    return parts.map(([n, x]) => `<div class="povrow"><span>${n}</span><span class="${x > 0 ? "up" : x < 0 ? "down" : ""}">${x == null ? "–" : (x * 100).toFixed(2) + "%"}</span></div>`).join(""); };
  body.innerHTML = `<div class="controls"><button class="btn" onclick="history.back()">← back</button> <a class="btn" href="#/stock/${encodeURIComponent(sym)}">stock page</a></div>
  <div class="card warn-box small">${esc(d.disclaimer)}</div>
  <div class="grid g3">
    <div class="card"><h3>${esc(v.symbol)} · ${esc(v.kind)} ${esc(v.session_date)}</h3>
      <div>${decPill(v.decision || v.status)} ${scoreBar(v.score)}</div>
      <div class="small muted">${esc(v.horizon || "")} · ${d.on_watchlist ? '<span class="up">on the watchlist</span>' : "not on the watchlist"} · ${new Date(v.created_at).toLocaleString("en-IN")}</div>
      ${v.status !== "OK" ? `<div class="down small">${esc(v.status)}: ${esc(v.invalid_reason || "")}</div>` : ""}
      <h3 style="margin-top:10px">Plan (LLM)</h3>
      <table class="small"><tr><td>Entry</td><td class="num">${v.entry_lo != null ? `${num(v.entry_lo)} – ${num(v.entry_hi)}` : "–"}</td><td class="muted">${esc(lb.entry || "")}</td></tr>
      <tr><td>Stop</td><td class="num down">${num(v.stop)}</td><td class="muted">${esc(lb.stop || "")}</td></tr>
      <tr><td>T1 / T2</td><td class="num up">${num(v.t1)} / ${num(v.t2)}</td><td class="muted">${esc(lb.targets || "")}</td></tr></table>
      ${d.live ? `<div class="small">Live ${num(d.live.ltp)} ${pct(d.live.change)}</div>` : ""}</div>
    <div class="card"><h3>Six viewpoints</h3>${bar("technical", "Technical")}${bar("catalyst", "News / catalyst")}${bar("fundamental", "Fundamentals")}${bar("market", "Market / sector")}${bar("execution", "Liquidity / execution")}${bar("risk", "Risk (100 = low)")}</div>
    <div class="card"><h3>Why it moved · ${pill((v.why_moved || {}).driver || "", "NEUTRAL")}</h3><div class="small">${esc((v.why_moved || {}).summary || "")}</div>
      <h3 style="margin-top:8px">Move split (last bar ${pct1(at.ret)})</h3>${attrBar()}<div class="small muted">beta ${at.beta_60 ?? "–"} · Nifty ${pct1(at.nifty_ret)} · sector ${pct1(at.sector_ret)}</div></div>
  </div>
  <div class="grid g2">
    <div class="card"><h3>Thesis</h3><div class="small">${esc(v.thesis || "")}</div>
      <h3>Risks</h3><ul class="small reasons">${(v.risks || []).map(r => `<li>${esc(r)}</li>`).join("")}</ul>
      <h3>Invalidation</h3><div class="small">${esc(v.invalidation || "")}</div>
      ${lb.rule_disagreement ? `<h3>Where the LLM disagrees with the rules</h3><div class="small">${esc(lb.rule_disagreement)}</div>` : ""}</div>
    <div class="card"><h3>Rule judge (${esc(rule.version || "")}) · ${decPill(v.rule_decision)}</h3>
      ${(v.conflicts || []).length ? `<div class="down small"><b>LLM overrides the rules:</b> ${esc(v.conflicts.join(", "))}</div>` : '<div class="small up">No conflict with the rules.</div>'}
      <ul class="small reasons">${(rule.notes || []).map(n => `<li>${esc(n)}</li>`).join("") || "<li>no rule flag</li>"}</ul>
      ${rule.cost ? `<div class="small">Reward/risk to T1 (rule plan): gross ${rule.cost.gross_rrr_t1}, net of costs ${rule.cost.net_rrr_t1}; with 5/10/20 bps slippage ${Object.values(rule.cost.slippage_scenarios_bps).join(" / ")}</div>` : ""}
      <h3>Price facts</h3><div class="small">Close ${num(px.close)} · 1d ${pct1(px.ret_1d)} · 5d ${pct1(px.ret_5d)} · 20d ${pct1(px.ret_20d)} · gap ${pct1(px.gap)} · volume ×${px.volume_x20 != null ? Number(px.volume_x20).toFixed(1) : "–"} · RSI ${px.rsi_14 != null ? Number(px.rsi_14).toFixed(0) : "–"} · ATR ${pct1(px.atr_pct)} · vs 20/50/200-day ${pct1(px.close_to_sma_20)} / ${pct1(px.close_to_sma_50)} / ${pct1(px.close_to_sma_200)}</div>
      <div class="small muted">Execution: turnover ₹${ev.exec && ev.exec.median_turnover ? num(ev.exec.median_turnover / 1e7, 1) + " cr" : "–"} · circuit ${ev.exec ? `${num(ev.exec.lower_circuit)} – ${num(ev.exec.upper_circuit)}` : "–"}</div></div>
  </div>
  <div class="card"><h3>News timeline (★ = cited by the LLM)</h3>${news || '<div class="small muted">No linked news in the window.</div>'}
    ${(ev.res || []).length ? `<h3>Results</h3><div class="small">${ev.res.map(r => `${esc(r.id)} ${esc(r.kind)} ${esc(r.meeting_date)} ${esc(r.verdict || "")}`).join("<br>")}</div>` : ""}
    ${(ev.ca || []).length ? `<h3>Corporate actions</h3><div class="small">${ev.ca.map(r => `${esc(r.type)} ex ${esc(r.ex_date)}`).join(", ")}</div>` : ""}</div>
  <div class="grid g2">
    <div class="card"><h3>Live tracking</h3>${d.tracks.length ? `<table class="small">${d.tracks.map(t => `<tr><td>${esc(t.kind)}</td><td class="num">${num(t.price)}</td><td>${new Date(t.at).toLocaleString("en-IN")}</td></tr>`).join("")}</table>` : '<div class="small muted">no tracking event yet</div>'}
      <h3>Watchlist log</h3>${d.watch_log.length ? `<table class="small">${d.watch_log.map(w => `<tr><td>${esc(w.event)}</td><td>${esc(w.reason)}</td><td>${new Date(w.created_at).toLocaleString("en-IN")}</td></tr>`).join("")}</table>` : '<div class="small muted">never on the watchlist</div>'}</div>
    <div class="card"><h3>Earlier verdicts</h3>${d.history.length ? `<table class="small">${d.history.map(h => `<tr><td>${esc(h.session_date)} ${esc(h.kind)}</td><td>${decPill(h.decision || h.status)}</td><td>${h.score ?? "–"}</td></tr>`).join("")}</table>` : '<div class="small muted">first verdict</div>'}</div>
  </div>`;
}

async function deskLog(body) {
  const l = await api("/api/desk/log");
  body.innerHTML = `<div class="card"><div class="tablewrap" style="max-height:none"><table><thead><tr><th>When</th><th>Stock</th><th>Event</th><th>Reason</th><th>Score</th></tr></thead><tbody>
  ${l.map(x => `<tr class="click" data-sym="${esc(x.symbol)}"><td>${new Date(x.created_at).toLocaleString("en-IN")}</td><td><b>${esc(x.symbol)}</b></td><td>${pill(x.event, x.event === "ADD" ? "BULLISH" : x.event === "REMOVE" ? "BEARISH" : "")}</td><td class="small">${esc(x.reason)}</td><td>${x.score ?? ""}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">no watchlist event yet</td></tr>'}</tbody></table></div></div>`;
  body.querySelectorAll("tr[data-sym]").forEach(tr => tr.onclick = () => location.hash = `#/desk/stock/${encodeURIComponent(tr.dataset.sym)}`);
}

async function deskAccuracy(body) {
  const a = await api("/api/desk/accuracy");
  const cols = ["added", "ENTRY_TRIGGERED", "T1", "T2", "STOP", "INVALIDATED", "EXPIRED"];
  body.innerHTML = `<div class="card small muted">${esc(a.note)} Profit/loss per suggestion: Strategy Lab → desk_llm_v1.</div>
  <div class="card"><table><thead><tr><th>Score bucket</th>${cols.map(c => `<th class="num">${c}</th>`).join("")}</tr></thead><tbody>
  ${Object.entries(a.buckets).map(([b, v]) => `<tr><td>${esc(b)}</td>${cols.map(c => `<td class="num">${v[c] || 0}</td>`).join("")}</tr>`).join("") || '<tr><td colspan="8" class="muted">no suggestion has reached the watchlist yet</td></tr>'}</tbody></table></div>`;
}
