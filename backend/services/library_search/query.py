"""Query parsing, Lucene query building and match marking for the library search.

Pure functions, no Neo4j: everything here is unit-tested in tests/test_library_search.py.

A query is split into *units*, the things a hit has to contain: single terms (lower case,
accents folded, English stop words dropped) and quoted phrases. Each term becomes a Lucene clause that
matches the exact word (boosted), any word it is a prefix of (``diffus*``, terms of 3+
characters) and, for alphabetic terms of 5+ characters, any word one edit away
(``scroe~1`` finds "score"). The same rules are mirrored by :class:`UnitMatcher` in Python,
which decides which units a hit covers and where to put the ``<mark>`` spans of a snippet.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# Lucene's reserved characters. Query terms come out of TOKEN and so never contain any of
# them; escaping is applied anyway so no user input reaches the parser unescaped.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
TOKEN = re.compile(r"[^\W_]+")
_WORD = r"[^\W_]"
# Lucene's classic English stop set. The indexes use the standard-no-stop-words analyzer,
# so stop words are indexed and still count inside phrases; they are just not required.
STOPWORDS = frozenset(
    "a an and are as at be but by for if in into is it no not of on or such that the "
    "their then there these they this to was will with".split()
)
MAX_UNITS = 12
_DOI = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+?)[.,;]?$", re.I)
_ARXIV = re.compile(
    r"^(?:arxiv:\s*|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", re.I
)
_QUOTED = re.compile(r'"([^"]*)"?')
_WORD_NUMBER = re.compile(r"^([a-z]{3,})(\d{1,3})$")


def escape_lucene(text: str) -> str:
    """Backslash-escape every Lucene special character."""
    return _LUCENE_SPECIAL.sub(r"\\\1", text)


# Letters NFKD does not decompose but Lucene's ASCIIFoldingFilter folds.
_SPECIAL_FOLD = str.maketrans({"ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ß": "ss",
                               "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ı": "i", "þ": "th", "Þ": "th"})


_COMBINING = re.compile("[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]")


@lru_cache(maxsize=20000)
def fold(text: str) -> str:
    """Lower case without accents, the way the standard-folding analyzer indexes text:
    "Kynkäänniemi" -> "kynkaanniemi", "AlphaFold" -> "alphafold"."""
    if text.isascii():
        return text.lower()
    return _COMBINING.sub("", unicodedata.normalize("NFKD", text.translate(_SPECIAL_FOLD))).lower()


@lru_cache(maxsize=4096)
def fold_map(text: str) -> tuple[str, tuple[int, ...] | None]:
    """``fold(text)`` plus, for non-ASCII text, the index in ``text`` of every folded
    character (folding can drop or add characters), so matches map back to the original."""
    if text.isascii():
        return text.lower(), None
    out, idx = [], []
    for i, ch in enumerate(text):
        f = ch.lower() if ch.isascii() else fold(ch)
        out.append(f)
        idx.extend([i] * len(f))
    return "".join(out), tuple(idx)


def tokenize(text: str) -> list[str]:
    """Folded word tokens, split at anything that is not a letter or digit."""
    return TOKEN.findall(fold(text or ""))


@dataclass(frozen=True)
class Unit:
    """One thing the query asks for: a term, or a phrase of several tokens."""

    tokens: tuple[str, ...]
    prefix: bool = False
    fuzzy: bool = False
    quoted: bool = False
    # Another spelling that also counts: a word+number term ("alphafold3", "boltz2") also
    # matches the spaced phrase ("AlphaFold 3"); a hyphenated compound typed as a phrase
    # ("over-conditioning", "co-folding") also matches the joined word ("cofolding").
    alt: tuple[str, ...] = ()

    @property
    def is_phrase(self) -> bool:
        return len(self.tokens) > 1

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


@dataclass
class ParsedQuery:
    raw: str
    units: list[Unit]
    phrase: tuple[str, ...]          # the unquoted query in order, for the phrase boost
    identifier: dict | None = None   # {"doi": ...} or {"arxiv": ...}

    @property
    def empty(self) -> bool:
        return not self.units and not self.identifier


def detect_identifier(raw: str) -> dict | None:
    """A DOI (bare, ``doi:`` or doi.org URL) or an arXiv id (``2210.02747``, ``arXiv:...``,
    arxiv.org URL) typed as the whole query."""
    s = raw.strip()
    m = _DOI.match(s)
    if m:
        return {"doi": m.group(1).lower()}
    m = _ARXIV.match(s)
    if m:
        return {"arxiv": m.group(1)}
    return None


def _term_unit(tok: str, explicit_prefix: bool = False, quoted: bool = False) -> Unit:
    if quoted:
        return Unit((tok,), quoted=True)
    prefix = explicit_prefix or (len(tok) >= 3 and not tok.isdigit())
    fuzzy = not explicit_prefix and len(tok) >= 5 and tok.isalpha()
    m = _WORD_NUMBER.match(tok)
    return Unit((tok,), prefix=prefix, fuzzy=fuzzy, alt=(m.group(1), m.group(2)) if m else ())


def parse_query(q: str | None) -> ParsedQuery:
    raw = (q or "").strip()[:500]
    identifier = detect_identifier(raw) if raw else None
    units: list[Unit] = []
    seen: set[tuple[str, ...]] = set()

    def add(u: Unit) -> None:
        if u.tokens and u.tokens not in seen and len(units) < MAX_UNITS:
            seen.add(u.tokens)
            units.append(u)

    for m in _QUOTED.finditer(raw):
        toks = tokenize(m.group(1))
        if len(toks) == 1:
            add(_term_unit(toks[0], quoted=True))
        elif toks:
            add(Unit(tuple(toks[:16]), quoted=True))
    rest = _QUOTED.sub(" ", raw)
    ordered: list[str] = []
    found: list[tuple[Unit, bool]] = []  # (unit, is a stop word)
    for word in rest.split():
        toks = tokenize(word)
        ordered.extend(toks)
        if len(toks) == 1:
            found.append((_term_unit(toks[0], explicit_prefix=word.endswith("*")), toks[0] in STOPWORDS))
        elif toks:
            # One word written with punctuation inside ("over-conditioning", "Boltz-2",
            # "SE(3)") means the parts next to each other, not each part anywhere.
            joined = "".join(toks)
            alt = (joined,) if "-" in word and len(joined) <= 40 else ()
            found.append((Unit(tuple(toks[:16]), alt=alt), False))
    content = [u for u, stop in found if not stop]
    for u in (content or [u for u, _ in found]):
        add(u)
    phrase = tuple(ordered) if 2 <= len(ordered) <= 8 else ()
    return ParsedQuery(raw=raw, units=units, phrase=phrase, identifier=identifier)


# ── Lucene ────────────────────────────────────────────────────────────────────

def _boost(b: float) -> str:
    return "" if b == 1 else f"^{b:g}"


def unit_clause(u: Unit) -> str:
    if u.is_phrase:
        phrase = '"' + escape_lucene(u.text) + '"'
        return f"({phrase} OR {escape_lucene(u.alt[0])})" if u.alt else phrase
    t = escape_lucene(u.tokens[0])
    alts = [t + "^2"] if (u.prefix or u.fuzzy) else [t]
    if u.prefix:
        alts.append(t + "*")
    if u.fuzzy:
        alts.append(t + "~1")
    if u.alt:
        alts.append('"' + escape_lucene(" ".join(u.alt)) + '"')
    return alts[0] if len(alts) == 1 else "(" + " OR ".join(alts) + ")"


def _phrase_clause(pq: ParsedQuery, boost: float) -> str | None:
    if not pq.phrase:
        return None
    return '"' + escape_lucene(" ".join(pq.phrase)) + '"' + _boost(boost)


def lucene_any(pq: ParsedQuery, phrase_boost: float = 3) -> str:
    """Any unit may match (OR); the whole query as a phrase is boosted."""
    parts = [unit_clause(u) for u in pq.units]
    ph = _phrase_clause(pq, phrase_boost)
    if ph:
        parts.append(ph)
    return " OR ".join(parts)


def lucene_all(pq: ParsedQuery, phrase_boost: float = 2) -> str:
    """Every unit must match (+); the phrase only adds to the score."""
    parts = ["+" + unit_clause(u) for u in pq.units]
    ph = _phrase_clause(pq, phrase_boost)
    if ph:
        parts.append(ph)
    return " ".join(parts)


def lucene_prefix_all(tokens: list[str]) -> str:
    """Type-ahead: every token required as a prefix (``tero kar`` -> ``+tero* +kar*``).
    Stop words are not indexed, so finished stop words are dropped and a last token that
    is a stop word ("generative models for") is only optional: it may still grow into
    "format"."""
    if not tokens:
        return ""
    *head, last = tokens
    parts = [f"+{escape_lucene(t)}*" for t in head if t not in STOPWORDS]
    if last in STOPWORDS:
        parts.append(f"{escape_lucene(last)}*")
    else:
        parts.append(f"+{escape_lucene(last)}*")
    return " ".join(parts)


def on_fields(body: str, fields: dict[str, float]) -> str:
    """Scope a query body to index fields with per-field boosts: ``title:(...)^4 OR ...``."""
    return " OR ".join(f"{f}:({body}){_boost(b)}" for f, b in fields.items())


# ── Matching in Python (coverage, marks, snippets) ────────────────────────────

def _fuzzy_alternatives(t: str) -> list[str]:
    """Regex alternatives for every word within one edit (insert, delete, substitute,
    swap neighbours) of ``t``, as Lucene's ``t~1`` with transpositions."""
    e = re.escape
    alts = set()
    n = len(t)
    for i in range(n):
        alts.add(e(t[:i]) + e(t[i + 1:]))                    # deletion
        alts.add(e(t[:i]) + _WORD + e(t[i + 1:]))           # substitution
        if i < n - 1:
            alts.add(e(t[:i] + t[i + 1] + t[i] + t[i + 2:]))  # transposition
    for i in range(n + 1):
        alts.add(e(t[:i]) + _WORD + e(t[i:]))               # insertion
    return sorted(alts, key=len, reverse=True)


class UnitMatcher:
    """Finds a unit in text with the same rules as its Lucene clause."""

    def __init__(self, unit: Unit):
        self.unit = unit
        if unit.is_phrase:
            core = r"[\W_]+".join(re.escape(t) for t in unit.tokens)
            if unit.alt:
                core = f"(?:{core}|{re.escape(unit.alt[0])})"
            strict = rf"(?<!{_WORD}){core}(?!{_WORD})"
            loose = strict
        else:
            t = unit.tokens[0]
            core = re.escape(t) + (f"{_WORD}*" if unit.prefix else "")
            strict = rf"(?<!{_WORD}){core}(?!{_WORD})"
            loose = strict
            if unit.alt:
                core = f"(?:{core}|" + r"[\W_]+".join(re.escape(x) for x in unit.alt) + ")"
                strict = rf"(?<!{_WORD}){core}(?!{_WORD})"
                loose = strict
            if unit.fuzzy:
                alts = "|".join(_fuzzy_alternatives(t))
                loose = rf"(?<!{_WORD})(?:{core}|{alts})(?!{_WORD})"
        # Patterns are folded tokens; they run on fold(text), so case and accents never matter.
        self.strict = re.compile(strict)
        self.loose = re.compile(loose)

    def _rx(self, text: str, fuzzy: bool | None):
        if fuzzy is None:
            fuzzy = len(text) <= 20000
        return self.loose if fuzzy else self.strict

    def found(self, text: str, fuzzy: bool | None = None) -> bool:
        return bool(text) and self._rx(text, fuzzy).search(fold(text)) is not None

    def spans(self, text: str, limit: int = 200, fuzzy: bool | None = None) -> list[tuple[int, int]]:
        """Match ranges in the original ``text`` (offsets in code points)."""
        if not text:
            return []
        folded, idx = fold_map(text)
        out = []
        for m in self._rx(text, fuzzy).finditer(folded):
            s, e = m.start(), m.end()
            out.append((s, e) if idx is None else (idx[s], idx[e - 1] + 1))
            if len(out) >= limit:
                break
        return out


def matchers_for(pq: ParsedQuery) -> list[UnitMatcher]:
    return [UnitMatcher(u) for u in pq.units]


class _Vocabulary:
    """Every distinct word of every text that ``token_set`` has seen, in first-seen order,
    and per term unit the words that satisfy it (``accepted``). Texts recur across queries
    (the same abstracts), so a unit's word list is computed once over this vocabulary and
    afterwards only extended with words that appeared since. A word the vocabulary has
    never seen cannot occur in any text a Coverage looks at, so a larger vocabulary than
    the candidates' own never changes which units a text covers."""

    MAX_WORDS = 2_000_000

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.words: list[str] = []
        self.seen: set[str] = set()
        self.units: dict[tuple, list] = {}   # (term, prefix, fuzzy) -> [accepted set, words checked]

    def reset_if_huge(self) -> None:
        """Start over (and forget the cached token sets, whose words would be missing)."""
        with self.lock:
            if len(self.words) <= self.MAX_WORDS:
                return
            self.words, self.seen, self.units = [], set(), {}
        token_set.cache_clear()

    def add(self, toks: frozenset) -> None:
        with self.lock:
            new = toks - self.seen
            if new:
                self.seen |= new
                self.words.extend(new)

    def accepted(self, t: str, prefix: bool, fuzzy: bool) -> frozenset:
        key = (t, prefix, fuzzy)
        with self.lock:
            ent = self.units.get(key)
            if ent is None:
                if len(self.units) > 4096:
                    self.units.clear()
                ent = self.units[key] = [{t}, 0]
            acc, done = ent
            if done < len(self.words):
                tail = self.words[done:]
                if prefix:
                    acc.update(w for w in tail if w.startswith(t))
                if fuzzy:
                    n = len(t)
                    near = (w for w in tail if n - 1 <= len(w) <= n + 1)
                    if n >= 4:
                        # One edit leaves the first or the last letter in place, or (same
                        # length) the second: a cheap necessary test before the real one.
                        first, last, second = t[0], t[-1], t[1]
                        near = (w for w in near
                                if w[0] == first or w[-1] == last or (len(w) == n and w[1] == second))
                    acc.update(w for w in near if within_one_edit(w, t))
                ent[1] = len(self.words)
            return frozenset(acc)


_VOCAB = _Vocabulary()


@lru_cache(maxsize=50000)
def token_set(text: str) -> frozenset[str]:
    """Distinct folded tokens of a text (cached: the same abstracts recur across queries).
    The tokens also join the shared vocabulary that ``Coverage`` expands terms over."""
    ts = frozenset(TOKEN.findall(fold(text)))
    _VOCAB.add(ts)
    return ts


def within_one_edit(a: str, b: str) -> bool:
    """Optimal-string-alignment distance <= 1: one insertion, deletion, substitution or
    swap of neighbouring characters (Lucene's ``~1`` with transpositions)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = []
        for i in range(la):
            if a[i] != b[i]:
                diff.append(i)
                if len(diff) > 2:
                    return False
        if len(diff) == 1:
            return True
        i, j = diff
        return j == i + 1 and a[i] == b[j] and a[j] == b[i]
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


class Coverage:
    """Decides which units a set of texts contains, for many candidates of one query.

    Built once per query: for every term unit, the word forms that satisfy it (the term,
    words it prefixes, words one edit away), expanded over the shared vocabulary of all
    texts seen so far (cached per unit, see ``_Vocabulary``).
    A text then covers the term if its token set meets that set, a C-level set operation,
    so checking a thousand candidates costs a few milliseconds. Phrases use the regex."""

    def __init__(self, units: list[Unit], texts):
        self.units = units
        _VOCAB.reset_if_huge()
        for t in texts:   # registers every word of every text in the shared vocabulary
            if t:
                token_set(t)
        self.accept: list[frozenset[str] | None] = []
        self.phrase: list[re.Pattern | None] = []
        # A phrase can only match in a text that has all its words (or its joined spelling)
        # as whole words, so the regex runs only on texts whose token set passes this test.
        self.need: list[list[frozenset[str]] | None] = []
        for u in units:
            if u.is_phrase:
                self.accept.append(None)
                self.phrase.append(UnitMatcher(u).strict)
                self.need.append([frozenset(u.tokens)] + ([frozenset(u.alt[:1])] if u.alt else []))
                continue
            self.accept.append(_VOCAB.accepted(u.tokens[0], u.prefix, u.fuzzy))
            self.phrase.append(UnitMatcher(u).strict if u.alt else None)
            self.need.append(None)

    def covered(self, texts) -> set[int]:
        texts = [t for t in texts if t]
        toks = [token_set(t) for t in texts]
        hit: set[int] = set()
        for i, acc in enumerate(self.accept):
            if acc is not None and any(not ts.isdisjoint(acc) for ts in toks):
                hit.add(i)
            elif self.phrase[i] is not None:
                need = self.need[i]
                if any((need is None or any(n <= ts for n in need)) and self.phrase[i].search(fold(t))
                       for t, ts in zip(texts, toks)):
                    hit.add(i)
        return hit


def covered(texts, matchers: list[UnitMatcher]) -> set[int]:
    """Indexes of the units found in at least one of ``texts`` (regex; for a few texts)."""
    texts = [t for t in texts if t]
    hit: set[int] = set()
    for i, m in enumerate(matchers):
        if any(m.found(t) for t in texts):
            hit.add(i)
    return hit


def _merge(spans: list[tuple[int, int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def mark(text: str, matchers: list[UnitMatcher]) -> list[list[int]]:
    """``[[start, end], ...]`` character ranges of every unit occurrence in ``text``."""
    spans: list[tuple[int, int]] = []
    for m in matchers:
        spans.extend(m.spans(text, limit=50))
    return _merge(spans)


_MD = re.compile(r"(^|\s)#{1,6}\s+|\*\*|__|`")
_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    """Collapse whitespace and drop markdown heading/bold/code markers."""
    return _WS.sub(" ", _MD.sub(r"\1", text or "")).strip()


def needles(pq: ParsedQuery) -> list[str]:
    """Lower-case strings to look for in a long text, most specific first: the whole
    query, quoted phrases, then terms by length."""
    out = []
    if pq.phrase:
        out.append(" ".join(pq.phrase))
    out += [u.text for u in pq.units if u.is_phrase]
    out += sorted((u.text for u in pq.units if not u.is_phrase), key=len, reverse=True)
    return list(dict.fromkeys(out))


def snippet(text: str, matchers: list[UnitMatcher], width: int = 240, *,
            cut_before: bool = False, cut_after: bool = False) -> dict | None:
    """The window of ``text`` (about ``width`` characters) holding the most distinct units,
    as ``{"text": ..., "marks": [[s, e], ...]}`` with offsets into the returned text;
    ``None`` when no unit occurs. Long texts are searched without the fuzzy variants.
    ``cut_before`` / ``cut_after`` mark ``text`` as a cut from a longer text (ellipses)."""
    if not text or not matchers:
        return None
    occ: list[tuple[int, int]] = []  # (position, unit index)
    for i, m in enumerate(matchers):
        occ.extend((s, i) for s, _ in m.spans(text, limit=200))
    if not occ:
        return None
    occ.sort()
    lead = width // 3
    best = None
    for pos, _ in occ:
        a, b = max(0, pos - lead), pos - lead + width
        distinct = {i for p, i in occ if a <= p < b}
        key = (len(distinct), -pos)
        if best is None or key > best[0]:
            best = (key, a, max(b, a + width))
    _, a, b = best
    b = min(len(text), b)
    # Snap to word boundaries so the snippet does not start or end mid-word.
    if a > 0:
        sp = text.find(" ", a, min(len(text), a + 30))
        a = sp + 1 if sp != -1 else a
    if b < len(text):
        sp = text.rfind(" ", max(a, b - 30), b)
        b = sp if sp != -1 else b
    body = clean(text[a:b])
    pre = "…" if a > 0 or cut_before else ""
    post = "…" if b < len(text) or cut_after else ""
    out = pre + body + post
    return {"text": out, "marks": mark(out, matchers)}
