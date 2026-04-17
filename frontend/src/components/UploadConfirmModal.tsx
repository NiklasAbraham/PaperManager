import { useState } from "react";
import { uploadPdf, saveReferences, suggestTags, applyTags, createStandaloneTag } from "../api/client";
import type { ParsedMeta, T_IngestOut, Reference } from "../types";

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

  const [step, setStep]                   = useState<1 | 2 | 3>(1);
  const [uploadedPaper, setUploadedPaper] = useState<T_IngestOut | null>(null);

  // Step 2: refs
  const [checkedRefs, setCheckedRefs] = useState<boolean[]>([]);
  const [savingRefs, setSavingRefs]   = useState(false);

  // Step 3: tags
  const [allTags, setAllTags]           = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [newTagInput, setNewTagInput]   = useState("");
  const [pendingNew, setPendingNew]     = useState<string[]>([]);
  const [loadingTags, setLoadingTags]   = useState(false);
  const [applyingTags, setApplyingTags] = useState(false);

  const source = SOURCE_LABELS[meta.metadata_source] ?? { label: meta.metadata_source, color: "bg-gray-100 text-gray-500" };

  // ── Advance to tag step ────────────────────────────────────────────────────

  const goToTagStep = async (paper: T_IngestOut) => {
    setUploadedPaper(paper);
    setStep(3);
    setLoadingTags(true);
    try {
      const result = await suggestTags(paper.title, (paper as any).abstract ?? meta.abstract ?? undefined);
      setAllTags(result.all_tags);
      setSelectedTags(new Set(result.existing));
      setPendingNew(result.new);
    } catch {
      // fallback: just show all tags with nothing pre-selected
      setAllTags([]);
    } finally {
      setLoadingTags(false);
    }
  };

  // ── Step 1: upload ─────────────────────────────────────────────────────────

  const confirm = async () => {
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const paper = await uploadPdf(file, title.trim());
      if (paper.references_found && paper.references_found.length > 0) {
        setUploadedPaper(paper);
        setCheckedRefs(paper.references_found.map(() => true));
        setStep(2);
      } else {
        await goToTagStep(paper);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setSaving(false);
    }
  };

  // ── Step 2: refs ───────────────────────────────────────────────────────────

  const confirmRefs = async () => {
    if (!uploadedPaper) return;
    setSavingRefs(true);
    const selected = uploadedPaper.references_found.filter((_, i) => checkedRefs[i]);
    if (selected.length > 0) {
      try { await saveReferences(uploadedPaper.id, selected as Reference[]); } catch { /* best-effort */ }
    }
    setSavingRefs(false);
    await goToTagStep(uploadedPaper);
  };

  // ── Step 3: tags ───────────────────────────────────────────────────────────

  const toggleTag = (name: string) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const addPendingTag = (name: string) => {
    const clean = name.toLowerCase().replace(/\s+/g, "-").slice(0, 20);
    if (!clean) return;
    setPendingNew((prev) => prev.includes(clean) ? prev : [...prev, clean]);
    setSelectedTags((prev) => new Set([...prev, clean]));
    setNewTagInput("");
  };

  const finishTags = async () => {
    if (!uploadedPaper) return;
    setApplyingTags(true);
    try {
      // Create any new tags first
      const newToCreate = pendingNew.filter((t) => selectedTags.has(t) && !allTags.includes(t));
      for (const name of newToCreate) {
        await createStandaloneTag(name);
      }
      // Apply all selected tags to the paper
      if (selectedTags.size > 0) {
        await applyTags(uploadedPaper.id, [...selectedTags]);
      }
    } catch { /* best-effort */ }
    setApplyingTags(false);
    onConfirmed(uploadedPaper);
  };

  // ── Render: Step 2 ─────────────────────────────────────────────────────────

  if (step === 2 && uploadedPaper) {
    const refs = uploadedPaper.references_found;
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
          <ModalHeader step={2} title="Save references?" subtitle={`Found ${refs.length} reference${refs.length !== 1 ? "s" : ""} — uncheck any to skip.`} />
          <div className="px-6 py-3 max-h-[55vh] overflow-y-auto space-y-1">
            {refs.map((ref, i) => (
              <label key={i} className="flex items-start gap-2 cursor-pointer hover:bg-gray-50 rounded px-1 py-1">
                <input type="checkbox" className="mt-0.5 shrink-0" checked={checkedRefs[i] ?? true}
                  onChange={(e) => { const n = [...checkedRefs]; n[i] = e.target.checked; setCheckedRefs(n); }} />
                <span className="text-xs text-gray-700 leading-snug">
                  <span className="font-medium">{ref.title}</span>
                  {ref.year ? <span className="text-gray-400"> · {ref.year}</span> : null}
                  {ref.doi  ? <span className="text-gray-400"> · {ref.doi}</span>  : null}
                </span>
              </label>
            ))}
          </div>
          <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
            <button onClick={() => goToTagStep(uploadedPaper)} disabled={savingRefs} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50">Skip</button>
            <button onClick={confirmRefs} disabled={savingRefs || checkedRefs.every((c) => !c)}
              className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50">
              {savingRefs ? "Saving…" : `Save ${checkedRefs.filter(Boolean).length} · Next →`}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Step 3 ─────────────────────────────────────────────────────────

  if (step === 3 && uploadedPaper) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
          <ModalHeader step={3} title="Add tags" subtitle="Ollama suggested tags based on the abstract. Click to toggle, or add your own." />

          <div className="px-6 py-4 space-y-4 max-h-[65vh] overflow-y-auto">
            {loadingTags ? (
              <div className="flex items-center gap-2 text-violet-600 text-sm py-4 justify-center">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                Asking Ollama for suggestions…
              </div>
            ) : (
              <>
                {/* Suggested new tags from Ollama */}
                {pendingNew.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                      ✦ New tags suggested by AI
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {pendingNew.map((t) => (
                        <button key={t} onClick={() => toggleTag(t)}
                          className={`text-xs px-2.5 py-1 rounded-full border transition-colors font-medium
                            ${selectedTags.has(t)
                              ? "bg-violet-600 border-violet-600 text-white"
                              : "border-dashed border-violet-400 text-violet-600 hover:bg-violet-50"}`}>
                          + {t}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* All existing tags */}
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                    All tags {selectedTags.size > 0 && <span className="text-violet-600">· {selectedTags.size} selected</span>}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {allTags.map((t) => (
                      <button key={t} onClick={() => toggleTag(t)}
                        className={`text-xs px-2.5 py-1 rounded-full border transition-colors
                          ${selectedTags.has(t)
                            ? "bg-violet-600 border-violet-600 text-white font-medium"
                            : "border-gray-200 text-gray-600 hover:border-violet-400 hover:text-violet-600"}`}>
                        {t}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Custom tag input */}
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Create new tag</p>
                  <div className="flex gap-2">
                    <input
                      value={newTagInput}
                      onChange={(e) => setNewTagInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addPendingTag(newTagInput); } }}
                      placeholder="new-tag-name"
                      className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
                    />
                    <button onClick={() => addPendingTag(newTagInput)} disabled={!newTagInput.trim()}
                      className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200 disabled:opacity-50">
                      Add
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
            <button onClick={() => onConfirmed(uploadedPaper)} disabled={applyingTags}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50">
              Skip
            </button>
            <button onClick={finishTags} disabled={applyingTags || loadingTags}
              className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50">
              {applyingTags ? "Saving…" : selectedTags.size > 0 ? `Apply ${selectedTags.size} tag${selectedTags.size !== 1 ? "s" : ""}` : "Done"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Step 1 ─────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold text-gray-900">Confirm paper details</h2>
            <StepDots current={1} />
          </div>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${source.color}`}>{source.label}</span>
        </div>

        <div className="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <Field label="Title *">
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300" />
          </Field>
          <Field label="Authors (comma separated)">
            <input type="text" value={authors} onChange={(e) => setAuthors(e.target.value)} placeholder="Author One, Author Two"
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300" />
          </Field>
          <div className="flex gap-3">
            <Field label="Year" className="w-24 shrink-0">
              <input type="number" value={year} onChange={(e) => setYear(e.target.value)} placeholder="2024"
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300" />
            </Field>
            <Field label="DOI / arXiv ID" className="flex-1">
              <input type="text" value={doi} onChange={(e) => setDoi(e.target.value)} placeholder="10.xxxx/… or arXiv:…"
                className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300" />
            </Field>
          </div>
          <Field label="Abstract">
            <textarea value={abstract} onChange={(e) => setAbstract(e.target.value)} rows={4} className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none" />
          </Field>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button onClick={onCancel} disabled={saving} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50">Cancel</button>
          <button onClick={confirm} disabled={saving || !title.trim()}
            className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2">
            {saving && <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" /></svg>}
            {saving ? "Uploading…" : "Upload · Next →"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function ModalHeader({ step, title, subtitle }: { step: number; title: string; subtitle: string }) {
  return (
    <div className="px-6 py-4 border-b border-gray-100">
      <div className="flex items-center justify-between mb-0.5">
        <h2 className="font-semibold text-gray-900">{title}</h2>
        <StepDots current={step} />
      </div>
      <p className="text-xs text-gray-500">{subtitle}</p>
    </div>
  );
}

function StepDots({ current }: { current: number }) {
  return (
    <div className="flex gap-1 items-center">
      {[1, 2, 3].map((n) => (
        <span key={n} className={`w-1.5 h-1.5 rounded-full transition-colors ${n === current ? "bg-violet-600" : n < current ? "bg-violet-300" : "bg-gray-200"}`} />
      ))}
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
