import logging
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

COLLECTION_NAME = "gmp_docs"


def get_chroma_client(chroma_dir: str) -> chromadb.Client:
    return chromadb.PersistentClient(path=chroma_dir)


def init_collection(
    client: chromadb.Client,
    name: str = COLLECTION_NAME,
) -> Any:
    """Delete and recreate the collection for idempotent ingestion (Decision 5)."""
    try:
        client.delete_collection(name)
        logger.info("[CHROMA] Deleted existing collection: %s", name)
    except Exception:
        pass
    collection = client.create_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),
    )
    logger.info("[CHROMA] Created collection: %s", name)
    return collection


def get_collection(
    client: chromadb.Client,
    name: str = COLLECTION_NAME,
) -> Any:
    """Get an existing collection without recreating it."""
    return client.get_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),
    )


def query_collection(
    collection: Any,
    query_string: str,
    n_results: int = 3,
) -> list[dict]:
    """Return top-n chunks as list of {text, source, distance}."""
    results = collection.query(
        query_texts=[query_string],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for text, meta, dist in zip(docs, metas, dists):
        chunks.append({
            "text": text,
            "source": meta.get("source", "unknown"),
            "distance": dist,
        })
    return chunks
