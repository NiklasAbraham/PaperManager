import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  createSuggestion,
  deleteSuggestion,
  getSuggestionCounts,
  listSuggestions,
  updateSuggestion,
  voteSuggestion,
} from "../api/insights";
import type { SuggestionCounts, SuggestionOut, SuggestionStatus } from "../api/insights";
import { useAuth } from "../contexts/AuthContext";
import { Badge, Card, EmptyState, ErrorNote, PageHeader, Spinner, btnDanger, btnPrimary, btnSecondary, errorMessage, inputCls } from "../components/insights/ui";
import { formatDate } from "../components/insights/format";

type Tab = SuggestionStatus | "all";
type Sort = "votes" | "new";

const TABS: { value: Tab; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "planned", label: "Planned" },
  { value: "done", label: "Done" },
  { value: "dismissed", label: "Dismissed" },
  { value: "all", label: "All" },
];
const STATUSES: SuggestionStatus[] = ["open", "planned", "done", "dismissed"];
const EMPTY_TEXT: Record<Tab, string> = {
  open: "Ideas that have not been picked up yet will appear here.",
  planned: "Suggestions an admin has planned will appear here.",
  done: "Suggestions that shipped will appear here.",
  dismissed: "Suggestions an admin turned down will appear here.",
  all: "Suggestions from the chat, from you and from reports will appear here.",
};
const SOURCE_LABEL = { chat: "from chat", user: "user", report: "from report" } as const;

function VoteIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 14 6-7 6 7" />
    </svg>
  );
}

function SuggestionRow({
  s,
  me,
  isAdmin,
  onVote,
  onStatus,
  onDelete,
}: {
  s: SuggestionOut;
  me: string | null;
  isAdmin: boolean;
  onVote: (s: SuggestionOut) => void;
  onStatus: (s: SuggestionOut, status: SuggestionStatus) => void;
  onDelete: (s: SuggestionOut) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const canDelete = isAdmin || (me !== null && me === s.created_by);
  const detailId = `suggestion-detail-${s.id}`;

  return (
    <li className="flex gap-3 rounded-xl border border-line bg-raised p-4">
      <button
        type="button"
        onClick={() => onVote(s)}
        aria-pressed={s.voted}
        aria-label={`${s.voted ? "Remove your vote from" : "Vote for"}: ${s.text}`}
        className={`flex h-14 w-12 shrink-0 flex-col items-center justify-center rounded-lg border text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border ${
          s.voted ? "border-accent bg-accent text-white" : "border-line bg-raised text-ink-2 hover:border-accent-border hover:text-accent"
        }`}
      >
        <VoteIcon />
        <span className="text-sm font-semibold tabular-nums">{s.votes}</span>
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="min-w-0 flex-1 break-words text-sm font-medium text-ink">{s.text}</p>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            <Badge tone={s.source === "chat" ? "accent" : "neutral"}>{SOURCE_LABEL[s.source]}</Badge>
            {s.seen > 1 ? <Badge title="The chat proposed this again">seen {s.seen}&times;</Badge> : null}
            {isAdmin ? (
              <select
                aria-label={`Status of: ${s.text}`}
                value={s.status}
                onChange={(e) => onStatus(s, e.target.value as SuggestionStatus)}
                className={`${inputCls} py-0.5 text-xs`}
              >
                {STATUSES.map((st) => (
                  <option key={st} value={st}>{st}</option>
                ))}
              </select>
            ) : s.status !== "open" ? (
              <Badge tone={s.status === "done" ? "ok" : s.status === "planned" ? "accent" : "warn"}>{s.status}</Badge>
            ) : null}
          </div>
        </div>
        {s.detail ? (
          <div className="mt-1">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={detailId}
              onClick={() => setOpen(!open)}
              className="text-xs text-accent hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
            >
              {open ? "Hide details" : "Show details"}
            </button>
            {open ? (
              <p id={detailId} className="mt-1 whitespace-pre-wrap break-words text-sm text-ink-2">{s.detail}</p>
            ) : null}
          </div>
        ) : null}
        {s.source === "chat" && s.context ? (
          <p className="mt-1.5 line-clamp-2 border-l-2 border-line pl-2 text-xs italic text-ink-3" title={s.context}>
            Asked: {s.context}
          </p>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
          <span>{s.created_by}</span>
          <span>{formatDate(s.created_at)}</span>
          {canDelete ? (
            confirming ? (
              <span role="group" aria-label="Confirm delete" className="flex items-center gap-2">
                Delete this suggestion?
                <button type="button" className={`${btnDanger} px-2 py-0.5 text-xs`} onClick={() => void onDelete(s)}>
                  Yes, delete
                </button>
                <button type="button" className={`${btnSecondary} px-2 py-0.5 text-xs`} onClick={() => setConfirming(false)}>
                  Keep
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirming(true)} className="text-ink-3 hover:text-coral focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border">
                Delete
              </button>
            )
          ) : null}
        </div>
      </div>
    </li>
  );
}

export default function Suggestions() {
  const { username, isAdmin } = useAuth();
  const [tab, setTab] = useState<Tab>("open");
  const [sort, setSort] = useState<Sort>("votes");
  const [items, setItems] = useState<SuggestionOut[] | null>(null);
  const [counts, setCounts] = useState<SuggestionCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [text, setText] = useState("");
  const [detail, setDetail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const seq = useRef(0);

  const loadCounts = useCallback(() => {
    getSuggestionCounts().then(setCounts).catch(() => {
      /* the tabs just show no numbers */
    });
  }, []);

  const load = useCallback(() => {
    const id = ++seq.current;
    setError(null);
    return listSuggestions({ status: tab === "all" ? undefined : tab, sort })
      .then((r) => {
        if (id === seq.current) setItems(r);
      })
      .catch((e) => {
        if (id === seq.current) setError(errorMessage(e, "Could not load suggestions"));
      });
  }, [tab, sort]);

  useEffect(() => {
    setItems(null);
    void load();
  }, [load]);

  useEffect(() => {
    loadCounts();
  }, [loadCounts]);

  const trimmed = text.trim();
  const textOk = trimmed.length >= 3 && trimmed.length <= 280;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!textOk || submitting) return;
    setSubmitting(true);
    setFormError(null);
    try {
      const body: { text: string; detail?: string } = { text: trimmed };
      if (detail.trim()) body.detail = detail.trim();
      await createSuggestion(body);
      setText("");
      setDetail("");
      await load();
      loadCounts();
    } catch (err) {
      setFormError(errorMessage(err, "Could not save the suggestion"));
    } finally {
      setSubmitting(false);
    }
  };

  const replace = (next: SuggestionOut) =>
    setItems((prev) => (prev ?? []).map((x) => (x.id === next.id ? next : x)));

  const vote = async (s: SuggestionOut) => {
    setActionError(null);
    const before = s;
    replace({ ...s, voted: !s.voted, votes: Math.max(0, s.votes + (s.voted ? -1 : 1)) });
    try {
      replace(await voteSuggestion(s.id));
    } catch (e) {
      replace(before);
      setActionError(errorMessage(e, "Could not save your vote"));
    }
  };

  const setStatus = async (s: SuggestionOut, status: SuggestionStatus) => {
    setActionError(null);
    try {
      const next = await updateSuggestion(s.id, { status });
      if (tab !== "all" && next.status !== tab) setItems((prev) => (prev ?? []).filter((x) => x.id !== s.id));
      else replace(next);
      loadCounts();
    } catch (e) {
      setActionError(errorMessage(e, "Could not change the status"));
    }
  };

  const remove = async (s: SuggestionOut) => {
    setActionError(null);
    try {
      await deleteSuggestion(s.id);
      setItems((prev) => (prev ?? []).filter((x) => x.id !== s.id));
      loadCounts();
    } catch (e) {
      setActionError(errorMessage(e, "Could not delete the suggestion"));
    }
  };

  const countFor = (t: Tab): number | null => {
    if (!counts) return null;
    return t === "all" ? STATUSES.reduce((n, k) => n + (counts[k] ?? 0), 0) : (counts[t] ?? 0);
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Suggestions"
        description="Ideas for improving PaperManager, from the chat, from you and from reports. Vote for the ones you want."
      />

      <Card title="Suggest an improvement">
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label htmlFor="suggestion-text" className="mb-1 block text-sm font-medium text-ink">
              Suggestion
            </label>
            <input
              id="suggestion-text"
              type="text"
              value={text}
              maxLength={280}
              onChange={(e) => setText(e.target.value)}
              placeholder="Export a project's notes as one Markdown file"
              aria-describedby="suggestion-count"
              className={`${inputCls} w-full`}
            />
            <p id="suggestion-count" className={`mt-1 text-right text-xs tabular-nums ${trimmed.length > 0 && trimmed.length < 3 ? "text-coral" : "text-ink-3"}`}>
              {text.length} / 280 (3 at least)
            </p>
          </div>
          <div>
            <label htmlFor="suggestion-detail" className="mb-1 block text-sm font-medium text-ink">
              Details <span className="font-normal text-ink-3">(optional)</span>
            </label>
            <textarea
              id="suggestion-detail"
              rows={2}
              value={detail}
              maxLength={2000}
              onChange={(e) => setDetail(e.target.value)}
              placeholder="What were you trying to do, and what got in the way?"
              className={`${inputCls} w-full resize-y`}
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            {formError ? <span role="alert" className="min-w-0 break-words text-sm text-coral">{formError}</span> : null}
            <button type="submit" className={btnPrimary} disabled={!textOk || submitting}>
              {submitting ? "Sending" : "Submit"}
            </button>
          </div>
        </form>
      </Card>

      <div className="mb-3 mt-8 flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Status" className="flex flex-wrap gap-1.5">
          {TABS.map((t) => {
            const n = countFor(t.value);
            const on = t.value === tab;
            return (
              <button
                key={t.value}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => setTab(t.value)}
                className={`rounded-full border px-3 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border ${
                  on ? "border-accent bg-accent text-white" : "border-line bg-raised text-ink-2 hover:border-accent-border hover:text-accent"
                }`}
              >
                {t.label}
                {n !== null ? <span className="ml-1.5 tabular-nums opacity-80">{n}</span> : null}
              </button>
            );
          })}
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} className={inputCls}>
            <option value="votes">Most votes</option>
            <option value="new">Newest</option>
          </select>
        </label>
      </div>

      {actionError ? <div className="mb-3"><ErrorNote message={actionError} /></div> : null}
      {error ? <ErrorNote message={error} onRetry={() => void load()} /> : null}
      {items === null && !error ? <Spinner label="Loading suggestions" /> : null}
      {items && items.length === 0 ? <EmptyState title="Nothing here yet">{EMPTY_TEXT[tab]}</EmptyState> : null}
      {items && items.length > 0 ? (
        <ul className="space-y-3" aria-label="Suggestions">
          {items.map((s) => (
            <SuggestionRow key={s.id} s={s} me={username} isAdmin={isAdmin} onVote={vote} onStatus={setStatus} onDelete={remove} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
