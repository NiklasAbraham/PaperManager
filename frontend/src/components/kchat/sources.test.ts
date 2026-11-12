import { describe, expect, it } from "vitest";
import { answerSources, summariseInput } from "./sources";
import { applyEvent, type ChatEvent, type TraceStep } from "./types";

const A = "c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e";
const B = "11111111-2222-4333-8444-555555555555";
const C = "99999999-aaaa-4bbb-8ccc-dddddddddddd";
const D = "00000000-aaaa-4bbb-8ccc-dddddddddddd";

describe("summariseInput", () => {
  it("run_cypher: the description, else the first line of the query", () => {
    expect(summariseInput("run_cypher", { query: "MATCH (p:Paper)\nRETURN p" }, "Count papers")).toBe("Count papers");
    expect(summariseInput("run_cypher", { query: "\nMATCH (p:Paper)\nRETURN p" }, "")).toBe("MATCH (p:Paper)");
  });
  it("semantic_search: the query in quotes", () => {
    expect(summariseInput("semantic_search", { query: "diffusion" }, "x")).toBe("“diffusion”");
  });
  it("load_full_text and list_figures: the paper title from papers, else the description", () => {
    expect(summariseInput("load_full_text", { paper_id: A }, "Reading", [{ id: A, title: "RFdiffusion" }])).toBe("RFdiffusion");
    expect(summariseInput("list_figures", { paper_id: A }, "Figures of AF3")).toBe("Figures of AF3");
  });
  it("WebSearch and mention", () => {
    expect(summariseInput("WebSearch", { query: "alphafold 3 release" }, "")).toBe("alphafold 3 release");
    expect(summariseInput("web_presearch", { query: "q" }, "")).toBe("q");
    expect(summariseInput("mention", { type: "topic", value: "Diffusion" }, "Papers in topic")).toBe("@topic:Diffusion");
  });
  it("falls back to the description and truncates at about 120 characters", () => {
    expect(summariseInput("mention", {}, "Papers in topic X")).toBe("Papers in topic X");
    expect(summariseInput(undefined, undefined, "plain")).toBe("plain");
    const long = summariseInput("semantic_search", { query: "x".repeat(300) }, "");
    expect(long.length).toBeLessThanOrEqual(120);
    expect(long.endsWith("…")).toBe(true);
  });
});

describe("answerSources", () => {
  const steps: TraceStep[] = [
    { tool: "semantic_search", kind: "search", description: "Find", input: { query: "diffusion" }, papers: [{ id: A, title: "AF3", year: 2024 }, { id: B, title: "DDPM", year: 2020 }] },
    { tool: "load_full_text", kind: "fulltext", description: "Reading", papers: [{ id: B, title: "DDPM" }] },
    { tool: "list_figures", kind: "figures", description: "Figures", papers: [{ id: C, title: "Score SDE" }] },
    { tool: "attach", kind: "attach", description: "Attached", papers: [{ id: D, title: "Mine" }] },
    { kind: "text", description: "", text: "Let me look." },
    { tool: "run_cypher", kind: "cypher", description: "Count", cypher: "MATCH (n) RETURN n" },
  ];

  it("merges by paper id with the verbs that apply, ranked cited/read, figures, attached, found", () => {
    const text = `See [AF3 paper](/paper/${A}) and [DDPM](/paper/${B}).`;
    const s = answerSources(steps, text);
    expect(s.papers.map((p) => [p.id, p.verbs])).toEqual([
      [A, ["cited", "found"]],
      [B, ["cited", "read", "found"]],
      [C, ["figures"]],
      [D, ["attached"]],
    ]);
    expect(s.papers[0]).toMatchObject({ title: "AF3", year: 2024, rank: 0 });
  });

  it("keeps first-seen order within a rank and puts read before merely found", () => {
    const s = answerSources(steps, "");
    expect(s.papers.map((p) => p.id)).toEqual([B, C, D, A]);
    expect(s.papers.map((p) => p.rank)).toEqual([0, 1, 2, 3]);
  });

  it("takes attached papers from the argument too, and a read named only in the arguments", () => {
    const s = answerSources([{ tool: "load_full_text", description: "Reading Foo", input: { paper_id: C } }], "", [{ id: D, title: "Att" }]);
    expect(s.papers.map((p) => [p.id, p.title, p.verbs])).toEqual([[C, "Reading Foo", ["read"]], [D, "Att", ["attached"]]]);
  });

  it("collects web links deduplicated by URL, labelled by host, and ignores non-http links", () => {
    const s = answerSources([
      { tool: "WebSearch", description: "web", input: { query: "q" }, links: ["https://www.nature.com/a", "https://www.nature.com/a", "https://arxiv.org/abs/1", "javascript:alert(1)"] },
      { tool: "web_presearch", description: "pre", links: ["https://arxiv.org/abs/1"] },
    ], "");
    expect(s.web).toEqual([
      { url: "https://www.nature.com/a", label: "nature.com" },
      { url: "https://arxiv.org/abs/1", label: "arxiv.org" },
    ]);
    expect(s.papers).toEqual([]);
  });

  it("counts searches (library, graph, web) with their summaries, not reads or scope", () => {
    const s = answerSources([
      ...steps,
      { tool: "WebSearch", description: "", input: { query: "latest news" } },
      { kind: "scope", description: "Papers in topic X", count: 4 },
    ], "");
    expect(s.searches).toEqual(["“diffusion”", "Count", "latest news"]);
  });

  it("papers put in context by scope steps are not sources", () => {
    const s = answerSources([
      { kind: "scope", tool: "mention", description: "Papers in topic X", input: { type: "topic", value: "X" }, papers: [{ id: D, title: "In context only" }] },
    ], "");
    expect(s.papers).toEqual([]);
  });

  it("old messages: no steps, only the cited papers; old kinds still count", () => {
    expect(answerSources(null, `[X](/paper/${A})`).papers).toEqual([{ id: A, title: "X", year: null, verbs: ["cited"], rank: 0 }]);
    expect(answerSources(undefined, "no links").papers).toEqual([]);
    const old = answerSources([{ kind: "search", description: "Find diffusion papers", cypher: "[vector search] diffusion", papers: [{ id: A, title: "AF3" }] }], "");
    expect(old.searches).toEqual(["Find diffusion papers"]);
    expect(old.papers[0].verbs).toEqual(["found"]);
  });
});

describe("applyEvent", () => {
  const start = { text: "", steps: [] as TraceStep[] };
  const run = (evs: ChatEvent[]) => evs.reduce(applyEvent, start);

  it("appends steps in order and skips the filler ones", () => {
    const s = run([
      { type: "step", description: "Sending to Claude…" },
      { type: "step", description: "Parsing @mentions in your question", count: 0 },
      { type: "step", kind: "scope", description: "Papers in topic X" },
      { type: "step", tool: "run_cypher", description: "Count", cypher: "MATCH (n) RETURN n", input: { query: "MATCH (n) RETURN n" }, result: "[]" },
    ]);
    expect(s.steps.map((x) => x.description)).toEqual(["Papers in topic X", "Count"]);
    expect(s.steps[1]).toMatchObject({ tool: "run_cypher", result: "[]" });
    expect(s.steps[1]).not.toHaveProperty("type");
  });

  it("interim moves the text streamed so far into the trace as a text step and resets the answer", () => {
    const s = run([
      { type: "token", text: "Let me " }, { type: "token", text: "check." },
      { type: "interim" },
      { type: "step", tool: "semantic_search", description: "Find" },
      { type: "token", text: "The answer." },
    ]);
    expect(s.steps).toEqual([
      { kind: "text", description: "", text: "Let me check." },
      { tool: "semantic_search", description: "Find" },
    ]);
    expect(s.text).toBe("The answer.");
  });

  it("an interim with nothing to move changes nothing (whitespace is dropped)", () => {
    expect(run([{ type: "interim" }])).toBe(start);
    expect(run([{ type: "token", text: " \n" }, { type: "interim" }])).toEqual({ text: "", steps: [] });
  });

  it("leaves the state alone for other events", () => {
    expect(applyEvent(start, { type: "status", text: "x" })).toBe(start);
    expect(applyEvent(start, { type: "done", conversation_id: "c", message_id: null, stopped: true })).toBe(start);
  });
});
