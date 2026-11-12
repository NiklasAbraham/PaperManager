/**
 * Which library papers (and web pages) one answer drew on, built from its trace.
 *
 * Ported from the thesis desk's `sources.ts` (every tool call attributed to a source,
 * merged by identity, with the verbs that were done to it), narrowed to what Knowledge
 * Chat has: papers by id, web pages by URL and a count of searches.
 */
import type { MessagePaper } from "../../types";
import { citedPapers } from "./sections";
import type { TraceStep } from "./types";

export type Verb = "cited" | "read" | "figures" | "attached" | "found";

/** Strongest first; a source ranks by its strongest verb. */
const RANK: Record<Verb, number> = { cited: 0, read: 0, figures: 1, attached: 2, found: 3 };
const ORDER: Verb[] = ["cited", "read", "figures", "attached", "found"];

export type PaperSource = { id: string; title: string; year?: number | null; verbs: Verb[]; rank: number };
export type WebSource = { url: string; label: string };
export type AnswerSources = {
  papers: PaperSource[];
  web: WebSource[];
  /** One summary per search the model ran (library searches, graph queries, web searches). */
  searches: string[];
};

export const hostOf = (u: string) => {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
};

const SEARCH_TOOLS = new Set(["semantic_search", "run_cypher", "WebSearch", "web_presearch"]);
const KIND_TOOL: Record<string, string> = {
  cypher: "run_cypher", search: "semantic_search", fulltext: "load_full_text", figures: "list_figures",
  web: "WebSearch", attach: "attach", scope: "scope",
};

/** The tool a step belongs to: its `tool`, or the one its (older) `kind` implies. */
export const toolOf = (s: Pick<TraceStep, "tool" | "kind">): string | undefined =>
  s.tool ?? (s.kind ? KIND_TOOL[s.kind] : undefined);

const clip = (s: string, n = 120) => (s.length > n ? `${s.slice(0, n - 3)}…` : s);

/** A short one-line summary of what a tool call was about (the row's text, the search count's tooltip). */
export function summariseInput(
  tool: string | undefined, input: Record<string, unknown> | null | undefined, description?: string | null, papers?: MessagePaper[],
): string {
  const inp = input && typeof input === "object" ? input : {};
  const str = (k: string) => (typeof inp[k] === "string" ? (inp[k] as string).trim() : "");
  const desc = (description ?? "").trim();
  const paperTitle = papers?.find((p) => p.title)?.title?.trim() ?? "";
  let out = "";
  switch (tool) {
    case "run_cypher":
      out = desc || str("query").split("\n").find((l) => l.trim())?.trim() || "";
      break;
    case "semantic_search":
      out = str("query") ? `“${str("query")}”` : "";
      break;
    case "load_full_text":
    case "list_figures":
      out = paperTitle || desc;
      break;
    case "WebSearch":
    case "web_presearch":
      out = str("query") || str("prompt");
      break;
    case "mention": {
      const type = str("type") || str("kind"), value = str("value") || str("name");
      out = type && value ? `@${type}:${value}` : "";
      break;
    }
  }
  return clip(out || desc);
}

type Acc = { id: string; title: string; year?: number | null; verbs: Set<Verb> };

/**
 * One Source per library paper the answer drew on, merged by paper id: cited in the text
 * (`[title](/paper/<id>)`), read in full, its figures listed, attached by the user, or just
 * returned by one of the model's searches (semantic search, a graph query). Ranked cited/read, figures, attached, found; within a rank in the order
 * first seen. `steps` may be empty (messages saved before the trace existed): then only the
 * cited papers remain.
 */
export function answerSources(
  steps: TraceStep[] | null | undefined, text: string, attached: MessagePaper[] = [],
): AnswerSources {
  const papers = new Map<string, Acc>();
  const web = new Map<string, WebSource>();
  const searches: string[] = [];

  const touch = (id: string, verb: Verb, title?: string | null, year?: number | null) => {
    if (!id) return;
    let a = papers.get(id);
    if (!a) { a = { id, title: "", year: null, verbs: new Set() }; papers.set(id, a); }
    if (!a.title && title) a.title = title;
    if (a.year == null && year != null) a.year = year;
    a.verbs.add(verb);
  };

  for (const s of steps ?? []) {
    if (s.kind === "text") continue;
    const tool = toolOf(s);
    if (tool && SEARCH_TOOLS.has(tool)) {
      const sum = summariseInput(tool, s.input, s.description, s.papers);
      searches.push(sum || (tool === "WebSearch" || tool === "web_presearch" ? "web search" : "library search"));
    }
    if (tool === "WebSearch" || tool === "web_presearch") {
      for (const url of s.links ?? []) {
        if (/^https?:\/\//i.test(url) && !web.has(url)) web.set(url, { url, label: hostOf(url) });
      }
      continue;
    }
    const verb: Verb | null =
      tool === "load_full_text" ? "read" : tool === "list_figures" ? "figures" : tool === "attach" ? "attached"
        : tool === "semantic_search" || tool === "run_cypher" ? "found" : null;
    // Scope steps (@mentions, the automatic selection) put papers in context; those are listed
    // under "N in context", not as sources, since no tool of the model touched them.
    if (!verb) continue;
    const listed = s.papers ?? [];
    for (const p of listed) touch(p.id, verb, p.title, p.year);
    // A read or figure listing that names its paper only in the arguments.
    const argId = typeof s.input?.paper_id === "string" ? (s.input.paper_id as string) : "";
    if (argId && (verb === "read" || verb === "figures") && !listed.some((p) => p.id === argId)) {
      touch(argId, verb, s.description || null);
    }
  }
  for (const p of attached) touch(p.id, "attached", p.title, p.year);
  for (const c of citedPapers(text)) touch(c.id, "cited", c.title);

  const ranked = [...papers.values()].map((a, i) => {
    const verbs = ORDER.filter((v) => a.verbs.has(v));
    return { i, source: { id: a.id, title: a.title || a.id.slice(0, 8), year: a.year, verbs, rank: Math.min(...verbs.map((v) => RANK[v])) } as PaperSource };
  });
  ranked.sort((x, y) => x.source.rank - y.source.rank || x.i - y.i);
  return { papers: ranked.map((r) => r.source), web: [...web.values()], searches };
}

export const hasSources = (s: AnswerSources) => s.papers.length > 0 || s.web.length > 0 || s.searches.length > 0;
