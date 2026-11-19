/**
 * Typed API of "find papers like this abstract" (.specs/020_similar_search.md).
 * An index that cannot be searched yet is a normal answer (`available: false` with a `reason`),
 * not an HTTP error.
 */
import { apiFetch } from "./client";

export type SimilarScope = "library" | "feed" | "both";

export interface SimilarHit {
  source: "library" | "feed";
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  published?: string;
  venue?: string | null;
  doi: string | null;
  url: string;
  /** Cosine similarity, 0 to 1 (a hit below the request's floor is not returned). */
  score: number;
  snippet: string;
  abstract?: string;
  in_library: boolean;
  library_paper_id: string | null;
  /** The caller's own feed rating; null for a library hit or an unrated feed paper. */
  my_label: 1 | -1 | 0 | null;
  feed_source?: string;
  reference_stub?: boolean;
}

export interface SimilarResult {
  available: boolean;
  reason: string | null;
  scope: SimilarScope;
  mode: "document" | "query" | "paper" | null;
  total: number;
  k?: number;
  hits: SimilarHit[];
  skipped: Record<string, string>;
  warnings?: string[];
}

export interface SimilarRequest {
  text: string;
  k?: number;
  scope?: SimilarScope;
  /** YYYY-MM-DD: only papers published on or after it. */
  since?: string;
  min_score?: number;
  include_stubs?: boolean;
}

export const MIN_TEXT = 20;
export const MAX_TEXT = 20000;

export function searchSimilar(req: SimilarRequest): Promise<SimilarResult> {
  return apiFetch("/search/similar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export function papersLike(paperId: string, params: { k?: number; scope?: SimilarScope; since?: string } = {}): Promise<SimilarResult> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const q = sp.toString();
  return apiFetch(`/search/similar/${encodeURIComponent(paperId)}${q ? `?${q}` : ""}`);
}
