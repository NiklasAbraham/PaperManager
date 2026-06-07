import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from db.connection import get_driver
from db.queries.tags import get_or_create_tag, tag_paper, untag_paper, list_tags, delete_tag, papers_by_tag, get_tags_for_paper
from models.schemas import TagBody, PaperOut

log = logging.getLogger(__name__)
tags_router = APIRouter(prefix="/tags", tags=["tags"])
papers_router = APIRouter(prefix="/papers", tags=["tags"])

DEFAULT_TAGS = [
    # ── Source / ingestion method (applied automatically) ─────────────────────
    "pdf-upload", "from-url", "from-references", "bulk-import", "debug",
    "from-linkedin", "from-twitter", "from-email",
    "from-conference", "from-newsletter", "from-google-scholar",
    "from-google", "from-ai-chat", "from-arxiv",

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


@tags_router.delete("/{name}", status_code=204)
def remove_tag(name: str):
    """Delete a tag and detach it from all papers/people."""
    delete_tag(get_driver(), name)


@tags_router.get("/{name}/papers", response_model=list[PaperOut])
def papers(name: str):
    return papers_by_tag(get_driver(), name)


@tags_router.post("/suggest")
def suggest_tags(body: SuggestBody):
    """Suggest relevant tags using Gemma/LiteLLM (falls back to Claude Work)."""
    from services.tag_suggester import suggest_tags_litellm

    driver = get_driver()
    existing_tags = [t["name"] for t in list_tags(driver)]

    if not body.abstract and not body.title:
        raise HTTPException(status_code=400, detail="Title or abstract required")

    # ── Strategy A: LiteLLM / Gemma (primary) ────────────────────────────────
    result = suggest_tags_litellm(body.title, body.abstract, existing_tags)
    if result is not None:
        return result

    # ── Strategy B: Claude Work (Palantir gateway) ───────────────────────────
    import json as _json
    from config import settings as _settings
    import anthropic, httpx
    from services.tag_suggester import build_prompt, parse_response, _SKIP
    from services.user_ai_config import get_effective_ai_config

    candidate_tags = [t for t in existing_tags if t not in _SKIP]
    prompt = build_prompt(body.title, body.abstract, candidate_tags)
    _ssl = False if not _settings.ssl_verify else (_settings.ssl_ca_bundle or True)
    ai_cfg = get_effective_ai_config()
    work_key = (ai_cfg.get("anthropic_work_api_key") or "").strip()
    work_base = (ai_cfg.get("anthropic_work_base_url") or "").strip()
    if work_key:
        try:
            kwargs: dict = {
                "api_key": work_key,
                "http_client": httpx.Client(verify=_ssl),
            }
            if work_base:
                kwargs["base_url"] = work_base
            client = anthropic.Anthropic(**kwargs)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            valid_existing, new_tags = parse_response(resp.content[0].text, existing_tags)
            log.debug("Tag suggestion via Claude Work | existing=%d new=%d", len(valid_existing), len(new_tags))
            return {"existing": valid_existing, "new": new_tags, "all_tags": existing_tags}
        except Exception as e:
            log.warning("Claude Work tag suggestion failed | %s", e)

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
