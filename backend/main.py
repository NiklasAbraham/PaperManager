import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from logger import setup_logging
setup_logging()

from config import settings
from db.connection import get_driver, close_driver, reset_driver
from db.schema import run_schema_setup
from models.schemas import HealthResponse
from services.rate_limit import LimitRule, RateLimitMiddleware, parse_csv_paths
from services.auth import extract_user_from_request, reset_request_user, set_request_user

log = logging.getLogger(__name__)
from routers import papers
from routers.auth import router as auth_router
from routers.people import people_router, papers_router as people_papers_router
from routers.tags import tags_router, papers_router as tags_papers_router, seed_default_tags
from routers.people import seed_people_tags
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
from routers.literature import router as literature_router
from routers.admin import router as admin_router
from routers.chapters import router as chapters_router
from routers.blogs import router as blogs_router
from routers.annotations import router as annotations_router
from routers.users import router as users_router
from routers.research_gaps import router as research_gaps_router
from routers.venues import router as venues_router
from routers.claims import router as claims_router
from routers.synthesis import router as synthesis_router
from routers.discover import router as discover_router
from routers.author_tracker import router as author_tracker_router
from routers.merge import router as merge_router
from routers.audit_log import router as audit_log_router
from routers.ideogram import router as ideogram_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("PaperManager backend starting up")
    # Enlarge the threadpool that serves sync endpoints. The default (40) can be
    # starved by a handful of long /papers/upload requests (each parks a thread
    # while Docling runs), which would block /auth/login from getting a worker.
    import anyio.to_thread
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = settings.server_threadpool_size
    log.info("Threadpool size set to %d", settings.server_threadpool_size)
    get_driver().verify_connectivity()
    log.info("Neo4j connection verified")
    run_schema_setup(get_driver())
    log.info("Schema ready")
    seed_default_tags(get_driver())
    log.info("Default tags ready")
    seed_people_tags(get_driver())
    log.info("People tags ready")
    yield
    log.info("PaperManager backend shutting down")


app = FastAPI(title="PaperManager API", lifespan=lifespan)

trusted_hosts = [host.strip() for host in settings.trusted_hosts.split(",") if host.strip()]
if trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from neo4j.exceptions import ServiceUnavailable, SessionExpired


class Neo4jReconnectMiddleware(BaseHTTPMiddleware):
    """Catch dead-connection errors from Neo4j Aura, reset the driver, and return 503."""
    async def dispatch(self, request: Request, call_next):
        request_user = extract_user_from_request(request)
        ctx_token = set_request_user(request_user)
        try:
            return await call_next(request)
        except (ServiceUnavailable, SessionExpired) as exc:
            log.warning("Neo4j connection lost — resetting driver: %s", exc)
            try:
                reset_driver()
            except Exception as e:
                log.error("Neo4j reconnect failed: %s", e)
            return JSONResponse(
                {"detail": "Database connection was reset. Please retry your request."},
                status_code=503,
            )
        finally:
            reset_request_user(ctx_token)


app.add_middleware(Neo4jReconnectMiddleware)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defensive response headers for browser clients."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

if settings.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        default_rule=LimitRule(
            requests=settings.rate_limit_default_requests,
            window_seconds=settings.rate_limit_default_window_seconds,
        ),
        auth_rule=LimitRule(
            requests=settings.rate_limit_auth_requests,
            window_seconds=settings.rate_limit_auth_window_seconds,
        ),
        exempt_paths=parse_csv_paths(settings.rate_limit_exempt_paths),
        auth_paths=parse_csv_paths(settings.rate_limit_auth_paths),
        trust_proxy_headers=settings.trust_proxy_headers,
    )


app.include_router(auth_router)
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
app.include_router(literature_router)
app.include_router(admin_router)
app.include_router(chapters_router)
app.include_router(blogs_router)
app.include_router(annotations_router)
app.include_router(users_router)
app.include_router(research_gaps_router)
app.include_router(venues_router)
app.include_router(claims_router)
app.include_router(synthesis_router)
app.include_router(discover_router)
app.include_router(author_tracker_router)
app.include_router(merge_router)
app.include_router(audit_log_router)
app.include_router(ideogram_router)


@app.get("/litellm/models", response_model=list[str])
@app.get("/ollama/models", response_model=list[str], include_in_schema=False)
def list_litellm_models():
    """Return model IDs available through the LiteLLM proxy."""
    from services.litellm_client import list_available_models

    try:
        return list_available_models()
    except Exception:
        from config import settings
        return [settings.litellm_model]


@app.get("/health", response_model=HealthResponse)
def health():
    try:
        get_driver().verify_connectivity()
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "unreachable"
    return HealthResponse(status="ok", neo4j=neo4j_status)
