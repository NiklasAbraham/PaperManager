import { useState, useEffect, useRef } from "react";
import { useAppSettings, type AppSettings, DEFAULT_SUMMARY_INSTRUCTIONS } from "../contexts/SettingsContext";
import { apiFetch, deleteDebugPapers, countDebugPapers, exportRdf, exportCsv, importRdf, clearPapers, seedDefaults } from "../api/client";

type BackfillResult = { processed: number; skipped: number; errors: number };
type BackfillOp = "topics" | "summary" | "figures";
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
  const [debugCount, setDebugCount] = useState<number | null>(null);
  const [debugDeleting, setDebugDeleting] = useState(false);
  const [debugDeleteResult, setDebugDeleteResult] = useState<{ deleted: number; figures_deleted: number } | null>(null);
  const [confirmDebugDelete, setConfirmDebugDelete] = useState(false);

  useEffect(() => {
    countDebugPapers().then(setDebugCount).catch(() => setDebugCount(null));
  }, []);
  const [backfill, setBackfill] = useState<Record<BackfillOp, BackfillState>>({
    topics:  { status: "idle" },
    summary: { status: "idle" },
    figures: { status: "idle" },
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
        <Row label="Default view" description="Starting layout when you open the library.">
          <ToggleGroup
            value={settings.defaultView}
            options={[
              { value: "grid", label: "Grid" },
              { value: "list", label: "List" },
            ]}
            onChange={(v) => update({ defaultView: v as AppSettings["defaultView"] })}
          />
        </Row>

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
      <Section title="Library Maintenance" description="Apply AI enrichment to papers already in your library. Skips papers that already have the data.">
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
