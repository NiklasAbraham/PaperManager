import { useState, useEffect, useRef } from "react";
import { useAppSettings, type AppSettings, DEFAULT_SUMMARY_INSTRUCTIONS } from "../contexts/SettingsContext";
import { apiFetch, deleteDebugPapers, countDebugPapers, exportRdf, exportCsv, importRdf, clearPapers, seedDefaults, listOllamaModels, deleteUser, renameUser } from "../api/client";

type BackfillResult = { processed: number; skipped: number; errors: number };
type BackfillOp = "topics" | "summary" | "figures" | "claims" | "embeddings";
type BackfillState = { status: "idle" | "running" | "done" | "error"; result?: BackfillResult };

export default function Settings() {
  const { settings, update, reset } = useAppSettings();
  const [confirmReset, setConfirmReset] = useState(false);
  const [exporting, setExporting] = useState<"bibtex" | "json" | "rdf" | "csv" | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<Record<string, number> | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const rdfInputRef = useRef<HTMLInputElement>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearResult, setClearResult] = useState<Record<string, number> | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [seedResult, setSeedResult] = useState<{ seeded: number } | null>(null);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [debugCount, setDebugCount] = useState<number | null>(null);
  const [debugDeleting, setDebugDeleting] = useState(false);
  const [debugDeleteResult, setDebugDeleteResult] = useState<{ deleted: number; figures_deleted: number } | null>(null);
  const [confirmDebugDelete, setConfirmDebugDelete] = useState(false);

  // Teammates
  interface UserInfo { name: string; paper_count: number; conversation_count: number }
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [renamingUser, setRenamingUser] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteUser, setConfirmDeleteUser] = useState<string | null>(null);

  useEffect(() => {
    countDebugPapers().then(setDebugCount).catch(() => setDebugCount(null));
    listOllamaModels().then(setOllamaModels).catch(() => setOllamaModels([]));
    apiFetch<UserInfo[]>("/users").then(setUsers).catch(() => {});
  }, []);
  const [backfill, setBackfill] = useState<Record<BackfillOp, BackfillState>>({
    topics:     { status: "idle" },
    summary:    { status: "idle" },
    figures:    { status: "idle" },
    claims:     { status: "idle" },
    embeddings: { status: "idle" },
  });

  const runBackfill = async (op: BackfillOp) => {
    setBackfill((s) => ({ ...s, [op]: { status: "running" } }));
    try {
      const result = await apiFetch<BackfillResult>(`/backfill/${op}`, { method: "POST" });
      setBackfill((s) => ({ ...s, [op]: { status: "done", result } }));
    } catch {
      setBackfill((s) => ({ ...s, [op]: { status: "error" } }));
    }
  };

  const exportBibtex = async () => {
    setExporting("bibtex");
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/export/bibtex`);
      const text = await res.text();
      download(text, "papers.bib", "text/plain");
    } finally {
      setExporting(null);
    }
  };

  const exportJson = async () => {
    setExporting("json");
    try {
      const papers = await apiFetch<unknown[]>("/papers");
      download(JSON.stringify(papers, null, 2), "papers.json", "application/json");
    } finally {
      setExporting(null);
    }
  };

  const handleExportRdf = async () => {
    setExporting("rdf");
    try { await exportRdf(); } finally { setExporting(null); }
  };

  const handleExportCsv = async () => {
    setExporting("csv");
    try { await exportCsv(); } finally { setExporting(null); }
  };

  const handleImportRdf = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    setImportError(null);
    try {
      const result = await importRdf(file);
      setImportResult(result.imported);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
      if (rdfInputRef.current) rdfInputRef.current.value = "";
    }
  };

  const handleClearPapers = async () => {
    setClearing(true);
    try {
      const result = await clearPapers();
      setClearResult(result);
      setConfirmClear(false);
    } catch { /* best-effort */ }
    setClearing(false);
  };

  const handleSeedDefaults = async () => {
    setSeeding(true);
    try {
      const result = await seedDefaults();
      setSeedResult(result);
    } catch { /* best-effort */ }
    setSeeding(false);
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-10 space-y-10">
      <h1 className="text-xl font-bold text-gray-900">Settings</h1>

      {/* ── Library ── */}
      <Section title="Library" description="Controls how papers are displayed and sorted by default.">
        <Row label="Default sort" description="Order papers are shown when no search is active.">
          <Select
            value={settings.defaultSort}
            options={[
              { value: "date_desc",      label: "Newest added" },
              { value: "date_asc",       label: "Oldest added" },
              { value: "year_desc",      label: "Year (newest first)" },
              { value: "year_asc",       label: "Year (oldest first)" },
              { value: "title_asc",      label: "Title (A → Z)" },
              { value: "rating_desc",    label: "Rating (highest first)" },
              { value: "citations_desc", label: "Citations (most first)" },
            ]}
            onChange={(v) => update({ defaultSort: v as AppSettings["defaultSort"] })}
          />
        </Row>

        <Row label="Papers per page" description="Set to 'All' to disable pagination.">
          <Select
            value={String(settings.papersPerPage)}
            options={[
              { value: "20",  label: "20" },
              { value: "50",  label: "50" },
              { value: "100", label: "100" },
              { value: "0",   label: "All" },
            ]}
            onChange={(v) => update({ papersPerPage: Number(v) as AppSettings["papersPerPage"] })}
          />
        </Row>

        <Row label="Abstract preview" description="Show the first lines of a paper's summary on each card.">
          <Toggle
            value={settings.showAbstractPreview}
            onChange={(v) => update({ showAbstractPreview: v })}
          />
        </Row>

        <Row label="Figure caption method" description="How figures are detected and captioned at upload time. Docling uses a neural layout model (best quality).">
          <ToggleGroup
            value={settings.figureCaptionMethod}
            options={[
              { value: "docling", label: "Docling (AI layout)" },
              { value: "ollama", label: "Ollama (text)" },
              { value: "claude-vision", label: "Claude Vision" },
            ]}
            onChange={(v) => update({ figureCaptionMethod: v as AppSettings["figureCaptionMethod"] })}
          />
        </Row>
      </Section>

      {/* ── Books & Chapters ── */}
      <Section title="Books & Chapters" description="Settings for chapter detection and AI summarisation.">
        <Row label="Summary model" description="Model used to generate per-chapter summaries. Claude models use the personal API key; Ollama models run locally.">
          {(() => {
            const CLAUDE_OPTIONS = [
              { value: "claude-opus-4-6",         label: "Claude Opus 4.6" },
              { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
            ];
            const localOptions = ollamaModels.map((m) => ({ value: m, label: m }));
            const allOptions = [
              ...CLAUDE_OPTIONS,
              ...(localOptions.length > 0 ? [{ value: "─────────", label: "─────────" }, ...localOptions] : []),
              // keep current value if it's not in any known list
              ...(!CLAUDE_OPTIONS.some(o => o.value === settings.chapterSummaryModel) && !ollamaModels.includes(settings.chapterSummaryModel)
                ? [{ value: settings.chapterSummaryModel, label: settings.chapterSummaryModel }]
                : []),
            ];
            return (
              <Select
                value={settings.chapterSummaryModel}
                options={allOptions}
                onChange={(v) => { if (v !== "─────────") update({ chapterSummaryModel: v }); }}
              />
            );
          })()}
        </Row>
      </Section>

      {/* ── Upload Workflow ── */}
      <Section title="Upload Workflow" description="Control which steps appear when you upload a paper.">
        <Row label="Source step" description='"How did you get this paper?" — track people or channels that shared it.'>
          <Toggle
            value={settings.showSourceStep}
            onChange={(v) => update({ showSourceStep: v })}
          />
        </Row>

        <Row label="Summary prompt step" description="Show and optionally edit the AI summary prompt before uploading.">
          <Toggle
            value={settings.showSummaryPromptStep}
            onChange={(v) => update({ showSummaryPromptStep: v })}
          />
        </Row>

        <Row label="Auto-save all references" description="Skip the references review step and save every found reference automatically.">
          <Toggle
            value={settings.autoSaveReferences}
            onChange={(v) => update({ autoSaveReferences: v })}
          />
        </Row>

        <div className="px-5 py-4 space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-800">Default summary instructions</p>
              <p className="text-xs text-gray-400 mt-0.5">Pre-filled in the summary prompt step on every upload.</p>
            </div>
            {settings.defaultSummaryInstructions !== DEFAULT_SUMMARY_INSTRUCTIONS && (
              <button
                onClick={() => update({ defaultSummaryInstructions: DEFAULT_SUMMARY_INSTRUCTIONS })}
                className="shrink-0 text-xs text-gray-400 hover:text-violet-600 transition-colors ml-4"
              >
                ↺ Reset
              </button>
            )}
          </div>
          <textarea
            value={settings.defaultSummaryInstructions}
            onChange={(e) => update({ defaultSummaryInstructions: e.target.value })}
            rows={8}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none"
          />
        </div>
      </Section>

      {/* ── Knowledge Chat ── */}
      <Section title="Knowledge Chat" description="Controls the default behaviour of the cross-library chat interface.">
        <Row label="Default model" description="Pre-selected model when a new conversation is opened. Can be overridden per-session in the chat header.">
          <ToggleGroup
            value={settings.knowledgeChatDefaultModel}
            options={[
              { value: "claude",      label: "Claude" },
              { value: "claude-work", label: "Claude (Work)" },
              { value: "ollama",      label: "Ollama" },
            ]}
            onChange={(v) => update({ knowledgeChatDefaultModel: v as AppSettings["knowledgeChatDefaultModel"] })}
          />
        </Row>

        <Row label="Web search by default" description="Pre-enable the web search toggle when starting a new conversation. Adds recent context from the web to every answer.">
          <Toggle
            value={settings.knowledgeChatUseWeb}
            onChange={(v) => update({ knowledgeChatUseWeb: v })}
          />
        </Row>

        <Row
          label="Auto-route large context to Opus"
          description={`When the total context (system prompt + papers + history) exceeds the threshold, switch from Sonnet to Claude Opus 4.6 for better multi-document reasoning. Current threshold: ${settings.knowledgeChatOpusThreshold.toLocaleString()} tokens.`}
        >
          <div className="flex items-center gap-3">
            <input
              type="range" min="10000" max="100000" step="5000"
              value={settings.knowledgeChatOpusThreshold}
              onChange={(e) => update({ knowledgeChatOpusThreshold: +e.target.value })}
              className="w-36 accent-violet-600"
            />
            <span className="text-xs text-gray-500 font-mono w-16 text-right">
              {(settings.knowledgeChatOpusThreshold / 1000).toFixed(0)}k tok
            </span>
          </div>
        </Row>

        <Row
          label="Compaction window"
          description={`Sliding-window compaction keeps the last N messages verbatim and replaces the rest with a structured working-memory block. Current: keep last ${settings.compactionKeepLastN} messages.`}
        >
          <div className="flex items-center gap-3">
            <input
              type="range" min="2" max="20" step="2"
              value={settings.compactionKeepLastN}
              onChange={(e) => update({ compactionKeepLastN: +e.target.value })}
              className="w-32 accent-violet-600"
            />
            <span className="text-xs text-gray-500 font-mono w-8 text-right">
              {settings.compactionKeepLastN}
            </span>
          </div>
        </Row>
      </Section>

      {/* ── Inference ── */}
      <Section title="Inference" description="Controls which AI enrichment steps run when a paper is uploaded.">
        <Row label="Extract claims on upload" description="Automatically extract typed intellectual claims (findings, methods, limitations) from every paper's text using Claude Haiku. Adds Claim nodes to the graph, queryable in Knowledge Chat.">
          <Toggle
            value={settings.autoExtractClaims}
            onChange={(v) => update({ autoExtractClaims: v })}
          />
        </Row>

        <Row label="Claims extraction model" description="Model used to extract claims. Claude Haiku is fast and cheap; Ollama runs locally.">
          {(() => {
            const CLAUDE_OPTIONS = [
              { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
              { value: "claude-opus-4-6",           label: "Claude Opus 4.6" },
            ];
            const localOptions = ollamaModels.map((m) => ({ value: m, label: m }));
            const allOptions = [
              ...CLAUDE_OPTIONS,
              ...(localOptions.length > 0
                ? [{ value: "─────────", label: "─────────" }, ...localOptions]
                : []),
              ...(!CLAUDE_OPTIONS.some((o) => o.value === settings.claimsModel) && !ollamaModels.includes(settings.claimsModel)
                ? [{ value: settings.claimsModel, label: settings.claimsModel }]
                : []),
            ];
            return (
              <Select
                value={settings.claimsModel}
                options={allOptions}
                onChange={(v) => { if (v !== "─────────") update({ claimsModel: v }); }}
              />
            );
          })()}
        </Row>

        <Row label="Generate embeddings on upload" description="Compute a 768-dim vector embedding for each paper using local Ollama (nomic-embed-text) after upload. Enables semantic search in Knowledge Chat. Requires Ollama to be running.">
          <Toggle
            value={settings.generateEmbeddingsOnUpload}
            onChange={(v) => update({ generateEmbeddingsOnUpload: v })}
          />
        </Row>
      </Section>

      {/* ── Graph ── */}
      <Section title="Graph" description="Default state when the graph view is opened.">
        <Row label="Default mode" description="Which nodes to show by default.">
          <ToggleGroup
            value={settings.defaultGraphMode}
            options={[
              { value: "full",   label: "All nodes" },
              { value: "papers", label: "Papers + People + Topics" },
            ]}
            onChange={(v) => update({ defaultGraphMode: v as AppSettings["defaultGraphMode"] })}
          />
        </Row>

        <Row label="Default node size" description={`Current: ${settings.graphNodeSize}`}>
          <input
            type="range" min="6" max="36" step="1"
            value={settings.graphNodeSize}
            onChange={(e) => update({ graphNodeSize: +e.target.value })}
            className="w-40 accent-violet-600"
          />
        </Row>

        <Row label="Show node labels" description="Display node titles on the graph canvas.">
          <Toggle
            value={settings.graphShowNodeLabels}
            onChange={(v) => update({ graphShowNodeLabels: v })}
          />
        </Row>

        <Row label="Show edge labels" description="Display relationship types on edges.">
          <Toggle
            value={settings.graphShowEdgeLabels}
            onChange={(v) => update({ graphShowEdgeLabels: v })}
          />
        </Row>
      </Section>

      {/* ── Export ── */}
      <Section title="Export" description="Download your library in a portable format.">
        <Row label="BibTeX" description="Standard citation format, compatible with LaTeX and most reference managers.">
          <button
            onClick={exportBibtex}
            disabled={exporting === "bibtex"}
            className="px-4 py-1.5 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {exporting === "bibtex" ? "Exporting…" : "Download .bib"}
          </button>
        </Row>
        <Row label="JSON" description="Full paper metadata as a JSON array.">
          <button
            onClick={exportJson}
            disabled={exporting === "json"}
            className="px-4 py-1.5 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {exporting === "json" ? "Exporting…" : "Download .json"}
          </button>
        </Row>
        <Row label="RDF / Turtle" description="Full graph export (nodes + relationships) as a .ttl file. Can be re-imported without creating duplicates.">
          <button
            onClick={handleExportRdf}
            disabled={exporting === "rdf"}
            className="px-4 py-1.5 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {exporting === "rdf" ? "Exporting…" : "Download .ttl"}
          </button>
        </Row>
        <Row label="CSV (ZIP)" description="All nodes and edges as CSV files, bundled in a ZIP archive.">
          <button
            onClick={handleExportCsv}
            disabled={exporting === "csv"}
            className="px-4 py-1.5 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {exporting === "csv" ? "Exporting…" : "Download .zip"}
          </button>
        </Row>
        <div className="px-5 py-4 space-y-2">
          <div>
            <p className="text-sm font-medium text-gray-800">Import RDF / Turtle</p>
            <p className="text-xs text-gray-400 mt-0.5">Upload a .ttl file exported from this app. Uses MERGE — safe to run on a populated database (no duplicates).</p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <input
              ref={rdfInputRef}
              type="file"
              accept=".ttl"
              onChange={handleImportRdf}
              disabled={importing}
              className="text-sm text-gray-600 file:mr-2 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100 disabled:opacity-50"
            />
            {importing && <span className="text-xs text-gray-500">Importing…</span>}
            {importResult && (
              <span className="text-xs text-green-700 font-medium">
                Imported: {Object.entries(importResult).map(([k, v]) => `${v} ${k}`).join(", ")}
              </span>
            )}
            {importError && <span className="text-xs text-red-600">{importError}</span>}
          </div>
        </div>
      </Section>

      {/* ── Library Maintenance ── */}
      <Section title="Library Maintenance" description="Apply AI enrichment to papers already in your library. Each operation skips papers that already have the data.">
        <BackfillRow
          label="Suggest topics"
          description="Run AI topic suggestion on papers that have no topics yet."
          state={backfill.topics}
          onRun={() => runBackfill("topics")}
        />
        <BackfillRow
          label="Generate summaries"
          description="Generate AI summaries for papers with extracted text but no summary yet."
          state={backfill.summary}
          onRun={() => runBackfill("summary")}
        />
        <BackfillRow
          label="Extract figures"
          description="Extract figures from PDFs for papers that have no figures yet."
          state={backfill.figures}
          onRun={() => runBackfill("figures")}
        />
        <BackfillRow
          label="Extract claims"
          description="Extract typed intellectual claims (findings, methods, limitations) for papers that have raw text but no claims yet. Uses Claude Haiku."
          state={backfill.claims}
          onRun={() => runBackfill("claims")}
        />
        <BackfillRow
          label="Generate embeddings"
          description="Compute vector embeddings for papers that have no embedding yet using local Ollama (nomic-embed-text). Required for semantic search in Knowledge Chat."
          state={backfill.embeddings}
          onRun={() => runBackfill("embeddings")}
        />
      </Section>

      {/* ── Teammates ── */}
      <Section title="Teammates" description="People who use this library. New members can join by entering their name in the top-right corner.">
        {users.length === 0 ? (
          <div className="px-5 py-4 text-sm text-gray-400">No teammates yet.</div>
        ) : (
          users.map((u) => (
            <div key={u.name} className="flex items-center justify-between gap-4 px-5 py-3">
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-7 h-7 rounded-full bg-violet-100 text-violet-700 flex items-center justify-center text-xs font-bold shrink-0">
                  {u.name[0].toUpperCase()}
                </span>
                {renamingUser === u.name ? (
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      const newName = renameValue.trim();
                      if (!newName || newName === u.name) { setRenamingUser(null); return; }
                      try {
                        await renameUser(u.name, newName);
                        setUsers((prev) => prev.map((x) => x.name === u.name ? { ...x, name: newName } : x));
                      } catch { /* best-effort */ }
                      setRenamingUser(null);
                    }}
                    className="flex items-center gap-2"
                  >
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      className="border border-violet-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
                    />
                    <button type="submit" className="text-xs text-violet-600 font-medium hover:text-violet-800">Save</button>
                    <button type="button" onClick={() => setRenamingUser(null)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                  </form>
                ) : (
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{u.name}</p>
                    <p className="text-xs text-gray-400">{u.conversation_count} conversations · {u.paper_count} papers added</p>
                  </div>
                )}
              </div>
              {renamingUser !== u.name && (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => { setRenamingUser(u.name); setRenameValue(u.name); setConfirmDeleteUser(null); }}
                    className="text-xs text-gray-400 hover:text-violet-600 transition-colors"
                  >
                    Rename
                  </button>
                  {confirmDeleteUser === u.name ? (
                    <>
                      <span className="text-xs text-red-500">Delete?</span>
                      <button
                        onClick={async () => {
                          try {
                            await deleteUser(u.name);
                            setUsers((prev) => prev.filter((x) => x.name !== u.name));
                          } catch { /* best-effort */ }
                          setConfirmDeleteUser(null);
                        }}
                        className="text-xs text-red-600 font-medium hover:text-red-800"
                      >Yes</button>
                      <button onClick={() => setConfirmDeleteUser(null)} className="text-xs text-gray-400 hover:text-gray-600">No</button>
                    </>
                  ) : (
                    <button
                      onClick={() => { setConfirmDeleteUser(u.name); setRenamingUser(null); }}
                      className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                    >
                      Delete
                    </button>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </Section>

      {/* ── Debug Mode ── */}
      <Section title="Debug Mode" description="Papers imported while debug mode is ON are tagged 'debug'. Use this to bulk-delete test imports.">
        <Row label="Debug papers in library" description={
          debugCount === null ? "Counting…" :
          debugCount === 0 ? "No debug papers in library." :
          `${debugCount} paper${debugCount !== 1 ? "s" : ""} tagged 'debug' in library.`
        }>
          {debugDeleteResult ? (
            <p className="text-xs text-green-700 font-medium">
              Deleted {debugDeleteResult.deleted} paper{debugDeleteResult.deleted !== 1 ? "s" : ""} and {debugDeleteResult.figures_deleted} figure{debugDeleteResult.figures_deleted !== 1 ? "s" : ""}.
            </p>
          ) : confirmDebugDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-red-500">Delete all {debugCount} debug paper{debugCount !== 1 ? "s" : ""}?</span>
              <button
                onClick={async () => {
                  setDebugDeleting(true);
                  try {
                    const result = await deleteDebugPapers();
                    setDebugDeleteResult(result);
                    setDebugCount(0);
                  } catch { /* best-effort */ }
                  setDebugDeleting(false);
                  setConfirmDebugDelete(false);
                }}
                disabled={debugDeleting}
                className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {debugDeleting ? "Deleting…" : "Yes, delete all"}
              </button>
              <button
                onClick={() => setConfirmDebugDelete(false)}
                className="px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDebugDelete(true)}
              disabled={(debugCount ?? 0) === 0}
              className="px-4 py-1.5 text-sm font-medium bg-gray-100 text-gray-700 rounded-lg hover:bg-red-50 hover:text-red-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Delete all debug papers
            </button>
          )}
        </Row>
      </Section>

      {/* ── Data ── */}
      <Section title="Data" description="Danger zone — these actions cannot be undone.">
        <Row label="Reset settings" description="Restore all settings to their default values.">
          {confirmReset ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-red-500">Sure?</span>
              <button
                onClick={() => { reset(); setConfirmReset(false); }}
                className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                Yes, reset
              </button>
              <button
                onClick={() => setConfirmReset(false)}
                className="px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmReset(true)}
              className="px-4 py-1.5 text-sm font-medium bg-gray-100 text-gray-700 rounded-lg hover:bg-red-50 hover:text-red-600 transition-colors"
            >
              Reset to defaults
            </button>
          )}
        </Row>
        <Row
          label="Clear all papers"
          description="Delete all papers, people, notes, figures, and projects from the database. Tags and topics are preserved."
        >
          {clearResult ? (
            <p className="text-xs text-green-700 font-medium">
              Deleted: {Object.entries(clearResult).map(([k, v]) => `${v} ${k}`).join(", ")}
            </p>
          ) : confirmClear ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-red-500">This is irreversible. Are you sure?</span>
              <button
                onClick={handleClearPapers}
                disabled={clearing}
                className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {clearing ? "Deleting…" : "Yes, delete all"}
              </button>
              <button
                onClick={() => setConfirmClear(false)}
                className="px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmClear(true)}
              className="px-4 py-1.5 text-sm font-medium bg-gray-100 text-gray-700 rounded-lg hover:bg-red-50 hover:text-red-600 transition-colors"
            >
              Clear all papers
            </button>
          )}
        </Row>
        <Row
          label="Seed default data"
          description="Re-populate the default tags (pdf-upload, from-url, from-references, debug, etc.). Safe to run at any time — idempotent."
        >
          {seedResult ? (
            <p className="text-xs text-green-700 font-medium">Seeded {seedResult.seeded} default tags.</p>
          ) : (
            <button
              onClick={handleSeedDefaults}
              disabled={seeding}
              className="px-4 py-1.5 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {seeding ? "Seeding…" : "Seed defaults"}
            </button>
          )}
        </Row>
      </Section>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function download(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Layout components ────────────────────────────────────────────────────────

function BackfillRow({ label, description, state, onRun }: {
  label: string;
  description: string;
  state: BackfillState;
  onRun: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-6 px-5 py-4">
      <div>
        <p className="text-sm font-medium text-gray-800">{label}</p>
        <p className="text-xs text-gray-400 mt-0.5">{description}</p>
        {state.status === "done" && state.result && (
          <p className="text-xs text-green-600 mt-1">
            Done — {state.result.processed} processed, {state.result.skipped} skipped
            {state.result.errors > 0 && `, ${state.result.errors} errors`}
          </p>
        )}
        {state.status === "error" && (
          <p className="text-xs text-red-500 mt-1">Failed — check backend logs</p>
        )}
      </div>
      <button
        onClick={onRun}
        disabled={state.status === "running"}
        className="shrink-0 px-4 py-1.5 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
      >
        {state.status === "running" ? "Running…" : state.status === "done" ? "Run again" : "Run"}
      </button>
    </div>
  );
}

function Section({ title, description, children }: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
        {children}
      </div>
    </div>
  );
}

function Row({ label, description, children }: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-6 px-5 py-4">
      <div>
        <p className="text-sm font-medium text-gray-800">{label}</p>
        {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`relative w-9 h-5 rounded-full transition-colors ${value ? "bg-violet-600" : "bg-gray-300"}`}
    >
      <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${value ? "translate-x-4" : "translate-x-0"}`} />
    </button>
  );
}

function ToggleGroup({ value, options, onChange }: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex border border-gray-200 rounded-lg overflow-hidden text-xs font-medium">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1.5 transition-colors ${
            value === opt.value
              ? "bg-violet-600 text-white"
              : "bg-white text-gray-600 hover:bg-gray-50"
          } ${options.indexOf(opt) > 0 ? "border-l border-gray-200" : ""}`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Select({ value, options, onChange }: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}
