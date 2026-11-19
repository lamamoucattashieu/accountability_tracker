import io

from PIL import Image


def image_bytes(image_format="JPEG", size=(10, 10)) -> bytes:
    """Encode a small solid-colour image in memory."""
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=image_format)
    return buffer.getvalue()


def image_file(image_format="JPEG", size=(10, 10)) -> io.BytesIO:
    return io.BytesIO(image_bytes(image_format, size))
