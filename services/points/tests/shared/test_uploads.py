import io
import os

import pytest
from PIL import Image

from app.shared import uploads
from tests.images import image_bytes, image_file


def stored_files(data_dir):
    return list((data_dir / "uploads").iterdir())


@pytest.mark.parametrize("image_format, extension", [("JPEG", ".jpg"), ("PNG", ".png")])
def test_valid_image_is_saved_with_relative_path_and_extension(data_dir, image_format, extension):
    relative_path = uploads.save_image(image_file(image_format))
    assert relative_path.startswith("uploads/")
    assert relative_path.endswith(extension)
    assert (data_dir / relative_path).read_bytes() == image_bytes(image_format)


def test_filenames_are_unique(data_dir):
    first = uploads.save_image(image_file())
    second = uploads.save_image(image_file())
    assert first != second


def test_random_bytes_are_rejected(data_dir):
    with pytest.raises(uploads.InvalidImage):
        uploads.save_image(io.BytesIO(os.urandom(1024)))
    assert stored_files(data_dir) == []


def test_text_file_named_jpg_is_rejected(data_dir):
    # The name is never looked at: only the content decides.
    fake = io.BytesIO(b"just some text, not a photo")
    fake.name = "holiday.jpg"
    with pytest.raises(uploads.InvalidImage):
        uploads.save_image(fake)


def test_other_image_formats_are_rejected(data_dir):
    with pytest.raises(uploads.InvalidImage):
        uploads.save_image(image_file("GIF"))


def test_truncated_image_is_rejected(data_dir):
    with pytest.raises(uploads.InvalidImage):
        uploads.save_image(io.BytesIO(image_bytes("PNG")[:40]))


def test_file_over_limit_is_rejected_and_nothing_written(data_dir):
    too_big = image_bytes("PNG") + b"\0" * uploads.MAX_UPLOAD_BYTES
    with pytest.raises(uploads.ImageTooLarge):
        uploads.save_image(io.BytesIO(too_big))
    assert stored_files(data_dir) == []


def test_file_exactly_at_limit_is_not_rejected_for_size(data_dir, monkeypatch):
    data = image_bytes("PNG")
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", len(data))
    assert uploads.save_image(io.BytesIO(data)).endswith(".png")


def test_too_many_pixels_is_rejected(data_dir, monkeypatch):
    # 20x20 = 400 pixels: above our limit, below Pillow's own 2x error threshold.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300)
    with pytest.warns(Image.DecompressionBombWarning), pytest.raises(uploads.ImageTooLarge):
        uploads.save_image(image_file(size=(20, 20)))


def test_decompression_bomb_error_is_too_large(data_dir, monkeypatch):
    # 400 pixels > 2 x 100, so Pillow itself raises DecompressionBombError.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(uploads.ImageTooLarge):
        uploads.save_image(image_file(size=(20, 20)))


def test_resolve_path_returns_absolute_path_inside_uploads(data_dir):
    relative_path = uploads.save_image(image_file())
    path = uploads.resolve_path(relative_path)
    assert path.is_absolute()
    assert path.is_file()


@pytest.mark.parametrize("relative_path", ["../app.db", "uploads/../app.db", "uploads/../../secret"])
def test_resolve_path_rejects_traversal(data_dir, relative_path):
    with pytest.raises(ValueError):
        uploads.resolve_path(relative_path)


def test_delete_image_removes_file_and_ignores_missing(data_dir):
    relative_path = uploads.save_image(image_file())
    uploads.delete_image(relative_path)
    assert stored_files(data_dir) == []
    uploads.delete_image(relative_path)  # already gone: no error
