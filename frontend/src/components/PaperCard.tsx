import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { deletePaper, apiFetch } from "../api/client";
import EditPaperModal from "./EditPaperModal";
import type { Paper } from "../types";

const SOURCE_COLORS: Record<string, string> = {
  semantic_scholar: "bg-green-100 text-green-700",
  crossref:         "bg-green-100 text-green-700",
  llm:              "bg-yellow-100 text-yellow-700",
  heuristic:        "bg-red-100 text-red-700",
};

const STATUS_STYLES: Record<string, string> = {
  unread:  "bg-gray-100 text-gray-500",
  reading: "bg-blue-100 text-blue-600",
  read:    "bg-green-100 text-green-600",
};

const STATUS_LABELS: Record<string, string> = {
  unread: "📚 Unread",
  reading: "📖 Reading",
  read: "✅ Read",
};

interface Props {
  paper: Paper;
  showAbstract?: boolean;
  onDeleted?: (id: string) => void;
  onUpdated?: (p: Paper) => void;
}

export default function PaperCard({ paper: initial, showAbstract = true, onDeleted, onUpdated }: Props) {
  const navigate = useNavigate();
  const [paper, setPaper]       = useState(initial);
  const [editing, setEditing]   = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  const summaryPreview = paper.summary?.split("\n").slice(0, 2).join(" ") ?? "";

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirmDel) { setConfirmDel(true); return; }
    setDeleting(true);
    try {
      await deletePaper(paper.id);
      onDeleted?.(paper.id);
    } catch {
      setDeleting(false);
      setConfirmDel(false);
    }
  };

  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditing(true);
  };

  const toggleBookmark = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const newVal = !paper.bookmarked;
    const updated = await apiFetch<Paper>(`/papers/${paper.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookmarked: newVal }),
    });
    setPaper(updated);
    onUpdated?.(updated);
  };

  const cycleStatus = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const cycle: Array<Paper["reading_status"]> = ["unread", "reading", "read"];
    const current = paper.reading_status ?? "unread";
    const next = cycle[(cycle.indexOf(current) + 1) % cycle.length];
    const updated = await apiFetch<Paper>(`/papers/${paper.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reading_status: next }),
    });
    setPaper(updated);
    onUpdated?.(updated);
  };

  const setRating = async (e: React.MouseEvent, stars: number) => {
    e.stopPropagation();
    const newRating = paper.rating === stars ? null : stars;
    const updated = await apiFetch<Paper>(`/papers/${paper.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: newRating }),
    });
    setPaper(updated);
    onUpdated?.(updated);
  };

  const colorDot = paper.color ? (
    <span
      className="w-3 h-3 rounded-full border border-white shadow-sm shrink-0"
      style={{ backgroundColor: paper.color }}
      title={`Color: ${paper.color}`}
    />
  ) : null;

  return (
    <>
      <div
        onClick={() => navigate(`/paper/${paper.id}`)}
        className="relative group bg-white border border-gray-200 rounded-lg p-4 cursor-pointer hover:shadow-md hover:border-violet-300 transition-all"
        onMouseLeave={() => setConfirmDel(false)}
      >
        {/* Action buttons — appear on hover */}
        <div className="absolute top-2 right-2 hidden group-hover:flex gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={handleEdit}
            title="Edit metadata"
            className="p-1 rounded bg-white border border-gray-200 text-gray-400 hover:text-violet-600 hover:border-violet-300 transition-colors"
          >
            <PencilIcon />
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            title={confirmDel ? "Click again to confirm" : "Delete paper"}
            className={`p-1 rounded border transition-colors ${
              confirmDel
                ? "bg-red-600 border-red-600 text-white"
                : "bg-white border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-300"
            } disabled:opacity-50`}
          >
            {deleting ? <Spinner /> : <TrashIcon />}
          </button>
        </div>

        <div className="flex items-start justify-between gap-2 mb-1 pr-14">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            {colorDot}
            <h3 className="font-medium text-gray-900 text-sm leading-snug line-clamp-2">{paper.title}</h3>
          </div>
          {paper.year && <span className="text-xs text-gray-400 shrink-0">{paper.year}</span>}
        </div>

        {paper.venue && (
          <p className="text-xs text-gray-400 italic mt-0.5 truncate">{paper.venue}</p>
        )}

        {showAbstract && summaryPreview && (
          <p className="text-xs text-gray-500 line-clamp-2 mt-1">{summaryPreview}</p>
        )}

        <div className="mt-3 flex flex-wrap gap-1 items-center">
          {paper.metadata_source && (
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${SOURCE_COLORS[paper.metadata_source] ?? "bg-gray-100 text-gray-500"}`}>
              {paper.metadata_source}
            </span>
          )}
          {paper.citation_count != null && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
              {paper.citation_count.toLocaleString()} citations
            </span>
          )}

          {/* Reading status badge — clickable to cycle */}
          <button
            onClick={cycleStatus}
            title="Click to cycle reading status"
            className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors ${STATUS_STYLES[paper.reading_status ?? "unread"]}`}
          >
            {STATUS_LABELS[paper.reading_status ?? "unread"]}
          </button>

          {/* Bookmark */}
          <button
            onClick={toggleBookmark}
            title={paper.bookmarked ? "Remove bookmark" : "Bookmark this paper"}
            className={`text-sm leading-none ${paper.bookmarked ? "text-amber-400" : "text-gray-300 hover:text-amber-300"} transition-colors`}
          >
            ★
          </button>
        </div>

        {/* Star rating */}
        <div className="mt-2 flex gap-0.5" onClick={(e) => e.stopPropagation()}>
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              onClick={(e) => setRating(e, star)}
              title={`Rate ${star} star${star > 1 ? "s" : ""}`}
              className={`text-sm leading-none transition-colors ${
                star <= (paper.rating ?? 0) ? "text-amber-400" : "text-gray-200 hover:text-amber-300"
              }`}
            >
              ★
            </button>
          ))}
        </div>
      </div>

      {editing && (
        <EditPaperModal
          paper={paper}
          onSaved={(updated) => { setPaper(updated); onUpdated?.(updated); setEditing(false); }}
          onClose={() => setEditing(false)}
        />
      )}
    </>
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

function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
    </svg>
  );
}
