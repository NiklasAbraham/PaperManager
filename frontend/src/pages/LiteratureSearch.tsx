import { useSearchParams } from "react-router-dom";
import ExternalSearch from "../components/literature/ExternalSearch";
import KeywordFeed from "../components/literature/KeywordFeed";

type Tab = "search" | "feed";

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "search", label: "Search", hint: "arXiv, Semantic Scholar, PubMed" },
  { id: "feed", label: "Feed", hint: "Recent papers for your keywords" },
];

/** "Find papers": ad-hoc search (Search tab) and the keyword feed (Feed tab, default). */
export default function LiteratureSearch() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "search" ? "search" : "feed";

  const select = (next: Tab) => {
    const p = new URLSearchParams(params);
    p.set("tab", next);
    setParams(p, { replace: true });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="bg-raised border-b border-line px-4 sm:px-6 pt-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="pb-2">
          <h1 className="text-xl font-bold text-ink">Find papers</h1>
          <p className="text-xs text-ink-3">Search the literature, or follow what is new for your keywords.</p>
        </div>
        <div role="tablist" aria-label="Find papers" className="flex gap-1">
          {TABS.map((t) => {
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                role="tab"
                aria-selected={active}
                title={t.hint}
                onClick={() => select(t.id)}
                className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  active
                    ? "border-accent text-accent"
                    : "border-transparent text-ink-2 hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>
      {/* The feed scrolls its own results area; the search tab scrolls the page body */}
      <div className={`flex-1 min-h-0 ${tab === "search" ? "overflow-auto" : "overflow-hidden"}`}>
        {tab === "search" ? <ExternalSearch /> : <KeywordFeed />}
      </div>
    </div>
  );
}
