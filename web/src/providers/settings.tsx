import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** UI state only (never server data). Persisted per browser. */
export interface Settings {
  refreshSeconds: number; // 0 = off
  theme: "dark" | "light";
  sidebarCollapsed: boolean;
  density: "compact" | "normal" | "comfortable";
  developerMode: boolean; // shows technical error details
}

const DEFAULTS: Settings = {
  refreshSeconds: 60,
  theme: "dark",
  sidebarCollapsed: false,
  density: "normal",
  developerMode: false,
};
const KEY = "prajna.web.settings.v1";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

interface Ctx {
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  /** when the last successful refresh of polled data happened (for display) */
  lastRefreshed: Date | null;
  markRefreshed: () => void;
}

const SettingsContext = createContext<Ctx | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(load);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(settings));
    } catch {
      /* storage unavailable: settings stay in memory */
    }
    document.documentElement.dataset.theme = settings.theme;
  }, [settings]);

  const update = useCallback((patch: Partial<Settings>) => setSettings((s) => ({ ...s, ...patch })), []);
  const markRefreshed = useCallback(() => setLastRefreshed(new Date()), []);
  const value = useMemo(() => ({ settings, update, lastRefreshed, markRefreshed }),
    [settings, update, lastRefreshed, markRefreshed]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): Ctx {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings outside SettingsProvider");
  return ctx;
}

/** Polling interval for price/news/ops queries (false = off). */
export function useRefetchInterval(): number | false {
  const { settings } = useSettings();
  return settings.refreshSeconds > 0 ? settings.refreshSeconds * 1000 : false;
}
