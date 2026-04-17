from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db.connection import get_driver, close_driver
from db.schema import run_schema_setup
from models.schemas import HealthResponse
from routers import papers
from routers.people import people_router, papers_router as people_papers_router
from routers.tags import tags_router, papers_router as tags_papers_router
from routers.topics import topics_router, papers_router as topics_papers_router
from routers.projects import router as projects_router
from routers.search import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify Neo4j is reachable, then ensure schema exists
    get_driver().verify_connectivity()
    run_schema_setup(get_driver())
    yield
    # Driver intentionally left open; the process exit cleans it up.
    # Explicit close would break test suites that reuse the singleton.


app = FastAPI(title="PaperManager API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(papers.router)
app.include_router(people_router)
app.include_router(people_papers_router)
app.include_router(tags_router)
app.include_router(tags_papers_router)
app.include_router(topics_router)
app.include_router(topics_papers_router)
app.include_router(projects_router)
app.include_router(search_router)


@app.get("/health", response_model=HealthResponse)
def health():
    try:
        get_driver().verify_connectivity()
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "unreachable"
    return HealthResponse(status="ok", neo4j=neo4j_status)
