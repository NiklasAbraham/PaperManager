import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import NoteEditor from "../components/NoteEditor";
import ChatPanel from "../components/ChatPanel";
import type { Paper, Person, Topic, Tag } from "../types";

interface PaperFull extends Paper {
  authors?: Person[];
  topics?: Topic[];
  tags?: Tag[];
}

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const [paper, setPaper] = useState<PaperFull | null>(null);
  const [authors, setAuthors] = useState<Person[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [newTag, setNewTag] = useState("");
  const [newTopic, setNewTopic] = useState("");

  useEffect(() => {
    if (!id) return;
    apiFetch<PaperFull>(`/papers/${id}`).then(setPaper).catch(() => {});
    apiFetch<Person[]>(`/papers/${id}/authors`).then(setAuthors).catch(() => {});
    apiFetch<Topic[]>(`/papers/${id}/topics`).then(setTopics).catch(() => {});
    apiFetch<Tag[]>(`/papers/${id}/tags`).then(setTags).catch(() => {});
  }, [id]);

  const addTag = async () => {
    if (!newTag.trim() || !id) return;
    await apiFetch(`/papers/${id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newTag.trim() }),
    });
    const updated = await apiFetch<Tag[]>(`/papers/${id}/tags`);
    setTags(updated);
    setNewTag("");
  };

  const addTopic = async () => {
    if (!newTopic.trim() || !id) return;
    await apiFetch(`/papers/${id}/topics`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newTopic.trim() }),
    });
    const updated = await apiFetch<Topic[]>(`/papers/${id}/topics`);
    setTopics(updated);
    setNewTopic("");
  };

  if (!paper) return <div className="p-8 text-sm text-gray-400">Loading…</div>;

  return (
    <div className="h-[calc(100vh-53px)] flex flex-col">
      {/* Topbar */}
      <div className="flex items-center justify-between px-6 py-3 bg-white border-b border-gray-200">
        <Link to="/" className="text-sm text-violet-600 hover:underline">← Library</Link>
        {paper.drive_file_id && (
          <a
            href={`https://drive.google.com/file/d/${paper.drive_file_id}/view`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            PDF ↗
          </a>
        )}
      </div>

      {/* Three-panel layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Metadata */}
        <aside className="w-56 shrink-0 border-r border-gray-200 bg-white overflow-y-auto p-4 space-y-4">
          <div>
            <h1 className="text-sm font-semibold text-gray-900 leading-snug">{paper.title}</h1>
            {paper.year && <p className="text-xs text-gray-400 mt-0.5">{paper.year}</p>}
          </div>

          {authors.length > 0 && (
            <MetaSection title="Authors">
              {authors.map((a) => <p key={a.id} className="text-xs text-gray-600">{a.name}</p>)}
            </MetaSection>
          )}

          <MetaSection title="Topics">
            <div className="flex flex-wrap gap-1">
              {topics.map((t) => (
                <span key={t.id} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">{t.name}</span>
              ))}
            </div>
            <InlineAdd
              value={newTopic}
              onChange={setNewTopic}
              onAdd={addTopic}
              placeholder="Add topic…"
            />
          </MetaSection>

          <MetaSection title="Tags">
            <div className="flex flex-wrap gap-1">
              {tags.map((t) => (
                <span key={t.id} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{t.name}</span>
              ))}
            </div>
            <InlineAdd
              value={newTag}
              onChange={setNewTag}
              onAdd={addTag}
              placeholder="Add tag…"
            />
          </MetaSection>

          {paper.abstract && (
            <MetaSection title="Abstract">
              <p className="text-xs text-gray-500 leading-relaxed">{paper.abstract}</p>
            </MetaSection>
          )}

          {paper.citation_count != null && (
            <p className="text-xs text-gray-400">{paper.citation_count.toLocaleString()} citations</p>
          )}
        </aside>

        {/* Note */}
        <div className="flex-1 border-r border-gray-200 bg-white p-4 overflow-hidden flex flex-col">
          {id && <NoteEditor paperId={id} />}
        </div>

        {/* Chat */}
        <div className="w-80 shrink-0 bg-white p-4 overflow-hidden flex flex-col">
          {id && <ChatPanel paperId={id} />}
        </div>
      </div>
    </div>
  );
}

function MetaSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">{title}</h3>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function InlineAdd({
  value, onChange, onAdd, placeholder,
}: {
  value: string; onChange: (v: string) => void; onAdd: () => void; placeholder: string;
}) {
  return (
    <div className="flex gap-1 mt-1">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onAdd()}
        placeholder={placeholder}
        className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-300"
      />
      <button
        onClick={onAdd}
        className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200"
      >+</button>
    </div>
  );
}
