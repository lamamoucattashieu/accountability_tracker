"""Photo checks shared by both services.

Callers only use validate_image; they never touch Pillow directly. Photos are
stored in the service's own database now (no files), so this module only
decides whether an upload is an acceptable image and returns its bytes and
content type. It accepts any binary file-like object rather than FastAPI's
UploadFile, so it has no web-framework dependency.
"""

import io

from PIL import Image, UnidentifiedImageError

# Detected Pillow format -> the content type stored with the photo and sent back
# to the browser. Supporting a new format means adding an entry here (and to the
# photo_type CHECK in a new migration), not a new branch in the code.
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}
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


def _detect_content_type(data: bytes) -> str:
    """Identify the format from the file's content, never its name or Content-Type."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            # Image.open reads only the header, so this check runs before any
            # pixel data is decoded.
            if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                raise ImageTooLarge("photo has too many pixels")
            content_type = ALLOWED_FORMATS.get(image.format)
            if content_type is None:
                raise InvalidImage("photo must be a JPEG or PNG image")
            image.verify()
    except Image.DecompressionBombError:
        raise ImageTooLarge("photo has too many pixels")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise InvalidImage("photo must be a JPEG or PNG image")
    return content_type


def validate_image(fileobj) -> tuple[bytes, str]:
    """An uploaded image's bytes and content type, or an UploadError.

    The size limit is enforced while reading, so nothing over MAX_UPLOAD_BYTES
    is ever held in memory as a photo. The web framework may already have
    buffered the request body; capping the request size itself belongs at the
    ingress.
    """
    data = _read_limited(fileobj)
    # TODO(stretch): strip EXIF. Stored photos keep their metadata, including GPS
    # location; only group members can fetch them.
    return data, _detect_content_type(data)
