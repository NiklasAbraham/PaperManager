import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { listProjects, bulkImport } from "../api/client";
import type { BulkSseEvent } from "../types";

// ── Types ──────────────────────────────────────────────────────────────────────

interface BulkEntry {
  url?: string;
  arxiv?: string;
  doi?: string;
  title?: string;
  year?: number;
  fetch_pdf?: boolean;
}

interface ParsedEntry extends BulkEntry {
  _type: "url" | "arxiv" | "doi" | "title" | "unknown";
  _display: string;
  _status: "pending" | "running" | "success" | "skipped" | "error";
  _result?: string;
  _hasPdf?: boolean;
}

interface ProgressEntry {
  index: number;
  status: "success" | "skipped" | "error";
  title?: string;
  input?: string;
  error?: string;
  has_pdf?: boolean;
  reason?: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function inferType(entry: BulkEntry): ParsedEntry["_type"] {
  if (entry.url) return "url";
  if (entry.arxiv) return "arxiv";
  if (entry.doi) return "doi";
  if (entry.title) return "title";
  return "unknown";
}

function entryDisplay(entry: BulkEntry): string {
  return entry.url || entry.arxiv || entry.doi || entry.title || "(empty)";
}

const EXAMPLE_JSON = `{
  "fetch_pdf": true,
  "papers": [
    {"arxiv": "1706.03762"},
    {"doi": "10.1038/nature14539"},
    {"url": "https://arxiv.org/abs/1810.04805"},
    {"title": "ImageNet classification with deep convolutional neural networks"}
  ]
}`;

// ── Component ─────────────────────────────────────────────────────────────────

export default function BulkImport() {
  const navigate = useNavigate();

  const [jsonText, setJsonText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [entries, setEntries] = useState<ParsedEntry[] | null>(null);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [fetchPdf, setFetchPdf] = useState(true);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [summary, setSummary] = useState<{ imported: number; skipped: number; errors: number } | null>(null);
  const [log, setLog] = useState<ProgressEntry[]>([]);
  const logEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load projects once
  const loadProjects = useCallback(async () => {
    try {
      const ps = await listProjects();
      setProjects(ps);
    } catch { /* non-fatal */ }
  }, []);

  // Parse JSON input
  function handleParse() {
    setParseError(null);
    setEntries(null);
    setDone(false);
    setLog([]);
    setSummary(null);

    const text = jsonText.trim();
    if (!text) {
      setParseError("Paste JSON or upload a file first.");
      return;
    }
    try {
      const parsed = JSON.parse(text);
      let raw: BulkEntry[];

      if (Array.isArray(parsed)) {
        raw = parsed;
      } else if (parsed.papers && Array.isArray(parsed.papers)) {
        raw = parsed.papers;
        if (typeof parsed.fetch_pdf === "boolean") setFetchPdf(parsed.fetch_pdf);
        if (parsed.project_id) setProjectId(parsed.project_id);
      } else {
        setParseError('JSON must be an array or an object with a "papers" array.');
        return;
      }

      if (raw.length === 0) {
        setParseError("No entries found in JSON.");
        return;
      }

      const validated = raw.map((e) => ({
        ...e,
        _type: inferType(e),
        _display: entryDisplay(e),
        _status: "pending" as const,
      }));

      const invalid = validated.filter((e) => e._type === "unknown");
      if (invalid.length === raw.length) {
        setParseError("No entries have a recognized field (url, arxiv, doi, title).");
        return;
      }

      setEntries(validated);
      loadProjects();
    } catch (e: unknown) {
      setParseError(`Invalid JSON: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // File drop / pick
  function handleFile(file: File) {
    const reader = new FileReader();
    reader.onload = (ev) => {
      setJsonText((ev.target?.result as string) ?? "");
    };
    reader.readAsText(file);
  }

  function handleDrop(ev: React.DragEvent) {
    ev.preventDefault();
    const file = ev.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  // Start import
  async function handleStart() {
    if (!entries) return;
    setRunning(true);
    setDone(false);
    setLog([]);
    setSummary(null);

    // Reset all to pending
    setEntries((prev) => prev?.map((e) => ({ ...e, _status: "pending" })) ?? null);

    abortRef.current = new AbortController();

    // Mark first as running
    setEntries((prev) =>
      prev?.map((e, i) => (i === 0 ? { ...e, _status: "running" } : e)) ?? null
    );

    try {
      const payload = {
        papers: entries.map(({ _type, _display, _status, _result, _hasPdf, ...rest }) => rest),
        project_id: projectId || null,
        fetch_pdf: fetchPdf,
      };

      for await (const event of bulkImport(payload, abortRef.current.signal)) {
        if (event.done) {
          setSummary({ imported: event.imported, skipped: event.skipped, errors: event.errors });
          setDone(true);
          break;
        }

        const { index, total: _total, status, ...rest } = event;

        // Update entry status
        setEntries((prev) =>
          prev?.map((e, i) => {
            if (i === index) {
              return {
                ...e,
                _status: status as ParsedEntry["_status"],
                _result: rest.title || rest.input || e._display,
                _hasPdf: rest.has_pdf,
              };
            }
            if (i === index + 1 && status !== "pending") {
              return { ...e, _status: "running" };
            }
            return e;
          }) ?? null
        );

        setLog((prev) => [...prev, { index, status, ...rest } as ProgressEntry]);
        logEndRef.current?.scrollIntoView({ behavior: "smooth" });
      }
    } catch (e: unknown) {
      if ((e as Error)?.name !== "AbortError") {
        console.error("Bulk import stream error", e);
      }
    } finally {
      setRunning(false);
    }
  }

  function handleAbort() {
    abortRef.current?.abort();
    setRunning(false);
  }

  const typeBadge: Record<ParsedEntry["_type"], string> = {
    url: "bg-blue-100 text-blue-700",
    arxiv: "bg-orange-100 text-orange-700",
    doi: "bg-green-100 text-green-700",
    title: "bg-purple-100 text-purple-700",
    unknown: "bg-red-100 text-red-700",
  };

  const statusIcon: Record<ParsedEntry["_status"], string> = {
    pending: "○",
    running: "⟳",
    success: "✓",
    skipped: "→",
    error: "✗",
  };

  const statusColor: Record<ParsedEntry["_status"], string> = {
    pending: "text-gray-400",
    running: "text-blue-500 animate-spin",
    success: "text-green-600",
    skipped: "text-yellow-600",
    error: "text-red-500",
  };

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Bulk Import</h1>
        <p className="text-sm text-gray-500 mt-1">
          Import a list of papers from a JSON file. Each entry can have a URL, arXiv ID, DOI, or title.
        </p>
      </div>

      {/* ── Input panel ────────────────────────────────────────────────────── */}
      {!running && !done && (
        <div className="space-y-3">
          <div
            className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center cursor-pointer hover:border-violet-400 transition-colors"
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => document.getElementById("bulk-file-input")?.click()}
          >
            <input
              id="bulk-file-input"
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
              }}
            />
            <p className="text-sm text-gray-500">
              Drag & drop a <code className="bg-gray-100 px-1 rounded">.json</code> file here, or{" "}
              <span className="text-violet-600 font-medium">click to browse</span>
            </p>
          </div>

          <textarea
            className="w-full h-48 font-mono text-xs border border-gray-300 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-y"
            placeholder={EXAMPLE_JSON}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
          />

          {parseError && (
            <p className="text-sm text-red-500">{parseError}</p>
          )}

          <button
            onClick={handleParse}
            className="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700 transition-colors"
          >
            Parse &amp; Preview
          </button>
        </div>
      )}

      {/* ── Preview table ──────────────────────────────────────────────────── */}
      {entries && !done && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-gray-700">
              {entries.length} entries parsed
              {entries.filter((e) => e._type === "unknown").length > 0 && (
                <span className="ml-2 text-red-500">
                  ({entries.filter((e) => e._type === "unknown").length} will be skipped — no resolvable field)
                </span>
              )}
            </h2>
            {!running && (
              <button
                onClick={() => { setEntries(null); setJsonText(""); }}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Clear
              </button>
            )}
          </div>

          {/* Options row */}
          {!running && (
            <div className="flex flex-wrap gap-4 items-center bg-gray-50 rounded-lg p-3">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={fetchPdf}
                  onChange={(e) => setFetchPdf(e.target.checked)}
                  className="accent-violet-600"
                />
                Download PDFs when available (arXiv + open access)
              </label>

              {projects.length > 0 && (
                <div className="flex items-center gap-2">
                  <label className="text-sm text-gray-600">Add to project:</label>
                  <select
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    className="text-sm border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-violet-400"
                  >
                    <option value="">— none —</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          {/* Entry table */}
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium w-8">#</th>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium w-20">Type</th>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium">Input</th>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium w-16">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {entries.map((e, i) => (
                    <tr key={i} className={e._status === "running" ? "bg-blue-50" : ""}>
                      <td className="px-3 py-1.5 text-gray-400">{i + 1}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${typeBadge[e._type]}`}>
                          {e._type}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-gray-700 font-mono truncate max-w-xs" title={e._display}>
                        {e._result || e._display}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className={`font-mono ${statusColor[e._status]}`}>
                          {statusIcon[e._status]}
                        </span>
                        {e._status === "running" && (
                          <span className="ml-1 text-blue-400">…</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Start / Abort button */}
          {!running ? (
            <button
              onClick={handleStart}
              className="px-5 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700 transition-colors"
            >
              Start Import ({entries.filter((e) => e._type !== "unknown").length} papers)
            </button>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-sm text-blue-600">
                <span className="inline-block w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                Importing…
              </div>
              <button
                onClick={handleAbort}
                className="px-3 py-1.5 text-sm border border-red-300 text-red-600 rounded hover:bg-red-50"
              >
                Stop
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Live progress log ─────────────────────────────────────────────── */}
      {(running || done) && log.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-medium text-gray-700">Progress</h2>
          <div className="bg-gray-950 rounded-lg p-4 max-h-80 overflow-y-auto font-mono text-xs space-y-1">
            {log.map((entry, i) => (
              <div key={i} className={
                entry.status === "success" ? "text-green-400" :
                entry.status === "skipped" ? "text-yellow-400" :
                "text-red-400"
              }>
                <span className="text-gray-500 mr-2">{String(entry.index + 1).padStart(3, "0")}</span>
                {entry.status === "success" && (
                  <>
                    <span className="mr-1">✓</span>
                    {entry.title}
                    {entry.has_pdf && <span className="ml-2 text-blue-400">[PDF]</span>}
                  </>
                )}
                {entry.status === "skipped" && (
                  <>
                    <span className="mr-1">→</span>
                    {entry.title} <span className="text-gray-500">({entry.reason})</span>
                  </>
                )}
                {entry.status === "error" && (
                  <>
                    <span className="mr-1">✗</span>
                    {entry.input} — <span className="text-red-300">{entry.error}</span>
                  </>
                )}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {/* ── Summary banner ────────────────────────────────────────────────── */}
      {done && summary && (
        <div className="border border-green-200 bg-green-50 rounded-lg p-4 flex items-center justify-between">
          <div className="text-sm text-green-800">
            <span className="font-semibold">{summary.imported}</span> imported
            {summary.skipped > 0 && (
              <span className="ml-3 text-yellow-700">
                <span className="font-semibold">{summary.skipped}</span> already existed
              </span>
            )}
            {summary.errors > 0 && (
              <span className="ml-3 text-red-700">
                <span className="font-semibold">{summary.errors}</span> failed
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => navigate("/?tag=bulk-import")}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
            >
              View in Library
            </button>
            <button
              onClick={() => {
                setEntries(null);
                setJsonText("");
                setDone(false);
                setLog([]);
                setSummary(null);
              }}
              className="px-3 py-1.5 text-sm border border-gray-300 text-gray-600 rounded hover:bg-gray-100"
            >
              New Import
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
