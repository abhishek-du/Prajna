/* Watchlist: persisted in this browser only (no backend persistence exists).
   Stores identifying metadata captured when the instrument was added; prices are
   always fetched live from the API, never stored here. */
import { useCallback, useEffect, useState } from "react";

export interface WatchItem {
  instrument_key: string;
  trading_symbol: string;
  name: string | null;
  sector: string | null;
  added_at: string;
}

const KEY = "prajna.web.watchlist.v1";
const EVENT = "prajna-watchlist";

function read(): WatchItem[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as WatchItem[]) : [];
  } catch {
    return [];
  }
}

function write(items: WatchItem[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchItem[]>(read);
  useEffect(() => {
    const sync = () => setItems(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const has = useCallback((key: string) => items.some((i) => i.instrument_key === key), [items]);
  const add = useCallback((i: Omit<WatchItem, "added_at">) => {
    const cur = read();
    if (!cur.some((x) => x.instrument_key === i.instrument_key)) write([...cur, { ...i, added_at: new Date().toISOString() }]);
  }, []);
  const remove = useCallback((key: string) => write(read().filter((x) => x.instrument_key !== key)), []);
  return { items, has, add, remove };
}
