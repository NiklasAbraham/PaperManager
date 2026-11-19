import { useState } from "react";
import { Link } from "react-router-dom";
import type { SimilarHit } from "../../api/similar";
import { formatDate } from "../insights/format";
import { Badge, btnPrimary, btnSecondary } from "../insights/ui";

function authorsLine(authors: string[]): string {
  return authors.length <= 4 ? authors.join(", ") : `${authors.slice(0, 4).join(", ")} et al.`;
}

export default function SimilarRow({
  hit,
  busy,
  onUseAsQuery,
  onAdd,
}: {
  hit: SimilarHit;
  busy: boolean;
  onUseAsQuery: (hit: SimilarHit) => void;
  onAdd: (hit: SimilarHit) => void;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = `similar-abstract-${hit.source}-${hit.id}`;
  const text = hit.abstract || hit.snippet;
  const pct = Math.round(Math.max(0, Math.min(1, hit.score)) * 100);
  const isLibrary = hit.source === "library";
  const when = isLibrary ? (hit.year ? String(hit.year) : "") : formatDate(hit.published);
  const meta = [authorsLine(hit.authors), when, isLibrary ? hit.venue : null].filter(Boolean);

  return (
    <li className="rounded-xl border border-line bg-raised p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 break-words text-sm font-semibold text-ink">
          {isLibrary ? (
            <Link to={`/paper/${hit.id}`} className="hover:text-accent hover:underline">{hit.title}</Link>
          ) : (
            <a href={hit.url} target="_blank" rel="noreferrer" className="hover:text-accent hover:underline">{hit.title}</a>
          )}
        </h3>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <Badge tone={isLibrary ? "accent" : "neutral"}>{isLibrary ? "Library" : "Feed"}</Badge>
          {hit.reference_stub ? <Badge tone="warn" title="Only cited by another paper; no abstract of its own is guaranteed">Reference</Badge> : null}
          {!isLibrary && hit.in_library ? (
            hit.library_paper_id ? (
              <Link to={`/paper/${hit.library_paper_id}`} className="inline-flex">
                <Badge tone="ok">In your library</Badge>
              </Link>
            ) : (
              <Badge tone="ok">In your library</Badge>
            )
          ) : null}
        </div>
      </div>

      {meta.length ? <p className="mt-0.5 text-xs text-ink-3">{meta.join(" · ")}</p> : null}

      <div className="mt-2 flex items-center gap-2" title="Cosine similarity to your text">
        <div
          role="meter"
          aria-label="Similarity"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          className="h-1.5 w-28 overflow-hidden rounded-full bg-line"
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs tabular-nums text-ink-3">{hit.score.toFixed(2)}</span>
      </div>

      {text ? (
        <div className="mt-2">
          <p className={`break-words text-sm text-ink-2 ${open ? "whitespace-pre-wrap" : "line-clamp-2"}`} id={bodyId}>
            {open ? text : hit.snippet || text}
          </p>
          {text.length > hit.snippet.length || hit.snippet.endsWith("…") ? (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={bodyId}
              onClick={() => setOpen(!open)}
              className="mt-1 text-xs text-accent hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
            >
              {open ? "Show less" : "Show more"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!isLibrary && !hit.in_library ? (
          <button type="button" className={btnPrimary} disabled={busy} onClick={() => onAdd(hit)}>
            Add to library
          </button>
        ) : null}
        <button type="button" className={btnSecondary} disabled={busy} onClick={() => onUseAsQuery(hit)}>
          Use this paper as the query
        </button>
      </div>
    </li>
  );
}
