# T15 — Search

**Phase:** 4 — Search
**Depends on:** T04, T05, T09
**Touches:** `backend/routers/search.py`, `backend/db/queries/` (new search functions)

## Goal
Full-text search across paper titles, abstracts, summaries, and note content.
Also filter by tag, topic, project, person.

## Search endpoint

```
GET /search?q=attention+mechanism&tag=arxiv&topic=NLP&project_id=...&person_id=...
```

All parameters optional. If only filters provided (no `q`), returns all matching papers.

## Cypher — full-text search

Uses the full-text indexes created in T04:

```cypher
CALL db.index.fulltext.queryNodes("paper_search", $query)
YIELD node, score
RETURN node, score
ORDER BY score DESC
LIMIT 20
```

For note search:
```cypher
CALL db.index.fulltext.queryNodes("note_search", $query)
YIELD node, score
MATCH (p:Paper)-[:HAS_NOTE]->(node)
RETURN p, score
```

Merge and deduplicate results from both indexes.

## Cypher — filter by tag/topic/project/person

```cypher
MATCH (p:Paper)
WHERE ($tag IS NULL OR (p)-[:TAGGED]->(:Tag {name: $tag}))
AND   ($topic IS NULL OR (p)-[:ABOUT]->(:Topic {name: $topic}))
AND   ($project_id IS NULL OR (p)-[:IN_PROJECT]->(:Project {id: $project_id}))
AND   ($person_id IS NULL OR (p)-[:AUTHORED_BY|INVOLVES]->(:Person {id: $person_id}))
RETURN p
```

## Combined search
When both `q` and filters are provided: run full-text search first, then filter the results.

## Response

```json
{
  "results": [
    {
      "id": "...",
      "title": "...",
      "year": 2023,
      "summary": "...",
      "score": 1.42,
      "matched_in": "title"   // "title" | "summary" | "note"
    }
  ],
  "total": 5
}
```

## Done when
- [ ] `GET /search?q=transformers` returns relevant papers
- [ ] `GET /search?tag=arxiv` returns all papers with that tag
- [ ] Combined: `GET /search?q=attention&topic=NLP` narrows results
- [ ] Note content is searchable
- [ ] Empty query with no filters returns all papers (paginated)

## Tests
`backend/tests/test_search.py`
- Create 3 papers with different titles/summaries
- Search by keyword in title → correct paper returned
- Search by keyword in summary → correct paper returned
- Filter by tag → only tagged papers
- Combined q + tag → intersection
- No results → empty list, not error
