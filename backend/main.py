import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logger import setup_logging
setup_logging()

from config import settings
from db.connection import get_driver, close_driver
from db.schema import run_schema_setup
from models.schemas import HealthResponse

log = logging.getLogger(__name__)
from routers import papers
from routers.people import people_router, papers_router as people_papers_router
from routers.tags import tags_router, papers_router as tags_papers_router, seed_default_tags
from routers.topics import topics_router, papers_router as topics_papers_router
from routers.projects import router as projects_router
from routers.search import router as search_router
from routers.graph import router as graph_router
from routers.stats import router as stats_router
from routers.cypher import router as cypher_router
from routers.export import router as export_router
from routers.backfill import router as backfill_router
from routers.knowledge_chat import router as knowledge_chat_router
from routers.figures import router as figures_router
from routers.bulk_import import router as bulk_import_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("PaperManager backend starting up")
    get_driver().verify_connectivity()
    log.info("Neo4j connection verified")
    run_schema_setup(get_driver())
    log.info("Schema ready")
    seed_default_tags(get_driver())
    log.info("Default tags ready")
    yield
    log.info("PaperManager backend shutting down")


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
app.include_router(graph_router)
app.include_router(stats_router)
app.include_router(cypher_router)
app.include_router(export_router)
app.include_router(backfill_router)
app.include_router(knowledge_chat_router)
app.include_router(figures_router)
app.include_router(bulk_import_router)


@app.get("/health", response_model=HealthResponse)
def health():
    try:
        get_driver().verify_connectivity()
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "unreachable"
    return HealthResponse(status="ok", neo4j=neo4j_status)
