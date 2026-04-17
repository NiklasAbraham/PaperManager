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
}

export interface T_IngestOut extends Paper {
  drive_url?: string;
  authors: string[];
  topics_auto_added: string[];
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
