import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { apiFetch, listVenues } from "../../api/client";
import {
  ADDED_LABELS, ADDED_PRESETS, BOOL_KEYS, DOCUMENT_TYPES, STATUS_LABELS,
  boolParam, sortOptions, type AddedPreset,
} from "./filterState";

type Mutate = (next: URLSearchParams) => void;

interface Props {
  params: URLSearchParams;
  /** Number of active filters, shown as a badge on the button. */
  count: number;
  hasQuery: boolean;
  /** The sort in effect (URL or default). */
  sort: string;
  projects: { id: string; name: string }[];
  onChange: (mutate: Mutate) => void;
  onClear: () => void;
}

const BOOL_ROWS: { key: (typeof BOOL_KEYS)[number]; label: string }[] = [
  { key: "has_pdf", label: "Has PDF" },
  { key: "has_text", label: "Has full text" },
  { key: "has_note", label: "Has note" },
  { key: "has_highlights", label: "Has highlights" },
  { key: "bookmarked", label: "Bookmarked" },
];

const FIELD = "h-8 w-full border border-line rounded px-2 text-sm bg-raised text-ink-2 focus:outline-none focus:ring-2 focus:ring-violet-300";

/** The Filters button with its popover (a bottom sheet on phones). Every change goes straight
 * into the URL, so the list refetches as you click and the filtered view is shareable. */
export default function FilterMenu({ params, count, hasQuery, sort, projects, onChange, onClear }: Props) {
  const [open, setOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [lists, setLists] = useState<{ tags: string[]; topics: string[]; venues: string[] } | null>(null);
  const loadedLists = useRef(false);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // The tag / topic / venue lists are only fetched the first time the panel opens.
  useEffect(() => {
    if (!open || loadedLists.current) return;
    loadedLists.current = true;
    const names = (v: unknown): string[] =>
      Array.isArray(v) ? v.map((x) => (x as { name?: string })?.name ?? "").filter(Boolean) : [];
    Promise.all([
      apiFetch<unknown>("/tags").catch(() => []),
      apiFetch<unknown>("/topics").catch(() => []),
      listVenues().catch(() => []),
    ]).then(([tags, topics, venues]) => setLists({ tags: names(tags), topics: names(topics), venues: names(venues) }));
  }, [open]);

  const get = (k: string) => params.get(k) ?? "";
  const set = (k: string, v: string | null) => onChange((n) => { if (v) n.set(k, v); else n.delete(k); });

  const added = get("added");
  const from = get("added_from");
  const to = get("added_to");
  const showCustom = customOpen || !!from || !!to;
  const pickPreset = (p: AddedPreset | "") => {
    setCustomOpen(false);
    onChange((n) => { n.delete("added_from"); n.delete("added_to"); if (p) n.set("added", p); else n.delete("added"); });
  };

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={`h-9 px-3 inline-flex items-center gap-1.5 rounded-lg border text-sm transition-colors ${
          count > 0 || open
            ? "border-accent-border bg-accent-lo text-accent"
            : "border-line text-ink-2 hover:border-accent-border hover:text-accent"
        }`}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h18M6 12h12M10 19h4" />
        </svg>
        Filters
        {count > 0 && (
          <span aria-label={`${count} active`} className="min-w-5 h-5 px-1 rounded-full bg-accent text-white text-[11px] font-semibold inline-flex items-center justify-center">
            {count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30 bg-black/30 sm:bg-transparent" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-label="Filters"
            className="fixed inset-x-0 bottom-0 z-40 max-h-[85vh] overflow-y-auto bg-raised border border-line rounded-t-xl shadow-xl
                       sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[26rem] sm:max-h-[75vh] sm:rounded-xl"
          >
            <div className="sticky top-0 bg-raised flex items-center justify-between px-4 py-3 border-b border-line-s">
              <h2 className="text-xs font-semibold text-ink-3 uppercase tracking-wide">Filters</h2>
              <div className="flex items-center gap-3">
                {count > 0 && (
                  <button type="button" onClick={onClear} className="text-xs text-ink-3 hover:text-accent underline">
                    Clear filters
                  </button>
                )}
                <button type="button" onClick={() => setOpen(false)} className="text-xs font-medium text-accent hover:underline">
                  Done
                </button>
              </div>
            </div>

            <div className="p-4 space-y-4">
              <Field label="Added">
                <div className="flex flex-wrap gap-1.5">
                  <Pill active={!added && !showCustom} onClick={() => pickPreset("")}>Any time</Pill>
                  {(Object.keys(ADDED_PRESETS) as AddedPreset[]).map((p) => (
                    <Pill key={p} active={added === p} onClick={() => pickPreset(p)}>{ADDED_LABELS[p]}</Pill>
                  ))}
                  <Pill active={showCustom && !added} onClick={() => { setCustomOpen(true); onChange((n) => n.delete("added")); }}>
                    Custom range
                  </Pill>
                </div>
                {showCustom && !added && (
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <label className="text-[11px] text-ink-3">
                      From
                      <input type="date" value={from} max={to || undefined} onChange={(e) => set("added_from", e.target.value)} className={`${FIELD} mt-0.5`} />
                    </label>
                    <label className="text-[11px] text-ink-3">
                      To
                      <input type="date" value={to} min={from || undefined} onChange={(e) => set("added_to", e.target.value)} className={`${FIELD} mt-0.5`} />
                    </label>
                  </div>
                )}
              </Field>

              <Field label="Year">
                <div className="flex items-center gap-2">
                  <CommitInput value={get("year_min")} onCommit={(v) => set("year_min", v)} label="Year from" placeholder="From" />
                  <span className="text-ink-3 text-xs">to</span>
                  <CommitInput value={get("year_max")} onCommit={(v) => set("year_max", v)} label="Year to" placeholder="To" />
                </div>
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Reading status">
                  <select aria-label="Reading status" value={get("reading_status")} onChange={(e) => set("reading_status", e.target.value || null)} className={FIELD}>
                    <option value="">Any</option>
                    {Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </Field>
                <Field label="Rating at least">
                  <select aria-label="Rating at least" value={get("rating_min")} onChange={(e) => set("rating_min", e.target.value || null)} className={FIELD}>
                    <option value="">Any</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} or more</option>)}
                  </select>
                </Field>
                <Field label="Document type">
                  <select aria-label="Document type" value={get("document_type")} onChange={(e) => set("document_type", e.target.value || null)} className={FIELD}>
                    <option value="">Any</option>
                    {Object.entries(DOCUMENT_TYPES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </Field>
                <Field label="Project">
                  <select aria-label="Project" value={get("project_id")} onChange={(e) => set("project_id", e.target.value || null)} className={FIELD}>
                    <option value="">Any</option>
                    {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </Field>
              </div>

              <Field label="Properties">
                <div className="divide-y divide-line-s border border-line rounded-lg">
                  {BOOL_ROWS.map((r) => (
                    <div key={r.key} className="flex items-center justify-between px-3 py-1.5">
                      <span className="text-sm text-ink-2">{r.label}</span>
                      <Tri
                        label={r.label}
                        value={boolParam(params.get(r.key))}
                        onChange={(v) => set(r.key, v === null ? null : v ? "1" : "0")}
                      />
                    </div>
                  ))}
                </div>
              </Field>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <Field label="Tag">
                  <ListInput id={`${id}-tags`} label="Tag" value={get("tag")} options={lists?.tags ?? []} onCommit={(v) => set("tag", v)} />
                </Field>
                <Field label="Topic">
                  <ListInput id={`${id}-topics`} label="Topic" value={get("topic")} options={lists?.topics ?? []} onCommit={(v) => set("topic", v)} />
                </Field>
                <Field label="Venue">
                  <ListInput id={`${id}-venues`} label="Venue" value={get("venue")} options={lists?.venues ?? []} onCommit={(v) => set("venue", v)} />
                </Field>
              </div>

              <Field label="Sort by">
                <select aria-label="Sort by" value={sort} onChange={(e) => set("sort", e.target.value === "relevance" ? null : e.target.value)} className={FIELD}>
                  {sortOptions(hasQuery).map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </Field>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-medium text-ink-3 mb-1">{label}</p>
      {children}
    </div>
  );
}

function Pill({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
        active ? "bg-accent text-white border-accent" : "bg-raised text-ink-2 border-line hover:border-accent-border hover:text-accent"
      }`}
    >
      {children}
    </button>
  );
}

/** Any / Yes / No for a true-false filter. */
function Tri({ label, value, onChange }: { label: string; value: "true" | "false" | null; onChange: (v: boolean | null) => void }) {
  const opts: { text: string; v: boolean | null; on: boolean }[] = [
    { text: "Any", v: null, on: value === null },
    { text: "Yes", v: true, on: value === "true" },
    { text: "No", v: false, on: value === "false" },
  ];
  return (
    <div role="group" aria-label={label} className="flex rounded-md border border-line overflow-hidden">
      {opts.map((o) => (
        <button
          key={o.text}
          type="button"
          aria-pressed={o.on}
          onClick={() => onChange(o.v)}
          className={`px-2.5 h-6 text-xs ${o.on ? "bg-accent text-white" : "bg-raised text-ink-2 hover:text-accent"}`}
        >
          {o.text}
        </button>
      ))}
    </div>
  );
}

/** A text input that edits locally and writes to the URL on blur / Enter, so typing a
 * year does not refetch after every digit. Follows the URL when it changes elsewhere. */
function useDraft(value: string) {
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setDraft(value);
  }
  return [draft, setDraft] as const;
}

function CommitInput({ value, onCommit, label, placeholder }: { value: string; onCommit: (v: string) => void; label: string; placeholder: string }) {
  const [draft, setDraft] = useDraft(value);
  const commit = () => {
    const v = draft.trim();
    if (v === value) return;
    if (v === "" || /^\d{1,4}$/.test(v)) onCommit(v);
    else setDraft(value);
  };
  return (
    <input
      type="text"
      inputMode="numeric"
      aria-label={label}
      placeholder={placeholder}
      value={draft}
      maxLength={4}
      onChange={(e) => setDraft(e.target.value.replace(/\D/g, ""))}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
      className={FIELD}
    />
  );
}

/** Free text with the library's names as suggestions (datalist); picking one applies it. */
function ListInput({ id, label, value, options, onCommit }: { id: string; label: string; value: string; options: string[]; onCommit: (v: string) => void }) {
  const [draft, setDraft] = useDraft(value);
  const canon = (v: string) => options.find((o) => o.toLowerCase() === v.trim().toLowerCase());
  const commit = (text: string) => {
    const v = canon(text) ?? text.trim();
    if (v !== value) onCommit(v);
  };
  return (
    <>
      <input
        type="text"
        list={id}
        aria-label={label}
        placeholder="Any"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          // A pick from the list arrives as one change with the whole name.
          if (e.target.value && options.includes(e.target.value)) commit(e.target.value);
        }}
        onBlur={() => commit(draft)}
        onKeyDown={(e) => { if (e.key === "Enter") commit(draft); }}
        className={FIELD}
      />
      <datalist id={id}>{options.map((o) => <option key={o} value={o} />)}</datalist>
    </>
  );
}
