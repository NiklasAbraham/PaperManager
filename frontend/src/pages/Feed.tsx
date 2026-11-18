import { useCallback, useEffect, useRef, useState } from "react";
import {
  addFeedItem,
  dismissFeedItem,
  getFeedConfig,
  getFeedStatus,
  listFeed,
  putFeedConfig,
  rateFeedItem,
  refreshFeed,
} from "../api/feed";
import type { FeedConfig, FeedDigest, FeedItem, FeedStatus as Status } from "../api/feed";
import { listProjects } from "../api/client";
import FeedRow from "../components/feed/FeedRow";
import FeedSetup from "../components/feed/FeedSetup";
import FeedStatus from "../components/feed/FeedStatus";
import { EmptyState, ErrorNote, PageHeader, Spinner, btnSecondary, errorMessage, inputCls } from "../components/insights/ui";

const PAGE = 30;
const DAY_CHOICES = [1, 2, 3, 5, 7, 14];

/** The window choices, plus the current value when it is not one of them (the API takes 1 to 14). */
function dayOptions(current: number): number[] {
  return DAY_CHOICES.includes(current) ? DAY_CHOICES : [...DAY_CHOICES, current].sort((a, b) => a - b);
}

export default function Feed() {
  const [status, setStatus] = useState<Status | null>(null);
  const [config, setConfig] = useState<FeedConfig | null>(null);
  const [digest, setDigest] = useState<FeedDigest | null>(null);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [days, setDays] = useState<number | null>(null);
  const [includeRated, setIncludeRated] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const seq = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadDigest = useCallback(() => {
    const id = ++seq.current;
    return listFeed({ days: days ?? undefined, include_rated: includeRated, limit: PAGE })
      .then((d) => {
        if (id !== seq.current) return;
        setError(null);
        setDigest(d);
        setItems(d.items);
      })
      .catch((e) => {
        if (id === seq.current) setError(errorMessage(e, "Could not load the feed"));
      });
  }, [days, includeRated]);

  // Status first: a switched-off feed answers 404 everywhere else.
  useEffect(() => {
    getFeedStatus()
      .then(setStatus)
      .catch((e) => setError(errorMessage(e, "Could not reach the server")));
    getFeedConfig().then(setConfig).catch(() => undefined);
    listProjects().then(setProjects).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (status?.enabled) void loadDigest();
  }, [status?.enabled, loadDigest]);

  const reloadStatus = () => {
    getFeedStatus().then(setStatus).catch(() => undefined);
  };

  const save = async (next: FeedConfig) => {
    setSaving(true);
    setSaveError(null);
    try {
      setConfig(await putFeedConfig(next));
      setEditing(false);
      setDays(null);
      await loadDigest();
      reloadStatus();
    } catch (e) {
      setSaveError(errorMessage(e, "Could not save the settings"));
    } finally {
      setSaving(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setRefreshError(null);
    try {
      await refreshFeed();
      // Poll the status until the refresh is over, then reload the digest.
      for (let i = 0; i < 120 && mounted.current; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        if (!mounted.current) return;
        const s = await getFeedStatus();
        setStatus(s);
        if (s.state !== "refreshing") break;
      }
      await loadDigest();
    } catch (e) {
      setRefreshError(errorMessage(e, "Could not start a refresh"));
    } finally {
      setRefreshing(false);
    }
  };

  const patch = (id: string, over: Partial<FeedItem>) =>
    setItems((prev) => prev.map((x) => (x.id === id ? { ...x, ...over } : x)));
  const drop = (id: string) => {
    setItems((prev) => prev.filter((x) => x.id !== id));
    setDigest((d) => (d ? { ...d, total: Math.max(0, d.total - 1) } : d));
  };

  const rate = async (item: FeedItem, value: 1 | -1) => {
    setActionError(null);
    setBusyId(item.id);
    try {
      await rateFeedItem(item.id, value);
      if (includeRated) patch(item.id, { my_label: value });
      else drop(item.id);
      reloadStatus();
    } catch (e) {
      setActionError(errorMessage(e, "Could not save your rating"));
    } finally {
      setBusyId(null);
    }
  };

  const dismiss = async (item: FeedItem) => {
    setActionError(null);
    setBusyId(item.id);
    try {
      await dismissFeedItem(item.id);
      if (includeRated) patch(item.id, { my_label: 0 });
      else drop(item.id);
    } catch (e) {
      setActionError(errorMessage(e, "Could not dismiss the paper"));
    } finally {
      setBusyId(null);
    }
  };

  const add = async (item: FeedItem, projectId?: string) => {
    setActionError(null);
    setBusyId(item.id);
    try {
      const r = await addFeedItem(item.id, projectId);
      patch(item.id, { in_library: true, library_paper_id: r.paper_id, my_label: 1 });
      reloadStatus();
    } catch (e) {
      setActionError(errorMessage(e, "Could not add the paper"));
    } finally {
      setBusyId(null);
    }
  };

  const more = async () => {
    setLoadingMore(true);
    try {
      const d = await listFeed({ days: days ?? undefined, include_rated: includeRated, limit: PAGE, skip: items.length });
      setItems((prev) => [...prev, ...d.items.filter((n) => !prev.some((p) => p.id === n.id))]);
    } catch (e) {
      setActionError(errorMessage(e, "Could not load more"));
    } finally {
      setLoadingMore(false);
    }
  };

  const header = (
    <PageHeader
      title="Paper feed"
      description="New preprints from the sources you chose, ranked by what you keep in your library."
    />
  );

  if (status === null && !error) return <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">{header}<Spinner label="Loading feed" /></div>;

  if (status && !status.enabled) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        {header}
        <EmptyState title="The paper feed is switched off">
          An admin can turn it on by setting PAPER_FEED=true on the server.
        </EmptyState>
      </div>
    );
  }

  const unconfigured = digest !== null && !digest.configured;
  const showSetup = config !== null && (editing || unconfigured);

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      {header}
      {status ? (
        <FeedStatus
          status={status}
          mode={digest?.mode ?? status.mode ?? null}
          positives={digest?.positives ?? status.positives ?? null}
          quality={digest?.quality ?? status.quality ?? null}
          refreshing={refreshing}
          refreshError={refreshError}
          onRefresh={() => void refresh()}
          onEdit={() => setEditing(true)}
        />
      ) : null}

      {showSetup && config ? (
        <div className="mb-6">
          <FeedSetup
            config={config}
            saving={saving}
            error={saveError}
            onSave={(c) => void save(c)}
            onCancel={editing && !unconfigured ? () => setEditing(false) : undefined}
          />
        </div>
      ) : null}

      {!unconfigured && digest ? (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ink-2">
            {digest.total} {digest.total === 1 ? "paper" : "papers"} in the last {digest.days} {digest.days === 1 ? "day" : "days"}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-ink-2">
              Window
              <select
                value={days ?? digest.days}
                onChange={(e) => setDays(Number(e.target.value))}
                className={inputCls}
              >
                {dayOptions(days ?? digest.days).map((d) => (
                  <option key={d} value={d}>{d} {d === 1 ? "day" : "days"}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-ink-2">
              <input type="checkbox" checked={includeRated} onChange={(e) => setIncludeRated(e.target.checked)} />
              Show rated
            </label>
          </div>
        </div>
      ) : null}

      {actionError ? <div className="mb-3"><ErrorNote message={actionError} /></div> : null}
      {error ? <ErrorNote message={error} onRetry={() => void loadDigest()} /> : null}
      {digest === null && !error && status?.enabled ? <Spinner label="Ranking papers" /> : null}

      {!unconfigured && digest && items.length === 0 ? (
        <EmptyState title="Nothing to show yet">
          {status?.candidates
            ? "Everything in this window is rated. Widen the window or show rated papers."
            : "The first fetch can take a few minutes after you choose your categories. Use Refresh now to start it."}
        </EmptyState>
      ) : null}

      {items.length > 0 ? (
        <>
          <ul className="space-y-3" aria-label="Papers">
            {items.map((it) => (
              <FeedRow key={it.id} item={it} projects={projects} busy={busyId === it.id} onRate={rate} onDismiss={dismiss} onAdd={add} />
            ))}
          </ul>
          {digest && items.length < digest.total ? (
            <div className="mt-4 text-center">
              <button type="button" className={btnSecondary} disabled={loadingMore} onClick={() => void more()}>
                {loadingMore ? "Loading" : "Show more"}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
