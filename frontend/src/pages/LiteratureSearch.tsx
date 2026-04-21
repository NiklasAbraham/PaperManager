import { useRef, useState } from "react";
import type { LitPaper, LiteratureSseEvent } from "../types";
import { searchLiterature, ingestFromUrl } from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

type Status = "idle" | "searching" | "done" | "error";
type ImportState = "idle" | "importing" | "done" | "error";

interface ResultPaper extends LitPaper {
  _importState: ImportState;
  _importedId?: string;
  _importError?: string;
  // Track already_in_library reactively
  _inLibrary: boolean;
}

// ── Source config ─────────────────────────────────────────────────────────────

const SOURCE_META: Record<string, { label: string; color: string; bg: string }> = {
  arxiv:   { label: "arXiv",   color: "text-orange-700", bg: "bg-orange-100" },
  pubmed:  { label: "PubMed",  color: "text-blue-700",   bg: "bg-blue-100"   },
  biorxiv: { label: "bioRxiv", color: "text-green-700",  bg: "bg-green-100"  },
};

// ── Paper card ────────────────────────────────────────────────────────────────

function PaperCard({
  paper,
  onImport,
}: {
  paper: ResultPaper;
  onImport: (paper: ResultPaper) => void;
}) {
  const sm = SOURCE_META[paper.source] ?? { label: paper.source, color: "text-gray-700", bg: "bg-gray-100" };
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-2 hover:shadow-sm transition-shadow">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3
            className="text-sm font-semibold text-gray-900 leading-snug cursor-pointer hover:text-violet-700"
            onClick={() => window.open(paper.url, "_blank")}
          >
            {paper.title}
          </h3>
          <div className="flex flex-wrap items-center gap-2 mt-1">
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${sm.bg} ${sm.color}`}>
              {sm.label}
            </span>
            {paper.date && (
              <span className="text-xs text-gray-500">{paper.date}</span>
            )}
            {paper.year && !paper.date && (
              <span className="text-xs text-gray-500">{paper.year}</span>
            )}
            {paper.doi && (
              <span className="text-xs text-gray-400 truncate max-w-[180px]">{paper.doi}</span>
            )}
          </div>
          {paper.authors.length > 0 && (
            <p className="text-xs text-gray-500 mt-1 truncate">
              {paper.authors.slice(0, 4).join(", ")}
              {paper.authors.length > 4 && ` +${paper.authors.length - 4} more`}
            </p>
          )}
        </div>

        {/* Import button */}
        <div className="flex-shrink-0">
          {paper._inLibrary || paper._importState === "done" ? (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded-full whitespace-nowrap">
              In library
            </span>
          ) : paper._importState === "importing" ? (
            <span className="text-xs text-violet-600 bg-violet-50 px-2 py-1 rounded-full animate-pulse whitespace-nowrap">
              Importing…
            </span>
          ) : paper._importState === "error" ? (
            <button
              onClick={() => onImport(paper)}
              className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded-full hover:bg-red-100 whitespace-nowrap"
              title={paper._importError}
            >
              Retry
            </button>
          ) : (
            <button
              onClick={() => onImport(paper)}
              className="text-xs text-white bg-violet-600 px-3 py-1 rounded-full hover:bg-violet-700 whitespace-nowrap"
            >
              Import
            </button>
          )}
        </div>
      </div>

      {/* Abstract */}
      {paper.abstract && (
        <div>
          <p
            className={`text-xs text-gray-600 leading-relaxed ${expanded ? "" : "line-clamp-2"}`}
          >
            {paper.abstract}
          </p>
          {paper.abstract.length > 200 && (
            <button
              className="text-xs text-violet-500 hover:text-violet-700 mt-0.5"
              onClick={() => setExpanded(e => !e)}
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}

      {paper._importError && paper._importState === "error" && (
        <p className="text-xs text-red-500">{paper._importError}</p>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LiteratureSearch() {
  const [days, setDays] = useState(7);
  const [maxPerSource, setMaxPerSource] = useState(100);
  const [sources, setSources] = useState<Record<string, boolean>>({
    arxiv: true,
    pubmed: true,
    biorxiv: true,
  });
  const [status, setStatus] = useState<Status>("idle");
  const [results, setResults] = useState<ResultPaper[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [currentlySearching, setCurrentlySearching] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const activeSources = Object.entries(sources)
    .filter(([, v]) => v)
    .map(([k]) => k);

  // ── Search handler ──────────────────────────────────────────────────────────

  async function handleSearch() {
    if (activeSources.length === 0) return;
    abortRef.current = new AbortController();
    setResults([]);
    setCounts({});
    setCurrentlySearching(null);
    setErrorMsg(null);
    setStatus("searching");

    try {
      for await (const event of searchLiterature(
        { days, max_per_source: maxPerSource, sources: activeSources },
        abortRef.current.signal,
      )) {
        if ("done" in event && event.done) {
          setCounts(event.counts);
          setCurrentlySearching(null);
          setStatus("done");
          break;
        }
        if ("searching" in event && event.searching) {
          setCurrentlySearching(event.searching as string);
        }
        if ("paper" in event && event.paper) {
          const p = event.paper as LitPaper;
          setResults(prev => [...prev, {
            ...p,
            _importState: "idle",
            _inLibrary: p.already_in_library,
          }]);
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === "AbortError") {
        setStatus("done");
      } else {
        setErrorMsg(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
      setCurrentlySearching(null);
    }
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  // ── Import handler ──────────────────────────────────────────────────────────

  async function handleImport(paper: ResultPaper) {
    setResults(prev =>
      prev.map(p =>
        p.url === paper.url ? { ...p, _importState: "importing" } : p
      )
    );
    try {
      await ingestFromUrl(paper.url);
      setResults(prev =>
        prev.map(p =>
          p.url === paper.url
            ? { ...p, _importState: "done", _inLibrary: true }
            : p
        )
      );
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setResults(prev =>
        prev.map(p =>
          p.url === paper.url
            ? { ...p, _importState: "error", _importError: msg }
            : p
        )
      );
    }
  }

  // ── Group results by source ─────────────────────────────────────────────────

  const grouped = activeSources.reduce<Record<string, ResultPaper[]>>((acc, src) => {
    acc[src] = results.filter(p => p.source === src);
    return acc;
  }, {});

  const totalFound = results.length;
  const alreadyCount = results.filter(p => p._inLibrary).length;
  const importedCount = results.filter(p => p._importState === "done" && !p._inLibrary).length;

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* Controls bar */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex flex-wrap items-end gap-4">
          {/* Days selector */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 font-medium">Date range</label>
            <select
              value={days}
              onChange={e => setDays(Number(e.target.value))}
              disabled={status === "searching"}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>

          {/* Max per source */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 font-medium">Max per source</label>
            <select
              value={maxPerSource}
              onChange={e => setMaxPerSource(Number(e.target.value))}
              disabled={status === "searching"}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
            >
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </div>

          {/* Source toggles */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 font-medium">Sources</label>
            <div className="flex gap-2">
              {Object.entries(SOURCE_META).map(([key, meta]) => (
                <label
                  key={key}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium cursor-pointer transition-colors ${
                    sources[key]
                      ? `${meta.bg} ${meta.color} border-transparent`
                      : "bg-white text-gray-500 border-gray-300"
                  } ${status === "searching" ? "opacity-50 cursor-not-allowed" : ""}`}
                >
                  <input
                    type="checkbox"
                    className="hidden"
                    checked={!!sources[key]}
                    disabled={status === "searching"}
                    onChange={e =>
                      setSources(prev => ({ ...prev, [key]: e.target.checked }))
                    }
                  />
                  {meta.label}
                </label>
              ))}
            </div>
          </div>

          {/* Search / Stop button */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 font-medium invisible">Action</label>
            {status === "searching" ? (
              <button
                onClick={handleStop}
                className="px-4 py-1.5 rounded text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300"
              >
                Stop
              </button>
            ) : (
              <button
                onClick={handleSearch}
                disabled={activeSources.length === 0}
                className="px-4 py-1.5 rounded text-sm font-medium bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Search
              </button>
            )}
          </div>

          {/* Keywords note */}
          <p className="text-xs text-gray-400 self-end pb-1.5">
            Keywords: <code className="bg-gray-100 px-1 rounded">prompts/literature_search_keywords.txt</code>
          </p>
        </div>

        {/* Status bar */}
        {status === "searching" && (
          <div className="mt-3 flex items-center gap-2 text-sm text-gray-500">
            <svg className="w-4 h-4 animate-spin text-violet-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
            <span>
              {currentlySearching
                ? `Searching ${SOURCE_META[currentlySearching]?.label ?? currentlySearching}…`
                : "Searching…"}
              {totalFound > 0 && ` — ${totalFound} found so far`}
            </span>
          </div>
        )}
        {status === "done" && totalFound > 0 && (
          <div className="mt-3 text-sm text-gray-500 flex gap-4">
            <span><strong className="text-gray-800">{totalFound}</strong> papers found</span>
            <span><strong className="text-gray-800">{alreadyCount}</strong> already in library</span>
            {importedCount > 0 && (
              <span><strong className="text-violet-700">{importedCount}</strong> imported this session</span>
            )}
            {Object.entries(counts).map(([src, n]) => (
              <span key={src} className="text-xs">
                {SOURCE_META[src]?.label ?? src}: {n}
              </span>
            ))}
          </div>
        )}
        {status === "error" && errorMsg && (
          <p className="mt-3 text-sm text-red-600">{errorMsg}</p>
        )}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {status === "idle" && (
          <div className="flex flex-col items-center justify-center h-64 text-gray-400 text-sm gap-2">
            <svg className="w-10 h-10 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
            <p>Select a date range and click Search to discover recent papers.</p>
          </div>
        )}

        {(status === "searching" || status === "done") && totalFound === 0 && status === "done" && (
          <div className="flex flex-col items-center justify-center h-64 text-gray-400 text-sm gap-2">
            <p>No results found for the selected date range and keywords.</p>
            <p className="text-xs">Try editing <code className="bg-gray-100 px-1 rounded">prompts/literature_search_keywords.txt</code> or increasing the date range.</p>
          </div>
        )}

        {/* Results grouped by source */}
        {activeSources.map(src => {
          const papers = grouped[src];
          if (!papers || (papers.length === 0 && status === "done")) return null;
          if (papers.length === 0) return null;

          const meta = SOURCE_META[src];
          return (
            <div key={src} className="mb-8">
              <div className="flex items-center gap-2 mb-3">
                <h2 className={`text-sm font-semibold ${meta.color}`}>{meta.label}</h2>
                <span className={`text-xs px-2 py-0.5 rounded-full ${meta.bg} ${meta.color}`}>
                  {papers.length}
                </span>
              </div>
              <div className="grid gap-3 grid-cols-1 xl:grid-cols-2">
                {papers.map((paper, i) => (
                  <PaperCard
                    key={`${src}-${i}`}
                    paper={paper}
                    onImport={handleImport}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
