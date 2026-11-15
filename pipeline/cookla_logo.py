"""Cookla kanal profil resmi (800x800). İki tasarım: 'gozler' (OO = kukla gözleri) ve 'maskot' (perde önünde kukla).
Kullanım: python pipeline/cookla_logo.py [çıktı_klasörü]"""
from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

import theater as T

S = 1600  # 2x çiz, 800'e indir (pürüzsüz kenarlar)
INTER_BLACK = "/usr/share/fonts/truetype/inter/Inter-Black.ttf"
GOLD, GOLD_D, CREAM = (232, 186, 82), (150, 104, 34), (255, 244, 222)
RED, RED_D = (170, 24, 38), (70, 8, 18)


def find_font():
    for p in (INTER_BLACK, "/usr/share/fonts/opentype/inter/Inter-Black.otf"):
        if os.path.exists(p):
            return p
    import subprocess
    out = subprocess.run(["fc-match", "-f", "%{file}", "Inter:black"], capture_output=True, text=True).stdout
    return out or T.FONT_BOLD


def stage_bg():
    """Koyu bordo zemin, ortada spot ışığı, kenarlarda kıvrımlı perde."""
    img = Image.new("RGBA", (S, S), RED_D + (255,))
    # perde kıvrımları: dikey koyu/açık şeritler
    d = ImageDraw.Draw(img)
    n = 18
    for i in range(n):
        x0 = i * S / n
        for k in range(40):
            t = k / 39
            c = tuple(int(RED_D[j] + (RED[j] - RED_D[j]) * (0.35 + 0.65 * math.sin(math.pi * t))) for j in range(3))
            d.rectangle([x0 + t * S / n, 0, x0 + t * S / n + S / n / 39 + 1, S], fill=c)
    # spot: ortası parlak, kenarlar karanlık
    spot = Image.new("L", (S, S), 0)
    ImageDraw.Draw(spot).ellipse([S * 0.12, S * 0.10, S * 0.88, S * 0.95], fill=255)
    spot = spot.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGBA", (S, S), (20, 4, 10, 255))
    dark.putalpha(spot.point(lambda v: int(200 * (1 - v / 255))))
    img.alpha_composite(dark)
    glow = Image.new("RGBA", (S, S), (255, 200, 120, 0))
    g = Image.new("L", (S, S), 0)
    ImageDraw.Draw(g).ellipse([S * 0.28, S * 0.22, S * 0.72, S * 0.78], fill=70)
    glow.putalpha(g.filter(ImageFilter.GaussianBlur(140)))
    img.alpha_composite(glow)
    return img


def ring(img):
    d = ImageDraw.Draw(img)
    m = 26
    d.ellipse([m, m, S - m, S - m], outline=GOLD_D, width=46)
    d.ellipse([m + 6, m + 6, S - m - 6, S - m - 6], outline=GOLD, width=30)
    d.ellipse([m + 52, m + 52, S - m - 52, S - m - 52], outline=(255, 226, 150), width=6)


def eye(d, cx, cy, r, look=(0.32, 0.08)):
    """Karton kukla gözü: krem kenar, beyaz, iri siyah bebek, parlama."""
    d.ellipse([cx - r - 16, cy - r - 16, cx + r + 16, cy + r + 16], fill=CREAM)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255), outline=(30, 20, 22), width=12)
    px, py = cx + look[0] * r, cy + look[1] * r
    pr = r * 0.5
    d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(28, 20, 22))
    hr = pr * 0.32
    d.ellipse([px - pr * 0.45 - hr, py - pr * 0.45 - hr, px - pr * 0.45 + hr, py - pr * 0.45 + hr], fill=(255, 255, 255))


def wordmark(img, y, size, eyes=True, fpath=None):
    """COOKLA; iki O harfi kukla gözü olarak çizilir."""
    d = ImageDraw.Draw(img)
    f = T.font(fpath, size)
    parts = ["C", "O", "O", "KLA"]
    gap = size * 0.04
    o_w = size * 0.80
    widths = [d.textlength("C", font=f), o_w, o_w, d.textlength("KLA", font=f)]
    total = sum(widths) + gap * 3
    x = S / 2 - total / 2
    # gölge katmanı
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    xx = x
    for p, w in zip(parts, widths):
        if p == "O":
            r = o_w / 2
            sd.ellipse([xx + 14 - 16, y + 18 - r - 16, xx + 14 + 2 * r + 16, y + 18 + r + 16], fill=(0, 0, 0, 150))
        else:
            sd.text((xx + 14, y + 18), p, font=f, fill=(0, 0, 0, 150), anchor="lm")
        xx += w + gap
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(img)
    for i, (p, w) in enumerate(zip(parts, widths)):
        if p == "O":
            r = o_w / 2
            if eyes:
                eye(d, x + r, y, r - 4, look=(0.30, 0.10))
            else:
                d.ellipse([x, y - r, x + 2 * r, y + r], outline=CREAM, width=int(size * 0.2))
        else:
            d.text((x, y), p, font=f, fill=CREAM, anchor="lm", stroke_width=10, stroke_fill=(60, 10, 18))
        x += w + gap


def valance(img, depth=210):
    """Üstte saçaklı perde ve altın şerit."""
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, S, depth - 60], fill=(130, 14, 28))
    for i in range(14):
        x0 = i * S / 14
        for k in range(12):
            t = k / 11
            c = tuple(int(v * (0.75 + 0.25 * math.sin(math.pi * t))) for v in (170, 24, 38))
            d.rectangle([x0 + t * S / 14, 0, x0 + t * S / 14 + S / 14 / 11 + 1, depth - 60], fill=c)
    n = 8
    for i in range(n):
        x0 = i * S / n
        d.chord([x0 - 6, depth - 130, x0 + S / n + 6, depth], 0, 180, fill=(150, 18, 34))
        d.arc([x0 - 6, depth - 130, x0 + S / n + 6, depth], 0, 180, fill=GOLD, width=16)
    d.rectangle([0, depth - 96, S, depth - 66], fill=GOLD)


def design_gozler(fpath):
    img = stage_bg()
    valance(img, 330)
    # sahne tahtası
    d = ImageDraw.Draw(img)
    d.rectangle([0, 1180, S, 1600], fill=(96, 58, 36))
    d.rectangle([0, 1180, S, 1200], fill=(150, 98, 60))
    for i in range(9):
        x = 100 + i * 175
        d.chord([x - 38, 1154, x + 38, 1220], 180, 360, fill=(255, 236, 170))
    wordmark(img, 790, 250, eyes=True, fpath=fpath)
    f = T.font(fpath, 70)
    d = ImageDraw.Draw(img)
    d.text((S / 2, 1010), "KUKLA TİYATROSU", font=f, fill=GOLD, anchor="mm", stroke_width=4, stroke_fill=(60, 10, 18))
    ring(img)
    return img


def design_maskot(fpath):
    """Aralanan perdenin arasından bakan iki iri kukla gözü + altta COOKLA."""
    img = Image.new("RGBA", (S, S), (16, 6, 10, 255))
    # perde aralığı: karanlık sahne, içeride sıcak ışık
    g = Image.new("L", (S, S), 0)
    ImageDraw.Draw(g).ellipse([S * 0.25, S * 0.18, S * 0.75, S * 0.78], fill=120)
    glow = Image.new("RGBA", (S, S), (255, 190, 110, 0))
    glow.putalpha(g.filter(ImageFilter.GaussianBlur(150)))
    img.alpha_composite(glow)
    # iki yan perde, ortada aralık bırakır
    for flip in (False, True):
        w = 640
        pnl = Image.new("RGBA", (w, S), (0, 0, 0, 0))
        pd = ImageDraw.Draw(pnl)
        n = 7
        for i in range(n):
            x0 = i * w / n
            for k in range(30):
                t = k / 29
                c = tuple(int(RED_D[j] + (RED[j] - RED_D[j]) * (0.3 + 0.7 * math.sin(math.pi * t))) for j in range(3))
                pd.rectangle([x0 + t * w / n, 0, x0 + t * w / n + w / n / 29 + 1, S], fill=c)
        # içe doğru toplanan kenar: alt köşe geriye çekilir
        mask = Image.new("L", (w, S), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (w, 0), (w - 40, S * 0.55), (w - 170, S), (0, S)], fill=255)
        pnl.putalpha(mask)
        sh = Image.new("RGBA", (w, S), (0, 0, 0, 0))
        sh.putalpha(mask.filter(ImageFilter.GaussianBlur(20)).point(lambda a: a * 0.6))
        if flip:
            pnl, sh = pnl.transpose(Image.FLIP_LEFT_RIGHT), sh.transpose(Image.FLIP_LEFT_RIGHT)
            img.alpha_composite(sh, (S - w - 20, 0))
            img.alpha_composite(pnl, (S - w, 0))
        else:
            img.alpha_composite(sh, (20, 0))
            img.alpha_composite(pnl, (0, 0))
    # perdeyi tutan altın kordonlar
    d = ImageDraw.Draw(img)
    valance(img, 300)
    # gözler (birbirine yakın, hafif yukarı-yana bakıyor) + kaşlar
    d = ImageDraw.Draw(img)
    for cx in (S / 2 - 170, S / 2 + 170):
        eye(d, cx, 660, 150, look=(0.28, -0.12))
        d.arc([cx - 140, 430, cx + 140, 560], 200, 340, fill=CREAM, width=26)
    # yazı
    f = T.font(fpath, 200)
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((S / 2 + 12, 1080 + 16), "COOKLA", font=f, fill=(0, 0, 0, 170), anchor="mm")
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(img)
    d.text((S / 2, 1080), "COOKLA", font=f, fill=GOLD, anchor="mm", stroke_width=10, stroke_fill=(60, 10, 18))
    d.rectangle([0, 1250, S, 1600], fill=(96, 58, 36))
    d.rectangle([0, 1250, S, 1270], fill=(150, 98, 60))
    for i in range(9):
        x = 100 + i * 175
        d.chord([x - 38, 1224, x + 38, 1290], 180, 360, fill=(255, 236, 170))
    ring(img)
    return img


def finish(img):
    out = img.resize((800, 800), Image.LANCZOS).convert("RGB")
    return out


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "cookla")
    os.makedirs(out_dir, exist_ok=True)
    fpath = find_font()
    finish(design_gozler(fpath)).save(os.path.join(out_dir, "cookla_profil_1_gozler.png"))
    finish(design_maskot(fpath)).save(os.path.join(out_dir, "cookla_profil_2_perde.png"))
    print("ok", out_dir, fpath)


if __name__ == "__main__":
    main()
