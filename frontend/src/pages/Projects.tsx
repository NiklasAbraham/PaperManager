import { useEffect, useState, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  listProjects, getProject, createProject, updateProject, deleteProject,
  removePaperFromProject, getProjectNote, saveProjectNote,
  getProjectKeywords, saveProjectKeywords,
  projectBibtexUrl, projectCsvUrl, projectConversationsUrl, addPaperToProject, apiFetch,
} from "../api/client";

const STATUS_OPTIONS = ["active", "paused", "done"] as const;
const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  paused: "bg-yellow-100 text-yellow-700",
  done:   "bg-gray-100 text-gray-500",
};

interface PaperRow {
  id: string; title: string; year?: number; doi?: string;
  authors?: string[]; abstract?: string; metadata_source?: string;
}

interface ProjectDetail {
  id: string; name: string; description?: string; status?: string;
  papers: PaperRow[];
}

type DetailTab = "papers" | "note" | "keywords" | "stats";

export default function Projects() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [projects, setProjects]     = useState<{id:string;name:string;description?:string;status?:string}[]>([]);
  const [selected, setSelected]     = useState<ProjectDetail | null>(null);
  const [detailTab, setDetailTab]   = useState<DetailTab>("papers");
  const [loading, setLoading]       = useState(false);

  // Create form
  const [newName, setNewName]         = useState("");
  const [newDesc, setNewDesc]         = useState("");
  const [creating, setCreating]       = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Edit inline
  const [editingName, setEditingName]   = useState(false);
  const [editName, setEditName]         = useState("");
  const [editingDesc, setEditingDesc]   = useState(false);
  const [editDesc, setEditDesc]         = useState("");
  const [savingMeta, setSavingMeta]     = useState(false);

  // Delete
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting]           = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);

  // Note
  const [note, setNote]         = useState("");
  const [noteLoaded, setNoteLoaded] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [noteSaved, setNoteSaved]   = useState(false);
  const noteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keywords
  const [kwText, setKwText]           = useState("");
  const [kwLoaded, setKwLoaded]       = useState(false);
  const [savingKw, setSavingKw]       = useState(false);
  const [kwSaved, setKwSaved]         = useState(false);
  const kwTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Paper search (add paper)
  const [paperQuery, setPaperQuery]   = useState("");
  const [paperResults, setPaperResults] = useState<PaperRow[]>([]);
  const [searching, setSearching]     = useState(false);
  const [addingPaper, setAddingPaper] = useState<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load list on mount
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);

  // Auto-select from URL param
  useEffect(() => {
    const id = searchParams.get("id");
    if (id && projects.length) {
      const p = projects.find((p) => p.id === id);
      if (p) selectProject(p.id);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  const selectProject = async (id: string) => {
    setLoading(true);
    setConfirmDelete(false);
    setEditingName(false);
    setEditingDesc(false);
    setNoteLoaded(false);
    setNote("");
    setKwLoaded(false);
    setKwText("");
    setDetailTab("papers");
    setPaperQuery("");
    setPaperResults([]);
    setSearchParams({ id });
    try {
      const detail = await getProject(id);
      setSelected(detail as ProjectDetail);
      setEditName(detail.name);
      setEditDesc(detail.description || "");
    } finally {
      setLoading(false);
    }
  };

  // Load note when switching to note tab
  useEffect(() => {
    if (detailTab === "note" && selected && !noteLoaded) {
      getProjectNote(selected.id)
        .then((r) => { setNote(r.content); setNoteLoaded(true); })
        .catch(() => setNoteLoaded(true));
    }
  }, [detailTab, selected, noteLoaded]);

  // Load keywords when switching to keywords tab
  useEffect(() => {
    if (detailTab === "keywords" && selected && !kwLoaded) {
      getProjectKeywords(selected.id)
        .then((r) => { setKwText(r.content); setKwLoaded(true); })
        .catch(() => setKwLoaded(true));
    }
  }, [detailTab, selected, kwLoaded]);

  const create = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const p = await createProject({ name: newName.trim(), description: newDesc.trim() || undefined });
      const updated = await listProjects();
      setProjects(updated);
      setNewName(""); setNewDesc(""); setShowCreateForm(false);
      selectProject(p.id);
    } finally { setCreating(false); }
  };

  const saveName = async () => {
    if (!selected || !editName.trim()) return;
    setSavingMeta(true);
    await updateProject(selected.id, { name: editName.trim() });
    setSelected((s) => s ? { ...s, name: editName.trim() } : s);
    setProjects((ps) => ps.map((p) => p.id === selected.id ? { ...p, name: editName.trim() } : p));
    setSavingMeta(false); setEditingName(false);
  };

  const saveDesc = async () => {
    if (!selected) return;
    setSavingMeta(true);
    await updateProject(selected.id, { description: editDesc.trim() || undefined });
    setSelected((s) => s ? { ...s, description: editDesc.trim() || undefined } : s);
    setProjects((ps) => ps.map((p) => p.id === selected.id ? { ...p, description: editDesc.trim() || undefined } : p));
    setSavingMeta(false); setEditingDesc(false);
  };

  const saveStatus = async (status: string) => {
    if (!selected) return;
    await updateProject(selected.id, { status });
    setSelected((s) => s ? { ...s, status } : s);
    setProjects((ps) => ps.map((p) => p.id === selected.id ? { ...p, status } : p));
  };

  const handleDelete = async () => {
    if (!selected) return;
    setDeleting(true);
    try {
      await deleteProject(selected.id);
      setProjects((ps) => ps.filter((p) => p.id !== selected.id));
      setSelected(null);
      setSearchParams({});
    } finally { setDeleting(false); setConfirmDelete(false); }
  };

  const handleDeleteFromList = async (projectId: string, projectName: string) => {
    const confirmed = window.confirm(`Delete "${projectName}"? Papers are kept; only the project grouping is removed.`);
    if (!confirmed) return;
    setDeletingProjectId(projectId);
    try {
      await deleteProject(projectId);
      setProjects((ps) => ps.filter((p) => p.id !== projectId));
      if (selected?.id === projectId) {
        setSelected(null);
        setSearchParams({});
      }
    } finally {
      setDeletingProjectId(null);
    }
  };

  const removePaper = async (paperId: string) => {
    if (!selected) return;
    await removePaperFromProject(selected.id, paperId);
    setSelected((s) => s ? { ...s, papers: s.papers.filter((p) => p.id !== paperId) } : s);
  };

  // Note auto-save with debounce
  const handleNoteChange = (val: string) => {
    setNote(val);
    setNoteSaved(false);
    if (noteTimer.current) clearTimeout(noteTimer.current);
    noteTimer.current = setTimeout(async () => {
      if (!selected) return;
      setSavingNote(true);
      try { await saveProjectNote(selected.id, val); setNoteSaved(true); } catch { /* ignore */ }
      setSavingNote(false);
    }, 1000);
  };

  // Keywords auto-save with debounce
  const handleKwChange = (val: string) => {
    setKwText(val);
    setKwSaved(false);
    if (kwTimer.current) clearTimeout(kwTimer.current);
    kwTimer.current = setTimeout(async () => {
      if (!selected) return;
      setSavingKw(true);
      try { await saveProjectKeywords(selected.id, val); setKwSaved(true); } catch { /* ignore */ }
      setSavingKw(false);
    }, 1000);
  };

  // Paper search
  const handlePaperSearch = (q: string) => {
    setPaperQuery(q);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!q.trim()) { setPaperResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await apiFetch<PaperRow[]>(`/search?q=${encodeURIComponent(q)}&limit=10`);
        const existingIds = new Set(selected?.papers.map((p) => p.id) || []);
        setPaperResults(res.filter((r) => !existingIds.has(r.id)));
      } catch { setPaperResults([]); }
      setSearching(false);
    }, 400);
  };

  const handleAddPaper = async (paperId: string) => {
    if (!selected) return;
    setAddingPaper(paperId);
    try {
      await addPaperToProject(selected.id, paperId);
      const detail = await getProject(selected.id);
      setSelected(detail as ProjectDetail);
      setPaperQuery(""); setPaperResults([]);
    } finally { setAddingPaper(null); }
  };

  const stats = selected ? {
    papers: selected.papers.length,
    years: [...new Set(selected.papers.map((p) => p.year).filter(Boolean))].sort(),
    sources: [...new Set(selected.papers.map((p) => p.metadata_source).filter(Boolean))],
  } : null;

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Left: project list ── */}
      <div className="w-64 shrink-0 border-r border-gray-200 bg-white flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h1 className="text-sm font-semibold text-gray-900">Projects</h1>
          <button
            onClick={() => setShowCreateForm((v) => !v)}
            className="text-xs px-2 py-1 bg-violet-600 text-white rounded hover:bg-violet-700 font-medium"
          >
            + New
          </button>
        </div>

        {showCreateForm && (
          <div className="px-3 py-3 border-b border-gray-100 bg-violet-50 space-y-2">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
              placeholder="Project name…"
              className="w-full border border-gray-200 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            <input
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Description (optional)"
              className="w-full border border-gray-200 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            <div className="flex gap-2">
              <button
                onClick={create}
                disabled={creating || !newName.trim()}
                className="flex-1 py-1.5 bg-violet-600 text-white text-xs rounded hover:bg-violet-700 disabled:opacity-50 font-medium"
              >
                {creating ? "Creating…" : "Create"}
              </button>
              <button onClick={() => setShowCreateForm(false)} className="text-xs text-gray-500 hover:text-gray-700 px-2">
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {projects.length === 0 ? (
            <p className="text-xs text-gray-400 p-4">No projects yet.</p>
          ) : (
            projects.map((p) => (
              <div
                key={p.id}
                className={`group flex items-stretch border-b border-gray-50 transition-colors ${
                  selected?.id === p.id
                    ? "bg-violet-50 border-l-2 border-l-violet-600"
                    : "hover:bg-gray-50 border-l-2 border-l-transparent"
                }`}
              >
                <button
                  onClick={() => selectProject(p.id)}
                  className="flex-1 text-left px-4 py-3 min-w-0"
                >
                  <p className="text-xs font-medium text-gray-800 leading-snug truncate">{p.name}</p>
                  {p.description && (
                    <p className="text-[10px] text-gray-400 mt-0.5 truncate">{p.description}</p>
                  )}
                  {p.status && (
                    <span className={`inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[p.status] ?? "bg-gray-100 text-gray-500"}`}>
                      {p.status}
                    </span>
                  )}
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleDeleteFromList(p.id, p.name);
                  }}
                  disabled={deletingProjectId === p.id}
                  title={`Delete ${p.name}`}
                  className="shrink-0 px-2.5 text-xs text-gray-300 hover:text-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {deletingProjectId === p.id ? "…" : "Delete"}
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Right: detail panel ── */}
      <div className="flex-1 flex flex-col overflow-hidden bg-gray-50">
        {!selected && !loading && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-gray-400">Select a project or create one.</p>
          </div>
        )}

        {loading && (
          <div className="flex-1 flex items-center justify-center">
            <svg className="animate-spin h-5 w-5 text-violet-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
            </svg>
          </div>
        )}

        {selected && !loading && (
          <>
            {/* Header */}
            <div className="bg-white border-b border-gray-200 px-8 py-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  {/* Name */}
                  {editingName ? (
                    <div className="flex items-center gap-2">
                      <input
                        autoFocus
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") saveName(); if (e.key === "Escape") { setEditingName(false); setEditName(selected.name); } }}
                        className="flex-1 text-lg font-semibold border border-violet-300 rounded px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-violet-300"
                      />
                      <button onClick={saveName} disabled={savingMeta} className="text-xs px-2.5 py-1 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50">Save</button>
                      <button onClick={() => { setEditingName(false); setEditName(selected.name); }} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
                    </div>
                  ) : (
                    <h2
                      className="text-lg font-semibold text-gray-900 cursor-pointer hover:text-violet-700 transition-colors group flex items-center gap-2"
                      onClick={() => setEditingName(true)}
                    >
                      {selected.name}
                      <span className="text-xs text-gray-300 group-hover:text-violet-400 font-normal">✎</span>
                    </h2>
                  )}

                  {/* Description */}
                  {editingDesc ? (
                    <div className="flex items-start gap-2 mt-1">
                      <input
                        autoFocus
                        value={editDesc}
                        onChange={(e) => setEditDesc(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") saveDesc(); if (e.key === "Escape") { setEditingDesc(false); setEditDesc(selected.description || ""); } }}
                        placeholder="Add a description…"
                        className="flex-1 text-xs border border-violet-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-violet-300"
                      />
                      <button onClick={saveDesc} disabled={savingMeta} className="text-xs px-2 py-1 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50">Save</button>
                      <button onClick={() => setEditingDesc(false)} className="text-xs text-gray-500">×</button>
                    </div>
                  ) : (
                    <p
                      className="text-xs text-gray-400 mt-0.5 cursor-pointer hover:text-violet-600 transition-colors"
                      onClick={() => { setEditingDesc(true); setEditDesc(selected.description || ""); }}
                    >
                      {selected.description || <span className="italic">Add a description…</span>}
                    </p>
                  )}
                </div>

                {/* Status + actions */}
                <div className="flex items-center gap-2 shrink-0">
                  <select
                    value={selected.status || "active"}
                    onChange={(e) => saveStatus(e.target.value)}
                    className={`text-xs px-2 py-1 rounded-full font-medium border-0 focus:outline-none focus:ring-2 focus:ring-violet-300 cursor-pointer ${STATUS_COLORS[selected.status || "active"] ?? "bg-gray-100 text-gray-500"}`}
                  >
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>

                  {/* Export buttons */}
                  <a
                    href={projectBibtexUrl(selected.id)}
                    download
                    className="text-xs px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded-lg hover:border-violet-300 hover:text-violet-700 transition-colors font-medium"
                  >
                    ↓ BibTeX
                  </a>
                  <a
                    href={projectCsvUrl(selected.id)}
                    download
                    className="text-xs px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded-lg hover:border-violet-300 hover:text-violet-700 transition-colors font-medium"
                  >
                    ↓ CSV
                  </a>
                  <a
                    href={projectConversationsUrl(selected.id)}
                    download
                    className="text-xs px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded-lg hover:border-violet-300 hover:text-violet-700 transition-colors font-medium"
                  >
                    ↓ Chats
                  </a>

                  {/* View in library */}
                  <Link
                    to={`/?project_id=${selected.id}`}
                    className="text-xs px-3 py-1.5 bg-violet-50 text-violet-700 rounded-lg hover:bg-violet-100 transition-colors font-medium"
                  >
                    View in Library →
                  </Link>
                </div>
              </div>

              {/* Stat chips */}
              {stats && (
                <div className="flex items-center gap-3 mt-3 flex-wrap">
                  <span className="text-[11px] text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">{stats.papers} paper{stats.papers !== 1 ? "s" : ""}</span>
                  {stats.years.length > 0 && (
                    <span className="text-[11px] text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                      {stats.years[0]}{stats.years.length > 1 ? `–${stats.years[stats.years.length - 1]}` : ""}
                    </span>
                  )}
                  {stats.sources.map((s) => (
                    <span key={s} className="text-[11px] text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">{s}</span>
                  ))}
                </div>
              )}
            </div>

            {/* Tab bar */}
            <div className="bg-white border-b border-gray-100 px-8 flex items-center gap-1">
              {(["papers", "note", "keywords", "stats"] as DetailTab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setDetailTab(t)}
                  className={`px-4 py-2 text-xs font-medium border-b-2 -mb-px capitalize transition-colors ${
                    detailTab === t ? "border-violet-600 text-violet-600" : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {t === "papers" ? `Papers (${selected.papers.length})` : t === "note" ? "Notes" : t === "keywords" ? "Keywords" : "Stats"}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto">

              {/* ── Papers tab ── */}
              {detailTab === "papers" && (
                <div className="max-w-3xl mx-auto px-8 py-6 space-y-4">

                  {/* Add paper search */}
                  <div className="relative">
                    <input
                      value={paperQuery}
                      onChange={(e) => handlePaperSearch(e.target.value)}
                      placeholder="Search library to add a paper…"
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white pr-8"
                    />
                    {searching && (
                      <svg className="absolute right-3 top-2.5 animate-spin h-4 w-4 text-violet-400" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                      </svg>
                    )}
                    {paperResults.length > 0 && (
                      <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden max-h-64 overflow-y-auto">
                        {paperResults.map((p) => (
                          <button
                            key={p.id}
                            onClick={() => handleAddPaper(p.id)}
                            disabled={addingPaper === p.id}
                            className="w-full text-left px-4 py-2.5 text-sm hover:bg-violet-50 flex items-center justify-between gap-3 border-b border-gray-50 last:border-0"
                          >
                            <div className="min-w-0">
                              <p className="text-xs font-medium text-gray-800 truncate">{p.title}</p>
                              {p.year && <p className="text-[10px] text-gray-400">{p.year}</p>}
                            </div>
                            <span className="shrink-0 text-[10px] font-medium text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
                              {addingPaper === p.id ? "Adding…" : "+ Add"}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Paper list */}
                  {selected.papers.length === 0 ? (
                    <p className="text-sm text-gray-400 text-center py-10">No papers in this project yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {selected.papers.map((paper) => (
                        <div
                          key={paper.id}
                          className="bg-white border border-gray-200 rounded-lg px-4 py-3 flex items-start justify-between gap-3 hover:border-violet-200 transition-colors group"
                        >
                          <div className="min-w-0 flex-1">
                            <Link
                              to={`/paper/${paper.id}`}
                              className="text-sm font-medium text-gray-800 hover:text-violet-700 transition-colors leading-snug block"
                            >
                              {paper.title}
                            </Link>
                            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                              {paper.year && <span className="text-[11px] text-gray-400">{paper.year}</span>}
                              {paper.doi && <span className="text-[11px] text-gray-400 font-mono truncate max-w-[200px]">{paper.doi}</span>}
                              {(paper.authors ?? []).length > 0 && (
                                <span className="text-[11px] text-gray-400 truncate max-w-[200px]">
                                  {(paper.authors ?? []).slice(0, 3).join(", ")}{(paper.authors ?? []).length > 3 ? " …" : ""}
                                </span>
                              )}
                            </div>
                          </div>
                          <button
                            onClick={() => removePaper(paper.id)}
                            title="Remove from project"
                            className="shrink-0 text-gray-300 hover:text-red-500 transition-colors text-lg leading-none mt-0.5"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* ── Note tab ── */}
              {detailTab === "note" && (
                <div className="max-w-3xl mx-auto px-8 py-6">
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Project notes</p>
                    <span className="text-[10px] text-gray-400">
                      {savingNote ? "Saving…" : noteSaved ? "✓ Saved" : "Auto-saves as you type"}
                    </span>
                  </div>
                  <textarea
                    value={note}
                    onChange={(e) => handleNoteChange(e.target.value)}
                    placeholder="Write anything about this project — goals, context, open questions, links…"
                    className="w-full h-[calc(100vh-320px)] border border-gray-200 rounded-lg px-4 py-3 text-sm text-gray-700 leading-relaxed focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none bg-white"
                  />
                </div>
              )}

              {/* ── Keywords tab ── */}
              {detailTab === "keywords" && (
                <div className="max-w-3xl mx-auto px-8 py-6">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Literature search keywords</p>
                    <span className="text-[10px] text-gray-400">
                      {savingKw ? "Saving…" : kwSaved ? "✓ Saved" : "Auto-saves as you type"}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mb-3">
                    One keyword or phrase per line. Lines starting with <code className="bg-gray-100 px-1 rounded">#</code> are comments. Used instead of global keywords when this project is selected in Literature Search. Leave empty to fall back to global keywords.
                  </p>
                  <textarea
                    value={kwText}
                    onChange={(e) => handleKwChange(e.target.value)}
                    placeholder={"# Keywords for literature search\nprotein design\ndiffusion model\nantibody"}
                    className="w-full h-80 border border-gray-200 rounded-lg px-4 py-3 text-sm font-mono text-gray-700 leading-relaxed focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none bg-white"
                  />
                  <p className="text-[10px] text-gray-400 mt-2">
                    {kwText.split("\n").filter(l => l.trim() && !l.trim().startsWith("#")).length} active keyword(s)
                  </p>
                </div>
              )}

              {/* ── Stats tab ── */}
              {detailTab === "stats" && stats && (
                <div className="max-w-3xl mx-auto px-8 py-6 space-y-6">

                  {/* Overview numbers */}
                  <div className="grid grid-cols-3 gap-4">
                    {[
                      { label: "Papers", value: stats.papers },
                      { label: "Year range", value: stats.years.length > 1 ? `${stats.years[0]}–${stats.years[stats.years.length-1]}` : stats.years[0] ?? "—" },
                      { label: "With abstracts", value: selected.papers.filter((p) => p.abstract).length },
                    ].map(({ label, value }) => (
                      <div key={label} className="bg-white border border-gray-200 rounded-xl px-5 py-4 text-center">
                        <p className="text-2xl font-bold text-violet-700">{value}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{label}</p>
                      </div>
                    ))}
                  </div>

                  {/* Papers by year */}
                  {stats.years.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-xl px-5 py-4">
                      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Papers by year</p>
                      {(() => {
                        const byYear: Record<number, number> = {};
                        selected.papers.forEach((p) => { if (p.year) byYear[p.year] = (byYear[p.year] || 0) + 1; });
                        const max = Math.max(...Object.values(byYear));
                        return (
                          <div className="space-y-1.5">
                            {Object.entries(byYear).sort(([a], [b]) => Number(b) - Number(a)).map(([year, count]) => (
                              <div key={year} className="flex items-center gap-3">
                                <span className="text-xs text-gray-500 w-10 shrink-0">{year}</span>
                                <div className="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-violet-500 rounded-full transition-all"
                                    style={{ width: `${(count / max) * 100}%` }}
                                  />
                                </div>
                                <span className="text-xs text-gray-500 w-4 text-right">{count}</span>
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                  )}

                  {/* Metadata sources */}
                  {stats.sources.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-xl px-5 py-4">
                      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Metadata sources</p>
                      <div className="flex flex-wrap gap-2">
                        {stats.sources.map((s) => {
                          const count = selected.papers.filter((p) => p.metadata_source === s).length;
                          return (
                            <div key={s} className="flex items-center gap-1.5 bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5">
                              <span className="text-xs font-medium text-gray-700">{s}</span>
                              <span className="text-[10px] text-gray-400 bg-gray-200 px-1.5 py-0.5 rounded-full">{count}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Danger zone */}
                  <div className="border border-red-100 rounded-xl px-5 py-4">
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Danger zone</p>
                    {!confirmDelete ? (
                      <button
                        onClick={() => setConfirmDelete(true)}
                        className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                      >
                        Delete project…
                      </button>
                    ) : (
                      <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                        <p className="text-xs text-red-700 flex-1">
                          Delete "{selected.name}"? Papers are kept — only the project grouping is removed.
                        </p>
                        <button onClick={() => setConfirmDelete(false)} disabled={deleting} className="shrink-0 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-50">Cancel</button>
                        <button onClick={handleDelete} disabled={deleting} className="shrink-0 text-xs font-medium bg-red-600 text-white px-3 py-1.5 rounded-lg hover:bg-red-700 disabled:opacity-50">
                          {deleting ? "Deleting…" : "Delete"}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
