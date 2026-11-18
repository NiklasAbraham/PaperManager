/**
 * Typed API of the optional paper feed (.specs/018_paper_feed.md).
 * Every route except `getFeedStatus` answers 404 when the instance has the feed switched off.
 */
import { apiFetch } from "./client";

export type FeedSource = "arxiv" | "biorxiv" | "medrxiv";
export type FeedMode = "classifier" | "similarity" | "newest";
export type FeedLabel = 1 | -1 | 0 | null;

export interface FeedConfig {
  sources: FeedSource[];
  arxiv_categories: string[];
  digest_days: number;
  min_score: number;
}

export interface FeedQuality {
  auc: number;
  positives: number;
  held_out: number;
}

export interface FeedStatus {
  enabled: boolean;
  state?: "idle" | "refreshing";
  last_refresh?: string | null;
  next_refresh?: string | null;
  candidates?: number;
  embedded?: number;
  mode?: FeedMode | null;
  positives?: number | null;
  quality?: FeedQuality | null;
  error?: string | null;
}

export interface FeedNeighbour {
  paper_id: string;
  title: string;
  similarity: number;
}

export interface FeedItem {
  id: string;
  source: FeedSource;
  title: string;
  authors: string[];
  abstract: string;
  published: string;
  url: string;
  doi: string | null;
  categories: string[];
  score: number | null;
  neighbours: FeedNeighbour[];
  in_library: boolean;
  library_paper_id: string | null;
  my_label: FeedLabel;
}

export interface FeedDigest {
  mode: FeedMode;
  total: number;
  days: number;
  skip: number;
  limit: number;
  positives: number;
  quality: FeedQuality | null;
  configured: boolean;
  items: FeedItem[];
}

const JSON_HEADERS = { "Content-Type": "application/json" };
const enc = encodeURIComponent;

export function getFeedStatus(): Promise<FeedStatus> {
  return apiFetch("/feed/status");
}

export function getFeedConfig(): Promise<FeedConfig> {
  return apiFetch("/feed/config");
}

export function putFeedConfig(config: FeedConfig): Promise<FeedConfig> {
  return apiFetch("/feed/config", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(config) });
}

export function listFeed(params: { days?: number; skip?: number; limit?: number; include_rated?: boolean; source?: FeedSource } = {}): Promise<FeedDigest> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) sp.set(k, String(v));
  }
  const q = sp.toString();
  return apiFetch(`/feed${q ? `?${q}` : ""}`);
}

export function rateFeedItem(id: string, value: 1 | -1): Promise<{ id: string; my_label: 1 | -1 }> {
  return apiFetch(`/feed/${enc(id)}/rate`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ value }) });
}

export function dismissFeedItem(id: string): Promise<{ id: string; my_label: 0 }> {
  return apiFetch(`/feed/${enc(id)}/dismiss`, { method: "POST" });
}

export function clearFeedLabel(id: string): Promise<{ id: string; my_label: null }> {
  return apiFetch(`/feed/${enc(id)}/label`, { method: "DELETE" });
}

export function addFeedItem(id: string, projectId?: string): Promise<{ id: string; my_label: 1; paper_id: string | null }> {
  return apiFetch(`/feed/${enc(id)}/add`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(projectId ? { project_id: projectId } : {}),
  });
}

export function refreshFeed(): Promise<{ started: boolean }> {
  return apiFetch("/feed/refresh", { method: "POST" });
}
