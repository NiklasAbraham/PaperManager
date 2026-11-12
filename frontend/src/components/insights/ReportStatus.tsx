import type { ReportStatus } from "../../api/insights";
import { Badge } from "./ui";

/** Queued or running: the report is still being written and the page polls. */
export const isActiveStatus = (s: ReportStatus) => s === "queued" || s === "running";

export function StatusBadge({ status }: { status: ReportStatus }) {
  const tone = status === "done" ? "ok" : status === "failed" ? "error" : status === "running" ? "accent" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}
