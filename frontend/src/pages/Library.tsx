import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { apiFetch, interpretSearch, getVenuePapers } from "../api/client";
import PaperCard from "../components/PaperCard";
import PaperDrop from "../components/PaperDrop";
import EditPaperModal from "../components/EditPaperModal";
import EntityPanel from "../components/EntityPanel";
import ResearchGapPanel from "../components/ResearchGapPanel";
import type { EntityType } from "../components/EntityPanel";
import { useAppSettings } from "../contexts/SettingsContext";
import type { Paper, Project, SearchResponse, T_IngestOut, Stats, VenueOut } from "../types";

export default function Library() {
  const { settings } = useAppSettings();
  const navigate = useNavigate();
  const [papers, setPapers]     = useState<Paper[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [stats, setStats]           = useState<Stats | null>(null);
  const [loading, setLoading]       = useState(true);
  const [page, setPage]             = useState(1);
  const [editingPaper, setEditingPaper] = useState<Paper | null>(null);
  const [activePanel, setActivePanel]   = useState<EntityType | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [surprisingMe, setSurprisingMe] = useState(false);
  const [showResearchGaps, setShowResearchGaps] = useState(false);
  const [aiSearching, setAiSearching] = useState(false);

  const q             = searchParams.get("q") ?? "";
  const activeTag     = searchParams.get("tag") ?? "";
  const activeTopic   = searchParams.get("topic") ?? "";
  const activeProject = searchParams.get("project_id") ?? "";
  const activeStatus  = searchParams.get("reading_status") ?? "";
  const activeBookmarked = searchParams.get("bookmarked") === "true";
  const activeVenue   = searchParams.get("venue") ?? "";
  const hasFilters    = q || activeTag || activeTopic || activeProject || activeStatus || activeBookmarked || activeVenue;

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
      const venue = params.get("venue");
      if (venue) {
        // Venue filter — fetch from venue endpoint, apply any remaining filters client-side
        const all = await getVenuePapers(venue);
        const tag = params.get("tag");
        const q   = params.get("q")?.toLowerCase();
        setPapers(all.filter((p) => {
          if (q && !p.title.toLowerCase().includes(q) && !(p.abstract ?? "").toLowerCase().includes(q)) return false;
          return !tag; // tag filtering would need separate lookup; omit for simplicity
        }));
      } else {
        const hasFilter = params.get("q") || params.get("tag") || params.get("topic") ||
          params.get("project_id") || params.get("reading_status") || params.get("bookmarked");
        if (hasFilter) {
          const res = await apiFetch<SearchResponse>(`/search?${params}`);
          setPapers(res.results);
        } else {
          const res = await apiFetch<Paper[]>("/papers");
          setPapers(res);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (searchParams.has("year_min") || searchParams.has("year_max")) {
      const next = new URLSearchParams(searchParams);
      next.delete("year_min");
      next.delete("year_max");
      setSearchParams(next, { replace: true });
      return;
    }

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
    if (!q.trim() || aiSearching) return;
    setAiSearching(true);
    try {
      const result = await interpretSearch(q.trim());
      const next = new URLSearchParams();
      if (result.keyword) next.set("q", result.keyword);
      if (result.tag)     next.set("tag", result.tag);
      if (result.topic)   next.set("topic", result.topic);
      if (result.venue)   next.set("venue", result.venue);
      if (result.year_min) next.set("year_min", String(result.year_min));
      if (result.year_max) next.set("year_max", String(result.year_max));
      setSearchParams(next);
    } catch { /* ignore */ } finally {
      setAiSearching(false);
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
        <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-6 py-3 flex gap-2 items-center flex-wrap">
          {/* Search + AI button */}
          <div className="flex flex-1 min-w-[160px] items-center gap-1">
            <input
              type="search"
              value={q}
              onChange={(e) => {
                const next = new URLSearchParams(searchParams);
                if (e.target.value) next.set("q", e.target.value);
                else next.delete("q");
                setSearchParams(next);
              }}
              onKeyDown={(e) => { if (e.key === "Enter") runAiSearch(); }}
              placeholder="Search… or describe in plain language and press ✦"
              className="flex-1 h-9 border border-gray-200 rounded-lg px-3 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            <button
              onClick={runAiSearch}
              disabled={aiSearching || !q.trim()}
              title="Let AI interpret your query into filters"
              className={`h-9 px-2.5 rounded-lg border text-sm font-semibold transition-colors shrink-0 ${
                aiSearching
                  ? "border-violet-300 text-violet-400 bg-violet-50 cursor-wait"
                  : "border-violet-200 text-violet-500 bg-white hover:bg-violet-50 hover:border-violet-400 disabled:opacity-30"
              }`}
            >
              {aiSearching
                ? <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                : "✦"}
            </button>
          </div>

          {/* Reading status filter */}
          <select
            value={activeStatus}
            onChange={(e) => {
              const next = new URLSearchParams(searchParams);
              if (e.target.value) next.set("reading_status", e.target.value);
              else next.delete("reading_status");
              setSearchParams(next);
            }}
            className="h-9 border border-gray-200 rounded-lg px-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white text-gray-600 shrink-0"
          >
            <option value="">All statuses</option>
            <option value="unread">Unread</option>
            <option value="reading">Reading</option>
            <option value="read">Read</option>
          </select>

          {/* Right-side icon buttons — all h-9 w-9 */}
          <div className="flex items-center gap-2 shrink-0 ml-auto">
            {/* Bookmark filter */}
            <button
              onClick={toggleBookmarked}
              title={activeBookmarked ? "Showing bookmarked only — click to clear" : "Show bookmarked only"}
              className={`h-9 w-9 flex items-center justify-center rounded-lg border text-sm transition-colors ${
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
              className="h-9 w-9 flex items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:text-violet-600 hover:border-violet-300 transition-colors disabled:opacity-50"
            >
              {surprisingMe
                ? <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                : <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-3.866-3.134-7-7-7S5.5 8.134 5.5 12s3.134 7 7 7 7-3.134 7-7z"/><path strokeLinecap="round" strokeLinejoin="round" d="M9 9h.01M15 9h.01M9 15h.01M15 15h.01M12 12h.01"/></svg>
              }
            </button>

            {/* Research Gaps */}
            <button
              onClick={() => setShowResearchGaps(true)}
              title="Find research gaps"
              className="h-9 px-3 flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 text-gray-600 hover:text-violet-600 hover:border-violet-300 transition-colors text-sm font-medium whitespace-nowrap"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
              </svg>
              <span>Find Gaps</span>
            </button>

            <PaperDrop onUploaded={(p: T_IngestOut) => {
              setPapers((prev) => [p, ...prev]);
              refreshStats();
            }} debug={settings.debugMode} />
          </div>
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
              {activeVenue && <Chip label={`Venue: ${activeVenue}`} onRemove={() => setFilter("venue", activeVenue)} />}
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
              onVenueClick={(name) => setFilter("venue", name)}
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
              <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
                {visiblePapers.map((p) => (
                  <PaperCard key={p.id} paper={p}
                    showAbstract={settings.showAbstractPreview}
                    onDeleted={handleDeleted}
                    onUpdated={handleUpdated}
                  />
                ))}
              </div>

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
          onTagClick={(name) => {
            setActivePanel(null);
            const next = new URLSearchParams(searchParams);
            next.set("tag", name);
            setSearchParams(next);
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

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ stats, onTopicClick, onEntityClick, onVenueClick }: {
  stats: Stats;
  onTopicClick: (name: string) => void;
  onEntityClick: (type: EntityType) => void;
  onVenueClick: (name: string) => void;
}) {
  const { counts, papers_by_year, top_topics, recent_papers, reading_status } = stats;
  const navigate = useNavigate();
  const [venues, setVenues] = useState<VenueOut[]>([]);
  useEffect(() => {
    apiFetch<VenueOut[]>("/venues?min_count=2").then(setVenues).catch(() => {});
  }, []);

  const maxYear = Math.max(...papers_by_year.map((y) => y.count), 1);

  const STATUS_COLORS: Record<string, string> = {
    unread:  "bg-gray-100 text-gray-600",
    reading: "bg-blue-100 text-blue-700",
    read:    "bg-green-100 text-green-700",
  };

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
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

      {/* Venues */}
      {venues.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Venues</h3>
          <div className="flex flex-wrap gap-1.5">
            {venues.map((v) => (
              <button
                key={v.name}
                onClick={() => onVenueClick(v.name)}
                className="inline-flex items-center gap-1 text-xs bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-full hover:bg-indigo-100 transition-colors"
              >
                {v.name}
                <span className="bg-indigo-100 text-indigo-500 rounded-full px-1.5 py-0.5 text-[10px] font-semibold">
                  {v.count}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
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
