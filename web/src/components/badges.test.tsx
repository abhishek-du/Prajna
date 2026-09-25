import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FRESHNESS } from "../config/data";
import { SettingsProvider } from "../providers/settings";
import { Change, freshnessOf, FreshnessBadge } from "./badges";

const ago = (s: number, now: Date) => new Date(now.getTime() - s * 1000).toISOString();

describe("freshness", () => {
  const now = new Date("2026-09-25T12:00:00Z");
  it("follows the configured per-kind thresholds", () => {
    const t = FRESHNESS.daily;
    expect(freshnessOf(ago(t.fresh - 1, now), "daily", now).state).toBe("fresh");
    expect(freshnessOf(ago(t.fresh + 1, now), "daily", now).state).toBe("aging");
    expect(freshnessOf(ago(t.stale + 1, now), "daily", now).state).toBe("stale");
    expect(freshnessOf(null, "daily", now).state).toBe("unavailable");
  });

  it("thresholds differ by data kind (not hard-coded in components)", () => {
    expect(FRESHNESS.news.stale).toBeLessThan(FRESHNESS.daily.stale);
  });

  it("renders Unavailable without a timestamp", () => {
    render(<SettingsProvider><FreshnessBadge at={null} kind="daily" /></SettingsProvider>);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});

describe("Change", () => {
  it("never relies on colour alone: arrow, sign and text", () => {
    const { container } = render(<Change value={-28.8} pct={-2.3} />);
    expect(container.textContent).toContain("▼");
    expect(container.textContent).toContain("−28.80");
    expect(container.textContent).toContain("down");
  });

  it("withheld changes render a dash with the reason", () => {
    render(<Change value={null} unavailableReason="split/bonus ex-date between the sessions" />);
    expect(screen.getByTitle("split/bonus ex-date between the sessions")).toHaveTextContent("—");
  });
});
