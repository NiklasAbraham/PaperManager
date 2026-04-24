import { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { apiFetch } from "../api/client";
import type { Note } from "../types";

interface Props {
  paperId: string;
  /** When true, shows a compact single-column layout (for narrow panels) */
  compact?: boolean;
}

const PERSON_RE = /@([\w][\w-]*)/g;
const TOPIC_RE = /#([\w][\w-]*)/g;

export default function NoteEditor({ paperId, compact }: Props) {
  const [content, setContent]   = useState("");
  const [saving, setSaving]     = useState(false);
  const [saved, setSaved]       = useState(false);
  const [loaded, setLoaded]     = useState(false);
  const [splitView, setSplitView] = useState(!compact);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const saveTimer   = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    apiFetch<Note>(`/papers/${paperId}/note`)
      .then((n) => { setContent(n.content); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [paperId]);

  const doSave = useCallback(async (text: string) => {
    setSaving(true);
    try {
      await apiFetch(`/papers/${paperId}/note`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }, [paperId]);

  const handleChange = (val: string) => {
    setContent(val);
    setSaved(false);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => doSave(val), 1000);
  };

  // Insert text at cursor position
  const insert = (before: string, after = "", placeholder = "") => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end   = el.selectionEnd;
    const sel   = content.slice(start, end) || placeholder;
    const next  = content.slice(0, start) + before + sel + after + content.slice(end);
    handleChange(next);
    // Restore cursor
    setTimeout(() => {
      el.focus();
      const pos = start + before.length + sel.length;
      el.setSelectionRange(pos, pos);
    }, 0);
  };

  const insertBlockquote = () => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end   = el.selectionEnd;
    const sel   = content.slice(start, end);
    if (sel) {
      // wrap selected text as blockquote lines
      const quoted = sel.split("\n").map((l) => `> ${l}`).join("\n");
      const next = content.slice(0, start) + quoted + content.slice(end);
      handleChange(next);
    } else {
      insert("> ", "", "paste quote here");
    }
  };

  const people = [...content.matchAll(PERSON_RE)].map((m) => m[1]);
  const topics = [...content.matchAll(TOPIC_RE)].map((m) => m[1]);

  const toolbar = (
    <div className="flex items-center gap-0.5 px-2 py-1 border-b border-gray-100 bg-gray-50 shrink-0 flex-wrap">
      <ToolBtn title="Bold" onClick={() => insert("**", "**", "bold text")}>B</ToolBtn>
      <ToolBtn title="Italic" onClick={() => insert("_", "_", "italic")} italic>I</ToolBtn>
      <ToolBtn title="Heading" onClick={() => insert("## ", "", "Heading")}>H</ToolBtn>
      <div className="w-px h-4 bg-gray-200 mx-1" />
      <ToolBtn title="Blockquote (PDF quote)" onClick={insertBlockquote}>"</ToolBtn>
      <ToolBtn title="Bullet list" onClick={() => insert("- ", "", "item")}>•</ToolBtn>
      <ToolBtn title="Code" onClick={() => insert("`", "`", "code")}>{"<>"}</ToolBtn>
      <div className="w-px h-4 bg-gray-200 mx-1" />
      <ToolBtn title="@Person mention" onClick={() => insert("@", "", "Name")}>@</ToolBtn>
      <ToolBtn title="#Topic mention" onClick={() => insert("#", "", "Topic")}>#</ToolBtn>
      <div className="flex-1" />
      <button
        onClick={() => setSplitView((v) => !v)}
        className="text-[10px] text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded border border-gray-200 hover:border-gray-300 transition-colors"
      >
        {splitView ? "Editor only" : "Split view"}
      </button>
      <span className="text-[10px] text-gray-400 ml-2 min-w-[40px] text-right">
        {saving ? "Saving…" : saved ? "✓ Saved" : loaded ? "Auto-saves" : "Loading…"}
      </span>
    </div>
  );

  const editorPane = (
    <textarea
      ref={textareaRef}
      className="flex-1 resize-none p-3 text-sm font-mono focus:outline-none bg-white leading-relaxed"
      value={content}
      onChange={(e) => handleChange(e.target.value)}
      placeholder={`Write notes in markdown…\n\n## Key insights\n\n> Paste a quote from the PDF here\n\nUse @Person and #Topic to link to graph nodes.`}
      spellCheck={false}
    />
  );

  const previewPane = (
    <div className="flex-1 overflow-y-auto p-3 prose prose-sm max-w-none text-gray-700 prose-headings:text-gray-800 prose-blockquote:border-violet-400 prose-blockquote:text-gray-500 prose-code:text-violet-700 prose-a:text-violet-600 border-l border-gray-100">
      {content.trim() ? (
        <ReactMarkdown>{content}</ReactMarkdown>
      ) : (
        <p className="text-gray-300 italic text-sm">Markdown preview will appear here.</p>
      )}
    </div>
  );

  return (
    <div className="flex flex-col h-full min-h-0 border border-gray-100 rounded-lg overflow-hidden">
      {toolbar}

      <div className={`flex-1 flex min-h-0 ${splitView ? "flex-row" : "flex-col"}`}>
        {editorPane}
        {splitView && previewPane}
      </div>

      {(people.length > 0 || topics.length > 0) && (
        <div className="px-3 py-1.5 border-t border-gray-100 bg-gray-50 text-xs text-gray-500 flex flex-wrap gap-1">
          {people.map((p) => (
            <span key={p} className="bg-violet-50 text-violet-700 px-2 py-0.5 rounded-full">@{p}</span>
          ))}
          {topics.map((t) => (
            <span key={t} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">#{t}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolBtn({ title, onClick, children, italic }: {
  title: string; onClick: () => void; children: React.ReactNode; italic?: boolean;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={`px-1.5 py-0.5 text-xs rounded hover:bg-gray-200 text-gray-600 font-medium transition-colors ${italic ? "italic" : ""}`}
    >
      {children}
    </button>
  );
}
