"""Users router — identity, attribution, and cross-user conversation search."""
from __future__ import annotations
import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from db.connection import get_driver
from db.queries.users import get_or_create_user, list_users, get_user_conversations_for_ask, delete_user, rename_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


class IdentifyBody(BaseModel):
    name: str


class AskBody(BaseModel):
    question: str


class RenameBody(BaseModel):
    name: str


@router.get("")
def get_users():
    return list_users(get_driver())


@router.post("/identify")
def identify(body: IdentifyBody):
    """Get or create a user by name. Called on app load to register the current user."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Name cannot be empty")
    return get_or_create_user(get_driver(), body.name.strip())


@router.delete("/{name}", status_code=204)
def remove_user(name: str):
    """Delete a user and all their graph relationships."""
    delete_user(get_driver(), name)


@router.patch("/{name}")
def update_user(name: str, body: RenameBody):
    """Rename a user."""
    new_name = body.name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="Name cannot be empty")
    updated = rename_user(get_driver(), name, new_name)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.post("/{name}/ask")
def ask_user(name: str, body: AskBody):
    """
    Ask Claude what a specific user has been thinking about a topic,
    based on their conversation history.
    """
    from services.ai import _personal_client
    import anthropic

    messages = get_user_conversations_for_ask(get_driver(), name)
    if not messages:
        return {"answer": f"{name} has no recorded conversations yet.", "message_count": 0}

    # Build a readable digest of the user's conversation history
    lines = []
    for m in messages:
        role = m["role"]
        if role not in ("user", "assistant"):
            continue
        paper_ctx = f" [re: {m['paper_title']}]" if m.get("paper_title") else ""
        conv_ctx = f" [conversation: {m['conv_title']}]" if m.get("conv_title") else ""
        lines.append(f"[{role.upper()}{paper_ctx}{conv_ctx}] {m['content']}")

    history_text = "\n\n".join(lines)

    system_prompt = (
        f"You are a research assistant helping a team understand each member's thinking. "
        f"Below are conversation messages from {name}'s research sessions. "
        f"Answer the user's question about {name}'s thinking based solely on this evidence. "
        f"Quote or reference specific things {name} said where relevant. "
        f"If the evidence doesn't address the question, say so honestly."
    )

    user_prompt = (
        f"Based on {name}'s conversations below, answer this question:\n\n"
        f"{body.question}\n\n"
        f"---\n{history_text}"
    )

    try:
        from services.litellm_client import chat_completion

        answer = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
        )
    except Exception as exc:
        log.error("Ask-user LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI call failed: {exc}")

    return {"answer": answer, "message_count": len(messages)}
