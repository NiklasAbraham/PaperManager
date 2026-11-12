// Card layout adapted from the thesis desk's ConceptBlock; the views are PaperManager's
// concept views, adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
import { useState, type ReactNode } from "react";
import type { ConceptSpec } from "../../types";
import AnimView from "../concepts/AnimView";
import FormulaView from "../concepts/FormulaView";
import GraphView from "../concepts/GraphView";
import TextView from "../concepts/TextView";

/**
 * A caption cut off mid-sentence (older cards were trimmed by length) ends at its
 * last whole sentence instead.
 */
export function tidyCaption(text: string): string {
  const t = text.trim();
  if (!t || /[.!?)\]"']$/.test(t)) return t;
  const end = Math.max(t.lastIndexOf(". "), t.lastIndexOf("? "), t.lastIndexOf("! "));
  return end > t.length / 3 ? t.slice(0, end + 1) : `${t}…`;
}

/**
 * Playback speeds offered on animation cards; the active one (and pause) is drawn filled. Cards start at
 * DEFAULT_SPEED: generated animations run too fast at 1x (as on the desk, from which both are ported).
 */
const SPEEDS = [0.25, 0.5, 1, 2];
export const DEFAULT_SPEED = 0.5;

const KIND: Record<ConceptSpec["type"], string> = {
  formula: "formula", graph: "graph", "2d-text": "background", "2d-anim": "animation",
};

interface Props {
  spec: ConceptSpec;
  /** Shown when the spec has no title. */
  label?: string;
  /** Extra controls at the end of the header (e.g. regenerate). */
  actions?: ReactNode;
  /** Called once per spec when an animation or graph fails to render. */
  onRuntimeError?: (message: string) => void;
  /** A note under the card (e.g. "generated from this answer"). */
  footnote?: ReactNode;
}

/**
 * One interactive concept card in an answer: a formula walked through step by step, a graph,
 * a short sourced note, or a canvas animation in a sandboxed iframe with pause / play,
 * 0.5×, 1×, 2× and replay.
 */
export default function ConceptCard({ spec, label, actions, onRuntimeError, footnote }: Props) {
  const [run, setRun] = useState(0);
  const [crash, setCrash] = useState<string | null>(null);
  const [speed, setSpeed] = useState(DEFAULT_SPEED);
  const [paused, setPaused] = useState(false);
  const fail = (m: string) => { setCrash(m); onRuntimeError?.(m); };

  const visual = spec.type === "2d-anim" || spec.type === "graph";
  return (
    <figure className={`kc-card kc-concept kc-concept-${spec.type}`}>
      <header>
        <span className="kc-card-kind">{KIND[spec.type]}</span>
        <span className="kc-card-title">{spec.title || label}</span>
        {spec.type === "2d-anim" && <>
          <button type="button" className={`kc-btn ${paused ? "on" : ""}`} title={paused ? "Play" : "Pause"}
            onClick={() => setPaused((p) => !p)}>{paused ? "▶ play" : "❚❚ pause"}</button>
          {SPEEDS.map((v) => (
            <button type="button" key={v} className={`kc-btn ${!paused && speed === v ? "on" : ""}`} title={`Play at ${v}× speed`}
              onClick={() => { setSpeed(v); setPaused(false); }}>{v}×</button>
          ))}
          <button type="button" className="kc-btn" title="Restart the animation"
            onClick={() => { setCrash(null); setPaused(false); setRun((n) => n + 1); }}>↻ replay</button>
        </>}
        {actions}
      </header>
      {visual ? (
        <div className="kc-concept-stage">
          {spec.type === "2d-anim"
            ? <AnimView key={run} spec={spec} onRuntimeError={fail} speed={paused ? 0 : speed} />
            : <GraphView spec={spec} onRuntimeError={fail} />}
        </div>
      ) : (
        <div className="kc-concept-body">
          {spec.type === "formula" ? <FormulaView spec={spec} /> : <TextView spec={spec} />}
        </div>
      )}
      {crash && <p className="kc-card-error">{crash}</p>}
      {(spec.caption || footnote) && (
        <figcaption>
          {tidyCaption(spec.caption ?? "")}
          {footnote && <span className="kc-card-foot">{footnote}</span>}
        </figcaption>
      )}
    </figure>
  );
}
