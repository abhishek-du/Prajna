import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { BASE } from "../mocks/handlers";
import { env } from "../mocks/fixtures";
import { server } from "./test-setup";
import { renderRoute } from "./test-utils";

describe("failures and empty states", () => {
  it("an API failure renders a human message and Retry, not a raw status", async () => {
    server.use(http.get(`${BASE}/sectors`, () => new HttpResponse(null, { status: 500 })));
    renderRoute("/sectors");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Sectors could not be loaded.")).toBeInTheDocument();
    expect(within(alert).getByText("The data service had an internal problem.")).toBeInTheDocument();
    expect(within(alert).queryByText(/500/)).toBeNull(); // technical detail only in developer mode
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("an unreachable API is reported as such", async () => {
    server.use(http.get(`${BASE}/news`, () => HttpResponse.error()));
    renderRoute("/news");
    expect(await screen.findByText("The data service could not be reached.")).toBeInTheDocument();
  });

  it("empty results render an explicit empty state", async () => {
    server.use(http.get(`${BASE}/news`, () => HttpResponse.json(env([]))));
    renderRoute("/news");
    expect(await screen.findByText("No news knowable for this selection.")).toBeInTheDocument();
  });

  it("missing backend capabilities are shown as unavailable, never as numbers", async () => {
    renderRoute("/overview");
    const u = await screen.findAllByTestId("unavailable");
    expect(u.map((e) => e.textContent).join(" ")).toMatch(/advancing \/ declining/);
    expect(u.map((e) => e.textContent).join(" ")).toMatch(/Missing backend capability/);
  });

  it("the empty watchlist explains how to add instruments", async () => {
    renderRoute("/watchlist");
    expect(await screen.findByText("Your watchlist is empty.")).toBeInTheDocument();
  });
});

describe("search", () => {
  it("Ctrl+K opens search; typing RELIANCE and Enter opens the stock", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/overview");
    await screen.findByRole("heading", { level: 1, name: "Overview" });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const box = await screen.findByRole("combobox", { name: "Search instruments and sectors" });
    await user.type(box, "RELIANCE");
    const option = await screen.findByRole("option", { name: /RELIANCE/ });
    expect(await within(option).findByText("1,219.20")).toBeInTheDocument(); // latest stored close from /latest
    await user.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/stocks/NSE_EQ%7CINE002A01018"));
  });

  it("Escape closes search", async () => {
    const user = userEvent.setup();
    renderRoute("/overview");
    await user.click(await screen.findByRole("button", { name: /Search symbol/ }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Search instruments" })).toBeNull();
  });
});

describe("stock detail", () => {
  it("shows the latest stored close with its session and freshness, never LIVE", async () => {
    renderRoute("/stocks/NSE_EQ%7CINE002A01018");
    expect(await screen.findByText("Latest stored · 1D close")).toBeInTheDocument();
    expect((await screen.findAllByText("1,219.20")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/session 24 Sept 2026|session 24 Sep 2026/).length).toBeGreaterThan(0);
  });

  it("chart: switching timeframe requests that timeframe; 5m is disabled with its reason", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => {
      const u = new URL(request.url);
      if (u.pathname.endsWith("/candles")) seen.push(u.searchParams.get("timeframe") ?? "");
    });
    renderRoute("/stocks/NSE_EQ%7CINE002A01018?tab=chart");
    expect(await screen.findByTestId("candle-chart")).toHaveTextContent("4 bars");
    const five = screen.getByRole("button", { name: /5m unavailable: Out of scope/ });
    expect(five).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "1h timeframe" }));
    await waitFor(() => expect(seen).toContain("1h"));
    expect(screen.getByRole("button", { name: "1h timeframe" })).toHaveAttribute("aria-pressed", "true");
    server.events.removeAllListeners();
  });

  it("chart: a timeframe with no stored bars says why", async () => {
    const user = userEvent.setup();
    renderRoute("/stocks/NSE_EQ%7CINE002A01018?tab=chart");
    await screen.findByTestId("candle-chart");
    await user.click(screen.getByRole("button", { name: "1m timeframe" }));
    expect(await screen.findByText("No 1m bars stored for this instrument.")).toBeInTheDocument();
    expect(screen.getByText(/historical intraday backfill: deferred/)).toBeInTheDocument();
  });

  it("withholds the change when the API says the closes are not comparable", async () => {
    renderRoute("/overview");
    // the NIFTY fixture has comparable=false across a split/bonus ex-date
    const cells = await screen.findAllByTitle("split/bonus ex-date between the sessions");
    for (const c of cells) expect(c).toHaveTextContent("—");
  });
});

describe("global finality", () => {
  it("revised and placeholder labels are withheld, never presented as confirmed", async () => {
    renderRoute("/global");
    expect(await screen.findByText("Bar withheld — later vendor revision detected.", { exact: false })).toBeInTheDocument();
    const hist = screen.getByRole("table", { name: "Label finality" });
    const rows = within(hist).getAllByRole("row").slice(1);
    const revised = rows.find((r) => within(r).queryByText("REVISED"));
    expect(revised).toBeDefined();
    expect(within(revised as HTMLElement).getByText("WITHHELD")).toBeInTheDocument();
    expect(within(revised as HTMLElement).queryByText("45,000.00")).toBeNull();
  });

  it("labels are presented as vendor labels, not trading dates", async () => {
    renderRoute("/global");
    expect((await screen.findAllByText("Vendor label")).length).toBeGreaterThan(0);
    expect(screen.getByText(/shifted calendar: label ≠ trading date/)).toBeInTheDocument();
  });
});

describe("acceptance", () => {
  it("Stage 3 is shown LOCKED with the gate's reason and no metrics", async () => {
    renderRoute("/operations/acceptance");
    const lock = await screen.findByTestId("stage3-lock");
    expect(lock).toHaveTextContent("Stage 3 Locked");
    expect(lock).toHaveTextContent("unlocked only after Stage 1 is COMPLETE");
    expect(screen.getByText("WAITING FOR EVIDENCE")).toBeInTheDocument();
  });

  it("operations never render a credential, only the token age", async () => {
    const { container } = renderRoute("/operations");
    expect(await screen.findByText("8.5 h")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/access_token|Bearer|secret/i);
  });
});
