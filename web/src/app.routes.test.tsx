import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderRoute } from "./test-utils";

const ROUTES: [string, RegExp][] = [
  ["/overview", /^Overview$/],
  ["/markets", /^Markets$/],
  ["/stocks", /^Stocks$/],
  ["/stocks/NSE_EQ%7CINE002A01018", /RELIANCE INDUSTRIES LTD/],
  ["/sectors", /^Sectors$/],
  ["/sectors/Refineries", /^Refineries$/],
  ["/global", /^Global markets$/],
  ["/news", /^News$/],
  ["/watchlist", /^Watchlist$/],
  ["/data-quality", /^Data quality$/],
  ["/operations", /^Operations$/],
  ["/operations/acceptance", /^Acceptance status$/],
  ["/nope", /^Page not found$/],
];

// Stage 3 vocabulary that must never appear in this client (spec §37)
const FORBIDDEN = /\b(BUY|SELL|LONG|SHORT|ENTRY|EXIT|TARGET|STOP[ -]LOSS|SIGNAL SCORE|AI SIGNAL|PREDICTION|PROBABILITY)\b/i;

describe("every route", () => {
  it.each(ROUTES)("%s loads its screen", async (path, heading) => {
    renderRoute(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it.each(ROUTES)("%s never shows Stage 3 wording, a LIVE claim or a credential", async (path, heading) => {
    const { container } = renderRoute(path);
    await screen.findByRole("heading", { level: 1, name: heading });
    await waitFor(() => expect(container.querySelector('[role="status"][aria-label="Loading"]')).toBeNull(), { timeout: 3000 });
    const text = container.textContent ?? "";
    expect(text).not.toMatch(FORBIDDEN);
    expect(text).not.toMatch(/\bLIVE\b/); // "Latest stored", never "LIVE"
    expect(text).not.toMatch(/access_token|Bearer |TOTP|password|api[_ ]secret/i);
  });
});

describe("shell", () => {
  it("marks data as latest stored, not live", async () => {
    renderRoute("/overview");
    const banner = await screen.findByRole("banner", { name: "Top bar" });
    expect(await within(banner).findByText("Latest stored")).toBeInTheDocument();
  });

  it("navigation lists every section", async () => {
    renderRoute("/overview");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    for (const s of ["Overview", "Markets", "Stocks", "Sectors", "Global", "News", "Watchlist", "Data Quality", "Operations"]) {
      expect(within(nav).getByRole("link", { name: s })).toBeInTheDocument();
    }
  });
});
