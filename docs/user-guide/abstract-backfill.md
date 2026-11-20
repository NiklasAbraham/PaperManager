# Fill missing abstracts

Papers that were imported from a list of DOIs or titles often have no abstract. Without one, the
semantic search has only the title to go on and ranks the paper poorly, [similar papers](similar-search.md) rarely
finds it, and the [paper feed](paper-feed.md) cannot learn from it as a paper you kept (that needs an abstract or a
summary). **Abstract backfill** looks up
the missing abstracts of papers that have a DOI in four open services and writes them in, so those papers
are found by meaning as well as by words.

It is an admin tool and changes nothing unless you ask: every run is a **dry run** first.

## What it does

For each paper with a DOI and an empty abstract it asks, in this order and only for what is still missing:

1. **OpenAlex**
2. **Semantic Scholar**
3. **arXiv** (only for arXiv DOIs)
4. **Crossref**

An abstract is accepted only when the title the service returns matches the title in your library, the
text is between 80 and 6,000 characters, and it is not a placeholder such as "Abstract not available".
Anything else is left alone and listed in the report (with both titles for a mismatch). An abstract that
is already there, including one you wrote, is never overwritten. Reference stubs (papers that only exist because another paper cites them, tagged `from-references`) are skipped
unless you include them. Papers without a DOI are counted and skipped.

Each filled paper records where its abstract came from (`abstract_source`) and when (`abstract_fetched_at`).
The search index picks up the new text by itself on its next sync (every 10 minutes by default) and embeds only the
changed papers, with whatever [embedding model](switching-the-embedding-model.md) is configured.

## Run it

Use the script for a whole library. Inside the backend container (the Compose service `backend`, or `app` with
`docker-compose.selfhost.yml`; write the reports to the persistent volume, `/data` or `/app/data`):

```bash
# 1. Dry run: asks the services, writes nothing to your library
python scripts/backfill_abstracts.py --report /data/abstracts_dry.json

# 2. Apply (needs --report, so the run can be undone)
python scripts/backfill_abstracts.py --apply --report /data/abstracts_run1.json

# 3. Undo exactly that run (dry run without --apply)
python scripts/backfill_abstracts.py --undo-report /data/abstracts_run1.json --apply
```

Useful options: `--limit 200` to try a few papers first, `--include-stubs`, `--sources openalex,crossref`
(the order is always OpenAlex, Semantic Scholar, arXiv, Crossref) and `--title-search` (look up papers
without a DOI by title in OpenAlex; only a near-identical title is accepted; off by default).

The report file lists, per paper, the outcome, the source and the length of the abstract, and for
mismatches both titles. It contains your library's titles, so the script refuses to write it inside a git
repository. A rerun only handles papers that still have no abstract. The undo clears an abstract only if
it still has the source and text the run wrote, so an abstract you wrote or edited afterwards stays.

Admins can also call `POST /backfill/abstracts` with `{"dry_run": true, "limit": 100}`. It runs in the
request, handles at most 500 papers and returns counts and up to 50 sample ids, no titles.

## Being a good citizen

The script waits between requests, honours `Retry-After` and gives a service up for the run after
repeated failures. Setting `ABSTRACT_BACKFILL_CONTACT` in `.env` to an e-mail address or URL adds it to the
`User-Agent` and uses it as `mailto` for OpenAlex and Crossref, which gives faster, friendlier access.
A Semantic Scholar API key (`SEMANTIC_SCHOLAR_API_KEY`), if you have one, allows larger batches.

## Privacy

The only data that leaves your instance is the DOIs of the papers being looked up (and, with
`--title-search`, the titles of papers without a DOI). They go to OpenAlex, Semantic Scholar, arXiv and
Crossref. Nothing else about your library is sent.
