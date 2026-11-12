/** URL state of the Library filters: which URL keys narrow the list, how they map to the
 * /search parameters, the chips that show them and the sort choices. Pure functions, so
 * a filtered search is a shareable URL and the mapping is unit-tested. */

/** URL keys that narrow the paper list on the Library page (the query itself is "q"). */
export const FILTER_KEYS = [
  "tag", "topic", "project_id", "person_id", "venue",
  "reading_status", "bookmarked",
  "year_min", "year_max",
  "added", "added_from", "added_to",
  "has_pdf", "has_text", "has_note", "has_highlights",
  "document_type", "rating_min",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

/** Query-only options that go away together with the query. */
export const QUERY_KEYS = ["q", "mode", "refs"] as const;

export const QUERY_PAGE_ALL = 200; // page size when "All" papers per page is set

/** Presets of the "Added" filter and how many days back each reaches (0 = since midnight). */
export const ADDED_PRESETS = { today: 0, "7d": 7, "30d": 30, "90d": 90 } as const;
export type AddedPreset = keyof typeof ADDED_PRESETS;
export const ADDED_LABELS: Record<AddedPreset, string> = {
  today: "Today", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days",
};

export const BOOL_KEYS = ["bookmarked", "has_pdf", "has_text", "has_note", "has_highlights"] as const;
const BOOL_LABELS: Record<(typeof BOOL_KEYS)[number], [string, string]> = {
  bookmarked: ["Bookmarked", "Not bookmarked"],
  has_pdf: ["Has PDF", "No PDF"],
  has_text: ["Has full text", "No full text"],
  has_note: ["Has note", "No note"],
  has_highlights: ["Has highlights", "No highlights"],
};

export const STATUS_LABELS: Record<string, string> = { unread: "Unread", reading: "Reading", read: "Read" };
export const DOCUMENT_TYPES: Record<string, string> = {
  paper: "Paper", book: "Book", lecture_deck: "Lecture deck", news_article: "News article",
};

export const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "date_desc", label: "Newest added" },
  { value: "date_asc", label: "Oldest added" },
  { value: "updated_desc", label: "Recently updated" },
  { value: "year_desc", label: "Year, new to old" },
  { value: "year_asc", label: "Year, old to new" },
  { value: "title_asc", label: "Title A to Z" },
  { value: "rating_desc", label: "Rating" },
  { value: "citations_desc", label: "Citations" },
];

/** Sort choices to offer: relevance only makes sense with a query. */
export function sortOptions(hasQuery: boolean) {
  return hasQuery ? SORT_OPTIONS : SORT_OPTIONS.filter((s) => s.value !== "relevance");
}

/** The sort in effect: the URL's, else relevance for a query, else the settings default. */
export function effectiveSort(url: URLSearchParams, hasQuery: boolean, defaultSort = "date_desc"): string {
  const s = url.get("sort");
  if (s && (hasQuery || s !== "relevance")) return s;
  return hasQuery ? "relevance" : defaultSort;
}

/** "1"/"true" -> "true", "0"/"false" -> "false", anything else -> null. */
export function boolParam(v: string | null): "true" | "false" | null {
  if (v === "1" || v === "true") return "true";
  if (v === "0" || v === "false") return "false";
  return null;
}

/** Start of the "Added" window: local midnight N days ago, as an ISO UTC instant. */
export function addedAfterFor(preset: string | null, now: Date): string | null {
  if (!preset || !(preset in ADDED_PRESETS)) return null;
  const days = ADDED_PRESETS[preset as AddedPreset];
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - days).toISOString();
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const INT_RE = /^\d+$/;

/** The /search parameters for a Library URL: the filters always, plus ranking options
 * (mode, references) when there is a query. Both listings are paged by the server
 * (`perPage` 0 = "All" = 200 per page); browsing sorts by the URL's sort or `defaultSort`. */
export function buildSearchParams(
  url: URLSearchParams,
  page: number,
  perPage: number,
  now: Date = new Date(),
  defaultSort = "date_desc",
): URLSearchParams {
  const out = new URLSearchParams();
  const q = url.get("q")?.trim();
  if (q) out.set("q", q);

  for (const k of ["tag", "topic", "project_id", "person_id", "venue", "reading_status", "document_type"] as const) {
    const v = url.get(k);
    if (v) out.set(k, v);
  }
  for (const k of ["year_min", "year_max", "rating_min"] as const) {
    const v = url.get(k);
    if (v && INT_RE.test(v)) out.set(k, v);
  }
  for (const k of BOOL_KEYS) {
    const v = boolParam(url.get(k));
    if (v) out.set(k, v);
  }

  const after = addedAfterFor(url.get("added"), now);
  if (after) {
    out.set("added_after", after);
  } else {
    const from = url.get("added_from");
    const to = url.get("added_to");
    if (from && DATE_RE.test(from)) out.set("added_after", from);
    if (to && DATE_RE.test(to)) out.set("added_before", to);
  }

  const size = perPage || QUERY_PAGE_ALL;
  out.set("skip", String((Math.max(1, page) - 1) * size));
  out.set("limit", String(size));
  out.set("sort", effectiveSort(url, !!q, defaultSort));
  if (q) {
    out.set("mode", url.get("mode") || "hybrid");
    out.set("include_references", url.get("refs") === "1" ? "true" : "false");
  } else {
    out.set("include_references", "false");
    out.set("snippets", "0");
  }
  return out;
}

export interface FilterChip {
  id: string;
  label: string;
  /** URL keys removed when the chip is dismissed. */
  keys: FilterKey[];
}

/** The active filters as chips, in a stable order. `names` resolves ids to display names. */
export function activeFilterChips(
  url: URLSearchParams,
  names: { person?: string; project?: string } = {},
): FilterChip[] {
  const chips: FilterChip[] = [];
  const get = (k: FilterKey) => url.get(k) ?? "";

  const added = get("added");
  const from = get("added_from");
  const to = get("added_to");
  if (added) {
    chips.push({
      id: "added", keys: ["added", "added_from", "added_to"],
      label: `Added: ${ADDED_LABELS[added as AddedPreset]?.toLowerCase() ?? added}`,
    });
  } else if (from || to) {
    const label = from && to ? `${from} to ${to}` : from ? `since ${from}` : `until ${to}`;
    chips.push({ id: "added_range", keys: ["added_from", "added_to"], label: `Added: ${label}` });
  }

  const y0 = get("year_min");
  const y1 = get("year_max");
  if (y0 || y1) {
    const label = y0 && y1 ? (y0 === y1 ? y0 : `${y0} to ${y1}`) : y0 ? `from ${y0}` : `until ${y1}`;
    chips.push({ id: "year", keys: ["year_min", "year_max"], label: `Year: ${label}` });
  }

  const status = get("reading_status");
  if (status) chips.push({ id: "reading_status", keys: ["reading_status"], label: `Status: ${STATUS_LABELS[status]?.toLowerCase() ?? status}` });

  for (const k of BOOL_KEYS) {
    const v = boolParam(url.get(k));
    if (v) chips.push({ id: k, keys: [k], label: BOOL_LABELS[k][v === "true" ? 0 : 1] });
  }

  const rating = get("rating_min");
  if (rating) chips.push({ id: "rating_min", keys: ["rating_min"], label: `Rating ${rating}+` });
  const type = get("document_type");
  if (type) chips.push({ id: "document_type", keys: ["document_type"], label: `Type: ${DOCUMENT_TYPES[type] ?? type}` });

  const project = get("project_id");
  if (project) chips.push({ id: "project_id", keys: ["project_id"], label: `Project: ${names.project ?? project}` });
  const person = get("person_id");
  if (person) chips.push({ id: "person_id", keys: ["person_id"], label: `Author: ${names.person ?? "…"}` });
  const tag = get("tag");
  if (tag) chips.push({ id: "tag", keys: ["tag"], label: `Tag: ${tag}` });
  const topic = get("topic");
  if (topic) chips.push({ id: "topic", keys: ["topic"], label: `Topic: ${topic}` });
  const venue = get("venue");
  if (venue) chips.push({ id: "venue", keys: ["venue"], label: `Venue: ${venue}` });
  return chips;
}

/** A copy of `url` without the given filter keys (and, with `query`, without the query). */
export function withoutKeys(url: URLSearchParams, keys: readonly string[]): URLSearchParams {
  const next = new URLSearchParams(url);
  keys.forEach((k) => next.delete(k));
  return next;
}

/** "Clear all": every filter key, and with `query` the query and its options too. The sort stays. */
export function clearFilters(url: URLSearchParams, query = false): URLSearchParams {
  return withoutKeys(url, query ? [...FILTER_KEYS, ...QUERY_KEYS] : FILTER_KEYS);
}

export const hasActiveFilters = (url: URLSearchParams) => FILTER_KEYS.some((k) => !!url.get(k));
