import { useState } from "react";
import { updatePaper } from "../api/client";
import type { Paper, Tag, Topic } from "../types";

interface Props {
  paper: Paper;
  onSaved: (updated: Paper) => void;
  onClose: () => void;
  metadataEditor?: {
    tags: Tag[];
    topics: Topic[];
    onSave: (next: { tags: string[]; topics: string[] }) => Promise<{ tags: Tag[]; topics: Topic[] }>;
    onSaved?: (next: { tags: Tag[]; topics: Topic[] }) => void;
  };
}

const PAPER_COLORS = [
  "", "#ef4444", "#f97316", "#eab308", "#22c55e",
  "#06b6d4", "#6366f1", "#ec4899", "#8b5cf6", "#14b8a6",
];

export default function EditPaperModal({ paper, onSaved, onClose, metadataEditor }: Props) {
  const [title,          setTitle]          = useState(paper.title);
  const [year,           setYear]           = useState(paper.year?.toString() ?? "");
  const [doi,            setDoi]            = useState(paper.doi ?? "");
  const [abstract,       setAbstract]       = useState(paper.abstract ?? "");
  const [venue,          setVenue]          = useState(paper.venue ?? "");
  const [metadataSource, setMetadataSource] = useState(paper.metadata_source ?? "");
  const [reading_status, setReadingStatus]  = useState<Paper["reading_status"]>(paper.reading_status ?? "unread");
  const [color,          setColor]          = useState(paper.color ?? "");
  const [tagNames, setTagNames]             = useState(() => metadataEditor?.tags.map((tag) => tag.name) ?? []);
  const [topicNames, setTopicNames]         = useState(() => metadataEditor?.topics.map((topic) => topic.name) ?? []);
  const [newTag, setNewTag]                 = useState("");
  const [newTopic, setNewTopic]             = useState("");
  const [saving,   setSaving]   = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  const updateList = (items: string[], next: string) => {
    if (!next) return items;
    return items.includes(next) ? items : [...items, next];
  };

  const removeListItem = (items: string[], target: string) => items.filter((item) => item !== target);

  const addTagDraft = () => {
    const clean = newTag.trim().toLowerCase().replace(/\s+/g, "-");
    if (!clean) return;
    setTagNames((prev) => updateList(prev, clean));
    setNewTag("");
  };

  const addTopicDraft = () => {
    const clean = newTopic.trim();
    if (!clean) return;
    setTopicNames((prev) => updateList(prev, clean));
    setNewTopic("");
  };

  const save = async () => {
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePaper(paper.id, {
        title:          title.trim(),
        year:           year ? parseInt(year) : null,
        doi:            doi.trim() || null,
        abstract:       abstract.trim() || null,
        venue:          venue.trim() || null,
        metadata_source: metadataSource.trim() || null,
        reading_status: reading_status ?? null,
        color:          color || null,
      });

      if (metadataEditor) {
        const nextTags = [...new Set(tagNames.map((tag) => tag.trim()).filter(Boolean))];
        const nextTopics = [...new Set(topicNames.map((topic) => topic.trim()).filter(Boolean))];
        const savedMetadata = await metadataEditor.onSave({ tags: nextTags, topics: nextTopics });
        metadataEditor.onSaved?.(savedMetadata);
      }

      onSaved(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Edit paper</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>

        <div className="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <Field label="Title *">
            <input
              type="text" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
          </Field>

          <div className="flex gap-3">
            <Field label="Year" className="w-24 shrink-0">
              <input
                type="number" value={year} onChange={(e) => setYear(e.target.value)}
                placeholder="2024"
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
              />
            </Field>
            <Field label="DOI / arXiv ID" className="flex-1">
              <input
                type="text" value={doi} onChange={(e) => setDoi(e.target.value)}
                placeholder="10.xxxx/…"
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
              />
            </Field>
          </div>

          <Field label="Venue / Journal">
            <input
              type="text" value={venue} onChange={(e) => setVenue(e.target.value)}
              placeholder="NeurIPS, ICML, Nature…"
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
          </Field>

          <Field label="Metadata source">
            <input
              type="text" value={metadataSource} onChange={(e) => setMetadataSource(e.target.value)}
              placeholder="manual, semantic_scholar, crossref…"
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
          </Field>

          <Field label="Abstract">
            <textarea
              value={abstract} onChange={(e) => setAbstract(e.target.value)}
              rows={5}
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none"
            />
          </Field>

          <div className="flex gap-3">
            <Field label="Reading status" className="flex-1">
              <select
                value={reading_status ?? "unread"}
                onChange={(e) => setReadingStatus(e.target.value as Paper["reading_status"])}
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
              >
                <option value="unread">📚 Unread</option>
                <option value="reading">📖 Reading</option>
                <option value="read">✅ Read</option>
              </select>
            </Field>

            <Field label="Label color">
              <div className="flex flex-wrap gap-1.5 mt-1">
                {PAPER_COLORS.map((c) => (
                  <button
                    key={c || "none"}
                    type="button"
                    onClick={() => setColor(c)}
                    title={c || "No color"}
                    className={`w-5 h-5 rounded-full border-2 transition-all ${
                      color === c ? "border-violet-500 scale-125" : "border-gray-200 hover:scale-110"
                    }`}
                    style={{ backgroundColor: c || "#f3f4f6" }}
                  />
                ))}
              </div>
            </Field>
          </div>

          {metadataEditor && (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Tags">
                  <div className="space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <div className="flex flex-wrap gap-1.5 min-h-6">
                      {tagNames.length === 0 ? (
                        <span className="text-xs text-gray-400">No tags yet</span>
                      ) : (
                        tagNames.map((tag) => (
                          <button
                            key={tag}
                            type="button"
                            onClick={() => setTagNames((prev) => removeListItem(prev, tag))}
                            className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-xs text-gray-600 ring-1 ring-gray-200 hover:ring-red-200 hover:text-red-600"
                          >
                            <span>{tag}</span>
                            <span>×</span>
                          </button>
                        ))
                      )}
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={newTag}
                        onChange={(e) => setNewTag(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            addTagDraft();
                          }
                        }}
                        placeholder="Add tag"
                        className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-300"
                      />
                      <button
                        type="button"
                        onClick={addTagDraft}
                        className="px-3 py-1.5 text-sm rounded bg-white text-gray-600 ring-1 ring-gray-200 hover:text-violet-700 hover:ring-violet-200"
                      >
                        Add
                      </button>
                    </div>
                  </div>
                </Field>

                <Field label="Topics">
                  <div className="space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <div className="flex flex-wrap gap-1.5 min-h-6">
                      {topicNames.length === 0 ? (
                        <span className="text-xs text-gray-400">No topics yet</span>
                      ) : (
                        topicNames.map((topic) => (
                          <button
                            key={topic}
                            type="button"
                            onClick={() => setTopicNames((prev) => removeListItem(prev, topic))}
                            className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-xs text-blue-700 ring-1 ring-blue-200 hover:ring-red-200 hover:text-red-600"
                          >
                            <span>{topic}</span>
                            <span>×</span>
                          </button>
                        ))
                      )}
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={newTopic}
                        onChange={(e) => setNewTopic(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            addTopicDraft();
                          }
                        }}
                        placeholder="Add topic"
                        className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-300"
                      />
                      <button
                        type="button"
                        onClick={addTopicDraft}
                        className="px-3 py-1.5 text-sm rounded bg-white text-gray-600 ring-1 ring-gray-200 hover:text-violet-700 hover:ring-violet-200"
                      >
                        Add
                      </button>
                    </div>
                  </div>
                </Field>
              </div>
            </>
          )}

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button onClick={onClose} disabled={saving}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50">
            Cancel
          </button>
          <button onClick={save} disabled={saving || !title.trim()}
            className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2">
            {saving && (
              <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
            )}
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
      {children}
    </div>
  );
}
