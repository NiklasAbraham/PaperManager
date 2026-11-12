import { useRef, useState } from "react";
import { apiFetch } from "../../api/client";
import { CYPHER_EXAMPLES } from "./cypherExamples";
import { ResultSummary, ResultTable } from "./ResultTable";
import {
  deleteSavedQuery,
  loadSavedQueries,
  saveQuery,
  type SavedQuery,
} from "./savedQueries";
import type { QueryResult, ResultTab, SchemaInfo } from "./types";

type Drawer = "examples" | "saved" | "schema" | null;

/** apiFetch throws `API 400: {"detail": "..."}`; show just the detail. */
function errorText(e: unknown, fallback: string): string {
  if (!(e instanceof Error)) return fallback;
  const m = /^API \d+: (.*)$/s.exec(e.message);
  if (!m) return e.message;
  try {
    const d = (JSON.parse(m[1]) as { detail?: unknown }).detail;
    return typeof d === "string" ? d : m[1];
  } catch {
    return m[1];
  }
}

const btn =
  "px-2.5 py-1 text-xs rounded border border-line text-ink-2 hover:border-accent-border hover:text-accent transition-colors";
const btnOn = "px-2.5 py-1 text-xs rounded border border-accent-border bg-accent-lo text-accent";

export interface CypherPanelProps {
  initialQuery: string;
  result: QueryResult | null;
  tab: ResultTab;
  onResult: (r: QueryResult | null) => void;
  onTabChange: (t: ResultTab) => void;
  onClose: () => void;
}

export default function CypherPanel({ initialQuery, result, tab, onResult, onTabChange, onClose }: CypherPanelProps) {
  const [query, setQuery] = useState(initialQuery);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [allowWrites, setAllowWrites] = useState(false);
  const [writesAcknowledged, setWritesAcknowledged] = useState(false);
  const [confirmWrites, setConfirmWrites] = useState(false);

  const [drawer, setDrawer] = useState<Drawer>(null);
  const [saved, setSaved] = useState<SavedQuery[]>(loadSavedQueries);
  const [saveName, setSaveName] = useState("");
  const [schema, setSchema] = useState<SchemaInfo | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const [assistText, setAssistText] = useState("");
  const [assisting, setAssisting] = useState(false);
  const [copied, setCopied] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const toggleDrawer = (d: Exclude<Drawer, null>) => {
    setDrawer((cur) => (cur === d ? null : d));
    if (d === "schema" && !schema) {
      setSchemaError(null);
      apiFetch<SchemaInfo>("/cypher/schema")
        .then(setSchema)
        .catch((e) => setSchemaError(errorText(e, "Schema unavailable")));
    }
  };

  const loadQuery = (q: string) => {
    setQuery(q);
    setError(null);
    textareaRef.current?.focus();
  };

  const run = async () => {
    const q = query.trim();
    if (!q || running) return;
    setRunning(true);
    setError(null);
    try {
      const res = await apiFetch<QueryResult>("/graph/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, read_only: !allowWrites }),
      });
      onResult(res);
      onTabChange(res.nodes.length > 0 ? "graph" : "table");
    } catch (e) {
      setError(errorText(e, "Query failed"));
    } finally {
      setRunning(false);
    }
  };

  const toggleWrites = (checked: boolean) => {
    if (!checked) {
      setAllowWrites(false);
      setConfirmWrites(false);
    } else if (writesAcknowledged) {
      setAllowWrites(true);
    } else {
      setConfirmWrites(true);
    }
  };

  const assist = async () => {
    if (!assistText.trim() || assisting) return;
    setAssisting(true);
    setError(null);
    try {
      const res = await apiFetch<{ query: string }>("/cypher/assist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: assistText }),
      });
      loadQuery(res.query);
    } catch (e) {
      setError(errorText(e, "AI assist unavailable"));
    } finally {
      setAssisting(false);
    }
  };

  const copyLink = async () => {
    const url = new URL(window.location.href);
    url.searchParams.set("view", "query");
    url.searchParams.set("q", query);
    try {
      await navigator.clipboard.writeText(url.toString());
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked: nothing to do
    }
  };

  const writeHint = error !== null && /read access mode/i.test(error) && !allowWrites;

  return (
    <div
      data-testid="query-panel"
      className="order-2 lg:order-1 flex flex-col bg-raised border-line min-h-0 overflow-y-auto border-t lg:border-t-0 lg:border-r
                 h-[55%] lg:h-auto w-full lg:w-[26rem] xl:w-[30rem] shrink-0"
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line-s shrink-0">
        <span className="text-[10px] font-semibold text-accent uppercase tracking-wide">Query</span>
        <span className="text-xs text-ink-3">Cypher</span>
        <button onClick={copyLink} className={`${btn} ml-auto`} title="Copy a link that opens this query">
          {copied ? "Copied" : "Copy link"}
        </button>
        <button
          onClick={onClose}
          aria-label="Close query panel"
          className="text-ink-3 hover:text-ink text-lg leading-none px-1"
        >
          ×
        </button>
      </div>

      <div className="p-3 space-y-2 border-b border-line-s">
        <textarea
          ref={textareaRef}
          aria-label="Cypher query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              run();
            }
          }}
          rows={5}
          spellCheck={false}
          placeholder="// Write Cypher here…"
          className="w-full font-mono text-xs bg-base text-ink border border-line rounded px-2.5 py-2 resize-y
                     focus:outline-none focus:ring-2 focus:ring-violet-300 leading-relaxed"
        />

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={run}
            disabled={running || !query.trim()}
            className="px-3 py-1.5 text-xs font-medium bg-accent text-white rounded hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {running ? "Running…" : "Run ⌘↵"}
          </button>
          <label className="flex items-center gap-1.5 text-xs text-ink-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={allowWrites}
              onChange={(e) => toggleWrites(e.target.checked)}
              className="accent-violet-600"
            />
            Allow writes
          </label>
          <button onClick={() => { setQuery(""); onResult(null); setError(null); }} className="text-xs text-ink-3 hover:text-ink px-1">
            Clear
          </button>
          <span className="ml-auto flex flex-wrap gap-1.5">
            <button onClick={() => toggleDrawer("examples")} className={drawer === "examples" ? btnOn : btn}>Examples</button>
            <button onClick={() => toggleDrawer("saved")} className={drawer === "saved" ? btnOn : btn}>Saved</button>
            <button onClick={() => toggleDrawer("schema")} className={drawer === "schema" ? btnOn : btn}>Schema</button>
          </span>
        </div>

        {confirmWrites && (
          <div role="alertdialog" className="border border-red-200 bg-red-50 rounded p-2.5 text-xs text-red-700 space-y-2">
            <p>
              Writes change the live library and cannot be undone. Queries run with writes enabled can
              create, change and delete nodes and relationships.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => { setAllowWrites(true); setWritesAcknowledged(true); setConfirmWrites(false); }}
                className="px-2.5 py-1 rounded bg-red-600 text-white hover:bg-red-700"
              >
                Allow writes
              </button>
              <button onClick={() => setConfirmWrites(false)} className={btn}>Cancel</button>
            </div>
          </div>
        )}
        {allowWrites && (
          <p className="text-[11px] text-amber">Writes are on: this query can modify the library.</p>
        )}

        <div className="flex items-center gap-2">
          <input
            value={assistText}
            onChange={(e) => setAssistText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && assist()}
            placeholder="Describe the query in plain English…"
            aria-label="Describe the query in plain English"
            className="flex-1 min-w-0 border border-line rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          <button
            onClick={assist}
            disabled={assisting || !assistText.trim()}
            className="px-2.5 py-1.5 text-xs font-medium rounded bg-accent-lo text-accent hover:bg-violet-100 disabled:opacity-50 whitespace-nowrap"
          >
            {assisting ? "Thinking…" : "Generate"}
          </button>
        </div>
      </div>

      {drawer === "examples" && (
        <div className="max-h-64 overflow-y-auto border-b border-line-s py-1" data-testid="examples-list">
          {CYPHER_EXAMPLES.map((cat) => (
            <div key={cat.category} className="mb-1">
              <p className="px-3 py-1 text-[10px] font-semibold text-ink-3 uppercase tracking-wider">{cat.category}</p>
              {cat.items.map((ex) => (
                <button
                  key={ex.label}
                  onClick={() => loadQuery(ex.query)}
                  title={ex.desc}
                  className="w-full text-left px-3 py-1 text-xs text-ink-2 hover:bg-accent-lo hover:text-accent leading-snug"
                >
                  {ex.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {drawer === "saved" && (
        <div className="max-h-64 overflow-y-auto border-b border-line-s p-3 space-y-2" data-testid="saved-list">
          <div className="flex gap-2">
            <input
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && query.trim()) { setSaved(saveQuery(saveName, query)); setSaveName(""); }
              }}
              placeholder="Name for the current query"
              aria-label="Name for the current query"
              className="flex-1 min-w-0 border border-line rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            <button
              onClick={() => { setSaved(saveQuery(saveName, query)); setSaveName(""); }}
              disabled={!query.trim()}
              className={`${btn} disabled:opacity-50`}
            >
              Save
            </button>
          </div>
          {saved.length === 0 && <p className="text-xs text-ink-3">No saved queries yet. They stay in this browser.</p>}
          <ul className="space-y-1">
            {saved.map((s) => (
              <li key={s.name} className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => loadQuery(s.query)}
                  title={s.query}
                  className="flex-1 min-w-0 text-left truncate text-ink-2 hover:text-accent"
                >
                  {s.name}
                </button>
                <span className="text-[10px] text-ink-3 shrink-0">{s.saved_at.slice(0, 10)}</span>
                <button
                  onClick={() => setSaved(deleteSavedQuery(s.name))}
                  aria-label={`Delete saved query ${s.name}`}
                  className="text-ink-3 hover:text-coral shrink-0"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {drawer === "schema" && (
        <div className="max-h-64 overflow-y-auto border-b border-line-s p-3 text-xs space-y-3">
          {!schema && !schemaError && <p className="text-ink-3">Loading schema…</p>}
          {schemaError && <p className="text-coral">{schemaError}</p>}
          {schema && (
            <>
              <div>
                <p className="font-semibold text-ink-3 mb-1">Node labels</p>
                <div className="flex flex-wrap gap-1">
                  {schema.labels.map((l) => (
                    <button key={l} onClick={() => setQuery((q) => `${q}${q && !q.endsWith("\n") ? "\n" : ""}MATCH (n:${l}) RETURN n LIMIT 25`)}
                      title="Add a query for this label" className="bg-accent-lo text-accent px-2 py-0.5 rounded font-mono">{l}</button>
                  ))}
                </div>
              </div>
              <div>
                <p className="font-semibold text-ink-3 mb-1">Relationships</p>
                <div className="flex flex-wrap gap-1">
                  {schema.relationship_types.map((r) => (
                    <span key={r} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded font-mono">{r}</span>
                  ))}
                </div>
              </div>
              <div>
                <p className="font-semibold text-ink-3 mb-1">Properties per label</p>
                <div className="space-y-1">
                  {Object.entries(schema.properties).map(([label, props]) => (
                    <div key={label} className="flex gap-2 items-baseline">
                      <span className="font-mono text-accent w-16 shrink-0">{label}</span>
                      <span className="text-ink-2 break-words min-w-0">{props.join(", ")}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      <div className="p-3 space-y-2 flex-1">
        {error && (
          <div role="alert" className="bg-red-50 border border-red-200 rounded p-2.5 text-xs text-red-700 font-mono whitespace-pre-wrap break-words">
            {error}
            {writeHint && <p className="mt-1.5 font-sans">This query writes. Tick &quot;Allow writes&quot; to run it.</p>}
          </div>
        )}

        {result && !error && (
          <>
            <ResultSummary result={result} />
            <div role="tablist" className="flex gap-1 border-b border-line-s">
              {(["graph", "table"] as ResultTab[]).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => onTabChange(t)}
                  className={`px-3 py-1.5 text-xs font-medium -mb-px border-b-2 capitalize ${
                    tab === t ? "border-accent text-accent" : "border-transparent text-ink-3 hover:text-ink"
                  }`}
                >
                  {t === "graph" ? `Graph (${result.nodes.length})` : `Table (${result.row_count})`}
                </button>
              ))}
            </div>
            {tab === "graph" ? (
              <p className="text-xs text-ink-2">
                {result.nodes.length === 0
                  ? "This result has no nodes to draw. Return nodes or relationships (for example RETURN n, r, m) to see them as a graph."
                  : `${result.nodes.length} nodes and ${result.links.length} links are shown in the canvas. Click a node for its properties. The Table tab brings back the full graph.`}
              </p>
            ) : (
              <ResultTable result={result} />
            )}
          </>
        )}

        {!result && !error && (
          <p className="text-xs text-ink-3">
            Run a query to see it as a graph and as a table. Queries are read-only unless you allow writes.
          </p>
        )}
      </div>
    </div>
  );
}
