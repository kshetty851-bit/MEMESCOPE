"use client";

import { useMemo, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * DATA TABLE — the foundation the scanner is built on.
 *
 * The app has eight wide tables and not one of them has a sticky header. The
 * Track Record's is `min-w-[1320px]` inside a 1120px shell, so it scrolls
 * horizontally *and* vertically, and by row twelve the reader has lost both
 * the column names and the left edge. That is the single worst thing this
 * interface does to someone reading data.
 *
 * Four decisions worth stating, because each has a non-obvious reason:
 *
 *  - **`border-separate`, not `border-collapse`.** Collapsed borders are owned
 *    by the table, not the cell, so they do not travel with a sticky header —
 *    the rule under the header disappears the moment it sticks. Separate
 *    borders with zero spacing look identical and survive.
 *  - **Sticky needs a bounded scroller.** `overflow-x: auto` silently computes
 *    block-direction overflow to `auto` as well, which disables page-level
 *    sticky. So the scroll container owns a `maxHeight` whenever the header
 *    sticks, and the header sticks to *it*.
 *  - **Rows are not buttons.** Making a `<tr>` focusable and clickable nests
 *    interactive elements inside an interactive element, which is invalid and
 *    announces as a mess. Instead the primary column carries a real link, the
 *    row click is a convenience on top, and `rowHref` puts a proper focusable
 *    anchor in the tab order.
 *  - **Sorting is controlled.** Pages already own their data and several sort
 *    server-side. A table that sorted its own copy would silently disagree
 *    with the page's paging. `useTableSort` is offered for the local case.
 */

export type Align = "left" | "right" | "center";

export interface Column<T> {
  /** Stable id. Also the sort key when the column is sortable. */
  key: string;
  header: ReactNode;
  /** Announced as the column name when `header` is a glyph or abbreviation. */
  srHeader?: string;
  /**
   * Numeric columns go right. This is not cosmetic: a right-aligned column of
   * tabular figures can be compared by eye down the decimal, and a left-
   * aligned one cannot.
   */
  align?: Align;
  /** CSS width, e.g. "120px" or "18%". */
  width?: string;
  sortable?: boolean;
  /** Pins the column against the left edge during horizontal scroll. */
  pinned?: boolean;
  cell: (row: T, index: number) => ReactNode;
  /** Extra classes on every cell in this column. */
  cellClassName?: string;
  /**
   * Extra classes on the header cell.
   *
   * Responsive column visibility is done by pairing this with `cellClassName`
   * (`"hidden xl:table-cell"` on both), rather than by measuring the viewport
   * in JavaScript. CSS has no hydration mismatch, no resize listener, and no
   * frame where the wrong column set is painted.
   */
  headerClassName?: string;
}

export type SortDirection = "asc" | "desc";

export interface SortState {
  key: string;
  direction: SortDirection;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  /** Names the table for assistive tech. Required. */
  caption: string;
  /** Renders the caption visibly above the table instead of only for SR. */
  showCaption?: boolean;
  sort?: SortState | null;
  onSortChange?: (sort: SortState) => void;
  density?: "compact" | "comfortable";
  stickyHeader?: boolean;
  /** Required for a sticky header to work. Ignored when `stickyHeader` is off. */
  maxHeight?: string;
  /** Minimum table width before horizontal scrolling begins. */
  minWidth?: string;
  onRowClick?: (row: T) => void;
  /** Marks a row as the current selection. */
  isRowActive?: (row: T) => boolean;
  isPending?: boolean;
  pendingRows?: number;
  empty?: ReactNode;
  className?: string;
}

const ALIGN: Record<Align, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

const PAD: Record<NonNullable<DataTableProps<unknown>["density"]>, string> = {
  compact: "px-2.5 py-1.5",
  comfortable: "px-3 py-2.5",
};

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  caption,
  showCaption = false,
  sort = null,
  onSortChange,
  density = "compact",
  stickyHeader = true,
  maxHeight = "calc(100vh - 16rem)",
  minWidth,
  onRowClick,
  isRowActive,
  isPending = false,
  pendingRows = 8,
  empty,
  className,
}: DataTableProps<T>) {
  const pad = PAD[density];

  function toggle(column: Column<T>) {
    if (!column.sortable || !onSortChange) return;
    const active = sort?.key === column.key;
    // First click on a new column sorts descending: for every sortable column
    // in this product — score, volume, liquidity, peak — "biggest first" is
    // the question being asked.
    onSortChange({
      key: column.key,
      direction: active && sort?.direction === "desc" ? "asc" : "desc",
    });
  }

  return (
    <div className={cn("flex flex-col", className)}>
      {showCaption ? (
        <p className="mb-2 text-label font-medium uppercase text-ink-3">{caption}</p>
      ) : null}

      <div
        className="overflow-auto rounded-md border border-line"
        style={stickyHeader ? { maxHeight } : undefined}
      >
        <table
          className="w-full border-separate border-spacing-0 text-sm"
          style={minWidth ? { minWidth } : undefined}
        >
          <caption className="sr-only">{caption}</caption>

          <thead>
            <tr>
              {columns.map((column) => {
                const active = sort?.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    style={column.width ? { width: column.width } : undefined}
                    aria-sort={
                      column.sortable
                        ? active
                          ? sort?.direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                        : undefined
                    }
                    className={cn(
                      "border-b border-line bg-sunken font-medium",
                      "text-label uppercase text-ink-3",
                      pad,
                      ALIGN[column.align ?? "left"],
                      stickyHeader && "sticky top-0 z-20",
                      column.pinned && "sticky left-0 z-30",
                      column.headerClassName,
                    )}
                  >
                    {column.sortable && onSortChange ? (
                      <button
                        type="button"
                        onClick={() => toggle(column)}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-sm",
                          "transition-colors duration-[var(--duration-instant)]",
                          "hover:text-ink",
                          active && "text-ink",
                          column.align === "right" && "flex-row-reverse",
                        )}
                      >
                        <span>{column.header}</span>
                        {/* The indicator is always rendered, at low contrast
                            when inactive, so a sortable column is discoverable
                            without hovering every header to find out. */}
                        <span
                          aria-hidden
                          className={cn(
                            "text-[0.625rem] leading-none",
                            active ? "text-accent" : "text-ink-4",
                          )}
                        >
                          {active ? (sort?.direction === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                        {column.srHeader ? (
                          <span className="sr-only">{column.srHeader}</span>
                        ) : null}
                      </button>
                    ) : (
                      <>
                        <span aria-hidden={Boolean(column.srHeader)}>
                          {column.header}
                        </span>
                        {column.srHeader ? (
                          <span className="sr-only">{column.srHeader}</span>
                        ) : null}
                      </>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody>
            {isPending ? (
              Array.from({ length: pendingRows }, (_, rowIndex) => (
                <tr key={`skeleton-${rowIndex}`}>
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn("border-b border-line-subtle bg-surface", pad)}
                    >
                      <span className="skeleton block h-3 w-full rounded-sm" />
                    </td>
                  ))}
                </tr>
              ))
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="bg-surface">
                  {empty ?? (
                    <p className="px-3 py-10 text-center text-sm text-ink-3">
                      Nothing to show.
                    </p>
                  )}
                </td>
              </tr>
            ) : (
              rows.map((row, index) => {
                const active = isRowActive?.(row) ?? false;
                return (
                  <tr
                    key={getRowId(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(
                      "group",
                      "transition-colors duration-[var(--duration-instant)]",
                      onRowClick && "cursor-pointer",
                      active ? "bg-raised" : "bg-surface hover:bg-raised",
                    )}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "border-b border-line-subtle",
                          pad,
                          ALIGN[column.align ?? "left"],
                          // Pinned cells need their own background or the
                          // scrolled content shows through them.
                          column.pinned &&
                            "sticky left-0 z-10 bg-[inherit] group-hover:bg-[inherit]",
                          column.cellClassName,
                        )}
                      >
                        {column.cell(row, index)}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Local sort state plus the comparator, for tables whose data is already
 * fully in memory (the Track Record, the Lab).
 *
 * `select` returns the sortable value for a row. Returning `null` puts the row
 * at the bottom in **both** directions — deliberately. A token with no peak
 * multiple has not performed worst, it has not been measured, and letting it
 * sort to the top of an ascending list would read as a result.
 */
export function useTableSort<T>(
  rows: T[],
  select: (row: T, key: string) => string | number | null,
  initial: SortState | null = null,
) {
  const [sort, setSort] = useState<SortState | null>(initial);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const factor = sort.direction === "asc" ? 1 : -1;

    return [...rows].sort((a, b) => {
      const left = select(a, sort.key);
      const right = select(b, sort.key);

      if (left === null && right === null) return 0;
      if (left === null) return 1;
      if (right === null) return -1;

      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * factor;
      }
      return String(left).localeCompare(String(right)) * factor;
    });
  }, [rows, sort, select]);

  return { sort, setSort, sorted };
}
