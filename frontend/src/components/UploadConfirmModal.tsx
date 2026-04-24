import { useState, useEffect, useRef } from "react";
import { uploadPdf, ingestFromUrlFull, saveReferences, applyTags, apiFetch, getOrCreatePerson, linkPersonInvolves, listPeople, listProjects, previewUrlPdf, uploadPdfForPaper, parsePdf } from "../api/client";
import { useAppSettings } from "../contexts/SettingsContext";
import type { ParsedMeta, T_IngestOut, Reference, Paper } from "../types";

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  semantic_scholar: { label: "Semantic Scholar", color: "bg-green-100 text-green-700" },
  crossref:         { label: "Crossref",          color: "bg-green-100 text-green-700" },
  llm:              { label: "AI extracted — please review", color: "bg-yellow-100 text-yellow-700" },
  heuristic:        { label: "Guessed — please correct",     color: "bg-red-100 text-red-700" },
};

interface Props {
  file: File | null;
  meta: ParsedMeta;
  onConfirmed: (paper: T_IngestOut) => void;
  onCancel: () => void;
  /** When provided (no file), ingest via URL instead of PDF upload. */
  url?: string;
  debug?: boolean;
}

export default function UploadConfirmModal({ file, meta, onConfirmed, onCancel, url, debug }: Props) {
  const urlMode = !file && !!url;
  const { settings } = useAppSettings();

  const [title, setTitle]       = useState(meta.title || "");
  const [authors, setAuthors]   = useState((meta.authors ?? []).join(", "));
  const [year, setYear]         = useState(meta.year?.toString() ?? "");
  const [doi, setDoi]           = useState(meta.doi ?? "");
  const [abstract, setAbstract] = useState(meta.abstract ?? "");
  const [documentType, setDocumentType] = useState<"paper" | "book" | "lecture_deck">("paper");
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<Paper | null>(null);
  const dupCheckTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [step, setStep]                   = useState<0 | 1 | 2 | 3>(settings.showSourceStep ? 0 : 1);
  const [uploadedPaper, setUploadedPaper] = useState<T_IngestOut | null>(null);

  // Step 2: summary prompt
  const [summaryInstructions, setSummaryInstructions] = useState(settings.defaultSummaryInstructions);

  // Step 0: source
  const [sourceType, setSourceType]     = useState<"person" | "source" | null>(null);
  const [sourcePerson, setSourcePerson] = useState<{id: string; name: string} | null>(null);
  const [sourceTag, setSourceTag]       = useState<string | null>(null);
  const [personQuery, setPersonQuery]   = useState("");
  const [allPeople, setAllPeople]       = useState<{id: string; name: string; affiliation?: string}[]>([]);
  const [peopleLoaded, setPeopleLoaded] = useState(false);
  const [creatingPerson, setCreatingPerson] = useState(false);
  const [showPersonDrop, setShowPersonDrop] = useState(false);
  const [showPersonForm, setShowPersonForm] = useState(false);
  const [newPersonAffiliation, setNewPersonAffiliation] = useState("");
  const [newPersonEmail, setNewPersonEmail] = useState("");

  // Project selector
  const [projects, setProjects] = useState<{id: string; name: string; description?: string}[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [suggestedProjectId, setSuggestedProjectId] = useState<string>("");
  useEffect(() => {
    listProjects().then((ps) => {
      setProjects(ps);
      // Auto-suggest: score each project by word overlap with paper title+abstract
      if (ps.length === 0) return;
      const paperText = `${meta.title ?? ""} ${meta.abstract ?? ""}`.toLowerCase();
      const words = paperText.match(/\b\w{4,}\b/g) ?? [];
      if (words.length === 0) return;
      let best = { id: "", score: 0 };
      for (const p of ps) {
        const pText = `${p.name} ${p.description ?? ""}`.toLowerCase();
        const hits = words.filter((w) => pText.includes(w)).length;
        if (hits > best.score) best = { id: p.id, score: hits };
      }
      if (best.score >= 3) setSuggestedProjectId(best.id);
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // PDF fallback (URL mode only) — download PDF and re-fill fields
  const [pdfFallbackLoading, setPdfFallbackLoading] = useState(false);
  const [pdfFallbackError, setPdfFallbackError]     = useState<string | null>(null);
  const [pdfFallbackDone, setPdfFallbackDone]       = useState(false);

  const handlePdfFallback = async () => {
    if (!url) return;
    setPdfFallbackLoading(true);
    setPdfFallbackError(null);
    try {
      const meta = await previewUrlPdf(url);
      if (meta.title && !title) setTitle(meta.title);
      if (meta.authors?.length && !authors) setAuthors(meta.authors.join(", "));
      if (meta.year && !year) setYear(String(meta.year));
      if (meta.doi && !doi) setDoi(meta.doi);
      if (meta.abstract && !abstract) setAbstract(meta.abstract);
      // Also fill if already empty even if we have some partial data
      if (meta.authors?.length && !authors) setAuthors(meta.authors.join(", "));
      if (meta.abstract && !abstract) setAbstract(meta.abstract);
      setPdfFallbackDone(true);
    } catch (e) {
      setPdfFallbackError(e instanceof Error ? e.message : "PDF extraction failed");
    } finally {
      setPdfFallbackLoading(false);
    }
  };

  // PDF-missing banner (URL mode only) — shown AFTER import on steps 3/4
  const [pdfMissing, setPdfMissing]     = useState(false);
  const [manualPdf, setManualPdf]       = useState<File | null>(null);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [pdfUploaded, setPdfUploaded]   = useState(false);

  // Manual PDF selected BEFORE import (when pdfFallbackError is set)
  const [preImportPdf, setPreImportPdf]           = useState<File | null>(null);
  const [preImportPdfLoading, setPreImportPdfLoading] = useState(false);

  const handlePreImportPdf = async (f: File) => {
    setPreImportPdf(f);
    setPreImportPdfLoading(true);
    try {
      const extracted = await parsePdf(f);
      if (extracted.authors?.length && !authors.trim()) setAuthors(extracted.authors.join(", "));
      if (extracted.abstract && !abstract.trim()) setAbstract(extracted.abstract);
      if (extracted.year && !year) setYear(String(extracted.year));
      if (extracted.doi && !doi) setDoi(extracted.doi);
    } catch { /* best-effort */ }
    finally { setPreImportPdfLoading(false); }
  };

  // Step 2: refs
  const [checkedRefs, setCheckedRefs] = useState<boolean[]>([]);
  const [savingRefs, setSavingRefs]   = useState(false);

  const source = SOURCE_LABELS[meta.metadata_source] ?? { label: meta.metadata_source, color: "bg-gray-100 text-gray-500" };

  // Debounced duplicate check whenever DOI or title changes
  useEffect(() => {
    if (dupCheckTimer.current) clearTimeout(dupCheckTimer.current);
    setDuplicate(null);
    dupCheckTimer.current = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        if (doi.trim()) params.set("doi", doi.trim());
        else if (title.trim()) params.set("title", title.trim());
        else return;
        const res = await apiFetch<{ duplicate: Paper | null }>(`/papers/check-duplicate?${params}`);
        setDuplicate(res.duplicate);
      } catch { /* silent */ }
    }, 600);
    return () => { if (dupCheckTimer.current) clearTimeout(dupCheckTimer.current); };
  }, [doi, title]);

  // Load people for autocomplete when person tab is opened
  useEffect(() => {
    if (sourceType === "person" && !peopleLoaded) {
      listPeople()
        .then((people) => { setAllPeople(people); setPeopleLoaded(true); })
        .catch(() => setPeopleLoaded(true));
    }
  }, [sourceType, peopleLoaded]);

  const filteredPeople = allPeople.filter((p) =>
    personQuery.trim() && p.name.toLowerCase().includes(personQuery.toLowerCase())
  );
  const showCreateOption = personQuery.trim().length > 1 &&
    !allPeople.some((p) => p.name.toLowerCase() === personQuery.toLowerCase());

  const handleSelectPerson = (person: {id: string; name: string}) => {
    setSourcePerson(person);
    setPersonQuery(person.name);
    setShowPersonDrop(false);
  };

  const handleCreatePerson = async () => {
    if (!personQuery.trim()) return;
    setCreatingPerson(true);
    setShowPersonDrop(false);
    try {
      const person = await getOrCreatePerson(
        personQuery.trim(),
        newPersonAffiliation.trim() || undefined,
        newPersonEmail.trim() || undefined,
      );
      setAllPeople((prev) => prev.find((p) => p.id === person.id) ? prev : [...prev, person]);
      handleSelectPerson(person);
      setShowPersonForm(false);
      setNewPersonAffiliation("");
      setNewPersonEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create person");
    } finally {
      setCreatingPerson(false);
    }
  };

  // Apply source link/tag after upload
  const applySource = async (paperId: string) => {
    if (sourceType === "person" && sourcePerson) {
      try { await linkPersonInvolves(paperId, sourcePerson.id, "shared_by"); } catch { /* best-effort */ }
      try { await applyTags(paperId, ["from-colleague"]); } catch { /* best-effort */ }
    } else if (sourceType === "source" && sourceTag) {
      try { await applyTags(paperId, [sourceTag]); } catch { /* best-effort */ }
    }
  };

  // ── After refs: call onConfirmed ──────────────────────────────────────────

  const goToTagStep = (paper: T_IngestOut) => {
    onConfirmed(paper);
  };

  // ── Step 1: upload ─────────────────────────────────────────────────────────

  const confirm = async () => {
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      let paper: T_IngestOut;
      if (urlMode) {
        const isDefault = summaryInstructions.trim() === settings.defaultSummaryInstructions.trim();
        paper = await ingestFromUrlFull(url!, selectedProjectId || undefined, debug, isDefault ? undefined : summaryInstructions);
        // If user provided a PDF manually before import, attach it now
        if (preImportPdf && paper.pdf_fetched === false) {
          try { await uploadPdfForPaper(paper.id, preImportPdf); } catch { /* non-fatal */ }
        }
      } else {
        const isDefault = summaryInstructions.trim() === settings.defaultSummaryInstructions.trim();
        paper = await uploadPdf(file!, title.trim(), selectedProjectId || undefined, undefined, isDefault ? undefined : summaryInstructions, debug, documentType !== "paper" ? documentType : undefined);
      }
      await applySource(paper.id);
      if (urlMode && paper.pdf_fetched === false) setPdfMissing(true);
      const hasRefs = paper.references_found && paper.references_found.length > 0;
      if (hasRefs && !settings.autoSaveReferences) {
        setUploadedPaper(paper);
        setCheckedRefs(paper.references_found.map(() => true));
        setStep(3);
      } else {
        // Auto-save all refs if setting is on, then go to tags
        if (hasRefs && settings.autoSaveReferences) {
          try { await saveReferences(paper.id, paper.references_found as Reference[]); } catch { /* best-effort */ }
        }
        goToTagStep(paper);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Upload failed";
      // 409 = duplicate detected server-side
      if (msg.includes("409")) {
        try {
          const detail = JSON.parse(msg.replace(/^API 409: /, ""));
          setError(`Duplicate: "${detail.existing_title}" already exists. Go to paper or upload anyway below.`);
          // Try to set duplicate info so banner appears
          setDuplicate({ id: detail.existing_id, title: detail.existing_title, created_at: "" });
        } catch {
          setError(msg);
        }
      } else {
        setError(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  // ── Manual PDF upload (when pdf_fetched === false) ─────────────────────────

  const uploadManualPdf = async () => {
    if (!manualPdf || !uploadedPaper) return;
    setUploadingPdf(true);
    try {
      await uploadPdfForPaper(uploadedPaper.id, manualPdf);
      setPdfUploaded(true);
      setPdfMissing(false);
    } catch (e) {
      alert(e instanceof Error ? e.message : "PDF upload failed");
    } finally {
      setUploadingPdf(false);
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
    goToTagStep(uploadedPaper);
  };

  // ── Render: Step 0 (source) ────────────────────────────────────────────────

  const SOURCE_OPTIONS = [
    { tag: "from-linkedin",       label: "LinkedIn",        icon: "in" },
    { tag: "from-twitter",        label: "Twitter / X",     icon: "𝕏"  },
    { tag: "from-email",          label: "Email",           icon: "✉"  },
    { tag: "from-conference",     label: "Conference",      icon: "🎤" },
    { tag: "from-newsletter",     label: "Newsletter",      icon: "📰" },
    { tag: "from-google-scholar", label: "Google Scholar",  icon: "𝓖"  },
  ];

  if (step === 0) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4">
          <ModalHeader step={0} title="How did you get this paper?" subtitle="Optionally track where you found it — helps build your knowledge graph." />

          <div className="px-6 py-5 space-y-4">
            {/* Mode tabs */}
            <div className="flex gap-2">
              <button
                onClick={() => { setSourceType("person"); setSourceTag(null); }}
                className={`flex-1 py-2 text-sm font-medium rounded-lg border transition-colors ${sourceType === "person" ? "bg-violet-600 text-white border-violet-600" : "border-gray-200 text-gray-600 hover:border-violet-400 hover:text-violet-600"}`}
              >
                From a person
              </button>
              <button
                onClick={() => { setSourceType("source"); setSourcePerson(null); setPersonQuery(""); }}
                className={`flex-1 py-2 text-sm font-medium rounded-lg border transition-colors ${sourceType === "source" ? "bg-violet-600 text-white border-violet-600" : "border-gray-200 text-gray-600 hover:border-violet-400 hover:text-violet-600"}`}
              >
                From a source
              </button>
            </div>

            {/* Person autocomplete */}
            {sourceType === "person" && (
              <div className="space-y-2">
                <div className="relative">
                  <input
                    autoFocus
                    value={personQuery}
                    onChange={(e) => {
                      setPersonQuery(e.target.value);
                      setSourcePerson(null);
                      setShowPersonForm(false);
                      setShowPersonDrop(true);
                    }}
                    onFocus={() => setShowPersonDrop(true)}
                    placeholder="Search or create a person…"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
                  />
                  {sourcePerson && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-violet-600 text-xs font-medium">✓ {sourcePerson.name}</span>
                  )}
                  {showPersonDrop && (filteredPeople.length > 0 || showCreateOption) && (
                    <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden max-h-48 overflow-y-auto">
                      {filteredPeople.map((p) => (
                        <button
                          key={p.id}
                          onMouseDown={() => handleSelectPerson(p)}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-violet-50 flex items-center gap-2"
                        >
                          <span className="w-6 h-6 rounded-full bg-violet-100 text-violet-600 text-xs flex items-center justify-center font-medium shrink-0">
                            {p.name[0]?.toUpperCase()}
                          </span>
                          <span>{p.name}</span>
                          {p.affiliation && <span className="text-xs text-gray-400 ml-auto">{p.affiliation}</span>}
                        </button>
                      ))}
                      {showCreateOption && (
                        <button
                          onMouseDown={(e) => { e.preventDefault(); setShowPersonDrop(false); setShowPersonForm(true); }}
                          className="w-full text-left px-3 py-2 text-sm text-violet-600 hover:bg-violet-50 flex items-center gap-2 border-t border-gray-100"
                        >
                          <span className="w-6 h-6 rounded-full border-2 border-dashed border-violet-400 text-violet-500 text-xs flex items-center justify-center shrink-0">+</span>
                          Create "{personQuery.trim()}"
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Inline person-details form */}
                {showPersonForm && !sourcePerson && (
                  <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 space-y-2">
                    <p className="text-xs font-medium text-violet-700">New person: <span className="font-semibold">{personQuery.trim()}</span></p>
                    <div className="space-y-1.5">
                      <input
                        autoFocus
                        value={newPersonAffiliation}
                        onChange={(e) => setNewPersonAffiliation(e.target.value)}
                        placeholder="Affiliation (e.g. MIT, Google Brain) — optional"
                        className="w-full border border-gray-200 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
                      />
                      <input
                        value={newPersonEmail}
                        onChange={(e) => setNewPersonEmail(e.target.value)}
                        placeholder="Email — optional"
                        type="email"
                        className="w-full border border-gray-200 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
                      />
                    </div>
                    <div className="flex gap-2 pt-0.5">
                      <button
                        onClick={handleCreatePerson}
                        disabled={creatingPerson}
                        className="px-3 py-1.5 text-xs font-medium bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
                      >
                        {creatingPerson ? "Creating…" : "Create person"}
                      </button>
                      <button
                        onClick={() => { setShowPersonForm(false); setNewPersonAffiliation(""); setNewPersonEmail(""); }}
                        className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Source grid */}
            {sourceType === "source" && (
              <div className="grid grid-cols-3 gap-2">
                {SOURCE_OPTIONS.map((opt) => (
                  <button
                    key={opt.tag}
                    onClick={() => setSourceTag(sourceTag === opt.tag ? null : opt.tag)}
                    className={`py-2.5 px-3 rounded-lg border text-sm font-medium flex flex-col items-center gap-1 transition-colors ${
                      sourceTag === opt.tag
                        ? "bg-violet-600 border-violet-600 text-white"
                        : "border-gray-200 text-gray-600 hover:border-violet-400 hover:text-violet-600"
                    }`}
                  >
                    <span className="text-base leading-none">{opt.icon}</span>
                    <span className="text-xs">{opt.label}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Nothing selected yet — placeholder */}
            {!sourceType && (
              <p className="text-xs text-gray-400 text-center py-2">Select an option above, or skip to continue.</p>
            )}

            {error && (
              <p className="text-xs text-red-600">{error}</p>
            )}
          </div>

          <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
            <button
              onClick={onCancel}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            >
              Cancel
            </button>
            <button
              onClick={() => { setSourceType(null); setSourcePerson(null); setSourceTag(null); setStep(1); }}
              className="px-4 py-2 text-sm text-gray-500 hover:text-gray-800"
            >
              Skip
            </button>
            <button
              onClick={() => setStep(1)}
              disabled={
                (sourceType === "person" && !sourcePerson) ||
                (sourceType === "source" && !sourceTag)
              }
              className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50"
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Step 2 (summary prompt) ────────────────────────────────────────

  if (step === 2) {
    const isModified = summaryInstructions.trim() !== settings.defaultSummaryInstructions.trim();
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
          <ModalHeader step={2} title="AI Summary Prompt" subtitle={urlMode ? "PDF will be downloaded automatically (arXiv/bioRxiv). Summary uses full text if available, otherwise abstract." : "Customize the summary instructions for this paper. Change your default in Settings."} />

          <div className="px-6 py-4">
            <textarea
              value={summaryInstructions}
              onChange={(e) => setSummaryInstructions(e.target.value)}
              rows={10}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none"
            />
            {isModified && (
              <button
                onClick={() => setSummaryInstructions(settings.defaultSummaryInstructions)}
                className="mt-1.5 text-xs text-gray-400 hover:text-violet-600 transition-colors"
              >
                ↺ Reset to saved default
              </button>
            )}
            <p className="mt-2 text-xs text-gray-400">
              The paper title and full text are appended automatically — no need to include them in the prompt.
            </p>
          </div>

          <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
            <button onClick={() => setStep(1)} disabled={saving} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50">← Back</button>
            <button onClick={confirm} disabled={saving || !title.trim()}
              className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2">
              {saving && <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" /></svg>}
              {saving ? (urlMode ? "Importing…" : "Uploading…") : (urlMode ? "Import →" : "Upload →")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Step 3 (refs) ───────────────────────────────────────────────────

  const pdfMissingBanner = pdfMissing ? (
    <div className="mx-6 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
      <p className="text-xs font-medium text-amber-800 mb-1.5">PDF not downloaded automatically</p>
      <p className="text-xs text-amber-700 mb-2">
        The PDF couldn't be fetched (Cloudflare-protected or paywalled).{" "}
        {url && <a href={url} target="_blank" rel="noreferrer" className="underline font-medium hover:text-amber-900">Open paper page ↗</a>}
        {" "}— download the PDF manually and upload it below to enable full-text chat and search.
      </p>
      {pdfUploaded ? (
        <p className="text-xs text-green-700 font-medium">PDF uploaded successfully.</p>
      ) : (
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setManualPdf(e.target.files?.[0] ?? null)}
            className="text-xs text-gray-600 file:mr-2 file:py-1 file:px-2 file:text-xs file:border file:border-gray-200 file:rounded file:bg-white file:text-gray-700 hover:file:bg-gray-50"
          />
          {manualPdf && (
            <button
              onClick={uploadManualPdf}
              disabled={uploadingPdf}
              className="px-2.5 py-1 text-xs bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1"
            >
              {uploadingPdf && <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>}
              {uploadingPdf ? "Uploading…" : "Upload PDF"}
            </button>
          )}
        </div>
      )}
    </div>
  ) : null;

  if (step === 3 && uploadedPaper) {
    const refs = uploadedPaper.references_found;
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
          <ModalHeader step={3} title="Save references?" subtitle={`Found ${refs.length} reference${refs.length !== 1 ? "s" : ""} — uncheck any to skip.`} />
          {pdfMissingBanner}
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
          <Field label="Add to project">
            {projects.length === 0 ? (
              <p className="text-xs text-gray-400 italic">No projects yet — create one in the Projects page.</p>
            ) : (
              <div className="space-y-1.5">
                {suggestedProjectId && !selectedProjectId && (
                  <div className="flex items-center gap-2 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2">
                    <span className="text-xs text-violet-700 flex-1">
                      ✦ Suggested: <strong>{projects.find((p) => p.id === suggestedProjectId)?.name}</strong>
                    </span>
                    <button
                      onClick={() => setSelectedProjectId(suggestedProjectId)}
                      className="text-xs bg-violet-600 text-white px-2.5 py-0.5 rounded-full hover:bg-violet-700 font-medium"
                    >
                      Add
                    </button>
                    <button onClick={() => setSuggestedProjectId("")} className="text-violet-400 hover:text-violet-700 text-xs">✕</button>
                  </div>
                )}
                <select
                  value={selectedProjectId}
                  onChange={(e) => { setSelectedProjectId(e.target.value); setSuggestedProjectId(""); }}
                  className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white text-gray-700"
                >
                  <option value="">— None —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
            )}
          </Field>
          {!urlMode && (
            <Field label="Document type">
              <div className="flex gap-2">
                {([ ["paper", "📄 Paper"], ["book", "📚 Book"], ["lecture_deck", "🎓 Lecture deck"] ] as const).map(([val, label]) => (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setDocumentType(val)}
                    className={`flex-1 py-1.5 px-2 text-xs font-medium rounded-lg border transition-colors ${documentType === val ? "bg-violet-600 text-white border-violet-600" : "border-gray-200 text-gray-600 hover:border-violet-400 hover:text-violet-600"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {documentType !== "paper" && (
                <p className="mt-1.5 text-xs text-violet-600">
                  📌 References & figure extraction will be skipped. After upload, use the <strong>Chapters</strong> tab to auto-detect chapter structure and summaries.
                </p>
              )}
            </Field>
          )}
          {/* PDF attachment — always available in URL mode */}
          {urlMode && (
            <div className={`rounded-lg border px-3 py-2.5 space-y-1.5 ${
              !authors.trim() || !abstract.trim()
                ? "border-amber-200 bg-amber-50"
                : "border-gray-200 bg-gray-50"
            }`}>
              {(!authors.trim() || !abstract.trim()) && (
                <p className="text-xs font-medium text-amber-800">
                  {!authors.trim() && !abstract.trim()
                    ? "Authors and abstract are missing."
                    : !authors.trim() ? "Authors are missing." : "Abstract is missing."}
                  {" "}Try extracting them from the PDF.
                </p>
              )}
              {pdfFallbackDone ? (
                <p className="text-xs text-green-700 font-medium">✓ Fields filled from PDF extraction.</p>
              ) : pdfFallbackError ? (
                <div className="space-y-2">
                  <p className="text-xs text-red-700">
                    Auto-download blocked (Cloudflare/paywalled).{" "}
                    <a href={url} target="_blank" rel="noreferrer" className="underline font-medium hover:text-red-900">
                      Open paper page ↗
                    </a>
                    {" "}— download the PDF manually and upload it here:
                  </p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="file"
                        accept="application/pdf"
                        className="hidden"
                        onChange={(e) => { const f = e.target.files?.[0]; if (f) handlePreImportPdf(f); }}
                      />
                      <span className="px-2.5 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 cursor-pointer flex items-center gap-1.5">
                        {preImportPdfLoading && (
                          <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                          </svg>
                        )}
                        {preImportPdfLoading ? "Extracting…" : preImportPdf ? `✓ ${preImportPdf.name}` : "Upload PDF"}
                      </span>
                    </label>
                    {preImportPdf && <p className="text-xs text-green-700">PDF ready — will be attached on import.</p>}
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={handlePdfFallback}
                    disabled={pdfFallbackLoading}
                    className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
                  >
                    {pdfFallbackLoading && (
                      <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                      </svg>
                    )}
                    {pdfFallbackLoading ? "Downloading…" : "↓ Fetch PDF automatically"}
                  </button>
                  <span className="text-xs text-gray-400">or</span>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="file"
                      accept="application/pdf"
                      className="hidden"
                      onChange={(e) => { const f = e.target.files?.[0]; if (f) handlePreImportPdf(f); }}
                    />
                    <span className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:border-violet-400 hover:text-violet-700 transition-colors cursor-pointer">
                      {preImportPdfLoading && (
                        <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                        </svg>
                      )}
                      {preImportPdfLoading ? "Reading…" : preImportPdf ? `✓ ${preImportPdf.name}` : "Upload PDF manually"}
                    </span>
                  </label>
                  {preImportPdf && <p className="text-xs text-green-700">PDF will be attached on import.</p>}
                </div>
              )}
            </div>
          )}

          {duplicate && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 text-xs">
              <span className="text-amber-500 mt-0.5 shrink-0">⚠</span>
              <div className="flex-1 min-w-0">
                <span className="font-medium text-amber-800">Possible duplicate — </span>
                <span className="text-amber-700">"{duplicate.title}" is already in your library.</span>
              </div>
              <a
                href={`/paper/${duplicate.id}`}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 text-amber-700 underline hover:text-amber-900 font-medium"
              >
                View →
              </a>
            </div>
          )}
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button onClick={onCancel} disabled={saving} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50">Cancel</button>
          {settings.showSummaryPromptStep ? (
            <button onClick={() => setStep(2)} disabled={!title.trim()}
              className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50">
              Next →
            </button>
          ) : (
            <button onClick={confirm} disabled={saving || !title.trim()}
              className="px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2">
              {saving && <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" /></svg>}
              {saving ? "Importing…" : urlMode ? "Import →" : "Upload →"}
            </button>
          )}
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
      {[0, 1, 2, 3].map((n) => (
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
