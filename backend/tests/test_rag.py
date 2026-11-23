"""Offline embedding and knowledge-base API tests."""

import shutil
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import AuditLog, DataSource, LandDataRule, ProcessingJob, User, Workspace, WorkspaceMembership
from app.rag.embeddings import LocalHashEmbeddings
from app.rag.indexing import KnowledgeDocumentError, chunk_document, decode_document
from app.services.ingestion import _storage_root

client = TestClient(app)


def test_document_chunking_and_offline_vectors_are_deterministic() -> None:
    text = "Parcel identifiers must remain text.\n" * 150
    chunks = chunk_document(text, chunk_size=300, overlap=40)
    assert len(chunks) > 1
    assert all(chunks)
    embedder = LocalHashEmbeddings(768)
    first = embedder.embed_query("positive land area in acres")
    assert len(first) == 768
    assert first == embedder.embed_query("positive land area in acres")
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_knowledge_document_decoder_rejects_bad_format_and_json() -> None:
    with pytest.raises(KnowledgeDocumentError, match="Supported"):
        decode_document("policy.pdf", b"not a pdf")
    with pytest.raises(KnowledgeDocumentError, match="malformed"):
        decode_document("policy.json", b"{")


def test_workspace_document_upload_list_and_pgvector_search() -> None:
    email = f"rag-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    original = b"A plot identifier must not be empty. Area must be a finite positive number and its unit must be known."
    headers: dict[str, str] = {}

    try:
        registration = client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert registration.status_code == 201, registration.text
        user_id = UUID(registration.json()["user"]["id"])
        headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        with SessionLocal() as db:
            workspace_id = db.scalar(select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user_id))
        assert workspace_id is not None

        upload = client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            data={"title": "Synthetic parcel policy", "rule_key": "synthetic-parcel-policy", "version": "1"},
            files={"file": ("synthetic_policy.md", original, "text/markdown")},
        )
        assert upload.status_code == 201, upload.text
        indexed = upload.json()
        assert indexed["chunks"] == 1
        assert indexed["embedding_provider"] == "local"
        stored_path = _storage_root().parent / "knowledge" / str(workspace_id) / f"{indexed['document_id']}.md"
        assert stored_path.read_bytes() == original

        listing = client.get("/api/v1/knowledge/documents", headers=headers)
        assert listing.status_code == 200, listing.text
        assert len(listing.json()) == 1
        assert listing.json()[0]["filename"] == "synthetic_policy.md"

        search = client.post(
            "/api/v1/knowledge/search",
            headers=headers,
            json={"query": "finite positive area and parcel identifier", "limit": 3},
        )
        assert search.status_code == 200, search.text
        result = search.json()
        assert result["provider"] == "local"
        assert result["results"]
        assert "positive number" in result["results"][0]["content"]

        duplicate = client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            data={"title": "Duplicate", "rule_key": "synthetic-parcel-policy", "version": "1"},
            files={"file": ("synthetic_policy.md", original, "text/markdown")},
        )
        assert duplicate.status_code == 409
    finally:
        if user_id is not None and workspace_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
                db.execute(delete(ProcessingJob).where(ProcessingJob.workspace_id == workspace_id))
                db.execute(delete(DataSource).where(DataSource.workspace_id == workspace_id))
                db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id))
                db.execute(delete(Workspace).where(Workspace.id == workspace_id))
                db.execute(delete(User).where(User.id == user_id))
            shutil.rmtree(_storage_root().parent / "knowledge" / str(workspace_id), ignore_errors=True)
