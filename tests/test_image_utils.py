# -*- coding: utf-8 -*-
import base64
import io

from PIL import Image

from image_utils import prepare_image


def make_png(w, h):
    # 密集噪声图：PNG 压缩率低，接近真实截图的体积特征
    im = Image.effect_noise((w, h), 80).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def decode_size(b64):
    im = Image.open(io.BytesIO(base64.b64decode(b64)))
    return im.size


def test_resize_long_side():
    png = make_png(3000, 2000)
    b64, mime = prepare_image(png, 2048, "jpeg", 85)
    w, h = decode_size(b64)
    assert max(w, h) == 2048
    assert mime == "image/jpeg"


def test_jpeg_smaller_than_png():
    png = make_png(3000, 2000)
    b64_j, _ = prepare_image(png, 2048, "jpeg", 85)
    b64_p, mime_p = prepare_image(png, 2048, "png", 85)
    assert mime_p == "image/png"
    assert len(base64.b64decode(b64_j)) < len(base64.b64decode(b64_p))


def test_4k_under_one_fifth():
    png = make_png(3840, 2160)
    b64, _ = prepare_image(png, 2048, "jpeg", 85)
    assert len(base64.b64decode(b64)) < len(png) / 5


def test_small_not_upscaled():
    png = make_png(800, 600)
    b64, _ = prepare_image(png, 2048, "png", 85)
    assert decode_size(b64) == (800, 600)