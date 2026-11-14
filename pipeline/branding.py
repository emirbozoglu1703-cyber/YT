"""Kanal görselleri: YouTube kapak (banner, 2560x1440) ve profil resmi (800x800).

Kuklalar ve fonlar videolardaki motorla (theater.py) aynı, böylece kanal kimliği videolarla tutarlı.
Kullanım: python pipeline/branding.py [çıktı_klasörü]   (varsayılan output/kanallar)
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import theater as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BW, BH = 2560, 1440
SAFE = (507, 508, 2053, 931)  # tüm cihazlarda görünen alan

# kanal başına sahne: fon, ışık, iki kukla (sol, sağ) ve profil maskotu
LOOKS = {
    "vicdan-testi": {
        "backdrop": ("street", "evening"),
        "left": {"id": "a", "type": "human", "gender": "male", "age": "old", "outfit": "apron", "color": "green", "skin": "light",
                 "hair": "bald", "hair_color": "gray", "mustache": True, "glasses": True, "holds": "wallet"},
        "right": {"id": "b", "type": "human", "gender": "female", "age": "adult", "outfit": "dress", "color": "red", "skin": "medium",
                  "hair": "long", "hair_color": "black", "holds": None},
        "right_pose": "think", "mascot": "left",
    },
    "mahalle-kuklalari": {
        "backdrop": ("street", "day"),
        "left": {"id": "a", "type": "human", "gender": "female", "age": "old", "outfit": "dress", "color": "purple", "skin": "light",
                 "hat": "scarf", "hat_color": "pink", "holds": "phone"},
        "right": {"id": "b", "type": "cat", "color": "orange"},
        "left_pose": "cheer", "mascot": "right",
    },
    "kukla-bilgi": {
        "backdrop": ("school", "day"),
        "left": {"id": "a", "type": "human", "gender": "male", "age": "old", "outfit": "vest", "color": "teal", "skin": "tan",
                 "hair": "short", "hair_color": "white", "beard": True, "glasses": True, "holds": "book"},
        "right": {"id": "b", "type": "owl", "color": "brown"},
        "left_pose": "point", "mascot": "right",
    },
    "gece-perdesi": {
        "backdrop": ("village", "night"),
        "left": {"id": "a", "type": "human", "gender": "male", "age": "adult", "outfit": "vest", "color": "navy", "skin": "medium",
                 "hair": "short", "hair_color": "brown", "holds": "lantern"},
        "right": {"id": "b", "type": "cat", "color": "black"},
        "mascot": "left",
    },
    "para-kuklalari": {
        "backdrop": ("market", "day"),
        "left": {"id": "a", "type": "human", "gender": "male", "age": "adult", "outfit": "suit", "color": "navy", "skin": "light",
                 "hair": "short", "hair_color": "black", "mustache": True, "holds": "coin"},
        "right": {"id": "b", "type": "human", "gender": "female", "age": "adult", "outfit": "dress", "color": "green", "skin": "tan",
                  "hair": "bun", "hair_color": "brown", "holds": "wallet"},
        "right_pose": "cheer", "mascot": "left",
    },
}
POSES = {"idle": (10, -8), "think": (128, -8), "point": (80, -8), "cheer": (76, -155)}


def puppet_img(spec, pose="idle", face=1):
    p = T.Puppet(spec)
    fa, ba = POSES.get(pose, POSES["idle"])
    im = p.render(fa, ba, False, False)
    im = T.cutout(im) if hasattr(T, "cutout") and False else im
    # çubuk
    d = ImageDraw.Draw(im)
    d.rectangle([T.PCX - 6, 690, T.PCX + 6, T.PH], fill=(92, 62, 38))
    return ImageOps.mirror(im) if face < 0 else im


def cover(img, w, h):
    k = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * k + 1), int(img.height * k + 1)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def fit_font(d, text, path, size, maxw):
    f = T.font(path, size)
    while d.textlength(text, font=f) > maxw and size > 40:
        size -= 4
        f = T.font(path, size)
    return f


def banner(key, ch, look, out):
    img = Image.new("RGBA", (BW, BH), (44, 22, 26, 255))
    bd = T.paint_backdrop(*look["backdrop"]).convert("RGBA")
    img.alpha_composite(cover(bd, BW, 1080), (0, 40))
    # sahne zemini ve önü
    d = ImageDraw.Draw(img)
    d.rectangle([0, 1000, BW, 1040], fill=(150, 98, 60))
    d.rectangle([0, 1040, BW, 1150], fill=(96, 58, 36))
    for i in range(23):
        x = 60 + i * 112
        d.chord([x - 26, 1022, x + 26, 1066], 180, 360, fill=(255, 236, 170))
    d.rectangle([0, 1150, BW, BH], fill=(26, 14, 20))
    # spot ışığı: ortayı aydınlat, kenarları karart
    vig = Image.new("L", (BW, BH), 0)
    ImageDraw.Draw(vig).ellipse([300, 120, BW - 300, 1500], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(220))
    dark = Image.new("RGBA", (BW, BH), (10, 4, 8, 150))
    dark.putalpha(Image.eval(vig, lambda v: int(150 * (1 - v / 255))))
    img.alpha_composite(dark)
    # kuklalar (güvenli alanın iki ucunda, birbirine dönük)
    k = 0.8
    for side, face, cx in (("left", 1, 650), ("right", -1, 1910)):
        pim = puppet_img(look[side], look.get(f"{side}_pose", "idle"), face)
        pim = pim.resize((int(T.PW * k), int(T.PH * k)), Image.LANCZOS)
        sh = Image.new("RGBA", pim.size, (0, 0, 0, 0))
        sh.putalpha(pim.getchannel("A").point(lambda a: a * 0.35))
        img.alpha_composite(sh, (cx - pim.width // 2 + 16, 1040 - int(T.PIV * k) + 12))
        img.alpha_composite(pim, (cx - pim.width // 2, 1040 - int(T.PIV * k)))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 1040, BW, 1150], fill=(96, 58, 36))  # çubuklar sahne önünün arkasında kalsın
    d.rectangle([0, 1040, BW, 1050], fill=(150, 98, 60))
    for i in range(23):
        x = 60 + i * 112
        d.chord([x - 26, 1022, x + 26, 1066], 180, 360, fill=(255, 236, 170))
    # perdeler ve saçak (güvenli alanın dışında)
    img.alpha_composite(T.curtain_panel(420, 1100), (-30, 0))
    img.alpha_composite(T.curtain_panel(420, 1100, flip=True), (BW - 390, 0))
    val = T.curtain_panel(BW, 300)
    img.alpha_composite(val, (0, -120))
    d = ImageDraw.Draw(img)
    for i in range(20):
        x0 = i * BW / 20
        d.chord([x0 - 4, 120, x0 + BW / 20 + 4, 250], 0, 180, fill=(140, 20, 32))
        d.arc([x0 - 4, 120, x0 + BW / 20 + 4, 250], 0, 180, fill=(214, 170, 70), width=10)
    d.rectangle([0, 160, BW, 186], fill=(214, 170, 70))
    # isim tabelası (güvenli alanın ortası)
    bc = tuple(ch.get("banner_color", [150, 30, 40]))
    name, about = ch["name"], ch["about"]
    nf = fit_font(d, T.tr_upper(name), T.FONT_SERIF, 120, 720)
    af = T.font(T.FONT_BOLD, 38)
    lines = T.wrap(d, about, af, 700)
    if len(lines) > 2:
        af = T.font(T.FONT_BOLD, 32)
        lines = T.wrap(d, about, af, 720)
    gap = 50 if len(lines) <= 2 else 40
    x0, x1 = BW / 2 - 400, BW / 2 + 400
    y0, y1 = 545, 900
    d.rounded_rectangle([x0 + 10, y0 + 14, x1 + 10, y1 + 14], radius=36, fill=(20, 10, 12, 140))
    d.rounded_rectangle([x0, y0, x1, y1], radius=36, fill=bc, outline=(214, 170, 70), width=10)
    d.rounded_rectangle([x0 + 22, y0 + 22, x1 - 22, y1 - 22], radius=24, outline=(255, 226, 150), width=3)
    d.text((BW / 2, 668), T.tr_upper(name), font=nf, fill=(255, 244, 222), anchor="mm", stroke_width=6, stroke_fill=T.shade(bc, 0.45))
    for i, ln in enumerate(lines[:3]):
        d.text((BW / 2, (790 if len(lines) <= 2 else 772) + i * gap), ln, font=af, fill=(255, 232, 180), anchor="mm")
    img.convert("RGB").save(out, quality=94)


def profile(key, ch, look, out):
    S = 800
    bc = tuple(ch.get("banner_color", [150, 30, 40]))
    img = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    grad = Image.new("L", (S, S), 0)
    ImageDraw.Draw(grad).ellipse([60, 40, S - 60, S + 80], fill=255)
    grad = grad.filter(ImageFilter.GaussianBlur(120))
    img.paste(Image.new("RGBA", (S, S), T.shade(bc, 0.45) + (255,)), (0, 0))
    img.paste(Image.new("RGBA", (S, S), T.shade(bc, 1.25) + (255,)), (0, 0), grad)
    side = look["mascot"]
    spec = look[side]
    pim = puppet_img(spec, "idle", 1 if side == "left" else -1)
    k = 1.55
    pim = pim.resize((int(T.PW * k), int(T.PH * k)), Image.LANCZOS)
    # baş ve omuzlar ortada
    head_y = 330 if spec.get("type") in T.ANIMALS else 250
    img.alpha_composite(pim, (S // 2 - pim.width // 2, 400 - int(head_y * k)))
    # üstte perde saçağı
    d = ImageDraw.Draw(img)
    img.alpha_composite(T.curtain_panel(S, 150), (0, -40))
    d = ImageDraw.Draw(img)
    for i in range(6):
        x0 = i * S / 6
        d.chord([x0 - 4, 70, x0 + S / 6 + 4, 150], 0, 180, fill=(140, 20, 32))
        d.arc([x0 - 4, 70, x0 + S / 6 + 4, 150], 0, 180, fill=(214, 170, 70), width=7)
    d.rectangle([0, 96, S, 112], fill=(214, 170, 70))
    img.convert("RGB").save(out, quality=94)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "output", "kanallar")
    with open(os.path.join(ROOT, "config", "channels.json"), encoding="utf-8") as f:
        chans = json.load(f)
    for key, ch in chans.items():
        d = os.path.join(out_dir, ch["name"])
        os.makedirs(d, exist_ok=True)
        banner(key, ch, LOOKS[key], os.path.join(d, "kapak_2560x1440.jpg"))
        profile(key, ch, LOOKS[key], os.path.join(d, "profil_800x800.jpg"))
        print("ok", ch["name"])


if __name__ == "__main__":
    main()
