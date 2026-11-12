/** Typed fetchers for the landing dashboard (GET /stats/dashboard, GET /stats/topic-map).
 * Both resolve to null on any failure (404 from an older backend included) so the page hides the piece. */
import { apiFetch } from "../../api/client";

export interface DashProject {
  id: string; name: string; count: number; read: number; reading: number; last_added?: string | null;
}
export interface DashboardData {
  total: number;
  references: number;
  added_7d: number;
  added_30d: number;
  added_weekly: { week_start: string; count: number }[];
  reading: { unread: number; reading: number; read: number };
  top_topics: { name: string; count: number }[];
  top_tags?: { name: string; count: number }[];
  projects: DashProject[];
}

export interface MapPoint {
  id: string; x: number; y: number; c: number; t: string; r: number; p: number[]; topic: string | null;
  /** Publication year (else the year it was added); missing from older backends. */
  yr?: number | null;
  /** Reading status; missing from older backends (= unread). */
  s?: "unread" | "reading" | "read";
}
export interface MapCluster {
  id: number; label: string; color: string; x: number; y: number; size: number; library: number;
  /** Junk cluster (unparsed references, ...): drawn grey and small, never used to colour a chip. Missing = false. */
  muted?: boolean;
}
export interface MapProject { id: string; name: string; color: string; count: number }
export interface TopicMapData {
  state: "ready" | "building" | "empty";
  computed_at?: string; seconds?: number; n?: number; stale?: boolean;
  points: MapPoint[];
  clusters: MapCluster[];
  projects: MapProject[];
}

export async function fetchDashboard(): Promise<DashboardData | null> {
  try {
    const d = await apiFetch<DashboardData>("/stats/dashboard");
    return d && typeof d.total === "number" && d.reading ? d : null;
  } catch {
    return null;
  }
}

/** `clusters`: ask for N clusters (the backend re-clusters in the background and answers `building` first). */
export async function fetchTopicMap(refs: boolean, clusters?: number | null): Promise<TopicMapData | null> {
  try {
    const q = `refs=${refs ? 1 : 0}${clusters ? `&clusters=${clusters}` : ""}`;
    const d = await apiFetch<Partial<TopicMapData>>(`/stats/topic-map?${q}`);
    if (!d || (d.state !== "ready" && d.state !== "building" && d.state !== "empty")) return null;
    return { state: d.state, computed_at: d.computed_at, seconds: d.seconds, n: d.n, stale: d.stale,
      points: d.points ?? [], clusters: d.clusters ?? [], projects: d.projects ?? [] };
  } catch {
    return null;
  }
}
