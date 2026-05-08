import { useEffect, useRef, useState } from "react";
import {
  suggestTags, createTag, listProjects, addPaperToProject,
  apiFetch, getOrCreatePerson, linkPersonInvolves,
} from "../api/client";
import type { T_IngestOut } from "../types";

type Step = "tags" | "project" | "people";

const STEPS: Step[] = ["tags", "project", "people"];

const STEP_META: Record<Step, { title: string; subtitle: string }> = {
  tags:    { title: "Add tags",       subtitle: "Click to apply. Tags help you filter and organise your library." },
  project: { title: "Add to project", subtitle: "Group this paper with related work. You can add it to more projects later." },
  people:  { title: "Link people",    subtitle: "Authors were auto-extracted. Link additional people — colleague, supervisor, who shared this…" },
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

// ── Step dots (matches UploadConfirmModal) ────────────────────────────────────

function StepDots({ current }: { current: Step }) {
  const idx = STEPS.indexOf(current);
  return (
    <div className="flex gap-1 items-center">
      {STEPS.map((_, i) => (
        <span
          key={i}
          className={`w-1.5 h-1.5 rounded-full transition-colors ${
            i === idx ? "bg-accent" : i < idx ? "bg-violet-300" : "bg-line"
          }`}
        />
      ))}
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
        const current = await apiFetch<{ id: string; name: string }[]>(`/papers/${paper.id}/tags`);
        setApplied(new Set(current.map((t) => t.name)));
        const res = await suggestTags(paper.title, paper.abstract);
        setSuggested({ existing: res.existing, new: res.new });
      } catch { /* ignore */ }
      finally { setLoading(false); }
    };
    loadTags();
  }, [paper.id, paper.title, paper.abstract]);

  const toggle = async (name: string) => {
    if (applied.has(name)) return;
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
    <>
      <div className="px-6 py-4 space-y-3">
        {loading ? (
          <p className="text-xs text-ink-3 animate-pulse">Suggesting tags…</p>
        ) : allSuggested.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {allSuggested.map((tag) => {
              const isOn = applied.has(tag);
              const isNew = suggested.new.includes(tag) && !suggested.existing.includes(tag);
              return (
                <button
                  key={tag}
                  onClick={() => toggle(tag)}
                  disabled={adding || isOn}
                  className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                    isOn
                      ? "bg-accent text-white border-accent"
                      : "bg-raised text-ink-2 border-line hover:border-accent-border hover:text-accent"
                  }`}
                >
                  {isNew && !isOn && <span className="mr-1 text-violet-400">✦</span>}
                  {tag}
                  {isOn && <span className="ml-1">✓</span>}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-ink-3">No suggestions — add a custom tag below.</p>
        )}

        {applied.size > 0 && (
          <p className="text-xs text-ink-3">
            {applied.size} tag{applied.size !== 1 ? "s" : ""} applied: {[...applied].join(", ")}
          </p>
        )}

        <div className="flex gap-2">
          <input
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCustom()}
            placeholder="Add a custom tag…"
            className="flex-1 border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          <button
            onClick={addCustom}
            disabled={adding || !custom.trim()}
            className="px-3 py-1.5 text-sm bg-accent text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>

      <div className="px-6 py-4 border-t border-line-s flex justify-end gap-2">
        <button onClick={onNext} className="px-4 py-2 text-sm text-ink-3 hover:text-ink">Skip</button>
        <button
          onClick={onNext}
          className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700"
        >
          Next →
        </button>
      </div>
    </>
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
    <>
      <div className="px-6 py-4 space-y-3">
        {loading ? (
          <p className="text-xs text-ink-3 animate-pulse">Loading projects…</p>
        ) : projects.length === 0 ? (
          <p className="text-xs text-ink-3 italic">No projects yet — create one from the Projects page.</p>
        ) : (
          <div className="max-h-52 overflow-y-auto space-y-1.5 pr-1">
            {projects.map((p) => {
              const isSuggested = p.id === suggestedId;
              const isSelected = p.id === selectedId;
              return (
                <button
                  key={p.id}
                  onClick={() => { if (!added) setSelectedId(isSelected ? null : p.id); }}
                  disabled={added}
                  className={`w-full text-left px-3 py-2.5 rounded-lg border text-xs transition-colors ${
                    isSelected
                      ? "border-accent bg-accent-lo text-violet-800"
                      : "border-line bg-raised text-ink-2 hover:border-accent-border hover:bg-accent-lo disabled:opacity-60"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    {isSelected && <span className="text-accent">✓</span>}
                    <span className="font-medium">{p.name}</span>
                    {isSuggested && !added && (
                      <span className="ml-auto text-[10px] text-accent font-semibold bg-accent-lo px-1.5 py-0.5 rounded-full">
                        ✦ Suggested
                      </span>
                    )}
                  </div>
                  {p.description && <p className="text-ink-3 mt-0.5 truncate">{p.description}</p>}
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
      </div>

      <div className="px-6 py-4 border-t border-line-s flex justify-end gap-2">
        <button onClick={onNext} className="px-4 py-2 text-sm text-ink-3 hover:text-ink">
          {added ? "Next →" : "Skip"}
        </button>
        {!added && selectedId && (
          <button
            onClick={handleAdd}
            disabled={adding}
            className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700 disabled:opacity-50"
          >
            {adding ? "Adding…" : "Add to project"}
          </button>
        )}
        {added && (
          <button onClick={onNext} className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700">
            Next →
          </button>
        )}
      </div>
    </>
  );
}

// ── People step ───────────────────────────────────────────────────────────────

function PeopleStep({ paper, onDone }: { paper: T_IngestOut; onDone: () => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>(INVOLVE_ROLES[0]);
  const [adding, setAdding] = useState(false);
  const [linked, setLinked] = useState<{ name: string; role: string }[]>([]);
  const [allPeople, setAllPeople] = useState<{ id: string; name: string; affiliation?: string }[]>([]);
  const [suggestions, setSuggestions] = useState<{ id: string; name: string; affiliation?: string }[]>([]);

  useEffect(() => {
    apiFetch<{ id: string; name: string; affiliation?: string }[]>("/people")
      .then(setAllPeople).catch(() => {});
  }, []);

  const linkPerson = async (personId: string, personName: string) => {
    setAdding(true);
    try {
      await linkPersonInvolves(paper.id, personId, role);
      setLinked((prev) => [...prev, { name: personName, role }]);
      setName("");
      setSuggestions([]);
    } catch { /* ignore */ }
    finally { setAdding(false); }
  };

  const handleAdd = async () => {
    const n = name.trim();
    if (!n) return;
    setAdding(true);
    try {
      const person = await getOrCreatePerson(n);
      await linkPersonInvolves(paper.id, person.id, role);
      setLinked((prev) => [...prev, { name: n, role }]);
      setName("");
      setSuggestions([]);
    } catch { /* ignore */ }
    finally { setAdding(false); }
  };

  return (
    <>
      <div className="px-6 py-4 space-y-3">
        {paper.authors.length > 0 && (
          <div>
            <p className="text-xs font-medium text-ink-3 uppercase tracking-wide mb-1.5">Authors (auto-extracted)</p>
            <div className="flex flex-wrap gap-1.5">
              {paper.authors.map((a) => (
                <span key={a} className="px-2.5 py-1 text-xs bg-accent-lo text-accent border border-accent-border rounded-full">
                  {a}
                </span>
              ))}
            </div>
          </div>
        )}

        {linked.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {linked.map((p, i) => (
              <span key={i} className="px-2.5 py-1 text-xs bg-accent-lo text-accent border border-accent-border rounded-full">
                {p.name} · <span className="text-violet-400">{p.role.replace("_", " ")}</span>
              </span>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <div className="relative flex-1">
            <input
              value={name}
              onChange={(e) => {
                const val = e.target.value;
                setName(val);
                setSuggestions(
                  val.trim()
                    ? allPeople.filter((p) => p.name.toLowerCase().includes(val.toLowerCase())).slice(0, 6)
                    : []
                );
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") { setSuggestions([]); return; }
                if (e.key === "Enter") handleAdd();
              }}
              onBlur={() => setTimeout(() => setSuggestions([]), 150)}
              placeholder="Person's name…"
              className="w-full border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            {suggestions.length > 0 && (
              <ul className="absolute z-20 top-full mt-0.5 left-0 right-0 bg-white border border-gray-200 rounded shadow-lg overflow-hidden text-xs">
                {suggestions.map((s) => (
                  <li key={s.id}>
                    <button
                      onMouseDown={(e) => { e.preventDefault(); linkPerson(s.id, s.name); }}
                      className="w-full text-left px-3 py-2 hover:bg-violet-50 transition-colors"
                    >
                      <span className="font-medium text-gray-800">{s.name}</span>
                      {s.affiliation && <span className="text-gray-400 ml-1.5">{s.affiliation}</span>}
                    </button>
                  </li>
                ))}
                <li className="border-t border-gray-100">
                  <button
                    onMouseDown={(e) => { e.preventDefault(); handleAdd(); }}
                    className="w-full text-left px-3 py-2 hover:bg-gray-50 text-gray-400 transition-colors"
                  >
                    + Add "{name}" as new person
                  </button>
                </li>
              </ul>
            )}
          </div>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="border border-line rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-raised text-ink-2"
          >
            {INVOLVE_ROLES.map((r) => (
              <option key={r} value={r}>{r.replace("_", " ")}</option>
            ))}
          </select>
          <button
            onClick={handleAdd}
            disabled={adding || !name.trim()}
            className="px-3 py-1.5 text-sm bg-accent text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {adding ? "…" : "Link"}
          </button>
        </div>
      </div>

      <div className="px-6 py-4 border-t border-line-s flex justify-end gap-2">
        <button onClick={onDone} className="px-4 py-2 text-sm text-ink-3 hover:text-ink">Skip</button>
        <button onClick={onDone} className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700">
          Done ✓
        </button>
      </div>
    </>
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

  const { title, subtitle } = STEP_META[step];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-raised rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Shared header */}
        <div className="px-6 py-4 border-b border-line-s">
          <div className="flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-semibold text-accent uppercase tracking-wide mb-0.5">Paper added</p>
              <h2 className="text-sm font-semibold text-ink leading-snug truncate" title={paper.title}>
                {paper.title}
              </h2>
            </div>
            <button
              onClick={onClose}
              className="shrink-0 text-ink-3 hover:text-ink-2 text-lg leading-none mt-0.5"
              title="Close"
            >
              ×
            </button>
          </div>

          {/* Step indicator */}
          <div className="mt-3 flex items-center gap-2">
            <StepDots current={step} />
            <span className="text-xs font-semibold text-ink">{title}</span>
          </div>
          <p className="text-xs text-ink-3 mt-0.5">{subtitle}</p>
        </div>

        {/* Step content */}
        {step === "tags"    && <TagsStep    paper={paper} onNext={next} />}
        {step === "project" && <ProjectStep paper={paper} onNext={next} />}
        {step === "people"  && <PeopleStep  paper={paper} onDone={onClose} />}
      </div>
    </div>
  );
}
