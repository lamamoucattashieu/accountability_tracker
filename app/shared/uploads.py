"""Image storage shared by both domains.

Callers only use save_image, delete_image and resolve_path; they never touch
Pillow or the filesystem directly. This module knows nothing about check-ins
or forfeits, and accepts any binary file-like object rather than FastAPI's
UploadFile, so it has no web-framework dependency.
"""

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import settings

# Detected Pillow format -> file extension. Supporting a new format means adding
# an entry here, not a new branch in the code.
ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


class UploadError(Exception):
    """Base class for every upload rejection."""


class InvalidImage(UploadError):
    pass


class ImageTooLarge(UploadError):
    pass


def _read_limited(fileobj) -> bytes:
    buffer = bytearray()
    while chunk := fileobj.read(CHUNK_SIZE):
        buffer.extend(chunk)
        if len(buffer) > MAX_UPLOAD_BYTES:
            raise ImageTooLarge(
                f"photo must be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            )
    return bytes(buffer)


def _detect_extension(data: bytes) -> str:
    """Identify the format from the file's content, never its name or Content-Type."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            # Image.open reads only the header, so this check runs before any
            # pixel data is decoded.
            if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                raise ImageTooLarge("photo has too many pixels")
            extension = ALLOWED_FORMATS.get(image.format)
            if extension is None:
                raise InvalidImage("photo must be a JPEG or PNG image")
            image.verify()
    except Image.DecompressionBombError:
        raise ImageTooLarge("photo has too many pixels")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise InvalidImage("photo must be a JPEG or PNG image")
    return extension


def save_image(fileobj) -> str:
    """Validate an uploaded image and store it; return its path relative to DATA_DIR.

    The size limit is enforced while reading, so nothing over MAX_UPLOAD_BYTES is
    ever written to DATA_DIR. The web framework may already have buffered the
    request body in the OS temp directory; capping the request size itself
    belongs at the ingress/reverse proxy (Assignment 2).
    """
    data = _read_limited(fileobj)
    extension = _detect_extension(data)
    # TODO(stretch): strip EXIF before saving. Stored photos keep their metadata,
    # including GPS location; only group members can fetch them.
    path = settings.uploads_dir / f"{uuid.uuid4().hex}{extension}"
    path.write_bytes(data)
    # as_posix() stores "/" separators, so the path still works in a Linux container.
    return path.relative_to(settings.data_dir).as_posix()


def resolve_path(relative_path: str) -> Path:
    """Turn a stored relative path into an absolute one inside DATA_DIR/uploads."""
    path = (settings.data_dir / relative_path).resolve()
    if not path.is_relative_to(settings.uploads_dir.resolve()):
        raise ValueError(f"path escapes the uploads directory: {relative_path}")
    return path


def delete_image(relative_path: str) -> None:
    resolve_path(relative_path).unlink(missing_ok=True)
