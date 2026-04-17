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


class PaperUpdate(BaseModel):
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    summary: str | None = None


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


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    answer: str
