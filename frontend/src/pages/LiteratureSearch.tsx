import { useEffect, useRef, useState } from "react";
import type { LitPaper, LiteratureSseEvent, T_IngestOut } from "../types";
import { searchLiterature, getLiteratureKeywords, putLiteratureKeywords, listProjects, getProjectKeywords } from "../api/client";
import UploadConfirmModal from "../components/UploadConfirmModal";
import OnboardingModal from "../components/OnboardingModal";
import { useAppSettings } from "../contexts/SettingsContext";

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
  const { settings } = useAppSettings();
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

  // Keywords editor
  const [kwText, setKwText] = useState<string>("");
  const [kwEditing, setKwEditing] = useState(false);
  const [kwSaving, setKwSaving] = useState(false);
  const [kwDraft, setKwDraft] = useState<string>("");

  // Project selector
  const [projects, setProjects] = useState<{id: string; name: string}[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [projectKwCount, setProjectKwCount] = useState<number | null>(null);

  useEffect(() => {
    getLiteratureKeywords().then(r => setKwText(r.content)).catch(() => {});
    listProjects().then(setProjects).catch(() => {});
  }, []);

  // When project selection changes, fetch its keyword count
  useEffect(() => {
    if (!selectedProjectId) { setProjectKwCount(null); return; }
    getProjectKeywords(selectedProjectId)
      .then(r => {
        const count = r.content.split("\n").filter(l => l.trim() && !l.trim().startsWith("#")).length;
        setProjectKwCount(count);
      })
      .catch(() => setProjectKwCount(0));
  }, [selectedProjectId]);

  async function saveKeywords() {
    setKwSaving(true);
    try {
      const r = await putLiteratureKeywords(kwDraft);
      setKwText(r.content);
      setKwEditing(false);
    } finally {
      setKwSaving(false);
    }
  }

  // Parsed keyword list for display (non-comment, non-empty lines)
  const kwList = kwText
    .split("\n")
    .map(l => l.trim())
    .filter(l => l && !l.startsWith("#"));

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
        { days, max_per_source: maxPerSource, sources: activeSources, project_id: selectedProjectId ?? null },
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

  // ── Import state ──────────────────────────────────────────────────────────────

  const [importingPaper, setImportingPaper] = useState<ResultPaper | null>(null);
  const [onboardingPaper, setOnboardingPaper] = useState<T_IngestOut | null>(null);

  function handleImport(paper: ResultPaper) {
    setImportingPaper(paper);
  }

  function handleImportConfirmed(result: T_IngestOut) {
    if (!importingPaper) return;
    setResults(prev =>
      prev.map(p =>
        p.url === importingPaper.url
          ? { ...p, _importState: "done", _inLibrary: true, _importedId: result.id }
          : p
      )
    );
    setImportingPaper(null);
    setOnboardingPaper(result);
  }

  function handleImportCancel() {
    setImportingPaper(null);
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
          <div className="flex min-w-0 flex-1 flex-wrap items-end gap-4">
            {/* Days selector */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500 font-medium">Date range</label>
              <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-1 shadow-sm">
                {[
                  { value: 7, label: "7d" },
                  { value: 14, label: "14d" },
                  { value: 30, label: "30d" },
                ].map((option) => {
                  const selected = days === option.value;

                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setDays(option.value)}
                      disabled={status === "searching"}
                      aria-pressed={selected}
                      className={`min-w-[64px] rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                        selected
                          ? "bg-white text-violet-700 shadow-sm ring-1 ring-violet-200"
                          : "text-gray-500 hover:text-gray-700"
                      } ${status === "searching" ? "cursor-not-allowed opacity-50" : ""}`}
                    >
                      {option.label}
                    </button>
                  );
                })}

                <div className="flex items-center gap-2 rounded-lg border border-transparent bg-white/80 px-2 py-1 ring-1 ring-gray-200">
                  <span className="text-xs font-medium uppercase tracking-wide text-gray-400">Custom</span>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={days}
                    onChange={(e) => {
                      const next = Number(e.target.value);
                      if (Number.isFinite(next) && next > 0) setDays(next);
                    }}
                    disabled={status === "searching"}
                    className="w-20 border-0 bg-transparent p-0 text-sm font-medium text-gray-700 focus:outline-none focus:ring-0"
                  />
                  <span className="text-xs font-medium text-gray-400">days</span>
                </div>
              </div>
            </div>

            {/* Max per source */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500 font-medium">Max per source</label>
              <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-1 shadow-sm">
                {[50, 100, 200].map((value) => {
                  const selected = maxPerSource === value;

                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setMaxPerSource(value)}
                      disabled={status === "searching"}
                      aria-pressed={selected}
                      className={`min-w-[58px] rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                        selected
                          ? "bg-white text-violet-700 shadow-sm ring-1 ring-violet-200"
                          : "text-gray-500 hover:text-gray-700"
                      } ${status === "searching" ? "cursor-not-allowed opacity-50" : ""}`}
                    >
                      {value}
                    </button>
                  );
                })}

                <div className="flex items-center gap-2 rounded-lg border border-transparent bg-white/80 px-2 py-1 ring-1 ring-gray-200">
                  <span className="text-xs font-medium uppercase tracking-wide text-gray-400">Custom</span>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={maxPerSource}
                    onChange={(e) => {
                      const next = Number(e.target.value);
                      if (Number.isFinite(next) && next > 0) setMaxPerSource(next);
                    }}
                    disabled={status === "searching"}
                    className="w-20 border-0 bg-transparent p-0 text-sm font-medium text-gray-700 focus:outline-none focus:ring-0"
                  />
                </div>
              </div>
            </div>

            {/* Source toggles */}
            <div className="flex min-w-0 flex-col gap-1">
              <label className="text-xs text-gray-500 font-medium">Sources</label>
              <div className="flex flex-wrap gap-2 rounded-xl border border-gray-200 bg-gray-50 p-1 shadow-sm">
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

            {/* Project context selector */}
            {projects.length > 0 && (
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 font-medium">Keyword context</label>
                <select
                  value={selectedProjectId ?? ""}
                  onChange={(e) => setSelectedProjectId(e.target.value || null)}
                  disabled={status === "searching"}
                  className="h-[42px] rounded-xl border border-gray-200 bg-gray-50 px-3 text-sm text-gray-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:opacity-50"
                >
                  <option value="">Default keywords</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                {selectedProjectId && (
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    {projectKwCount === null
                      ? "Loading…"
                      : projectKwCount === 0
                      ? "No project keywords — using default"
                      : `${projectKwCount} project keyword(s)`}
                  </p>
                )}
              </div>
            )}

            {/* Keywords button */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500 font-medium invisible">kw</label>
              <button
                onClick={() => { setKwDraft(kwText); setKwEditing(true); }}
                className="flex h-[42px] items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 text-sm font-medium text-gray-600 shadow-sm transition-colors hover:border-violet-200 hover:bg-white hover:text-violet-700"
              >
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-violet-600 ring-1 ring-violet-100">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536M9 11l6-6 3 3-6 6H9v-3z" />
                  </svg>
                </span>
                <span>Default keywords</span>
                {kwList.length > 0 && (
                  <span className="ml-1 rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-gray-500 ring-1 ring-gray-200">
                    {kwList.length}
                  </span>
                )}
              </button>
            </div>
          </div>

          {/* Search / Stop button */}
          <div className="ml-auto flex flex-col gap-1 self-end">
            <label className="text-xs text-gray-500 font-medium invisible">Action</label>
            {status === "searching" ? (
              <button
                onClick={handleStop}
                className="h-[42px] px-5 rounded-xl text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300"
              >
                Stop
              </button>
            ) : (
              <button
                onClick={handleSearch}
                disabled={activeSources.length === 0}
                className="h-[42px] px-5 rounded-xl text-sm font-medium bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Search
              </button>
            )}
          </div>
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

      {/* Import modal */}
      {importingPaper && (
        <UploadConfirmModal
          file={null}
          url={importingPaper.url}
          meta={{
            title: importingPaper.title,
            authors: importingPaper.authors,
            year: importingPaper.year,
            doi: importingPaper.doi ?? undefined,
            abstract: importingPaper.abstract ?? undefined,
            metadata_source: importingPaper.source,
          }}
          onConfirmed={handleImportConfirmed}
          onCancel={handleImportCancel}
          debug={settings.debugMode}
        />
      )}

      {/* Onboarding modal */}
      {onboardingPaper && (
        <OnboardingModal
          paper={onboardingPaper}
          onClose={() => setOnboardingPaper(null)}
        />
      )}

      {/* Keywords modal */}
      {kwEditing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-[500px] max-w-[95vw] flex flex-col">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <h2 className="text-sm font-semibold text-gray-900">Edit search keywords</h2>
              <button
                onClick={() => setKwEditing(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="px-5 py-4 flex flex-col gap-3">
              <p className="text-xs text-gray-500">
                One keyword or phrase per line. Lines starting with <code className="bg-gray-100 px-1 rounded">#</code> are comments and ignored. Terms are OR-ed and searched across arXiv, PubMed, and bioRxiv.
              </p>
              <textarea
                value={kwDraft}
                onChange={e => setKwDraft(e.target.value)}
                rows={14}
                autoFocus
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono bg-gray-50 resize-none w-full focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
                placeholder="One keyword per line…"
              />
            </div>
            <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-100">
              <button
                onClick={() => setKwEditing(false)}
                className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                onClick={saveKeywords}
                disabled={kwSaving}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {kwSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
