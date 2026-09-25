/* Contract test: the fixtures (typed with src/types/api.ts) must satisfy the
   read API's OpenAPI document (mocks/openapi.json, dumped from
   backend/app/readapi). A field renamed or removed in the backend fails here. */
import { describe, expect, it } from "vitest";
import * as F from "../../mocks/fixtures";
import openapi from "../../mocks/openapi.json";

type Schema = { properties?: Record<string, unknown>; required?: string[] };
const schemas = (openapi as { components: { schemas: Record<string, Schema> } }).components.schemas;

function check(name: string, obj: object) {
  const s = schemas[name];
  expect(s, `schema ${name} exists`).toBeDefined();
  const props = Object.keys(s?.properties ?? {});
  for (const k of Object.keys(obj)) expect(props, `${name}.${k} is in the contract`).toContain(k);
  for (const r of s?.required ?? []) expect(Object.keys(obj), `${name}.${r} is present`).toContain(r);
}

describe("fixtures match the read-API contract", () => {
  it.each([
    ["Instrument", F.instruments[0]], ["SearchHit", F.searchHits[0]], ["LatestPrice", F.latest[0]],
    ["MarketSession", F.session], ["Candle", F.candles("1d").candles[0]], ["CandleSeries", F.candles("1d")],
    ["Quote", F.quote], ["Profile", F.profile], ["Fundamental", F.fundamentals[0]],
    ["CorporateAction", F.corporateActions[0]], ["NewsItem", F.news[0]], ["SectorCount", F.sectors[0]],
    ["GlobalInstrument", F.global[0]], ["GlobalBar", F.globalBars[0]], ["GlobalLabel", F.globalLabels[0]],
    ["Freshness", F.freshness[0]], ["Quality", F.quality],
  ])("%s", (name, obj) => check(name as string, obj as object));

  it("every endpoint the clients call exists in the contract", () => {
    const paths = Object.keys((openapi as { paths: Record<string, unknown> }).paths);
    for (const p of ["/v1/market/session", "/v1/latest", "/v1/instruments", "/v1/search",
      "/v1/instruments/{instrument_key}/profile", "/v1/instruments/{instrument_key}/candles",
      "/v1/instruments/{instrument_key}/quote", "/v1/instruments/{instrument_key}/fundamentals",
      "/v1/instruments/{instrument_key}/corporate-actions", "/v1/instruments/{instrument_key}/quality",
      "/v1/news", "/v1/sectors", "/v1/global", "/v1/global/{instrument_key}/candles",
      "/v1/global/{instrument_key}/finality", "/v1/freshness", "/v1/pipeline/status", "/v1/acceptance"]) {
      expect(paths).toContain(p);
    }
  });
});
