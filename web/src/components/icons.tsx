/* Minimal stroke icons (inline SVG: no icon font, no network). Decorative:
   aria-hidden; every icon sits next to a text label. */
import type { ReactElement } from "react";

const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" } as const;
const I = (d: ReactElement) => () => (
  <svg viewBox="0 0 24 24" className="nav-icon" aria-hidden="true" focusable="false" {...P}>{d}</svg>
);

export const IconOverview = I(<><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></>);
export const IconMarkets = I(<path d="M3 17l5-6 4 4 8-9M15 6h5v5" />);
export const IconStocks = I(<><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>);
export const IconSectors = I(<><circle cx="12" cy="12" r="9" /><path d="M12 3v9l7 5" /></>);
export const IconGlobal = I(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>);
export const IconNews = I(<><rect x="3" y="4" width="18" height="16" rx="1" /><path d="M7 8h10M7 12h10M7 16h6" /></>);
export const IconWatch = I(<path d="M12 4l2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8z" />);
export const IconQuality = I(<><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>);
export const IconOps = I(<><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></>);
export const IconSearch = I(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>);
export const IconBell = I(<path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 21h4" />);
export const IconSettings = I(<><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></>);
export const IconRefresh = I(<path d="M20 11a8 8 0 0 0-14.9-3.5M4 4v4h4M4 13a8 8 0 0 0 14.9 3.5M20 20v-4h-4" />);
export const IconChevron = I(<path d="M15 6l-6 6 6 6" />);

export function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" className="brand-mark" aria-hidden="true">
      <rect width="32" height="32" rx="4" fill="var(--surface-3)" />
      <path d="M9 25V8h8.5a5.5 5.5 0 0 1 0 11H9" fill="none" stroke="var(--accent)" strokeWidth="3" />
    </svg>
  );
}
