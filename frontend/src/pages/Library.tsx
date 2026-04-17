import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import PaperCard from "../components/PaperCard";
import PaperDrop from "../components/PaperDrop";
import type { Paper, Tag, Topic, Project, SearchResponse, T_IngestOut } from "../types";

export default function Library() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();

  const q = searchParams.get("q") ?? "";
  const activeTag = searchParams.get("tag") ?? "";
  const activeTopic = searchParams.get("topic") ?? "";
  const activeProject = searchParams.get("project_id") ?? "";

  const loadPapers = async (params: URLSearchParams) => {
    setLoading(true);
    try {
      const hasFilter = params.get("q") || params.get("tag") || params.get("topic") || params.get("project_id");
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
    apiFetch<Tag[]>("/tags").then(setTags).catch(() => {});
    apiFetch<Topic[]>("/topics").then(setTopics).catch(() => {});
    apiFetch<Project[]>("/projects").then(setProjects).catch(() => {});
  }, [searchParams.toString()]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (next.get(key) === value) {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setSearchParams(next);
  };

  const clearAll = () => setSearchParams(new URLSearchParams());

  const hasFilters = q || activeTag || activeTopic || activeProject;

  return (
    <div className="flex h-[calc(100vh-53px)]">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 border-r border-gray-200 bg-white overflow-y-auto p-4 space-y-6">
        <FilterSection title="Tags">
          {tags.map((t) => (
            <FilterItem
              key={t.id}
              label={t.name}
              count={t.paper_count}
              active={activeTag === t.name}
              onClick={() => setFilter("tag", t.name)}
            />
          ))}
        </FilterSection>
        <FilterSection title="Topics">
          {topics.map((t) => (
            <FilterItem
              key={t.id}
              label={t.name}
              count={t.paper_count}
              active={activeTopic === t.name}
              onClick={() => setFilter("topic", t.name)}
            />
          ))}
        </FilterSection>
        <FilterSection title="Projects">
          {projects.map((p) => (
            <FilterItem
              key={p.id}
              label={p.name}
              active={activeProject === p.id}
              onClick={() => setFilter("project_id", p.id)}
            />
          ))}
        </FilterSection>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        {/* Search + upload bar */}
        <div className="flex gap-3 items-start">
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
            className="flex-1 border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          <div className="w-64 shrink-0">
            <PaperDrop onUploaded={(p: T_IngestOut) => setPapers((prev) => [p, ...prev])} />
          </div>
        </div>

        {/* Active filter chips */}
        {hasFilters && (
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-gray-500">Showing:</span>
            {q && <Chip label={`"${q}"`} onRemove={() => setFilter("q", q)} />}
            {activeTag && <Chip label={activeTag} onRemove={() => setFilter("tag", activeTag)} />}
            {activeTopic && <Chip label={activeTopic} onRemove={() => setFilter("topic", activeTopic)} />}
            {activeProject && (
              <Chip
                label={projects.find((p) => p.id === activeProject)?.name ?? activeProject}
                onRemove={() => setFilter("project_id", activeProject)}
              />
            )}
            <button onClick={clearAll} className="text-xs text-gray-400 hover:text-gray-600 underline">
              Clear all
            </button>
          </div>
        )}

        {/* Grid */}
        {loading ? (
          <p className="text-sm text-gray-400">Loading…</p>
        ) : papers.length === 0 ? (
          <p className="text-sm text-gray-400">No papers found.</p>
        ) : (
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
            {papers.map((p) => <PaperCard key={p.id} paper={p} />)}
          </div>
        )}
      </main>
    </div>
  );
}

function FilterSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">{title}</h3>
      <ul className="space-y-1">{children}</ul>
    </div>
  );
}

function FilterItem({
  label, count, active, onClick,
}: {
  label: string; count?: number; active: boolean; onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        className={`w-full text-left text-xs px-2 py-1 rounded flex justify-between gap-1 transition-colors
          ${active ? "bg-violet-100 text-violet-700 font-medium" : "text-gray-600 hover:bg-gray-100"}`}
      >
        <span className="truncate">{label}</span>
        {count != null && <span className="text-gray-400">{count}</span>}
      </button>
    </li>
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
