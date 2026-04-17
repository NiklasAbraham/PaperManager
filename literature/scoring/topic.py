import pandas as pd

from sentence_transformers import SentenceTransformer


def score(data):
    # Load the model
    model = SentenceTransformer(
        "NovaSearch/stella_en_400M_v5", trust_remote_code=True, device="mps",
        config_kwargs={
            "use_memory_efficient_attention": False,
            "unpad_inputs": False
        }
    )
    # Define and embed the target topic query
    query_embeddings = model.encode([
       'Articles describing new machine learning methods for protein design or for analysis/prediction of protein properties or articles describing the application of such methods.'
        ], prompt_name="s2p_query"
    )
    # Embed description (title, abstract) of each paper
    doc_embeddings = model.encode(
        data.apply(lambda x: f'Title: {x.title}. Abstract: {x.abstract}',
                   axis=1).to_list()
    )

    # How well each paper corresponds to the topic query
    similarities = pd.Series(
        model.similarity(query_embeddings, doc_embeddings).numpy().ravel(),
        index=data.index
    )

    return similarities
