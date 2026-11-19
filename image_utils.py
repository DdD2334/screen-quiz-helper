# -*- coding: utf-8 -*-
"""image_utils.py — Pillow 压缩缩放（T15）：控制请求体积，文字清晰且快。"""
from __future__ import annotations

import base64
import io

from PIL import Image


def prepare_image(png_bytes: bytes, max_side: int = 2048, fmt: str = "jpeg", quality: int = 85) -> tuple[str, str]:
    """返回 (base64, mime)。长边 > max_side 时等比 LANCZOS 缩小；小图不放大。"""
    im = Image.open(io.BytesIO(png_bytes))
    im.load()
    long_side = max(im.size)
    if max_side > 0 and long_side > max_side:
        scale = max_side / long_side
        new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        im = im.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "jpeg":
        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        im.save(buf, "PNG", optimize=True)
        mime = "image/png"
    return base64.b64encode(buf.getvalue()).decode("ascii"), mime