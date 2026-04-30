import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Blogs ──────────────────────────────────────────────────────────────────────

def create_blog(driver: Driver, data: dict) -> dict:
    blog_id = str(uuid.uuid4())
    with driver.session() as session:
        result = session.run(
            """
            CREATE (b:Blog {
              id: $id,
              name: $name,
              url: $url,
              feed_url: $feed_url,
              description: $description,
              parser: $parser,
              created_at: $now
            }) RETURN b
            """,
            id=blog_id,
            name=data.get("name", ""),
            url=data.get("url", ""),
            feed_url=data.get("feed_url", ""),
            description=data.get("description", ""),
            parser=data.get("parser", "generic"),
            now=_now(),
        )
        return dict(result.single()["b"])


def get_blog(driver: Driver, blog_id: str) -> dict | None:
    with driver.session() as session:
        rec = session.run("MATCH (b:Blog {id: $id}) RETURN b", id=blog_id).single()
        return dict(rec["b"]) if rec else None


def list_blogs(driver: Driver) -> list[dict]:
    with driver.session() as session:
        rows = session.run(
            """
            MATCH (b:Blog)
            OPTIONAL MATCH (bp:BlogPost)-[:FROM_BLOG]->(b)
            RETURN b, count(bp) AS post_count
            ORDER BY b.created_at DESC
            """
        ).data()
        return [{"post_count": r["post_count"], **dict(r["b"])} for r in rows]


def delete_blog(driver: Driver, blog_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (b:Blog {id: $id})
            OPTIONAL MATCH (bp:BlogPost)-[:FROM_BLOG]->(b)
            DETACH DELETE b, bp
            RETURN count(b) AS deleted
            """,
            id=blog_id,
        )
        return result.single()["deleted"] > 0


def find_blog_by_url(driver: Driver, url: str) -> dict | None:
    with driver.session() as session:
        rec = session.run(
            "MATCH (b:Blog) WHERE b.url = $url OR b.url = $url2 RETURN b LIMIT 1",
            url=url.rstrip("/"),
            url2=url.rstrip("/") + "/",
        ).single()
        return dict(rec["b"]) if rec else None


# ── BlogPosts ──────────────────────────────────────────────────────────────────

def create_or_update_post(driver: Driver, blog_id: str, data: dict) -> dict:
    """MERGE by URL so re-fetching the feed never creates duplicates."""
    post_id = str(uuid.uuid4())
    with driver.session() as session:
        result = session.run(
            """
            MATCH (b:Blog {id: $blog_id})
            MERGE (bp:BlogPost {url: $url})
            ON CREATE SET
              bp.id              = $id,
              bp.blog_id         = $blog_id,
              bp.title           = $title,
              bp.author          = $author,
              bp.published_at    = $published_at,
              bp.description     = $description,
              bp.content         = $content,
              bp.content_md      = $content_md,
              bp.figures         = $figures,
              bp.references_json = $references_json,
              bp.imported        = $imported,
              bp.reading_status  = 'unread',
              bp.created_at      = $now,
              bp.updated_at      = $now
            ON MATCH SET
              bp.title           = CASE WHEN $title <> '' THEN $title ELSE bp.title END,
              bp.content         = CASE WHEN $imported AND $content <> '' THEN $content ELSE bp.content END,
              bp.content_md      = CASE WHEN $imported AND $content_md <> '' THEN $content_md ELSE bp.content_md END,
              bp.figures         = CASE WHEN $imported THEN $figures ELSE bp.figures END,
              bp.references_json = CASE WHEN $imported AND $references_json <> '' THEN $references_json ELSE bp.references_json END,
              bp.imported        = CASE WHEN $imported THEN true ELSE bp.imported END,
              bp.updated_at      = $now
            MERGE (bp)-[:FROM_BLOG]->(b)
            RETURN bp
            """,
            blog_id=blog_id,
            id=post_id,
            url=data.get("url", ""),
            title=data.get("title", ""),
            author=data.get("author", ""),
            published_at=data.get("published_at", _now()),
            description=data.get("description", ""),
            content=data.get("content", ""),
            content_md=data.get("content_md", ""),
            figures=data.get("figures", []),
            references_json=data.get("references_json", "[]"),
            imported=data.get("imported", False),
            now=_now(),
        )
        return dict(result.single()["bp"])


def get_post(driver: Driver, post_id: str) -> dict | None:
    with driver.session() as session:
        rec = session.run(
            "MATCH (bp:BlogPost {id: $id}) RETURN bp",
            id=post_id,
        ).single()
        return dict(rec["bp"]) if rec else None


def list_blog_posts(
    driver: Driver,
    blog_id: str,
    reading_status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    with driver.session() as session:
        if reading_status:
            rows = session.run(
                """
                MATCH (bp:BlogPost)-[:FROM_BLOG]->(b:Blog {id: $blog_id})
                WHERE bp.reading_status = $status
                RETURN bp ORDER BY bp.published_at DESC SKIP $skip LIMIT $limit
                """,
                blog_id=blog_id,
                status=reading_status,
                skip=skip,
                limit=limit,
            ).data()
        else:
            rows = session.run(
                """
                MATCH (bp:BlogPost)-[:FROM_BLOG]->(b:Blog {id: $blog_id})
                RETURN bp ORDER BY bp.published_at DESC SKIP $skip LIMIT $limit
                """,
                blog_id=blog_id,
                skip=skip,
                limit=limit,
            ).data()
        # Strip heavy content field from list view
        posts = []
        for r in rows:
            p = dict(r["bp"])
            p.pop("content", None)
            posts.append(p)
        return posts


def update_post(driver: Driver, post_id: str, data: dict) -> dict | None:
    data["updated_at"] = _now()
    with driver.session() as session:
        result = session.run(
            "MATCH (bp:BlogPost {id: $id}) SET bp += $props RETURN bp",
            id=post_id,
            props=data,
        )
        rec = result.single()
        return dict(rec["bp"]) if rec else None


def delete_post(driver: Driver, post_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (bp:BlogPost {id: $id}) DETACH DELETE bp RETURN count(bp) AS deleted",
            id=post_id,
        )
        return result.single()["deleted"] > 0


def random_post(driver: Driver, reading_status: str | None = None) -> dict | None:
    with driver.session() as session:
        if reading_status:
            result = session.run(
                """
                MATCH (bp:BlogPost)
                WHERE bp.reading_status = $status AND bp.imported = true
                WITH bp, rand() AS r ORDER BY r LIMIT 1
                RETURN bp
                """,
                status=reading_status,
            )
        else:
            result = session.run(
                """
                MATCH (bp:BlogPost)
                WHERE bp.imported = true
                WITH bp, rand() AS r ORDER BY r LIMIT 1
                RETURN bp
                """
            )
        rec = result.single()
        if not rec:
            return None
        post = dict(rec["bp"])
        # Also fetch the blog name
        blog_rec = session.run(
            "MATCH (bp:BlogPost {id: $id})-[:FROM_BLOG]->(b:Blog) RETURN b.name AS name, b.id AS blog_id",
            id=post["id"],
        ).single()
        if blog_rec:
            post["blog_name"] = blog_rec["name"]
            post["blog_id"] = blog_rec["blog_id"]
        return post


# ── Tags on BlogPost ───────────────────────────────────────────────────────────

def tag_post(driver: Driver, post_id: str, tag_name: str) -> dict:
    from db.queries.tags import get_or_create_tag
    tag = get_or_create_tag(driver, tag_name)
    with driver.session() as session:
        session.run(
            "MATCH (bp:BlogPost {id: $pid}), (t:Tag {id: $tid}) MERGE (bp)-[:TAGGED]->(t)",
            pid=post_id, tid=tag["id"],
        )
    return tag


def untag_post(driver: Driver, post_id: str, tag_name: str):
    with driver.session() as session:
        session.run(
            "MATCH (bp:BlogPost {id: $pid})-[r:TAGGED]->(t:Tag {name: $name}) DELETE r",
            pid=post_id, name=tag_name,
        )


def get_tags_for_post(driver: Driver, post_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (bp:BlogPost {id: $id})-[:TAGGED]->(t:Tag) RETURN t ORDER BY t.name",
            id=post_id,
        )
        return [dict(r["t"]) for r in result]


# ── People on BlogPost ─────────────────────────────────────────────────────────

def link_person_to_post(driver: Driver, post_id: str, person_name: str, role: str = "author") -> dict:
    person_id = str(uuid.uuid4())
    with driver.session() as session:
        rec = session.run(
            """
            MERGE (p:Person {name: $name})
            ON CREATE SET p.id = $pid
            WITH p
            MATCH (bp:BlogPost {id: $bp_id})
            MERGE (bp)-[r:INVOLVES {role: $role}]->(p)
            RETURN p
            """,
            name=person_name, pid=person_id, bp_id=post_id, role=role,
        ).single()
        return dict(rec["p"]) if rec else {}


def get_people_for_post(driver: Driver, post_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (bp:BlogPost {id: $id})-[r:INVOLVES]->(p:Person)
            RETURN p, r.role AS role
            ORDER BY p.name
            """,
            id=post_id,
        )
        return [{**dict(r["p"]), "role": r["role"]} for r in result]


def unlink_person_from_post(driver: Driver, post_id: str, person_id: str):
    with driver.session() as session:
        session.run(
            "MATCH (bp:BlogPost {id: $bp_id})-[r:INVOLVES]->(p:Person {id: $pid}) DELETE r",
            bp_id=post_id, pid=person_id,
        )


# ── Projects ───────────────────────────────────────────────────────────────────

def add_post_to_project(driver: Driver, post_id: str, project_id: str):
    with driver.session() as session:
        session.run(
            "MATCH (proj:Project {id: $proj_id}), (bp:BlogPost {id: $bp_id}) MERGE (proj)-[:CONTAINS]->(bp)",
            proj_id=project_id, bp_id=post_id,
        )


def remove_post_from_project(driver: Driver, post_id: str, project_id: str):
    with driver.session() as session:
        session.run(
            "MATCH (proj:Project {id: $proj_id})-[r:CONTAINS]->(bp:BlogPost {id: $bp_id}) DELETE r",
            proj_id=project_id, bp_id=post_id,
        )


def get_projects_for_post(driver: Driver, post_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (proj:Project)-[:CONTAINS]->(bp:BlogPost {id: $id}) RETURN proj ORDER BY proj.name",
            id=post_id,
        )
        return [dict(r["proj"]) for r in result]


# ── Notes on BlogPost ──────────────────────────────────────────────────────────

def upsert_post_note(driver: Driver, post_id: str, content: str) -> dict:
    note_id = str(uuid.uuid4())
    with driver.session() as session:
        result = session.run(
            """
            MATCH (bp:BlogPost {id: $post_id})
            MERGE (n:Note)-[:ABOUT]->(bp)
            ON CREATE SET n.id = $note_id, n.content = $content,
                          n.created_at = $now, n.updated_at = $now
            ON MATCH  SET n.content = $content, n.updated_at = $now
            RETURN n
            """,
            post_id=post_id,
            note_id=note_id,
            content=content,
            now=_now(),
        )
        return dict(result.single()["n"])


def get_post_note(driver: Driver, post_id: str) -> dict | None:
    with driver.session() as session:
        rec = session.run(
            "MATCH (n:Note)-[:ABOUT]->(bp:BlogPost {id: $id}) RETURN n",
            id=post_id,
        ).single()
        return dict(rec["n"]) if rec else None
