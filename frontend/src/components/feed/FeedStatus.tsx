import type { FeedMode, FeedQuality, FeedStatus as Status } from "../../api/feed";
import { formatInt, relativeTime } from "../insights/format";
import { Badge, btnSecondary } from "../insights/ui";
import { modeText } from "./modeText";

export default function FeedStatus({
  status,
  mode,
  positives,
  quality,
  refreshing,
  refreshError,
  onRefresh,
  onEdit,
}: {
  status: Status;
  mode: FeedMode | null;
  positives: number | null;
  quality: FeedQuality | null;
  refreshing: boolean;
  refreshError: string | null;
  onRefresh: () => void;
  onEdit: () => void;
}) {
  const busy = refreshing || status.state === "refreshing";
  return (
    <div className="mb-4 rounded-xl border border-line bg-raised px-4 py-3 text-sm text-ink-2" aria-label="Feed status">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="min-w-0">
          {status.last_refresh ? `Updated ${relativeTime(status.last_refresh)}` : "Not fetched yet"}
          <span className="mx-2 text-ink-3">&middot;</span>
          {formatInt(status.candidates)} papers stored
          {mode ? (
            <>
              <span className="mx-2 text-ink-3">&middot;</span>
              {modeText(mode, positives)}
            </>
          ) : null}
        </p>
        <div className="flex items-center gap-2">
          {busy ? <Badge tone="accent">Refreshing</Badge> : null}
          <button type="button" className={btnSecondary} onClick={onEdit}>
            Settings
          </button>
          <button type="button" className={btnSecondary} onClick={onRefresh} disabled={busy}>
            Refresh now
          </button>
        </div>
      </div>
      {quality ? (
        <p className="mt-1 text-xs text-ink-3">
          Held-out AUC {quality.auc.toFixed(2)}: how well a model trained without your {quality.held_out} newest
          papers ranks them above random ones. A rough guide, not a promise.
        </p>
      ) : null}
      {status.error ? (
        <p role="alert" className="mt-1 break-words text-xs text-coral">
          Last refresh problem: {status.error}
        </p>
      ) : null}
      {refreshError ? (
        <p role="alert" className="mt-1 break-words text-xs text-coral">
          {refreshError}
        </p>
      ) : null}
    </div>
  );
}
