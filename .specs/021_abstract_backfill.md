# Abstract backfill — developer context

Papers imported by DOI or title list often have no abstract, which makes them embed poorly for
semantic search (`.specs/012_search.md`, `.specs/019_vector_store.md`: the embedded text is title plus
abstract, falling back to the summary). The backfill finds papers that have a DOI but an empty
abstract and fills them from open metadata services.

Code: `backend/services/abstract_backfill.py`, `backend/scripts/backfill_abstracts.py`, route
`POST /backfill/abstracts` in `backend/routers/backfill.py`.
Tests: `backend/tests/test_abstract_backfill_*.py` (fake graph driver and `httpx.MockTransport` in
`backend/tests/abstract_backfill_helpers.py`; no network). User guide: `docs/user-guide/abstract-backfill.md`.

## Selection

Parameterised Cypher (`CANDIDATES_QUERY`): `Paper` with `abstract` null or whitespace and a non-empty
`doi`; unless `include_stubs`, not tagged `from-references`; ordered by `id`. The DOI is normalised in
Python (`doi_for_lookup`: prefixes stripped, lower case, arXiv ids become `10.48550/arxiv.<id>`); a
value that is not a DOI counts as `invalid_doi`. Papers without a DOI are counted (`no_doi`) and skipped,
unless `title_search` is on. `limit` cuts the id-ordered list. The selection does not apply the
per-user visibility clause: it is an admin and CLI tool and sees the whole library.

## Sources

Tried in this order; each is asked only for DOIs that still have no accepted abstract. Sequential, one
request in flight, minimum interval per host, retries with exponential backoff, `Retry-After` honoured
on 429 and 503 (a value over 120 s gives the source up for the run), 25 s timeout, TLS settings of
`metadata_lookup._ssl`.

| Source | Request | Batch | Interval |
|---|---|---|---|
| OpenAlex | `GET /works?filter=doi:<url>\|<url>...&per-page=50&select=...`; text from `abstract_inverted_index` | 50 | 0.2 s |
| Semantic Scholar | `POST /graph/v1/paper/batch?fields=title,abstract,externalIds`, ids `DOI:<doi>`; key from `semantic_scholar_api_key` | 100 (500 with a key) | 3 s (1.1 s with a key) |
| arXiv | `GET /api/query?id_list=...`, only `10.48550/arXiv.<id>` DOIs | 100 | 3.1 s |
| Crossref | `GET /works/<doi>`, JATS stripped with `metadata_lookup._strip_jats` | 1 | 0.25 s |

`User-Agent` is `PaperManager-abstract-backfill/1.0`, plus ` (<contact>)` when `ABSTRACT_BACKFILL_CONTACT`
is set; a contact containing `@` is also sent as `mailto` to OpenAlex and Crossref. A batch that fails
after the retries is recorded in the report and its DOIs go on to the next source; three failed batches
in a row (five single requests for Crossref) switch a source off for the rest of the run. Nothing a
service does can crash the run.

`title_search` (off by default): papers without a DOI are looked up one by one in OpenAlex
(`filter=title.search:`); the title must be equal after normalisation or have a difflib ratio of at
least 0.97, and exactly one distinct abstract may match.

## Safety checks

An abstract is applied only if all hold, else the paper keeps its empty abstract and the reason is
in the report:

1. **Title**: library and returned title match after normalisation (case, accents, punctuation,
   tags), by difflib ratio >= 0.88 (plain or with the words sorted), word-set overlap >= 0.88, or
   prefix with coverage >= 0.9; the numbers in both titles must be equal (`Part 1` is not `Part 2`).
   Otherwise `title_mismatch`, listed with both titles.
2. **Length** 80 to 6000 characters after cleaning, **not a placeholder** (`Abstract not available`,
   `No abstract`, `n/a`, ...), **not the title repeated**, mostly letters. Otherwise `rejected_quality`.
3. **Cleaning**: entities decoded, HTML and JATS tags dropped (a `<` that does not start a tag is kept),
   an `Abstract` heading removed, whitespace collapsed.
4. **Never overwrite**: the write is `MATCH (p:Paper {id: $id}) WHERE p.abstract IS NULL OR trim(p.abstract) = ''
   SET p.abstract, p.abstract_source, p.abstract_fetched_at RETURN p.id`; only returned rows count as
   applied, so an abstract that appears between the selection and the write wins (`skipped_has_abstract`).

`abstract_source` is the service name, `abstract_fetched_at` an ISO UTC time. `updated_at` is **not**
touched: the library's `updated_desc` sort reads it and a backfill would put hundreds of papers at the top.
The vector index notices the new text by its hash and re-embeds on its next sync; nothing to trigger.

## Report

`run_backfill` returns it; the CLI writes it to `--report`. Top level: `dry_run`, `options`, `counts`
(`candidates`, `candidates_total`, `applied` or `would_apply`, `no_abstract_found`, `title_mismatch`,
`rejected_quality`, `skipped_has_abstract`, `no_doi`, `invalid_doi`, `incomplete_lookup`, `errors`),
`accepted_by_source`, `per_source` (requests, found, accepted, errors, disabled), `errors` (at most 50),
and per paper: `id`, `outcome`, `source`, `abstract_length`, `abstract_sha1`, `title_mismatch`
(both titles), `rejected`, `failed_sources`. The file holds library titles, so the CLI refuses a
`--report` path inside any git work tree and writes it with mode 0600.

## Entry points

* **CLI**: `python scripts/backfill_abstracts.py [--apply] [--report PATH] [--limit N] [--include-stubs]
  [--sources a,b] [--title-search]`; `--apply` requires `--report`;
  `--undo-report PATH [--apply]` clears what a report applied (dry run without `--apply`).
* **Undo** clears `abstract`, `abstract_source`, `abstract_fetched_at` of exactly the papers an
  `applied` report lists, and only where `abstract_source` equals the report's source **and** the stored
  text still has the reported SHA-1, so an abstract a user wrote or edited since stays.
* **Route** `POST /backfill/abstracts` (admin only, synchronous like the other backfill routes), body
  `{dry_run: true, limit, include_stubs, sources, title_search}`. A request processes at most 500 papers
  (default 100) so that it ends before a gateway timeout; one run at a time (409 otherwise); unknown
  source 422. The answer is `summarize_for_api`: counts, per-source statistics, error messages and at
  most 50 `{id, outcome}` samples, no titles. For the whole library use the CLI.

## Privacy

Only DOIs (and, with `title_search`, titles of papers that have no DOI) leave the instance, sent to
OpenAlex, Semantic Scholar, arXiv and Crossref. No abstracts, notes, users or other data are sent.
