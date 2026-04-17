import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { uploadPdf } from "../api/client";
import type { T_IngestOut } from "../types";

interface Props {
  onUploaded: (paper: T_IngestOut) => void;
}

export default function PaperDrop({ onUploaded }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onDrop = useCallback(async (files: File[]) => {
    const file = files[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const paper = await uploadPdf(file);
      onUploaded(paper);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [onUploaded]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    multiple: false,
    disabled: uploading,
  });

  return (
    <div
      {...getRootProps()}
      className={`border-2 border-dashed rounded-lg px-6 py-4 text-center cursor-pointer transition-colors
        ${isDragActive ? "border-violet-500 bg-violet-50" : "border-gray-300 bg-white hover:border-violet-400"}
        ${uploading ? "opacity-60 cursor-wait" : ""}`}
    >
      <input {...getInputProps()} />
      {uploading ? (
        <div className="flex items-center justify-center gap-2 text-violet-600 text-sm">
          <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          Processing PDF…
        </div>
      ) : (
        <p className="text-sm text-gray-500">
          {isDragActive ? "Drop PDF here…" : "Drag & drop a PDF, or click to select"}
        </p>
      )}
      {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
    </div>
  );
}
