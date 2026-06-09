"""Unit tests for RAG ingestion pipeline (SC-006)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.rag.ingest import chunk_document, ingest_docs


class TestChunkDocument:
    def test_single_chunk_short_text(self):
        text = "A" * 300
        chunks = chunk_document(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_count_with_overlap(self):
        # 1000 chars, chunk=500, overlap=50 → stride=450 → 3 chunks
        # chunk1: 0–500, chunk2: 450–950, chunk3: 900–1000
        text = "X" * 1000
        chunks = chunk_document(text, chunk_size=500, overlap=50)
        assert len(chunks) == 3

    def test_overlap_content(self):
        text = "ABCDE" * 200  # 1000 chars
        chunks = chunk_document(text, chunk_size=100, overlap=20)
        # Last 20 chars of chunk[0] == first 20 chars of chunk[1]
        assert chunks[0][-20:] == chunks[1][:20]

    def test_empty_text_returns_empty_list(self):
        chunks = chunk_document("", chunk_size=500, overlap=50)
        assert chunks == []


class TestQueryCollection:
    def test_returns_three_results_with_source(self):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["chunk text 1", "chunk text 2", "chunk text 3"]],
            "metadatas": [
                [{"source": "boiler_sop.txt"}, {"source": "haccp_general.txt"}, {"source": "boiler_sop.txt"}]
            ],
            "distances": [[0.1, 0.2, 0.3]],
        }

        from src.rag.chroma_store import query_collection
        results = query_collection(mock_collection, "boiler temperature deviation", n_results=3)

        assert len(results) == 3
        assert all("source" in r for r in results)
        assert results[0]["source"] == "boiler_sop.txt"
        assert results[0]["text"] == "chunk text 1"
        assert results[0]["distance"] == pytest.approx(0.1)

    def test_source_key_present_on_all_results(self):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["a", "b"]],
            "metadatas": [[{"source": "dryer_sop.txt"}, {"source": "haccp_general.txt"}]],
            "distances": [[0.05, 0.15]],
        }
        from src.rag.chroma_store import query_collection
        results = query_collection(mock_collection, "dryer humidity", n_results=2)
        assert all("source" in r for r in results)


class TestIngestDocs:
    def test_idempotent_reingest_calls_delete_then_create(self, tmp_path):
        (tmp_path / "test.txt").write_text("some SOP content here " * 20)

        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.create_collection.return_value = mock_collection

        with patch("src.rag.ingest.get_chroma_client", return_value=mock_client), \
             patch("src.rag.ingest.init_collection", return_value=mock_collection) as mock_init:
            ingest_docs(str(tmp_path), "./chroma_db")
            mock_init.assert_called_once_with(mock_client, "gmp_docs")

    def test_empty_docs_dir_exits_nonzero(self, tmp_path):
        with patch("src.rag.ingest.get_chroma_client"):
            with pytest.raises(SystemExit) as exc_info:
                ingest_docs(str(tmp_path), "./chroma_db")
            assert exc_info.value.code != 0

    def test_chunk_count_returned(self, tmp_path):
        (tmp_path / "sop.txt").write_text("A" * 1000)
        mock_collection = MagicMock()
        with patch("src.rag.ingest.get_chroma_client"), \
             patch("src.rag.ingest.init_collection", return_value=mock_collection):
            total = ingest_docs(str(tmp_path), "./chroma_db", chunk_size=500, overlap=50)
        assert total == 3  # stride=450, so 3 chunks for 1000 chars

    def test_source_metadata_set_to_filename(self, tmp_path):
        (tmp_path / "boiler_sop.txt").write_text("B" * 600)
        mock_collection = MagicMock()
        with patch("src.rag.ingest.get_chroma_client"), \
             patch("src.rag.ingest.init_collection", return_value=mock_collection):
            ingest_docs(str(tmp_path), "./chroma_db", chunk_size=500, overlap=50)

        add_call = mock_collection.add.call_args
        metadatas = add_call[1]["metadatas"] if add_call[1] else add_call[0][2]
        assert all(m["source"] == "boiler_sop.txt" for m in metadatas)
