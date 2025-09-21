import json
import sys
from typing import Optional

import faiss
import numpy as np

from app.core.logging import get_logger
from app.db.redis_client import redis_client

logger = get_logger(__name__)

EMBEDDING_DIM: int | None = None
vector_index: faiss.Index | None = None
vector_emails: list[str] = []


def _propagate_to_main(name: str, value) -> None:
    module = sys.modules.get("app.main")
    if module is not None:
        setattr(module, name, value)

def ensure_index(dim: int) -> None:
    """Ensure the FAISS index exists with the correct dimension."""
    global EMBEDDING_DIM, vector_index
    if EMBEDDING_DIM != dim:
        EMBEDDING_DIM = dim
        vector_index = faiss.IndexFlatIP(dim)
        vector_emails.clear()
        _propagate_to_main("vector_emails", vector_emails)
    if vector_index is None:
        vector_index = faiss.IndexFlatIP(dim)
    _propagate_to_main("EMBEDDING_DIM", EMBEDDING_DIM)
    _propagate_to_main("vector_index", vector_index)

def rebuild_vector_index() -> None:
    """Populate the FAISS index with existing student embeddings."""
    global vector_index, vector_emails
    vector_emails = []
    _propagate_to_main("vector_emails", vector_emails)
    if EMBEDDING_DIM is None:
        _propagate_to_main("vector_index", vector_index)
        return
    vector_index = faiss.IndexFlatIP(EMBEDDING_DIM)
    _propagate_to_main("vector_index", vector_index)
    for key in redis_client.scan_iter("student:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            student = json.loads(raw)
            emb = student.get("embedding")
            if emb:
                ensure_index(len(emb))
                if vector_index is not None:
                    vector_index.add(np.array([emb], dtype="float32"))
                    vector_emails.append(student.get("email"))
        except Exception:
            continue

