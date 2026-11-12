/** Named Cypher queries kept in the browser (localStorage), newest first. */

export const SAVED_QUERIES_KEY = "pm.graph.savedQueries";

export interface SavedQuery {
  name: string;
  query: string;
  saved_at: string;
}

function isSavedQuery(v: unknown): v is SavedQuery {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return typeof o.name === "string" && typeof o.query === "string" && typeof o.saved_at === "string";
}

export function loadSavedQueries(): SavedQuery[] {
  try {
    const raw = localStorage.getItem(SAVED_QUERIES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isSavedQuery) : [];
  } catch {
    return [];
  }
}

function persist(list: SavedQuery[]): SavedQuery[] {
  try {
    localStorage.setItem(SAVED_QUERIES_KEY, JSON.stringify(list));
  } catch {
    // storage full or blocked: the in-memory list still works for this session
  }
  return list;
}

/** Name used when the user saves without typing one: the first line, shortened. */
export function defaultQueryName(query: string): string {
  const first = query.trim().split("\n")[0].trim();
  return first.length > 40 ? `${first.slice(0, 39)}…` : first || "Untitled query";
}

/** Save `query` under `name`; an existing entry with the same name is replaced. */
export function saveQuery(name: string, query: string, now: Date = new Date()): SavedQuery[] {
  const clean = name.trim() || defaultQueryName(query);
  const entry: SavedQuery = { name: clean, query, saved_at: now.toISOString() };
  return persist([entry, ...loadSavedQueries().filter((q) => q.name !== clean)]);
}

export function deleteSavedQuery(name: string): SavedQuery[] {
  return persist(loadSavedQueries().filter((q) => q.name !== name));
}
