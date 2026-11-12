/**
 * The tool calls of one answer, as in the thesis desk: a compact row per call in the order
 * they happened, collapsed by default (status dot, tool label, one-line summary of the
 * arguments, result count, chevron); expanded they show the query or arguments, a preview of
 * the result, the papers and figures it touched and the web pages it found.
 *
 * Ported from the desk's `ToolCall` / `summariseInput` (components/Chat.tsx), with
 * PaperManager's own tools. Steps saved before the trace carried `tool`, `input` and
 * `result` render as informative as before: description, Cypher, papers.
 */
import { useState } from "react";
import { apiUrl } from "../../api/client";
import type { MessagePaper } from "../../types";
import { Markdown } from "./Markdown";
import { hostOf, summariseInput, toolOf } from "./sources";
import type { TraceStep } from "./types";

export { summariseInput } from "./sources";

export const TOOL_LABEL: Record<string, string> = {
  run_cypher: "Graph", semantic_search: "Search", load_full_text: "Read", list_figures: "Figures",
  WebSearch: "Web", web_presearch: "Web", mention: "Scope", scope: "Scope", attach: "Attach",
};

/** The arguments worth showing: everything but the description (already the row's summary). */
function shownInput(step: TraceStep): string {
  const { description: _d, ...rest } = (step.input ?? {}) as Record<string, unknown>;
  return Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
}

const isWeb = (u: string) => /^https?:\/\//i.test(u);

export function ToolCall({ step, onPaper, onFigure, pending }: {
  step: TraceStep;
  onPaper: (p: MessagePaper) => void;
  onFigure?: (src: string, caption: string) => void;
  /** The call is the last one and the answer has not started: show a spinner. */
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const tool = toolOf(step);
  const cypher = tool === "run_cypher" ? (step.cypher || (typeof step.input?.query === "string" ? step.input.query : "")) : "";
  // Vector searches saved before the trace keep their query in `cypher` behind a marker; it is the summary already.
  const showCypher = !!cypher && !cypher.startsWith("[vector search]");
  const inputJson = tool === "run_cypher" ? "" : shownInput(step);
  const result = step.result?.trim() ? step.result : "";
  const links = (step.links ?? []).filter(isWeb);
  const figures = step.figures ?? [];
  const detail = showCypher || !!inputJson || !!result || !!step.papers?.length || figures.length > 0 || links.length > 0;
  const summary = summariseInput(tool, step.input, step.description, step.papers);
  const status = step.is_error ? "error" : "done";

  return (
    <div className={`kc-tool ${status} ${open ? "open" : ""}`}>
      <button type="button" className="kc-tool-head" aria-expanded={open}
        onClick={() => detail && setOpen((o) => !o)} style={detail ? undefined : { cursor: "default" }}>
        <span className="kc-tool-dot" />
        <span className="kc-tool-name">{tool ? TOOL_LABEL[tool] ?? tool : "Library"}</span>
        <span className="kc-tool-sum">{summary}</span>
        {pending && <span className="kc-spinner" role="status" aria-label="running" />}
        {step.count != null && <span className="kc-tool-count">{step.count}</span>}
        {detail && <span className="kc-chev">{open ? "▾" : "▸"}</span>}
      </button>
      {open && (
        <div className="kc-tool-body">
          {showCypher && <pre className="kc-tool-input"><code>{cypher}</code></pre>}
          {inputJson && <pre className="kc-tool-input">{inputJson}</pre>}
          {result && <pre className={`kc-tool-result ${step.is_error ? "error" : ""}`}>{result}</pre>}
          {!!step.papers?.length && (
            <div className="kc-src-list">
              {step.papers.map((p) => (
                <button type="button" key={p.id} className="kc-src-chip k-paper" onClick={() => onPaper(p)}>
                  <span>{p.title ?? p.id}{p.year ? ` · ${p.year}` : ""}</span>
                </button>
              ))}
            </div>
          )}
          {figures.length > 0 && (
            <div className="kc-tool-figs">
              {figures.map((f, i) => {
                const src = apiUrl(f.image_url);
                const caption = f.caption || (f.figure_number != null ? `Figure ${f.figure_number}` : "");
                return (
                  <button type="button" key={`${f.image_url}-${i}`} title={caption || "Open the figure beside the chat"}
                    onClick={() => onFigure?.(src, caption)}>
                    <img src={src} alt={caption} loading="lazy" />
                  </button>
                );
              })}
            </div>
          )}
          {links.length > 0 && (
            <div className="kc-src-list">
              {links.map((u) => (
                <a key={u} className="kc-src-chip k-web" href={u} target="_blank" rel="noreferrer" title={u}><span>{hostOf(u)}</span></a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Prose the model wrote before a tool call: a muted line inside the trace, maths rendered. */
export function TraceText({ text }: { text: string }) {
  if (!text.trim()) return null;
  return <div className="kc-trace-text"><Markdown text={text} /></div>;
}

/** All of an answer's trace rows, in order. */
export function Trace({ steps, waiting, onPaper, onFigure }: {
  steps: TraceStep[];
  /** The answer is streaming and no answer text has arrived yet. */
  waiting?: boolean;
  onPaper: (p: MessagePaper) => void;
  onFigure?: (src: string, caption: string) => void;
}) {
  const visible = steps.map((s, i) => ({ s, i })).filter(({ s }) => s.kind !== "text" || (s.text ?? "").trim());
  if (!visible.length) return null;
  let lastTool = -1;
  visible.forEach(({ s, i }) => { if (s.kind !== "text") lastTool = i; });
  return (
    <div className="kc-steps">
      {visible.map(({ s, i }) => s.kind === "text"
        ? <TraceText key={i} text={s.text ?? ""} />
        : <ToolCall key={i} step={s} onPaper={onPaper} onFigure={onFigure} pending={waiting && i === lastTool} />)}
    </div>
  );
}
