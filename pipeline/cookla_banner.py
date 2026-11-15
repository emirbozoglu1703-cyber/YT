"""Cookla kanal kapağı (YouTube banner, 2560x1440).
Logo, slogan ve beş tür ortadaki güvenli alanda; kuklalar iki yanda, perdeler kenarlarda.
Kullanım: python pipeline/cookla_banner.py [çıktı_klasörü]"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

import branding as B
import cookla_logo as L
import theater as T

BW, BH = 2560, 1440
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAST = [  # (spec, poz, yön, x, ölçek)
    ({"id": "a", "type": "human", "gender": "male", "age": "old", "outfit": "apron", "color": "green", "skin": "light",
      "hair": "bald", "hair_color": "gray", "mustache": True, "glasses": True, "holds": "wallet"}, "idle", 1, 600, 0.68),
    ({"id": "b", "type": "cat", "color": "orange"}, "idle", 1, 790, 0.62),
    ({"id": "c", "type": "owl", "color": "brown"}, "idle", -1, 1760, 0.62),
    ({"id": "d", "type": "human", "gender": "female", "age": "old", "outfit": "dress", "color": "purple", "skin": "light",
      "hat": "scarf", "hat_color": "pink", "holds": "phone"}, "cheer", -1, 1960, 0.68),
]
LIP = 1060


def logo_layer(fpath, size):
    """cookla_logo.wordmark'ı şeffaf tuvale çizip kırpar."""
    c = Image.new("RGBA", (L.S, L.S), (0, 0, 0, 0))
    L.wordmark(c, L.S // 2, size, eyes=True, fpath=fpath)
    return c.crop(c.getbbox())


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "output", "cookla")
    os.makedirs(out_dir, exist_ok=True)
    fpath = L.find_font()
    img = Image.new("RGBA", (BW, BH), (24, 8, 14, 255))
    # arka perde (sahnenin içi): kıvrımlı kırmızı + ortada spot
    back = Image.new("RGBA", (BW, BH), (0, 0, 0, 255))
    d = ImageDraw.Draw(back)
    n = 30
    for i in range(n):
        x0 = i * BW / n
        for k in range(24):
            t = k / 23
            import math
            c = tuple(int(L.RED_D[j] + (L.RED[j] - L.RED_D[j]) * (0.3 + 0.7 * math.sin(math.pi * t))) for j in range(3))
            d.rectangle([x0 + t * BW / n, 0, x0 + t * BW / n + BW / n / 23 + 1, BH], fill=c)
    img.alpha_composite(back)
    spot = Image.new("L", (BW, BH), 0)
    ImageDraw.Draw(spot).ellipse([520, 220, BW - 520, 1300], fill=255)
    spot = spot.filter(ImageFilter.GaussianBlur(200))
    dark = Image.new("RGBA", (BW, BH), (14, 4, 8, 255))
    dark.putalpha(spot.point(lambda v: int(185 * (1 - v / 255))))
    img.alpha_composite(dark)
    glow = Image.new("RGBA", (BW, BH), (255, 196, 120, 0))
    g = Image.new("L", (BW, BH), 0)
    ImageDraw.Draw(g).ellipse([800, 420, BW - 800, 1000], fill=80)
    glow.putalpha(g.filter(ImageFilter.GaussianBlur(160)))
    img.alpha_composite(glow)
    # kuklalar
    for spec, pose, face, cx, k in CAST:
        pim = B.puppet_img(spec, pose, face)
        pim = pim.resize((int(T.PW * k), int(T.PH * k)), Image.LANCZOS)
        sh = Image.new("RGBA", pim.size, (0, 0, 0, 0))
        sh.putalpha(pim.getchannel("A").point(lambda a: a * 0.4))
        y = LIP - int(T.PIV * k)
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)), (cx - pim.width // 2 + 16, y + 14))
        img.alpha_composite(pim, (cx - pim.width // 2, y))
    # sahne önü (kukla çubuklarını örter) ve ışıklar
    d = ImageDraw.Draw(img)
    d.rectangle([0, LIP - 20, BW, LIP + 110], fill=(96, 58, 36))
    d.rectangle([0, LIP - 20, BW, LIP - 6], fill=(150, 98, 60))
    d.rectangle([0, LIP + 110, BW, BH], fill=(22, 10, 16))
    for i in range(23):
        x = 60 + i * 112
        d.chord([x - 28, LIP - 44, x + 28, LIP + 4], 180, 360, fill=(255, 236, 170))
    # yan perdeler ve saçak (güvenli alanın dışında)
    img.alpha_composite(T.curtain_panel(440, 1180), (-30, 0))
    img.alpha_composite(T.curtain_panel(440, 1180, flip=True), (BW - 410, 0))
    d = ImageDraw.Draw(img)
    for x in (300, BW - 300):
        d.rounded_rectangle([x - 70, 760, x + 70, 810], radius=24, fill=L.GOLD, outline=L.GOLD_D, width=6)
    img.alpha_composite(T.curtain_panel(BW, 300), (0, -110))
    d = ImageDraw.Draw(img)
    for i in range(20):
        x0 = i * BW / 20
        d.chord([x0 - 4, 130, x0 + BW / 20 + 4, 260], 0, 180, fill=(140, 20, 32))
        d.arc([x0 - 4, 130, x0 + BW / 20 + 4, 260], 0, 180, fill=L.GOLD, width=10)
    d.rectangle([0, 170, BW, 196], fill=L.GOLD)
    # logo + slogan + türler (güvenli alanda: x 507-2053, y 508-931)
    logo = logo_layer(fpath, 250)
    if logo.width > 860:
        logo = logo.resize((860, int(logo.height * 860 / logo.width)), Image.LANCZOS)
    img.alpha_composite(logo, (BW // 2 - logo.width // 2, 640 - logo.height // 2))
    d = ImageDraw.Draw(img)
    f = T.font(fpath, 50)
    d.text((BW / 2 + 4, 790 + 5), "Her gün yeni bir kukla oyunu", font=f, fill=(0, 0, 0), anchor="mm")
    d.text((BW / 2, 790), "Her gün yeni bir kukla oyunu", font=f, fill=L.GOLD, anchor="mm")
    with open(os.path.join(ROOT, "config", "channels.json"), encoding="utf-8") as fh:
        chans = json.load(fh)
    labels = [("Vicdan", "vicdan-testi"), ("Komedi", "mahalle-kuklalari"), ("Bilgi", "kukla-bilgi"), ("Gizem", "gece-perdesi"), ("Para", "para-kuklalari")]
    cf = T.font(fpath, 32)
    widths = [d.textlength(t, font=cf) + 54 for t, _ in labels]
    gap = 18
    x = BW / 2 - (sum(widths) + gap * (len(widths) - 1)) / 2
    for (t, key), w in zip(labels, widths):
        col = tuple(chans[key]["banner_color"])
        d.rounded_rectangle([x, 850, x + w, 906], radius=28, fill=col, outline=L.CREAM, width=3)
        d.text((x + w / 2, 878), t, font=cf, fill=L.CREAM, anchor="mm")
        x += w + gap
    out = os.path.join(out_dir, "cookla_kapak_2560x1440.jpg")
    img.convert("RGB").save(out, quality=94)
    print(out)


if __name__ == "__main__":
    main()
