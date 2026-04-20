import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { apiFetch, deletePaper } from "../api/client";
import PaperCard from "../components/PaperCard";
import PaperDrop from "../components/PaperDrop";
import EditPaperModal from "../components/EditPaperModal";
import EntityPanel from "../components/EntityPanel";
import type { EntityType } from "../components/EntityPanel";
import { useAppSettings } from "../contexts/SettingsContext";
import type { Paper, Project, SearchResponse, T_IngestOut, Stats } from "../types";

type ViewMode = "grid" | "list";

export default function Library() {
  const { settings } = useAppSettings();
  const navigate = useNavigate();
  const [papers, setPapers]     = useState<Paper[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [stats, setStats]           = useState<Stats | null>(null);
  const [loading, setLoading]       = useState(true);
  const [viewMode, setViewMode]     = useState<ViewMode>(settings.defaultView);
  const [page, setPage]             = useState(1);
  const [editingPaper, setEditingPaper] = useState<Paper | null>(null);
  const [activePanel, setActivePanel]   = useState<EntityType | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [surprisingMe, setSurprisingMe] = useState(false);

  const q             = searchParams.get("q") ?? "";
  const activeTag     = searchParams.get("tag") ?? "";
  const activeTopic   = searchParams.get("topic") ?? "";
  const activeProject = searchParams.get("project_id") ?? "";
  const activeStatus  = searchParams.get("reading_status") ?? "";
  const activeBookmarked = searchParams.get("bookmarked") === "true";
  const yearMin       = searchParams.get("year_min") ?? "";
  const yearMax       = searchParams.get("year_max") ?? "";
  const hasFilters    = q || activeTag || activeTopic || activeProject || activeStatus || activeBookmarked || yearMin || yearMax;

  // Sort papers per settings
  const sortedPapers = useMemo(() => {
    const sorted = [...papers];
    switch (settings.defaultSort) {
      case "date_asc":        return sorted.reverse();
      case "year_desc":       return sorted.sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
      case "year_asc":        return sorted.sort((a, b) => (a.year ?? 0) - (b.year ?? 0));
      case "title_asc":       return sorted.sort((a, b) => a.title.localeCompare(b.title));
      case "rating_desc":     return sorted.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
      case "citations_desc":  return sorted.sort((a, b) => (b.citation_count ?? 0) - (a.citation_count ?? 0));
      default:                return sorted; // date_desc = API order
    }
  }, [papers, settings.defaultSort]);

  // Paginate
  const perPage = settings.papersPerPage;
  const totalPages = perPage === 0 ? 1 : Math.ceil(sortedPapers.length / perPage);
  const visiblePapers = perPage === 0 ? sortedPapers : sortedPapers.slice((page - 1) * perPage, page * perPage);

  const loadPapers = async (params: URLSearchParams) => {
    setLoading(true);
    try {
      const hasFilter = params.get("q") || params.get("tag") || params.get("topic") ||
        params.get("project_id") || params.get("reading_status") || params.get("bookmarked") ||
        params.get("year_min") || params.get("year_max");
      if (hasFilter) {
        const res = await apiFetch<SearchResponse>(`/search?${params}`);
        setPapers(res.results);
      } else {
        const res = await apiFetch<Paper[]>("/papers");
        setPapers(res);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPapers(searchParams);
    apiFetch<Project[]>("/projects").then(setProjects).catch(() => {});
    apiFetch<Stats>("/stats").then(setStats).catch(() => {});
  }, [searchParams.toString()]);

  // Reset to page 1 when sort or per-page changes
  useEffect(() => { setPage(1); }, [settings.defaultSort, settings.papersPerPage]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (next.get(key) === value) next.delete(key);
    else next.set(key, value);
    setSearchParams(next);
  };

  const clearAll = () => setSearchParams(new URLSearchParams());

  const toggleBookmarked = () => {
    const next = new URLSearchParams(searchParams);
    if (activeBookmarked) next.delete("bookmarked");
    else next.set("bookmarked", "true");
    setSearchParams(next);
  };

  const setYearMin = (val: string) => {
    const next = new URLSearchParams(searchParams);
    if (val) next.set("year_min", val); else next.delete("year_min");
    setSearchParams(next);
  };

  const setYearMax = (val: string) => {
    const next = new URLSearchParams(searchParams);
    if (val) next.set("year_max", val); else next.delete("year_max");
    setSearchParams(next);
  };

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

  const refreshStats = () => apiFetch<Stats>("/stats").then(setStats).catch(() => {});

  const handleDeleted = (id: string) => {
    setPapers((prev) => prev.filter((p) => p.id !== id));
    refreshStats();
  };

  const handleUpdated = (updated: Paper) => {
    setPapers((prev) => prev.map((p) => p.id === updated.id ? updated : p));
    setEditingPaper(null);
  };

  return (
    <div className="h-[calc(100vh-53px)] overflow-y-auto">
      <main>
        {/* Search + upload + view toggle bar */}
        <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-6 py-3 flex gap-3 items-center flex-wrap">
          <input
            type="search"
            value={q}
            onChange={(e) => {
              const next = new URLSearchParams(searchParams);
              if (e.target.value) next.set("q", e.target.value);
              else next.delete("q");
              setSearchParams(next);
            }}
            placeholder="Search papers, notes…"
            className="flex-1 min-w-[160px] border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
          />

          {/* Year range */}
          <input
            type="number"
            value={yearMin}
            onChange={(e) => setYearMin(e.target.value)}
            placeholder="From year"
            className="w-24 border border-gray-200 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          <input
            type="number"
            value={yearMax}
            onChange={(e) => setYearMax(e.target.value)}
            placeholder="To year"
            className="w-24 border border-gray-200 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
          />

          {/* Reading status filter */}
          <select
            value={activeStatus}
            onChange={(e) => {
              const next = new URLSearchParams(searchParams);
              if (e.target.value) next.set("reading_status", e.target.value);
              else next.delete("reading_status");
              setSearchParams(next);
            }}
            className="border border-gray-200 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white text-gray-600"
          >
            <option value="">All statuses</option>
            <option value="unread">Unread</option>
            <option value="reading">Reading</option>
            <option value="read">Read</option>
          </select>

          {/* Bookmark filter */}
          <button
            onClick={toggleBookmarked}
            title={activeBookmarked ? "Showing bookmarked only — click to clear" : "Show bookmarked only"}
            className={`px-3 py-2 rounded-lg border text-sm transition-colors ${
              activeBookmarked
                ? "bg-amber-500 border-amber-500 text-white"
                : "border-gray-200 text-gray-400 hover:text-amber-500 hover:border-amber-300"
            }`}
          >
            ★
          </button>

          {/* Surprise Me */}
          <button
            onClick={surpriseMe}
            disabled={surprisingMe}
            title="Open a random paper"
            className="px-3 py-2 rounded-lg border border-gray-200 text-sm text-gray-500 hover:text-violet-600 hover:border-violet-300 transition-colors disabled:opacity-50 shrink-0"
          >
            {surprisingMe ? "…" : "🎲 Surprise"}
          </button>

          {/* View toggle */}
          <div className="flex border border-gray-200 rounded-lg overflow-hidden shrink-0">
            <button
              onClick={() => setViewMode("grid")}
              title="Grid view"
              className={`px-2.5 py-2 transition-colors ${viewMode === "grid" ? "bg-violet-600 text-white" : "text-gray-400 hover:bg-gray-50"}`}
            >
              <GridIcon />
            </button>
            <button
              onClick={() => setViewMode("list")}
              title="List view"
              className={`px-2.5 py-2 border-l border-gray-200 transition-colors ${viewMode === "list" ? "bg-violet-600 text-white" : "text-gray-400 hover:bg-gray-50"}`}
            >
              <ListIcon />
            </button>
          </div>
          <PaperDrop onUploaded={(p: T_IngestOut) => {
            setPapers((prev) => [p, ...prev]);
            refreshStats();
          }} />
        </div>

        <div className="p-6 space-y-6">
          {/* Active filter chips */}
          {hasFilters && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-xs text-gray-500">Showing:</span>
              {q            && <Chip label={`"${q}"`}    onRemove={() => setFilter("q", q)} />}
              {activeTag    && <Chip label={activeTag}   onRemove={() => setFilter("tag", activeTag)} />}
              {activeTopic  && <Chip label={activeTopic} onRemove={() => setFilter("topic", activeTopic)} />}
              {activeProject && (
                <Chip
                  label={projects.find((p) => p.id === activeProject)?.name ?? activeProject}
                  onRemove={() => setFilter("project_id", activeProject)}
                />
              )}
              {activeStatus && <Chip label={`Status: ${activeStatus}`} onRemove={() => setFilter("reading_status", activeStatus)} />}
              {activeBookmarked && <Chip label="★ Bookmarked" onRemove={toggleBookmarked} />}
              {yearMin && <Chip label={`From ${yearMin}`} onRemove={() => setYearMin("")} />}
              {yearMax && <Chip label={`To ${yearMax}`}   onRemove={() => setYearMax("")} />}
              <button onClick={clearAll} className="text-xs text-gray-400 hover:text-gray-600 underline">
                Clear all
              </button>
            </div>
          )}

          {/* Dashboard — only shown when no filters active */}
          {!hasFilters && stats && (
            <Dashboard
              stats={stats}
              onTopicClick={(name) => setFilter("topic", name)}
              onEntityClick={(type) => setActivePanel(type)}
            />
          )}

          {/* Paper list — shown always, below dashboard */}
          {loading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : papers.length === 0 ? (
            <p className="text-sm text-gray-400">No papers found.</p>
          ) : (
            <>
              {!hasFilters && (
                <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  All papers ({papers.length})
                </h2>
              )}
              {viewMode === "grid" ? (
                <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
                  {visiblePapers.map((p) => (
                    <PaperCard key={p.id} paper={p}
                      showAbstract={settings.showAbstractPreview}
                      onDeleted={handleDeleted}
                      onUpdated={handleUpdated}
                    />
                  ))}
                </div>
              ) : (
                <PaperListView
                  papers={visiblePapers}
                  onDeleted={handleDeleted}
                  onEdit={setEditingPaper}
                />
              )}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 pt-2">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="px-3 py-1 text-xs rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
                  >
                    ← Prev
                  </button>
                  <span className="text-xs text-gray-400">
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="px-3 py-1 text-xs rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
                  >
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </main>

      {editingPaper && (
        <EditPaperModal
          paper={editingPaper}
          onSaved={handleUpdated}
          onClose={() => setEditingPaper(null)}
        />
      )}

      {activePanel && (
        <EntityPanel
          type={activePanel}
          onClose={() => setActivePanel(null)}
          onStatsChanged={refreshStats}
        />
      )}
    </div>
  );
}

// ── List view ────────────────────────────────────────────────────────────────

function PaperListView({ papers, onDeleted, onEdit }: {
  papers: Paper[];
  onDeleted: (id: string) => void;
  onEdit: (p: Paper) => void;
}) {
  const navigate = useNavigate();
  const [confirmId, setConfirmId]   = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const handleDelete = async (p: Paper) => {
    if (confirmId !== p.id) { setConfirmId(p.id); return; }
    setDeletingId(p.id);
    try {
      await deletePaper(p.id);
      onDeleted(p.id);
    } finally {
      setDeletingId(null);
      setConfirmId(null);
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      {/* Header row */}
      <div className="grid grid-cols-[1fr_60px_180px_90px_90px] gap-4 px-4 py-2 bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-400 uppercase tracking-wide">
        <span>Title</span>
        <span>Year</span>
        <span>DOI</span>
        <span>Source</span>
        <span className="text-right">Actions</span>
      </div>

      {papers.map((p, i) => (
        <div
          key={p.id}
          onMouseLeave={() => setConfirmId(null)}
          className={`grid grid-cols-[1fr_60px_180px_90px_90px] gap-4 px-4 py-3 items-center text-sm
            hover:bg-violet-50 transition-colors cursor-pointer
            ${i !== papers.length - 1 ? "border-b border-gray-100" : ""}`}
        >
          {/* Title */}
          <span
            onClick={() => navigate(`/paper/${p.id}`)}
            className="font-medium text-gray-800 hover:text-violet-700 truncate"
          >
            {p.title}
          </span>

          {/* Year */}
          <span className="text-gray-400 text-xs">{p.year ?? "—"}</span>

          {/* DOI */}
          <span className="text-gray-400 text-xs truncate">{p.doi ?? "—"}</span>

          {/* Source */}
          <span className="text-xs">
            {p.metadata_source ? (
              <span className={`px-2 py-0.5 rounded-full font-medium ${
                p.metadata_source === "semantic_scholar" || p.metadata_source === "crossref"
                  ? "bg-green-100 text-green-700"
                  : p.metadata_source === "llm"
                  ? "bg-yellow-100 text-yellow-700"
                  : "bg-red-100 text-red-700"
              }`}>
                {p.metadata_source === "semantic_scholar" ? "S2" : p.metadata_source}
              </span>
            ) : "—"}
          </span>

          {/* Actions */}
          <div className="flex justify-end gap-1">
            <button
              onClick={(e) => { e.stopPropagation(); onEdit(p); }}
              title="Edit metadata"
              className="p-1.5 rounded border border-gray-200 text-gray-400 hover:text-violet-600 hover:border-violet-300 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
              </svg>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); handleDelete(p); }}
              disabled={deletingId === p.id}
              title={confirmId === p.id ? "Click again to confirm delete" : "Delete paper"}
              className={`p-1.5 rounded border transition-colors disabled:opacity-50 ${
                confirmId === p.id
                  ? "bg-red-600 border-red-600 text-white"
                  : "border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-300"
              }`}
            >
              {deletingId === p.id ? (
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
              )}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Icons ──────────────────────────────────────────────────────────────────────

function GridIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ stats, onTopicClick, onEntityClick }: {
  stats: Stats;
  onTopicClick: (name: string) => void;
  onEntityClick: (type: EntityType) => void;
}) {
  const { counts, papers_by_year, top_topics, recent_papers, reading_status } = stats;
  const navigate = useNavigate();

  const maxYear = Math.max(...papers_by_year.map((y) => y.count), 1);

  const STATUS_COLORS: Record<string, string> = {
    unread:  "bg-gray-100 text-gray-600",
    reading: "bg-blue-100 text-blue-700",
    read:    "bg-green-100 text-green-700",
  };

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
        <StatCard value={counts.papers}    label="Papers"     color="violet" onClick={() => onEntityClick("papers")}   />
        <StatCard value={counts.authors}   label="Authors"    color="blue"   onClick={() => onEntityClick("authors")}  />
        <StatCard value={counts.topics}    label="Topics"     color="green"  onClick={() => onEntityClick("topics")}   />
        <StatCard value={counts.tags}      label="Tags"       color="amber"  onClick={() => onEntityClick("tags")}     />
        <StatCard value={counts.projects}  label="Projects"   color="pink"   onClick={() => onEntityClick("projects")} />
        <StatCard value={counts.bookmarked ?? 0} label="Bookmarked" color="orange" />
      </div>

      {/* Reading status breakdown */}
      {reading_status && reading_status.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Reading progress</h3>
          <div className="flex flex-wrap gap-2">
            {reading_status.map(({ status, count }) => (
              <span key={status} className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full font-medium ${STATUS_COLORS[status] ?? "bg-gray-100 text-gray-600"}`}>
                {status === "unread" ? "📚 Unread" : status === "reading" ? "📖 Reading" : "✅ Read"}
                <span className="font-bold">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {/* Papers by year */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Papers by year
          </h3>
          {papers_by_year.length === 0 ? (
            <p className="text-xs text-gray-300">No data yet</p>
          ) : (
            <div className="space-y-1.5">
              {papers_by_year.slice(-12).map(({ year, count }) => (
                <div key={year} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-10 shrink-0">{year}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-2 rounded-full bg-violet-500 transition-all"
                      style={{ width: `${(count / maxYear) * 100}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-4 text-right">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top topics */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Top topics
          </h3>
          {top_topics.length === 0 ? (
            <p className="text-xs text-gray-300">No topics yet</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {top_topics.map(({ name, count }) => (
                <button
                  key={name}
                  onClick={() => onTopicClick(name)}
                  className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full hover:bg-blue-100 transition-colors"
                >
                  {name}
                  <span className="bg-blue-100 text-blue-500 rounded-full px-1.5 py-0.5 text-[10px] font-semibold">
                    {count}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Recent papers */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Recently added
          </h3>
          {recent_papers.length === 0 ? (
            <p className="text-xs text-gray-300">No papers yet</p>
          ) : (
            <ul className="space-y-2">
              {recent_papers.map((p) => (
                <li key={p.id}>
                  <button
                    onClick={() => navigate(`/paper/${p.id}`)}
                    className="w-full text-left group"
                  >
                    <p className="text-xs font-medium text-gray-800 group-hover:text-violet-600 line-clamp-1 leading-snug">
                      {p.title}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {p.authors?.slice(0, 2).join(", ")}
                      {p.year ? ` · ${p.year}` : ""}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

const STAT_COLORS: Record<string, { bg: string; text: string; num: string }> = {
  violet: { bg: "bg-violet-50", text: "text-violet-500", num: "text-violet-700" },
  blue:   { bg: "bg-blue-50",   text: "text-blue-500",   num: "text-blue-700"   },
  green:  { bg: "bg-green-50",  text: "text-green-500",  num: "text-green-700"  },
  amber:  { bg: "bg-amber-50",  text: "text-amber-500",  num: "text-amber-700"  },
  pink:   { bg: "bg-pink-50",   text: "text-pink-500",   num: "text-pink-700"   },
  orange: { bg: "bg-orange-50", text: "text-orange-500", num: "text-orange-700" },
};

function StatCard({ value, label, color, onClick }: { value: number; label: string; color: string; onClick?: () => void }) {
  const c = STAT_COLORS[color];
  return (
    <button
      onClick={onClick}
      className={`${c.bg} rounded-xl p-4 flex flex-col gap-1 text-left w-full transition-all hover:shadow-md hover:scale-[1.02] active:scale-[0.98] ${onClick ? "cursor-pointer" : ""}`}
    >
      <span className={`text-2xl font-bold ${c.num}`}>{value.toLocaleString()}</span>
      <span className={`text-xs font-medium ${c.text}`}>{label}</span>
    </button>
  );
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 bg-violet-100 text-violet-700 text-xs px-2 py-0.5 rounded-full">
      {label}
      <button onClick={onRemove} className="hover:text-violet-900">×</button>
    </span>
  );
}
