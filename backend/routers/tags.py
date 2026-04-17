import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from db.connection import get_driver
from db.queries.tags import get_or_create_tag, tag_paper, untag_paper, list_tags, papers_by_tag
from models.schemas import TagBody, PaperOut

log = logging.getLogger(__name__)
tags_router = APIRouter(prefix="/tags", tags=["tags"])
papers_router = APIRouter(prefix="/papers", tags=["tags"])

DEFAULT_TAGS = [
    # ── Source / ingestion method (applied automatically) ─────────────────────
    "pdf-upload", "from-url", "from-references",

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
    """Use Ollama to suggest relevant tags for a paper based on title + abstract."""
    driver = get_driver()
    existing_tags = [t["name"] for t in list_tags(driver)]

    if not body.abstract and not body.title:
        raise HTTPException(status_code=400, detail="Title or abstract required")

    try:
        import ollama
        from config import settings

        abstract_block = f"Abstract:\n{body.abstract}" if body.abstract else "(no abstract available)"
        tag_list = ", ".join(existing_tags)

        prompt = f"""You are helping organise academic papers in a personal research library.

Available tags in this library:
{tag_list}

Paper to tag:
Title: {body.title}
{abstract_block}

Task:
1. From the available tags above, pick the 3–6 most relevant ones for this paper.
2. If there are important concepts not covered by any existing tag, suggest up to 2 short new tag names (lowercase, hyphen-separated, max 20 chars each).

Return ONLY valid JSON with exactly these two keys:
  "existing": [list of chosen tags from the available list]
  "new": [list of brand-new tag names, or empty list]

No explanation, no markdown fences, just JSON."""

        response = ollama.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        import json
        raw = json.loads(response["message"]["content"])
        # Sanitise: only return tags that actually exist in the library
        valid_existing = [t for t in (raw.get("existing") or []) if t in existing_tags]
        new_tags = [t.lower().replace(" ", "-")[:20] for t in (raw.get("new") or [])]
        return {"existing": valid_existing, "new": new_tags, "all_tags": existing_tags}
    except Exception as e:
        log.warning("Tag suggestion failed | %s", e)
        # Return all tags so the user can still manually select
        return {"existing": [], "new": [], "all_tags": existing_tags}


@tags_router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(name: str):
    with get_driver().session() as session:
        session.run("MATCH (t:Tag {name: $name}) DETACH DELETE t", name=name)


@papers_router.post("/{paper_id}/tags", status_code=201)
def add_tag(paper_id: str, body: TagBody):
    tag = tag_paper(get_driver(), paper_id, body.name)
    return {"paper_id": paper_id, "tag": tag}


@papers_router.delete("/{paper_id}/tags/{name}", status_code=204)
def remove_tag(paper_id: str, name: str):
    untag_paper(get_driver(), paper_id, name)
