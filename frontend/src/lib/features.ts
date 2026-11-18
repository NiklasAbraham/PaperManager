import { useSyncExternalStore } from "react";

// Optional features of the instance. Today only the paper feed: GET /feed/status answers
// {"enabled": false} when it is off, and the navigation shows its entry only when it is on.
// Fetched once per page load after login and kept here.
const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

let features: ReadonlySet<string> = new Set();
let loaded = false;
const listeners = new Set<() => void>();

export async function loadFeatures(): Promise<void> {
  if (loaded) return;
  try {
    const res = await fetch(`${BASE}/feed/status`, { credentials: "include" });
    if (!res.ok) return; // not logged in yet, or an older backend: try again later
    const data = await res.json();
    loaded = true;
    features = new Set(data && data.enabled === true ? ["feed"] : []);
    listeners.forEach((l) => l());
  } catch {
    // Offline: the optional entry just stays hidden.
  }
}

/** The optional features switched on for this instance, e.g. `has("feed")`. */
export function useFeatures(): ReadonlySet<string> {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => features,
  );
}

/** For tests: forget what was loaded. */
export function resetFeatures(): void {
  features = new Set();
  loaded = false;
  listeners.forEach((l) => l());
}
