"""Token-ledger hook: records every LLM call made through the Anthropic and OpenAI SDKs.

``install()`` wraps, once and at class level (so every client instance is covered, whatever
key, gateway or proxy it points at):

* ``anthropic`` ``Messages.create`` (also ``stream=True``) and ``Messages.stream``, and the
  same two on the beta ``Messages`` (``client.beta.messages.stream`` in services/concepts.py);
* ``openai`` chat ``Completions.create`` (also ``stream=True``) and ``Embeddings.create``
  (the LiteLLM proxy and OpenAI, through services/litellm_client.py).

Wrapping the SDK instead of the call sites means new call sites are covered automatically.
Streams are returned as transparent proxies that record once, when the stream is exhausted,
closed or fails. Recording never raises into the call path. Claude Code (a subprocess, not an
SDK call) records explicitly with ``record_call`` from services/claude_code_chat.py.

Attribution (feature / label / paper / user) comes from ``usage_context`` first and from the
call stack second (see ``FEATURE_RULES``); it is resolved when the call starts, because a
stream is consumed later and possibly elsewhere.
"""
from __future__ import annotations

import contextlib
import importlib.abc
import importlib.machinery
import functools
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlparse

from services.usage import ledger, pricing

log = logging.getLogger(__name__)

# ── attribution ───────────────────────────────────────────────────────────────

# "<module path>:<function>" or "<module path>" (all of a file) or "<dir>/" (a whole folder)
# -> feature. The function rule wins over the file rule.
FEATURE_RULES: dict[str, str] = {
    # services/ai.py
    "services/ai.py:summarize_paper": "summary",
    "services/ai.py:suggest_topics": "topics",
    "services/ai.py:extract_claims": "claims",
    "services/ai.py:knowledge_chat_stream": "knowledge-chat",
    "services/ai.py:_stream_round": "knowledge-chat",
    "services/ai.py:execute_library_tool": "knowledge-chat",
    "services/ai.py:_condense_paper_for_budget": "knowledge-chat",
    "services/ai.py:chat_with_paper": "paper-chat",
    "services/ai.py:chat_with_paper_work": "paper-chat",
    "services/ai.py:chat_with_paper_litellm": "paper-chat",
    "services/ai.py:_run_claude_with_tools": "paper-chat",
    "services/ai.py:summarize_chapter": "chapters",
    "services/ai.py:chat_with_chapter": "chapters",
    "services/ai.py:detect_chapters_with_ai": "chapters",
    "services/ai.py:extract_affiliations_with_litellm": "affiliations",
    "services/ai.py:summarize_blog_post": "blogs",
    "services/ai.py:chat_with_blog_post": "blogs",
    "services/ai.py:find_research_gaps": "research-gaps",
    "services/ai.py:synthesize_papers": "synthesis",
    "services/ai.py:_fetch_web_context": "synthesis",
    # _generate_search_queries / _web_presearch are shared by the knowledge chat and the
    # synthesis: no rule, so the private-helper fall-through takes the caller's feature.
    # services
    "services/concepts.py": "concepts",
    "services/concept_map.py": "concept-map",
    "services/paper_tour.py": "tour",
    "services/person_cv.py": "cv-builder",
    "services/references.py": "references",
    "services/figure_extractor.py": "figure-captions",
    "services/ideogram_magic.py": "ideogram",
    "services/tag_suggester.py": "tags",
    "services/person_enrichment.py": "people",
    "services/blog_fetcher.py": "blogs",
    "services/book_chapter_parser.py": "chapters",
    "services/pdf_parser.py": "metadata",
    "services/bulk_resolver.py": "bulk-import",
    "services/embeddings.py": "embeddings",
    "services/duplicate_scan.py": "merge-scan",
    "services/suggestions.py": "suggestions",
    "services/reports/": "reports",
    "services/claude_code_chat.py:knowledge_chat_claude_code": "knowledge-chat",
    "services/claude_code_chat.py:chat_with_paper_claude_code": "paper-chat",
    # routers
    "routers/figures.py": "figure-chat",
    "routers/cypher.py": "cypher-assist",
    "routers/knowledge_chat.py": "knowledge-chat",
    "routers/knowledge_chat.py:compact": "chat-compaction",
    "routers/tags.py": "tags",
    "routers/people.py": "people",
    "routers/search.py": "search",
    "routers/users.py": "user-insights",
    "routers/merge.py": "merge-scan",
    "routers/papers.py:ai_extract_metadata": "metadata",
    "routers/papers.py:_generate_search_keywords": "discover",
}

# Generic runners: the caller decides the feature, so these frames are looked through.
_SKIP_FRAMES = {
    ("services/litellm_client.py", None),
    ("services/claude_code_chat.py", "run_structured_claude_code"),
    ("services/claude_code_chat.py", "_drive"),
    ("services/claude_code_chat.py", "_run"),
}
_SKIP_PREFIX = "services/usage/"
_TRANSPARENT = {"<lambda>", "<genexpr>", "<listcomp>", "<dictcomp>", "<setcomp>"}
_MAX_BACKEND_FRAMES = 40

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_rel_cache: dict[str, Optional[str]] = {}
_ctx: ContextVar[Optional[dict[str, Optional[str]]]] = ContextVar("usage_context", default=None)


@contextlib.contextmanager
def usage_context(
    feature: str | None = None, paper_id: str | None = None, user: str | None = None, label: str | None = None,
) -> Iterator[None]:
    """Attribute the LLM calls made inside the block; nests, inner non-None values win."""
    merged = dict(_ctx.get() or {})
    for key, value in (("feature", feature), ("paper_id", paper_id), ("user", user), ("label", label)):
        if value is not None:
            merged[key] = value
    token = _ctx.set(merged)
    try:
        yield
    finally:
        try:
            _ctx.reset(token)
        except ValueError:  # a generator closed in another context: nothing to restore there
            pass


def _rel_path(filename: str) -> Optional[str]:
    """Path of a source file relative to backend/ (posix), or None when it is not backend code."""
    if filename in _rel_cache:
        return _rel_cache[filename]
    rel: Optional[str] = None
    absolute = os.path.abspath(filename)
    if absolute.startswith(_BACKEND_DIR + os.sep):
        rel = absolute[len(_BACKEND_DIR) + 1:].replace(os.sep, "/")
        if set(rel.split("/")[:-1]) & {"site-packages", ".venv", "venv", "node_modules"}:
            rel = None
    _rel_cache[filename] = rel
    return rel


def _skipped(rel: str, func: str) -> bool:
    return (
        rel.startswith(_SKIP_PREFIX) or func in _TRANSPARENT
        or (rel, None) in _SKIP_FRAMES or (rel, func) in _SKIP_FRAMES
    )


def _feature_for(rel: str, func: str) -> Optional[str]:
    found = FEATURE_RULES.get(f"{rel}:{func}") or FEATURE_RULES.get(rel)
    if found:
        return found
    for key, feature in FEATURE_RULES.items():
        if key.endswith("/") and rel.startswith(key):
            return feature
    return None


def _module(rel: str) -> str:
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")


def _short_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and 0 < len(value) <= 80 else None


def _scan_stack(skip: int, want_site: bool, want_paper: bool, want_user: bool) -> dict[str, Optional[str]]:
    """Walk the call stack outward from the caller of ``capture``/``record_call``."""
    out: dict[str, Optional[str]] = {"feature": None, "label": None, "paper_id": None, "user": None}
    try:
        frame = sys._getframe(skip)
    except ValueError:
        return out
    feature_open = want_site
    seen = 0
    while frame is not None and seen < _MAX_BACKEND_FRAMES:
        code = frame.f_code
        rel = _rel_path(code.co_filename)
        if rel is not None and not _skipped(rel, code.co_name):
            seen += 1
            name = code.co_name
            if want_site and out["label"] is None:
                out["label"] = f"{_module(rel)}.{name}"
            if feature_open:
                found = _feature_for(rel, name)
                if found:
                    out["feature"], feature_open = found, False
                elif not name.startswith("_"):
                    feature_open = False  # a public, unmapped function: its caller is not the feature
            if want_paper and out["paper_id"] is None or want_user and out["user"] is None:
                try:
                    local_vars = frame.f_locals
                    if want_paper and out["paper_id"] is None:
                        out["paper_id"] = _short_str(local_vars.get("paper_id"))
                    if want_user and out["user"] is None:
                        out["user"] = _short_str(local_vars.get("current_user")) or _short_str(local_vars.get("username"))
                except Exception:  # noqa: BLE001
                    pass
        frame = frame.f_back
    return out


def capture(skip: int = 2) -> dict[str, Optional[str]]:
    """Resolve the attribution for a call made right now: ``{feature, label, paper_id, user}``.

    Explicit ``usage_context`` values win; the rest comes from the stack. Threads that lose
    the stack (Claude Code's worker) capture here and re-enter with ``usage_context(**captured)``.
    """
    ctx = _ctx.get() or {}
    feature, label, paper_id, user = (ctx.get(k) for k in ("feature", "label", "paper_id", "user"))
    if user is None:
        try:
            from services.auth import get_request_user

            user = get_request_user()
        except Exception:  # noqa: BLE001
            user = None
    inferred = _scan_stack(skip, want_site=feature is None or label is None,
                           want_paper=paper_id is None, want_user=user is None)
    label = label or inferred["label"] or ""
    feature = feature or inferred["feature"] or label or "unknown"
    return {
        "feature": feature, "label": label,
        "paper_id": paper_id or inferred["paper_id"], "user": user or inferred["user"],
    }


# ── recording ─────────────────────────────────────────────────────────────────

def record_call(
    *,
    provider: str,
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reported_cost: float | None = None,
    cost_usd: float | None = None,
    latency_ms: int = 0,
    ok: bool = True,
    error: str | None = None,
    streamed: bool = False,
    estimated: bool = False,
    attribution: dict[str, Optional[str]] | None = None,
) -> None:
    """Write one ledger row. Never raises.

    ``cost_usd`` (alias ``reported_cost``) is a cost the provider reported itself (the Claude
    Code CLI's ``total_cost_usd``); it wins over the price table.
    """
    reported_cost = reported_cost if reported_cost is not None else cost_usd
    try:
        if not ledger.enabled():
            return
        attr = attribution or capture(skip=3)
        input_tokens, output_tokens = int(input_tokens or 0), int(output_tokens or 0)
        cache_read_tokens, cache_write_tokens = int(cache_read_tokens or 0), int(cache_write_tokens or 0)
        cost, known = pricing.cost(
            provider, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reported_cost
        )
        ledger.record({
            "feature": attr.get("feature") or "unknown", "label": attr.get("label") or "",
            "provider": provider, "model": model or "",
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens, "cache_write_tokens": cache_write_tokens,
            "cost_usd": cost, "price_known": 1 if known else 0,
            "username": attr.get("user"), "paper_id": attr.get("paper_id"),
            "ok": 1 if ok else 0, "error": (error or None) and error[:300],
            "latency_ms": int(latency_ms or 0), "streamed": 1 if streamed else 0,
            "estimated": 1 if estimated else 0,
        })
    except Exception as exc:  # noqa: BLE001
        log.debug("record_call failed: %s", exc)


def _err(exc: BaseException | None) -> Optional[str]:
    return f"{type(exc).__name__}: {exc}"[:300] if exc is not None else None


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _provider(resource: Any, kind: str) -> str:
    """Provider from the client's base URL host."""
    try:
        host = urlparse(str(resource._client.base_url)).hostname or ""
    except Exception:  # noqa: BLE001
        host = ""
    if kind == "anthropic":
        return "anthropic" if host == "api.anthropic.com" else "anthropic-gateway"
    return "openai" if host == "api.openai.com" else "litellm"


def _int(obj: Any, name: str) -> int:
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return int(value) if isinstance(value, (int, float)) else 0


class _Usage:
    """Token counts accumulated for one call."""

    __slots__ = ("input", "output", "cache_read", "cache_write", "seen")

    def __init__(self) -> None:
        self.input = self.output = self.cache_read = self.cache_write = 0
        self.seen = False

    def anthropic(self, usage: Any) -> None:
        """Merge an Anthropic usage object (message_start / message_delta / final message)."""
        if usage is None:
            return
        self.seen = True
        for attr, name in (("input", "input_tokens"), ("output", "output_tokens"),
                           ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
            value = _int(usage, name)
            if value:
                setattr(self, attr, value)  # event fields are cumulative: the latest wins

    def openai(self, usage: Any) -> None:
        """Set from an OpenAI usage object: input is the prompt without its cached part."""
        if usage is None:
            return
        self.seen = True
        prompt = _int(usage, "prompt_tokens")
        details = usage.get("prompt_tokens_details") if isinstance(usage, dict) else getattr(usage, "prompt_tokens_details", None)
        cached = _int(details, "cached_tokens") if details is not None else 0
        self.cache_read = cached
        self.input = max(0, prompt - cached)
        self.output = _int(usage, "completion_tokens")


def _anthropic_event(acc: _Usage, event: Any) -> None:
    kind = getattr(event, "type", None)
    if kind == "message_start":
        acc.anthropic(getattr(getattr(event, "message", None), "usage", None))
    elif kind == "message_delta":
        acc.anthropic(getattr(event, "usage", None))


def _text_len(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, (list, tuple)):
        return sum(_text_len(c) for c in content)
    if isinstance(content, dict):
        return _text_len(content.get("text") or content.get("content") or "")
    return len(str(getattr(content, "text", "") or ""))


def _estimate_input_tokens(kwargs: dict[str, Any]) -> int:
    chars = sum(_text_len(m.get("content") if isinstance(m, dict) else getattr(m, "content", ""))
                for m in (kwargs.get("messages") or []))
    return max(1, chars // 4) if chars else 0


class _Call:
    """What one wrapped call has to know to record itself later."""

    def __init__(self, provider: str, model: str | None, streamed: bool) -> None:
        self.provider = provider
        self.model = model
        self.streamed = streamed
        self.t0 = time.perf_counter()
        try:
            self.attr: dict[str, Optional[str]] | None = capture(skip=3)
        except Exception:  # noqa: BLE001
            self.attr = None

    def record(self, usage: _Usage, exc: BaseException | None = None, estimated: bool = False,
               model: str | None = None) -> None:
        record_call(
            provider=self.provider, model=self.model or model, input_tokens=usage.input,
            output_tokens=usage.output, cache_read_tokens=usage.cache_read, cache_write_tokens=usage.cache_write,
            latency_ms=_ms(self.t0), ok=exc is None, error=_err(exc), streamed=self.streamed,
            estimated=estimated, attribution=self.attr,
        )


class _RecordingStream:
    """Transparent proxy of an SDK ``Stream``: forwards everything, records once at the end."""

    def __init__(self, inner: Any, feed: Callable[[Any], None],
                 finish: Callable[[Optional[BaseException]], None]) -> None:
        self._inner = inner
        self._it: Any = None
        self._feed = feed
        self._finish_cb = finish
        self._done = False

    def _finish(self, exc: BaseException | None) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._finish_cb(exc)
        except Exception as err:  # noqa: BLE001
            log.debug("stream record failed: %s", err)

    def __iter__(self) -> "_RecordingStream":
        return self

    def __next__(self) -> Any:
        if self._it is None:
            self._it = iter(self._inner)
        try:
            event = next(self._it)
        except StopIteration:
            self._finish(None)
            raise
        except BaseException as exc:
            self._finish(exc)
            raise
        try:
            self._feed(event)
        except Exception:  # noqa: BLE001
            pass
        return event

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._finish(None)

    def __enter__(self) -> "_RecordingStream":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc is not None:
            self._finish(exc)
        self.close()

    def __del__(self) -> None:
        try:
            self._finish(None)
        except Exception:  # noqa: BLE001
            pass

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name in ("_inner", "_it", "_feed", "_finish_cb", "_done"):
            raise AttributeError(name)
        return getattr(self._inner, name)


class _RecordingStreamManager:
    """Proxy of anthropic's ``MessageStreamManager``: records on exit from the final snapshot."""

    def __init__(self, inner: Any, provider: str, model: str | None) -> None:
        self._inner = inner
        self._provider = provider
        self._model = model
        self._call: _Call | None = None
        self._stream: Any = None

    def __enter__(self) -> Any:
        self._call = _Call(self._provider, self._model, streamed=True)
        try:
            self._stream = self._inner.__enter__()
        except BaseException as exc:
            self._call.record(_Usage(), exc)
            raise
        return self._stream

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        try:
            return self._inner.__exit__(exc_type, exc, tb)
        finally:
            call = self._call
            if call is not None:
                usage = _Usage()
                model = None
                try:
                    snapshot = self._stream.current_message_snapshot
                    usage.anthropic(snapshot.usage)
                    model = getattr(snapshot, "model", None)
                except Exception:  # noqa: BLE001 — nothing was streamed
                    pass
                call.record(usage, exc, model=model)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name in ("_inner", "_provider", "_model", "_call", "_stream"):
            raise AttributeError(name)
        return getattr(self._inner, name)


# ── SDK wrappers ──────────────────────────────────────────────────────────────

def _wrap_anthropic_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not ledger.enabled():
            return orig(self, *args, **kwargs)
        streamed = bool(kwargs.get("stream"))
        try:
            call = _Call(_provider(self, "anthropic"), kwargs.get("model"), streamed)
        except Exception:  # noqa: BLE001
            return orig(self, *args, **kwargs)
        try:
            response = orig(self, *args, **kwargs)
        except Exception as exc:
            call.record(_Usage(), exc)
            raise
        try:
            if streamed:
                acc = _Usage()
                return _RecordingStream(response, lambda ev: _anthropic_event(acc, ev),
                                        lambda exc: call.record(acc, exc))
            usage = _Usage()
            usage.anthropic(getattr(response, "usage", None))
            call.record(usage, model=getattr(response, "model", None))
        except Exception as exc:  # noqa: BLE001
            log.debug("anthropic record failed: %s", exc)
        return response

    return create


def _wrap_anthropic_stream(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    def stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        manager = orig(self, *args, **kwargs)
        if not ledger.enabled():
            return manager
        try:
            return _RecordingStreamManager(manager, _provider(self, "anthropic"), kwargs.get("model"))
        except Exception:  # noqa: BLE001
            return manager

    return stream


def _wrap_openai_chat_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not ledger.enabled():
            return orig(self, *args, **kwargs)
        streamed = bool(kwargs.get("stream"))
        try:
            call = _Call(_provider(self, "openai"), kwargs.get("model"), streamed)
        except Exception:  # noqa: BLE001
            return orig(self, *args, **kwargs)
        try:
            response = orig(self, *args, **kwargs)
        except Exception as exc:
            call.record(_Usage(), exc)
            raise
        try:
            if streamed:
                acc = _Usage()
                chars = [0]

                def feed(chunk: Any) -> None:
                    if getattr(chunk, "usage", None) is not None:
                        acc.openai(chunk.usage)
                    for choice in getattr(chunk, "choices", None) or []:
                        delta = getattr(choice, "delta", None)
                        chars[0] += len(getattr(delta, "content", None) or "")

                def finish(exc: BaseException | None) -> None:
                    estimated = not acc.seen
                    if estimated:
                        acc.input = _estimate_input_tokens(kwargs)
                        acc.output = chars[0] // 4 if chars[0] else 0
                    call.record(acc, exc, estimated=estimated)

                return _RecordingStream(response, feed, finish)
            usage = _Usage()
            usage.openai(getattr(response, "usage", None))
            call.record(usage, model=getattr(response, "model", None))
        except Exception as exc:  # noqa: BLE001
            log.debug("openai record failed: %s", exc)
        return response

    return create


def _wrap_openai_embeddings_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not ledger.enabled():
            return orig(self, *args, **kwargs)
        try:
            call = _Call(_provider(self, "openai"), kwargs.get("model"), False)
        except Exception:  # noqa: BLE001
            return orig(self, *args, **kwargs)
        try:
            response = orig(self, *args, **kwargs)
        except Exception as exc:
            call.record(_Usage(), exc)
            raise
        try:
            usage = _Usage()
            raw = getattr(response, "usage", None)
            if raw is not None:
                usage.seen = True
                usage.input = _int(raw, "prompt_tokens") or _int(raw, "total_tokens")
            call.record(usage, model=getattr(response, "model", None))
        except Exception as exc:  # noqa: BLE001
            log.debug("embeddings record failed: %s", exc)
        return response

    return create


# ── install ───────────────────────────────────────────────────────────────────

_MARK = "_pm_usage_original"
_installed: list[tuple[Any, str, Any]] = []  # (class, method name, original)


def _targets(only_loaded: bool = False) -> list[tuple[Any, str, Callable[[Callable[..., Any]], Callable[..., Any]]]]:
    targets: list[tuple[Any, str, Callable[[Callable[..., Any]], Callable[..., Any]]]] = []
    if only_loaded and "anthropic" not in sys.modules and "openai" not in sys.modules:
        return targets
    try:
        if only_loaded and "anthropic" not in sys.modules:
            raise _NotLoaded
        from anthropic.resources.messages.messages import Messages
        targets += [(Messages, "create", _wrap_anthropic_create), (Messages, "stream", _wrap_anthropic_stream)]
    except _NotLoaded:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Token ledger: anthropic Messages not wrapped (%s)", exc)
    try:
        if only_loaded and "anthropic" not in sys.modules:
            raise _NotLoaded
        from anthropic.resources.beta.messages.messages import Messages as BetaMessages
        targets += [(BetaMessages, "create", _wrap_anthropic_create), (BetaMessages, "stream", _wrap_anthropic_stream)]
    except _NotLoaded:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Token ledger: anthropic beta Messages not wrapped (%s)", exc)
    try:
        if only_loaded and "openai" not in sys.modules:
            raise _NotLoaded
        from openai.resources.chat.completions.completions import Completions
        targets.append((Completions, "create", _wrap_openai_chat_create))
    except _NotLoaded:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Token ledger: openai Completions not wrapped (%s)", exc)
    try:
        if only_loaded and "openai" not in sys.modules:
            raise _NotLoaded
        from openai.resources.embeddings import Embeddings
        targets.append((Embeddings, "create", _wrap_openai_embeddings_create))
    except _NotLoaded:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Token ledger: openai Embeddings not wrapped (%s)", exc)
    return targets


class _NotLoaded(Exception):
    """The SDK is not imported yet (lazy install)."""


def install(only_loaded: bool = False) -> None:
    """Wrap the SDK methods once; calling it again does nothing.

    ``only_loaded`` wraps only the SDKs already imported (used by ``install_lazy``).
    """
    for cls, name, wrap in _targets(only_loaded):
        current = cls.__dict__.get(name)
        if current is None or hasattr(current, _MARK):
            continue
        wrapper = wrap(current)
        setattr(wrapper, _MARK, current)
        setattr(cls, name, wrapper)
        _installed.append((cls, name, current))


class _SdkImportHook(importlib.abc.MetaPathFinder):
    """Wrap an SDK right after its first import (``install_lazy``)."""

    _NAMES = ("anthropic", "openai")

    def find_spec(self, name: str, path: Any, target: Any = None) -> Any:
        if name not in self._NAMES:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        loader = getattr(spec, "loader", None)
        if loader is None or not hasattr(loader, "exec_module"):
            return None  # found elsewhere: imported unwrapped, as without the hook
        original = loader.exec_module

        def exec_module(module: Any) -> None:
            original(module)
            try:
                install(only_loaded=True)
            except Exception as exc:  # noqa: BLE001 — never break the import
                log.debug("lazy install failed: %s", exc)

        loader.exec_module = exec_module
        return spec


def install_lazy() -> None:
    """Like ``install``, for processes that should not import the SDKs at startup (the MCP
    server): wraps what is loaded now and the rest the moment it is first imported."""
    install(only_loaded=True)
    if not any(isinstance(f, _SdkImportHook) for f in sys.meta_path):
        sys.meta_path.insert(0, _SdkImportHook())


def uninstall() -> None:
    """Restore the original SDK methods (tests)."""
    while _installed:
        cls, name, original = _installed.pop()
        setattr(cls, name, original)
