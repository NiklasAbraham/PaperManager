import { useState } from "react";
import { Link } from "react-router-dom";
import { discoverSearch, discoverAdd } from "../api/client";
import type { DiscoverSearchResult } from "../types";

export default function Discover() {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<"all" | "arxiv" | "s2" | "pubmed">("all");
  const [results, setResults] = useState<DiscoverSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingIds, setAddingIds] = useState<Set<string>>(new Set());

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const data = await discoverSearch(query, source);
      setResults(data);
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
      // Update the result to mark it as in library
      setResults((prev) =>
        prev.map((r) =>
          r.url === result.url
            ? { ...r, in_library: true, library_paper_id: paper.id }
            : r
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

  const getSourceBadge = (src: string) => {
    const colors = {
      arxiv: "bg-orange-100 text-orange-700",
      semantic_scholar: "bg-blue-100 text-blue-700",
      pubmed: "bg-green-100 text-green-700",
    };
    const labels = {
      arxiv: "arXiv",
      semantic_scholar: "S2",
      pubmed: "PubMed",
    };
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[src as keyof typeof colors] || "bg-gray-100 text-gray-700"}`}>
        {labels[src as keyof typeof labels] || src}
      </span>
    );
  };

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">Discover Papers</h1>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for papers..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-2 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? "Searching..." : "Search"}
          </button>
        </div>

        {/* Source Filter */}
        <div className="flex gap-4 items-center text-sm">
          <span className="text-gray-600 font-medium">Sources:</span>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              value="all"
              checked={source === "all"}
              onChange={(e) => setSource(e.target.value as typeof source)}
              className="text-violet-600"
            />
            <span>All</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              value="arxiv"
              checked={source === "arxiv"}
              onChange={(e) => setSource(e.target.value as typeof source)}
              className="text-violet-600"
            />
            <span>arXiv</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              value="s2"
              checked={source === "s2"}
              onChange={(e) => setSource(e.target.value as typeof source)}
              className="text-violet-600"
            />
            <span>Semantic Scholar</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              value="pubmed"
              checked={source === "pubmed"}
              onChange={(e) => setSource(e.target.value as typeof source)}
              className="text-violet-600"
            />
            <span>PubMed</span>
          </label>
        </div>
      </form>

      {/* Error */}
      {error && (
        <div className="p-4 mb-4 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="mb-4 text-sm text-gray-600">
          {results.length} result{results.length !== 1 ? "s" : ""} for "{query}"
        </div>
      )}

      <div className="space-y-4">
        {results.map((result, idx) => (
          <div
            key={idx}
            className="p-4 bg-white border border-gray-200 rounded shadow-sm hover:shadow-md transition-shadow"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-lg font-semibold text-gray-900">
                    {result.title}
                  </h3>
                  {getSourceBadge(result.source)}
                  {result.year && (
                    <span className="text-sm text-gray-500">{result.year}</span>
                  )}
                </div>

                {result.authors.length > 0 && (
                  <p className="text-sm text-gray-600 mb-2">
                    {result.authors.slice(0, 5).join(", ")}
                    {result.authors.length > 5 && ` +${result.authors.length - 5} more`}
                  </p>
                )}

                {result.abstract && (
                  <p className="text-sm text-gray-700 line-clamp-3 mb-2">
                    {result.abstract}
                  </p>
                )}

                <a
                  href={result.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-violet-600 hover:underline"
                >
                  View source →
                </a>
              </div>

              <div className="flex-shrink-0">
                {result.in_library ? (
                  <Link
                    to={`/paper/${result.library_paper_id}`}
                    className="flex items-center gap-1.5 px-4 py-2 bg-green-50 text-green-700 border border-green-200 rounded hover:bg-green-100 text-sm font-medium"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="w-4 h-4"
                    >
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
                    className="px-4 py-2 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                  >
                    {addingIds.has(result.url) ? "Adding..." : "Add"}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {!loading && results.length === 0 && query && (
        <div className="text-center py-12 text-gray-500">
          No results found for "{query}"
        </div>
      )}
    </div>
  );
}
