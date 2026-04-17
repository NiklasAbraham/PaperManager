import { useState } from "react";
import { uploadPdf } from "../api/client";
import type { ParsedMeta, T_IngestOut } from "../types";

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  semantic_scholar: { label: "Semantic Scholar", color: "bg-green-100 text-green-700" },
  crossref:         { label: "Crossref",          color: "bg-green-100 text-green-700" },
  llm:              { label: "AI extracted — please review", color: "bg-yellow-100 text-yellow-700" },
  heuristic:        { label: "Guessed — please correct",     color: "bg-red-100 text-red-700" },
};

interface Props {
  file: File;
  meta: ParsedMeta;
  onConfirmed: (paper: T_IngestOut) => void;
  onCancel: () => void;
}

export default function UploadConfirmModal({ file, meta, onConfirmed, onCancel }: Props) {
  const [title, setTitle]       = useState(meta.title || "");
  const [authors, setAuthors]   = useState((meta.authors ?? []).join(", "));
  const [year, setYear]         = useState(meta.year?.toString() ?? "");
  const [doi, setDoi]           = useState(meta.doi ?? "");
  const [abstract, setAbstract] = useState(meta.abstract ?? "");
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const source = SOURCE_LABELS[meta.metadata_source] ?? { label: meta.metadata_source, color: "bg-gray-100 text-gray-500" };

  const confirm = async () => {
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const paper = await uploadPdf(file, title.trim());
      onConfirmed(paper);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Confirm paper details</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${source.color}`}>
            {source.label}
          </span>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <Field label="Title *">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
              autoFocus
            />
          </Field>

          <Field label="Authors (comma separated)">
            <input
              type="text"
              value={authors}
              onChange={(e) => setAuthors(e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
              placeholder="Author One, Author Two"
            />
          </Field>

          <div className="flex gap-3">
            <Field label="Year" className="w-24 shrink-0">
              <input
                type="number"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
                placeholder="2024"
              />
            </Field>
            <Field label="DOI / arXiv ID" className="flex-1">
              <input
                type="text"
                value={doi}
                onChange={(e) => setDoi(e.target.value)}
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
                placeholder="10.xxxx/… or arXiv:…"
              />
            </Field>
          </div>

          <Field label="Abstract">
            <textarea
              value={abstract}
              onChange={(e) => setAbstract(e.target.value)}
              rows={4}
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none"
            />
          </Field>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={confirm}
            disabled={saving || !title.trim()}
            className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2"
          >
            {saving && (
              <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
            )}
            {saving ? "Uploading…" : "Upload paper"}
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
