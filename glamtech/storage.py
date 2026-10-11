import io
import os
import re
import warnings
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 5 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 12_000_000


class InvalidUpload(ValueError):
    pass


def folder(kind):
    return Path(current_app.config["STORAGE_ROOT"]) / ("photos" if kind == "photo" else "private")


def file_path(kind, name):
    if not re.fullmatch(r"[a-f0-9]{32}\.jpg", name):
        raise InvalidUpload("Invalid storage filename.")
    return folder(kind) / name


def save_image(upload, kind):
    raw = upload.read(MAX_FILE_BYTES + 1)
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise InvalidUpload("Each image must be nonempty and at most 5 MiB.")
    extension = Path(upload.filename).suffix.lower()
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}.get(extension)
    if not expected or upload.mimetype not in {"image/jpeg", "image/png"}:
        raise InvalidUpload("Only JPEG and PNG images are accepted.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != expected or getattr(image, "n_frames", 1) != 1:
                    raise InvalidUpload("Image content must match its extension; animations are unsupported.")
                if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                    raise InvalidUpload("Images must contain at most 12 million pixels.")
                image.load()
                image = image.convert("RGB")
                image.thumbnail((2400, 2400))
                output = io.BytesIO()
                # Keep pixel data only: no source metadata or original filename survives.
                image.save(output, format="JPEG", quality=88)
                data = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise InvalidUpload("Upload a valid, non-animated JPEG or PNG image.") from exc
    if len(data) > MAX_FILE_BYTES:
        raise InvalidUpload("The processed image exceeds 5 MiB.")
    name = f"{uuid4().hex}.jpg"
    path = file_path(kind, name)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return name, len(data)
