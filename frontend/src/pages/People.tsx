import { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  apiFetch, setPersonTracked,
  enrichPerson, enrichAllPeople,
  addPersonTag, removePersonTag,
  getPersonNote, savePersonNote,
} from "../api/client";
import type { Person, Paper, Tag, Note, StartupRole } from "../types";
import NoteEditor from "../components/NoteEditor";

// ── Tag groups for the Q&A-style Tags tab ─────────────────────────────────────

const TAG_GROUPS = [
  {
    question: "Do you know this person personally?",
    tags: ["known-personally"],
  },
  {
    question: "Where did you meet?",
    tags: ["met-at-conference", "colleague", "collaborator", "contact", "friend"],
  },
  {
    question: "What is their role?",
    tags: ["professor", "phd-student", "postdoc", "student", "tech-lead", "co-founder", "advisor", "mentor", "recruiter", "investor", "hiring-manager", "industry", "academia"],
  },
  {
    question: "What is your relationship / next action?",
    tags: ["strong-reference", "potential-hire", "follow-up"],
  },
];

// ── Inline-editable field ─────────────────────────────────────────────────────

function InlineField({
  label, value, placeholder, href, onSave, multiline,
}: {
  label: string;
  value?: string | null;
  placeholder: string;
  href?: string;      // if set and value exists, renders as a link
  onSave: (v: string) => Promise<void>;
  multiline?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState(value ?? "");
  const [saving, setSaving]   = useState(false);

  // sync when parent value changes (e.g. after enrichment)
  useEffect(() => { if (!editing) setDraft(value ?? ""); }, [value]);

  const commit = async () => {
    setSaving(true);
    try {
      await onSave(draft.trim());
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  const startEdit = () => { setDraft(value ?? ""); setEditing(true); };

  if (editing) {
    return (
      <div className="flex items-start gap-2 py-1.5 border-b border-gray-100">
        <span className="w-24 shrink-0 text-xs text-gray-400 pt-1.5">{label}</span>
        <div className="flex-1 flex gap-1">
          {multiline ? (
            <textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-300 resize-none"
            />
          ) : (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
              onBlur={commit}
              className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-300"
            />
          )}
          {multiline && (
            <button onClick={commit} disabled={saving}
              className="text-xs text-violet-600 hover:text-violet-800 self-end pb-0.5">
              {saving ? "…" : "Save"}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={startEdit}
      className="flex items-center gap-2 py-1.5 border-b border-gray-100 cursor-text hover:bg-gray-50 rounded group"
    >
      <span className="w-24 shrink-0 text-xs text-gray-400">{label}</span>
      {value ? (
        href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="flex-1 text-sm text-violet-700 hover:underline truncate"
          >
            {value}
          </a>
        ) : (
          <span className="flex-1 text-sm text-gray-800 truncate">{value}</span>
        )
      ) : (
        <span className="flex-1 text-sm text-gray-300 italic">{placeholder}</span>
      )}
      <span className="opacity-0 group-hover:opacity-60 text-gray-400 text-xs pr-1">edit</span>
    </div>
  );
}

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
  tags: Tag[];
  note: Note | null;
}

// Role options — maps UI label → rel type + role string used in Neo4j
const ROLES = [
  { label: "Author",           rel: "authored",         display: "Authored" },
  { label: "Shared by",        rel: "shared_by",        display: "Shared By" },
  { label: "Recommended",      rel: "recommended",      display: "Recommended" },
  { label: "Has read",         rel: "read",             display: "Has Read" },
  { label: "Working on",       rel: "working_on",       display: "Working On" },
  { label: "Collaborating",    rel: "collaborating",    display: "Collaborating" },
  { label: "Supervisor",       rel: "supervisor",       display: "Supervisor" },
  { label: "Feedback needed",  rel: "feedback_needed",  display: "Feedback Needed" },
] as const;

type RoleKey = typeof ROLES[number]["rel"];

const ROLE_COLORS: Record<string, string> = {
  authored:        "bg-violet-100 text-violet-700",
  shared_by:       "bg-orange-100 text-orange-700",
  recommended:     "bg-amber-100 text-amber-700",
  read:            "bg-green-100 text-green-700",
  working_on:      "bg-blue-100 text-blue-700",
  collaborating:   "bg-teal-100 text-teal-700",
  supervisor:      "bg-purple-100 text-purple-700",
  feedback_needed: "bg-red-100 text-red-600",
};

function relKey(link: PaperLink): RoleKey {
  if (link._rel_type === "AUTHORED_BY") return "authored";
  // Fall back to "working_on" only if role is not a known key
  const role = link._role ?? "working_on";
  return ROLES.some((r) => r.rel === role) ? (role as RoleKey) : "working_on";
}

// ── Main page ────────────────────────────────────────────────────────────────

type PeopleFilter = "all" | "known" | "authors";

export default function People() {
  const [people, setPeople]       = useState<PersonSummary[]>([]);
  const [selected, setSelected]   = useState<PersonDetail | null>(null);
  const [loading, setLoading]     = useState(false);
  const [adding, setAdding]       = useState(false);
  const [newName, setNewName]     = useState("");
  const [newAffil, setNewAffil]   = useState("");
  const [saving, setSaving]       = useState(false);
  const [enrichingAll, setEnrichingAll] = useState(false);
  const [enrichAllMsg, setEnrichAllMsg] = useState("");
  const [filter, setFilter]       = useState<PeopleFilter>("all");
  const [search, setSearch]       = useState("");

  const [searchParams] = useSearchParams();

  const fetchPeople = async (f: PeopleFilter = filter) => {
    let url = "/people";
    if (f === "known") url = "/people?tag=known-personally";
    else if (f === "authors") url = "/people?exclude_tag=known-personally";
    return apiFetch<PersonSummary[]>(url);
  };

  useEffect(() => {
    const targetId = searchParams.get("id");
    fetchPeople("all").then((list) => {
      setPeople(list);
      if (targetId) {
        const target = list.find((p) => p.id === targetId);
        if (target) selectPerson(target);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    fetchPeople(filter).then(setPeople).catch(() => {});
  }, [filter]);

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
      fetchPeople(),
    ]);
    setSelected(detail);
    setPeople(list);
  };

  const handleEnrichAll = async () => {
    setEnrichingAll(true);
    setEnrichAllMsg("");
    try {
      const res = await enrichAllPeople();
      setEnrichAllMsg(`Enrichment started for ${res.total_people} people`);
      setTimeout(() => setEnrichAllMsg(""), 4000);
    } catch {
      setEnrichAllMsg("Failed to start enrichment");
      setTimeout(() => setEnrichAllMsg(""), 3000);
    } finally {
      setEnrichingAll(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-53px)]">
      {/* ── Left: people list ── */}
      <aside className="w-60 shrink-0 bg-white border-r border-gray-200 overflow-y-auto">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-2">
          <h1 className="text-sm font-semibold text-gray-900">People</h1>
          <div className="flex items-center gap-2">
            <button
              onClick={handleEnrichAll}
              disabled={enrichingAll}
              title="Re-check ORCID/Scholar profiles for all people"
              className="text-xs text-gray-400 hover:text-violet-600 transition-colors disabled:opacity-40"
            >
              {enrichingAll ? "…" : "↻ All"}
            </button>
            <button
              onClick={() => { setAdding((v) => !v); setNewName(""); setNewAffil(""); }}
              className="text-xs font-medium text-violet-600 hover:text-violet-800 transition-colors"
            >
              {adding ? "Cancel" : "+ New"}
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="px-3 py-2 border-b border-gray-100">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search people…"
            className="w-full text-xs border border-gray-200 rounded-md px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
          />
        </div>

        {/* Filter toggle */}
        <div className="px-3 py-2 border-b border-gray-100 flex gap-1">
          {(["all", "known", "authors"] as PeopleFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`flex-1 text-xs py-1 rounded-md font-medium transition-colors ${
                filter === f
                  ? "bg-violet-600 text-white"
                  : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
              }`}
            >
              {f === "all" ? "All" : f === "known" ? "Known" : "Authors"}
            </button>
          ))}
        </div>

        {enrichAllMsg && (
          <div className="px-4 py-2 text-xs text-violet-700 bg-violet-50 border-b border-violet-100">
            {enrichAllMsg}
          </div>
        )}

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
            {people.filter((p) => !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.affiliation?.toLowerCase().includes(search.toLowerCase())).map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => selectPerson(p)}
                  className={`w-full text-left px-4 py-3 transition-colors hover:bg-violet-50 ${
                    selected?.id === p.id ? "bg-violet-50 border-l-2 border-violet-600" : ""
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm font-medium text-gray-900 truncate">{p.name}</p>
                  </div>
                  {p.affiliation && (
                    <p className="text-xs text-gray-400 truncate">{p.affiliation}</p>
                  )}
                  {p.citation_count != null && (
                    <p className="text-xs text-gray-300 mt-0.5">{p.citation_count.toLocaleString()} citations</p>
                  )}
                  {p.citation_count == null && (p.paper_count ?? 0) > 0 && (
                    <p className="text-xs text-gray-300 mt-0.5">{p.paper_count} papers</p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* ── Right: person detail ── */}
      <main className="flex-1 overflow-hidden bg-gray-50 flex flex-col">
        {loading && (
          <div className="flex items-center justify-center h-full text-sm text-gray-400">
            Loading…
          </div>
        )}

        {!loading && !selected && (
          <div className="flex items-center justify-center h-full text-sm text-gray-400">
            Select a person to see their profile.
          </div>
        )}

        {!loading && selected && (
          <PersonDetailPanel
            key={selected.id}
            person={selected}
            onChanged={refreshSelected}
          />
        )}
      </main>
    </div>
  );
}

// ── Person detail panel ──────────────────────────────────────────────────────

type DetailTab = "overview" | "notes" | "tags";

function PersonDetailPanel({ person, onChanged }: {
  person: PersonDetail;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<DetailTab>("overview");
  const [profileOpen, setProfileOpen] = useState(false);

  // Edit state (only used for name + startup roles which need a modal-style form)
  const [editingName, setEditingName] = useState(false);
  const [editName, setEditName]       = useState(person.name);
  const [saving, setSaving]           = useState(false);
  const [editingRoles, setEditingRoles] = useState(false);
  const [editRoles, setEditRoles]     = useState<StartupRole[]>(
    () => tryParseRoles(person.startup_roles)
  );

  // Enrichment
  const [enriching, setEnriching]     = useState(false);
  const [enrichMsg, setEnrichMsg]     = useState("");

  // Tracking
  const [trackUpdating, setTrackUpdating] = useState(false);

  // Tags
  const [tags, setTags]           = useState<Tag[]>(person.tags ?? []);
  const [allTags, setAllTags]     = useState<Tag[]>([]);
  const [newTag, setNewTag]       = useState("");
  const [tagSaving, setTagSaving] = useState(false);

  useEffect(() => {
    setEditName(person.name);
    setEditRoles(tryParseRoles(person.startup_roles));
    setEditingName(false);
    setEditingRoles(false);
    setTags(person.tags ?? []);
  }, [person.id]);

  // Load all available tags when the tags tab is first opened
  useEffect(() => {
    if (tab === "tags" && allTags.length === 0) {
      apiFetch<Tag[]>("/tags").then(setAllTags).catch(() => {});
    }
  }, [tab]);

  /** Save a single field via PATCH; refreshes the detail panel when done. */
  const saveField = async (field: string, value: string | null) => {
    await apiFetch(`/people/${person.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value || null }),
    });
    onChanged();
  };

  const saveSkills = async (csv: string) => {
    const skillsJson = JSON.stringify(csv.split(",").map((s) => s.trim()).filter(Boolean));
    await saveField("skills", skillsJson);
  };

  const handleSaveName = async () => {
    if (!editName.trim()) return;
    setSaving(true);
    try { await saveField("name", editName.trim()); } finally { setSaving(false); setEditingName(false); }
  };

  const handleSaveRoles = async () => {
    setSaving(true);
    try {
      await saveField("startup_roles", JSON.stringify(editRoles));
      setEditingRoles(false);
    } finally { setSaving(false); }
  };

  const toggleTrack = async () => {
    setTrackUpdating(true);
    try {
      await setPersonTracked(person.id, !person.tracked);
      onChanged();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to update tracking");
    } finally {
      setTrackUpdating(false);
    }
  };

  const handleEnrich = async () => {
    setEnriching(true);
    setEnrichMsg("");
    try {
      const res = await enrichPerson(person.id);
      if (res.enriched) {
        setEnrichMsg("Profile updated");
        onChanged();
      } else {
        setEnrichMsg(res.message ?? "No new data");
      }
      setTimeout(() => setEnrichMsg(""), 3000);
    } catch {
      setEnrichMsg("Enrichment failed");
      setTimeout(() => setEnrichMsg(""), 3000);
    } finally {
      setEnriching(false);
    }
  };

  const handleAddTag = async () => {
    const name = newTag.trim();
    if (!name) return;
    setTagSaving(true);
    try {
      await addPersonTag(person.id, name);
      setTags(await apiFetch<Tag[]>(`/people/${person.id}/tags`));
      setNewTag("");
    } finally {
      setTagSaving(false);
    }
  };

  const handleRemoveTag = async (tagName: string) => {
    await removePersonTag(person.id, tagName);
    setTags((prev) => prev.filter((t) => t.name !== tagName));
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

  const skills = tryParseSkills(person.skills);
  const roles  = tryParseRoles(person.startup_roles);

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-4 bg-white border-b border-gray-100 shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            {/* Name — inline editable */}
            {editingName ? (
              <div className="flex items-center gap-2 mb-1">
                <input
                  autoFocus
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleSaveName(); if (e.key === "Escape") setEditingName(false); }}
                  onBlur={handleSaveName}
                  className="text-xl font-bold text-gray-900 border border-violet-300 rounded-lg px-3 py-1 focus:outline-none focus:ring-2 focus:ring-violet-300"
                />
              </div>
            ) : (
              <h2
                onClick={() => { setEditName(person.name); setEditingName(true); }}
                className="text-xl font-bold text-gray-900 cursor-text hover:text-violet-800 transition-colors inline-block"
                title="Click to edit name"
              >
                {person.name}
              </h2>
            )}

            {/* Citation count badge */}
            {person.citation_count != null && (
              <span className="ml-2 text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-mono">
                {person.citation_count.toLocaleString()} citations
              </span>
            )}

            {/* Topic specialties */}
            {person.specialties.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {person.specialties.map((t) => (
                  <span key={t.id} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                    {t.name}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0 mt-1">
            <button
              onClick={handleEnrich}
              disabled={enriching}
              title="Re-fetch ORCID / Scholar / S2 profile data"
              className="text-xs text-gray-400 hover:text-violet-600 transition-colors disabled:opacity-40 px-2 py-1 rounded border border-gray-200 hover:border-violet-300"
            >
              {enriching ? "…" : "↻ Enrich"}
            </button>
            <button
              onClick={toggleTrack}
              disabled={trackUpdating}
              title={person.tracked ? "Untrack this author" : "Track this author for auto-import"}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-50 ${
                person.tracked
                  ? "bg-amber-100 text-amber-700 hover:bg-amber-200"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                <path fillRule="evenodd" d="M10.868 2.884c-.321-.772-1.415-.772-1.736 0l-1.83 4.401-4.753.381c-.833.067-1.171 1.107-.536 1.651l3.62 3.102-1.106 4.637c-.194.813.691 1.456 1.405 1.02L10 15.591l4.069 2.485c.713.436 1.598-.207 1.404-1.02l-1.106-4.637 3.62-3.102c.635-.544.297-1.584-.536-1.65l-4.752-.382-1.831-4.401Z" clipRule="evenodd" />
              </svg>
              {person.tracked ? "Tracked" : "Track"}
            </button>
          </div>
        </div>

        {/* ── Inline profile fields (collapsible) ── */}
        <div className="mt-3">
          <button
            onClick={() => setProfileOpen((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors mb-1 select-none"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"
              className={`w-3.5 h-3.5 transition-transform ${profileOpen ? "rotate-90" : ""}`}
            >
              <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
            </svg>
            Profile details
            {!profileOpen && (person.affiliation || person.email || person.bio) && (
              <span className="text-gray-300 truncate max-w-xs">
                — {person.affiliation || person.email || person.bio}
              </span>
            )}
          </button>
          {profileOpen && (
            <div className="space-y-0">
              <InlineField label="Affiliation" value={person.affiliation} placeholder="Add affiliation…"
                onSave={(v) => saveField("affiliation", v)} />
              <InlineField label="Email" value={person.email} placeholder="Add email…"
                onSave={(v) => saveField("email", v)} />
              <InlineField label="Phone" value={person.phone} placeholder="Add phone…"
                onSave={(v) => saveField("phone", v)} />
              <InlineField label="LinkedIn" value={person.linkedin_url} placeholder="Add LinkedIn URL…"
                href={person.linkedin_url ?? undefined}
                onSave={(v) => saveField("linkedin_url", v)} />
              <InlineField label="ORCID" value={person.orcid_url} placeholder="Add ORCID URL…"
                href={person.orcid_url ?? undefined}
                onSave={(v) => saveField("orcid_url", v)} />
              <InlineField label="Scholar" value={person.scholar_url} placeholder="Add Google Scholar URL…"
                href={person.scholar_url ?? undefined}
                onSave={(v) => saveField("scholar_url", v)} />
              <InlineField label="Website" value={person.website_url} placeholder="Add website URL…"
                href={person.website_url ?? undefined}
                onSave={(v) => saveField("website_url", v)} />
              <InlineField label="Bio" value={person.bio} placeholder="Add bio / description…"
                onSave={(v) => saveField("bio", v)} multiline />
              <InlineField label="Skills" value={tryParseSkills(person.skills).join(", ") || null}
                placeholder="Add skills (comma-separated)…"
                onSave={saveSkills} />
            </div>
          )}
        </div>

        {enrichMsg && (
          <p className="mt-2 text-xs text-violet-600">{enrichMsg}</p>
        )}

        {/* Tab bar */}
        <div className="flex gap-4 mt-4">
          {(["overview", "notes", "tags"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`pb-1.5 text-sm font-medium border-b-2 transition-colors capitalize ${
                tab === t
                  ? "border-violet-600 text-violet-700"
                  : "border-transparent text-gray-400 hover:text-gray-600"
              }`}
            >
              {t}
              {t === "tags" && tags.length > 0 && (
                <span className="ml-1 text-xs text-gray-400">({tags.length})</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab content ── */}
      <div className="flex-1 overflow-y-auto">
        {/* OVERVIEW */}
        {tab === "overview" && (
          <div className="max-w-2xl mx-auto px-6 py-6 space-y-8">
            {/* Skills */}
            {skills.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Skills</h3>
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((s) => (
                    <span key={s} className="text-xs bg-violet-50 text-violet-700 px-2.5 py-0.5 rounded-full border border-violet-100">
                      {s}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* Startup / company roles */}
            <section>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Startup / Company Roles</h3>
                <button onClick={() => { setEditRoles(tryParseRoles(person.startup_roles)); setEditingRoles((v) => !v); }}
                  className="text-xs text-violet-500 hover:text-violet-700 transition-colors">
                  {editingRoles ? "Cancel" : roles.length > 0 ? "Edit" : "+ Add"}
                </button>
              </div>

              {editingRoles ? (
                <div className="space-y-2 bg-gray-50 rounded-lg p-3">
                  {editRoles.map((r, i) => (
                    <div key={i} className="flex gap-2 items-center">
                      <input value={r.name}
                        onChange={(e) => setEditRoles((prev) => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                        placeholder="Company name"
                        className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-300 bg-white" />
                      <input value={r.role}
                        onChange={(e) => setEditRoles((prev) => prev.map((x, j) => j === i ? { ...x, role: e.target.value } : x))}
                        placeholder="Role (e.g. CTO)"
                        className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-300 bg-white" />
                      <label className="flex items-center gap-1 text-xs text-gray-500 cursor-pointer whitespace-nowrap">
                        <input type="checkbox" checked={r.active}
                          onChange={(e) => setEditRoles((prev) => prev.map((x, j) => j === i ? { ...x, active: e.target.checked } : x))}
                          className="rounded" />
                        Active
                      </label>
                      <button onClick={() => setEditRoles((prev) => prev.filter((_, j) => j !== i))}
                        className="text-gray-300 hover:text-red-500 text-base leading-none">×</button>
                    </div>
                  ))}
                  <div className="flex gap-2 mt-1">
                    <button onClick={() => setEditRoles((prev) => [...prev, { name: "", role: "", active: true }])}
                      className="text-xs text-violet-600 hover:text-violet-800 transition-colors">+ Add row</button>
                    <button onClick={handleSaveRoles} disabled={saving}
                      className="text-xs bg-violet-600 text-white px-2.5 py-1 rounded hover:bg-violet-700 disabled:opacity-50 transition-colors ml-auto">
                      {saving ? "Saving…" : "Save"}
                    </button>
                  </div>
                </div>
              ) : roles.length > 0 ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-400 border-b border-gray-100">
                      <th className="text-left pb-1 font-normal">Company</th>
                      <th className="text-left pb-1 font-normal">Role</th>
                      <th className="text-left pb-1 font-normal">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roles.map((r, i) => (
                      <tr key={i} className="border-b border-gray-50">
                        <td className="py-1.5 pr-4 font-medium text-gray-800">{r.name}</td>
                        <td className="py-1.5 pr-4 text-gray-600">{r.role}</td>
                        <td className="py-1.5">
                          <span className={`text-xs px-1.5 py-0.5 rounded-full ${r.active ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-400"}`}>
                            {r.active ? "Active" : "Past"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-gray-300">No roles added yet.</p>
              )}
            </section>

            {/* Add connection */}
            <AddPaperLink personId={person.id} existingPapers={person.papers} onAdded={onChanged} />

            {/* Papers by role — only show groups that have papers */}
            {grouped.filter((g) => g.papers.length > 0).length === 0 && (
              <p className="text-xs text-gray-400 italic pl-1">No papers linked yet.</p>
            )}
            {grouped.filter((g) => g.papers.length > 0).map(({ rel, display, papers }) => (
              <section key={rel}>
                <div className="flex items-center gap-2 mb-3">
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${ROLE_COLORS[rel]}`}>
                    {display}
                  </span>
                  <span className="text-xs text-gray-400">{papers.length} paper{papers.length !== 1 ? "s" : ""}</span>
                </div>

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
              </section>
            ))}
          </div>
        )}

        {/* NOTES */}
        {tab === "notes" && (
          <div className="h-full p-4">
            <NoteEditor
              fetchNote={() => getPersonNote(person.id)}
              saveNote={(content) => savePersonNote(person.id, content)}
              compact
            />
          </div>
        )}

        {/* TAGS */}
        {tab === "tags" && (
          <div className="max-w-xl mx-auto px-6 py-6 space-y-6">
            {TAG_GROUPS.map((group) => (
                <div key={group.question}>
                  <p className="text-sm font-medium text-gray-600 mb-2">{group.question}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {group.tags.map((tagName) => {
                      const applied = tags.some((t) => t.name === tagName);
                      return (
                        <button
                          key={tagName}
                          disabled={tagSaving}
                          onClick={async () => {
                            setTagSaving(true);
                            try {
                              if (applied) {
                                await handleRemoveTag(tagName);
                              } else {
                                const t = allTags.find((x) => x.name === tagName) ?? { id: tagName, name: tagName };
                                await addPersonTag(person.id, tagName);
                                setTags((prev) => [...prev.filter((x) => x.name !== tagName), t]);
                              }
                            } finally { setTagSaving(false); }
                          }}
                          className={`text-xs px-3 py-1 rounded-full border transition-colors disabled:opacity-40 ${
                            applied
                              ? "bg-violet-600 text-white border-violet-600 hover:bg-violet-700"
                              : "bg-white text-gray-600 border-gray-200 hover:border-violet-400 hover:text-violet-700 hover:bg-violet-50"
                          }`}
                        >
                          {applied ? "✓ " : ""}{tagName}
                        </button>
                      );
                    })}
                  </div>
                </div>
            ))}

            {/* Other tags (not in any group) */}
            {(() => {
              const groupedTagNames = new Set(TAG_GROUPS.flatMap((g) => g.tags));
              const otherApplied = tags.filter((t) => !groupedTagNames.has(t.name));
              const otherAvailable = allTags.filter((t) => !groupedTagNames.has(t.name) && !tags.some((a) => a.name === t.name));
              if (otherApplied.length === 0 && otherAvailable.length === 0) return null;
              return (
                <div>
                  <p className="text-sm font-medium text-gray-600 mb-2">Other tags</p>
                  <div className="flex flex-wrap gap-1.5">
                    {otherApplied.map((t) => (
                      <span key={t.id} className="flex items-center gap-1 text-xs bg-violet-100 text-violet-800 border border-violet-200 px-2.5 py-1 rounded-full font-medium">
                        {t.name}
                        <button onClick={() => handleRemoveTag(t.name)}
                          className="text-violet-400 hover:text-red-500 leading-none transition-colors ml-0.5" title="Remove">×</button>
                      </span>
                    ))}
                    {otherAvailable.map((t) => (
                      <button key={t.id} disabled={tagSaving}
                        onClick={async () => {
                          setTagSaving(true);
                          try {
                            await addPersonTag(person.id, t.name);
                            setTags((prev) => [...prev, t]);
                          } finally { setTagSaving(false); }
                        }}
                        className="text-xs bg-white border border-gray-200 text-gray-600 px-2.5 py-1 rounded-full hover:border-violet-400 hover:text-violet-700 hover:bg-violet-50 transition-colors disabled:opacity-40"
                      >
                        + {t.name}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* Custom tag input */}
            <div>
              <p className="text-sm font-medium text-gray-600 mb-2">Add a custom tag</p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddTag()}
                  placeholder="Type a tag name and press Enter"
                  className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-300"
                />
                <button
                  onClick={handleAddTag}
                  disabled={!newTag.trim() || tagSaving}
                  className="px-3 py-1.5 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-40 transition-colors"
                >
                  {tagSaving ? "…" : "Add"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function tryParseSkills(json?: string | null): string[] {
  if (!json) return [];
  try {
    const parsed = JSON.parse(json);
    return Array.isArray(parsed) ? parsed.filter((s): s is string => typeof s === "string") : [];
  } catch {
    return [];
  }
}

function tryParseRoles(json?: string | null): StartupRole[] {
  if (!json) return [];
  try {
    const parsed = JSON.parse(json);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((r): r is StartupRole =>
      typeof r === "object" && r !== null && "name" in r && "role" in r
    );
  } catch {
    return [];
  }
}
