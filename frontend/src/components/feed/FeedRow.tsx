import { useState } from "react";
import { Link } from "react-router-dom";
import type { FeedItem } from "../../api/feed";
import { formatDate } from "../insights/format";
import { Badge, btnPrimary, btnSecondary, inputCls } from "../insights/ui";

const SOURCE_LABEL = { arxiv: "arXiv", biorxiv: "bioRxiv", medrxiv: "medRxiv" } as const;

function ThumbIcon({ down }: { down?: boolean }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={down ? "rotate-180" : ""}>
      <path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3Zm0 0 4-8a2 2 0 0 1 2 2v4h5.3a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.1 20H7" />
    </svg>
  );
}

function authorsLine(authors: string[]): string {
  if (authors.length <= 4) return authors.join(", ");
  return `${authors.slice(0, 4).join(", ")} et al.`;
}

export default function FeedRow({
  item,
  projects,
  busy,
  onRate,
  onDismiss,
  onAdd,
}: {
  item: FeedItem;
  projects: { id: string; name: string }[];
  busy: boolean;
  onRate: (item: FeedItem, value: 1 | -1) => void;
  onDismiss: (item: FeedItem) => void;
  onAdd: (item: FeedItem, projectId?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const abstractId = `feed-abstract-${item.id}`;
  const pct = item.score === null ? null : Math.round(Math.max(0, Math.min(1, item.score)) * 100);

  return (
    <li className="rounded-xl border border-line bg-raised p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 break-words text-sm font-semibold text-ink">
          <a href={item.url} target="_blank" rel="noreferrer" className="hover:text-accent hover:underline">
            {item.title}
          </a>
        </h3>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <Badge>{SOURCE_LABEL[item.source]}</Badge>
          {item.in_library ? (
            item.library_paper_id ? (
              <Link to={`/paper/${item.library_paper_id}`} className="inline-flex">
                <Badge tone="ok">In your library</Badge>
              </Link>
            ) : (
              <Badge tone="ok">In your library</Badge>
            )
          ) : null}
        </div>
      </div>

      <p className="mt-0.5 text-xs text-ink-3">
        {authorsLine(item.authors)}
        {item.authors.length ? <span className="mx-1.5">&middot;</span> : null}
        {formatDate(item.published)}
        {item.categories.length ? <span className="mx-1.5">&middot;</span> : null}
        {item.categories.slice(0, 3).join(", ")}
      </p>

      {pct !== null ? (
        <div className="mt-2 flex items-center gap-2" title="How well this paper fits what you keep">
          <div
            role="meter"
            aria-label="Relevance"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            className="h-1.5 w-28 overflow-hidden rounded-full bg-line"
          >
            <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-xs tabular-nums text-ink-3">{pct}%</span>
        </div>
      ) : null}

      {item.neighbours.length > 0 ? (
        <p className="mt-2 text-xs text-ink-3">
          Why: close to{" "}
          {item.neighbours.map((n, i) => (
            <span key={n.paper_id}>
              {i > 0 ? "; " : ""}
              <Link to={`/paper/${n.paper_id}`} className="text-ink-2 hover:text-accent hover:underline">
                {n.title}
              </Link>
            </span>
          ))}
        </p>
      ) : null}

      {item.abstract ? (
        <div className="mt-2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={abstractId}
            onClick={() => setOpen(!open)}
            className="text-xs text-accent hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
          >
            {open ? "Hide abstract" : "Show abstract"}
          </button>
          {open ? <p id={abstractId} className="mt-1 whitespace-pre-wrap break-words text-sm text-ink-2">{item.abstract}</p> : null}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {item.in_library ? null : (
          <>
            <button type="button" className={btnPrimary} disabled={busy} onClick={() => onAdd(item)}>
              Add to library
            </button>
            {projects.length > 0 ? (
              <select
                aria-label={`Add to project: ${item.title}`}
                value=""
                disabled={busy}
                onChange={(e) => e.target.value && onAdd(item, e.target.value)}
                className={`${inputCls} py-1 text-xs`}
              >
                <option value="">Add to project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            ) : null}
          </>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Good match"
            aria-pressed={item.my_label === 1}
            disabled={busy}
            onClick={() => onRate(item, 1)}
            className={`${btnSecondary} px-2 ${item.my_label === 1 ? "border-accent text-accent" : ""}`}
          >
            <ThumbIcon />
          </button>
          <button
            type="button"
            aria-label="Not for me"
            aria-pressed={item.my_label === -1}
            disabled={busy}
            onClick={() => onRate(item, -1)}
            className={`${btnSecondary} px-2 ${item.my_label === -1 ? "border-coral text-coral" : ""}`}
          >
            <ThumbIcon down />
          </button>
          <button type="button" className={btnSecondary} disabled={busy} onClick={() => onDismiss(item)}>
            Dismiss
          </button>
        </span>
      </div>
    </li>
  );
}
