import { beforeEach, describe, expect, it } from "vitest";
import {
  SAVED_QUERIES_KEY,
  defaultQueryName,
  deleteSavedQuery,
  loadSavedQueries,
  saveQuery,
} from "./savedQueries";

beforeEach(() => localStorage.clear());

describe("savedQueries", () => {
  it("starts empty and survives broken storage", () => {
    expect(loadSavedQueries()).toEqual([]);
    localStorage.setItem(SAVED_QUERIES_KEY, "{not json");
    expect(loadSavedQueries()).toEqual([]);
    localStorage.setItem(SAVED_QUERIES_KEY, JSON.stringify({ a: 1 }));
    expect(loadSavedQueries()).toEqual([]);
  });

  it("drops malformed entries but keeps good ones", () => {
    localStorage.setItem(
      SAVED_QUERIES_KEY,
      JSON.stringify([{ name: "ok", query: "RETURN 1", saved_at: "2026-11-01T00:00:00.000Z" }, { name: 3 }, null]),
    );
    expect(loadSavedQueries().map((q) => q.name)).toEqual(["ok"]);
  });

  it("saves newest first with name, query and timestamp", () => {
    saveQuery("one", "RETURN 1", new Date("2026-11-01T10:00:00Z"));
    const list = saveQuery("two", "RETURN 2", new Date("2026-11-02T10:00:00Z"));
    expect(list.map((q) => q.name)).toEqual(["two", "one"]);
    expect(list[0]).toEqual({ name: "two", query: "RETURN 2", saved_at: "2026-11-02T10:00:00.000Z" });
    expect(JSON.parse(localStorage.getItem(SAVED_QUERIES_KEY)!)).toEqual(list);
    expect(loadSavedQueries()).toEqual(list);
  });

  it("replaces an entry saved under the same name", () => {
    saveQuery("same", "RETURN 1", new Date("2026-11-01T10:00:00Z"));
    saveQuery("other", "RETURN 2", new Date("2026-11-01T11:00:00Z"));
    const list = saveQuery("same", "RETURN 3", new Date("2026-11-01T12:00:00Z"));
    expect(list.map((q) => [q.name, q.query])).toEqual([["same", "RETURN 3"], ["other", "RETURN 2"]]);
  });

  it("names an unnamed query after its first line, shortened", () => {
    expect(defaultQueryName("  MATCH (n)\nRETURN n")).toBe("MATCH (n)");
    expect(defaultQueryName("x".repeat(60))).toHaveLength(40);
    expect(defaultQueryName("   ")).toBe("Untitled query");
    expect(saveQuery("  ", "MATCH (t:Tag) RETURN t")[0].name).toBe("MATCH (t:Tag) RETURN t");
  });

  it("deletes by name", () => {
    saveQuery("a", "RETURN 1");
    saveQuery("b", "RETURN 2");
    expect(deleteSavedQuery("a").map((q) => q.name)).toEqual(["b"]);
    expect(loadSavedQueries().map((q) => q.name)).toEqual(["b"]);
    expect(deleteSavedQuery("missing").map((q) => q.name)).toEqual(["b"]);
  });
});
