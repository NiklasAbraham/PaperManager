// Kinds a project's papers are filtered by: document type and whether a PDF is
// stored. Hidden kinds persist across visits in localStorage.
import { useState } from "react";

export interface KindedPaper {
  document_type?: string;
  has_pdf?: boolean;
}

export const TYPE_KINDS = [
  { key: "paper",        label: "Papers" },
  { key: "book",         label: "Books" },
  { key: "lecture_deck", label: "Lecture decks" },
  { key: "news_article", label: "News articles" },
] as const;

export const PDF_KINDS = [
  { key: "pdf",    label: "With PDF" },
  { key: "no_pdf", label: "Metadata only" },
] as const;

export const TYPE_LABELS: Record<string, string> = {
  book: "Book", lecture_deck: "Lecture deck", news_article: "News",
};

export function typeKind(p: KindedPaper): string {
  return p.document_type || "paper";
}

export function pdfKind(p: KindedPaper): string {
  return p.has_pdf ? "pdf" : "no_pdf";
}

export function isVisible(p: KindedPaper, hidden: Set<string>): boolean {
  return !hidden.has(typeKind(p)) && !hidden.has(pdfKind(p));
}

const STORAGE_KEY = "projects-hidden-kinds";

export function useHiddenKinds(): [Set<string>, (key: string) => void, () => void] {
  const [hidden, setHidden] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]")); } catch { return new Set(); }
  });
  const save = (next: Set<string>) => {
    setHidden(next);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...next])); } catch { /* ignore */ }
  };
  const toggle = (key: string) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key); else next.add(key);
    save(next);
  };
  return [hidden, toggle, () => save(new Set())];
}
