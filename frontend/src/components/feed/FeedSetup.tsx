import { useState } from "react";
import type { FormEvent } from "react";
import type { FeedConfig, FeedSource } from "../../api/feed";
import { Card, btnPrimary, btnSecondary, inputCls } from "../insights/ui";

const SOURCES: { value: FeedSource; label: string; hint: string }[] = [
  { value: "arxiv", label: "arXiv", hint: "Only the categories you choose below" },
  { value: "biorxiv", label: "bioRxiv", hint: "All new preprints, ranked for you" },
  { value: "medrxiv", label: "medRxiv", hint: "All new preprints, ranked for you" },
];
const EXAMPLES = ["cs.LG", "cs.CV", "q-bio.BM"];
const CATEGORY_RE = /^[a-z-]+(\.[A-Za-z-]+)?$/;
const MAX_CATEGORIES = 30;
const DAY_CHOICES = [1, 2, 3, 5, 7, 14];

export default function FeedSetup({
  config,
  saving,
  error,
  onSave,
  onCancel,
}: {
  config: FeedConfig;
  saving: boolean;
  error: string | null;
  onSave: (next: FeedConfig) => void;
  onCancel?: () => void;
}) {
  const [sources, setSources] = useState<FeedSource[]>(config.sources);
  const [categories, setCategories] = useState<string[]>(config.arxiv_categories);
  const [days, setDays] = useState(config.digest_days);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const toggleSource = (s: FeedSource) =>
    setSources((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));

  const addCategories = (raw: string) => {
    const parts = raw.split(/[\s,]+/).filter(Boolean);
    const next = [...categories];
    for (const p of parts) {
      if (!CATEGORY_RE.test(p)) {
        setProblem(`"${p}" is not an arXiv category. Use names like cs.LG or q-bio.BM.`);
        return false;
      }
      if (!next.includes(p)) next.push(p);
    }
    if (next.length > MAX_CATEGORIES) {
      setProblem(`At most ${MAX_CATEGORIES} categories.`);
      return false;
    }
    setProblem(null);
    setCategories(next);
    return true;
  };

  const submitCategory = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim() && addCategories(text)) setText("");
  };

  const needsCategory = sources.length === 1 && sources[0] === "arxiv" && categories.length === 0;
  const canSave = sources.length > 0 && !needsCategory && !saving;

  return (
    <Card title="What should the feed show?" aside="Stays on this instance">
      <fieldset className="mb-4">
        <legend className="mb-1 text-sm font-medium text-ink">Sources</legend>
        <div className="space-y-1.5">
          {SOURCES.map((s) => (
            <label key={s.value} className="flex items-start gap-2 text-sm text-ink-2">
              <input
                type="checkbox"
                checked={sources.includes(s.value)}
                onChange={() => toggleSource(s.value)}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-ink">{s.label}</span>
                <span className="ml-2 text-xs text-ink-3">{s.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mb-4">
        <form onSubmit={submitCategory}>
          <label htmlFor="feed-category" className="mb-1 block text-sm font-medium text-ink">
            arXiv categories
          </label>
          <div className="flex gap-2">
            <input
              id="feed-category"
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="cs.LG"
              aria-describedby="feed-category-help"
              className={`${inputCls} min-w-0 flex-1`}
            />
            <button type="submit" className={btnSecondary} disabled={!text.trim()}>
              Add
            </button>
          </div>
        </form>
        <p id="feed-category-help" className="mt-1 text-xs text-ink-3">
          The feed fetches only what you choose here. Press Enter to add; several at once with commas.
        </p>
        {problem ? <p role="alert" className="mt-1 text-xs text-coral">{problem}</p> : null}

        {categories.length > 0 ? (
          <ul aria-label="Chosen categories" className="mt-2 flex flex-wrap gap-1.5">
            {categories.map((c) => (
              <li key={c} className="inline-flex items-center gap-1 rounded-full border border-accent-border bg-accent-lo px-2.5 py-0.5 text-xs text-accent">
                {c}
                <button
                  type="button"
                  aria-label={`Remove ${c}`}
                  onClick={() => setCategories(categories.filter((x) => x !== c))}
                  className="rounded-full px-1 hover:text-coral focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
                >
                  &times;
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
          Examples:
          {EXAMPLES.filter((c) => !categories.includes(c)).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => addCategories(c)}
              className="rounded-full border border-line bg-raised px-2.5 py-0.5 text-ink-2 hover:border-accent-border hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
            >
              + {c}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <label htmlFor="feed-days" className="mb-1 block text-sm font-medium text-ink">
          Digest window
        </label>
        <select id="feed-days" value={days} onChange={(e) => setDays(Number(e.target.value))} className={inputCls}>
          {(DAY_CHOICES.includes(config.digest_days) ? DAY_CHOICES : [...DAY_CHOICES, config.digest_days].sort((a, b) => a - b)).map((d) => (
            <option key={d} value={d}>
              Last {d} {d === 1 ? "day" : "days"}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3">
        {error ? <span role="alert" className="min-w-0 break-words text-sm text-coral">{error}</span> : null}
        {needsCategory ? <span className="text-xs text-ink-3">Add at least one category.</span> : null}
        {onCancel ? (
          <button type="button" className={btnSecondary} onClick={onCancel}>
            Cancel
          </button>
        ) : null}
        <button
          type="button"
          className={btnPrimary}
          disabled={!canSave}
          onClick={() =>
            onSave({ sources, arxiv_categories: categories, digest_days: days, min_score: config.min_score })
          }
        >
          {saving ? "Saving" : "Save"}
        </button>
      </div>
    </Card>
  );
}
