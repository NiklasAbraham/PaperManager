from fastapi import APIRouter, Depends
from neo4j import Driver
from db.connection import get_driver

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
def get_stats(driver: Driver = Depends(get_driver)):
    with driver.session() as session:
        # Exclude stub papers pulled in via reference scanning
        papers   = session.run("""
            MATCH (n:Paper) WHERE NOT (n)-[:TAGGED]->(:Tag {name: 'from-references'})
            RETURN count(n) AS c
        """).single()["c"]
        authors  = session.run("MATCH (n:Person)  RETURN count(n) AS c").single()["c"]
        topics   = session.run("MATCH (n:Topic)   RETURN count(n) AS c").single()["c"]
        tags     = session.run("MATCH (n:Tag)     RETURN count(n) AS c").single()["c"]
        projects = session.run("MATCH (n:Project) RETURN count(n) AS c").single()["c"]

        by_year = session.run("""
            MATCH (p:Paper)
            WHERE p.year IS NOT NULL
              AND NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'})
            RETURN p.year AS year, count(p) AS count
            ORDER BY year ASC
        """).data()

        top_topics = session.run("""
            MATCH (t:Topic)<-[:ABOUT]-(p:Paper)
            WHERE NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'})
            RETURN t.name AS name, count(p) AS count
            ORDER BY count DESC LIMIT 8
        """).data()

        recent = session.run("""
            MATCH (p:Paper)
            WHERE NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'})
            OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Person)
            WITH p, collect(a.name) AS authors
            ORDER BY p.created_at DESC LIMIT 6
            RETURN p.id AS id, p.title AS title, p.year AS year,
                   p.doi AS doi, p.metadata_source AS metadata_source,
                   p.created_at AS created_at, authors
        """).data()

        reading_status = session.run("""
            MATCH (p:Paper)
            WHERE NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'})
            RETURN coalesce(p.reading_status, 'unread') AS status, count(p) AS count
            ORDER BY status
        """).data()

        bookmarked_count = session.run("""
            MATCH (p:Paper)
            WHERE p.bookmarked = true
              AND NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'})
            RETURN count(p) AS c
        """).single()["c"]

    return {
        "counts": {
            "papers": papers, "authors": authors, "topics": topics,
            "tags": tags, "projects": projects,
            "bookmarked": bookmarked_count,
        },
        "papers_by_year": by_year,
        "top_topics": top_topics,
        "recent_papers": recent,
        "reading_status": reading_status,
    }
