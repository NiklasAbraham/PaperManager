import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { apiFetch } from "../api/client";
import type { Note } from "../types";

interface Props {
  paperId: string;
}

const PERSON_RE = /@([\w][\w-]*)/g;
const TOPIC_RE = /#([\w][\w-]*)/g;


export default function NoteEditor({ paperId }: Props) {
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<Note>(`/papers/${paperId}/note`)
      .then((n) => setContent(n.content))
      .catch(() => {});
  }, [paperId]);

  const save = async () => {
    setSaving(true);
    try {
      await apiFetch(`/papers/${paperId}/note`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const people = [...content.matchAll(PERSON_RE)].map((m) => m[1]);
  const topics = [...content.matchAll(TOPIC_RE)].map((m) => m[1]);

  return (
    <div className="flex flex-col h-full gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">Note</h2>
        <button
          onClick={() => setPreview((p) => !p)}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          {preview ? "Edit" : "Preview"}
        </button>
      </div>

      {preview ? (
        <div className="flex-1 overflow-auto prose prose-sm max-w-none bg-white border border-gray-200 rounded p-3">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      ) : (
        <div className="flex-1 relative">
          <textarea
            className="w-full h-full resize-none border border-gray-200 rounded p-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-300"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Write notes… use @Person and #Topic"
          />
        </div>
      )}

      {(people.length > 0 || topics.length > 0) && (
        <div className="text-xs text-gray-500 flex flex-wrap gap-1">
          {people.map((p) => (
            <span key={p} className="bg-violet-50 text-violet-700 px-2 py-0.5 rounded-full">@{p}</span>
          ))}
          {topics.map((t) => (
            <span key={t} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">#{t}</span>
          ))}
        </div>
      )}

      <button
        onClick={save}
        disabled={saving}
        className="self-end text-sm px-4 py-1.5 rounded bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
      >
        {saving ? "Saving…" : saved ? "Saved!" : "Save"}
      </button>
    </div>
  );
}
