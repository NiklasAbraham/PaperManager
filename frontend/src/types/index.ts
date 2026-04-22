export interface Paper {
  id: string;
  title: string;
  year?: number;
  doi?: string;
  abstract?: string;
  summary?: string;
  drive_file_id?: string;
  citation_count?: number;
  metadata_source?: string;
  created_at: string;
  venue?: string;
  reading_status?: "unread" | "reading" | "read";
  rating?: number;
  bookmarked?: boolean;
  color?: string;
}

export interface Person {
  id: string;
  name: string;
  affiliation?: string;
  email?: string;
}

export interface Topic {
  id: string;
  name: string;
  paper_count?: number;
}

export interface Tag {
  id: string;
  name: string;
  paper_count?: number;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  status?: string;
  created_at: string;
}

export interface Note {
  id: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface SearchResult extends Paper {
  score: number;
  matched_in: string;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface Reference {
  id?: string;
  title: string;
  year?: number;
  doi?: string;
  arxiv_id?: string;
  authors?: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  [key: string]: unknown;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface Stats {
  counts: { papers: number; authors: number; topics: number; tags: number; projects: number; bookmarked: number };
  papers_by_year: { year: number; count: number }[];
  top_topics: { name: string; count: number }[];
  recent_papers: (Paper & { authors: string[] })[];
  reading_status: { status: string; count: number }[];
}

export interface ParsedMeta {
  title: string;
  authors: string[];
  year?: number;
  doi?: string;
  abstract?: string;
  venue?: string;
  citation_count?: number;
  metadata_source: string;
}

export interface T_IngestOut extends Paper {
  drive_url?: string;
  authors: string[];
  topics_auto_added: string[];
  references_found: Reference[];
  pdf_fetched?: boolean;  // undefined = legacy upload (assume true); false = no PDF available
}

// ── Figures ───────────────────────────────────────────────────────────────────

export interface Figure {
  id: string;
  paper_id: string;
  figure_number: number | null;
  caption: string | null;
  drive_file_id: string;
  drive_url: string | null;
  page_number: number;
  created_at: string;
}

// ── Knowledge Chat ────────────────────────────────────────────────────────────

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  compacted: boolean;
  message_count: number;
}

export interface KnowledgeMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  tokens_used?: number;
  created_at: string;
  paper_refs: string[];
}

export interface ContextPaper {
  id: string;
  title: string;
  tokens: number;
  color: string;
}

export interface TokenTotals {
  system: number;
  papers: number;
  history: number;
  question: number;
  total: number;
  limit: number;
}

export type SseEvent =
  | { type: "step"; description: string; cypher?: string; count?: number }
  | { type: "context"; papers: ContextPaper[]; token_totals: TokenTotals }
  | { type: "token"; text: string }
  | { type: "done"; conversation_id: string; message_id: string }
  | { type: "error"; message: string };

export type BulkSseEvent =
  | { done?: false; index: number; total: number; status: "success"; title: string; id: string; has_pdf: boolean }
  | { done?: false; index: number; total: number; status: "skipped"; title: string; id: string; reason: string }
  | { done?: false; index: number; total: number; status: "error"; input: string; error: string }
  | { done: true; imported: number; skipped: number; errors: number };

// ── Literature search ─────────────────────────────────────────────────────────

export interface LitPaper {
  title: string;
  abstract?: string;
  authors: string[];
  doi?: string;
  year?: number;
  date: string;
  source: "arxiv" | "pubmed" | "biorxiv";
  url: string;
  already_in_library: boolean;
}

export type LiteratureSseEvent =
  | { done?: false; searching: string }
  | { done?: false; source: string; paper: LitPaper }
  | { done?: false; source: string; error: string }
  | { done: true; counts: Record<string, number> };
