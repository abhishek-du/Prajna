import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { handlers } from "../mocks/handlers";

export const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});
afterAll(() => server.close());

// jsdom has no canvas: the chart library is replaced by a marker that reports
// what it would draw (the real chart is exercised by the Playwright E2E test).
vi.mock("./components/charts/CandlestickChart", () => ({
  CandlestickChart: ({ candles }: { candles: unknown[] }) => (
    <div data-testid="candle-chart">{candles.length} bars</div>
  ),
}));

class RO { observe() {} unobserve() {} disconnect() {} }
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (RO as unknown as typeof ResizeObserver);
