/**
 * The row under an answer naming what it drew on: library papers as real links
 * (`/paper/<id>`: a plain click opens the preview beside the chat, ctrl/meta/middle click
 * follows the link), web pages, and how many searches were run. Ported from the desk's
 * `TurnSources`.
 */
import { useState, type MouseEvent } from "react";
import type { MessagePaper } from "../../types";
import { hasSources, type AnswerSources, type PaperSource } from "./sources";

const LIMIT = 10;

export function TurnSources({ sources, onPaper }: { sources: AnswerSources; onPaper: (p: MessagePaper) => void }) {
  const [all, setAll] = useState(false);
  if (!hasSources(sources)) return null;
  const { papers, web, searches } = sources;
  const list = all ? papers : papers.slice(0, LIMIT);

  const chip = (p: PaperSource) => {
    const strength = p.rank === 0 ? "strong" : p.rank === 3 ? "weak" : "mid";
    const open = (e: MouseEvent<HTMLAnchorElement>) => {
      // Let the browser follow the link for new-tab clicks; a plain click opens the preview pane.
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      onPaper({ id: p.id, title: p.title, year: p.year });
    };
    return (
      <a key={p.id} href={`/paper/${p.id}`} className={`kc-src-chip k-paper ${strength}`} title={p.verbs.join(", ")} onClick={open}>
        <span>{p.title}</span>
      </a>
    );
  };

  return (
    <div className="kc-turn-sources">
      <span className="kc-kicker">Sources</span>
      {list.map(chip)}
      {papers.length > LIMIT && (
        <button type="button" className="kc-src-more" onClick={() => setAll((v) => !v)}>
          {all ? "fewer" : `+${papers.length - LIMIT}`}
        </button>
      )}
      {web.map((w) => (
        <a key={w.url} href={w.url} target="_blank" rel="noreferrer" className="kc-src-chip k-web" title={w.url}><span>{w.label}</span></a>
      ))}
      {searches.length > 0 && (
        <span className="kc-src-count" title={searches.join("\n")}>{searches.length} search{searches.length > 1 ? "es" : ""}</span>
      )}
    </div>
  );
}
