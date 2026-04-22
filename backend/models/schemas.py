from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    neo4j: str


# ── Papers ────────────────────────────────────────────────────────────────────

class PaperCreate(BaseModel):
    title: str
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    venue: str | None = None


class PaperUpdate(BaseModel):
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    summary: str | None = None
    venue: str | None = None
    metadata_source: str | None = None
    reading_status: str | None = None   # "unread" | "reading" | "read"
    rating: int | None = None           # 1-5
    bookmarked: bool | None = None
    color: str | None = None            # hex color string or named color


class PaperOut(BaseModel):
    id: str
    title: str
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    summary: str | None = None
    drive_file_id: str | None = None
    citation_count: int | None = None
    metadata_source: str | None = None
    created_at: str
    venue: str | None = None
    reading_status: str | None = None
    rating: int | None = None
    bookmarked: bool | None = None
    color: str | None = None


# ── People ────────────────────────────────────────────────────────────────────

class PersonCreate(BaseModel):
    name: str
    affiliation: str | None = None
    email: str | None = None


class PersonOut(BaseModel):
    id: str
    name: str
    affiliation: str | None = None
    email: str | None = None


class AuthorLink(BaseModel):
    person_id: str


class InvolvesLink(BaseModel):
    person_id: str
    role: str


class SpecialtyLink(BaseModel):
    topic_name: str


# ── Tags & Topics ─────────────────────────────────────────────────────────────

class TagBody(BaseModel):
    name: str


class TopicBody(BaseModel):
    name: str


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    status: str = "active"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str | None = None
    created_at: str


class ProjectPaperLink(BaseModel):
    paper_id: str


# ── Notes ─────────────────────────────────────────────────────────────────────

class NoteBody(BaseModel):
    content: str


class NoteOut(BaseModel):
    id: str
    content: str
    created_at: str
    updated_at: str


# ── Ingestion ──────────────────────────────────────────────────────────────────

class IngestOut(PaperOut):
    drive_url: str | None = None
    authors: list[str] = []
    topics_auto_added: list[str] = []
    references_found: list[dict] = []
    pdf_fetched: bool = True  # False when no PDF was downloaded (metadata-only ingest)


class IngestFromUrlBody(BaseModel):
    url: str
    project_id: str | None = None
    debug: bool = False


# ── References ─────────────────────────────────────────────────────────────────

class ReferenceOut(BaseModel):
    id: str | None = None
    title: str
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = []


class ReferencesBody(BaseModel):
    references: list[dict]


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []
    model: str = "claude"  # "claude" | "ollama"


class ChatResponse(BaseModel):
    answer: str


# ── Knowledge Chat ──────────────────────────────────────────────────────────────

class KnowledgeChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []
    model: str = "claude"
    conversation_id: str | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    compacted: bool = False
    message_count: int = 0


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    tokens_used: int | None = None
    created_at: str
    paper_refs: list[str] = []


# ── Figures ──────────────────────────────────────────────────────────────────

class FigureOut(BaseModel):
    id: str
    paper_id: str
    figure_number: int | None = None
    caption: str | None = None
    drive_file_id: str
    drive_url: str | None = None
    page_number: int
    created_at: str


class FigureChatRequest(BaseModel):
    question: str
    model: str = "claude"


class FigureExtractRequest(BaseModel):
    caption_method: str = "ollama"  # "ollama" | "claude-vision"
