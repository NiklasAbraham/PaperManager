import type { GraphLink, GraphNode } from "../../types";

/** Response of POST /graph/query: one run, table view and graph view together. */
export interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  counters: Record<string, number>;
  nodes: GraphNode[];
  links: GraphLink[];
  graph_truncated?: boolean;
  took_ms: number;
}

export type ResultTab = "graph" | "table";

export interface SchemaInfo {
  labels: string[];
  relationship_types: string[];
  properties: Record<string, string[]>;
}
