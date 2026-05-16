import { useCallback, useRef, useState, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import { useNavigate } from "react-router-dom";
import { parsePdf, previewUrl, deletePaper, checkDuplicate } from "../api/client";
import UploadConfirmModal from "./UploadConfirmModal";
import type { ParsedMeta, T_IngestOut } from "../types";
import {
  persistItem, removePersistedItem, loadPersistedQueue,
  fileToBuffer, bufferToFile,
} from "../lib/queueStorage";

interface Props {
  onUploaded: (paper: T_IngestOut) => void;
  debug?: boolean;
}

type Tab = "pdf" | "url" | "bulk" | "queue";
type PdfStatus = "parsing" | "uploading" | "ready" | "duplicate" | "error" | "done";

type QueuedPdf = {
  id: string;
  file: File;
  meta: ParsedMeta | null;
  status: PdfStatus;
  error: string | null;
  uploadResult?: T_IngestOut;
  duplicateId?: string;
  duplicateTitle?: string;
};

export default function PaperDrop({ onUploaded, debug }: Props) {
  const navigate = useNavigate();
  const [open, setOpen]   = useState(false);
  const [tab, setTab]     = useState<Tab>("pdf");
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // PDF queue
  const [queue, setQueue]         = useState<QueuedPdf[]>([]);
  const [activeIdx, setActiveIdx] = useState(-1);

  // URL state
  const [urlValue, setUrlValue]     = useState("");
  const [loadingUrl, setLoadingUrl] = useState(false);
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);
  const [urlMeta, setUrlMeta]       = useState<ParsedMeta | null>(null);

  // ── Restore queue from IndexedDB on mount ──────────────────────────────────
  useEffect(() => {
    loadPersistedQueue().then((stored) => {
      if (!stored.length) return;
      const restored: QueuedPdf[] = stored.map((s) => ({
        id: s.id,
        file: bufferToFile(s.fileBytes, s.fileName, s.fileType),
        meta: s.meta,
        status: s.status,
        error: s.error,
        duplicateId: s.duplicateId,
        duplicateTitle: s.duplicateTitle,
        uploadResult: s.uploadResult,
      }));
      setQueue(restored);
      setTab("queue");
    }).catch(() => { /* IndexedDB unavailable — silent fail */ });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Persist queue changes to IndexedDB ────────────────────────────────────
  useEffect(() => {
    queue.forEach((item) => {
      if (item.status === "done" || item.status === "uploading" || item.status === "parsing") {
        // Transient states — remove from store if previously saved
        removePersistedItem(item.id).catch(() => {});
        return;
      }
      fileToBuffer(item.file).then((bytes) => {
        persistItem({
          id: item.id,
          fileName: item.file.name,
          fileType: item.file.type,
          fileBytes: bytes,
          meta: item.meta,
          status: item.status as "ready" | "error",
          error: item.error,
          duplicateId: item.duplicateId,
          duplicateTitle: item.duplicateTitle,
          uploadResult: item.uploadResult,
        }).catch(() => {});
      }).catch(() => {});
    });
  }, [queue]);

  // Auto-switch to queue tab when items arrive
  useEffect(() => {
    if (queue.length > 0 && tab !== "queue") setTab("queue");
  }, [queue.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-remove done rows after 3 s (also cleans IndexedDB)
  useEffect(() => {
    const done = queue.filter((q) => q.status === "done");
    if (!done.length) return;
    const timer = setTimeout(() => {
      done.forEach((q) => removePersistedItem(q.id).catch(() => {}));
      setQueue((prev) => prev.filter((q) => q.status !== "done"));
    }, 3000);
    return () => clearTimeout(timer);
  }, [queue]);

  // Close panel on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const updateItem = (id: string, patch: Partial<QueuedPdf>) =>
    setQueue((prev) => prev.map((q) => q.id === id ? { ...q, ...patch } : q));

  const prepareItem = async (item: QueuedPdf, meta: ParsedMeta) => {
    // Check for duplicates before showing the modal
    try {
      const dup = await checkDuplicate(meta.doi || undefined, meta.title || undefined);
      if (dup) {
        updateItem(item.id, {
          meta,
          status: "duplicate",
          duplicateId: dup.id,
          duplicateTitle: dup.title,
        });
        return;
      }
    } catch { /* best-effort — proceed if check fails */ }

    updateItem(item.id, { meta, status: "ready" });
  };

  const onDrop = useCallback((files: File[]) => {
    if (!files.length) return;
    setError(null);

    const newItems: QueuedPdf[] = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      meta: null,
      status: "parsing" as PdfStatus,
      error: null,
    }));

    setQueue((prev) => [...prev, ...newItems]);

    newItems.forEach((item) => {
      parsePdf(item.file)
        .then((meta) => prepareItem(item, meta))
        .catch((e) =>
          updateItem(item.id, {
            status: "error",
            error: e instanceof Error ? e.message : "Could not read PDF",
          })
        );
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    multiple: true,
  });

  const handleDeleteRow = async (item: QueuedPdf) => {
    if (item.uploadResult) {
      try { await deletePaper(item.uploadResult.id); } catch { /* best-effort */ }
    }
    removePersistedItem(item.id).catch(() => {});
    setQueue((prev) => prev.filter((q) => q.id !== item.id));
    if (queue[activeIdx]?.id === item.id) setActiveIdx(-1);
  };

  const handleClickRow = (idx: number) => {
    const item = queue[idx];
    if (item.status === "ready") setActiveIdx(idx);
  };

  const handleUrlSubmit = async () => {
    if (!urlValue.trim()) return;
    setLoadingUrl(true);
    setError(null);
    try {
      const meta = await previewUrl(urlValue.trim());
      setPendingUrl(urlValue.trim());
      setUrlMeta(meta);
      setUrlValue("");
      setOpen(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not resolve URL");
    } finally {
      setLoadingUrl(false);
    }
  };

  const pendingCount = queue.filter((q) => q.status !== "done").length;

  return (
    <>
      <div className="relative" ref={panelRef}>
        {/* Plus button with queue badge */}
        <button
          onClick={() => { setOpen((o) => !o); setError(null); }}
          title="Add paper"
          className={`relative flex items-center justify-center w-9 h-9 rounded-lg border transition-colors shrink-0
            ${open
              ? "bg-violet-600 border-violet-600 text-white"
              : "border-gray-200 text-gray-500 hover:border-violet-400 hover:text-violet-600 bg-white"
            }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          {pendingCount > 0 && (
            <span className="absolute -top-2.5 -right-2.5 min-w-[22px] h-[22px] px-1.5 rounded-full bg-violet-500 text-white text-xs font-semibold flex items-center justify-center border-2 border-white leading-none">
              {pendingCount}
            </span>
          )}
        </button>

        {/* Floating panel */}
        {open && (
          <div className="absolute right-0 top-11 z-50 w-[480px] bg-white border border-gray-200 rounded-xl shadow-xl p-5 space-y-4">
            {/* Tab bar */}
            <div className="flex border border-gray-200 rounded-lg overflow-hidden text-sm font-medium">
              <button
                onClick={() => { setTab("pdf"); setError(null); }}
                className={`flex-1 py-2.5 transition-colors ${tab === "pdf" ? "bg-violet-600 text-white" : "text-gray-500 hover:bg-gray-50"}`}
              >
                PDF
              </button>
              <button
                onClick={() => { setTab("url"); setError(null); }}
                className={`flex-1 py-2.5 border-l border-gray-200 transition-colors ${tab === "url" ? "bg-violet-600 text-white" : "text-gray-500 hover:bg-gray-50"}`}
              >
                URL / DOI
              </button>
              <button
                onClick={() => { setTab("bulk"); setError(null); }}
                className={`flex-1 py-2.5 border-l border-gray-200 transition-colors ${tab === "bulk" ? "bg-violet-600 text-white" : "text-gray-500 hover:bg-gray-50"}`}
              >
                Bulk
              </button>
              {queue.length > 0 && (
                <button
                  onClick={() => setTab("queue")}
                  className={`flex-1 py-2.5 border-l border-gray-200 transition-colors flex items-center justify-center gap-1.5 ${tab === "queue" ? "bg-violet-600 text-white" : "text-gray-500 hover:bg-gray-50"}`}
                >
                  Queue
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${tab === "queue" ? "bg-white/25 text-white" : "bg-violet-100 text-violet-600"}`}>
                    {pendingCount}
                  </span>
                </button>
              )}
            </div>

            {/* PDF drop zone */}
            {tab === "pdf" && (
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-xl px-6 py-10 text-center cursor-pointer transition-colors
                  ${isDragActive ? "border-violet-500 bg-violet-50" : "border-gray-300 hover:border-violet-400 hover:bg-gray-50"}`}
              >
                <input {...getInputProps()} />
                <svg className="w-8 h-8 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12l-3-3m0 0l-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <p className="text-sm text-gray-500 font-medium">
                  {isDragActive ? "Drop PDFs here…" : "Drag & drop PDFs, or click to select"}
                </p>
                <p className="text-xs text-gray-400 mt-1">Select multiple — all start processing in parallel</p>
              </div>
            )}

            {/* URL input */}
            {tab === "url" && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <input
                    autoFocus
                    value={urlValue}
                    onChange={(e) => setUrlValue(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleUrlSubmit()}
                    placeholder="https://arxiv.org/abs/2104.09864"
                    disabled={loadingUrl}
                    className="flex-1 border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:opacity-60"
                  />
                  <button
                    onClick={handleUrlSubmit}
                    disabled={loadingUrl || !urlValue.trim()}
                    className="px-4 py-2.5 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors font-medium"
                  >
                    {loadingUrl ? (
                      <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                      </svg>
                    ) : "Add"}
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {["arxiv.org", "doi.org", "pubmed", "biorxiv.org"].map((s) => (
                    <span key={s} className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{s}</span>
                  ))}
                  <span className="text-xs text-gray-400">· plain DOIs & arXiv IDs</span>
                </div>
              </div>
            )}

            {/* Bulk import */}
            {tab === "bulk" && (
              <div className="space-y-3 text-center py-4">
                <svg className="w-8 h-8 mx-auto text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" />
                </svg>
                <p className="text-sm text-gray-600 font-medium">Import multiple papers at once</p>
                <p className="text-xs text-gray-400">Paste a JSON list of arXiv IDs, DOIs, or URLs</p>
                <button
                  onClick={() => { setOpen(false); navigate("/bulk-import"); }}
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-violet-600 text-white text-sm font-medium rounded-lg hover:bg-violet-700 transition-colors"
                >
                  Open Bulk Import
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                  </svg>
                </button>
              </div>
            )}

            {/* Queue panel */}
            {tab === "queue" && (
              <div className="space-y-1 max-h-[55vh] overflow-y-auto -mx-1 px-1">
                {queue.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">Queue is empty</p>
                ) : (
                  queue.map((item, idx) => (
                    <QueueRow
                      key={item.id}
                      item={item}
                      isActive={activeIdx === idx}
                      onClick={() => handleClickRow(idx)}
                      onDelete={() => handleDeleteRow(item)}
                    />
                  ))
                )}
                {queue.length > 0 && (
                  <div className="pt-2 border-t border-gray-100">
                    <button
                      onClick={() => setTab("pdf")}
                      className="w-full py-2 text-xs text-violet-600 hover:text-violet-700 font-medium flex items-center justify-center gap-1"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                      </svg>
                      Add more PDFs
                    </button>
                  </div>
                )}
              </div>
            )}

            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
        )}
      </div>

      {/* Onboarding modal — shown when user clicks a ready row */}
      {activeIdx >= 0 && queue[activeIdx]?.meta && queue[activeIdx].status === "ready" && (() => {
        const reviewable = queue.filter((q) => !["error", "duplicate"].includes(q.status));
        const pos = reviewable.findIndex((q) => q.id === queue[activeIdx].id) + 1;
        return (
          <UploadConfirmModal
            file={queue[activeIdx].file}
            meta={queue[activeIdx].meta!}
            skipSummaryStep={true}
            queuePosition={reviewable.length > 1 ? pos : undefined}
            queueTotal={reviewable.length > 1 ? reviewable.length : undefined}
            onConfirmed={(paper) => {
              updateItem(queue[activeIdx].id, { status: "done", uploadResult: paper });
              setActiveIdx(-1);
              onUploaded(paper);
            }}
            onCancel={() => setActiveIdx(-1)}
            debug={debug}
          />
        );
      })()}

      {/* URL modal */}
      {urlMeta && pendingUrl && (
        <UploadConfirmModal
          file={null}
          meta={urlMeta}
          url={pendingUrl}
          onConfirmed={(paper) => { setPendingUrl(null); setUrlMeta(null); onUploaded(paper); }}
          onCancel={() => { setPendingUrl(null); setUrlMeta(null); }}
          debug={debug}
        />
      )}
    </>
  );
}

// ── Queue row ────────────────────────────────────────────────────────────────

function QueueRow({
  item,
  isActive,
  onClick,
  onDelete,
}: {
  item: QueuedPdf;
  isActive: boolean;
  onClick: () => void;
  onDelete: () => void;
}) {
  const isClickable = item.status === "ready";
  const title = item.meta?.title || item.uploadResult?.title || item.duplicateTitle || item.file.name;

  const statusIcon = {
    parsing:   <Spinner color="text-violet-400" />,
    uploading: <Spinner color="text-violet-600" />,
    ready:     <span className="w-2 h-2 rounded-full bg-green-400 shrink-0 mt-0.5" />,
    duplicate: <span className="text-amber-500 shrink-0 leading-none mt-0.5">⚠</span>,
    error:     <span className="text-red-400 shrink-0 leading-none mt-0.5">✕</span>,
    done:      <span className="text-gray-300 shrink-0 leading-none mt-0.5">✓</span>,
  }[item.status];

  const statusText = {
    parsing:   "Extracting metadata…",
    uploading: "Uploading…",
    ready:     "Ready — click to review",
    duplicate: "Already in your library",
    error:     item.error ?? "Something went wrong",
    done:      "Added ✓",
  }[item.status];

  const statusColor = {
    parsing:   "text-violet-400",
    uploading: "text-violet-500",
    ready:     "text-green-600",
    duplicate: "text-amber-600",
    error:     "text-red-500",
    done:      "text-gray-300",
  }[item.status];

  return (
    <div
      onClick={isClickable ? onClick : undefined}
      className={`group flex items-start gap-2.5 px-3 py-2.5 rounded-lg transition-colors ${
        isClickable
          ? "cursor-pointer hover:bg-violet-50"
          : "cursor-default"
      } ${isActive ? "bg-violet-50 ring-1 ring-violet-200" : ""} ${
        item.status === "done" ? "opacity-40" : ""
      }`}
    >
      <div className="mt-1 shrink-0">{statusIcon}</div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate">{title}</p>
        <p className={`text-xs mt-0.5 ${statusColor}`}>{statusText}</p>
        {item.status === "duplicate" && item.duplicateId && (
          <a
            href={`/paper/${item.duplicateId}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-violet-600 hover:underline mt-0.5 inline-block"
          >
            View existing →
          </a>
        )}
      </div>

      <button
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        title="Remove"
        className="shrink-0 mt-0.5 w-5 h-5 flex items-center justify-center rounded text-gray-300 hover:text-red-400 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

function Spinner({ color }: { color: string }) {
  return (
    <svg className={`animate-spin h-3.5 w-3.5 ${color} shrink-0`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
    </svg>
  );
}
