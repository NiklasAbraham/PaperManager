import { formatCellValue, isMutation } from "./resultFormat";
import type { QueryResult } from "./types";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Row count, timing, mutation counters and truncation notes for one run. */
export function ResultSummary({ result }: { result: QueryResult }) {
  const c = result.counters;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
      {result.columns.length > 0 && (
        <span className="font-medium text-ink">{plural(result.row_count, "row")}</span>
      )}
      <span className="text-ink-3">{result.took_ms} ms</span>
      {isMutation(c) && (
        <span className="flex flex-wrap gap-x-3">
          {c.nodes_created > 0 && <span className="text-green-600">+{plural(c.nodes_created, "node")}</span>}
          {c.nodes_deleted > 0 && <span className="text-coral">−{plural(c.nodes_deleted, "node")}</span>}
          {c.relationships_created > 0 && <span className="text-green-600">+{plural(c.relationships_created, "rel")}</span>}
          {c.relationships_deleted > 0 && <span className="text-coral">−{plural(c.relationships_deleted, "rel")}</span>}
          {c.properties_set > 0 && <span className="text-blue-600">{c.properties_set} {c.properties_set === 1 ? "prop" : "props"} set</span>}
        </span>
      )}
      {result.truncated && <span className="text-amber">Table capped at 500 rows</span>}
      {result.graph_truncated && <span className="text-amber">Graph capped at 5,000 nodes</span>}
    </div>
  );
}

export function ResultTable({ result }: { result: QueryResult }) {
  if (result.columns.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-ink-2">
        {isMutation(result.counters) ? "Query executed successfully." : "Query returned no columns."}
      </p>
    );
  }
  if (result.rows.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-3">Query returned no results.</p>;
  }
  return (
    <div className="bg-raised border border-line rounded-lg overflow-auto max-h-[50vh]">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0">
          <tr className="bg-base border-b border-line">
            {result.columns.map((col) => (
              <th key={col} className="text-left px-3 py-2 font-semibold text-ink-3 uppercase tracking-wide whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className="border-b border-line-s hover:bg-accent-lo transition-colors">
              {result.columns.map((col) => (
                <td key={col} className="px-3 py-1.5 text-ink-2 font-mono max-w-[16rem] truncate" title={formatCellValue(row[col])}>
                  {formatCellValue(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
