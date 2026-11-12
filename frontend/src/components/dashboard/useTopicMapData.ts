import { useEffect, useState } from "react";
import { fetchTopicMap, type TopicMapData } from "./api";

const POLL_MS = 4000, MAX_POLLS = 60;
const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export interface TopicMapPageData {
  map: TopicMapData | null;
  /** loading: first answer pending; building: the first layout is not computed yet; ready; none: no map / failed */
  status: "loading" | "building" | "ready" | "none";
  /** A different cluster count was asked for and is being computed in the background (the old map stays on screen). */
  reclustering: boolean;
}

/** The map for the full page: library points first (fast), then with references; `clusters` re-clusters in the
 * backend, which answers `building` until its background job is done, so this polls like the dashboard does. */
export function useTopicMapData(clusters: number | null): TopicMapPageData {
  const [state, setState] = useState<TopicMapPageData>({ map: null, status: "loading", reclustering: false });

  useEffect(() => {
    let live = true;
    (async () => {
      for (let tries = 0; live; tries++) {
        const m = await fetchTopicMap(false, clusters);
        if (!live) return;
        if (!m || m.state === "empty") { setState((s) => ({ ...s, status: s.map ? "ready" : "none", reclustering: false })); return; }
        if (m.state === "ready") {
          setState({ map: m, status: "ready", reclustering: false });
          const full = await fetchTopicMap(true, clusters);
          if (!live) return;
          setState({ map: full && full.state === "ready" ? full : m, status: "ready", reclustering: false });
          return;
        }
        if (tries >= MAX_POLLS) { setState((s) => ({ ...s, status: s.map ? "ready" : "none", reclustering: false })); return; }
        setState((s) => (s.map ? { ...s, reclustering: true } : { map: null, status: "building", reclustering: false }));
        await wait(POLL_MS);
      }
    })();
    return () => { live = false; };
  }, [clusters]);

  return state;
}
