import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
}

/** A compact, horizontally scrollable table with an accessible caption. */
export default function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  empty,
}: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string | number;
  empty?: string;
}) {
  if (rows.length === 0) {
    return <p className="py-3 text-sm text-ink-3">{empty ?? "Nothing here yet."}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line text-xs text-ink-3">
            {columns.map((c) => (
              <th key={c.header} scope="col" className={`px-2 py-1.5 font-medium ${c.align === "right" ? "text-right" : "text-left"}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)} className="border-b border-line-s last:border-0">
              {columns.map((c) => (
                <td
                  key={c.header}
                  className={`px-2 py-1.5 align-top text-ink-2 ${c.align === "right" ? "text-right tabular-nums" : "text-left"} ${c.className ?? ""}`}
                >
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
