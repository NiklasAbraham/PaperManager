import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { addFeedItem } from "../api/feed";
import { MAX_TEXT, MIN_TEXT, searchSimilar } from "../api/similar";
import type { SimilarHit, SimilarResult, SimilarScope } from "../api/similar";
import SimilarRow from "../components/similar/SimilarRow";
import { queryFromHit } from "../components/similar/queryFromHit";
import { EmptyState, ErrorNote, PageHeader, Segmented, Spinner, btnPrimary, errorMessage, inputCls } from "../components/insights/ui";
import { loadFeatures, useFeatures } from "../lib/features";

const K_CHOICES = [5, 10, 20, 30, 50];
const SCOPE_OPTIONS: { value: SimilarScope; label: string }[] = [
  { value: "library", label: "Library" },
  { value: "feed", label: "Feed" },
  { value: "both", label: "Both" },
];

export default function SimilarSearch() {
  const feedOn = useFeatures().has("feed");
  const [text, setText] = useState("");
  const [scope, setScope] = useState<SimilarScope>("both");
  const [since, setSince] = useState("");
  const [k, setK] = useState(10);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimilarResult | null>(null);
  const [hits, setHits] = useState<SimilarHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [replaced, setReplaced] = useState(false);
  const seq = useRef(0);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    void loadFeatures();
  }, []);

  // Without the feed there is nothing to choose: the search runs on the library.
  const effectiveScope: SimilarScope = feedOn ? scope : "library";
  const trimmed = text.trim();
  const tooShort = trimmed.length < MIN_TEXT;
  const tooLong = trimmed.length > MAX_TEXT;

  const run = async (e?: FormEvent) => {
    e?.preventDefault();
    if (tooShort || tooLong || loading) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    setActionError(null);
    setReplaced(false);
    try {
      const r = await searchSimilar({ text: trimmed, k, scope: effectiveScope, since: since || undefined });
      if (id !== seq.current) return;
      setResult(r);
      setHits(r.hits);
    } catch (err) {
      if (id === seq.current) {
        setResult(null);
        setHits([]);
        setError(errorMessage(err, "The search failed"));
      }
    } finally {
      if (id === seq.current) setLoading(false);
    }
  };

  const useAsQuery = (hit: SimilarHit) => {
    setText(queryFromHit(hit));
    setReplaced(true);
    box.current?.focus();
    box.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  };

  const add = async (hit: SimilarHit) => {
    setActionError(null);
    setBusyId(hit.id);
    try {
      const r = await addFeedItem(hit.id);
      setHits((prev) => prev.map((h) => (h.id === hit.id && h.source === "feed" ? { ...h, in_library: true, library_paper_id: r.paper_id, my_label: 1 } : h)));
    } catch (err) {
      setActionError(errorMessage(err, "Could not add the paper"));
    } finally {
      setBusyId(null);
    }
  };

  const counter = `${trimmed.length.toLocaleString("en-US")} / ${MAX_TEXT.toLocaleString("en-US")}`;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Similar papers"
        description="Does a paper like this already exist? Write or paste an abstract, even one for a paper you wish existed."
      />

      <form onSubmit={(e) => void run(e)} className="mb-6 rounded-xl border border-line bg-raised p-4">
        <label htmlFor="similar-text" className="block text-xs font-medium text-ink-3 mb-1">Abstract</label>
        <textarea
          id="similar-text"
          ref={box}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setReplaced(false);
          }}
          rows={9}
          placeholder="Paste or write an abstract: title and a paragraph work best"
          aria-describedby="similar-text-help"
          className={`${inputCls} w-full resize-y`}
        />
        <div id="similar-text-help" className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
          <span>
            {replaced
              ? "The text was replaced by the paper you picked. Edit it, then search again."
              : `At least ${MIN_TEXT} characters. Describe what the paper does, not just its topic.`}
          </span>
          <span className={`tabular-nums ${tooLong ? "text-coral" : ""}`}>{counter}</span>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-x-5 gap-y-3">
          {feedOn ? (
            <div>
              <span aria-hidden="true" className="mb-1 block text-xs font-medium text-ink-3">Search in</span>
              <Segmented label="Search in" value={scope} options={SCOPE_OPTIONS} onChange={setScope} />
            </div>
          ) : null}
          <label className="text-xs font-medium text-ink-3">
            <span className="mb-1 block">Published since</span>
            <input
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className={`${inputCls} py-1`}
            />
          </label>
          <label className="text-xs font-medium text-ink-3">
            <span className="mb-1 block">Results</span>
            <select value={k} onChange={(e) => setK(Number(e.target.value))} className={`${inputCls} py-1`}>
              {K_CHOICES.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <button type="submit" className={`${btnPrimary} ml-auto`} disabled={tooShort || tooLong || loading}>
            {loading ? "Searching" : "Search"}
          </button>
        </div>
      </form>

      {error ? <ErrorNote message={error} onRetry={() => void run()} /> : null}
      {actionError ? <div className="mb-3"><ErrorNote message={actionError} /></div> : null}
      {loading ? <Spinner label="Looking for similar papers" /> : null}

      {!loading && !error && result === null ? (
        <EmptyState title="Nothing searched yet">
          Your text is compared by meaning with the abstracts in your library{feedOn ? " and the paper feed" : ""}. A close match means
          the work you describe may already exist; a weak one means it probably does not.
        </EmptyState>
      ) : null}

      {!loading && result && !result.available ? (
        <div role="status" className="rounded-xl border border-dashed border-line bg-raised px-6 py-8 text-center">
          <p className="text-sm font-medium text-ink">The index is not ready for this search</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">
            {result.reason ?? "It may still be building after a start or a change of the embedding model."} Try again in a few minutes.
          </p>
          <button type="button" className={`${btnPrimary} mt-4`} onClick={() => void run()}>Try again</button>
        </div>
      ) : null}

      {!loading && result?.available ? (
        <>
          {Object.entries(result.skipped ?? {}).length > 0 || (result.warnings ?? []).length > 0 ? (
            <ul className="mb-3 space-y-1 text-xs text-amber" aria-label="Notes">
              {Object.entries(result.skipped ?? {}).map(([where, why]) => (
                <li key={where}>Not searched ({where}): {why}.</li>
              ))}
              {(result.warnings ?? []).map((w) => <li key={w}>Note: {w}.</li>)}
            </ul>
          ) : null}
          {hits.length === 0 ? (
            <EmptyState title="No similar papers found">
              Nothing came close. Either no such paper is in {feedOn && effectiveScope !== "library" ? "your library or the feed" : "your library"} yet,
              or the text is too short or too general. Try a longer description, or widen the date.
            </EmptyState>
          ) : (
            <>
              <p className="mb-3 text-sm text-ink-2">
                {hits.length} {hits.length === 1 ? "paper" : "papers"}, closest first
              </p>
              <ul className="space-y-3" aria-label="Similar papers">
                {hits.map((h) => (
                  <SimilarRow key={`${h.source}:${h.id}`} hit={h} busy={busyId === h.id} onUseAsQuery={useAsQuery} onAdd={add} />
                ))}
              </ul>
            </>
          )}
        </>
      ) : null}
    </div>
  );
}
