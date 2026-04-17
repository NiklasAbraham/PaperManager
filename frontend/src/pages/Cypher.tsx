import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  counters: Record<string, number>;
}

interface SchemaInfo {
  labels: string[];
  relationship_types: string[];
  properties: Record<string, string[]>;
}

// ── Example queries ───────────────────────────────────────────────────────────

const EXAMPLES = [
  {
    category: "References",
    items: [
      {
        label: "Show all reference stubs",
        desc: "Papers that were pulled as citation stubs (no full data yet)",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NULL
  AND p.drive_file_id IS NULL
  AND p.metadata_source IS NULL
RETURN p.title AS title, p.year AS year, p.doi AS doi
ORDER BY p.year DESC`,
      },
      {
        label: "Delete all reference stubs",
        desc: "Remove sparse citation stubs that haven't been pulled",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NULL
  AND p.drive_file_id IS NULL
  AND p.metadata_source IS NULL
DETACH DELETE p`,
      },
      {
        label: "Remove all CITES from a paper",
        desc: "Delete citation relationships (not the cited papers)",
        query: `MATCH (p:Paper)-[r:CITES]->()
WHERE toLower(p.title) CONTAINS toLower("PAPER TITLE HERE")
DELETE r`,
      },
      {
        label: "Papers citing a specific paper",
        desc: "Find which papers in your library cite a given paper",
        query: `MATCH (citing:Paper)-[:CITES]->(cited:Paper)
WHERE toLower(cited.title) CONTAINS toLower("CITED PAPER TITLE")
RETURN citing.title AS citing_paper, citing.year AS year
ORDER BY year DESC`,
      },
    ],
  },
  {
    category: "Papers",
    items: [
      {
        label: "Papers without abstracts",
        desc: "Find ingested papers that are missing abstracts",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NULL
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.doi AS doi
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers by year distribution",
        desc: "Count how many papers per publication year",
        query: `MATCH (p:Paper)
WHERE p.year IS NOT NULL
RETURN p.year AS year, count(p) AS count
ORDER BY year DESC`,
      },
      {
        label: "Most cited papers in library",
        desc: "Papers with the highest citation_count from Semantic Scholar",
        query: `MATCH (p:Paper)
WHERE p.citation_count IS NOT NULL
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY citations DESC
LIMIT 20`,
      },
      {
        label: "Papers added this week",
        desc: "Recently added papers",
        query: `MATCH (p:Paper)
WHERE p.created_at >= toString(date() - duration('P7D'))
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.created_at AS added
ORDER BY p.created_at DESC`,
      },
    ],
  },
  {
    category: "Authors & People",
    items: [
      {
        label: "Most prolific authors",
        desc: "Authors with the most papers in the library",
        query: `MATCH (person:Person)<-[:AUTHORED_BY]-(p:Paper)
RETURN person.name AS author, count(p) AS paper_count
ORDER BY paper_count DESC
LIMIT 20`,
      },
      {
        label: "Papers by a person",
        desc: "All papers linked to a specific person",
        query: `MATCH (person:Person)<-[:AUTHORED_BY]-(p:Paper)
WHERE toLower(person.name) CONTAINS toLower("AUTHOR NAME HERE")
RETURN p.title AS title, p.year AS year`,
      },
      {
        label: "People with no papers",
        desc: "Person nodes with no linked papers (cleanup)",
        query: `MATCH (p:Person)
WHERE NOT (p)<-[:AUTHORED_BY]-()
  AND NOT (p)<-[:INVOLVES]-()
RETURN p.name AS name, p.id AS id`,
      },
    ],
  },
  {
    category: "Topics & Tags",
    items: [
      {
        label: "Topics with paper count",
        desc: "All topics ranked by how many papers they cover",
        query: `MATCH (t:Topic)
OPTIONAL MATCH (p:Paper)-[:ABOUT]->(t)
RETURN t.name AS topic, count(p) AS papers
ORDER BY papers DESC`,
      },
      {
        label: "Papers with no topics",
        desc: "Papers that haven't been assigned any research topics",
        query: `MATCH (p:Paper)
WHERE NOT (p)-[:ABOUT]->()
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year`,
      },
      {
        label: "Rename a tag",
        desc: "Update a tag name across the entire graph",
        query: `MATCH (t:Tag {name: "OLD TAG NAME"})
SET t.name = "NEW TAG NAME"
RETURN t`,
      },
      {
        label: "Merge two topics",
        desc: "Re-point all papers from one topic to another, then delete the old one",
        query: `MATCH (old:Topic {name: "OLD TOPIC"}), (keep:Topic {name: "KEEP TOPIC"})
MATCH (p:Paper)-[r:ABOUT]->(old)
MERGE (p)-[:ABOUT]->(keep)
DELETE r
WITH old
DETACH DELETE old`,
      },
    ],
  },
  {
    category: "Cleanup",
    items: [
      {
        label: "Orphan nodes",
        desc: "Nodes with no relationships at all",
        query: `MATCH (n)
WHERE NOT (n)--()
RETURN labels(n) AS type, n.name AS name, n.title AS title, n.id AS id`,
      },
      {
        label: "Delete orphan nodes",
        desc: "Remove all completely unconnected nodes",
        query: `MATCH (n)
WHERE NOT (n)--()
DETACH DELETE n`,
      },
      {
        label: "Duplicate papers by title",
        desc: "Find papers with the same title (potential duplicates)",
        query: `MATCH (p:Paper)
WITH toLower(trim(p.title)) AS norm, collect(p.id) AS ids, count(*) AS cnt
WHERE cnt > 1
RETURN norm AS title, cnt AS duplicates, ids`,
      },
      {
        label: "Full paper count by source",
        desc: "How many papers came from each metadata source",
        query: `MATCH (p:Paper)
RETURN p.metadata_source AS source, count(p) AS count
ORDER BY count DESC`,
      },
    ],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatCellValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v, null, 0).slice(0, 120);
  return String(v);
}

function isMutation(counters: Record<string, number>): boolean {
  return Object.values(counters).some((n) => n > 0);
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Cypher() {
  const navigate = useNavigate();
  const [query, setQuery]           = useState("MATCH (p:Paper) RETURN p.title AS title, p.year AS year, p.metadata_source AS source ORDER BY p.created_at DESC LIMIT 10");
  const [result, setResult]         = useState<QueryResult | null>(null);
  const [error, setError]           = useState<string | null>(null);
  const [running, setRunning]       = useState(false);

  const [assistText, setAssistText] = useState("");
  const [assisting, setAssisting]   = useState(false);

  const [schema, setSchema]         = useState<SchemaInfo | null>(null);
  const [schemaOpen, setSchemaOpen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    apiFetch<SchemaInfo>("/cypher/schema").then(setSchema).catch(() => {});
  }, []);

  const runQuery = async () => {
    if (!query.trim()) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<QueryResult>("/cypher/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Query failed");
    } finally {
      setRunning(false);
    }
  };

  const runAssist = async () => {
    if (!assistText.trim()) return;
    setAssisting(true);
    setError(null);
    try {
      const res = await apiFetch<{ query: string }>("/cypher/assist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: assistText }),
      });
      setQuery(res.query);
      textareaRef.current?.focus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Ollama unavailable");
    } finally {
      setAssisting(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-53px)]">

      {/* ── Left sidebar: examples ─────────────────────────────────────── */}
      <aside className="w-60 shrink-0 border-r border-gray-200 bg-white overflow-y-auto">
        <div className="px-4 py-3 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Example queries</p>
        </div>
        <div className="py-2">
          {EXAMPLES.map((cat) => (
            <div key={cat.category} className="mb-1">
              <p className="px-4 py-1.5 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                {cat.category}
              </p>
              {cat.items.map((ex) => (
                <button
                  key={ex.label}
                  onClick={() => { setQuery(ex.query); setResult(null); setError(null); }}
                  title={ex.desc}
                  className="w-full text-left px-4 py-1.5 text-xs text-gray-600 hover:bg-violet-50 hover:text-violet-700 transition-colors leading-snug"
                >
                  {ex.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* ── Main area ──────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden bg-gray-50">

        {/* ── Query editor ─────────────────────────────────────────────── */}
        <div className="bg-white border-b border-gray-200 p-4 space-y-3">

          {/* Editor */}
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  runQuery();
                }
              }}
              rows={6}
              spellCheck={false}
              className="w-full font-mono text-sm bg-gray-950 text-green-300 rounded-xl px-4 py-3 resize-none focus:outline-none focus:ring-2 focus:ring-violet-500 leading-relaxed"
              placeholder="// Write Cypher here…"
            />
            <span className="absolute bottom-2 right-3 text-[10px] text-gray-600 select-none">
              ⌘↵ to run
            </span>
          </div>

          {/* Run bar */}
          <div className="flex items-center gap-2">
            <button
              onClick={runQuery}
              disabled={running || !query.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-violet-600 text-white text-sm font-medium rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {running ? (
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z" />
                </svg>
              )}
              Run
            </button>
            <button
              onClick={() => { setQuery(""); setResult(null); setError(null); }}
              className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Clear
            </button>

            {/* Schema toggle */}
            <button
              onClick={() => setSchemaOpen((o) => !o)}
              className={`ml-auto flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg border transition-colors
                ${schemaOpen ? "bg-gray-100 border-gray-300 text-gray-700" : "border-gray-200 text-gray-400 hover:text-gray-600"}`}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
              </svg>
              Schema
            </button>
          </div>

          {/* Schema panel */}
          {schemaOpen && schema && (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-xs space-y-3">
              <div className="flex gap-6 flex-wrap">
                <div>
                  <p className="font-semibold text-gray-500 mb-1">Node labels</p>
                  <div className="flex flex-wrap gap-1">
                    {schema.labels.map((l) => (
                      <span key={l} className="bg-violet-100 text-violet-700 px-2 py-0.5 rounded font-mono">{l}</span>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="font-semibold text-gray-500 mb-1">Relationships</p>
                  <div className="flex flex-wrap gap-1">
                    {schema.relationship_types.map((r) => (
                      <span key={r} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded font-mono">{r}</span>
                    ))}
                  </div>
                </div>
              </div>
              <div>
                <p className="font-semibold text-gray-500 mb-1">Properties per label</p>
                <div className="space-y-1">
                  {Object.entries(schema.properties).map(([label, props]) => (
                    <div key={label} className="flex gap-2 items-baseline">
                      <span className="font-mono text-violet-700 w-20 shrink-0">{label}</span>
                      <span className="text-gray-500">{props.join(", ")}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Ollama assist */}
          <div className="flex gap-2 items-center">
            <div className="flex-1 flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
              <svg className="w-4 h-4 text-violet-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
              <input
                value={assistText}
                onChange={(e) => setAssistText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runAssist()}
                placeholder="Describe what you want in plain English… (Ollama)"
                className="flex-1 bg-transparent text-sm focus:outline-none placeholder-gray-400"
              />
            </div>
            <button
              onClick={runAssist}
              disabled={assisting || !assistText.trim()}
              className="px-3 py-2 bg-violet-100 text-violet-700 text-sm font-medium rounded-lg hover:bg-violet-200 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {assisting ? "Thinking…" : "Generate ✦"}
            </button>
          </div>
        </div>

        {/* ── Results ──────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-auto p-4">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700 font-mono whitespace-pre-wrap">
              {error}
            </div>
          )}

          {result && !error && (
            <div className="space-y-3">
              {/* Status bar */}
              <div className="flex items-center gap-4 text-xs text-gray-500">
                {result.columns.length > 0 && (
                  <span className="font-medium text-gray-700">{result.row_count} row{result.row_count !== 1 ? "s" : ""}</span>
                )}
                {isMutation(result.counters) && (
                  <span className="flex gap-3">
                    {result.counters.nodes_created > 0   && <span className="text-green-600">+{result.counters.nodes_created} node{result.counters.nodes_created !== 1 ? "s" : ""}</span>}
                    {result.counters.nodes_deleted > 0   && <span className="text-red-600">−{result.counters.nodes_deleted} node{result.counters.nodes_deleted !== 1 ? "s" : ""}</span>}
                    {result.counters.relationships_created > 0 && <span className="text-green-600">+{result.counters.relationships_created} rel{result.counters.relationships_created !== 1 ? "s" : ""}</span>}
                    {result.counters.relationships_deleted > 0 && <span className="text-red-600">−{result.counters.relationships_deleted} rel{result.counters.relationships_deleted !== 1 ? "s" : ""}</span>}
                    {result.counters.properties_set > 0  && <span className="text-blue-600">{result.counters.properties_set} prop{result.counters.properties_set !== 1 ? "s" : ""} set</span>}
                  </span>
                )}
                {result.row_count >= 500 && (
                  <span className="text-amber-600">Results capped at 500 rows</span>
                )}
                <button
                  onClick={() => navigate("/graph", { state: { cypherQuery: query } })}
                  className="ml-auto flex items-center gap-1.5 px-3 py-1.5 bg-violet-100 text-violet-700 rounded-lg hover:bg-violet-200 transition-colors font-medium"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/>
                    <line x1="7" y1="11.5" x2="17" y2="6.5" strokeLinecap="round"/>
                    <line x1="7" y1="12.5" x2="17" y2="17.5" strokeLinecap="round"/>
                  </svg>
                  Open in Graph
                </button>
              </div>

              {/* Table */}
              {result.columns.length > 0 && result.rows.length > 0 && (
                <div className="bg-white border border-gray-200 rounded-xl overflow-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        {result.columns.map((col) => (
                          <th key={col} className="text-left px-4 py-2.5 font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i} className={`border-b border-gray-100 hover:bg-violet-50 transition-colors ${i % 2 === 0 ? "" : "bg-gray-50/50"}`}>
                          {result.columns.map((col) => (
                            <td key={col} className="px-4 py-2 text-gray-700 font-mono max-w-xs truncate" title={formatCellValue(row[col])}>
                              {formatCellValue(row[col])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {result.columns.length > 0 && result.rows.length === 0 && (
                <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-400">
                  Query returned no results.
                </div>
              )}

              {result.columns.length === 0 && isMutation(result.counters) && (
                <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-600">
                  Query executed successfully.
                </div>
              )}
            </div>
          )}

          {!result && !error && (
            <div className="h-full flex items-center justify-center">
              <p className="text-sm text-gray-400">Run a query or pick an example from the sidebar</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
