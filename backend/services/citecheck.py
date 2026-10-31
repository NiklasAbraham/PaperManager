#!/usr/bin/env python3
"""Citation link checker: does every DOI, arXiv id and URL a document cites resolve, and to the cited work?

    python3 050_system/scripts/citecheck.py 070_reports/090_guidance_and_steering
    python3 050_system/scripts/citecheck.py 080_thesis/010_thesis/references.bib
    python3 050_system/scripts/citecheck.py notes.md --json

Inputs: a report folder (its index.html and papers.json), an .html, .bib, .md / .txt or papers.json file.
Checks, all in parallel and without any language model:

  doi    GET https://doi.org/<doi> with Accept: CSL-JSON (Crossref, DataCite, mEDRA answer with the record);
         a 404 there is confirmed with the handle API (doi.org/api/handles), which knows every DOI.
  arxiv  one batched request to the arXiv API per 100 ids (also 10.48550/arXiv.* DOIs and arxiv.org links).
  url    HEAD, then GET when HEAD is refused; 401/403/429 count as "blocked" (reachable, bot-protected).
  file   relative links in an HTML page must point to an existing file.
  pm     PaperManager links (papermanager.niklas-abraham.de/paper/<id>, paperId in papers.json): the id must
         exist in the library, checked in one query through `docker exec papermanager-backend-1` (the command is
         $CITECHECK_PM_CMD); skipped where docker or the container is not there.

When the citing document gives a title (papers.json, a .bib entry) the resolved title must match it; for a link in
an HTML reference list the resolved title must appear in the list item's text. A failed match is "mismatch": the
identifier exists but names a different work (the usual LLM error). Results are cached in
050_system/.cache/citecheck.json (ok for 30 days, failures for 1 day). Exit 1 on any dead, mismatch or missing
file; --strict also fails on blocked and network errors.

The same file is vendored in PaperManager as backend/services/citecheck.py (keep the two in step); stdlib only.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import difflib
import html
import html.parser
import json
import os
import re
import socket
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 citecheck/1.0"
CROSSREF_MAILTO = os.environ.get("CITECHECK_MAILTO", "")

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>{}\]]+)", re.I)
ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)
ARXIV_ID_RE = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$", re.I)
ARXIV_TEXT_RE = re.compile(r"arXiv[:\s]\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
PM_URL_RE = re.compile(r"papermanager\.niklas-abraham\.de/papers?/([0-9a-f\-]{36})", re.I)
PM_CMD = os.environ.get("CITECHECK_PM_CMD", "docker exec -i papermanager-backend-1 python -c")
ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/([a-z\-.]*/?\d{4}\.?\d{3,5}(?:v\d+)?)", re.I)

OK, DEAD, MISMATCH, BLOCKED, ERROR, MISSING, SKIPPED = "ok", "dead", "mismatch", "blocked", "error", "missing", "skipped"
FAILING = {DEAD, MISMATCH, MISSING}
TTL_OK = 30 * 86400
TTL_FAIL = 86400
TITLE_MIN = 0.6           # similarity below this is a mismatch


# ── items and results ─────────────────────────────────────────────────────────

@dataclass
class Item:
    kind: str                  # doi | arxiv | url | file | pm
    ident: str                 # the DOI, arXiv id, URL or path
    title: str = ""            # the title the citing document gives, if any
    context: str = ""          # text around a link (the reference-list entry), if no title
    where: str = ""            # where it was found (file:line, papers.json[3], bib key)


@dataclass
class Result:
    kind: str
    ident: str
    status: str
    detail: str = ""
    resolved_title: str = ""
    similarity: float | None = None
    where: list[str] = field(default_factory=list)


def normalise_doi(doi: str) -> str:
    doi = urllib.parse.unquote(doi.strip())
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    doi = doi.rstrip(".,;:)]}>").strip()
    if doi.startswith("10.1101/"):                    # bioRxiv / medRxiv page version, not part of the DOI
        doi = re.sub(r"v\d+$", "", doi)
    return doi


def normalise_arxiv(aid: str) -> str:
    aid = aid.strip()
    aid = re.sub(r"^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf|html)/)", "", aid, flags=re.I)
    aid = re.sub(r"\.pdf$", "", aid)
    return re.sub(r"v\d+$", "", aid)


def classify(kind: str, ident: str) -> tuple[str, str]:
    """Route arXiv DOIs and arxiv.org / doi.org URLs to the cheaper specific checkers."""
    if kind == "url":
        m = PM_URL_RE.search(ident)
        if m:
            return "pm", m.group(1).lower()
        m = ARXIV_URL_RE.search(ident)
        if m:
            return "arxiv", normalise_arxiv(m.group(1))
        m = re.match(r"https?://(?:dx\.)?doi\.org/(.+)", ident, re.I)
        if m:
            kind, ident = "doi", m.group(1)
    if kind == "doi":
        ident = normalise_doi(ident)
        m = ARXIV_DOI_RE.match(ident)
        if m:
            return "arxiv", normalise_arxiv(m.group(1))
        return "doi", ident
    if kind == "arxiv":
        return "arxiv", normalise_arxiv(ident)
    if kind == "pm":
        return "pm", ident.strip().lower()
    return kind, ident


# ── title comparison ──────────────────────────────────────────────────────────

def _tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", html.unescape(s or ""))
    s = re.sub(r"\\[a-zA-Z]+|[{}$\\]", " ", s)       # LaTeX commands and braces
    s = re.sub(r"<[^>]+>", " ", s)                    # markup in CSL titles (<i>, <sub>)
    return re.findall(r"[a-z0-9]+", s.lower())


_GENERIC = {"survey", "review", "introduction", "tutorial", "editorial", "correction", "erratum", "perspective",
            "commentary", "chapter", "part", "appendix", "supplementary", "abstract", "preface"}


def _name_prefix(title: str) -> list[str]:
    """The model or method name before a colon ("Boltz-2: Towards ..."), if it is short and specific."""
    head = html.unescape(title or "").split(":", 1)
    if len(head) < 2:
        return []
    toks = _tokens(head[0])
    if not 1 <= len(toks) <= 3 or any(t in _GENERIC for t in toks) or len("".join(toks)) < 4:
        return []
    return toks


def title_similarity(cited: str, resolved: str) -> float:
    """1.0 for the same title; robust to case, punctuation, markup, subtitles and truncation.

    A paper renamed between versions usually keeps its name ("ControlNet-XS: Designing ..." →
    "ControlNet-XS: Rethinking ..."): a specific name before a colon in one title that appears in
    the other counts as a match (0.8).
    """
    a, b = _tokens(cited), _tokens(resolved)
    if not a or not b:
        return 0.0
    for name, other in ((_name_prefix(cited), " ".join(b)), (_name_prefix(resolved), " ".join(a))):
        if name and re.search(r"\b" + re.escape(" ".join(name)) + r"\b", other):
            return 0.8
    ratio = difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    sa, sb = set(a), set(b)
    shorter = sa if len(sa) <= len(sb) else sb
    contain = len(sa & sb) / len(shorter)            # one title is the other plus a subtitle
    return round(max(ratio, contain if len(shorter) >= 4 else 0.0), 3)


def context_similarity(context: str, resolved: str) -> float:
    """Share of the resolved title's words found in the citing text (a reference-list entry)."""
    stop = {"a", "an", "the", "of", "and", "for", "in", "on", "with", "to", "by", "via", "from", "is", "at"}
    want = [t for t in _tokens(resolved) if t not in stop]
    have = set(_tokens(context))
    if not want or not have:
        return 0.0
    return round(sum(t in have for t in want) / len(want), 3)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def prefer_ipv4() -> None:
    """Sort IPv4 addresses first: Python's IPv6 connections hang on some hosts (the desk machine)."""
    orig = socket.getaddrinfo
    if getattr(orig, "_citecheck", False):
        return

    def gai(*a, **k):
        res = orig(*a, **k)
        return sorted(res, key=lambda r: r[0] != socket.AF_INET)
    gai._citecheck = True
    socket.getaddrinfo = gai


def _request(url: str, method: str = "GET", accept: str = "*/*", timeout: float = 12.0,
             max_bytes: int = 400_000) -> tuple[int, str, bytes, str]:
    """(status, final url, body, content type). Network failures raise OSError."""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": accept,
                                                              "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(max_bytes) if method != "HEAD" else b""
            return r.status, r.geturl(), body, r.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(max_bytes)
        except Exception:
            pass
        return e.code, url, body, e.headers.get("content-type", "") if e.headers else ""


def _csl_title(data: dict) -> str:
    t = data.get("title") or ""
    if isinstance(t, list):
        t = t[0] if t else ""
    sub = data.get("subtitle") or ""
    if isinstance(sub, list):
        sub = sub[0] if sub else ""
    return f"{t}: {sub}" if sub and sub.lower() not in t.lower() else t


def check_doi(doi: str, timeout: float) -> Result:
    url = "https://doi.org/" + urllib.parse.quote(doi, safe="/:;()._-")
    try:
        code, final, body, ctype = _request(url, accept="application/vnd.citationstyles.csl+json", timeout=timeout)
    except OSError as e:
        return Result("doi", doi, ERROR, f"network: {e}")
    if code == 200 and "json" in ctype:
        try:
            return Result("doi", doi, OK, "", _csl_title(json.loads(body.decode("utf-8", "replace"))))
        except ValueError:
            pass
    if code == 200:
        return Result("doi", doi, OK, f"resolves to {final[:80]}")
    # Not every registration agency serves CSL; the handle API knows whether the DOI exists at all.
    try:
        hcode, _, hbody, _ = _request("https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/"),
                                      accept="application/json", timeout=timeout)
        rc = json.loads(hbody.decode() or "{}").get("responseCode")
    except (OSError, ValueError) as e:
        return Result("doi", doi, ERROR, f"doi.org {code}, handle API failed: {e}")
    if rc == 1:
        return Result("doi", doi, OK, f"registered (doi.org content negotiation {code})")
    if rc in (100, 200) or hcode == 404:
        return Result("doi", doi, DEAD, "DOI not registered")
    return Result("doi", doi, ERROR, f"doi.org {code}, handle API {hcode}")


def check_arxiv_batch(ids: list[str], timeout: float) -> dict[str, Result]:
    """All ids in requests of 100 to the arXiv API; ids the feed does not return are dead."""
    out: dict[str, Result] = {}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        if i:
            time.sleep(3)                     # arXiv asks for one request every 3 s
        q = urllib.parse.urlencode({"id_list": ",".join(chunk), "max_results": len(chunk)})
        try:
            code, _, body, _ = _request(f"https://export.arxiv.org/api/query?{q}", timeout=max(timeout, 30),
                                        max_bytes=20_000_000)
            if code != 200:
                raise OSError(f"HTTP {code}")
            root = ET.fromstring(body)
        except (OSError, ET.ParseError) as e:
            # The API is down or one malformed id broke the batch: fall back to the abs pages, one by one.
            for aid in chunk:
                out[aid] = _arxiv_abs(aid, timeout, f"API failed ({e})")
            continue
        found: dict[str, str] = {}
        for entry in root.findall("a:entry", ns):
            eid = (entry.findtext("a:id", "", ns) or "").strip()
            title = re.sub(r"\s+", " ", entry.findtext("a:title", "", ns) or "").strip()
            m = re.search(r"arxiv\.org/abs/(.+?)(?:v\d+)?$", eid)
            if m and title and title.lower() != "error":
                found[m.group(1)] = title
        for aid in chunk:
            out[aid] = Result("arxiv", aid, OK, "", found[aid]) if aid in found else \
                Result("arxiv", aid, DEAD, "no such arXiv id")
    return out


def _arxiv_abs(aid: str, timeout: float, why: str) -> Result:
    try:
        code, _, body, _ = _request(f"https://arxiv.org/abs/{aid}", timeout=timeout)
    except OSError as e:
        return Result("arxiv", aid, ERROR, f"{why}; abs page: {e}")
    if code == 200:
        m = re.search(rb'<meta name="citation_title" content="([^"]+)"', body)
        return Result("arxiv", aid, OK, "", html.unescape(m.group(1).decode("utf-8", "replace")) if m else "")
    if code == 404:
        return Result("arxiv", aid, DEAD, "no such arXiv id")
    return Result("arxiv", aid, ERROR, f"{why}; abs page HTTP {code}")


def check_url(url: str, timeout: float) -> Result:
    try:
        code, final, _, _ = _request(url, method="HEAD", timeout=timeout)
        if code in (400, 403, 405, 406, 409, 429, 501) or code >= 500:   # many servers refuse HEAD
            code, final, body, ctype = _request(url, timeout=timeout, max_bytes=200_000)
        else:
            body, ctype = b"", ""
    except OSError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, socket.gaierror):
            return Result("url", url, DEAD, "host does not resolve")
        return Result("url", url, ERROR, f"network: {reason}")
    if code < 400:
        title = ""
        if body and "html" in ctype:
            m = re.search(rb"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            title = html.unescape(m.group(1).decode("utf-8", "replace")).strip()[:200] if m else ""
        return Result("url", url, OK, f"HTTP {code}" + (f" → {final[:80]}" if final.rstrip("/") != url.rstrip("/") else ""),
                      title)
    if code in (401, 403, 429, 451, 999):
        return Result("url", url, BLOCKED, f"HTTP {code} (bot protection or login)")
    if code in (404, 410):
        return Result("url", url, DEAD, f"HTTP {code}")
    return Result("url", url, ERROR, f"HTTP {code}")


_PM_SCRIPT = """
import sys, json
from db.connection import get_driver
ids = json.load(sys.stdin)
with get_driver().session() as s:
    rows = s.run('MATCH (p:Paper) WHERE p.id IN $ids RETURN p.id AS id, p.title AS title', ids=ids)
    print('CITECHECK' + json.dumps({r['id']: r['title'] or '' for r in rows}))
"""


def check_pm_batch(ids: list[str], timeout: float) -> dict[str, Result]:
    """PaperManager paper ids in one query inside the backend container."""
    import shlex
    import subprocess
    try:
        cp = subprocess.run(shlex.split(PM_CMD) + [_PM_SCRIPT], input=json.dumps(ids), capture_output=True,
                            text=True, timeout=max(30, timeout * 3))
        line = next(ln for ln in cp.stdout.splitlines() if ln.startswith("CITECHECK"))
        found = json.loads(line[len("CITECHECK"):])
    except (OSError, StopIteration, ValueError, subprocess.SubprocessError) as e:
        why = f"PaperManager not reachable ({type(e).__name__})"
        return {i: Result("pm", i, SKIPPED, why) for i in ids}
    return {i: Result("pm", i, OK, "", found[i]) if i in found else
            Result("pm", i, DEAD, "no paper with this id in PaperManager") for i in ids}


# ── cache ─────────────────────────────────────────────────────────────────────

class Cache:
    def __init__(self, path: Path | None):
        self.path, self.lock, self.data = path, threading.Lock(), {}
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text())
            except ValueError:
                self.data = {}

    def get(self, key: str) -> Result | None:
        e = self.data.get(key)
        if not e:
            return None
        ttl = TTL_OK if e["status"] in (OK, BLOCKED) else TTL_FAIL
        if time.time() - e.get("t", 0) > ttl:
            return None
        return Result(e["kind"], e["ident"], e["status"], e.get("detail", ""), e.get("resolved_title", ""))

    def put(self, key: str, r: Result) -> None:
        if r.status == ERROR:              # transient: never cached
            return
        with self.lock:
            self.data[key] = {"kind": r.kind, "ident": r.ident, "status": r.status, "detail": r.detail,
                              "resolved_title": r.resolved_title, "t": int(time.time())}

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False))
        tmp.replace(self.path)


# ── the check ─────────────────────────────────────────────────────────────────

def check_items(items: list[Item], *, workers: int = 16, timeout: float = 12.0, cache_path: Path | None = None,
                budget: float | None = None) -> list[Result]:
    """Check every item; one Result per item, in input order.

    Identical identifiers are fetched once. ``budget`` (seconds) bounds the whole run: what is not
    done by then comes back as "skipped".
    """
    cache = Cache(cache_path)
    norm = [classify(it.kind, it.ident) for it in items]
    unique = list(dict.fromkeys(norm))
    fetched: dict[tuple[str, str], Result] = {}
    todo = []
    for key in unique:
        hit = cache.get(f"{key[0]}:{key[1]}")
        if hit:
            fetched[key] = hit
        elif key[0] in ("doi", "arxiv", "url", "pm"):
            todo.append(key)
    t0 = time.time()

    arxiv_ids = [k[1] for k in todo if k[0] == "arxiv" and ARXIV_ID_RE.match(k[1])]
    for k in todo:
        if k[0] == "arxiv" and not ARXIV_ID_RE.match(k[1]):
            fetched[k] = Result("arxiv", k[1], DEAD, "malformed arXiv id")
    others = [k for k in todo if k[0] in ("doi", "url")]

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {}
        if arxiv_ids:
            futs[pool.submit(check_arxiv_batch, arxiv_ids, timeout)] = ("arxiv-batch", "")
        pm_ids = [k[1] for k in todo if k[0] == "pm"]
        if pm_ids:
            futs[pool.submit(check_pm_batch, pm_ids, timeout)] = ("pm-batch", "")
        for k in others:
            fn = check_doi if k[0] == "doi" else check_url
            futs[pool.submit(fn, k[1], timeout)] = k
        remaining = None if budget is None else max(0.0, budget - (time.time() - t0))
        try:
            for f in cf.as_completed(futs, timeout=remaining):
                k = futs[f]
                try:
                    res = f.result()
                except Exception as e:                  # a checker bug must not sink the run
                    res = Result(k[0], k[1], ERROR, f"checker error: {e}")
                if k[0] in ("arxiv-batch", "pm-batch"):
                    kind = k[0].split("-")[0]
                    for aid, r in res.items():
                        fetched[(kind, aid)] = r
                        if kind == "arxiv":           # library ids change (merges): always ask afresh
                            cache.put(f"arxiv:{aid}", r)
                else:
                    fetched[k] = res
                    cache.put(f"{k[0]}:{k[1]}", res)
        except cf.TimeoutError:
            for f in futs:
                f.cancel()
    cache.save()

    out = []
    for it, key in zip(items, norm):
        if key[0] == "file":
            r = Result("file", it.ident, OK if Path(it.ident).exists() else MISSING,
                       "" if Path(it.ident).exists() else "linked file does not exist")
        else:
            base = fetched.get(key) or Result(key[0], key[1], SKIPPED, "time budget exhausted")
            r = Result(base.kind, base.ident, base.status, base.detail, base.resolved_title)
            if r.status == OK and r.resolved_title and key[0] in ("doi", "arxiv", "pm"):
                if it.title:
                    r.similarity = title_similarity(it.title, r.resolved_title)
                elif it.context:
                    r.similarity = context_similarity(it.context, r.resolved_title)
                if r.similarity is not None and r.similarity < TITLE_MIN:
                    r.status = MISMATCH
                    hint = " (renamed version?)" if r.similarity >= 0.4 else ""
                    r.detail = f"cited “{(it.title or it.context)[:90]}” but the {key[0]} names another title{hint}"
        r.where = [it.where] if it.where else []
        out.append(r)
    return out


def merge_results(results: list[Result]) -> list[Result]:
    """One row per (kind, ident, status), with every place it occurs."""
    rows: dict[tuple, Result] = {}
    for r in results:
        k = (r.kind, r.ident, r.status)
        if k in rows:
            rows[k].where += [w for w in r.where if w not in rows[k].where]
        else:
            rows[k] = Result(**{**asdict(r), "where": list(r.where)})
    return list(rows.values())


# ── extracting citations from documents ───────────────────────────────────────

SKIP_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0")


def _skip_url(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    return p.scheme not in ("http", "https") or (p.hostname or "") in SKIP_HOSTS


class _LinkParser(html.parser.HTMLParser):
    """Collects hrefs (with the text of their reference-list entry, if they sit in one) and linked files."""
    BLOCKS = {"li", "p", "figcaption", "td", "dd", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, int, list]] = []   # (href, line, block text buffer)
        self.files: list[tuple[str, int]] = []
        self.stack: list[list] = []
        self.tags: list[str] = []
        self.lists: list[bool] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("ol", "ul"):
            self.lists.append(bool(re.search(r"ref|bib|biblio|citation", a.get("class") or "", re.I)))
        if tag in self.BLOCKS:
            self.stack.append([])
            # A reference entry: <li id="r-…"> or an item of a list classed as references.
            is_ref = tag == "li" and (bool(re.match(r"(?:r|ref|refs|lib|bib|cite)[-_:]", a.get("id") or "", re.I))
                                      or any(self.lists))
            self.tags.append("li*" if is_ref else tag)
        if tag == "a" and a.get("href"):
            # Only a reference-list entry (li) names the work it links; prose links get no title check.
            ctx = self.stack[-1] if self.stack and self.tags[-1] == "li*" else []
            self.links.append((a["href"], self.getpos()[0], ctx))
        for attr in ("src", "href", "data-src"):
            v = a.get(attr)
            if v and tag in ("img", "script", "link", "source", "video", "a", "figure", "iframe"):
                self.files.append((v, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag in ("ol", "ul") and self.lists:
            self.lists.pop()
        if tag in self.BLOCKS and self.stack:
            done = self.stack.pop()
            self.tags.pop()
            if self.stack:
                self.stack[-1].extend(done)

    def handle_data(self, data):
        if not self.skip and self.stack:
            self.stack[-1].append(data)


def items_from_html(path: Path, repo_root: Path | None = None) -> list[Item]:
    text = path.read_text(encoding="utf-8", errors="replace")
    p = _LinkParser()
    p.feed(text)
    items: list[Item] = []
    seen_files = set()
    for href, line, buf in p.links:
        href = html.unescape(href.strip())
        where = f"{path.name}:{line}"
        ctx_holder = buf                               # filled after parsing: the list is shared
        if href.startswith(("http://", "https://")):
            if _skip_url(href):
                continue
            items.append(Item("url", href, where=where, context=ctx_holder))   # type: ignore[arg-type]
        elif href.lower().startswith("doi:"):
            items.append(Item("doi", href[4:], where=where, context=ctx_holder))  # type: ignore[arg-type]
    for v, line in p.files:
        v = html.unescape(v.strip())
        if re.match(r"^(?:[a-z]+:|#|//|/|\{)", v, re.I) or not v:
            continue                                    # absolute, anchor, server path or template
        target = (path.parent / urllib.parse.unquote(v.split("#")[0].split("?")[0])).resolve()
        if repo_root and v.startswith("050_system/") and not target.exists():
            target = (repo_root / v).resolve()          # concept specs are repo-relative
        if target in seen_files:
            continue
        seen_files.add(target)
        items.append(Item("file", str(target), where=f"{path.name}:{line}"))
    # DOIs and arXiv ids written in the text but not linked
    linked = " ".join(i.ident for i in items)
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    for m in DOI_RE.finditer(re.sub(r"<[^>]+>", " ", plain)):
        d = normalise_doi(m.group(1))
        if d not in linked:
            items.append(Item("doi", d, where=f"{path.name}:{text.count(chr(10), 0, text.find(m.group(1))) + 1}"))
            linked += " " + d
    for it in items:                                   # join context buffers into text
        if isinstance(it.context, list):
            it.context = re.sub(r"\s+", " ", "".join(it.context)).strip()
    return items


def items_from_papers_json(path: Path) -> list[Item]:
    try:
        papers = json.loads(path.read_text())
    except ValueError as e:
        sys.exit(f"citecheck: {path} is not JSON: {e}")
    items = []
    for i, p in enumerate(papers if isinstance(papers, list) else []):
        title = p.get("title") or ""
        where = f"{path.name}[{i}]"
        if p.get("arxiv"):
            items.append(Item("arxiv", str(p["arxiv"]), title=title, where=where))
        if p.get("doi"):
            items.append(Item("doi", str(p["doi"]), title=title, where=where))
        if p.get("paperId"):
            items.append(Item("pm", str(p["paperId"]), title=title, where=where))
        elif p.get("url") and not _skip_url(p["url"]):
            items.append(Item("url", p["url"], title=title, where=where))
    return items


def items_from_bib(path: Path) -> list[Item]:
    text = path.read_text(encoding="utf-8", errors="replace")
    items = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*\{|\Z)", text, re.S):
        typ, key, body = m.group(1).lower(), m.group(2), m.group(3)
        if typ in ("string", "comment", "preamble"):
            continue
        fields = {}
        for f in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}|\"[^\"]*\"|\w+)", body):
            fields[f.group(1).lower()] = f.group(2).strip("{}\"").strip()
        title = re.sub(r"[{}]", "", fields.get("title", ""))
        where = f"{path.name}:{key}"
        if fields.get("doi"):
            items.append(Item("doi", fields["doi"], title=title, where=where))
        eprint = fields.get("eprint", "")
        if eprint and (fields.get("archiveprefix", "").lower() == "arxiv" or ARXIV_ID_RE.match(eprint)):
            items.append(Item("arxiv", eprint, title=title, where=where))
        if fields.get("url"):
            items.append(Item("url", fields["url"], title=title, where=where))
    return items


def items_from_text(path: Path) -> list[Item]:
    items = []
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        where = f"{path.name}:{n}"
        urls = re.findall(r"https?://[^\s)\]>\"'`]+", line)
        for u in urls:
            u = u.rstrip(".,;:")
            if not _skip_url(u):
                items.append(Item("url", u, where=where, context=line))
        for m in DOI_RE.finditer(line):
            if not any(m.group(1) in u for u in urls):
                items.append(Item("doi", normalise_doi(m.group(1)), where=where, context=line))
        for m in ARXIV_TEXT_RE.finditer(line):
            items.append(Item("arxiv", m.group(1), where=where, context=line))
    return items


def collect(target: Path, repo_root: Path | None) -> list[Item]:
    if target.is_dir():
        items = []
        for name in ("index.html", "papers.json"):
            if (target / name).exists():
                items += collect(target / name, repo_root)
        if not items and not any((target / n).exists() for n in ("index.html", "papers.json")):
            sys.exit(f"citecheck: {target} has neither index.html nor papers.json")
        return items
    suf = target.suffix.lower()
    if suf in (".html", ".htm"):
        return items_from_html(target, repo_root)
    if suf == ".json":
        return items_from_papers_json(target)
    if suf == ".bib":
        return items_from_bib(target)
    return items_from_text(target)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _repo_root(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return None


def report(rows: list[Result], verbose: bool) -> str:
    order = [DEAD, MISMATCH, MISSING, BLOCKED, ERROR, SKIPPED, OK]
    mark = {OK: "ok", DEAD: "DEAD", MISMATCH: "MISMATCH", MISSING: "MISSING", BLOCKED: "blocked",
            ERROR: "error", SKIPPED: "skipped"}
    lines = []
    for st in order:
        group = [r for r in rows if r.status == st]
        if not group or (st == OK and not verbose):
            continue
        lines.append(f"\n{mark[st]} ({len(group)})")
        for r in sorted(group, key=lambda r: (r.kind, r.ident)):
            where = ", ".join(r.where[:3]) + (f" +{len(r.where) - 3}" if len(r.where) > 3 else "")
            lines.append(f"  {r.kind:5} {r.ident}  [{where}]")
            if r.detail:
                lines.append(f"        {r.detail}")
            if r.resolved_title and st in (MISMATCH, OK) and r.kind != "url":
                sim = f" (similarity {r.similarity:.2f})" if r.similarity is not None else ""
                lines.append(f"        resolves to: {r.resolved_title[:110]}{sim}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("targets", nargs="+", help="report folder, .html, papers.json, .bib, .md or .txt")
    ap.add_argument("--json", action="store_true", help="print the results as JSON")
    ap.add_argument("--verbose", "-v", action="store_true", help="also list the links that are fine")
    ap.add_argument("--strict", action="store_true", help="blocked, network errors and skipped fail too")
    ap.add_argument("--no-files", action="store_true", help="do not check relative file links")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=12.0, help="per request, seconds")
    ap.add_argument("--budget", type=float, default=180.0, help="whole run, seconds (default 180)")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args(argv)

    prefer_ipv4()
    items: list[Item] = []
    root = None
    for t in a.targets:
        path = Path(os.path.expanduser(t)).resolve()
        if not path.exists():
            sys.exit(f"citecheck: no such file: {t}")
        root = root or _repo_root(path)
        items += collect(path, _repo_root(path))
    if a.no_files:
        items = [i for i in items if i.kind != "file"]
    cache_path = None if a.no_cache else (root / "050_system/.cache/citecheck.json" if root and (root / "050_system").exists()
                                          else Path.home() / ".cache/citecheck.json")
    t0 = time.time()
    rows = merge_results(check_items(items, workers=a.workers, timeout=a.timeout, cache_path=cache_path,
                                     budget=a.budget))
    fail = FAILING | ({BLOCKED, ERROR, SKIPPED} if a.strict else set())
    bad = [r for r in rows if r.status in fail]
    if a.json:
        print(json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=1))
    else:
        counts = {s: sum(r.status == s for r in rows) for s in (OK, DEAD, MISMATCH, MISSING, BLOCKED, ERROR, SKIPPED)}
        summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        print(f"citecheck: {len(rows)} links checked in {time.time() - t0:.1f}s: {summary or 'nothing to check'}")
        out = report(rows, a.verbose)
        if out:
            print(out)
        print("\nFAIL" if bad else "\nPASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
