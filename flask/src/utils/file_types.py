from __future__ import annotations

from typing import Protocol


class UploadedFile(Protocol):
    """
    Protocol for file-like objects used for uploaded documents.

    This app commonly passes `io.BytesIO` objects with a dynamically attached
    `.filename` attribute (see API endpoints). Werkzeug `FileStorage` also matches.

    The protocol is intentionally minimal and focuses on the operations required by
    file-processing utilities.
    """

    filename: str

    def read(self, size: int = -1) -> bytes:
        ...

    def seek(self, offset: int, whence: int = 0) -> int:
        ...

    def tell(self) -> int:
        ...
