import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { apiFetch, interpretSearch, searchLibrary } from "../api/client";
import PaperCard from "../components/PaperCard";
import PaperDrop from "../components/PaperDrop";
import EntityPanel from "../components/EntityPanel";
import ResearchGapPanel from "../components/ResearchGapPanel";
import FilterMenu from "../components/search/FilterMenu";
import LibraryMenu from "../components/search/LibraryMenu";
import SearchBox, { type PickedSuggestion } from "../components/search/SearchBox";
import SearchResultRow from "../components/search/SearchResultRow";
import {
  QUERY_PAGE_ALL, activeFilterChips, buildSearchParams, clearFilters, effectiveSort,
  hasActiveFilters, sortOptions,
} from "../components/search/filterState";
import type { EntityType } from "../components/EntityPanel";
import Dashboard from "../components/dashboard/Dashboard";
import { parseVariant } from "../components/dashboard/helpers";
import { useAppSettings } from "../contexts/SettingsContext";
import type { Paper, Person, Project, SearchMode, SearchResponse, SearchResult, T_IngestOut } from "../types";

const MODES: { value: SearchMode; label: string; title: string }[] = [
  { value: "lexical", label: "Exact", title: "Words, prefixes and near-spellings only" },
  { value: "hybrid", label: "Hybrid", title: "Words and meaning combined (default)" },
  { value: "semantic", label: "Meaning", title: "Papers whose title and abstract mean something similar" },
];
const SECTION_HEADING = "text-xs font-semibold text-ink-3 uppercase tracking-wide";
const READING_PARAMS = () => new URLSearchParams({
  reading_status: "reading", sort: "updated_desc", skip: "0", limit: "6", include_references: "false", snippets: "0",
});

export default function Library() {
  const { settings } = useAppSettings();
  const navigate = useNavigate();
  // One listing for everything: ranked hits with a query, the filter-only listing without.
  const [res, setRes]           = useState<SearchResponse | null>(null);
  const [failed, setFailed]     = useState(false);
  const [reading, setReading]   = useState<SearchResult[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  // Key of the request whose results are on screen; "loading" while it differs from the
  // key of what the URL asks for (no synchronous setState in the fetch effect).
  const [doneKey, setDoneKey]   = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [activePanel, setActivePanel]   = useState<EntityType | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [surprisingMe, setSurprisingMe] = useState(false);
  const [showResearchGaps, setShowResearchGaps] = useState(false);
  const [aiSearching, setAiSearching] = useState(false);
  const [personNames, setPersonNames] = useState<Record<string, string>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  const q             = searchParams.get("q") ?? "";
  const activeProject = searchParams.get("project_id") ?? "";
  const activePerson  = searchParams.get("person_id") ?? "";
  const queryMode     = (searchParams.get("mode") as SearchMode) || "hybrid";
  const withRefs      = searchParams.get("refs") === "1";
  const hasQuery      = q.trim().length > 0;
  const hasNarrowing  = hasActiveFilters(searchParams);
  const hasFilters    = hasQuery || hasNarrowing;
  const sort          = effectiveSort(searchParams, hasQuery, settings.defaultSort);
  const chips = activeFilterChips(searchParams, {
    person: personNames[activePerson],
    project: projects.find((p) => p.id === activeProject)?.name,
  });

  // The text in the box runs ahead of the URL while typing; the URL follows debounced.
  const [input, setInput] = useState(q);
  const lastCommitted = useRef(q);
  useEffect(() => {
    if (q !== lastCommitted.current) {
      lastCommitted.current = q;
      setInput(q);
    }
  }, [q]);

  // Page number, reset whenever the query, a filter or the sort changes.
  const queryKey = searchParams.toString();
  const pageKey = `${queryKey}|${settings.defaultSort}|${settings.papersPerPage}`;
  const [pageState, setPageState] = useState({ key: pageKey, page: 1 });
  const page = pageState.key === pageKey ? pageState.page : 1;
  const setPage = (p: number) => {
    setPageState({ key: pageKey, page: p });
    scrollRef.current?.scrollTo?.({ top: 0 });
  };

  const perPage = settings.papersPerPage;
  const pageSize = perPage || QUERY_PAGE_ALL;
  const total = res?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const requestKey = `${queryKey}|${page}|${perPage}|${settings.defaultSort}|${reloadTick}`;
  const loading = doneKey !== requestKey;
  const latestKey = useRef(requestKey);

  const loadPapers = async (params: URLSearchParams, pageNo: number, key: string) => {
    latestKey.current = key;
    const stale = () => latestKey.current !== key; // a newer keystroke won
    try {
      const out = await searchLibrary(buildSearchParams(params, pageNo, perPage, new Date(), settings.defaultSort));
      if (stale()) return;
      setRes(out);
      setFailed(false);
    } catch {
      if (stale()) return;
      setRes(null);
      setFailed(true);
    }
    setDoneKey(key);
  };

  useEffect(() => {
    // State is only set once the request resolves (loadPapers awaits first).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPapers(searchParams, page, requestKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  useEffect(() => {
    apiFetch<Project[]>("/projects").then((p) => setProjects(Array.isArray(p) ? p : [])).catch(() => {});
  }, []);

  // Continue reading: the dashboard's one extra call.
  useEffect(() => {
    if (hasFilters) return;
    let live = true;
    searchLibrary(READING_PARAMS())
      .then((r) => { if (live) setReading(r?.results ?? []); })
      .catch(() => {});
    return () => { live = false; };
  }, [hasFilters, reloadTick]);

  // Name for the author chip when the page was opened with ?person_id=...
  useEffect(() => {
    if (activePerson && !personNames[activePerson]) {
      apiFetch<Person>(`/people/${activePerson}`)
        .then((p) => { if (p?.name) setPersonNames((m) => ({ ...m, [activePerson]: p.name })); })
        .catch(() => {});
    }
  }, [activePerson, personNames]);

  const update = (mutate: (next: URLSearchParams) => void, replace = false) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next, { replace });
  };

  const setParam = (key: string, value: string | null) => update((next) => {
    if (value) next.set(key, value);
    else next.delete(key);
  });

  const commitQuery = (text: string) => {
    if (text.trim() === q.trim()) return;
    lastCommitted.current = text;
    update((next) => {
      if (text.trim()) next.set("q", text);
      else next.delete("q");
    }, true);
  };

  const pickSuggestion = (s: PickedSuggestion) => {
    if (s.kind === "paper") {
      navigate(`/paper/${s.id}`);
      return;
    }
    // An author / topic / tag / project replaces the typed text with a filter.
    lastCommitted.current = "";
    setInput("");
    update((next) => {
      next.delete("q");
      if (s.kind === "author") {
        next.set("person_id", s.id);
        setPersonNames((m) => ({ ...m, [s.id]: s.name }));
      }
      if (s.kind === "topic") next.set("topic", s.name);
      if (s.kind === "tag") next.set("tag", s.name);
      if (s.kind === "project") next.set("project_id", s.id);
    });
  };

  const clearAll = () => {
    lastCommitted.current = "";
    setInput("");
    setSearchParams(clearFilters(searchParams, true));
  };

  const clearNarrowing = () => setSearchParams(clearFilters(searchParams));

  const surpriseMe = async () => {
    setSurprisingMe(true);
    try {
      const paper = await apiFetch<Paper>("/papers/random");
      navigate(`/paper/${paper.id}`);
    } catch {
      // no papers
    } finally {
      setSurprisingMe(false);
    }
  };

  const runAiSearch = async () => {
    const text = input.trim();
    if (!text || aiSearching) return;
    setAiSearching(true);
    try {
      const result = await interpretSearch(text);
      const next = new URLSearchParams();
      if (result.keyword) next.set("q", result.keyword);
      if (result.tag)     next.set("tag", result.tag);
      if (result.topic)   next.set("topic", result.topic);
      if (result.venue)   next.set("venue", result.venue);
      if (result.year_min) next.set("year_min", String(result.year_min));
      if (result.year_max) next.set("year_max", String(result.year_max));
      const keepSort = searchParams.get("sort");
      if (keepSort && keepSort !== "relevance") next.set("sort", keepSort);
      setSearchParams(next);
    } catch { /* ignore */ } finally {
      setAiSearching(false);
    }
  };

  const handleDeleted = (id: string) => {
    setRes((r) => r && { ...r, results: r.results.filter((p) => p.id !== id), total: Math.max(0, r.total - 1) });
  };

  const handleUpdated = (updated: Paper) => {
    setRes((r) => r && { ...r, results: r.results.map((p) => p.id === updated.id ? { ...p, ...updated } : p) });
  };

  // A new upload shows at the top of the unfiltered newest-first list at once; any other
  // view (a project filter, another sort, a later page) reloads, since where it belongs differs.
  const handleUploaded = (p: T_IngestOut) => {
    if (!hasFilters && page === 1 && sort === "date_desc" && res) {
      const row: SearchResult = { ...p, score: 0, matched_in: "paper" };
      setRes({ ...res, results: [row, ...res.results.filter((x) => x.id !== p.id)].slice(0, pageSize), total: res.total + 1 });
    } else {
      setReloadTick((t) => t + 1);
    }
  };

  const semanticNote = (() => {
    if (!res || queryMode === "lexical" || res.mode !== "lexical") return null;
    const s = res.semantic;
    if (s && s.state !== "ready" && s.enabled) {
      return s.state === "building" && s.todo
        ? `Meaning search is still indexing (${s.done} / ${s.todo} papers); showing exact matches.`
        : "Meaning search is starting up; showing exact matches.";
    }
    return queryMode === "semantic" ? "Nothing in the library is close enough in meaning; showing exact matches." : null;
  })();

  const dashVariant = parseVariant(searchParams);
  const libraryTitle = (
    <>
      Library
      {res && <span className="font-normal text-ink-3"> · {res.total.toLocaleString()} paper{res.total === 1 ? "" : "s"}</span>}
    </>
  );

  const sortSelect = (
    <select
      aria-label="Sort results"
      value={sort}
      onChange={(e) => setParam("sort", e.target.value === "relevance" ? null : e.target.value)}
      className="h-7 border border-line rounded px-2 text-xs bg-raised text-ink-2 focus:outline-none focus:ring-2 focus:ring-violet-300"
    >
      {sortOptions(hasQuery).map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
    </select>
  );

  const removeFiltersButton = (
    <button onClick={clearNarrowing} className="px-3 py-1.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
      Remove filters
    </button>
  );

  // The paged card grid of the dashboard and of a filter-only listing.
  const browseBody = (() => {
    if (failed) {
      return (
        <div className="text-sm text-ink-3 space-y-2">
          <p>The library could not be loaded.</p>
          <button onClick={() => setReloadTick((t) => t + 1)} className="text-xs text-accent underline">Try again</button>
        </div>
      );
    }
    if (!res) return <p className="text-sm text-ink-3">Loading…</p>;
    if (res.results.length === 0 && !loading) {
      return hasNarrowing ? (
        <div className="bg-raised border border-line rounded-xl p-6 text-center space-y-3">
          <p className="text-sm text-ink">No papers match these filters.</p>
          <div className="flex justify-center">{removeFiltersButton}</div>
        </div>
      ) : (
        <p className="text-sm text-ink-3">No papers yet. Use the + button to add the first one.</p>
      );
    }
    return (
      <>
        <div className={`grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 ${loading ? "opacity-60" : ""}`}>
          {res.results.map((p) => (
            <PaperCard key={p.id} paper={p}
              showAbstract={settings.showAbstractPreview}
              onDeleted={handleDeleted}
              onUpdated={handleUpdated}
            />
          ))}
        </div>
        {totalPages > 1 && <Pager page={page} totalPages={totalPages} onPage={setPage} />}
      </>
    );
  })();

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      {/* Search, filters, upload: one wrapping bar */}
      <div className="sticky top-0 z-20 bg-raised border-b border-line-s px-4 sm:px-6 py-3 flex flex-wrap items-center gap-2">
        <div className="flex w-full sm:w-auto sm:flex-1 min-w-0">
          <SearchBox
            value={input}
            onChange={setInput}
            onCommit={commitQuery}
            onPick={pickSuggestion}
            placeholder="Search titles, authors, notes, highlights, full text… or describe it and press ✦"
          >
            <button
              onClick={runAiSearch}
              disabled={aiSearching || !input.trim()}
              title="Let AI interpret your query into filters"
              className={`h-9 px-2.5 rounded-lg border text-sm font-semibold transition-colors shrink-0 ${
                aiSearching
                  ? "border-accent-border text-accent bg-accent-lo cursor-wait"
                  : "border-accent-border text-accent bg-raised hover:bg-accent-lo disabled:opacity-30"
              }`}
            >
              {aiSearching
                ? <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                : "✦"}
            </button>
          </SearchBox>
        </div>

        <div className="flex w-full sm:w-auto items-center gap-2">
          <FilterMenu
            params={searchParams}
            count={chips.length}
            hasQuery={hasQuery}
            sort={sort}
            projects={projects}
            onChange={(mutate) => update(mutate)}
            onClear={clearNarrowing}
          />
          <div className="flex items-center gap-2 ml-auto sm:ml-0">
            <PaperDrop
              onUploaded={handleUploaded}
              debug={settings.debugMode}
              defaultProjectId={activeProject || undefined}
            />
            <LibraryMenu
              surprising={surprisingMe}
              onSurprise={surpriseMe}
              onGaps={() => setShowResearchGaps(true)}
              onManage={setActivePanel}
            />
          </div>
        </div>
      </div>

      <main className="px-4 sm:px-6 py-5 space-y-5">
        {/* Active filters */}
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2 items-center" aria-label="Active filters">
            {chips.map((c) => (
              <Chip key={c.id} label={c.label} onRemove={() => update((next) => c.keys.forEach((k) => next.delete(k)))} />
            ))}
            <button onClick={clearAll} className="text-xs text-ink-3 hover:text-accent underline">
              Clear all
            </button>
          </div>
        )}

        {hasQuery ? (
          <section className="space-y-3" aria-label="Search results">
            {/* Results header: count, mode, references, sort */}
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs text-ink-3" aria-live="polite">
                {loading && !res ? "Searching…" : res && (
                  <>
                    <span className="font-semibold text-ink-2">{res.total.toLocaleString()}</span>
                    {` result${res.total === 1 ? "" : "s"}`}
                    {res.took_ms != null && ` · ${Math.round(res.took_ms)} ms`}
                    {loading && " · updating…"}
                  </>
                )}
              </p>
              <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
                <div role="group" aria-label="Search mode" className="flex rounded-lg border border-line overflow-hidden">
                  {MODES.map((m) => (
                    <button
                      key={m.value}
                      title={m.title}
                      aria-pressed={queryMode === m.value}
                      onClick={() => setParam("mode", m.value === "hybrid" ? null : m.value)}
                      className={`px-2.5 h-7 text-xs ${queryMode === m.value ? "bg-accent text-white" : "bg-raised text-ink-2 hover:text-accent"}`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-1 text-xs text-ink-2 cursor-pointer" title="Also search cited references that have no PDF in the library">
                  <input type="checkbox" checked={withRefs} onChange={() => setParam("refs", withRefs ? null : "1")} />
                  References
                </label>
                {sortSelect}
              </div>
            </div>

            {semanticNote && <p className="text-xs text-amber">{semanticNote}</p>}
            {res?.relaxed && res.results.length > 0 && (
              <p className="text-xs text-amber">
                No paper contains every word of “{q}”; showing papers that match some of them.
              </p>
            )}

            {failed ? (
              <p className="text-sm text-ink-3">The search failed. Try again in a moment.</p>
            ) : res && res.results.length === 0 && !loading ? (
              <div className="bg-raised border border-line rounded-xl p-6 text-center space-y-3">
                <p className="text-sm text-ink">
                  No papers match “{q}”{hasNarrowing ? " with these filters" : ""}.
                </p>
                <p className="text-xs text-ink-3">
                  Titles, authors, topics, tags, abstracts, your notes and highlights, claims and full texts were searched.
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {!withRefs && (
                    <button onClick={() => setParam("refs", "1")} className="px-3 py-1.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
                      Search cited references too
                    </button>
                  )}
                  {queryMode !== "semantic" && (
                    <button onClick={() => setParam("mode", "semantic")} className="px-3 py-1.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
                      Search by meaning
                    </button>
                  )}
                  {hasNarrowing && removeFiltersButton}
                </div>
              </div>
            ) : (
              <ul className={`space-y-2 ${loading ? "opacity-60" : ""}`}>
                {res?.results.map((hit) => <SearchResultRow key={hit.id} hit={hit} />)}
              </ul>
            )}

            {res && totalPages > 1 && (
              <Pager page={page} totalPages={totalPages} onPage={setPage} />
            )}
          </section>
        ) : hasNarrowing ? (
          <section className="space-y-3" aria-label="Filtered papers">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-ink-3" aria-live="polite">
                {res && (
                  <>
                    <span className="font-semibold text-ink-2">{res.total.toLocaleString()}</span>
                    {` paper${res.total === 1 ? "" : "s"}`}
                    {loading && " · updating…"}
                  </>
                )}
              </p>
              {sortSelect}
            </div>
            {browseBody}
          </section>
        ) : (
          <>
            {dashVariant === "off" ? (
              <h1 className="text-sm font-semibold text-ink">{libraryTitle}</h1>
            ) : (
              <Dashboard
                variant={dashVariant}
                title={libraryTitle}
                onFilter={(key, value) => update((next) => { next.set(key, value); })}
              />
            )}

            {reading.length > 0 && (
              <section className="space-y-1.5" aria-label="Continue reading">
                <h2 className={SECTION_HEADING}>Continue reading</h2>
                {/* One slim row of three: the dashboard above already takes the space (two on phones). */}
                <ul className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {reading.slice(0, 3).map((p, i) => (
                    <li key={p.id} className={i >= 2 ? "hidden sm:block" : undefined}>
                      <Link
                        to={`/paper/${p.id}`}
                        title={p.title}
                        className="flex items-center gap-2 h-9 bg-raised border border-line rounded-lg px-3 hover:border-accent-border transition-colors"
                      >
                        <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-[#eda100]" />
                        <span className="text-sm text-ink truncate">{p.title}</span>
                        {p.year && <span className="text-xs text-ink-3 shrink-0 ml-auto">{p.year}</span>}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="space-y-3" aria-label="Papers">
              <div className="flex items-center justify-between gap-3">
                <h2 className={SECTION_HEADING}>{sort === "date_desc" ? "Recently added" : "All papers"}</h2>
                {sortSelect}
              </div>
              {browseBody}
            </section>
          </>
        )}
      </main>


      {activePanel && (
        <EntityPanel
          type={activePanel}
          onClose={() => setActivePanel(null)}
          onStatsChanged={() => setReloadTick((t) => t + 1)}
          onTagClick={(name) => {
            setActivePanel(null);
            update((next) => { next.set("tag", name); });
          }}
        />
      )}

      {showResearchGaps && (
        <ResearchGapPanel
          onClose={() => setShowResearchGaps(false)}
          projectId={activeProject || undefined}
        />
      )}
    </div>
  );
}

function Pager({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  const btn = "px-3 py-1 text-xs rounded border border-line text-ink-2 hover:border-accent-border hover:text-accent disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-2";
  return (
    <div className="flex items-center justify-center gap-2 pt-2">
      <button onClick={() => onPage(Math.max(1, page - 1))} disabled={page === 1} className={btn}>
        ← Prev
      </button>
      <span className="text-xs text-ink-3">
        {page} / {totalPages}
      </span>
      <button onClick={() => onPage(Math.min(totalPages, page + 1))} disabled={page === totalPages} className={btn}>
        Next →
      </button>
    </div>
  );
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 bg-accent-lo text-accent border border-accent-border text-xs pl-2.5 pr-1.5 py-0.5 rounded-full">
      {label}
      <button onClick={onRemove} aria-label={`Remove ${label}`} className="hover:text-violet-900 leading-none px-0.5">×</button>
    </span>
  );
}
