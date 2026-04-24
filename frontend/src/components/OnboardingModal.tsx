import { useEffect, useState } from "react";
import {
  suggestTags, createTag, listProjects, addPaperToProject,
  apiFetch, getOrCreatePerson, linkPersonInvolves,
} from "../api/client";
import type { T_IngestOut } from "../types";

type Step = "tags" | "project" | "people";

const STEPS: Step[] = ["tags", "project", "people"];
const STEP_LABELS: Record<Step, string> = {
  tags: "Tags",
  project: "Project",
  people: "People",
};

const INVOLVE_ROLES = [
  "shared_by", "supervisor", "collaborating", "reviewer", "colleague",
] as const;

interface Props {
  paper: T_IngestOut;
  onClose: () => void;
}

// ── Score project keyword overlap with paper title+abstract ─────────────────

function scoreProject(proj: { name: string; description?: string }, paper: T_IngestOut): number {
  const haystack = `${proj.name} ${proj.description ?? ""}`.toLowerCase();
  const needle = `${paper.title} ${paper.abstract ?? ""}`.toLowerCase();
  const words = needle.match(/\b\w{4,}\b/g) ?? [];
  return words.filter((w) => haystack.includes(w)).length;
}

// ── Step indicators ──────────────────────────────────────────────────────────

function StepBar({ current }: { current: Step }) {
  return (
    <div className="flex items-center gap-0 mb-6">
      {STEPS.map((s, i) => {
        const done = STEPS.indexOf(current) > i;
        const active = s === current;
        return (
          <div key={s} className="flex items-center flex-1">
            <div className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold border-2 transition-colors shrink-0 ${
              done ? "bg-violet-600 border-violet-600 text-white"
              : active ? "border-violet-600 text-violet-700 bg-white"
              : "border-gray-200 text-gray-400 bg-white"
            }`}>
              {done ? "✓" : i + 1}
            </div>
            <span className={`ml-1.5 text-xs font-medium transition-colors ${active ? "text-violet-700" : done ? "text-gray-500" : "text-gray-300"}`}>
              {STEP_LABELS[s]}
            </span>
            {i < STEPS.length - 1 && (
              <div className={`flex-1 h-px mx-3 ${done ? "bg-violet-300" : "bg-gray-200"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Tags step ────────────────────────────────────────────────────────────────

function TagsStep({ paper, onNext }: { paper: T_IngestOut; onNext: () => void }) {
  const [suggested, setSuggested] = useState<{ existing: string[]; new: string[] }>({ existing: [], new: [] });
  const [applied, setApplied] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [custom, setCustom] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const loadTags = async () => {
      try {
        // Load currently applied tags
        const current = await apiFetch<{ id: string; name: string }[]>(`/papers/${paper.id}/tags`);
        const currentNames = new Set(current.map((t) => t.name));
        setApplied(currentNames);

        // Load suggestions
        const res = await suggestTags(paper.title, paper.abstract);
        setSuggested({ existing: res.existing, new: res.new });
      } catch { /* ignore */ }
      finally { setLoading(false); }
    };
    loadTags();
  }, [paper.id, paper.title, paper.abstract]);

  const toggle = async (name: string) => {
    if (applied.has(name)) return; // don't remove via this UI
    setAdding(true);
    try {
      await createTag(paper.id, name);
      setApplied((prev) => new Set([...prev, name]));
    } catch { /* ignore */ }
    finally { setAdding(false); }
  };

  const addCustom = async () => {
    const name = custom.trim();
    if (!name) return;
    setAdding(true);
    try {
      await createTag(paper.id, name);
      setApplied((prev) => new Set([...prev, name]));
      setCustom("");
    } catch { /* ignore */ }
    finally { setAdding(false); }
  };

  const allSuggested = [...new Set([...suggested.existing, ...suggested.new])];

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-800 mb-1">Tags</p>
        <p className="text-xs text-gray-500">Click to apply. Tags help you filter and organise your library.</p>
      </div>

      {loading ? (
        <p className="text-xs text-gray-400 animate-pulse">Suggesting tags…</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {allSuggested.map((tag) => {
            const isOn = applied.has(tag);
            const isNew = suggested.new.includes(tag) && !suggested.existing.includes(tag);
            return (
              <button
                key={tag}
                onClick={() => toggle(tag)}
                disabled={adding}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  isOn
                    ? "bg-violet-600 text-white border-violet-600"
                    : "bg-white text-gray-700 border-gray-200 hover:border-violet-400 hover:text-violet-700"
                }`}
              >
                {isNew && !isOn && <span className="mr-1 text-violet-400">✦</span>}
                {tag}
                {isOn && <span className="ml-1">✓</span>}
              </button>
            );
          })}
        </div>
      )}

      {/* Applied tags summary */}
      {applied.size > 0 && (
        <p className="text-[11px] text-gray-400">{applied.size} tag{applied.size !== 1 ? "s" : ""} applied: {[...applied].join(", ")}</p>
      )}

      {/* Custom tag input */}
      <div className="flex gap-2">
        <input
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addCustom()}
          placeholder="Add a custom tag…"
          className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300"
        />
        <button
          onClick={addCustom}
          disabled={adding || !custom.trim()}
          className="px-3 py-1.5 text-xs bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
        >
          Add
        </button>
      </div>

      <div className="flex justify-between pt-2">
        <button onClick={onNext} className="text-xs text-gray-400 hover:text-gray-600">
          Skip
        </button>
        <button
          onClick={onNext}
          className="px-4 py-2 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

// ── Project step ─────────────────────────────────────────────────────────────

function ProjectStep({ paper, onNext }: { paper: T_IngestOut; onNext: () => void }) {
  const [projects, setProjects] = useState<{ id: string; name: string; description?: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [suggestedId, setSuggestedId] = useState<string | null>(null);

  useEffect(() => {
    listProjects()
      .then((ps) => {
        setProjects(ps);
        // Find best match
        let best: { id: string; score: number } | null = null;
        for (const p of ps) {
          const score = scoreProject(p, paper);
          if (score >= 3 && (!best || score > best.score)) best = { id: p.id, score };
        }
        if (best) { setSuggestedId(best.id); setSelectedId(best.id); }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [paper]);

  const handleAdd = async () => {
    if (!selectedId) return;
    setAdding(true);
    try {
      await addPaperToProject(selectedId, paper.id);
      setAdded(true);
    } catch { /* ignore */ }
    finally { setAdding(false); }
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-800 mb-1">Add to a project</p>
        <p className="text-xs text-gray-500">Group this paper with related work. You can add it to more projects later.</p>
      </div>

      {loading ? (
        <p className="text-xs text-gray-400 animate-pulse">Loading projects…</p>
      ) : projects.length === 0 ? (
        <p className="text-xs text-gray-400 italic">No projects yet — create one from the Projects page.</p>
      ) : (
        <div className="max-h-52 overflow-y-auto space-y-1.5 pr-1">
          {projects.map((p) => {
            const isSuggested = p.id === suggestedId;
            const isSelected = p.id === selectedId;
            return (
              <button
                key={p.id}
                onClick={() => setSelectedId(isSelected ? null : p.id)}
                disabled={added}
                className={`w-full text-left px-3 py-2.5 rounded-lg border text-xs transition-colors ${
                  isSelected
                    ? "border-violet-500 bg-violet-50 text-violet-800"
                    : "border-gray-200 bg-white text-gray-700 hover:border-violet-300 hover:bg-violet-50"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  {isSelected && <span className="text-violet-500">✓</span>}
                  <span className="font-medium">{p.name}</span>
                  {isSuggested && !added && (
                    <span className="ml-auto text-[10px] text-violet-500 font-semibold bg-violet-100 px-1.5 py-0.5 rounded-full">
                      ✦ Suggested
                    </span>
                  )}
                </div>
                {p.description && (
                  <p className="text-gray-400 mt-0.5 truncate">{p.description}</p>
                )}
              </button>
            );
          })}
        </div>
      )}

      {added && (
        <p className="text-xs text-green-600 font-medium">
          ✓ Added to "{projects.find((p) => p.id === selectedId)?.name}"
        </p>
      )}

      <div className="flex justify-between pt-2">
        <button onClick={onNext} className="text-xs text-gray-400 hover:text-gray-600">
          Skip
        </button>
        <div className="flex gap-2">
          {!added && selectedId && (
            <button
              onClick={handleAdd}
              disabled={adding}
              className="px-4 py-2 text-xs font-medium bg-white border border-violet-300 text-violet-700 rounded-lg hover:bg-violet-50 disabled:opacity-50"
            >
              {adding ? "Adding…" : "Add to project"}
            </button>
          )}
          <button
            onClick={onNext}
            className="px-4 py-2 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}

// ── People step ───────────────────────────────────────────────────────────────

function PeopleStep({ paper, onDone }: { paper: T_IngestOut; onDone: () => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>(INVOLVE_ROLES[0]);
  const [adding, setAdding] = useState(false);
  const [linked, setLinked] = useState<{ name: string; role: string }[]>([]);

  const handleAdd = async () => {
    const n = name.trim();
    if (!n) return;
    setAdding(true);
    try {
      const person = await getOrCreatePerson(n);
      await linkPersonInvolves(paper.id, person.id, role);
      setLinked((prev) => [...prev, { name: n, role }]);
      setName("");
    } catch { /* ignore */ }
    finally { setAdding(false); }
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-800 mb-1">People</p>
        <p className="text-xs text-gray-500">Authors were auto-extracted. Link additional people (colleagues, supervisor, who shared this with you…).</p>
      </div>

      {/* Authors already linked */}
      {paper.authors.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Authors (auto-extracted)</p>
          <div className="flex flex-wrap gap-1.5">
            {paper.authors.map((a) => (
              <span key={a} className="px-2.5 py-1 text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full">
                {a}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Newly linked people */}
      {linked.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {linked.map((p, i) => (
            <span key={i} className="px-2.5 py-1 text-xs bg-violet-50 text-violet-700 border border-violet-100 rounded-full">
              {p.name} · <span className="text-violet-400">{p.role.replace("_", " ")}</span>
            </span>
          ))}
        </div>
      )}

      {/* Add person form */}
      <div className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Person's name…"
          className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="border border-gray-200 rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
        >
          {INVOLVE_ROLES.map((r) => (
            <option key={r} value={r}>{r.replace("_", " ")}</option>
          ))}
        </select>
        <button
          onClick={handleAdd}
          disabled={adding || !name.trim()}
          className="px-3 py-1.5 text-xs bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
        >
          {adding ? "…" : "Link"}
        </button>
      </div>

      <div className="flex justify-between pt-2">
        <button onClick={onDone} className="text-xs text-gray-400 hover:text-gray-600">
          Skip
        </button>
        <button
          onClick={onDone}
          className="px-4 py-2 text-xs font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700"
        >
          Done
        </button>
      </div>
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────

export default function OnboardingModal({ paper, onClose }: Props) {
  const [step, setStep] = useState<Step>("tags");

  const next = () => {
    const idx = STEPS.indexOf(step);
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1]);
    else onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-100">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-semibold text-violet-500 uppercase tracking-wide mb-0.5">Paper added</p>
              <h2 className="text-sm font-semibold text-gray-900 leading-snug truncate" title={paper.title}>
                {paper.title}
              </h2>
            </div>
            <button
              onClick={onClose}
              className="shrink-0 text-gray-400 hover:text-gray-600 text-lg leading-none mt-0.5"
              title="Close"
            >
              ×
            </button>
          </div>
          <div className="mt-4">
            <StepBar current={step} />
          </div>
        </div>

        {/* Step content */}
        <div className="px-6 py-5">
          {step === "tags"    && <TagsStep    paper={paper} onNext={next} />}
          {step === "project" && <ProjectStep paper={paper} onNext={next} />}
          {step === "people"  && <PeopleStep  paper={paper} onDone={onClose} />}
        </div>
      </div>
    </div>
  );
}
