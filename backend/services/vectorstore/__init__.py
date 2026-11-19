"""One vector store for every embedding index of PaperManager. Spec: .specs/019_vector_store.md.

    from services.vectorstore import get_store, model_config
    store = get_store("library")                       # opened (and created) on first use
    if store.is_stale():                               # built with another embedding model
        ...                                            # rebuild with store.begin_rebuild()
    hits = store.search(query_vector, k=10, filter={"kind": "paper"})   # [(id, cosine, metadata)]
"""
from services.vectorstore.base import (FILTER_FIELDS, BackendUnavailableError, GenerationalStore, Hit, Manifest,
                                       Rebuild, StaleStoreError, StoreDamagedError, StoreLockedError, VectorStore,
                                       VectorStoreError, compile_filter)
from services.vectorstore.model_config import ModelConfigError, ModelSpec, current as current_model
from services.vectorstore.registry import ExactStore, LanceStore, backend_name, get_store, reset, vector_dir

__all__ = [
    "FILTER_FIELDS", "BackendUnavailableError", "ExactStore", "GenerationalStore", "Hit", "LanceStore", "Manifest",
    "ModelConfigError", "ModelSpec", "Rebuild", "StaleStoreError", "StoreDamagedError", "StoreLockedError",
    "VectorStore", "VectorStoreError", "backend_name", "compile_filter", "current_model", "get_store", "reset",
    "vector_dir",
]
