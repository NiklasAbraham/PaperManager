import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { cancelReport, deleteReport, downloadReport, getReport } from "../api/insights";
import type { ReportDetail } from "../api/insights";
import ReportMarkdown from "../components/insights/ReportMarkdown";
import { Badge, Card, ErrorNote, ProgressBar, Spinner, btnDanger, btnSecondary, errorMessage } from "../components/insights/ui";
import { formatDate, formatDateTime, formatInt } from "../components/insights/format";
import { StatusBadge, isActiveStatus } from "../components/insights/ReportStatus";

const POLL_MS = 2500;

export default function ReportView() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const req = useRef(0);

  const load = useCallback(
    (silent = false) => {
      const n = ++req.current;
      if (!silent) setError(null);
      return getReport(id)
        .then((r) => {
          if (n === req.current) setReport(r);
        })
        .catch((e) => {
          if (n === req.current && !silent) setError(errorMessage(e, "Could not load the report"));
        });
    },
    [id],
  );

  useEffect(() => {
    setReport(null);
    void load();
  }, [load]);

  const polling = report ? isActiveStatus(report.status) : false;
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => void load(true), POLL_MS);
    return () => clearInterval(t);
  }, [polling, load]);

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(errorMessage(e, `Could not ${name}`));
    } finally {
      setBusy(null);
    }
  };

  const onCancel = () =>
    run("cancel the report", async () => {
      const s = await cancelReport(id);
      setReport((prev) => (prev ? { ...prev, ...s } : prev));
    });

  const onDelete = () => {
    if (!window.confirm("Delete this report? This cannot be undone.")) return;
    void run("delete the report", async () => {
      await deleteReport(id);
      navigate("/reports");
    });
  };

  const back = (
    <Link to="/reports" className="text-sm text-ink-2 hover:text-accent">
      &larr; All reports
    </Link>
  );

  if (error) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-4">{back}</div>
        <ErrorNote message={error} onRetry={() => void load()} />
      </div>
    );
  }
  if (!report) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-4">{back}</div>
        <Spinner label="Loading report" />
      </div>
    );
  }

  const heading = report.title || report.question || "Untitled report";
  const active = isActiveStatus(report.status);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-4">{back}</div>
      <header className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="min-w-0 text-2xl font-bold text-ink">{heading}</h1>
          <StatusBadge status={report.status} />
        </div>
        {report.title && report.question ? <p className="mt-2 max-w-[70ch] text-sm text-ink-2">{report.question}</p> : null}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
          {report.project_name ? <span>Project: {report.project_name}</span> : null}
          <span>Model: {report.model}</span>
          <span>Length: {report.length}</span>
          <span>{formatDate(report.created_at)}</span>
          {report.word_count > 0 ? <span>{formatInt(report.word_count)} words</span> : null}
          {report.paper_count > 0 ? <span>{formatInt(report.paper_count)} papers</span> : null}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {active ? (
            <button type="button" className={btnSecondary} onClick={onCancel} disabled={busy !== null}>
              Cancel
            </button>
          ) : null}
          {report.status === "done" ? (
            <>
              <button type="button" className={btnSecondary} disabled={busy !== null} onClick={() => run("export the report", () => downloadReport(id, "md"))}>
                Export Markdown
              </button>
              <button type="button" className={btnSecondary} disabled={busy !== null} onClick={() => run("export the report", () => downloadReport(id, "html"))}>
                Export HTML
              </button>
            </>
          ) : null}
          <button type="button" className={btnDanger} onClick={onDelete} disabled={busy !== null}>
            Delete
          </button>
        </div>
        {actionError ? (
          <div className="mt-3">
            <ErrorNote message={actionError} />
          </div>
        ) : null}
      </header>

      {active ? (
        <Card title={report.status === "queued" ? "Waiting for a free slot" : "Writing the report"} aside={`${Math.round(report.progress)}%`}>
          <ProgressBar value={report.progress} label="Report progress" />
          {report.stage ? <p className="mt-2 text-sm text-ink-2">{report.stage}</p> : null}
          {report.steps.length > 0 ? (
            <ol aria-label="Steps" className="mt-3 max-h-56 space-y-1 overflow-y-auto text-xs text-ink-2">
              {report.steps.map((s, i) => (
                <li key={`${s.ts}-${i}`} className="flex gap-2">
                  <span className="shrink-0 tabular-nums text-ink-3">{formatDateTime(s.ts)}</span>
                  <span className="min-w-0 break-words">{s.message}</span>
                </li>
              ))}
            </ol>
          ) : null}
        </Card>
      ) : null}

      {report.status === "failed" ? (
        <div className="space-y-3">
          <ErrorNote message={report.error || "The report failed."} />
        </div>
      ) : null}
      {report.status === "cancelled" ? <p className="text-sm text-ink-2">This report was cancelled.</p> : null}

      {report.status === "done" ? (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <article aria-label="Report">
            {report.markdown ? <ReportMarkdown markdown={report.markdown.replace(/^# [^\n]*\n+/, "")} /> : <p className="text-sm text-ink-2">The report has no text.</p>}
          </article>
          <aside aria-label="Cited papers" className="lg:sticky lg:top-6 lg:self-start">
            <h2 className="mb-2 text-sm font-semibold text-ink">
              Cited papers <Badge>{report.papers.length}</Badge>
            </h2>
            {report.papers.length === 0 ? (
              <p className="text-sm text-ink-3">No library papers were cited.</p>
            ) : (
              <ol className="space-y-2 text-sm">
                {[...report.papers]
                  .sort((a, b) => a.n - b.n)
                  .map((p) => (
                    <li key={p.id} className="flex gap-2">
                      <span className="w-6 shrink-0 text-right tabular-nums text-ink-3">{p.n}</span>
                      <span className="min-w-0">
                        <Link to={`/paper/${p.id}`} className="text-accent hover:underline">
                          {p.title}
                        </Link>
                        {p.year ? <span className="text-ink-3"> ({p.year})</span> : null}
                      </span>
                    </li>
                  ))}
              </ol>
            )}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
