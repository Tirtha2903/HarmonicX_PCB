from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from ui.design import _read_uploaded_images


def _png_bytes() -> bytes:
    image = Image.new("RGB", (2, 2), color="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_read_uploaded_images_accepts_valid_photo():
    raw = _png_bytes()
    uploaded = SimpleNamespace(name="circuit.png", size=len(raw), getvalue=lambda: raw)

    images, errors = _read_uploaded_images([uploaded], max_image_mb=1)

    assert images == [("circuit.png", raw)]
    assert errors == []


def test_read_uploaded_images_reports_invalid_photo():
    raw = b"not an image"
    uploaded = SimpleNamespace(name="broken.png", size=len(raw), getvalue=lambda: raw)

    images, errors = _read_uploaded_images([uploaded], max_image_mb=1)

    assert images == []
    assert len(errors) == 1
    assert "broken.png is not a valid supported image" in errors[0]
