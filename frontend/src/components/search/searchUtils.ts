/** Pure helpers of the library search UI (kept apart from the components for fast refresh). */
import type { SearchField, SearchResult, SearchSuggestions } from "../../types";

export const FIELD_LABELS: Record<SearchField, string> = {
  doi: "DOI",
  title: "Title",
  author: "Author",
  topic: "Topic",
  tag: "Tag",
  venue: "Venue",
  abstract: "Abstract",
  summary: "Summary",
  note: "Your note",
  highlight: "Highlight",
  claim: "Claim",
  fulltext: "Full text",
  semantic: "Meaning",
};

/** "Author: Tero Karras", "Topic: A, B +1", "Full text", "Meaning 0.78". */
export function matchChips(hit: SearchResult): { field: SearchField; label: string }[] {
  const out: { field: SearchField; label: string }[] = [];
  for (const f of hit.matched_fields ?? []) {
    const names = hit.matches?.[f as "author" | "topic" | "tag" | "venue"];
    if (names?.length) {
      const shown = names.slice(0, 2).join(", ") + (names.length > 2 ? ` +${names.length - 2}` : "");
      out.push({ field: f, label: `${FIELD_LABELS[f]}: ${shown}` });
    } else if (f === "semantic" && hit.similarity != null) {
      out.push({ field: f, label: `${FIELD_LABELS[f]} ${hit.similarity.toFixed(2)}` });
    } else {
      out.push({ field: f, label: FIELD_LABELS[f] });
    }
  }
  return out;
}

/** Split `text` into marked / unmarked runs. The API's offsets count code points (Python
 * string indices), so astral characters (math italics such as 𝑥) do not shift the marks.
 * Out-of-range, empty or overlapping ranges are clipped and merged: a malformed response
 * degrades to plain text instead of throwing. */
export function splitMarks(text: string, marks: [number, number][]): { text: string; marked: boolean }[] {
  const cps = Array.from(text);
  const n = cps.length;
  const clean = marks
    .map(([s, e]) => [Math.max(0, Math.min(s, n)), Math.max(0, Math.min(e, n))] as const)
    .filter(([s, e]) => e > s)
    .sort((a, b) => a[0] - b[0]);
  const out: { text: string; marked: boolean }[] = [];
  const slice = (a: number, b: number) => cps.slice(a, b).join("");
  let at = 0;
  for (const [s, e] of clean) {
    if (e <= at) continue;
    const start = Math.max(s, at);
    if (start > at) out.push({ text: slice(at, start), marked: false });
    out.push({ text: slice(start, e), marked: true });
    at = e;
  }
  if (at < n) out.push({ text: slice(at, n), marked: false });
  return out;
}

export type SuggestionKind = "paper" | "author" | "topic" | "tag" | "project";
export interface SuggestionItem { kind: SuggestionKind; id: string; name: string; detail?: string }

export const SUGGESTION_SECTIONS: { key: keyof Omit<SearchSuggestions, "query">; kind: SuggestionKind; label: string }[] = [
  { key: "papers", kind: "paper", label: "Papers" },
  { key: "authors", kind: "author", label: "Authors" },
  { key: "topics", kind: "topic", label: "Topics" },
  { key: "tags", kind: "tag", label: "Tags" },
  { key: "projects", kind: "project", label: "Projects" },
];

/** Flatten the suggestion groups into keyboard order (papers, authors, topics, tags, projects). */
export function suggestionItems(s: SearchSuggestions | null): SuggestionItem[] {
  if (!s) return [];
  const out: SuggestionItem[] = [];
  for (const p of s.papers) out.push({ kind: "paper", id: p.id, name: p.title, detail: p.year ? String(p.year) : undefined });
  for (const sec of SUGGESTION_SECTIONS.slice(1)) {
    for (const e of s[sec.key] as { id: string; name: string; papers: number }[]) {
      out.push({ kind: sec.kind, id: e.id, name: e.name, detail: `${e.papers} paper${e.papers === 1 ? "" : "s"}` });
    }
  }
  return out;
}

// Filter URL state (keys, /search mapping, chips) lives in filterState.ts; re-exported here
// because the Library page and its tests have always imported it from this module.
export { FILTER_KEYS, QUERY_PAGE_ALL, buildSearchParams } from "./filterState";
