import { useCallback, useRef, useState, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import { parsePdf, ingestFromUrl } from "../api/client";
import UploadConfirmModal from "./UploadConfirmModal";
import type { ParsedMeta, T_IngestOut } from "../types";

interface Props {
  onUploaded: (paper: T_IngestOut) => void;
  debug?: boolean;
}

type Tab = "pdf" | "url";

export default function PaperDrop({ onUploaded, debug }: Props) {
  const [open, setOpen]           = useState(false);
  const [tab, setTab]             = useState<Tab>("pdf");
  const [parsing, setParsing]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [parsedMeta, setParsedMeta]   = useState<ParsedMeta | null>(null);
  const [urlValue, setUrlValue]   = useState("");
  const [loadingUrl, setLoadingUrl] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

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

  const onDrop = useCallback(async (files: File[]) => {
    const file = files[0];
    if (!file) return;
    setParsing(true);
    setError(null);
    try {
      const meta = await parsePdf(file);
      setPendingFile(file);
      setParsedMeta(meta);
      setOpen(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not read PDF");
    } finally {
      setParsing(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    multiple: false,
    disabled: parsing,
  });

  const handleUrlSubmit = async () => {
    if (!urlValue.trim()) return;
    setLoadingUrl(true);
    setError(null);
    try {
      const paper = await ingestFromUrl(urlValue.trim(), undefined, debug);
      setUrlValue("");
      setOpen(false);
      onUploaded(paper);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not resolve URL");
    } finally {
      setLoadingUrl(false);
    }
  };

  const handleConfirmed = (paper: T_IngestOut) => {
    setPendingFile(null);
    setParsedMeta(null);
    onUploaded(paper);
  };

  return (
    <>
      <div className="relative" ref={panelRef}>
        {/* Plus button */}
        <button
          onClick={() => { setOpen((o) => !o); setError(null); }}
          title="Add paper"
          className={`flex items-center justify-center w-9 h-9 rounded-lg border transition-colors shrink-0
            ${open
              ? "bg-violet-600 border-violet-600 text-white"
              : "border-gray-200 text-gray-500 hover:border-violet-400 hover:text-violet-600 bg-white"
            }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
        </button>

        {/* Floating panel */}
        {open && (
          <div className="absolute right-0 top-11 z-50 w-[480px] bg-white border border-gray-200 rounded-xl shadow-xl p-5 space-y-4">
            {/* Tab toggle */}
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
            </div>

            {/* PDF drop zone */}
            {tab === "pdf" && (
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-xl px-6 py-10 text-center cursor-pointer transition-colors
                  ${isDragActive ? "border-violet-500 bg-violet-50" : "border-gray-300 hover:border-violet-400 hover:bg-gray-50"}
                  ${parsing ? "opacity-60 cursor-wait" : ""}`}
              >
                <input {...getInputProps()} />
                {parsing ? (
                  <div className="flex items-center justify-center gap-2 text-violet-600">
                    <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                    <span className="text-sm">Extracting metadata…</span>
                  </div>
                ) : (
                  <>
                    <svg className="w-8 h-8 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12l-3-3m0 0l-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                    <p className="text-sm text-gray-500 font-medium">
                      {isDragActive ? "Drop PDF here…" : "Drag & drop a PDF, or click to select"}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">Metadata will be extracted automatically</p>
                  </>
                )}
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

            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
        )}
      </div>

      {pendingFile && parsedMeta && (
        <UploadConfirmModal
          file={pendingFile}
          meta={parsedMeta}
          onConfirmed={handleConfirmed}
          onCancel={() => { setPendingFile(null); setParsedMeta(null); }}
          debug={debug}
        />
      )}
    </>
  );
}
