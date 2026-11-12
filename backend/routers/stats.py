from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from neo4j import Driver

from db.connection import get_driver
from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from services import topic_map

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
def get_stats(driver: Driver = Depends(get_driver)):
    with driver.session() as session:
        # Exclude all from-references papers
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


_LIB = "NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'})"


def _dashboard(driver: Driver, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    pvis, pparams = paper_visibility_clause("p")
    projvis, projparams = project_visibility_clause("proj")
    d7 = (now - timedelta(days=7)).isoformat()
    d30 = (now - timedelta(days=30)).isoformat()
    since = (topic_map.monday_of(now.date()) - timedelta(weeks=11)).isoformat()
    with driver.session() as session:
        lib = session.run(
            f"""
            MATCH (p:Paper) WHERE {_LIB} AND ({pvis})
            RETURN count(p) AS total,
                   sum(CASE WHEN p.created_at >= $d7 THEN 1 ELSE 0 END) AS added_7d,
                   sum(CASE WHEN p.created_at >= $d30 THEN 1 ELSE 0 END) AS added_30d,
                   sum(CASE WHEN p.reading_status = 'read' THEN 1 ELSE 0 END) AS read,
                   sum(CASE WHEN p.reading_status = 'reading' THEN 1 ELSE 0 END) AS reading
            """, d7=d7, d30=d30, **pparams).single()
        refs = session.run(
            f"""
            MATCH (p:Paper)-[:TAGGED]->(:Tag {{name: 'from-references'}}) WHERE ({pvis})
            RETURN count(p) AS c
            """, **pparams).single()["c"]
        created = session.run(
            f"""
            MATCH (p:Paper) WHERE {_LIB} AND ({pvis}) AND p.created_at >= $since
            RETURN p.created_at AS c
            """, since=since, **pparams).value()
        top_topics = session.run(
            f"""
            MATCH (p:Paper)-[:ABOUT]->(t:Topic) WHERE {_LIB} AND ({pvis})
            RETURN t.name AS name, count(p) AS count ORDER BY count DESC, name LIMIT 8
            """, **pparams).data()
        tags = session.run(
            f"""
            MATCH (p:Paper)-[:TAGGED]->(g:Tag)
            WHERE {_LIB} AND ({pvis}) AND NOT g.name STARTS WITH 'from-' AND g.name <> 'pdf-upload'
            RETURN g.name AS name, count(p) AS count ORDER BY count DESC, name LIMIT 8
            """, **pparams).data()
        projects = session.run(
            f"""
            MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project) WHERE ({projvis}) AND ({pvis})
            RETURN proj.id AS id, proj.name AS name, count(p) AS count,
                   sum(CASE WHEN p.reading_status = 'read' THEN 1 ELSE 0 END) AS read,
                   sum(CASE WHEN p.reading_status = 'reading' THEN 1 ELSE 0 END) AS reading,
                   max(p.created_at) AS last_added
            ORDER BY last_added DESC LIMIT 6
            """, **{**projparams, **pparams}).data()
    total = lib["total"]
    return {
        "total": total,
        "references": refs,
        "added_7d": lib["added_7d"],
        "added_30d": lib["added_30d"],
        "added_weekly": topic_map.week_buckets(created, now),
        "reading": {"unread": total - lib["read"] - lib["reading"], "reading": lib["reading"], "read": lib["read"]},
        "top_topics": top_topics,
        "top_tags": tags,
        "projects": projects,
    }


@router.get("/dashboard")
def get_dashboard(driver: Driver = Depends(get_driver)):
    return _dashboard(driver)


@router.get("/topic-map")
def get_topic_map(refs: int = Query(1), driver: Driver = Depends(get_driver)):
    return topic_map.get_topic_map(driver, refs=bool(refs))
