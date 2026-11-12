import { describe, expect, it } from "vitest";
import {
  FILTER_KEYS, activeFilterChips, addedAfterFor, buildSearchParams, clearFilters,
  effectiveSort, hasActiveFilters, sortOptions,
} from "./filterState";

const NOW = new Date(2026, 10, 12, 15, 30); // 12 Nov 2026, local afternoon
const url = (s: string) => new URLSearchParams(s);
const obj = (p: URLSearchParams) => Object.fromEntries(p);

describe("buildSearchParams", () => {
  it("adds ranking options and paging for a query", () => {
    const p = buildSearchParams(url("q=diffusion&tag=x&mode=semantic&refs=1&sort=year_desc"), 3, 20, NOW);
    expect(obj(p)).toEqual({
      q: "diffusion", tag: "x", mode: "semantic", sort: "year_desc", include_references: "true",
      skip: "40", limit: "20",
    });
  });

  it("defaults a query to hybrid relevance without references, 200 per page for All", () => {
    const p = buildSearchParams(url("q=edm"), 1, 0, NOW);
    expect(p.get("mode")).toBe("hybrid");
    expect(p.get("sort")).toBe("relevance");
    expect(p.get("include_references")).toBe("false");
    expect(p.get("limit")).toBe("200");
    expect(p.get("skip")).toBe("0");
  });

  it("pages browsing on the server with the URL sort, else the settings default", () => {
    const a = buildSearchParams(url("topic=Diffusion%20Models&sort=year_desc"), 2, 20, NOW, "title_asc");
    expect(obj(a)).toEqual({
      topic: "Diffusion Models", sort: "year_desc", skip: "20", limit: "20",
      include_references: "false", snippets: "0",
    });
    const b = buildSearchParams(url(""), 1, 50, NOW, "citations_desc");
    expect(obj(b)).toEqual({ sort: "citations_desc", skip: "0", limit: "50", include_references: "false", snippets: "0" });
    // relevance means nothing without a query
    expect(buildSearchParams(url("sort=relevance"), 1, 50, NOW).get("sort")).toBe("date_desc");
  });

  it("browses 'All' papers per page in pages of 200", () => {
    const p = buildSearchParams(url(""), 3, 0, NOW);
    expect(p.get("limit")).toBe("200");
    expect(p.get("skip")).toBe("400");
    expect(p.get("sort")).toBe("date_desc");
  });

  it("turns the added presets into local midnights as ISO UTC", () => {
    const midnight = (daysBack: number) => new Date(2026, 10, 12 - daysBack).toISOString();
    expect(buildSearchParams(url("added=today"), 1, 20, NOW).get("added_after")).toBe(midnight(0));
    expect(buildSearchParams(url("added=7d"), 1, 20, NOW).get("added_after")).toBe(midnight(7));
    expect(buildSearchParams(url("added=30d"), 1, 20, NOW).get("added_after")).toBe(midnight(30));
    expect(buildSearchParams(url("added=90d"), 1, 20, NOW).get("added_after")).toBe(midnight(90));
    expect(addedAfterFor("nonsense", NOW)).toBeNull();
    expect(buildSearchParams(url("added=nonsense"), 1, 20, NOW).has("added_after")).toBe(false);
  });

  it("passes a custom range through as dates and lets a preset win", () => {
    const r = buildSearchParams(url("added_from=2026-01-05&added_to=2026-02-01"), 1, 20, NOW);
    expect(r.get("added_after")).toBe("2026-01-05");
    expect(r.get("added_before")).toBe("2026-02-01");
    const both = buildSearchParams(url("added=7d&added_from=2026-01-05"), 1, 20, NOW);
    expect(both.get("added_after")).toBe(new Date(2026, 10, 5).toISOString());
    expect(both.has("added_before")).toBe(false);
    expect(buildSearchParams(url("added_from=yesterday"), 1, 20, NOW).has("added_after")).toBe(false);
  });

  it("maps booleans 1/0 to true/false and keeps the other filters", () => {
    const p = buildSearchParams(
      url("has_pdf=1&has_text=0&has_note=1&has_highlights=0&bookmarked=1&reading_status=unread&year_min=2020&year_max=2024&rating_min=4&document_type=book&venue=NeurIPS&project_id=p1&person_id=a1"),
      1, 20, NOW,
    );
    expect(obj(p)).toMatchObject({
      has_pdf: "true", has_text: "false", has_note: "true", has_highlights: "false", bookmarked: "true",
      reading_status: "unread", year_min: "2020", year_max: "2024", rating_min: "4",
      document_type: "book", venue: "NeurIPS", project_id: "p1", person_id: "a1",
    });
    // old links used bookmarked=true
    expect(buildSearchParams(url("bookmarked=true"), 1, 20, NOW).get("bookmarked")).toBe("true");
    // junk is dropped instead of causing a 422
    const junk = buildSearchParams(url("year_min=abc&rating_min=x&has_pdf=maybe"), 1, 20, NOW);
    expect(junk.has("year_min") || junk.has("rating_min") || junk.has("has_pdf")).toBe(false);
  });
});

describe("filter chips", () => {
  const ALL = "tag=t&topic=o&project_id=p1&person_id=a1&venue=ICML&reading_status=reading&bookmarked=1"
    + "&year_min=2020&year_max=2023&added=30d&has_pdf=1&has_text=0&has_note=1&has_highlights=1"
    + "&document_type=lecture_deck&rating_min=3";

  it("lists every active filter with the keys that remove it", () => {
    const chips = activeFilterChips(url(ALL), { person: "Tero Karras", project: "Thesis" });
    const labels = chips.map((c) => c.label);
    expect(labels).toEqual(expect.arrayContaining([
      "Added: last 30 days", "Year: 2020 to 2023", "Status: reading", "Bookmarked", "Has PDF", "No full text",
      "Has note", "Has highlights", "Rating 3+", "Type: Lecture deck", "Project: Thesis", "Author: Tero Karras",
      "Tag: t", "Topic: o", "Venue: ICML",
    ]));
    expect(chips.find((c) => c.id === "year")!.keys).toEqual(["year_min", "year_max"]);
    // every filter key is covered by some chip
    const covered = new Set(chips.flatMap((c) => c.keys));
    for (const k of FILTER_KEYS) expect(covered.has(k)).toBe(true);
  });

  it("describes a custom range and half-open years", () => {
    expect(activeFilterChips(url("added_from=2026-01-01&added_to=2026-02-01"))[0])
      .toMatchObject({ label: "Added: 2026-01-01 to 2026-02-01", keys: ["added_from", "added_to"] });
    expect(activeFilterChips(url("added_from=2026-01-01"))[0].label).toBe("Added: since 2026-01-01");
    expect(activeFilterChips(url("year_min=2020"))[0].label).toBe("Year: from 2020");
    expect(activeFilterChips(url("year_max=2020"))[0].label).toBe("Year: until 2020");
    expect(activeFilterChips(url("q=flow&sort=year_desc&mode=lexical"))).toEqual([]);
  });

  it("clear-all removes every filter key (and the query when asked), keeping the sort", () => {
    const withAll = url(`q=flow&mode=lexical&refs=1&sort=year_desc&added_from=2026-01-01&added_to=2026-02-01&${ALL}`);
    expect(hasActiveFilters(withAll)).toBe(true);
    const kept = clearFilters(withAll);
    expect(kept.toString()).toBe("q=flow&mode=lexical&refs=1&sort=year_desc");
    expect(hasActiveFilters(kept)).toBe(false);
    expect(clearFilters(withAll, true).toString()).toBe("sort=year_desc");
    // dismissing each chip alone leaves no filter behind once all are dismissed
    let cur = withAll;
    for (const chip of activeFilterChips(withAll)) {
      const next = new URLSearchParams(cur);
      chip.keys.forEach((k) => next.delete(k));
      cur = next;
    }
    expect(hasActiveFilters(cur)).toBe(false);
  });
});

describe("sort", () => {
  it("offers relevance only with a query", () => {
    expect(sortOptions(true).map((s) => s.value)).toContain("relevance");
    expect(sortOptions(false).map((s) => s.value)).not.toContain("relevance");
    expect(sortOptions(false).map((s) => s.value)).toEqual(
      ["date_desc", "date_asc", "updated_desc", "year_desc", "year_asc", "title_asc", "rating_desc", "citations_desc"]);
  });

  it("picks the URL sort, else relevance for a query, else the settings default", () => {
    expect(effectiveSort(url("sort=year_asc"), false, "date_desc")).toBe("year_asc");
    expect(effectiveSort(url(""), true, "date_desc")).toBe("relevance");
    expect(effectiveSort(url(""), false, "rating_desc")).toBe("rating_desc");
    expect(effectiveSort(url("sort=relevance"), false, "rating_desc")).toBe("rating_desc");
  });
});
