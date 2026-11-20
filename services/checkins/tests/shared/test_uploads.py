import io
import os

import pytest
from PIL import Image

from app.shared import uploads
from tests.images import image_bytes, image_file


@pytest.mark.parametrize("image_format, content_type", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
def test_valid_image_gives_its_bytes_and_content_type(image_format, content_type):
    assert uploads.validate_image(image_file(image_format)) == (image_bytes(image_format), content_type)


def test_random_bytes_are_rejected():
    with pytest.raises(uploads.InvalidImage):
        uploads.validate_image(io.BytesIO(os.urandom(1024)))


def test_text_file_named_jpg_is_rejected():
    fake = io.BytesIO(b"definitely not a photo")
    fake.name = "proof.jpg"
    with pytest.raises(uploads.InvalidImage):
        uploads.validate_image(fake)


def test_other_image_formats_are_rejected():
    with pytest.raises(uploads.InvalidImage):
        uploads.validate_image(image_file("GIF"))


def test_truncated_image_is_rejected():
    with pytest.raises(uploads.InvalidImage):
        uploads.validate_image(io.BytesIO(image_bytes("PNG")[:40]))


def test_file_over_limit_is_rejected():
    too_big = image_bytes("PNG") + b"\0" * uploads.MAX_UPLOAD_BYTES
    with pytest.raises(uploads.ImageTooLarge):
        uploads.validate_image(io.BytesIO(too_big))


def test_file_exactly_at_limit_is_not_rejected_for_size(monkeypatch):
    data = image_bytes("PNG")
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", len(data))
    assert uploads.validate_image(io.BytesIO(data))[1] == "image/png"


def test_too_many_pixels_is_rejected(monkeypatch):
    # 20x20 = 400 pixels: above our limit, below Pillow's own 2x error threshold.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300)
    with pytest.warns(Image.DecompressionBombWarning), pytest.raises(uploads.ImageTooLarge):
        uploads.validate_image(image_file(size=(20, 20)))


def test_decompression_bomb_error_is_too_large(monkeypatch):
    # 400 pixels > 2 x 100, so Pillow itself raises DecompressionBombError.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(uploads.ImageTooLarge):
        uploads.validate_image(image_file(size=(20, 20)))
