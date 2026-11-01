import { useEffect, useRef } from "react";
import { listReferenceImports, type ReferenceImportJob } from "../api/client";
import { notify } from "../lib/notify";

const POLL_MS = 4000;

/**
 * Watches background reference imports app-wide, so a pull keeps reporting
 * while the user reads another paper. Polls only while a job is active,
 * toasts when one finishes, and broadcasts `refimport:update` (all jobs) and
 * `refimport:finished` (one job) for pages that show per-reference state.
 */
export default function ReferenceImportTracker() {
  const known = useRef<Map<string, ReferenceImportJob["status"]>>(new Map());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let stopped = false;

    const poll = async () => {
      timer.current = null;
      let jobs: ReferenceImportJob[];
      try {
        jobs = await listReferenceImports();
      } catch {
        jobs = [];
      }
      if (stopped) return;
      for (const j of jobs) {
        const prev = known.current.get(j.id);
        known.current.set(j.id, j.status);
        // Only toast for jobs we saw running in this tab (no replay after reload).
        if (prev && prev !== j.status && (j.status === "done" || j.status === "error")) {
          if (j.status === "done") {
            const extras = [
              j.pdf === false ? "no open PDF, metadata only" : null,
              j.tags_applied.length ? `tags: ${j.tags_applied.join(", ")}` : null,
            ].filter(Boolean).join(" · ");
            notify(`Added to library: ${j.title}${extras ? ` (${extras})` : ""}`, "success");
          } else {
            notify(`Could not import "${j.title}": ${j.error ?? "unknown error"}`, "error");
          }
          window.dispatchEvent(new CustomEvent("refimport:finished", { detail: j }));
        }
      }
      window.dispatchEvent(new CustomEvent("refimport:update", { detail: jobs }));
      if (jobs.some((j) => j.status === "queued" || j.status === "running")) {
        timer.current = setTimeout(poll, POLL_MS);
      }
    };

    const kick = (e: Event) => {
      const job = (e as CustomEvent<ReferenceImportJob>).detail;
      if (job && !known.current.has(job.id)) known.current.set(job.id, job.status);
      if (!timer.current) timer.current = setTimeout(poll, 300);
    };

    window.addEventListener("refimport:started", kick);
    poll(); // picks up jobs still running after a reload
    return () => {
      stopped = true;
      window.removeEventListener("refimport:started", kick);
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  return null;
}
