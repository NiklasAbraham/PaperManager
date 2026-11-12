from neo4j import Driver

_CONSTRAINTS = [
    "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (n:Paper) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (n:Topic) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (n:Topic) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT tag_id IF NOT EXISTS FOR (n:Tag) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (n:Tag) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT venue_id IF NOT EXISTS FOR (n:Venue) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT note_id IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (n:Conversation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT message_id IF NOT EXISTS FOR (n:Message) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT figure_id IF NOT EXISTS FOR (n:Figure) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT blog_id IF NOT EXISTS FOR (n:Blog) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT blogpost_id IF NOT EXISTS FOR (n:BlogPost) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT annotation_id IF NOT EXISTS FOR (a:Annotation) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT user_name IF NOT EXISTS FOR (n:User) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT map_concept_id IF NOT EXISTS FOR (c:MapConcept) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT map_concept_key IF NOT EXISTS FOR (c:MapConcept) REQUIRE c.key IS UNIQUE",
    "CREATE CONSTRAINT report_id IF NOT EXISTS FOR (r:Report) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT suggestion_id IF NOT EXISTS FOR (n:Suggestion) REQUIRE n.id IS UNIQUE",
]

# Full-text indexes of the library search (.specs/012_search.md), analysed with
# standard-folding: lower case, accents folded (Tübingen = Tubingen), English stop words
# dropped. (name, label pattern, properties, eventually consistent). The full-text index
# on raw_text is eventually consistent so an upload does not wait for Lucene to index
# ~100 kB of text. An existing index with another analyzer or other properties is dropped
# and rebuilt at startup (seconds on a library of ~9k papers; see _ensure_fulltext).
SEARCH_ANALYZER = "standard-folding"
_SEARCH_INDEXES = [
    ("paper_search", "n:Paper", ["title", "abstract", "summary"], False),
    ("note_search", "n:Note", ["content"], False),
    ("claim_search", "n:Claim", ["text"], False),
    ("entity_name_search", "n:Person|Topic|Tag|Project", ["name"], False),
    ("annotation_search", "n:Annotation", ["highlighted_text", "note"], False),
    ("paper_text_search", "n:Paper", ["venue", "raw_text"], True),
]

_INDEXES = [
    """CREATE FULLTEXT INDEX message_search IF NOT EXISTS
       FOR (n:Message) ON EACH [n.content]""",
    # Vector index for semantic similarity search (nomic-embed-text, 768-dim)
    """CREATE VECTOR INDEX paper_embeddings IF NOT EXISTS
       FOR (n:Paper) ON n.embedding
       OPTIONS {indexConfig: {
         `vector.dimensions`: 768,
         `vector.similarity_function`: 'cosine'
       }}""",
    # Range indexes for the library listing's date/year filters and sorts (.specs/012_search.md).
    "CREATE INDEX paper_created_at IF NOT EXISTS FOR (p:Paper) ON (p.created_at)",
    "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    "CREATE INDEX paper_updated_at IF NOT EXISTS FOR (p:Paper) ON (p.updated_at)",
]


def fulltext_statement(name: str, pattern: str, props: list[str], eventual: bool) -> str:
    on = ", ".join(f"n.{p}" for p in props)
    config = f"`fulltext.analyzer`: '{SEARCH_ANALYZER}'"
    if eventual:
        config += ", `fulltext.eventually_consistent`: true"
    return (f"CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR ({pattern}) ON EACH [{on}] "
            f"OPTIONS {{indexConfig: {{{config}}}}}")


def _ensure_fulltext(session) -> None:
    existing = {r["name"]: r for r in session.run(
        "SHOW FULLTEXT INDEXES YIELD name, properties, options RETURN name, properties, options")}
    for name, pattern, props, eventual in _SEARCH_INDEXES:
        cur = existing.get(name)
        if cur is not None:
            cfg = (cur["options"] or {}).get("indexConfig", {})
            same = (cfg.get("fulltext.analyzer") == SEARCH_ANALYZER
                    and list(cur["properties"] or []) == props
                    and bool(cfg.get("fulltext.eventually_consistent")) == eventual)
            if same:
                continue
            session.run(f"DROP INDEX {name} IF EXISTS").consume()
        session.run(fulltext_statement(name, pattern, props, eventual)).consume()


def run_schema_setup(driver: Driver):
    with driver.session() as session:
        for stmt in _CONSTRAINTS + _INDEXES:
            session.run(stmt)
        _ensure_fulltext(session)
