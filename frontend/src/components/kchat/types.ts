/**
 * Types of the Knowledge Chat trace (tool calls and interim prose) and the pure
 * reducer that folds stream events into it.
 *
 * The backend sends every field below as optional: old saved messages and old
 * servers lack `tool`, `input`, `result`, `is_error`, `links`, `figures`, the
 * `scope` and `text` kinds and the `interim` event, and all of it must still render.
 */
import type { KnowledgeMessage, MessagePaper, SseEvent, StepKind } from "../../types";

export type TraceKind = StepKind | "scope" | "text";

/** The tools the backend runs for the model (and the steps it adds itself: mention, attach). */
export type StepTool =
  | "run_cypher" | "semantic_search" | "load_full_text" | "list_figures"
  | "WebSearch" | "web_presearch" | "mention" | "attach" | "scope";

export type StepFigure = { image_url: string; caption?: string | null; figure_number?: string | number | null };

export type TraceStep = {
  kind?: TraceKind;
  tool?: StepTool | string;
  description: string;
  cypher?: string | null;
  count?: number | null;
  papers?: MessagePaper[];
  /** The arguments the model sent to the tool. */
  input?: Record<string, unknown> | null;
  /** A preview of what the tool returned (at most ~4000 characters). */
  result?: string | null;
  is_error?: boolean;
  /** Web URLs, on web steps. */
  links?: string[];
  figures?: StepFigure[];
  /** Prose the model wrote before a tool call, on `kind: "text"` steps. */
  text?: string;
};

export type StepEvent = TraceStep & { type: "step" };
export type InterimEvent = { type: "interim" };
export type DoneEvent = { type: "done"; conversation_id: string; message_id: string | null; stopped?: boolean };

/** Every event of POST /knowledge-chat/stream: the shared SseEvent widened by what the newer backend adds. */
export type ChatEvent = Exclude<SseEvent, { type: "step" | "done" }> | StepEvent | InterimEvent | DoneEvent;

/** A message as GET /knowledge-chat/conversations/{id}/messages returns it, with the trace and the stopped flag. */
export type SavedMessage = KnowledgeMessage & { steps?: TraceStep[] | null; stopped?: boolean | null };

// ── Folding events into the answer ───────────────────────────────────────────

/** What the stream has built so far for one answer. */
export type Streamed = { text: string; steps: TraceStep[] };

/** Progress lines the backend still sends that say nothing worth a row. */
export const isFiller = (description: string | undefined | null) =>
  !!description && (description === "Sending to Claude…" || description.startsWith("Parsing @mentions"));

/**
 * One step of the stream's reduction. Steps are appended in order; `token` extends the
 * answer text; `interim` says the text streamed so far was prose before a tool call, so it
 * moves out of the answer into the trace as a text step. Anything else leaves the state alone.
 */
export function applyEvent(state: Streamed, ev: ChatEvent): Streamed {
  switch (ev.type) {
    case "step": {
      if (isFiller(ev.description)) return state;
      const { type: _type, ...step } = ev;
      return { ...state, steps: [...state.steps, { ...step, description: step.description ?? "" }] };
    }
    case "token":
      return { ...state, text: state.text + ev.text };
    case "interim": {
      if (!state.text.trim()) return state.text ? { ...state, text: "" } : state;
      return { text: "", steps: [...state.steps, { kind: "text", description: "", text: state.text }] };
    }
    default:
      return state;
  }
}
