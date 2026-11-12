"""The report pipeline: scope -> plan -> evidence -> sections -> frame -> save.

``run_report(report_id)`` runs in a job thread (see ``jobs.py``). Every step is persisted to the
Report node through ``db.queries.reports``; the job stops quietly when a write reports that the
report is no longer queued or running (cancelled or deleted), so cancellation takes effect
before the next model call. Failures become ``status = failed`` with a short error.
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path

from db.queries import reports as rq
from services.auth import reset_request_user, set_request_user
from services.reports import llm, render, retrieval

log = logging.getLogger(__name__)

try:  # the token ledger is optional (services/usage)
    from services.usage import usage_context
except ImportError:  # pragma: no cover - depends on the checkout

    def usage_context(**_kwargs):
        return contextlib.nullcontext()


PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
# length -> (sections, words per section, max tokens per section)
LENGTHS = {"short": (3, 350, 1600), "standard": (5, 550, 2400), "long": (7, 800, 3200)}
MAX_CANDIDATES = 60
MAX_SECTION_SOURCES = 8
MIN_SECTION_SOURCES = 3
_FALLBACK_SECTIONS = [
    "Background and definitions",
    "What the papers establish",
    "Methods and evidence",
    "Applications and results",
    "Disagreements and caveats",
    "Related directions",
    "Limits and open problems",
]


class ReportError(Exception):
    """A failure with a message fit to show the user."""


class _Stop(Exception):
    """The report was cancelled or deleted while the job ran."""


def load_prompt(name: str, **values: str) -> str:
    """Read ``prompts/<name>`` fresh and replace ``{{KEY}}`` placeholders (no str.format)."""
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _clip(text: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _strip_fences_and_headings(text: str) -> str:
    """Drop a code fence around the answer and any leading heading line."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    while True:
        m = re.match(r"^#{1,3}\s+[^\n]*\n+", text)
        if not m:
            return text.strip()
        text = text[m.end():]


def parse_label(value, label_map: dict[str, str]) -> str | None:
    """``"C3"``, ``"c3"`` or ``3`` -> the paper id behind label C3."""
    m = re.search(r"\d+", str(value))
    return label_map.get(f"C{m.group()}") if m else None


def normalise_plan(data: dict, n: int, label_map: dict[str, str], question: str) -> dict:
    """Validate the model's plan: at most ``n`` sections, known candidates, clean strings."""
    sections = []
    for raw in data.get("sections") or []:
        if len(sections) == n:
            break
        if not isinstance(raw, dict):
            continue
        title = _clip(str(raw.get("title") or ""), 160)
        if not title:
            continue
        ids = []
        for label in raw.get("candidates") or []:
            pid = parse_label(label, label_map)
            if pid and pid not in ids:
                ids.append(pid)
        queries = [_clip(str(q), 120) for q in (raw.get("queries") or []) if str(q).strip()][:3]
        sections.append({
            "title": title,
            "focus": _clip(str(raw.get("focus") or ""), 400),
            "queries": queries,
            "ids": ids[:MAX_SECTION_SOURCES],
        })
    if not sections:
        raise ValueError("The plan has no sections")
    return {
        "title": _clip(str(data.get("title") or ""), 200) or _clip(question, 120),
        "lede": _clip(str(data.get("lede") or ""), 600),
        "sections": sections,
    }


def fallback_plan(question: str, n: int, ids: list[str]) -> dict:
    """A generic plan used when the model cannot produce a valid one."""
    sections = []
    for i in range(n):
        chunk = ids[i * 4: i * 4 + MAX_SECTION_SOURCES] or ids[:MAX_SECTION_SOURCES]
        sections.append({
            "title": _FALLBACK_SECTIONS[i % len(_FALLBACK_SECTIONS)],
            "focus": f"Set out what the library's papers say about: {question}",
            "queries": [_clip(question, 120)],
            "ids": chunk,
        })
    return {"title": _clip(question, 120), "lede": "", "sections": sections}


class _Job:
    """State and steps of one report run."""

    def __init__(self, driver, report: dict, cancel_event=None) -> None:
        self.driver = driver
        self.cancel_event = cancel_event
        self.report = report
        self.id = report["id"]
        self.owner = report["owner"]
        self.model = report.get("model") if report.get("model") in llm.MODELS else llm.DEFAULT_MODEL
        self.length = report.get("length") if report.get("length") in LENGTHS else "standard"
        self.project_id = report.get("project_id") or None
        self.question = ""
        self.candidates: dict[str, dict] = {}
        self.evidence: dict[str, dict] = {}
        self.raw: dict[str, str] = {}
        self.numbers: dict[str, int] = {}  # paper id -> global source number
        self.title = ""

    # -- plumbing

    def step(self, stage: str, progress: int, message: str, **extra) -> None:
        """Persist progress; raise _Stop when the report is no longer active."""
        if self.cancel_event is not None and self.cancel_event.is_set():
            rq.cancel_report(self.driver, self.id)
            raise _Stop()
        ok = rq.update_progress(
            self.driver, self.id, status="running", stage=stage, progress=progress, step=message, **extra
        )
        if not ok:
            raise _Stop()

    def ask(self, prompt: str, max_tokens: int, json_mode: bool = False) -> str:
        return llm.complete(
            [{"role": "user", "content": prompt}], model=self.model, max_tokens=max_tokens, json_mode=json_mode
        )

    def sources(self) -> dict[int, dict]:
        """Source number -> paper dict for render.assemble."""
        out = {}
        for pid, n in self.numbers.items():
            ev = self.evidence.get(pid) or self.candidates.get(pid) or {}
            out[n] = {
                "id": pid,
                "title": ev.get("title") or "",
                "year": ev.get("year"),
                "venue": ev.get("venue") or "",
                "authors": ev.get("authors") or [],
            }
        return out

    # -- stages

    def run(self) -> None:
        self.step("scope", 2, "Starting")
        self.scope()
        plan = self.plan()
        self.gather_evidence(plan)
        bodies = self.write_sections(plan)
        frame = self.write_frame(plan, bodies)
        self.save(plan, frame, bodies)

    def scope(self) -> None:
        r = self.report
        question = (r.get("question") or "").strip()
        ids = list(json.loads(r.get("paper_ids_json") or "[]"))
        name = r.get("project_name") or ""
        if not question:
            if self.project_id:
                question = f"An overview of the literature in the project “{name or 'selected project'}”"
            else:
                question = "An overview of the selected papers"
        self.question = question

        found: dict[str, dict] = {}

        def add(rows: list[dict]) -> None:
            for row in rows:
                if row.get("id") and row["id"] not in found and len(found) < MAX_CANDIDATES:
                    found[row["id"]] = row

        add(retrieval.papers_by_ids(self.driver, ids))
        if (r.get("question") or "").strip():
            add(retrieval.search(self.driver, question, project_id=self.project_id, limit=30))
        if self.project_id:
            add(retrieval.project_papers(self.driver, self.project_id, MAX_CANDIDATES))
        self.evidence = retrieval.fetch_evidence(self.driver, list(found))
        self.candidates = {pid: row for pid, row in found.items() if pid in self.evidence}
        if not self.candidates:
            raise ReportError("The library has no papers for this question, so there is nothing to write from.")
        self.step("scope", 10, f"Found {len(self.candidates)} candidate papers")

    def plan(self) -> dict:
        n_sections = LENGTHS[self.length][0]
        label_map, lines = {}, []
        for i, (pid, row) in enumerate(self.candidates.items(), start=1):
            label_map[f"C{i}"] = pid
            ev = self.evidence[pid]
            year = f" ({ev['year']})" if ev.get("year") else ""
            lines.append(f"C{i} | {_clip(ev.get('title'), 140)}{year} | {_clip(ev.get('summary') or ev.get('abstract'), 160)}")
        self.step("plan", 12, "Planning the report")
        prompt = load_prompt(
            "report_plan.txt",
            QUESTION=self.question,
            LENGTH=self.length,
            SECTIONS=str(n_sections),
            CANDIDATES="\n".join(lines),
        )
        plan = None
        for attempt in range(2):
            try:
                plan = normalise_plan(
                    llm.parse_json(self.ask(prompt, 2000, json_mode=True)), n_sections, label_map, self.question
                )
                break
            except ValueError as exc:
                log.warning("report %s: plan attempt %d invalid: %s", self.id, attempt + 1, exc)
                if attempt == 0:
                    self.step("plan", 14, "The plan was not valid, trying once more")
        if plan is None:
            plan = fallback_plan(self.question, n_sections, list(self.candidates))
            self.step("plan", 18, "Using a generic outline")
        self.title = plan["title"]
        self.step("plan", 20, f"Planned {len(plan['sections'])} sections: {self.title}", title=self.title)
        return plan

    def gather_evidence(self, plan: dict) -> None:
        sections = plan["sections"]
        n = len(sections)
        budget = llm.evidence_budget(self.model)
        for i, sec in enumerate(sections):
            self.step(
                "evidence", 20 + round(35 * i / n), f"Reading the evidence for section {i + 1} of {n}: {sec['title']}"
            )
            ranked = list(sec["ids"])
            for query in sec["queries"]:
                for hit in retrieval.search(self.driver, query, project_id=self.project_id, limit=6):
                    if hit["id"] not in ranked:
                        ranked.append(hit["id"])
            ranked = ranked[:MAX_SECTION_SOURCES]
            if len(ranked) < MIN_SECTION_SOURCES:
                for pid in self.candidates:
                    if pid not in ranked and len(ranked) < MIN_SECTION_SOURCES:
                        ranked.append(pid)
            missing = [pid for pid in ranked if pid not in self.evidence]
            if missing:
                self.evidence.update(retrieval.fetch_evidence(self.driver, missing))
            ranked = [pid for pid in ranked if pid in self.evidence]
            need_raw = [pid for pid in ranked if pid not in self.raw]
            if need_raw:
                self.raw.update(retrieval.fetch_raw(self.driver, need_raw))
            terms = retrieval.query_terms(self.question, sec["title"], sec["focus"], " ".join(sec["queries"]))
            per_source = max(600, budget // max(1, len(ranked)))
            blocks = []
            for pid in ranked:
                number = self.numbers.setdefault(pid, len(self.numbers) + 1)
                passages = retrieval.find_passages(self.raw.get(pid, ""), terms)
                blocks.append(retrieval.format_source(f"S{number}", self.evidence[pid], passages, per_source))
            sec["source_ids"] = ranked
            sec["source_block"] = "\n\n".join(blocks)
        self.step("evidence", 55, f"Collected evidence from {len(self.numbers)} papers", paper_count=len(self.numbers))

    def write_sections(self, plan: dict) -> list[str]:
        sections = plan["sections"]
        n = len(sections)
        _, words, max_tokens = LENGTHS[self.length]
        bodies: list[str] = []
        for i, sec in enumerate(sections):
            self.step("sections", 55 + round(35 * i / n), f"Writing section {i + 1} of {n}: {sec['title']}")
            if not sec.get("source_ids"):
                bodies.append("The library holds no papers that bear on this part of the question.")
                continue
            outline = "\n".join(
                f"{j + 1}. {other['title']}: {other['focus']}" for j, other in enumerate(sections) if j != i
            )
            prompt = load_prompt(
                "report_section.txt",
                TITLE=plan["title"],
                QUESTION=self.question,
                SECTION_TITLE=sec["title"],
                FOCUS=sec["focus"] or sec["title"],
                OUTLINE=outline or "(none)",
                SOURCES=sec["source_block"],
                WORDS=str(words),
            )
            body = ""
            for _ in range(2):
                body = _strip_fences_and_headings(self.ask(prompt, max_tokens))
                if body:
                    break
            if not body:
                raise ReportError(f"The model returned nothing for section {i + 1} ({sec['title']}).")
            bodies.append(body)
        self.step("sections", 90, f"Wrote {n} sections")
        return bodies

    def write_frame(self, plan: dict, bodies: list[str]) -> dict:
        self.step("frame", 91, "Writing the introduction and the closing section")
        sections = plan["sections"]
        marker = re.compile(r"\[S\d+(?:\s*[,;]\s*S\d+)*\]")
        digest = "\n".join(
            f"{i + 1}. {sec['title']}: {_clip(marker.sub('', body), 350)}"
            for i, (sec, body) in enumerate(zip(sections, bodies))
        )
        cited = sorted({int(x) for body in bodies for m in marker.findall(body) for x in re.findall(r"S(\d+)", m)})
        sources = self.sources()
        listed = [s for s in cited if s in sources] or sorted(sources)
        source_lines = "\n".join(
            f"S{s}: {_clip(sources[s]['title'], 120)}" + (f" ({sources[s]['year']})" if sources[s]["year"] else "")
            for s in listed[:60]
        )
        prompt = load_prompt(
            "report_frame.txt", TITLE=plan["title"], QUESTION=self.question, SECTIONS=digest, SOURCES=source_lines
        )
        for attempt in range(2):
            try:
                data = llm.parse_json(self.ask(prompt, 2200, json_mode=True))
                closing = _strip_fences_and_headings(str(data.get("closing") or ""))
                lede = _clip(str(data.get("lede") or ""), 700) or plan["lede"]
                if closing:
                    return {
                        "lede": lede,
                        "intro": _strip_fences_and_headings(str(data.get("introduction") or "")),
                        "closing": closing,
                    }
                raise ValueError("The frame has no closing section")
            except ValueError as exc:
                log.warning("report %s: frame attempt %d invalid: %s", self.id, attempt + 1, exc)
        return {
            "lede": plan["lede"] or f"This report reads {len(sources)} papers from your library on: {self.question}",
            "intro": "",
            "closing": (
                f"This report draws on {len(sources)} papers from your library. The sections above set out what "
                "they establish; wherever a section says the library is silent, treat that part of the question "
                "as open and look beyond the library before relying on it."
            ),
        }

    def save(self, plan: dict, frame: dict, bodies: list[str]) -> None:
        self.step("save", 97, "Assembling the report and its references")
        result = render.assemble(
            plan["title"],
            frame["lede"],
            frame["intro"],
            [{"title": sec["title"], "body": body} for sec, body in zip(plan["sections"], bodies)],
            frame["closing"],
            self.sources(),
        )
        saved = rq.finish_report(
            self.driver,
            self.id,
            title=plan["title"],
            markdown=result["markdown"],
            word_count=result["word_count"],
            cited=result["cited"],
        )
        if not saved:
            log.info("report %s: finished after it was cancelled or deleted; result dropped", self.id)


def _error_text(exc: Exception) -> str:
    if isinstance(exc, ReportError):
        return str(exc)[:1000]
    return f"{type(exc).__name__}: {exc}"[:1000]


def run_report(report_id: str, driver=None, cancel_event=None) -> None:
    """Run the whole pipeline for one report; never raises.

    ``cancel_event`` (a ``threading.Event`` from ``jobs.py``) stops the job before its next step.
    """
    owner_token = None
    try:
        if driver is None:
            from db.connection import get_driver

            driver = get_driver()
        report = rq.get_report(driver, report_id)
        if not report or report.get("status") not in rq.ACTIVE:
            return
        owner_token = set_request_user(report["owner"])
        with usage_context(feature="reports", user=report["owner"]):
            _Job(driver, report, cancel_event).run()
    except _Stop:
        log.info("report %s: stopped (cancelled or deleted)", report_id)
    except Exception as exc:  # noqa: BLE001 — a job must never crash its thread
        log.exception("report %s failed", report_id)
        try:
            if driver is not None:
                rq.fail_report(driver, report_id, _error_text(exc))
        except Exception:  # noqa: BLE001
            log.exception("report %s: could not record the failure", report_id)
    finally:
        if owner_token is not None:
            reset_request_user(owner_token)
