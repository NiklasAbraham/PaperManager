import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.blogs import (
    create_blog,
    get_blog,
    list_blogs,
    delete_blog,
    find_blog_by_url,
    create_or_update_post,
    get_post,
    list_blog_posts,
    update_post,
    delete_post,
    random_post,
    upsert_post_note,
    get_post_note,
    tag_post,
    untag_post,
    get_tags_for_post,
    link_person_to_post,
    get_people_for_post,
    unlink_person_from_post,
    add_post_to_project,
    remove_post_from_project,
    get_projects_for_post,
)
from models.schemas import (
    BlogRegisterBody,
    BlogOut,
    BlogPostOut,
    BlogPostUpdate,
    BlogPostChatRequest,
    NoteBody,
    NoteOut,
)
from services.blog_fetcher import (
    detect_blog_config,
    auto_detect_feed,
    fetch_feed_posts,
    fetch_post_full_content,
    fetch_post_extras,
)
from services.ai import summarize_blog_post, chat_with_blog_post

log = logging.getLogger(__name__)
router = APIRouter(prefix="/blogs", tags=["blogs"])


# ── Blog registration & management ────────────────────────────────────────────

@router.post("", response_model=BlogOut, status_code=201)
def register_blog(body: BlogRegisterBody):
    """
    Register a blog. Auto-detects RSS feed, fetches post stubs, returns the blog.
    """
    driver = get_driver()

    # Normalise URL
    url = body.url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url

    # Prevent duplicates
    existing = find_blog_by_url(driver, url)
    if existing:
        return {**existing, "post_count": 0}

    # Match against known registry or auto-detect
    config = detect_blog_config(url)
    if not config:
        feed_url = auto_detect_feed(url)
        if not feed_url:
            raise HTTPException(status_code=422, detail="Could not find RSS/Atom feed for this URL.")
        config = {
            "name": url.split("//")[-1].split("/")[0],
            "feed_url": feed_url,
            "parser": "generic",
            "description": "",
        }

    blog_data = {
        "url": url,
        "name": config["name"],
        "feed_url": config["feed_url"],
        "parser": config["parser"],
        "description": config.get("description", ""),
    }

    blog = create_blog(driver, blog_data)

    # Fetch initial post list
    try:
        posts = fetch_feed_posts(config["feed_url"], config["parser"])
        for p in posts:
            create_or_update_post(driver, blog["id"], p)
        log.info("Fetched %d posts for blog %s", len(posts), blog["id"])
    except Exception as exc:
        log.warning("Failed to fetch initial posts for %s: %s", url, exc)

    blogs = list_blogs(driver)
    for b in blogs:
        if b["id"] == blog["id"]:
            return b
    return {**blog, "post_count": 0}


@router.get("", response_model=list[BlogOut])
def get_blogs():
    return list_blogs(get_driver())


@router.get("/{blog_id}", response_model=BlogOut)
def get_blog_detail(blog_id: str):
    b = get_blog(get_driver(), blog_id)
    if not b:
        raise HTTPException(404, "Blog not found")
    return {**b, "post_count": 0}


@router.delete("/{blog_id}", status_code=204)
def remove_blog(blog_id: str):
    if not delete_blog(get_driver(), blog_id):
        raise HTTPException(404, "Blog not found")


# ── Post fetching (refresh from RSS) ──────────────────────────────────────────

@router.post("/{blog_id}/fetch")
def fetch_new_posts(blog_id: str):
    """Re-fetch RSS feed and add new post stubs. Returns count of new posts."""
    driver = get_driver()
    blog = get_blog(driver, blog_id)
    if not blog:
        raise HTTPException(404, "Blog not found")

    try:
        posts = fetch_feed_posts(blog["feed_url"], blog["parser"])
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch feed: {exc}")

    new_count = 0
    for p in posts:
        result = create_or_update_post(driver, blog_id, p)
        if result.get("created_at") == result.get("updated_at"):
            new_count += 1

    return {"new_posts": new_count, "total_fetched": len(posts)}


# ── Post listing ───────────────────────────────────────────────────────────────

@router.get("/{blog_id}/posts", response_model=list[BlogPostOut])
def get_blog_posts(
    blog_id: str,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
):
    return list_blog_posts(get_driver(), blog_id, status, skip, limit)


@router.get("/posts/random", response_model=BlogPostOut)
def get_random_post(status: str = "unread"):
    """Return a random imported post, optionally filtered by reading_status."""
    driver = get_driver()
    post = random_post(driver, reading_status=status if status != "any" else None)
    if not post:
        # Try without status filter
        post = random_post(driver, reading_status=None)
    if not post:
        raise HTTPException(404, "No blog posts found")

    # Auto-import if not yet done (e.g. Jekyll posts)
    if not post.get("imported") and post.get("url"):
        blog = get_blog(driver, post["blog_id"])
        if blog:
            try:
                extras = fetch_post_extras(post["url"], blog["parser"])
                post = update_post(driver, post["id"], extras)
            except Exception as exc:
                log.warning("Auto-import failed for post %s: %s", post["id"], exc)

    return post


# ── Single post operations ─────────────────────────────────────────────────────

@router.get("/posts/{post_id}", response_model=BlogPostOut)
def get_post_detail(post_id: str):
    driver = get_driver()
    post = get_post(driver, post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    # Auto-import if not yet done
    if not post.get("imported") and post.get("url"):
        with driver.session() as session:
            blog_rec = session.run(
                "MATCH (bp:BlogPost {id: $id})-[:FROM_BLOG]->(b:Blog) RETURN b",
                id=post_id,
            ).single()
        if blog_rec:
            blog = dict(blog_rec["b"])
            try:
                extras = fetch_post_extras(post["url"], blog["parser"])
                post = update_post(driver, post_id, extras)
            except Exception as exc:
                log.warning("Auto-import failed for post %s: %s", post_id, exc)

    return post


@router.patch("/posts/{post_id}", response_model=BlogPostOut)
def patch_post(post_id: str, body: BlogPostUpdate):
    driver = get_driver()
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = update_post(driver, post_id, data)
    if not updated:
        raise HTTPException(404, "Post not found")
    return updated


@router.delete("/posts/{post_id}", status_code=204)
def remove_post(post_id: str):
    if not delete_post(get_driver(), post_id):
        raise HTTPException(404, "Post not found")


@router.post("/posts/{post_id}/import")
def import_post_content(post_id: str):
    """Fetch and store full content for a single post (used for Jekyll posts)."""
    driver = get_driver()
    post = get_post(driver, post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    with driver.session() as session:
        blog_rec = session.run(
            "MATCH (bp:BlogPost {id: $id})-[:FROM_BLOG]->(b:Blog) RETURN b",
            id=post_id,
        ).single()
    if not blog_rec:
        raise HTTPException(404, "Blog not found for this post")

    blog = dict(blog_rec["b"])
    try:
        extras = fetch_post_extras(post["url"], blog["parser"])
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch post content: {exc}")

    updated = update_post(driver, post_id, extras)
    content = extras.get("content", "")
    return {"imported": True, "content_length": len(content), "post": updated}


# ── AI summarize ───────────────────────────────────────────────────────────────

@router.post("/posts/{post_id}/summarize")
def summarize_post(post_id: str):
    driver = get_driver()
    post = get_post(driver, post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    content = post.get("content", "")
    if not content:
        raise HTTPException(422, "Post has no content yet. Import it first.")

    try:
        summary = summarize_blog_post(content, post.get("title", ""))
    except Exception as exc:
        raise HTTPException(502, f"AI summarization failed: {exc}")

    updated = update_post(driver, post_id, {"summary": summary})
    return {"summary": summary, "post": updated}


# ── AI chat ────────────────────────────────────────────────────────────────────

@router.post("/posts/{post_id}/chat")
def chat_post(post_id: str, body: BlogPostChatRequest):
    driver = get_driver()
    post = get_post(driver, post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    content = post.get("content", "")
    if not content:
        raise HTTPException(422, "Post has no content yet. Import it first.")

    history = [{"role": m.role, "content": m.content} for m in body.history]
    try:
        answer = chat_with_blog_post(content, post.get("title", ""), body.question, history)
    except Exception as exc:
        raise HTTPException(502, f"AI chat failed: {exc}")

    return {"answer": answer}


# ── Batch re-import (populate figures/refs/markdown for existing posts) ────────

@router.post("/{blog_id}/reimport-all")
def reimport_all_posts(blog_id: str):
    """
    Re-fetch full content + figures + references for all posts of a blog.
    Safe to call multiple times — just updates fields, never creates duplicates.
    For Substack/WordPress this re-parses the RSS (no extra HTTP per post).
    For Jekyll/Google Research it fetches each post page.
    """
    driver = get_driver()
    blog = get_blog(driver, blog_id)
    if not blog:
        raise HTTPException(404, "Blog not found")

    # Re-fetch RSS first (handles Substack/WordPress inline content)
    try:
        posts_from_feed = fetch_feed_posts(blog["feed_url"], blog["parser"])
        for p in posts_from_feed:
            create_or_update_post(driver, blog_id, p)
    except Exception as exc:
        log.warning("RSS re-fetch failed for blog %s: %s", blog_id, exc)

    # For parsers that need page fetch, import posts that still lack figures
    page_fetch_parsers = {"jekyll", "google_research", "generic"}
    updated = 0
    errors = 0
    if blog["parser"] in page_fetch_parsers:
        posts = list_blog_posts(driver, blog_id, skip=0, limit=200)
        for post_stub in posts:
            post = get_post(driver, post_stub["id"])
            if not post or (post.get("figures") and post.get("references_json")):
                continue
            try:
                extras = fetch_post_extras(post["url"], blog["parser"])
                update_post(driver, post["id"], extras)
                updated += 1
            except Exception as exc:
                log.warning("Re-import failed for post %s: %s", post["id"], exc)
                errors += 1

    return {"updated": updated, "errors": errors}


# ── Tags ───────────────────────────────────────────────────────────────────────

@router.get("/posts/{post_id}/tags")
def get_post_tags(post_id: str):
    return get_tags_for_post(get_driver(), post_id)


@router.post("/posts/{post_id}/tags/{tag_name}", status_code=201)
def add_tag(post_id: str, tag_name: str):
    if not get_post(get_driver(), post_id):
        raise HTTPException(404, "Post not found")
    return tag_post(get_driver(), post_id, tag_name)


@router.delete("/posts/{post_id}/tags/{tag_name}", status_code=204)
def remove_tag(post_id: str, tag_name: str):
    untag_post(get_driver(), post_id, tag_name)


# ── People ─────────────────────────────────────────────────────────────────────

class PersonLinkBody(BaseModel):
    name: str
    role: str = "author"


@router.get("/posts/{post_id}/people")
def get_post_people(post_id: str):
    return get_people_for_post(get_driver(), post_id)


@router.post("/posts/{post_id}/people", status_code=201)
def link_person(post_id: str, body: PersonLinkBody):
    if not get_post(get_driver(), post_id):
        raise HTTPException(404, "Post not found")
    return link_person_to_post(get_driver(), post_id, body.name, body.role)


@router.delete("/posts/{post_id}/people/{person_id}", status_code=204)
def unlink_person(post_id: str, person_id: str):
    unlink_person_from_post(get_driver(), post_id, person_id)


# ── Projects ───────────────────────────────────────────────────────────────────

@router.get("/posts/{post_id}/projects")
def get_post_projects(post_id: str):
    return get_projects_for_post(get_driver(), post_id)


@router.post("/posts/{post_id}/projects/{project_id}", status_code=201)
def add_to_project(post_id: str, project_id: str):
    if not get_post(get_driver(), post_id):
        raise HTTPException(404, "Post not found")
    add_post_to_project(get_driver(), post_id, project_id)
    return {"ok": True}


@router.delete("/posts/{post_id}/projects/{project_id}", status_code=204)
def remove_from_project(post_id: str, project_id: str):
    remove_post_from_project(get_driver(), post_id, project_id)


# ── Notes ──────────────────────────────────────────────────────────────────────

@router.get("/posts/{post_id}/note", response_model=NoteOut)
def get_note(post_id: str):
    note = get_post_note(get_driver(), post_id)
    if not note:
        raise HTTPException(404, "No note found")
    return note


@router.put("/posts/{post_id}/note", response_model=NoteOut)
def save_note(post_id: str, body: NoteBody):
    if not get_post(get_driver(), post_id):
        raise HTTPException(404, "Post not found")
    return upsert_post_note(get_driver(), post_id, body.content)
