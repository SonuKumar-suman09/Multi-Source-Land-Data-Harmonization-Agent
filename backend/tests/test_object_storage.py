"""Storage adapter tests use only temporary disk and a mocked S3-compatible client."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services import object_storage


def test_local_storage_round_trips_exact_original_bytes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    original = b"plot_id,owner_name\nSYN-1,Synthetic Owner\n"

    stored_path = object_storage.store_original("workspace-1/source.csv", original, "text/csv")

    assert stored_path is not None
    assert stored_path.read_bytes() == original
    object_storage.delete_original("workspace-1/source.csv")
    assert not stored_path.exists()


def test_minio_storage_creates_bucket_and_preserves_bytes(monkeypatch) -> None:
    client = MagicMock()
    client.bucket_exists.return_value = False
    monkeypatch.setattr(settings, "storage_backend", "minio")
    monkeypatch.setattr(settings, "minio_bucket", "land-source-files")
    monkeypatch.setattr(object_storage, "_minio_client", lambda: client)
    original = b"unchanged synthetic source"

    assert object_storage.store_original("workspace-1/file.csv", original, "text/csv") is None

    client.make_bucket.assert_called_once_with("land-source-files")
    args, kwargs = client.put_object.call_args
    assert args[:2] == ("land-source-files", "workspace-1/file.csv")
    assert isinstance(args[2], BytesIO)
    assert args[2].read() == original
    assert args[3] == len(original)
    assert kwargs["content_type"] == "text/csv"

    object_storage.delete_original("workspace-1/file.csv")
    client.remove_object.assert_called_once_with("land-source-files", "workspace-1/file.csv")


def test_object_storage_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="Unsafe object key"):
        object_storage.store_original("workspace/../private.csv", b"source")
    with pytest.raises(ValueError, match="Unsafe object key"):
        object_storage.store_original(r"workspace\..\private.csv", b"source")
