import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getSystemHealth } from "../api/insights";
import type { HealthCheck, OverallHealth, SystemHealth } from "../api/insights";
import { useAuth } from "../contexts/AuthContext";
import DataTable from "../components/insights/DataTable";
import StatusDot from "../components/insights/StatusDot";
import type { DotStatus } from "../components/insights/StatusDot";
import { Badge, Card, ErrorNote, PageHeader, Spinner, btnSecondary, errorMessage } from "../components/insights/ui";
import { formatDateTime, formatInt, formatInterval, formatTokens, formatUptime, formatUsd, relativeTime } from "../components/insights/format";

const REFRESH_MS = 60_000;

const BANNER: Record<OverallHealth, { dot: DotStatus; text: string; cls: string }> = {
  ok: { dot: "ok", text: "All systems normal", cls: "border-emerald-200 bg-emerald-50 text-emerald-800" },
  degraded: { dot: "warn", text: "Degraded: at least one check needs attention", cls: "border-amber-200 bg-amber-50 text-amber" },
  error: { dot: "error", text: "Error: at least one check is failing", cls: "border-red-200 bg-red-50 text-coral" },
};

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "none";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function CheckCard({ check }: { check: HealthCheck }) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(check.details ?? {});
  const panelId = `check-details-${check.id.replace(/[^a-z0-9_-]/gi, "-")}`;
  return (
    <li className="rounded-xl border border-line bg-raised p-4" data-testid={`check-${check.id}`}>
      <div className="flex items-start gap-2.5">
        <StatusDot status={check.status} className="mt-1.5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-ink">{check.label}</h3>
            {check.latency_ms !== null && check.latency_ms !== undefined ? (
              <span className="text-xs tabular-nums text-ink-3">{Math.round(check.latency_ms)} ms</span>
            ) : null}
          </div>
          <p className="mt-0.5 break-words text-sm text-ink-2">{check.summary}</p>
          {entries.length > 0 ? (
            <>
              <button
                type="button"
                aria-expanded={open}
                aria-controls={panelId}
                onClick={() => setOpen(!open)}
                className="mt-1.5 text-xs text-accent hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
              >
                {open ? "Hide details" : "Show details"}
              </button>
              {open ? (
                <dl id={panelId} className="mt-2 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
                  {entries.map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-ink-3">{k}</dt>
                      <dd className="break-words font-mono text-ink-2">{renderValue(v)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function HealthBody({ initialRefresh = false }: { initialRefresh?: boolean }) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const alive = useRef(true);
  const lastLoad = useRef(0);

  const load = useCallback((refresh: boolean) => {
    setRefreshing(true);
    return getSystemHealth(refresh)
      .then((h) => {
        if (!alive.current) return;
        lastLoad.current = Date.now();
        setHealth(h);
        setError(null);
      })
      .catch((e) => {
        if (alive.current) setError(errorMessage(e, "Could not load the system health"));
      })
      .finally(() => {
        if (alive.current) setRefreshing(false);
      });
  }, []);

  useEffect(() => {
    alive.current = true;
    void load(initialRefresh);
    const tick = () => {
      if (!document.hidden) void load(false);
    };
    const timer = setInterval(tick, REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden && Date.now() - lastLoad.current >= REFRESH_MS) void load(false);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive.current = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load, initialRefresh]);

  const banner = health ? BANNER[health.status] : null;

  return (
    <>
      <PageHeader
        title="System health"
        description="Whether the backend, the database, the AI providers and the background jobs are up and keeping pace."
        actions={
          <button type="button" className={btnSecondary} disabled={refreshing} onClick={() => void load(true)}>
            {refreshing ? "Refreshing" : "Refresh"}
          </button>
        }
      />

      {error ? <ErrorNote message={error} onRetry={() => void load(false)} /> : null}
      {!health && !error ? <Spinner label="Running the checks" /> : null}

      {health && banner ? (
        <div className="space-y-5">
          <div role="status" className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm font-medium ${banner.cls}`}>
            <StatusDot status={banner.dot} />
            <span>{banner.text}</span>
            <span className="ml-auto text-xs font-normal opacity-80" title={health.generated_at}>
              Checked {formatDateTime(health.generated_at)} ({relativeTime(health.generated_at)}). Refreshes every minute while this tab is open.
            </span>
          </div>

          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Checks">
            {health.checks.map((c) => (
              <CheckCard key={c.id} check={c} />
            ))}
          </ul>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Background sweepers">
              <DataTable
                caption="Background sweepers"
                rows={health.sweepers}
                rowKey={(s) => s.name}
                empty="Sweepers (concept map, embeddings, conference build) will be listed here once they report in."
                columns={[
                  { header: "Name", cell: (s) => s.name },
                  { header: "Alive", cell: (s) => (s.alive ? <Badge tone="ok">alive</Badge> : <Badge tone="error">stopped</Badge>) },
                  { header: "Last run", cell: (s) => relativeTime(s.last_run) },
                  { header: "Every", align: "right", cell: (s) => formatInterval(s.interval_s) },
                  { header: "Last error", cell: (s) => (s.last_error ? <span className="break-words text-coral">{s.last_error}</span> : <span className="text-ink-3">none</span>) },
                ]}
              />
            </Card>

            <Card title="Token spend today" aside={<Link to="/tokens" className="text-accent hover:underline">Open Tokens</Link>}>
              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div><dt className="text-xs text-ink-3">Spend</dt><dd className="text-lg font-semibold tabular-nums text-ink">{formatUsd(health.tokens_today.cost_usd)}</dd></div>
                <div><dt className="text-xs text-ink-3">Calls</dt><dd className="text-lg font-semibold tabular-nums text-ink">{formatInt(health.tokens_today.calls)}</dd></div>
                <div><dt className="text-xs text-ink-3">Errors</dt><dd className={`text-lg font-semibold tabular-nums ${health.tokens_today.errors > 0 ? "text-coral" : "text-ink"}`}>{formatInt(health.tokens_today.errors)}</dd></div>
                <div><dt className="text-xs text-ink-3">Tokens in / out</dt><dd className="text-lg font-semibold tabular-nums text-ink">{formatTokens(health.tokens_today.input_tokens)} / {formatTokens(health.tokens_today.output_tokens)}</dd></div>
              </dl>
            </Card>
          </div>

          <Card
            title="Recent errors"
            aside={
              health.recent_errors.length > 0 ? (
                <button type="button" aria-expanded={showErrors} onClick={() => setShowErrors(!showErrors)} className="text-accent hover:underline">
                  {showErrors ? "Collapse" : `Show ${health.recent_errors.length}`}
                </button>
              ) : undefined
            }
          >
            {health.recent_errors.length === 0 ? (
              <p className="text-sm text-ink-3">No ERROR or CRITICAL lines in the recent log. Any that appear will be listed here, newest first.</p>
            ) : showErrors ? (
              <ul className="space-y-1.5 font-mono text-xs">
                {health.recent_errors.map((e, i) => (
                  <li key={`${e.ts}-${i}`} className="break-words rounded bg-line-s px-2 py-1 text-ink-2">
                    <span className="text-ink-3">{e.ts}</span> <span className="text-coral">{e.level}</span> <span className="text-ink-3">{e.logger}</span> {e.message}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="break-words font-mono text-xs text-ink-2" title={health.recent_errors[0].message}>
                <span className="text-ink-3">{health.recent_errors[0].ts}</span> {health.recent_errors[0].message.slice(0, 160)}
              </p>
            )}
          </Card>

          <Card title="Audit" aside={`${formatInt(health.audit.actions_24h)} actions in 24 h`}>
            <DataTable
              caption="Latest audit entries"
              rows={health.audit.last}
              rowKey={(a, i) => `${a.ts}-${i}`}
              empty="User actions (uploads, edits, deletes) will be listed here."
              columns={[
                { header: "Time", cell: (a) => <span className="whitespace-nowrap">{formatDateTime(a.ts)}</span> },
                { header: "User", cell: (a) => a.username },
                { header: "Action", cell: (a) => a.action_type },
                { header: "Entity", cell: (a) => a.entity_type },
              ]}
            />
          </Card>

          <footer className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3" aria-label="Version">
            <span>App {health.version.app}</span>
            <span>Commit {health.version.git_sha ? health.version.git_sha.slice(0, 7) : "unknown"}</span>
            <span>Branch {health.version.git_branch ?? "unknown"}</span>
            <span>Python {health.version.python}</span>
            <span>Up {formatUptime(health.version.uptime_s)}</span>
          </footer>
        </div>
      ) : null}
    </>
  );
}

export default function Health() {
  const { isAdmin, isLoading } = useAuth();
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      {isAdmin ? (
        <HealthBody />
      ) : isLoading ? (
        <Spinner label="Checking your access" />
      ) : (
        <>
          <PageHeader title="System health" description="Whether the backend, the database, the AI providers and the background jobs are up." />
          <p role="alert" className="rounded-xl border border-line bg-raised px-5 py-8 text-center text-sm text-ink-2">
            Only admins can see the system health.
          </p>
        </>
      )}
    </div>
  );
}
