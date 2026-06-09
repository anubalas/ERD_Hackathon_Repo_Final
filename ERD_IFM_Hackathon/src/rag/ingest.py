"""RAG ingestion script: chunk GMP .txt files and store in ChromaDB.

Usage:
    python -m src.rag.ingest
    python -m src.rag.ingest --docs-dir docs/gmp/ --chroma-dir ./chroma_db
"""
import argparse
import logging
import os
import sys
from pathlib import Path

from src.rag.chroma_store import get_chroma_client, init_collection

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def chunk_document(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into fixed-size chunks with overlap (Decision 4)."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def ingest_docs(
    docs_dir: str,
    chroma_dir: str,
    collection_name: str = "gmp_docs",
    chunk_size: int = 500,
    overlap: int = 50,
) -> int:
    """Ingest all .txt files from docs_dir into ChromaDB. Returns total chunk count."""
    docs_path = Path(docs_dir)
    txt_files = sorted(docs_path.glob("*.txt"))

    if not txt_files:
        logger.error("[ERROR] No .txt files found in %s — ingestion aborted", docs_dir)
        sys.exit(2)

    client = get_chroma_client(chroma_dir)
    collection = init_collection(client, collection_name)

    total_chunks = 0
    all_documents: list[str] = []
    all_ids: list[str] = []
    all_metadatas: list[dict] = []

    for txt_file in txt_files:
        text = txt_file.read_text(encoding="utf-8")
        chunks = chunk_document(text, chunk_size=chunk_size, overlap=overlap)
        for i, chunk in enumerate(chunks):
            all_documents.append(chunk)
            all_ids.append(f"{txt_file.name}::chunk{i}")
            all_metadatas.append({"source": txt_file.name})
        logger.info(
            "[INGEST] Processing %-30s — %d chunks", txt_file.name, len(chunks)
        )
        total_chunks += len(chunks)

    collection.add(
        documents=all_documents,
        ids=all_ids,
        metadatas=all_metadatas,
    )
    logger.info(
        "[INGEST] Complete. %d documents, %d chunks stored in %s.",
        len(txt_files),
        total_chunks,
        collection_name,
    )
    return total_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest GMP SOP docs into ChromaDB")
    parser.add_argument(
        "--docs-dir",
        default=os.getenv("GMP_DOCS_DIR", "docs/gmp/"),
        help="Directory containing .txt SOP files (default: docs/gmp/)",
    )
    parser.add_argument(
        "--chroma-dir",
        default=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"),
        help="ChromaDB persistence directory (default: ./chroma_db)",
    )
    parser.add_argument(
        "--collection",
        default="gmp_docs",
        help="ChromaDB collection name (default: gmp_docs)",
    )
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    args = parser.parse_args()

    if not Path(args.docs_dir).is_dir():
        logger.error("[ERROR] docs-dir not found: %s", args.docs_dir)
        sys.exit(1)

    ingest_docs(
        docs_dir=args.docs_dir,
        chroma_dir=args.chroma_dir,
        collection_name=args.collection,
        chunk_size=args.chunk_size,
        overlap=args.chunk_overlap,
    )


if __name__ == "__main__":
    main()
