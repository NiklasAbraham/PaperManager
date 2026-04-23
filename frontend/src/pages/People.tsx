import { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { Person, Paper } from "../types";

// ── Types ────────────────────────────────────────────────────────────────────

interface PersonSummary extends Person {
  paper_count?: number;
}

interface PaperLink extends Paper {
  _rel_type: "AUTHORED_BY" | "INVOLVES";
  _role: string | null;
}

interface PersonDetail extends Person {
  papers: PaperLink[];
  specialties: { id: string; name: string }[];
}

// Role options — maps UI label → rel type + role string used in Neo4j
const ROLES = [
  { label: "Author",      rel: "authored",    display: "Authored" },
  { label: "Recommended", rel: "recommended",  display: "Recommended" },
  { label: "Has read",    rel: "read",         display: "Has Read" },
  { label: "Working on",  rel: "working_on",   display: "Working On" },
] as const;

type RoleKey = typeof ROLES[number]["rel"];

const ROLE_COLORS: Record<string, string> = {
  authored:    "bg-violet-100 text-violet-700",
  recommended: "bg-amber-100 text-amber-700",
  read:        "bg-green-100 text-green-700",
  working_on:  "bg-blue-100 text-blue-700",
};

function relKey(link: PaperLink): RoleKey {
  if (link._rel_type === "AUTHORED_BY") return "authored";
  return (link._role ?? "working_on") as RoleKey;
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function People() {
  const [people, setPeople]       = useState<PersonSummary[]>([]);
  const [selected, setSelected]   = useState<PersonDetail | null>(null);
  const [loading, setLoading]     = useState(false);
  const [adding, setAdding]       = useState(false);
  const [newName, setNewName]     = useState("");
  const [newAffil, setNewAffil]   = useState("");
  const [saving, setSaving]       = useState(false);

  const [searchParams] = useSearchParams();

  useEffect(() => {
    const targetId = searchParams.get("id");
    apiFetch<PersonSummary[]>("/people").then((list) => {
      setPeople(list);
      if (targetId) {
        const target = list.find((p) => p.id === targetId);
        if (target) selectPerson(target);
      }
    }).catch(() => {});
  }, []);

  const selectPerson = async (p: PersonSummary) => {
    setLoading(true);
    try {
      const detail = await apiFetch<PersonDetail>(`/people/${p.id}`);
      setSelected(detail);
    } finally {
      setLoading(false);
    }
  };

  const createPerson = async () => {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const person = await apiFetch<PersonSummary>("/people", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), affiliation: newAffil.trim() || null }),
      });
      const list = await apiFetch<PersonSummary[]>("/people");
      setPeople(list);
      setNewName("");
      setNewAffil("");
      setAdding(false);
      selectPerson(person);
    } finally {
      setSaving(false);
    }
  };

  const refreshSelected = async () => {
    if (!selected) return;
    const [detail, list] = await Promise.all([
      apiFetch<PersonDetail>(`/people/${selected.id}`),
      apiFetch<PersonSummary[]>("/people"),
    ]);
    setSelected(detail);
    setPeople(list);
  };

  return (
    <div className="flex h-[calc(100vh-53px)]">
      {/* ── Left: people list ── */}
      <aside className="w-60 shrink-0 bg-white border-r border-gray-200 overflow-y-auto">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h1 className="text-sm font-semibold text-gray-900">People</h1>
          <button
            onClick={() => { setAdding((v) => !v); setNewName(""); setNewAffil(""); }}
            className="text-xs font-medium text-violet-600 hover:text-violet-800 transition-colors"
          >
            {adding ? "Cancel" : "+ New"}
          </button>
        </div>

        {adding && (
          <div className="px-4 py-3 border-b border-gray-100 space-y-2 bg-violet-50">
            <input
              autoFocus
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createPerson()}
              placeholder="Full name"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
            />
            <input
              type="text"
              value={newAffil}
              onChange={(e) => setNewAffil(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createPerson()}
              placeholder="Affiliation (optional)"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
            />
            <button
              onClick={createPerson}
              disabled={!newName.trim() || saving}
              className="w-full py-1.5 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-40 transition-colors"
            >
              {saving ? "Adding…" : "Add person"}
            </button>
          </div>
        )}

        {people.length === 0 ? (
          <p className="p-4 text-xs text-gray-400">
            No people yet — add one above or ingest a paper.
          </p>
        ) : (
          <ul className="divide-y divide-gray-50">
            {people.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => selectPerson(p)}
                  className={`w-full text-left px-4 py-3 transition-colors hover:bg-violet-50 ${
                    selected?.id === p.id ? "bg-violet-50 border-l-2 border-violet-600" : ""
                  }`}
                >
                  <p className="text-sm font-medium text-gray-900 truncate">{p.name}</p>
                  {p.affiliation && (
                    <p className="text-xs text-gray-400 truncate">{p.affiliation}</p>
                  )}
                  {(p.paper_count ?? 0) > 0 && (
                    <p className="text-xs text-gray-300 mt-0.5">{p.paper_count} papers</p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* ── Right: person detail ── */}
      <main className="flex-1 overflow-y-auto bg-gray-50">
        {loading && (
          <div className="flex items-center justify-center h-full text-sm text-gray-400">
            Loading…
          </div>
        )}

        {!loading && !selected && (
          <div className="flex items-center justify-center h-full text-sm text-gray-400">
            Select a person to see their paper connections.
          </div>
        )}

        {!loading && selected && (
          <PersonDetailPanel
            person={selected}
            onChanged={refreshSelected}
          />
        )}
      </main>
    </div>
  );
}

// ── Person detail panel ──────────────────────────────────────────────────────

function PersonDetailPanel({ person, onChanged }: {
  person: PersonDetail;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [editName, setEditName]   = useState(person.name);
  const [editAffil, setEditAffil] = useState(person.affiliation ?? "");
  const [saving, setSaving]       = useState(false);
  const [editing, setEditing]     = useState(false);

  // Keep local state in sync when person prop changes (e.g. after refresh)
  useEffect(() => {
    setEditName(person.name);
    setEditAffil(person.affiliation ?? "");
    setEditing(false);
  }, [person.id]);

  const handleSave = async () => {
    if (!editName.trim()) return;
    setSaving(true);
    try {
      await apiFetch(`/people/${person.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName.trim(), affiliation: editAffil.trim() || null }),
      });
      setEditing(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setEditName(person.name);
    setEditAffil(person.affiliation ?? "");
    setEditing(false);
  };

  // Group papers by role
  const grouped = ROLES.map((r) => ({
    ...r,
    papers: person.papers.filter((p) => relKey(p) === r.rel),
  }));

  const handleUnlink = async (paper: PaperLink) => {
    const key = relKey(paper);
    if (key === "authored") {
      await apiFetch(`/papers/${paper.id}/authors/${person.id}`, { method: "DELETE" });
    } else {
      await apiFetch(`/papers/${paper.id}/involves/${person.id}?role=${key}`, { method: "DELETE" });
    }
    onChanged();
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="space-y-2">
              <input
                autoFocus
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSave(); if (e.key === "Escape") handleCancel(); }}
                className="w-full text-xl font-bold text-gray-900 border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-300"
              />
              <input
                value={editAffil}
                onChange={(e) => setEditAffil(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSave(); if (e.key === "Escape") handleCancel(); }}
                placeholder="Affiliation (optional)"
                className="w-full text-sm text-gray-500 border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-300"
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSave}
                  disabled={saving || !editName.trim()}
                  className="px-3 py-1 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={handleCancel}
                  className="px-3 py-1 text-xs font-medium bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-bold text-gray-900">{person.name}</h2>
              {person.affiliation && (
                <p className="text-sm text-gray-500 mt-0.5">{person.affiliation}</p>
              )}
            </>
          )}
          {person.specialties.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {person.specialties.map((t) => (
                <span key={t.id} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                  {t.name}
                </span>
              ))}
            </div>
          )}
        </div>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="shrink-0 text-xs text-gray-400 hover:text-violet-600 transition-colors mt-1"
          >
            Edit
          </button>
        )}
      </div>

      {/* Add connection */}
      <AddPaperLink personId={person.id} existingPapers={person.papers} onAdded={onChanged} />

      {/* Papers by role */}
      {grouped.map(({ rel, display, papers }) => (
        <section key={rel}>
          <div className="flex items-center gap-2 mb-3">
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${ROLE_COLORS[rel]}`}>
              {display}
            </span>
            <span className="text-xs text-gray-400">{papers.length} paper{papers.length !== 1 ? "s" : ""}</span>
          </div>

          {papers.length === 0 ? (
            <p className="text-xs text-gray-300 pl-1">None yet.</p>
          ) : (
            <ul className="space-y-2">
              {papers.map((paper) => (
                <li key={`${paper.id}-${rel}`}
                  className="flex items-start justify-between gap-3 bg-white border border-gray-100 rounded-lg px-4 py-3 group"
                >
                  <div className="flex-1 min-w-0">
                    <button
                      onClick={() => navigate(`/paper/${paper.id}`)}
                      className="text-sm font-medium text-gray-800 hover:text-violet-700 text-left truncate block w-full"
                    >
                      {paper.title}
                    </button>
                    {paper.year && (
                      <p className="text-xs text-gray-400 mt-0.5">{paper.year}</p>
                    )}
                  </div>
                  <button
                    onClick={() => handleUnlink(paper)}
                    title="Remove connection"
                    className="shrink-0 opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition-all text-lg leading-none"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

// ── Add paper link widget ─────────────────────────────────────────────────────

function AddPaperLink({ personId, existingPapers, onAdded }: {
  personId: string;
  existingPapers: PaperLink[];
  onAdded: () => void;
}) {
  const [query, setQuery]       = useState("");
  const [results, setResults]   = useState<Paper[]>([]);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [role, setRole]         = useState<RoleKey>("recommended");
  const [saving, setSaving]     = useState(false);
  const [open, setOpen]         = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = (q: string) => {
    setQuery(q);
    setSelected(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) { setResults([]); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await apiFetch<{ results: Paper[] }>(`/search?q=${encodeURIComponent(q)}`);
        setResults(res.results.slice(0, 8));
      } catch {
        setResults([]);
      }
    }, 300);
  };

  const pickPaper = (p: Paper) => {
    setSelected(p);
    setQuery(p.title);
    setResults([]);
  };

  const handleAdd = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      if (role === "authored") {
        await apiFetch(`/papers/${selected.id}/authors`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ person_id: personId }),
        });
      } else {
        await apiFetch(`/papers/${selected.id}/involves`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ person_id: personId, role }),
        });
      }
      setQuery("");
      setSelected(null);
      setResults([]);
      onAdded();
    } finally {
      setSaving(false);
    }
  };

  const existingIds = new Set(existingPapers.map((p) => p.id));

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 w-full text-left"
      >
        <span className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Add paper connection</span>
        <span className="ml-auto text-gray-400 text-sm">{open ? "▾" : "▴"}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          {/* Role selector */}
          <div className="flex gap-1.5 flex-wrap">
            {ROLES.map((r) => (
              <button
                key={r.rel}
                onClick={() => setRole(r.rel)}
                className={`px-3 py-1 text-xs rounded-full font-medium transition-colors border ${
                  role === r.rel
                    ? ROLE_COLORS[r.rel] + " border-transparent"
                    : "border-gray-200 text-gray-500 hover:bg-gray-50"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>

          {/* Paper search */}
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={(e) => search(e.target.value)}
              placeholder="Search for a paper…"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            {results.length > 0 && (
              <ul className="absolute z-20 top-full mt-1 left-0 right-0 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden max-h-56 overflow-y-auto">
                {results.map((p) => {
                  const already = existingIds.has(p.id);
                  return (
                    <li key={p.id}>
                      <button
                        disabled={already}
                        onClick={() => pickPaper(p)}
                        className={`w-full text-left px-3 py-2 text-sm hover:bg-violet-50 transition-colors ${already ? "opacity-40 cursor-not-allowed" : ""}`}
                      >
                        <span className="font-medium text-gray-800 truncate block">{p.title}</span>
                        {p.year && <span className="text-xs text-gray-400">{p.year}</span>}
                        {already && <span className="text-xs text-gray-400 ml-2">already linked</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <button
            onClick={handleAdd}
            disabled={!selected || saving}
            className="px-4 py-1.5 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-40 transition-colors"
          >
            {saving ? "Saving…" : "Add connection"}
          </button>
        </div>
      )}
    </div>
  );
}
