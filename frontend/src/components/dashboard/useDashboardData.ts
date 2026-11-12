import { useEffect, useState } from "react";
import { fetchDashboard, fetchTopicMap, type DashboardData, type TopicMapData } from "./api";

const POLL_MS = 4000, MAX_POLLS = 30;     // "building": poll every 4 s for about two minutes
const FRESH_MS = 5 * 60 * 1000;
const cache: { at: number; dash: DashboardData | null; map: TopicMapData | null } = { at: 0, dash: null, map: null };
const fresh = () => (Date.now() - cache.at < FRESH_MS ? cache : null);
export const resetDashboardCache = () => { cache.at = 0; cache.dash = null; cache.map = null; };

export interface DashboardState {
  dash: DashboardData | null;
  map: TopicMapData | null;
  /** loading: first answer pending; ready: map can be drawn; building: layout not computed yet; none: hide the piece */
  mapStatus: "loading" | "ready" | "building" | "none";
  dashLoading: boolean;
}

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Both endpoints once per mount (cached for a few minutes); failures resolve to "hide". The map comes
 * without references first (small, fast), then with them. */
export function useDashboardData(enabled: boolean): DashboardState {
  const [dash, setDash] = useState<DashboardData | null>(() => fresh()?.dash ?? null);
  const [dashLoading, setDashLoading] = useState(() => enabled && !fresh()?.dash);
  const [map, setMap] = useState<TopicMapData | null>(() => fresh()?.map ?? null);
  const [mapStatus, setMapStatus] = useState<DashboardState["mapStatus"]>(() => (fresh()?.map ? "ready" : "loading"));

  useEffect(() => {
    if (!enabled || (fresh()?.dash && fresh()?.map)) return;
    let live = true;
    fetchDashboard().then((d) => {
      if (!live) return;
      cache.dash = d; cache.at = Date.now();
      setDash(d); setDashLoading(false);
    });
    (async () => {
      for (let tries = 0; live; tries++) {
        const m = await fetchTopicMap(false);
        if (!live) return;
        if (!m || m.state === "empty") { setMapStatus("none"); return; }
        if (m.state === "ready") {
          setMap(m); setMapStatus("ready");
          const full = await fetchTopicMap(true);
          if (!live) return;
          const best = full && full.state === "ready" ? full : m;
          if (best !== m) setMap(best);
          cache.map = best; cache.at = Date.now();
          return;
        }
        if (tries >= MAX_POLLS) { setMapStatus("none"); return; }
        setMapStatus("building");
        await wait(POLL_MS);
      }
    })();
    return () => { live = false; };
  }, [enabled]);

  return { dash, map, mapStatus, dashLoading };
}
