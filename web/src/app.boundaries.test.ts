/* Architectural boundaries, checked on the source itself. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname);
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(f) ? [p] : [];
  });
}
const app = files(SRC).filter((f) => !/\.test\.(ts|tsx)$/.test(f) && !/test-(setup|utils)\.tsx$/.test(f));

describe("boundaries", () => {
  it("application code never imports fixtures or mocks", () => {
    for (const f of app) expect(readFileSync(f, "utf8"), relative(SRC, f)).not.toMatch(/from\s+["'][./]*mocks\//);
  });

  it("the API client only issues GET requests (read-only)", () => {
    const http = readFileSync(join(SRC, "api", "http.ts"), "utf8");
    expect(http).toMatch(/method: "GET"/);
    for (const f of app) expect(readFileSync(f, "utf8"), relative(SRC, f)).not.toMatch(/method:\s*["'](POST|PUT|PATCH|DELETE)/);
  });

  it("no credential material in the client source", () => {
    for (const f of app) {
      const s = readFileSync(f, "utf8");
      expect(s, relative(SRC, f)).not.toMatch(/Authorization|Bearer |PRAJNA_WRITE_TOKEN|TOTP|api[_-]?secret/i);
    }
  });

  it("no random or synthetic market values in application code", () => {
    for (const f of app) expect(readFileSync(f, "utf8"), relative(SRC, f)).not.toMatch(/Math\.random/);
  });
});
