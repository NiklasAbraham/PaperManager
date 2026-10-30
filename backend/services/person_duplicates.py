"""Find and merge duplicate Person nodes (People page and scripts/merge_people.py).

Two names are one person when they agree after
  - stripping accents, punctuation and case ("Alán Aspuru-Guzik" = "Al'an Aspuru-Guzik"),
  - additionally dropping middle initials, when both first names are spelled out
    ("Nele P. Quast" = "Nele Quast"), or
  - an initial-only name matches exactly one spelled-out name with the same surname, first
    initial and compatible middle initials ("C. P. Robert" = "Christian P. Robert"; with two
    candidates, "C. Robert" is left alone).
The keeper is the node with an S2 id / tracking / most relationships; it adopts the others'
missing properties, every relationship (MERGE, so nothing doubles) and their names as aliases.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from neo4j import Driver

_TYPE_RE = re.compile(r"^[A-Z_]+$")

REASONS = {
    "exact": "same name",
    "loose": "same name without middle initials",
    "initials": "initials match the only full name",
}

PEOPLE_QUERY = """
MATCH (p:Person)
RETURN p.id AS id, p.name AS name, p.affiliation AS affiliation, properties(p).s2_author_id AS s2_author_id,
       p.tracked AS tracked, COUNT { (p)--() } AS degree,
       COUNT { (:Paper)-[:AUTHORED_BY|INVOLVES]->(p) } AS paper_count
"""


def _ascii(name: str) -> str:
    t = unicodedata.normalize("NFKD", name or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[’'`´]", "", t)
    return re.sub(r"[^a-z]+", " ", t).strip()


def exact_key(name: str) -> str:
    return _ascii(name).replace(" ", "")


def loose_key(name: str) -> str | None:
    """First + last name without middle initials; None if the first name is only an initial."""
    words = _ascii(name).split()
    if len(words) < 2 or len(words[0]) < 2:
        return None
    middle = words[1:-1]
    if any(len(w) > 1 for w in middle):  # a spelled-out middle name: keep it in the key
        return None
    return f"{words[0]} {words[-1]}"


def keep_score(p: dict) -> tuple:
    clean = not re.search(r"[´’`]", p["name"] or "")  # "Jim´enez" is a PDF-extraction artefact
    return (bool(p.get("s2_author_id")), bool(p.get("tracked")), clean, p["degree"], len(p["name"] or ""))


def _initial_pairs(people: list[dict]) -> list[tuple[dict, dict]]:
    """(full-name person, initial-only person) pairs where the full name is the only candidate."""
    full: dict[tuple[str, str], list[tuple[dict, list[str]]]] = defaultdict(list)
    for p in people:
        words = _ascii(p["name"]).split()
        if len(words) >= 2 and len(words[0]) > 1:
            full[(words[-1], words[0][0])].append((p, words))
    pairs = []
    for p in people:
        words = _ascii(p["name"]).split()
        if len(words) < 2 or len(words[0]) > 1:
            continue
        cands = full.get((words[-1], words[0]), [])
        # Middle initials must not contradict ("C. P. Robert" vs "Christian X. Robert").
        if len(words) > 2:
            cands = [(c, w) for c, w in cands if len(w) < 3 or w[1][0] == words[1][0]]
        # Several spelled-out names may be one person themselves (exact/loose rules).
        if len({loose_key(c["name"]) or exact_key(c["name"]) for c, _ in cands}) == 1:
            pairs.append((cands[0][0], p))
    return pairs


def groups(people: list[dict], initials: bool = True) -> list[dict]:
    """Duplicate groups as {"people": [keeper, *others], "reasons": [...]}, largest first."""
    parent = {p["id"]: p["id"] for p in people}
    why: dict[str, set[str]] = defaultdict(set)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, reason):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            why[ra] |= why.pop(rb, set())
        why[ra].add(reason)

    for reason, keyf in (("exact", exact_key), ("loose", loose_key)):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for p in people:
            k = keyf(p["name"])
            if k:
                buckets[k].append(p)
        for ps in buckets.values():
            for q in ps[1:]:
                union(ps[0]["id"], q["id"], reason)
    if initials:
        for keep, other in _initial_pairs(people):
            union(keep["id"], other["id"], "initials")
    out: dict[str, list[dict]] = defaultdict(list)
    for p in people:
        out[find(p["id"])].append(p)
    result = [
        {"people": sorted(g, key=keep_score, reverse=True), "reasons": [REASONS[r] for r in REASONS if r in why[root]]}
        for root, g in out.items() if len(g) > 1
    ]
    return sorted(result, key=lambda g: (-len(g["people"]), _ascii(g["people"][0]["name"])))


def find_duplicate_groups(driver: Driver, initials: bool = True) -> list[dict]:
    with driver.session() as s:
        people = s.run(PEOPLE_QUERY).data()
    return groups(people, initials=initials)


def merge(tx, keep_id: str, remove_id: str) -> int:
    rec = tx.run("MATCH (k:Person {id: $k}), (r:Person {id: $r}) RETURN properties(k) AS k, properties(r) AS r",
                 k=keep_id, r=remove_id).single()
    if rec is None:
        raise LookupError(f"person not found: {keep_id} or {remove_id}")
    keep, rem = dict(rec["k"]), dict(rec["r"])
    fill = {k: v for k, v in rem.items() if k not in ("id", "name", "aliases") and v not in (None, "", []) and keep.get(k) in (None, "", [])}
    aliases = [a for a in [*(keep.get("aliases") or []), rem.get("name"), *(rem.get("aliases") or [])]
               if a and a != keep.get("name")]
    fill["aliases"] = list(dict.fromkeys(aliases))
    tx.run("MATCH (k:Person {id: $k}) SET k += $p", k=keep_id, p=fill)
    moved = 0
    for direction in ("OUT", "IN"):
        any_pat = "(r:Person {id: $r})-[rel]->(x)" if direction == "OUT" else "(x)-[rel]->(r:Person {id: $r})"
        for t in [x["t"] for x in tx.run(f"MATCH {any_pat} RETURN DISTINCT type(rel) AS t", r=remove_id).data()]:
            if not _TYPE_RE.match(t):
                raise ValueError(f"unexpected relationship type {t!r}")
            pat = any_pat.replace("[rel]", f"[rel:{t}]")
            new = f"(k)-[nr:{t}]->(x)" if direction == "OUT" else f"(x)-[nr:{t}]->(k)"
            moved += tx.run(f"""
                MATCH {pat}, (k:Person {{id: $k}})
                WHERE x.id IS NULL OR (x.id <> $k AND x.id <> $r)
                MERGE {new} ON CREATE SET nr = properties(rel)
                DELETE rel RETURN count(rel) AS n
            """, r=remove_id, k=keep_id).single()["n"]
    tx.run("MATCH (r:Person {id: $r}) DETACH DELETE r", r=remove_id)
    return moved


def merge_people(driver: Driver, keep_id: str, remove_ids: list[str]) -> dict:
    """Merge every ``remove_ids`` person into ``keep_id`` in one transaction."""
    with driver.session() as s:
        moved = s.execute_write(lambda tx: sum(merge(tx, keep_id, r) for r in remove_ids))
    return {"kept_id": keep_id, "merged": len(remove_ids), "relationships_moved": moved}
