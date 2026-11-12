export interface CypherExample {
  label: string;
  desc: string;
  query: string;
}

export interface CypherExampleGroup {
  category: string;
  items: CypherExample[];
}

/** Example queries offered in the Graph page's query panel, grouped by category. */
export const CYPHER_EXAMPLES: CypherExampleGroup[] = [
  {
    category: "Graph views",
    items: [
      {
        label: "Neighbourhood of a paper",
        desc: "A paper with everything linked to it (topics, authors, tags, notes, citations)",
        query: `MATCH (p:Paper)
WHERE toLower(p.title) CONTAINS toLower("PAPER TITLE HERE")
WITH p LIMIT 1
MATCH (p)-[r]-(n)
RETURN p, r, n`,
      },
      {
        label: "Citation network between full papers",
        desc: "Papers in your library that cite each other (no reference stubs)",
        query: `MATCH (a:Paper)-[r:CITES]->(b:Paper)
WHERE a.metadata_source IS NOT NULL AND b.metadata_source IS NOT NULL
RETURN a, r, b
LIMIT 300`,
      },
      {
        label: "Topics and the papers about them",
        desc: "The most used topics with their papers",
        query: `MATCH (t:Topic)<-[r:ABOUT]-(p:Paper)
WITH t, count(p) AS n
ORDER BY n DESC
LIMIT 8
MATCH (t)<-[r:ABOUT]-(p:Paper)
RETURN t, r, p`,
      },
      {
        label: "Papers of a project with their authors",
        desc: "One project, its papers and the people who wrote them",
        query: `MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project)
WHERE toLower(proj.name) CONTAINS toLower("PROJECT NAME HERE")
OPTIONAL MATCH (p)-[r:AUTHORED_BY]->(a:Person)
RETURN proj, p, r, a`,
      },
    ],
  },
  {
    category: "Discovery",
    items: [
      {
        label: "Papers with no notes yet",
        desc: "Ingested papers you haven't written any notes on",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
  AND NOT (p)<-[:ABOUT]-(:Note)
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers similar to a given paper",
        desc: "Papers sharing the most topics and authors with a paper you name",
        query: `MATCH (seed:Paper)
WHERE toLower(seed.title) CONTAINS toLower("PAPER TITLE HERE")
MATCH (seed)-[:ABOUT]->(t:Topic)<-[:ABOUT]-(other:Paper)
WHERE other <> seed
WITH other, count(DISTINCT t) AS shared_topics
OPTIONAL MATCH (seed)-[:AUTHORED_BY]->(a:Person)<-[:AUTHORED_BY]-(other)
WITH other, shared_topics, count(DISTINCT a) AS shared_authors
RETURN other.title AS title, other.year AS year,
       shared_topics, shared_authors,
       shared_topics + shared_authors AS score
ORDER BY score DESC
LIMIT 15`,
      },
      {
        label: "Papers bridging two topics",
        desc: "Papers that sit at the intersection of two research areas",
        query: `MATCH (p:Paper)-[:ABOUT]->(t1:Topic), (p)-[:ABOUT]->(t2:Topic)
WHERE toLower(t1.name) CONTAINS toLower("TOPIC A")
  AND toLower(t2.name) CONTAINS toLower("TOPIC B")
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.citation_count DESC NULLS LAST`,
      },
      {
        label: "Classic papers (old + highly cited)",
        desc: "Papers older than 10 years with the most citations — foundational work",
        query: `MATCH (p:Paper)
WHERE p.year IS NOT NULL
  AND p.year <= date().year - 10
  AND p.citation_count IS NOT NULL
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.citation_count DESC
LIMIT 20`,
      },
      {
        label: "Recent papers (last 2 years)",
        desc: "Papers published in the last two years",
        query: `MATCH (p:Paper)
WHERE p.year >= date().year - 2
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.year DESC, p.citation_count DESC NULLS LAST
LIMIT 30`,
      },
      {
        label: "Highly cited but no summary",
        desc: "Important papers where AI summary never ran — prioritise these",
        query: `MATCH (p:Paper)
WHERE p.summary IS NULL
  AND p.citation_count IS NOT NULL
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.citation_count DESC
LIMIT 20`,
      },
      {
        label: "Papers you added but never categorised",
        desc: "Papers with no topics, no tags, and no notes",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
  AND NOT (p)-[:ABOUT]->()
  AND NOT (p)-[:TAGGED]->()
  AND NOT (p)<-[:ABOUT]-(:Note)
RETURN p.title AS title, p.year AS year, p.created_at AS added
ORDER BY p.created_at DESC`,
      },
    ],
  },
  {
    category: "Network Analysis",
    items: [
      {
        label: "Citation chains (depth 2)",
        desc: "Papers that cite papers that cite a given paper",
        query: `MATCH (root:Paper)<-[:CITES*1..2]-(p:Paper)
WHERE toLower(root.title) CONTAINS toLower("PAPER TITLE HERE")
  AND p <> root
RETURN DISTINCT p.title AS title, p.year AS year
ORDER BY p.year DESC
LIMIT 30`,
      },
      {
        label: "Papers not cited by anything in your library",
        desc: "Leaf nodes — papers with no incoming CITES (not referenced by others in your collection)",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
  AND NOT ()-[:CITES]->(p)
RETURN p.title AS title, p.year AS year, p.citation_count AS ext_citations
ORDER BY p.ext_citations DESC NULLS LAST
LIMIT 30`,
      },
      {
        label: "Hub papers (cited AND citing many)",
        desc: "Papers with high in-degree and out-degree — connective tissue of your library",
        query: `MATCH (p:Paper)
OPTIONAL MATCH ()-[:CITES]->(p)
WITH p, count(*) AS in_degree
OPTIONAL MATCH (p)-[:CITES]->()
WITH p, in_degree, count(*) AS out_degree
WHERE in_degree > 0 AND out_degree > 0
RETURN p.title AS title, p.year AS year,
       in_degree AS cited_by, out_degree AS cites, in_degree + out_degree AS total_degree
ORDER BY total_degree DESC
LIMIT 20`,
      },
      {
        label: "Topic clusters by shared authors",
        desc: "Which topics are linked through shared authors",
        query: `MATCH (t1:Topic)<-[:ABOUT]-(p:Paper)-[:ABOUT]->(t2:Topic)
WHERE id(t1) < id(t2)
WITH t1, t2, count(p) AS shared
WHERE shared >= 2
RETURN t1.name AS topic_a, t2.name AS topic_b, shared AS shared_papers
ORDER BY shared DESC
LIMIT 20`,
      },
      {
        label: "References you haven't pulled yet",
        desc: "Stubs cited by your papers that aren't fully in your library",
        query: `MATCH (yours:Paper)-[:CITES]->(stub:Paper)
WHERE yours.metadata_source IS NOT NULL
  AND stub.metadata_source IS NULL
RETURN stub.title AS missing_paper, stub.doi AS doi, stub.year AS year,
       count(yours) AS cited_by_count
ORDER BY cited_by_count DESC
LIMIT 30`,
      },
    ],
  },
  {
    category: "Projects",
    items: [
      {
        label: "Projects with paper count",
        desc: "All projects and how many papers they contain",
        query: `MATCH (proj:Project)
OPTIONAL MATCH (p:Paper)-[:IN_PROJECT]->(proj)
RETURN proj.name AS project, proj.description AS description, count(p) AS papers
ORDER BY papers DESC`,
      },
      {
        label: "Papers in a specific project",
        desc: "All papers in a named project",
        query: `MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project)
WHERE toLower(proj.name) CONTAINS toLower("PROJECT NAME HERE")
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.year DESC`,
      },
      {
        label: "Papers not in any project",
        desc: "Papers that haven't been added to a project yet",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
  AND NOT (p)-[:IN_PROJECT]->()
RETURN p.title AS title, p.year AS year
ORDER BY p.created_at DESC`,
      },
      {
        label: "Topic breakdown per project",
        desc: "What research topics each project covers",
        query: `MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project)-[:ABOUT]->(t:Topic)
RETURN proj.name AS project, t.name AS topic, count(p) AS papers
ORDER BY proj.name, papers DESC`,
      },
      {
        label: "Authors per project",
        desc: "Which authors appear in each project",
        query: `MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project)-[:AUTHORED_BY]->(a:Person)
RETURN proj.name AS project, a.name AS author, count(p) AS papers
ORDER BY proj.name, papers DESC`,
      },
    ],
  },
  {
    category: "Annotations & Notes",
    items: [
      {
        label: "Most annotated papers",
        desc: "Papers with the most PDF highlights/annotations",
        query: `MATCH (p:Paper)-[:HAS_ANNOTATION]->(a:Annotation)
RETURN p.title AS title, p.year AS year, count(a) AS annotation_count
ORDER BY annotation_count DESC
LIMIT 20`,
      },
      {
        label: "Annotations by colour",
        desc: "How many highlights you have per colour label",
        query: `MATCH (p:Paper)-[:HAS_ANNOTATION]->(a:Annotation)
WHERE a.color IS NOT NULL
RETURN a.color AS color, count(a) AS count
ORDER BY count DESC`,
      },
      {
        label: "Annotations with notes",
        desc: "Highlights that have a written note attached",
        query: `MATCH (p:Paper)-[:HAS_ANNOTATION]->(a:Annotation)
WHERE a.note IS NOT NULL AND a.note <> ''
RETURN p.title AS paper, a.highlighted_text AS highlight,
       a.note AS note, a.color AS color
ORDER BY p.title`,
      },
      {
        label: "Notes mentioning a topic",
        desc: "Notes that reference a research topic via #mention",
        query: `MATCH (n:Note)-[:MENTIONS]->(t:Topic)
MATCH (n)-[:ABOUT]->(p:Paper)
WHERE toLower(t.name) CONTAINS toLower("TOPIC NAME HERE")
RETURN p.title AS paper, left(n.content, 200) AS note_preview`,
      },
      {
        label: "Papers with notes but no summary",
        desc: "You wrote notes but the AI summary is missing",
        query: `MATCH (n:Note)-[:ABOUT]->(p:Paper)
WHERE p.summary IS NULL
RETURN p.title AS title, p.year AS year, left(n.content, 120) AS note_preview
ORDER BY p.created_at DESC`,
      },
    ],
  },
  {
    category: "Data Quality",
    items: [
      {
        label: "Suspiciously short abstracts",
        desc: "Abstracts under 150 chars — likely truncated or extraction error",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NOT NULL
  AND size(p.abstract) < 150
RETURN p.title AS title, p.year AS year, p.abstract AS abstract
ORDER BY size(p.abstract) ASC`,
      },
      {
        label: "Titles that look like filenames",
        desc: "Titles containing underscores, hyphens or .pdf — extraction probably grabbed the filename",
        query: `MATCH (p:Paper)
WHERE p.title =~ '.*[_\\-].*' OR toLower(p.title) ENDS WITH '.pdf'
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.metadata_source AS source`,
      },
      {
        label: "Very long titles",
        desc: "Titles over 200 chars — may have grabbed the first paragraph instead",
        query: `MATCH (p:Paper)
WHERE size(p.title) > 200
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, size(p.title) AS length, p.metadata_source AS source
ORDER BY length DESC`,
      },
      {
        label: "Papers with future years",
        desc: "Year field set to a year in the future — extraction error",
        query: `MATCH (p:Paper)
WHERE p.year > date().year
RETURN p.title AS title, p.year AS year, p.metadata_source AS source`,
      },
      {
        label: "Papers before 1900",
        desc: "Year field looks unrealistically old — likely a parsing artefact",
        query: `MATCH (p:Paper)
WHERE p.year IS NOT NULL AND p.year < 1900
RETURN p.title AS title, p.year AS year, p.metadata_source AS source`,
      },
      {
        label: "Authors with very short names",
        desc: "Person nodes with 1–2 char names — likely initials grabbed as names",
        query: `MATCH (p:Person)
WHERE size(p.name) <= 2
RETURN p.name AS name, p.id AS id`,
      },
    ],
  },
  {
    category: "Broken / Incomplete",
    items: [
      {
        label: "Papers without abstracts",
        desc: "Fully ingested papers still missing an abstract",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NULL
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.doi AS doi, p.metadata_source AS source
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers without a summary",
        desc: "Papers that were uploaded but AI summary never ran",
        query: `MATCH (p:Paper)
WHERE p.summary IS NULL
  AND p.drive_file_id IS NOT NULL
RETURN p.title AS title, p.year AS year, p.metadata_source AS source
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers with no DOI or arXiv",
        desc: "Papers missing a stable identifier — metadata may be unreliable",
        query: `MATCH (p:Paper)
WHERE p.doi IS NULL
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.metadata_source AS source
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers with no year",
        desc: "Ingested papers where year extraction failed",
        query: `MATCH (p:Paper)
WHERE p.year IS NULL
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.doi AS doi, p.metadata_source AS source
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers with no authors",
        desc: "Papers not linked to any Person node",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
  AND NOT (p)-[:AUTHORED_BY]->()
RETURN p.title AS title, p.year AS year, p.doi AS doi
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers with no PDF on Drive",
        desc: "Ingested papers missing a Google Drive file (URL imports, stubs)",
        query: `MATCH (p:Paper)
WHERE p.drive_file_id IS NULL
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.metadata_source AS source
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers with no topics AND no tags",
        desc: "Completely uncategorised papers",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
  AND NOT (p)-[:ABOUT]->()
  AND NOT (p)-[:TAGGED]->()
RETURN p.title AS title, p.year AS year
ORDER BY p.created_at DESC`,
      },
      {
        label: "Health check — missing fields count",
        desc: "Summary of how many papers are missing each key field",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NOT NULL
RETURN
  count(p) AS total,
  sum(CASE WHEN p.abstract IS NULL THEN 1 ELSE 0 END) AS no_abstract,
  sum(CASE WHEN p.summary IS NULL THEN 1 ELSE 0 END) AS no_summary,
  sum(CASE WHEN p.doi IS NULL THEN 1 ELSE 0 END) AS no_doi,
  sum(CASE WHEN p.year IS NULL THEN 1 ELSE 0 END) AS no_year,
  sum(CASE WHEN NOT (p)-[:AUTHORED_BY]->() THEN 1 ELSE 0 END) AS no_authors`,
      },
    ],
  },
  {
    category: "References",
    items: [
      {
        label: "Show all reference stubs",
        desc: "Papers pulled as citation stubs (no full data yet)",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NULL
  AND p.drive_file_id IS NULL
  AND p.metadata_source IS NULL
RETURN p.title AS title, p.year AS year, p.doi AS doi
ORDER BY p.year DESC`,
      },
      {
        label: "Most referenced papers",
        desc: "Papers in your library cited by the most other papers",
        query: `MATCH (cited:Paper)<-[:CITES]-(citing:Paper)
RETURN cited.title AS title, cited.year AS year, count(citing) AS cited_by_count
ORDER BY cited_by_count DESC
LIMIT 20`,
      },
      {
        label: "Papers citing a specific paper",
        desc: "Find which papers in your library cite a given paper",
        query: `MATCH (citing:Paper)-[:CITES]->(cited:Paper)
WHERE toLower(cited.title) CONTAINS toLower("CITED PAPER TITLE")
RETURN citing.title AS citing_paper, citing.year AS year
ORDER BY year DESC`,
      },
      {
        label: "Papers with most outgoing references",
        desc: "Papers that cite the most other works",
        query: `MATCH (p:Paper)-[:CITES]->(ref:Paper)
RETURN p.title AS title, p.year AS year, count(ref) AS references_count
ORDER BY references_count DESC
LIMIT 20`,
      },
      {
        label: "Reference stubs with a DOI",
        desc: "Stubs you could pull into your library (have a DOI to look up)",
        query: `MATCH (p:Paper)
WHERE p.metadata_source IS NULL
  AND p.doi IS NOT NULL
RETURN p.title AS title, p.doi AS doi, p.year AS year
ORDER BY p.year DESC`,
      },
      {
        label: "Delete all reference stubs",
        desc: "Remove sparse citation stubs that haven't been pulled",
        query: `MATCH (p:Paper)
WHERE p.abstract IS NULL
  AND p.drive_file_id IS NULL
  AND p.metadata_source IS NULL
DETACH DELETE p`,
      },
      {
        label: "Remove all CITES from a paper",
        desc: "Delete citation relationships only (not the cited papers themselves)",
        query: `MATCH (p:Paper)-[r:CITES]->()
WHERE toLower(p.title) CONTAINS toLower("PAPER TITLE HERE")
DELETE r`,
      },
    ],
  },
  {
    category: "Papers",
    items: [
      {
        label: "Papers by year distribution",
        desc: "Count how many papers per publication year",
        query: `MATCH (p:Paper)
WHERE p.year IS NOT NULL
RETURN p.year AS year, count(p) AS count
ORDER BY year DESC`,
      },
      {
        label: "Most cited papers in library",
        desc: "Papers with the highest citation_count from Semantic Scholar",
        query: `MATCH (p:Paper)
WHERE p.citation_count IS NOT NULL
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY citations DESC
LIMIT 20`,
      },
      {
        label: "Papers added this week",
        desc: "Recently added papers",
        query: `MATCH (p:Paper)
WHERE p.created_at >= toString(date() - duration('P7D'))
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year, p.created_at AS added
ORDER BY p.created_at DESC`,
      },
      {
        label: "Papers by metadata source",
        desc: "How many papers came from each extraction method",
        query: `MATCH (p:Paper)
RETURN p.metadata_source AS source, count(p) AS count
ORDER BY count DESC`,
      },
      {
        label: "Papers in multiple projects",
        desc: "Papers that appear in more than one project",
        query: `MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project)
WITH p, collect(proj.name) AS projects, count(proj) AS n
WHERE n > 1
RETURN p.title AS title, p.year AS year, projects
ORDER BY n DESC`,
      },
      {
        label: "Papers with notes",
        desc: "Papers that have a written note attached",
        query: `MATCH (n:Note)-[:ABOUT]->(p:Paper)
RETURN p.title AS title, p.year AS year, left(n.content, 120) AS note_preview
ORDER BY p.created_at DESC`,
      },
    ],
  },
  {
    category: "Authors & People",
    items: [
      {
        label: "Most prolific authors",
        desc: "Authors with the most papers in your library",
        query: `MATCH (person:Person)<-[:AUTHORED_BY]-(p:Paper)
RETURN person.name AS author, person.affiliation AS affiliation, count(p) AS paper_count
ORDER BY paper_count DESC
LIMIT 20`,
      },
      {
        label: "Authors who collaborate",
        desc: "Pairs of authors who co-appear on the same papers",
        query: `MATCH (a:Person)<-[:AUTHORED_BY]-(p:Paper)-[:AUTHORED_BY]->(b:Person)
WHERE id(a) < id(b)
RETURN a.name AS author_a, b.name AS author_b, count(p) AS shared_papers
ORDER BY shared_papers DESC
LIMIT 20`,
      },
      {
        label: "Author publication timeline",
        desc: "All papers by an author ordered by year",
        query: `MATCH (person:Person)<-[:AUTHORED_BY]-(p:Paper)
WHERE toLower(person.name) CONTAINS toLower("AUTHOR NAME HERE")
RETURN p.title AS title, p.year AS year, p.citation_count AS citations
ORDER BY p.year DESC`,
      },
      {
        label: "Authors with affiliation",
        desc: "People nodes that have an affiliation set",
        query: `MATCH (p:Person)
WHERE p.affiliation IS NOT NULL
RETURN p.name AS name, p.affiliation AS affiliation, count{ (p)<-[:AUTHORED_BY]-() } AS papers
ORDER BY papers DESC`,
      },
      {
        label: "People mentioned in notes",
        desc: "People linked via @mentions in paper notes",
        query: `MATCH (n:Note)-[:MENTIONS]->(person:Person)
MATCH (n)-[:ABOUT]->(p:Paper)
RETURN person.name AS person, p.title AS paper, left(n.content, 100) AS note_snippet`,
      },
      {
        label: "People with no papers",
        desc: "Person nodes with no linked papers (cleanup candidates)",
        query: `MATCH (p:Person)
WHERE NOT (p)<-[:AUTHORED_BY]-()
  AND NOT (p)<-[:INVOLVES]-()
RETURN p.name AS name, p.id AS id`,
      },
      {
        label: "Authors spanning multiple topics",
        desc: "Authors whose papers cover the most distinct research topics",
        query: `MATCH (person:Person)<-[:AUTHORED_BY]-(p:Paper)-[:ABOUT]->(t:Topic)
RETURN person.name AS author, count(DISTINCT t) AS topic_count, collect(DISTINCT t.name) AS topics
ORDER BY topic_count DESC
LIMIT 20`,
      },
    ],
  },
  {
    category: "Topics & Tags",
    items: [
      {
        label: "Topics with paper count",
        desc: "All topics ranked by how many papers they cover",
        query: `MATCH (t:Topic)
OPTIONAL MATCH (p:Paper)-[:ABOUT]->(t)
RETURN t.name AS topic, count(p) AS papers
ORDER BY papers DESC`,
      },
      {
        label: "Topic co-occurrence",
        desc: "Which topics appear together most on the same papers",
        query: `MATCH (a:Topic)<-[:ABOUT]-(p:Paper)-[:ABOUT]->(b:Topic)
WHERE id(a) < id(b)
RETURN a.name AS topic_a, b.name AS topic_b, count(p) AS shared_papers
ORDER BY shared_papers DESC
LIMIT 20`,
      },
      {
        label: "Papers with no topics",
        desc: "Papers missing research topic assignments",
        query: `MATCH (p:Paper)
WHERE NOT (p)-[:ABOUT]->()
  AND p.metadata_source IS NOT NULL
RETURN p.title AS title, p.year AS year`,
      },
      {
        label: "Tags and their paper counts",
        desc: "All tags ranked by usage",
        query: `MATCH (t:Tag)
OPTIONAL MATCH (p:Paper)-[:TAGGED]->(t)
RETURN t.name AS tag, count(p) AS papers
ORDER BY papers DESC`,
      },
      {
        label: "Rename a tag",
        desc: "Update a tag name across the entire graph",
        query: `MATCH (t:Tag {name: "OLD TAG NAME"})
SET t.name = "NEW TAG NAME"
RETURN t`,
      },
      {
        label: "Merge two topics",
        desc: "Re-point all papers from one topic to another, then delete the old one",
        query: `MATCH (old:Topic {name: "OLD TOPIC"}), (keep:Topic {name: "KEEP TOPIC"})
MATCH (p:Paper)-[r:ABOUT]->(old)
MERGE (p)-[:ABOUT]->(keep)
DELETE r
WITH old
DETACH DELETE old`,
      },
    ],
  },
  {
    category: "Cleanup",
    items: [
      {
        label: "Duplicate papers by title",
        desc: "Find papers with identical titles (potential duplicates)",
        query: `MATCH (p:Paper)
WITH toLower(trim(p.title)) AS norm, collect(p.id) AS ids, count(*) AS cnt
WHERE cnt > 1
RETURN norm AS title, cnt AS duplicates, ids`,
      },
      {
        label: "Duplicate authors by name",
        desc: "Person nodes that look like the same person (same normalised name)",
        query: `MATCH (p:Person)
WITH toLower(trim(p.name)) AS norm, collect(p.id) AS ids, count(*) AS cnt
WHERE cnt > 1
RETURN norm AS name, cnt AS duplicates, ids`,
      },
      {
        label: "Orphan nodes",
        desc: "Nodes with no relationships at all",
        query: `MATCH (n)
WHERE NOT (n)--()
RETURN labels(n) AS type, n.name AS name, n.title AS title, n.id AS id`,
      },
      {
        label: "Delete orphan nodes",
        desc: "Remove all completely unconnected nodes",
        query: `MATCH (n)
WHERE NOT (n)--()
DETACH DELETE n`,
      },
      {
        label: "Merge duplicate author (re-point rels)",
        desc: "Move all relationships from a duplicate Person to the canonical one",
        query: `MATCH (keep:Person {name: "CANONICAL NAME"}), (dup:Person {name: "DUPLICATE NAME"})
MATCH (dup)<-[r:AUTHORED_BY]-(p:Paper)
MERGE (p)-[:AUTHORED_BY]->(keep)
DELETE r
WITH dup
DETACH DELETE dup`,
      },
    ],
  },
];
