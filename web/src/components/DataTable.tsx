/* Professional table: sticky header + first column, client-side sort of the rows it
   is given, column selection, density, row activation by mouse or keyboard, and
   row virtualisation for long lists. It displays values; it never derives them. */
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useSettings } from "../providers/settings";

export interface Column<T> {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** enables sorting on this column (of the rows currently loaded) */
  sortValue?: (row: T) => string | number | null;
  numeric?: boolean;
  sticky?: boolean;
  hiddenByDefault?: boolean;
  title?: string;
}

type Sort = { id: string; dir: "asc" | "desc" } | null;
const VIRTUALIZE_AFTER = 150;

export function DataTable<T>({ rows, columns, rowKey, onRowActivate, caption, toolbar, initialSort = null,
  columnsState }: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onRowActivate?: (row: T) => void;
  caption: string;
  toolbar?: ReactNode;
  initialSort?: Sort;
  columnsState?: [string[], (ids: string[]) => void];
}) {
  const { settings } = useSettings();
  const [sort, setSort] = useState<Sort>(initialSort);
  const localVisible = useState<string[]>(() => columns.filter((c) => !c.hiddenByDefault).map((c) => c.id));
  const [visibleIds, setVisibleIds] = columnsState ?? localVisible;
  const visible = columns.filter((c) => visibleIds.includes(c.id) || c.sticky);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.id === sort.id);
    if (!col?.sortValue) return rows;
    const f = col.sortValue;
    return [...rows].sort((a, b) => {
      const x = f(a);
      const y = f(b);
      if (x === y) return 0;
      if (x === null) return 1; // missing values always last
      if (y === null) return -1;
      const r = x < y ? -1 : 1;
      return sort.dir === "asc" ? r : -r;
    });
  }, [rows, columns, sort]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtual = sorted.length > VIRTUALIZE_AFTER;
  const rowH = settings.density === "compact" ? 26 : settings.density === "comfortable" ? 38 : 32;
  const v = useVirtualizer({ count: sorted.length, getScrollElement: () => scrollRef.current,
    estimateSize: () => rowH, overscan: 12, enabled: virtual });
  const items = virtual ? v.getVirtualItems() : null;
  const padTop = items && items.length ? (items[0]?.start ?? 0) : 0;
  const padBottom = items && items.length ? v.getTotalSize() - (items[items.length - 1]?.end ?? 0) : 0;
  const slice = items ? items.map((i) => sorted[i.index] as T) : sorted;

  const toggleSort = (c: Column<T>) => {
    if (!c.sortValue) return;
    setSort((s) => (s?.id !== c.id ? { id: c.id, dir: c.numeric ? "desc" : "asc" }
      : s.dir === "asc" ? { id: c.id, dir: "desc" } : { id: c.id, dir: "asc" }));
  };
  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (onRowActivate && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onRowActivate(row);
    }
  };

  return (
    <div>
      {toolbar && (
        <div className="toolbar">
          {toolbar}
          <span style={{ flex: 1 }} />
          <ColumnSelector columns={columns} visible={visibleIds} onChange={setVisibleIds} />
        </div>
      )}
      <div className="table-wrap" ref={scrollRef} style={virtual ? { maxHeight: "70vh" } : undefined}>
        <table className="dt" data-density={settings.density}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {visible.map((c) => (
                <th key={c.id} scope="col" title={c.title}
                  className={[c.numeric ? "num" : "", c.sticky ? "sticky-col" : "", c.sortValue ? "sortable" : ""].join(" ")}
                  aria-sort={sort?.id === c.id ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                  onClick={() => toggleSort(c)}
                  onKeyDown={(e) => { if (e.key === "Enter") toggleSort(c); }}
                  tabIndex={c.sortValue ? 0 : undefined}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {padTop > 0 && <tr aria-hidden="true"><td colSpan={visible.length} style={{ height: padTop, padding: 0, border: 0 }} /></tr>}
            {slice.map((row) => (
              <tr key={rowKey(row)} className={onRowActivate ? "clickable" : undefined}
                tabIndex={onRowActivate ? 0 : undefined}
                onClick={onRowActivate ? () => onRowActivate(row) : undefined}
                onKeyDown={(e) => onKey(e, row)}>
                {visible.map((c) => (
                  <td key={c.id} className={[c.numeric ? "num" : "", c.sticky ? "sticky-col" : ""].join(" ")}>{c.cell(row)}</td>
                ))}
              </tr>
            ))}
            {padBottom > 0 && <tr aria-hidden="true"><td colSpan={visible.length} style={{ height: padBottom, padding: 0, border: 0 }} /></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ColumnSelector<T>({ columns, visible, onChange }: {
  columns: Column<T>[]; visible: string[]; onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectable = columns.filter((c) => !c.sticky);
  return (
    <div className="menu-wrap">
      <button type="button" className="btn" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)}>
        Columns
      </button>
      {open && (
        <div className="menu" role="group" aria-label="Visible columns" onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>
          {selectable.map((c) => (
            <label key={c.id} className="field" style={{ display: "flex", padding: "4px 6px" }}>
              <input type="checkbox" checked={visible.includes(c.id)}
                onChange={(e) => onChange(e.target.checked ? [...visible, c.id] : visible.filter((x) => x !== c.id))} />
              {c.header}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function DensityControl() {
  const { settings, update } = useSettings();
  return (
    <div className="segmented" role="group" aria-label="Row density">
      {(["compact", "normal", "comfortable"] as const).map((d) => (
        <button key={d} type="button" aria-pressed={settings.density === d} onClick={() => update({ density: d })}>
          {d === "compact" ? "S" : d === "normal" ? "M" : "L"}
          <span className="sr-only"> {d}</span>
        </button>
      ))}
    </div>
  );
}
