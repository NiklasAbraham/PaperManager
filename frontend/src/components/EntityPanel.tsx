import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  apiFetch, deletePaper, updatePaper,
  createStandaloneTag, deleteTag,
  createStandaloneTopic, deleteTopic, renameTopic,
  deletePerson, updatePerson,
  deleteProject, updateProject,
} from "../api/client";
import type { Paper, Person, Topic, Tag, Project } from "../types";

export type EntityType = "papers" | "authors" | "topics" | "tags" | "projects";

interface Props {
  type: EntityType;
  onClose: () => void;
  onStatsChanged: () => void;
}

export default function EntityPanel({ type, onClose, onStatsChanged }: Props) {
  const [items, setItems]     = useState<unknown[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = () => {
    setLoading(true);
    const url = type === "authors" ? "/people" : `/${type}`;
    apiFetch<unknown[]>(url).then(setItems).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { reload(); }, [type]);

  const title: Record<EntityType, string> = {
    papers: "Papers", authors: "Authors", topics: "Topics", tags: "Tags", projects: "Projects",
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-white h-full shadow-2xl flex flex-col animate-slide-in">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900">{title[type]}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="p-5 text-sm text-gray-400">Loading…</p>
          ) : items.length === 0 ? (
            <p className="p-5 text-sm text-gray-400">Nothing here yet.</p>
          ) : (
            <>
              {type === "papers"   && <PaperList   items={items as Paper[]}   reload={reload} onStatsChanged={onStatsChanged} />}
              {type === "authors"  && <PersonList  items={items as Person[]}  reload={reload} onStatsChanged={onStatsChanged} />}
              {type === "topics"   && <TopicList   items={items as Topic[]}   reload={reload} onStatsChanged={onStatsChanged} />}
              {type === "tags"     && <TagList     items={items as Tag[]}     reload={reload} onStatsChanged={onStatsChanged} />}
              {type === "projects" && <ProjectList items={items as Project[]} reload={reload} onStatsChanged={onStatsChanged} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Papers ────────────────────────────────────────────────────────────────────

function PaperList({ items, reload, onStatsChanged }: { items: Paper[]; reload: () => void; onStatsChanged: () => void }) {
  const navigate = useNavigate();
  const [editing, setEditing] = useState<Paper | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const startEdit = (p: Paper) => { setEditing(p); setEditTitle(p.title); };

  const saveEdit = async () => {
    if (!editing) return;
    await updatePaper(editing.id, { title: editTitle.trim() });
    setEditing(null);
    reload();
  };

  const remove = async (p: Paper) => {
    await deletePaper(p.id);
    onStatsChanged();
    reload();
  };

  return (
    <div className="divide-y divide-gray-100">
      {items.map((p) => (
        <div key={p.id} className="px-5 py-3 flex items-start gap-3 hover:bg-gray-50">
          {editing?.id === p.id ? (
            <div className="flex-1 flex gap-2">
              <input
                autoFocus value={editTitle} onChange={(e) => setEditTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditing(null); }}
                className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none"
              />
              <button onClick={saveEdit} className="text-xs bg-violet-600 text-white px-2 py-1 rounded hover:bg-violet-700">Save</button>
              <button onClick={() => setEditing(null)} className="text-xs text-gray-400 hover:text-gray-600">×</button>
            </div>
          ) : (
            <>
              <div className="flex-1 min-w-0 cursor-pointer" onClick={() => navigate(`/paper/${p.id}`)}>
                <p className="text-sm font-medium text-gray-800 hover:text-violet-700 truncate">{p.title}</p>
                <p className="text-xs text-gray-400">{p.year ?? "—"}</p>
              </div>
              <div className="flex gap-1 shrink-0">
                <IconBtn title="Edit" onClick={() => startEdit(p)}><PencilIcon /></IconBtn>
                <ConfirmDelete onDelete={() => remove(p)} />
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ── People ────────────────────────────────────────────────────────────────────

function PersonList({ items, reload, onStatsChanged }: { items: Person[]; reload: () => void; onStatsChanged: () => void }) {
  const [editing, setEditing] = useState<Person | null>(null);
  const [editName, setEditName] = useState("");

  const startEdit = (p: Person) => { setEditing(p); setEditName(p.name); };

  const saveEdit = async () => {
    if (!editing) return;
    await updatePerson(editing.id, { name: editName.trim() });
    setEditing(null);
    reload();
  };

  const remove = async (p: Person) => {
    await deletePerson(p.id);
    onStatsChanged();
    reload();
  };

  return (
    <div className="divide-y divide-gray-100">
      {items.map((p) => (
        <div key={p.id} className="px-5 py-3 flex items-center gap-3 hover:bg-gray-50">
          {editing?.id === p.id ? (
            <div className="flex-1 flex gap-2">
              <input
                autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditing(null); }}
                className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none"
              />
              <button onClick={saveEdit} className="text-xs bg-violet-600 text-white px-2 py-1 rounded hover:bg-violet-700">Save</button>
              <button onClick={() => setEditing(null)} className="text-xs text-gray-400 hover:text-gray-600">×</button>
            </div>
          ) : (
            <>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{p.name}</p>
                {p.affiliation && <p className="text-xs text-gray-400 truncate">{p.affiliation}</p>}
              </div>
              <div className="flex gap-1 shrink-0">
                <IconBtn title="Edit" onClick={() => startEdit(p)}><PencilIcon /></IconBtn>
                <ConfirmDelete onDelete={() => remove(p)} />
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Topics ────────────────────────────────────────────────────────────────────

function TopicList({ items, reload, onStatsChanged }: { items: Topic[]; reload: () => void; onStatsChanged: () => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");

  const startEdit = (t: Topic) => { setEditing(t.name); setEditName(t.name); };

  const saveEdit = async () => {
    if (!editing) return;
    await renameTopic(editing, editName.trim());
    setEditing(null);
    reload();
  };

  const remove = async (name: string) => {
    await deleteTopic(name);
    onStatsChanged();
    reload();
  };

  const add = async () => {
    const name = newName.trim();
    if (!name) return;
    await createStandaloneTopic(name);
    setNewName("");
    setAdding(false);
    onStatsChanged();
    reload();
  };

  return (
    <div className="divide-y divide-gray-100">
      {/* Add row */}
      <div className="px-5 py-3">
        {adding ? (
          <div className="flex gap-2">
            <input
              autoFocus value={newName} onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") add(); if (e.key === "Escape") { setAdding(false); setNewName(""); } }}
              placeholder="Topic name…"
              className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none"
            />
            <button onClick={add} className="text-xs bg-violet-600 text-white px-2 py-1 rounded hover:bg-violet-700">Add</button>
            <button onClick={() => { setAdding(false); setNewName(""); }} className="text-xs text-gray-400 hover:text-gray-600">×</button>
          </div>
        ) : (
          <button onClick={() => setAdding(true)} className="flex items-center gap-1.5 text-xs text-violet-600 hover:text-violet-800 font-medium">
            <PlusIcon /> Add topic
          </button>
        )}
      </div>
      {items.map((t) => (
        <div key={t.id} className="px-5 py-3 flex items-center gap-3 hover:bg-gray-50">
          {editing === t.name ? (
            <div className="flex-1 flex gap-2">
              <input
                autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditing(null); }}
                className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none"
              />
              <button onClick={saveEdit} className="text-xs bg-violet-600 text-white px-2 py-1 rounded hover:bg-violet-700">Save</button>
              <button onClick={() => setEditing(null)} className="text-xs text-gray-400 hover:text-gray-600">×</button>
            </div>
          ) : (
            <>
              <span className="flex-1 text-sm font-medium text-gray-800">{t.name}</span>
              {t.paper_count != null && (
                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">{t.paper_count} papers</span>
              )}
              <div className="flex gap-1 shrink-0">
                <IconBtn title="Rename" onClick={() => startEdit(t)}><PencilIcon /></IconBtn>
                <ConfirmDelete onDelete={() => remove(t.name)} />
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Tags ─────────────────────────────────────────────────────────────────────

function TagList({ items, reload, onStatsChanged }: { items: Tag[]; reload: () => void; onStatsChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");

  const remove = async (name: string) => {
    await deleteTag(name);
    onStatsChanged();
    reload();
  };

  const add = async () => {
    const name = newName.trim();
    if (!name) return;
    await createStandaloneTag(name);
    setNewName("");
    setAdding(false);
    onStatsChanged();
    reload();
  };

  return (
    <div className="divide-y divide-gray-100">
      {/* Add row */}
      <div className="px-5 py-3">
        {adding ? (
          <div className="flex gap-2">
            <input
              autoFocus value={newName} onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") add(); if (e.key === "Escape") { setAdding(false); setNewName(""); } }}
              placeholder="Tag name…"
              className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none"
            />
            <button onClick={add} className="text-xs bg-violet-600 text-white px-2 py-1 rounded hover:bg-violet-700">Add</button>
            <button onClick={() => { setAdding(false); setNewName(""); }} className="text-xs text-gray-400 hover:text-gray-600">×</button>
          </div>
        ) : (
          <button onClick={() => setAdding(true)} className="flex items-center gap-1.5 text-xs text-violet-600 hover:text-violet-800 font-medium">
            <PlusIcon /> Add tag
          </button>
        )}
      </div>
      {items.map((t) => (
        <div key={t.id} className="px-5 py-3 flex items-center gap-3 hover:bg-gray-50">
          <span className="flex-1 text-sm font-medium text-gray-800">{t.name}</span>
          {t.paper_count != null && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">{t.paper_count} papers</span>
          )}
          <ConfirmDelete onDelete={() => remove(t.name)} />
        </div>
      ))}
    </div>
  );
}

// ── Projects ──────────────────────────────────────────────────────────────────

function ProjectList({ items, reload, onStatsChanged }: { items: Project[]; reload: () => void; onStatsChanged: () => void }) {
  const [editing, setEditing] = useState<Project | null>(null);
  const [editName, setEditName] = useState("");

  const startEdit = (p: Project) => { setEditing(p); setEditName(p.name); };

  const saveEdit = async () => {
    if (!editing) return;
    await updateProject(editing.id, { name: editName.trim() });
    setEditing(null);
    reload();
  };

  const remove = async (p: Project) => {
    await deleteProject(p.id);
    onStatsChanged();
    reload();
  };

  return (
    <div className="divide-y divide-gray-100">
      {items.map((p) => (
        <div key={p.id} className="px-5 py-3 flex items-center gap-3 hover:bg-gray-50">
          {editing?.id === p.id ? (
            <div className="flex-1 flex gap-2">
              <input
                autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditing(null); }}
                className="flex-1 text-sm border border-violet-300 rounded px-2 py-1 focus:outline-none"
              />
              <button onClick={saveEdit} className="text-xs bg-violet-600 text-white px-2 py-1 rounded hover:bg-violet-700">Save</button>
              <button onClick={() => setEditing(null)} className="text-xs text-gray-400 hover:text-gray-600">×</button>
            </div>
          ) : (
            <>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{p.name}</p>
                {p.description && <p className="text-xs text-gray-400 truncate">{p.description}</p>}
              </div>
              <div className="flex gap-1 shrink-0">
                <IconBtn title="Edit" onClick={() => startEdit(p)}><PencilIcon /></IconBtn>
                <ConfirmDelete onDelete={() => remove(p)} />
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function ConfirmDelete({ onDelete }: { onDelete: () => void }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <button
      title={confirm ? "Click again to confirm" : "Delete"}
      onClick={() => { if (confirm) onDelete(); else setConfirm(true); }}
      onMouseLeave={() => setConfirm(false)}
      className={`p-1.5 rounded border transition-colors text-xs ${
        confirm
          ? "bg-red-600 border-red-600 text-white"
          : "border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-300"
      }`}
    >
      <TrashIcon />
    </button>
  );
}

function IconBtn({ onClick, title, children }: { onClick: () => void; title: string; children: React.ReactNode }) {
  return (
    <button onClick={onClick} title={title}
      className="p-1.5 rounded border border-gray-200 text-gray-400 hover:text-violet-600 hover:border-violet-300 transition-colors">
      {children}
    </button>
  );
}

function PencilIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}
