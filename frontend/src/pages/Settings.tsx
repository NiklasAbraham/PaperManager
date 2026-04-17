import { useState } from "react";
import { useAppSettings, type AppSettings } from "../contexts/SettingsContext";
import { apiFetch } from "../api/client";

export default function Settings() {
  const { settings, update, reset } = useAppSettings();
  const [confirmReset, setConfirmReset] = useState(false);
  const [exporting, setExporting] = useState<"bibtex" | "json" | null>(null);

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
              { value: "date_desc", label: "Newest added" },
              { value: "date_asc",  label: "Oldest added" },
              { value: "year_desc", label: "Year (newest first)" },
              { value: "year_asc",  label: "Year (oldest first)" },
              { value: "title_asc", label: "Title (A → Z)" },
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
