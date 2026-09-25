import type { Envelope } from "../types/api";

/** Base URL of the read API. Development and preview proxy /v1 to the API
 * (vite.config.ts), so the browser talks to its own origin. */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/v1";
const TIMEOUT_MS = 15_000;

/** A failed API call, with a sentence for people and details for developers. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly path: string;
  readonly detail: string;

  constructor(message: string, status: number | null, path: string, detail: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
    this.detail = detail;
  }
}

function humanMessage(status: number | null): string {
  if (status === null) return "The data service could not be reached.";
  if (status === 404) return "This item does not exist in the data store.";
  if (status === 422) return "The request was not accepted (invalid parameter).";
  if (status >= 500) return "The data service had an internal problem.";
  return "The data could not be loaded.";
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return `${API_BASE}${path}${s ? `?${s}` : ""}`;
}

/** GET a /v1 resource and return its envelope. Read-only by construction:
 * this client has no method that sends a body. */
export async function get<T>(path: string, query?: Query, signal?: AbortSignal): Promise<Envelope<T>> {
  const url = buildUrl(path, query);
  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  let res: Response;
  try {
    res = await fetch(url, { method: "GET", headers: { Accept: "application/json" }, signal: combined });
  } catch (e) {
    if (signal?.aborted) throw e; // cancelled by the caller: not an error to show
    const detail = timeout.aborted ? `timeout after ${TIMEOUT_MS} ms` : String(e);
    throw new ApiError(humanMessage(null), null, path, detail);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail !== undefined) detail += ` — ${JSON.stringify(body.detail)}`;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(humanMessage(res.status), res.status, path, detail);
  }
  return (await res.json()) as Envelope<T>;
}

/** Instrument keys contain "|" and spaces: always encode them into paths. */
export const enc = (key: string): string => encodeURIComponent(key);
