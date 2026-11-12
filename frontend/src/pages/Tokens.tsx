import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getTokenCalls, getTokenPrices, getTokenSummary } from "../api/insights";
import type { TokenCallRow, TokenPrices, TokenSummary } from "../api/insights";
import BarChart from "../components/insights/BarChart";
import type { Bar } from "../components/insights/BarChart";
import DataTable from "../components/insights/DataTable";
import type { Column } from "../components/insights/DataTable";
import StatRow from "../components/insights/StatRow";
import { Badge, Card, EmptyState, ErrorNote, PageHeader, Segmented, Spinner, btnSecondary, errorMessage, inputCls } from "../components/insights/ui";
import { formatCost, formatDate, formatDateTime, formatInt, formatLatency, formatTokens, formatUsd } from "../components/insights/format";

const RANGES = [
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
];
const PAGE = 50;

function shortDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

function CallsTable({ caption, calls, empty }: { caption: string; calls: TokenCallRow[]; empty: string }) {
  const columns: Column<TokenCallRow>[] = [
    { header: "Time", cell: (c) => <span className="whitespace-nowrap">{formatDateTime(c.ts)}</span> },
    { header: "Feature", cell: (c) => <span title={c.label}>{c.feature}</span> },
    { header: "Model", cell: (c) => <span className="break-all">{c.model}</span> },
    { header: "User", cell: (c) => c.user ?? "(system)" },
    {
      header: "Tokens",
      align: "right",
      cell: (c) => (
        <span title={`${formatInt(c.input_tokens)} in, ${formatInt(c.output_tokens)} out`}>
          {formatTokens(c.input_tokens)} / {formatTokens(c.output_tokens)}
        </span>
      ),
    },
    { header: "Cost", align: "right", cell: (c) => formatCost(c.cost_usd, c.provider, c.price_known) },
    { header: "Latency", align: "right", cell: (c) => formatLatency(c.latency_ms) },
    {
      header: "Status",
      cell: (c) =>
        c.ok ? (
          <span className="text-ink-3">ok</span>
        ) : (
          <span title={c.error ?? "error"}>
            <Badge tone="error">error</Badge>
          </span>
        ),
    },
  ];
  return <DataTable caption={caption} columns={columns} rows={calls} rowKey={(c) => c.id} empty={empty} />;
}

export default function Tokens() {
  const [days, setDays] = useState(30);
  const [user, setUser] = useState("");
  const [feature, setFeature] = useState("");
  const [model, setModel] = useState("");

  const [summary, setSummary] = useState<TokenSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [calls, setCalls] = useState<TokenCallRow[]>([]);
  const [callsTotal, setCallsTotal] = useState(0);
  const [callsLoading, setCallsLoading] = useState(true);
  const [callsError, setCallsError] = useState<string | null>(null);

  const [prices, setPrices] = useState<TokenPrices | null>(null);
  const [showPrices, setShowPrices] = useState(false);
  const [pricesError, setPricesError] = useState<string | null>(null);

  // Filter choices come from every response seen so far, so choosing one does not empty the others.
  const [options, setOptions] = useState<{ users: string[]; features: string[]; models: string[] }>({ users: [], features: [], models: [] });
  const seq = useRef(0);
  const callSeq = useRef(0);

  const params = useMemo(
    () => ({ days, user: user || undefined, feature: feature || undefined, model: model || undefined }),
    [days, user, feature, model],
  );

  const loadSummary = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    getTokenSummary(params)
      .then((s) => {
        if (id !== seq.current) return;
        setSummary(s);
        setOptions((o) => ({
          users: [...new Set([...o.users, ...s.by_user.map((r) => r.user)])].sort(),
          features: [...new Set([...o.features, ...s.by_feature.map((r) => r.feature)])].sort(),
          models: [...new Set([...o.models, ...s.by_model.map((r) => r.model)])].sort(),
        }));
      })
      .catch((e) => {
        if (id === seq.current) setError(errorMessage(e, "Could not load the token summary"));
      })
      .finally(() => {
        if (id === seq.current) setLoading(false);
      });
  }, [params]);

  const loadCalls = useCallback(
    (append: boolean, offset: number) => {
      const id = ++callSeq.current;
      setCallsLoading(true);
      setCallsError(null);
      getTokenCalls({ ...params, limit: PAGE, offset })
        .then((r) => {
          if (id !== callSeq.current) return;
          setCalls((prev) => (append ? [...prev, ...r.calls] : r.calls));
          setCallsTotal(r.total);
        })
        .catch((e) => {
          if (id === callSeq.current) setCallsError(errorMessage(e, "Could not load calls"));
        })
        .finally(() => {
          if (id === callSeq.current) setCallsLoading(false);
        });
    },
    [params],
  );

  useEffect(() => {
    loadSummary();
    loadCalls(false, 0);
  }, [loadSummary, loadCalls]);

  const togglePrices = () => {
    const next = !showPrices;
    setShowPrices(next);
    if (next && !prices) {
      getTokenPrices().then(setPrices).catch((e) => setPricesError(errorMessage(e, "Could not load prices")));
    }
  };

  const isAdmin = summary?.scope.is_admin ?? false;
  const weekly = days >= 90;

  const bars: Bar[] = useMemo(() => {
    if (!summary) return [];
    const rows = weekly ? summary.by_week : summary.by_day;
    return rows.map((r) => {
      const day = "day" in r ? r.day : r.start;
      const when = "day" in r ? formatDate(r.day) : `week of ${formatDate(r.start)}`;
      return {
        key: day,
        label: shortDay(day),
        value: r.cost_usd,
        title: `${when}: ${formatInt(r.calls)} calls, ${formatTokens(r.input_tokens + r.output_tokens)} tokens, ${formatUsd(r.cost_usd)}`,
      };
    });
  }, [summary, weekly]);

  const t = summary?.totals;
  const hasSubscription = (t?.subscription_usd ?? 0) > 0;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Tokens"
        description="Every LLM call this instance made, with what it cost at list price."
        actions={
          <>
            <Segmented label="Time range" value={days} options={RANGES} onChange={setDays} />
            <button type="button" className={btnSecondary} onClick={() => { loadSummary(); loadCalls(false, 0); }}>
              Refresh
            </button>
          </>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        {isAdmin && options.users.length > 0 ? (
          <label className="flex items-center gap-2 text-sm text-ink-2">
            User
            <select className={inputCls} value={user} onChange={(e) => setUser(e.target.value)}>
              <option value="">All users</option>
              {options.users.filter((u) => u !== "(system)").map((u) => (
                <option key={u} value={u}>{u}</option>
              ))}
            </select>
          </label>
        ) : null}
        {options.features.length > 0 ? (
          <label className="flex items-center gap-2 text-sm text-ink-2">
            Feature
            <select className={inputCls} value={feature} onChange={(e) => setFeature(e.target.value)}>
              <option value="">All features</option>
              {options.features.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </label>
        ) : null}
        {options.models.length > 0 ? (
          <label className="flex items-center gap-2 text-sm text-ink-2">
            Model
            <select className={inputCls} value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">All models</option>
              {options.models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
        ) : null}
        {(user || feature || model) ? (
          <button type="button" className="text-sm text-accent hover:underline" onClick={() => { setUser(""); setFeature(""); setModel(""); }}>
            Clear filters
          </button>
        ) : null}
      </div>

      {error ? <ErrorNote message={error} onRetry={loadSummary} /> : null}
      {!summary && loading ? <Spinner label="Loading token usage" /> : null}

      {summary && t ? (
        <div className={`space-y-5 transition-opacity ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
          <StatRow
            label="Totals"
            stats={[
              {
                label: `Spend, last ${summary.range.days} days`,
                value: formatUsd(hasSubscription ? t.billed_usd : t.cost_usd),
                sub: hasSubscription ? `billed; plus ${formatUsd(t.subscription_usd)} subscription-equivalent` : undefined,
              },
              { label: "Today", value: formatUsd(summary.today.cost_usd), sub: `${formatInt(summary.today.calls)} calls` },
              { label: "Calls", value: formatInt(t.calls) },
              { label: "Input tokens", value: formatTokens(t.input_tokens), sub: t.cache_read_tokens ? `${formatTokens(t.cache_read_tokens)} read from cache` : undefined },
              { label: "Output tokens", value: formatTokens(t.output_tokens) },
              { label: "Errors", value: formatInt(t.errors), tone: t.errors > 0 ? "error" : "default" },
            ]}
          />

          {t.unknown_price_calls > 0 ? (
            <div role="alert" className="rounded-lg border border-amber/30 bg-amber-50 px-4 py-3 text-sm text-amber">
              {formatInt(t.unknown_price_calls)} {t.unknown_price_calls === 1 ? "call has" : "calls have"} an unknown price and{" "}
              {t.unknown_price_calls === 1 ? "is" : "are"} not in the spend above
              {summary.unknown_models.length ? `: ${summary.unknown_models.join(", ")}` : ""}.
            </div>
          ) : null}

          <Card title={weekly ? "Cost per week" : "Cost per day"} aside={`${formatDate(summary.range.since)} to ${formatDate(summary.range.until)}`}>
            {t.calls === 0 ? (
              <EmptyState title="No calls in this range">
                As soon as the backend makes an LLM call (a summary, a chat answer, a report), it appears here.
              </EmptyState>
            ) : (
              <BarChart bars={bars} ariaLabel={weekly ? "Cost per week" : "Cost per day"} />
            )}
            <p className="mt-2 text-xs text-ink-3">
              Prices as of {summary.prices_as_of}; LiteLLM is counted as free.{" "}
              <button type="button" onClick={togglePrices} aria-expanded={showPrices} className="text-accent hover:underline">
                {showPrices ? "Hide price table" : "Show price table"}
              </button>
            </p>
            {showPrices ? (
              pricesError ? (
                <ErrorNote message={pricesError} />
              ) : prices ? (
                <div className="mt-2">
                  <DataTable
                    caption="Prices in USD per million tokens"
                    rows={prices.models}
                    rowKey={(m) => m.prefix}
                    columns={[
                      { header: "Model prefix", cell: (m) => m.prefix },
                      { header: "Input", align: "right", cell: (m) => `$${m.input}` },
                      { header: "Output", align: "right", cell: (m) => `$${m.output}` },
                      { header: "Cache write", align: "right", cell: (m) => `$${m.cache_write}` },
                      { header: "Cache read", align: "right", cell: (m) => `$${m.cache_read}` },
                    ]}
                  />
                  <p className="mt-1 text-xs text-ink-3">USD per million tokens.</p>
                </div>
              ) : (
                <Spinner label="Loading prices" />
              )
            ) : null}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="By feature">
              <DataTable
                caption="Usage by feature"
                rows={summary.by_feature}
                rowKey={(r) => r.feature}
                empty="Features with calls will be listed here."
                columns={[
                  { header: "Feature", cell: (r) => r.feature },
                  { header: "Calls", align: "right", cell: (r) => formatInt(r.calls) },
                  { header: "Tokens in / out", align: "right", cell: (r) => `${formatTokens(r.input_tokens)} / ${formatTokens(r.output_tokens)}` },
                  { header: "Cost", align: "right", cell: (r) => formatUsd(r.cost_usd) },
                  { header: "Avg latency", align: "right", cell: (r) => formatLatency(r.avg_latency_ms) },
                  { header: "Errors", align: "right", cell: (r) => (r.errors > 0 ? <span className="text-coral">{r.errors}</span> : "0") },
                ]}
              />
            </Card>
            <Card title="By model">
              <DataTable
                caption="Usage by model"
                rows={summary.by_model}
                rowKey={(r) => `${r.provider}/${r.model}`}
                empty="Models with calls will be listed here."
                columns={[
                  { header: "Model", cell: (r) => <span className="break-all">{r.model}</span> },
                  { header: "Provider", cell: (r) => r.provider },
                  { header: "Calls", align: "right", cell: (r) => formatInt(r.calls) },
                  { header: "Tokens in / out", align: "right", cell: (r) => `${formatTokens(r.input_tokens)} / ${formatTokens(r.output_tokens)}` },
                  {
                    header: "Cost",
                    align: "right",
                    cell: (r) =>
                      r.price_known ? (
                        formatCost(r.cost_usd, r.provider, true)
                      ) : (
                        <span title="This model is not in the price table">
                          <Badge tone="warn">unknown price</Badge>
                        </span>
                      ),
                  },
                ]}
              />
            </Card>
          </div>

          {isAdmin ? (
            <Card title="By user">
              <DataTable
                caption="Usage by user"
                rows={summary.by_user}
                rowKey={(r) => r.user}
                empty="Users with calls will be listed here."
                columns={[
                  { header: "User", cell: (r) => r.user },
                  { header: "Calls", align: "right", cell: (r) => formatInt(r.calls) },
                  { header: "Tokens in / out", align: "right", cell: (r) => `${formatTokens(r.input_tokens)} / ${formatTokens(r.output_tokens)}` },
                  { header: "Cost", align: "right", cell: (r) => formatUsd(r.cost_usd) },
                ]}
              />
            </Card>
          ) : null}

          <Card title="Most expensive calls">
            <CallsTable caption="The most expensive calls in this range" calls={summary.top_calls} empty="The costliest calls will be listed here." />
          </Card>

          <Card title="Most expensive papers">
            <DataTable
              caption="Papers that caused the most cost"
              rows={summary.top_papers}
              rowKey={(r) => r.paper_id}
              empty="Papers that cost something (summaries, claims, paper chats) will be listed here."
              columns={[
                {
                  header: "Paper",
                  cell: (r) =>
                    r.title ? (
                      <Link to={`/paper/${r.paper_id}`} className="text-accent hover:underline">
                        {r.title}
                      </Link>
                    ) : (
                      <span className="text-ink-3">(deleted paper)</span>
                    ),
                },
                { header: "Calls", align: "right", cell: (r) => formatInt(r.calls) },
                { header: "Tokens in / out", align: "right", cell: (r) => `${formatTokens(r.input_tokens)} / ${formatTokens(r.output_tokens)}` },
                { header: "Cost", align: "right", cell: (r) => formatUsd(r.cost_usd) },
              ]}
            />
          </Card>
        </div>
      ) : null}

      <div className="mt-5">
        <Card title="Recent calls" aside={callsTotal > 0 ? `${formatInt(calls.length)} of ${formatInt(callsTotal)}` : undefined}>
          {callsError ? <ErrorNote message={callsError} onRetry={() => loadCalls(false, 0)} /> : null}
          {callsLoading && calls.length === 0 ? <Spinner label="Loading calls" /> : null}
          {!callsLoading || calls.length > 0 ? (
            <CallsTable caption="Recent calls, newest first" calls={calls} empty="Individual calls will be listed here, newest first." />
          ) : null}
          {calls.length < callsTotal ? (
            <div className="mt-3 text-center">
              <button type="button" className={btnSecondary} disabled={callsLoading} onClick={() => loadCalls(true, calls.length)}>
                {callsLoading ? "Loading" : "Load more"}
              </button>
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
