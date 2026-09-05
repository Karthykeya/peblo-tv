import os
from pathlib import Path
from typing import Protocol


class StorageBackend(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> str:
        """Writes data under `key`, returns a URL/path to access it."""
        ...

    def read(self, key: str) -> bytes:
        """Reads back the bytes stored under `key`."""
        ...

    def delete(self, key: str) -> None:
        """Deletes the object stored under `key`, if it exists."""
        ...


class LocalDiskStorage:
    """
    Local filesystem implementation of StorageBackend.
    Everything above this layer (endpoints, the publish job) only ever
    calls save/read/delete — never touches the filesystem directly.
    Swapping to R2/S3 means writing one new class implementing the same
    three methods against the S3-compatible API (R2 is S3-compatible);
    nothing else in the codebase changes.
    """

    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or os.environ.get("STORAGE_PATH", "./storage"))
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes, content_type: str = "") -> str:
        full_path = self.base_path / key
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return f"/static/{key}"

    def read(self, key: str) -> bytes:
        full_path = self.base_path / key
        return full_path.read_bytes()

    def delete(self, key: str) -> None:
        full_path = self.base_path / key
        if full_path.exists():
            full_path.unlink()


# module-level singleton used across the app
storage: StorageBackend = LocalDiskStorage()