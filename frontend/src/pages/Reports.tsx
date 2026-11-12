import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAuth } from "../contexts/AuthContext";
import { createReport, getReportOptions, listReports } from "../api/insights";
import type { ReportLength, ReportOptions, ReportSummary } from "../api/insights";
import { StatusBadge, isActiveStatus } from "../components/insights/ReportStatus";
import { Card, EmptyState, ErrorNote, PageHeader, ProgressBar, Segmented, Spinner, btnPrimary, errorMessage, inputCls } from "../components/insights/ui";
import { formatDate, formatInt } from "../components/insights/format";

const POLL_MS = 2500;
const LENGTHS: { value: ReportLength; label: string }[] = [
  { value: "short", label: "Short" },
  { value: "standard", label: "Standard" },
  { value: "long", label: "Long" },
];

interface ProjectOption {
  id: string;
  name: string;
}

function NewReportForm({ onCreated }: { onCreated: (r: ReportSummary) => void }) {
  const [question, setQuestion] = useState("");
  const [projectId, setProjectId] = useState("");
  const [length, setLength] = useState<ReportLength>("standard");
  const [model, setModel] = useState("");
  const [options, setOptions] = useState<ReportOptions | null>(null);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getReportOptions()
      .then((o) => {
        if (!live) return;
        setOptions(o);
        setModel((m) => m || o.default_model);
      })
      .catch(() => {
        /* the form still works with the server's default model */
      });
    Promise.resolve(apiFetch<ProjectOption[]>("/projects"))
      .then((p) => {
        if (live && Array.isArray(p)) setProjects(p);
      })
      .catch(() => {
        /* the project is optional */
      });
    return () => {
      live = false;
    };
  }, []);

  const canSubmit = (question.trim().length > 0 || projectId !== "") && !submitting;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const body: Parameters<typeof createReport>[0] = { length };
      if (question.trim()) body.question = question.trim();
      if (projectId) body.project_id = projectId;
      if (model) body.model = model;
      const created = await createReport(body);
      onCreated(created);
      setQuestion("");
    } catch (err) {
      setError(errorMessage(err, "Could not start the report"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card title="New report">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="report-question" className="mb-1 block text-sm font-medium text-ink">
            Question
          </label>
          <textarea
            id="report-question"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What do my papers say about..."
            className={`${inputCls} w-full resize-y`}
          />
          <p className="mt-1 text-xs text-ink-3">The report is written from your library and cites its papers. A project can stand in for the question.</p>
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="report-project" className="mb-1 block text-sm font-medium text-ink">
              Project <span className="font-normal text-ink-3">(optional)</span>
            </label>
            <select id="report-project" value={projectId} onChange={(e) => setProjectId(e.target.value)} className={`${inputCls} min-w-[12rem]`}>
              <option value="">Whole library</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium text-ink">Length</span>
            <Segmented label="Length" value={length} options={LENGTHS} onChange={setLength} />
          </div>
          {options ? (
            <div>
              <label htmlFor="report-model" className="mb-1 block text-sm font-medium text-ink">
                Model
              </label>
              <select id="report-model" value={model} onChange={(e) => setModel(e.target.value)} className={`${inputCls} min-w-[12rem]`}>
                {options.models.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.label}
                    {m.available ? "" : " (not configured)"}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <button type="submit" className={`${btnPrimary} ml-auto`} disabled={!canSubmit}>
            {submitting ? "Starting" : "Write report"}
          </button>
        </div>
        {error ? <ErrorNote message={error} /> : null}
      </form>
    </Card>
  );
}

function ReportRow({ report, showOwner }: { report: ReportSummary; showOwner: boolean }) {
  const active = isActiveStatus(report.status);
  const title = report.title || report.question || "Untitled report";
  return (
    <li className="relative rounded-xl border border-line bg-raised px-4 py-3 hover:border-accent-border focus-within:border-accent">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Link
          to={`/reports/${report.id}`}
          className="min-w-0 flex-1 text-base font-semibold text-ink after:absolute after:inset-0 after:content-[''] focus:outline-none"
        >
          {title}
        </Link>
        <StatusBadge status={report.status} />
      </div>
      {report.title && report.question ? <p className="mt-0.5 line-clamp-2 text-sm text-ink-2">{report.question}</p> : null}
      <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-ink-3">
        {report.project_name ? <span>Project: {report.project_name}</span> : null}
        {showOwner ? <span>By {report.owner}</span> : null}
        <span>{formatDate(report.created_at)}</span>
        {report.status === "done" ? (
          <>
            <span>{formatInt(report.paper_count)} papers</span>
            <span>{formatInt(report.word_count)} words</span>
          </>
        ) : null}
      </p>
      {active ? (
        <div className="mt-2">
          <ProgressBar value={report.progress} label={`Progress of ${title}`} />
          <p className="mt-1 text-xs text-ink-3">
            {report.stage || (report.status === "queued" ? "Waiting for a free slot" : "Working")} ({Math.round(report.progress)}%)
          </p>
        </div>
      ) : null}
      {report.status === "failed" && report.error ? <p className="mt-2 break-words text-sm text-coral">{report.error}</p> : null}
    </li>
  );
}

export default function Reports() {
  const { isAdmin } = useAuth();
  const [all, setAll] = useState(false);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(
    (quiet = false) => {
      const id = ++seq.current;
      if (!quiet) setError(null);
      return listReports(all)
        .then((r) => {
          if (id === seq.current) {
            setReports(r);
            setError(null);
          }
        })
        .catch((e) => {
          if (id === seq.current && !quiet) setError(errorMessage(e, "Could not load reports"));
        });
    },
    [all],
  );

  useEffect(() => {
    setReports(null);
    void load();
  }, [load]);

  const anyActive = useMemo(() => (reports ?? []).some((r) => isActiveStatus(r.status)), [reports]);

  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => void load(true), POLL_MS);
    return () => clearInterval(t);
  }, [anyActive, load]);

  const created = (r: ReportSummary) => setReports((prev) => [r, ...(prev ?? []).filter((x) => x.id !== r.id)]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Reports"
        description="Long reads written from your library, with every claim linked to the paper behind it."
        actions={
          isAdmin ? (
            <label className="flex items-center gap-2 text-sm text-ink-2">
              <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="accent-accent" />
              All users
            </label>
          ) : null
        }
      />
      <NewReportForm onCreated={created} />
      <h2 className="mb-3 mt-8 text-base font-semibold text-ink">{all ? "All reports" : "Your reports"}</h2>
      {error ? <ErrorNote message={error} onRetry={() => void load()} /> : null}
      {reports === null && !error ? <Spinner label="Loading reports" /> : null}
      {reports && reports.length === 0 ? (
        <EmptyState title="No reports yet">Ask a question above. The finished report will appear here, and you can export it as Markdown or HTML.</EmptyState>
      ) : null}
      {reports && reports.length > 0 ? (
        <ul className="space-y-3" aria-label="Reports">
          {reports.map((r) => (
            <ReportRow key={r.id} report={r} showOwner={all} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
