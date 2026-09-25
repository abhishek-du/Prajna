/* MSW handlers for tests only. */
import { http, HttpResponse, type JsonBodyType } from "msw";
import * as F from "./fixtures";

const j = (d: unknown) => HttpResponse.json(d as JsonBodyType);
export const BASE = "http://localhost/v1";

export const handlers = [
  http.get(`${BASE}/market/session`, () => j(F.env(F.session, false))),
  http.get(`${BASE}/instruments`, ({ request }) => {
    const seg = new URL(request.url).searchParams.get("segment");
    const rows = seg === "NSE_INDEX" ? F.indices : F.instruments;
    return j(F.env(rows, false, rows.length));
  }),
  http.get(`${BASE}/search`, ({ request }) => {
    const q = (new URL(request.url).searchParams.get("q") ?? "").toUpperCase();
    return j(F.env(F.searchHits.filter((h) => h.trading_symbol.startsWith(q)), false));
  }),
  http.get(`${BASE}/latest`, ({ request }) => {
    const keys = (new URL(request.url).searchParams.get("keys") ?? "").split(",");
    return j(F.env(F.latest.filter((p) => keys.includes(p.instrument_key))));
  }),
  http.get(`${BASE}/instruments/:key/profile`, () => j(F.env(F.profile))),
  http.get(`${BASE}/instruments/:key/quote`, () => j(F.env(F.quote))),
  http.get(`${BASE}/instruments/:key/candles`, ({ request }) => {
    const tf = new URL(request.url).searchParams.get("timeframe");
    return tf === "1h" || tf === "1d" ? j(F.env(F.candles(tf))) : j(F.env({ ...F.candles("1d"), timeframe: tf, candles: [] }));
  }),
  http.get(`${BASE}/instruments/:key/fundamentals`, () => j(F.env(F.fundamentals))),
  http.get(`${BASE}/instruments/:key/corporate-actions`, () => j(F.env(F.corporateActions))),
  http.get(`${BASE}/instruments/:key/quality`, () => j(F.env(F.quality, false))),
  http.get(`${BASE}/news`, () => j(F.env(F.news))),
  http.get(`${BASE}/sectors`, () => j(F.env(F.sectors, false))),
  http.get(`${BASE}/global`, () => j(F.env(F.global))),
  http.get(`${BASE}/global/:key/candles`, () => j(F.env(F.globalBars))),
  http.get(`${BASE}/global/:key/finality`, () => j(F.env(F.globalLabels, false))),
  http.get(`${BASE}/freshness`, () => j(F.env(F.freshness, false))),
  http.get(`${BASE}/pipeline/status`, () => j(F.env(F.pipeline, false))),
  http.get(`${BASE}/acceptance`, () => j(F.env(F.acceptance, false))),
];
