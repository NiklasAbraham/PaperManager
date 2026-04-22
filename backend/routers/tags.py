import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from db.connection import get_driver
from db.queries.tags import get_or_create_tag, tag_paper, untag_paper, list_tags, papers_by_tag, get_tags_for_paper
from models.schemas import TagBody, PaperOut

log = logging.getLogger(__name__)
tags_router = APIRouter(prefix="/tags", tags=["tags"])
papers_router = APIRouter(prefix="/papers", tags=["tags"])

DEFAULT_TAGS = [
    # ── Source / ingestion method (applied automatically) ─────────────────────
    "pdf-upload", "from-url", "from-references", "bulk-import", "debug",
    "from-linkedin", "from-twitter", "from-email",
    "from-conference", "from-newsletter", "from-google-scholar",

    # ── Workflow & personal status ─────────────────────────────────────────────
    "to-read", "reading", "read", "important", "revisit",
    "needs-review", "relevant", "in-bibliography",
    "from-colleague", "reproduced", "code-available",

    # ── Content type & paper class ─────────────────────────────────────────────
    "review", "benchmark", "dataset", "method", "theory",
    "negative-result", "foundational", "highly-cited", "sota",

    # ── Mathematics ───────────────────────────────────────────────────────────
    "algebra",
    "topology",
    "differential-geometry",
    "real-analysis",
    "probability-theory",
    "statistics",
    "linear-algebra",
    "numerical-methods",
    "optimization",
    "convex-optimization",
    "stochastic-processes",
    "measure-theory",
    "graph-theory",
    "combinatorics",
    "information-theory",

    # ── Machine Learning & AI ─────────────────────────────────────────────────
    "machine-learning",
    "deep-learning",
    "supervised-learning",
    "unsupervised-learning",
    "self-supervised",
    "reinforcement-learning",
    "meta-learning",
    "transfer-learning",
    "federated-learning",
    "contrastive-learning",
    "representation-learning",
    "generative-models",
    "diffusion-models",
    "flow-matching",
    "normalizing-flows",
    "variational-autoencoder",
    "gan",
    "transformers",
    "attention-mechanism",
    "large-language-models",
    "llm",
    "multimodal",
    "computer-vision",
    "nlp",
    "graph-neural-networks",
    "neural-arch-search",
    "bayesian-inference",
    "variational-inference",
    "gaussian-processes",
    "uncertainty-quantification",
    "active-learning",
    "multi-task-learning",

    # ── Physics & Simulation ──────────────────────────────────────────────────
    "statistical-mechanics",
    "thermodynamics",
    "quantum-mechanics",
    "quantum-chemistry",
    "molecular-dynamics",
    "monte-carlo",
    "force-fields",
    "free-energy-calculation",
    "enhanced-sampling",
    "biophysics",
    "coarse-graining",

    # ── Structural & Computational Biology ───────────────────────────────────
    "protein-structure",
    "protein-folding",
    "protein-design",
    "protein-function",
    "structure-prediction",
    "alphafold",
    "protein-language-model",
    "protein-protein-interaction",
    "binding-affinity",
    "allosteric-regulation",
    "sequence-alignment",
    "homology-modeling",
    "evolutionary-biology",
    "phylogenetics",
    "genomics",
    "transcriptomics",
    "proteomics",
    "metabolomics",
    "single-cell",
    "scrna-seq",
    "crispr",
    "gene-expression",
    "epigenetics",
    "systems-biology",

    # ── Drug Discovery & Pharma ───────────────────────────────────────────────
    "drug-discovery",
    "drug-design",
    "structure-based-design",
    "ligand-based-design",
    "molecular-docking",
    "virtual-screening",
    "hit-identification",
    "lead-optimization",
    "admet",
    "pharmacokinetics",
    "pharmacodynamics",
    "target-identification",
    "target-validation",
    "mechanism-of-action",
    "polypharmacology",
    "clinical-trial",
    "biomarker",
    "antibody-engineering",
    "small-molecule",
    "fragment-based",
    "de-novo-design",
    "protac",
    "molecular-glue",
    "selectivity",

    # ── Cheminformatics & Molecular Design ───────────────────────────────────
    "cheminformatics",
    "molecular-representation",
    "mol-fingerprints",
    "smiles",
    "reaction-prediction",
    "retrosynthesis",
    "property-prediction",
    "toxicity-prediction",
    "solubility",
    "qsar",
    "scaffold-hopping",
    "multi-objective-opt",
    "chemical-space",
]


def seed_default_tags(driver) -> None:
    """Create default tags if they don't exist yet (idempotent)."""
    for name in DEFAULT_TAGS:
        get_or_create_tag(driver, name)
    log.info("Default tags seeded (%d tags)", len(DEFAULT_TAGS))


class SuggestBody(BaseModel):
    title: str
    abstract: str | None = None


@tags_router.get("")
def list_all():
    return list_tags(get_driver())


@tags_router.post("", status_code=status.HTTP_201_CREATED)
def create_tag(body: TagBody):
    return get_or_create_tag(get_driver(), body.name)


@tags_router.get("/{name}/papers", response_model=list[PaperOut])
def papers(name: str):
    return papers_by_tag(get_driver(), name)


@tags_router.post("/suggest")
def suggest_tags(body: SuggestBody):
    """Suggest relevant tags using Claude Haiku (falls back to Ollama)."""
    import json as _json
    from config import settings as _settings

    driver = get_driver()
    existing_tags = [t["name"] for t in list_tags(driver)]

    if not body.abstract and not body.title:
        raise HTTPException(status_code=400, detail="Title or abstract required")

    abstract_block = f"Abstract:\n{body.abstract}" if body.abstract else "(no abstract available)"
    # Exclude system/source tags from the suggestion list — not useful to suggest these
    _SKIP = {"pdf-upload", "from-url", "from-references", "bulk-import", "debug",
             "from-linkedin", "from-twitter", "from-email", "from-conference",
             "from-newsletter", "from-google-scholar", "from-colleague"}
    candidate_tags = [t for t in existing_tags if t not in _SKIP]
    tag_list = ", ".join(candidate_tags) if candidate_tags else "(none yet)"

    prompt = (
        "You are helping organise academic papers in a personal research library.\n\n"
        f"Available tags in this library:\n{tag_list}\n\n"
        f"Paper to tag:\nTitle: {body.title}\n{abstract_block}\n\n"
        "Task:\n"
        "1. From the available tags above, pick the most relevant ones for this paper (ideally 3–6).\n"
        "2. If fewer than 4 existing tags fit well, suggest additional NEW tag names (total ≥ 4).\n"
        "   New tags: lowercase, hyphen-separated, max 20 chars each.\n\n"
        'Return ONLY valid JSON with exactly two keys:\n'
        '  "existing": [list of chosen tags from the available list]\n'
        '  "new": [list of brand-new tag names, or empty list]\n\n'
        "No explanation, no markdown fences, just the JSON object."
    )

    def _parse(raw_text: str) -> tuple[list[str], list[str]]:
        text = raw_text.strip()
        # Strip markdown fences if present
        import re as _re
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
        # Extract first JSON object
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        raw = _json.loads(m.group() if m else text)
        existing_set = set(existing_tags)
        valid_existing = [t for t in (raw.get("existing") or []) if t in existing_set]
        new_tags = [
            t.lower().replace(" ", "-")[:20]
            for t in (raw.get("new") or [])
            if t and t.lower().replace(" ", "-")[:20] not in existing_set
        ]
        return valid_existing, new_tags

    # ── Strategy A: Claude Haiku ──────────────────────────────────────────────
    if _settings.anthropic_api_key:
        try:
            import anthropic, httpx
            _BASE = "https://api.anthropic.com"
            _ssl = False if not _settings.ssl_verify else (_settings.ssl_ca_bundle or True)
            client = anthropic.Anthropic(
                api_key=_settings.anthropic_api_key,
                base_url=_BASE,
                http_client=httpx.Client(verify=_ssl),
            )
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            valid_existing, new_tags = _parse(resp.content[0].text)
            log.debug("Tag suggestion via Claude | existing=%d new=%d", len(valid_existing), len(new_tags))
            return {"existing": valid_existing, "new": new_tags, "all_tags": existing_tags}
        except Exception as e:
            log.warning("Claude tag suggestion failed, trying Ollama | %s", e)

    # ── Strategy B: Ollama fallback ───────────────────────────────────────────
    try:
        import ollama
        response = ollama.chat(
            model=_settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        valid_existing, new_tags = _parse(response["message"]["content"])
        log.debug("Tag suggestion via Ollama | existing=%d new=%d", len(valid_existing), len(new_tags))
        return {"existing": valid_existing, "new": new_tags, "all_tags": existing_tags}
    except Exception as e:
        log.warning("Tag suggestion failed entirely | %s", e)
        return {"existing": [], "new": [], "all_tags": existing_tags}


@tags_router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(name: str):
    with get_driver().session() as session:
        session.run("MATCH (t:Tag {name: $name}) DETACH DELETE t", name=name)


@papers_router.get("/{paper_id}/tags")
def list_paper_tags(paper_id: str):
    return get_tags_for_paper(get_driver(), paper_id)


@papers_router.post("/{paper_id}/tags", status_code=201)
def add_tag(paper_id: str, body: TagBody):
    tag = tag_paper(get_driver(), paper_id, body.name)
    return {"paper_id": paper_id, "tag": tag}


@papers_router.delete("/{paper_id}/tags/{name}", status_code=204)
def remove_tag(paper_id: str, name: str):
    untag_paper(get_driver(), paper_id, name)
