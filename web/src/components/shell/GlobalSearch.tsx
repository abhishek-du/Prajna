/* Command-style search (Ctrl/Cmd+K). Instruments come from /v1/search; their
   latest stored daily close from /v1/latest; sector matches from /v1/sectors.
   Enter opens, arrows move, Escape closes. No result is ever invented. */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useLatest, useSearch, useSectors } from "../../api/hooks";
import { fmtPrice } from "../../lib/format";
import { FreshnessBadge } from "../badges";
import { IconSearch } from "../icons";

type Result =
  | { kind: "instrument"; key: string; symbol: string; name: string | null; meta: string }
  | { kind: "sector"; sector: string; stocks: number };

function useDebounced<T>(v: T, ms = 150): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <button type="button" className="search-trigger" onClick={() => setOpen(true)} aria-haspopup="dialog">
        <IconSearch /> <span>Search symbol, company, ISIN, sector</span>
        <span className="kbd hide-sm" aria-hidden="true">Ctrl K</span>
      </button>
      {open && <SearchDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function SearchDialog({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const q = useDebounced(text);
  const search = useSearch(q);
  const sectors = useSectors();
  const navigate = useNavigate();
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  const results: Result[] = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    const inst: Result[] = (search.data?.data ?? []).map((h) => ({
      kind: "instrument", key: h.instrument_key, symbol: h.trading_symbol, name: h.name,
      meta: [h.segment, h.instrument_type, h.security_class, h.lifecycle_status !== "ACTIVE" ? h.lifecycle_status : null]
        .filter(Boolean).join(" · "),
    }));
    const sec: Result[] = (sectors.data?.data ?? [])
      .filter((s) => s.sector && s.sector.toLowerCase().includes(t))
      .slice(0, 5)
      .map((s) => ({ kind: "sector", sector: s.sector as string, stocks: s.stocks }));
    return [...inst, ...sec];
  }, [q, search.data, sectors.data]);

  const keys = results.flatMap((r) => (r.kind === "instrument" ? [r.key] : []));
  const latest = useLatest(keys);
  const priceOf = new Map((latest.data?.data ?? []).map((p) => [p.instrument_key, p]));

  const go = (r: Result | undefined) => {
    if (!r) return;
    onClose();
    navigate(r.kind === "instrument" ? `/stocks/${encodeURIComponent(r.key)}` : `/sectors/${encodeURIComponent(r.sector)}`);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(results[active]); }
  };

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Search instruments">
        <input ref={input} value={text} onChange={(e) => { setText(e.target.value); setActive(0); }} onKeyDown={onKey}
          placeholder="RELIANCE, HDFC Bank, INE002A01018, Refineries…" role="combobox" aria-label="Search instruments and sectors" aria-expanded={results.length > 0}
          aria-controls={listId} aria-activedescendant={results.length ? `${listId}-${active}` : undefined} aria-autocomplete="list" />
        <ul className="results" id={listId} role="listbox" aria-label="Results">
          {q.trim() && search.isPending && <li className="muted" aria-disabled="true">Searching…</li>}
          {q.trim() && search.isError && <li className="muted" aria-disabled="true">Search is unavailable (the data service could not be reached).</li>}
          {q.trim() && !search.isPending && !search.isError && results.length === 0 && <li className="muted" aria-disabled="true">No instrument or sector matches “{q}”.</li>}
          {results.map((r, i) => (
            <li key={r.kind === "instrument" ? r.key : `s:${r.sector}`} id={`${listId}-${i}`} role="option" aria-selected={i === active}
              onMouseEnter={() => setActive(i)} onClick={() => go(r)}>
              {r.kind === "instrument" ? (
                <>
                  <span className="symbol">{r.symbol}</span>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.name ?? "—"} <span className="faint hide-sm">· {r.meta}</span>
                  </span>
                  <span className="num">{priceOf.get(r.key) ? fmtPrice(priceOf.get(r.key)?.close) : "—"}</span>
                  <span className="hide-sm">
                    {priceOf.get(r.key)
                      ? <FreshnessBadge at={priceOf.get(r.key)?.knowable_at} kind="daily" prefix="1D close" />
                      : <span className="faint">no stored price</span>}
                  </span>
                </>
              ) : (
                <>
                  <span className="faint">SECTOR</span>
                  <span>{r.sector}</span>
                  <span className="num">{r.stocks} stocks</span>
                  <span />
                </>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
