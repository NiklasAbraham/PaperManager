import { useState } from "react";
import { Link } from "react-router-dom";
import { discoverSearch, discoverAdd } from "../../api/client";
import type { DiscoverSearchResult } from "../../types";

type SourceFilter = "all" | "arxiv" | "s2" | "pubmed";

const SOURCES: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "arxiv", label: "arXiv" },
  { value: "s2", label: "Semantic Scholar" },
  { value: "pubmed", label: "PubMed" },
];

const BADGE_COLORS: Record<string, string> = {
  arxiv: "bg-orange-100 text-orange-700",
  semantic_scholar: "bg-blue-100 text-blue-700",
  pubmed: "bg-green-100 text-green-700",
};
const BADGE_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  semantic_scholar: "S2",
  pubmed: "PubMed",
};

function SourceBadge({ source }: { source: string }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${
        BADGE_COLORS[source] ?? "bg-gray-100 text-gray-700"
      }`}
    >
      {BADGE_LABELS[source] ?? source}
    </span>
  );
}

/** Ad-hoc query across arXiv, Semantic Scholar and PubMed with one-click add. */
export default function ExternalSearch() {
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [source, setSource] = useState<SourceFilter>("all");
  const [results, setResults] = useState<DiscoverSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingIds, setAddingIds] = useState<Set<string>>(new Set());

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setSearched(query);
    try {
      setResults(await discoverSearch(query, source));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async (result: DiscoverSearchResult) => {
    const key = result.url;
    setAddingIds((prev) => new Set(prev).add(key));
    try {
      const paper = await discoverAdd(result.url);
      setResults((prev) =>
        prev.map((r) =>
          r.url === result.url ? { ...r, in_library: true, library_paper_id: paper.id } : r
        )
      );
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to add paper");
    } finally {
      setAddingIds((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6">
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex flex-col sm:flex-row gap-2 mb-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for papers..."
            aria-label="Search query"
            className="flex-1 border border-line rounded-lg px-4 py-2 text-sm bg-raised text-ink focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? "Searching..." : "Search"}
          </button>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 items-center text-sm">
          <span className="text-xs font-medium text-ink-3 uppercase tracking-wide">Sources</span>
          {SOURCES.map((s) => (
            <label key={s.value} className="flex items-center gap-1.5 cursor-pointer text-ink-2">
              <input
                type="radio"
                name="external-source"
                value={s.value}
                checked={source === s.value}
                onChange={() => setSource(s.value)}
                className="accent-violet-600"
              />
              <span>{s.label}</span>
            </label>
          ))}
        </div>
      </form>

      {error && (
        <div className="p-4 mb-4 bg-red-50 border border-red-200 rounded-lg text-coral text-sm">
          {error}
        </div>
      )}

      {results.length > 0 && (
        <div className="mb-4 text-sm text-ink-2">
          {results.length} result{results.length !== 1 ? "s" : ""} for "{searched}"
        </div>
      )}

      <div className="space-y-3">
        {results.map((result) => (
          <div
            key={result.url}
            className="p-4 bg-raised border border-line rounded-xl hover:shadow-sm transition-shadow"
          >
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 sm:gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <h3 className="text-base font-semibold text-ink">{result.title}</h3>
                  <SourceBadge source={result.source} />
                  {result.year && <span className="text-sm text-ink-3">{result.year}</span>}
                </div>

                {result.authors.length > 0 && (
                  <p className="text-sm text-ink-2 mb-2">
                    {result.authors.slice(0, 5).join(", ")}
                    {result.authors.length > 5 && ` +${result.authors.length - 5} more`}
                  </p>
                )}

                {result.abstract && (
                  <p className="text-sm text-ink-2 line-clamp-3 mb-2">{result.abstract}</p>
                )}

                <a
                  href={result.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-accent hover:underline"
                >
                  View source
                </a>
              </div>

              <div className="flex-shrink-0">
                {result.in_library ? (
                  <Link
                    to={`/paper/${result.library_paper_id}`}
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-green-50 text-green-700 border border-green-200 rounded-lg hover:bg-green-100 text-sm font-medium"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                      <path
                        fillRule="evenodd"
                        d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
                        clipRule="evenodd"
                      />
                    </svg>
                    In library
                  </Link>
                ) : (
                  <button
                    onClick={() => handleAdd(result)}
                    disabled={addingIds.has(result.url)}
                    className="px-4 py-2 bg-accent text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                  >
                    {addingIds.has(result.url) ? "Adding..." : "Add"}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {!loading && !error && results.length === 0 && searched && (
        <div className="text-center py-12 text-ink-3">No results found for "{searched}"</div>
      )}
    </div>
  );
}
