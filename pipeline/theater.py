"""Kıssa Defteri: KUKLA TİYATROSU render motoru.

Görünüm: ahşap sahne, kırmızı kadife perdeler, boyalı fon, çubuklu karton kuklalar, ön ışıklar, karanlık seyirci sırası.
Kurgu dili:
  * Konuşan kuklanın ağzı kelimelerle açılıp kapanır, üstüne spot ışık düşer, kukla konuşurken zıplar/el sallar.
  * Mekân değişince perde kapanır ve açılır; aynı mekânda kamera planı değişir (genel / orta / yakın).
  * Altyazı seyirci bölümünde, konuşanın adıyla, kelimeler söylendikçe belirir.
  * Video perde açılarak başlar, son selamla perde kapanır ve alkış gelir.
Kuklalar oyunun başında "cast" ile bir kez tanımlanır: her sahnede aynı görünürler (süreklilik garantili).
"""
from __future__ import annotations

import math
import random
import subprocess
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FPS = 30
OPEN_L, OPEN_R = 70, 1010            # sahne ağzı
BACK_TOP, BACK_BOT = 250, 1165       # fon
FLOOR_BACK, FLOOR_FRONT = 1150, 1300 # zemin (arka kenar, ön kenar)
LIP_TOP, LIP_BOT = 1300, 1372        # sahne önü
PIVOT_Y = 1335                       # kukla çubuğunun tutulduğu nokta (sahne önünün arkasında)
CAP_Y = 1510

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

COLORS = {"red": (186, 58, 48), "blue": (58, 98, 160), "green": (74, 132, 84), "ochre": (212, 156, 58), "purple": (124, 84, 150),
          "teal": (44, 132, 136), "gray": (120, 118, 116), "brown": (130, 88, 58), "pink": (214, 120, 140), "navy": (40, 52, 96),
          "white": (236, 230, 220), "black": (46, 42, 44), "orange": (222, 126, 50)}
SKINS = {"light": (246, 214, 182), "medium": (222, 176, 136), "tan": (196, 146, 106), "dark": (140, 96, 70)}
INK = (36, 26, 22)
CARD = (238, 226, 200)
BACKDROPS = {"street", "shop", "home", "forest", "village", "sea", "market", "office", "school", "palace"}
LIGHTS = {"day", "evening", "night"}
CAMERAS = {"wide", "medium", "close"}
ACTIONS = {"idle", "talk", "point", "think", "cheer", "sad", "shake", "laugh", "bow", "jump", "give", "enter", "exit", "walk"}
PROP_KINDS = {"wallet", "table", "chair", "door", "chest", "sack", "crate", "coins", "plant", "bench", "sign", "candle", "lantern", "tree", "counter", "well", "bed"}
HOLDS = {"wallet", "coin", "letter", "gift", "phone", "lantern", "key", "bag", "flower", "book", "cane", "bread", "cup", None}
ANIMALS = {"cat", "dog", "fox", "owl", "crow", "rabbit"}


def tr_upper(s: str) -> str:
    """Türkçe büyük harf: i -> İ, ı -> I (str.upper() bunu yanlış yapar)."""
    return s.replace("i", "İ").replace("ı", "I").upper()


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    return 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2


_fonts: dict = {}


def font(path, size):
    k = (path, int(size))
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(path, int(size))
    return _fonts[k]


def col(name, default="blue"):
    if isinstance(name, (list, tuple)):
        return tuple(name)
    return COLORS.get(name or default, COLORS[default])


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def wrap(d, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        test = (cur + " " + w_).strip()
        if d.textlength(test, font=fnt) <= maxw:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines or [""]


def cutout(img: Image.Image, border=7, outline=2) -> Image.Image:
    """Karton kesik görünümü: şeklin etrafına açık karton kenar + ince koyu kontur ekler."""
    a = img.getchannel("A")
    a_card = a.filter(ImageFilter.MaxFilter(border * 2 + 1))
    a_ink = a_card.filter(ImageFilter.MaxFilter(outline * 2 + 1))
    out = Image.new("RGBA", img.size, INK + (0,))
    out.putalpha(a_ink)
    card = Image.new("RGBA", img.size, CARD + (0,))
    card.putalpha(a_card)
    out.alpha_composite(card)
    out.alpha_composite(img)
    return out


# ============================================================================ puppets
PW, PH = 520, 820       # kukla tuvali
PCX, PIV = 260, 800     # tuvalde gövde merkezi x ve çubuk pivotu y


@dataclass
class PuppetParts:
    torso: Image.Image
    front_arm: Image.Image
    back_arm: Image.Image
    shoulder: tuple
    mouth: tuple
    eyes: list
    skin: tuple
    kind: str
    height: int


def _arm(color, skin, length=150, kind="human", hold=None):
    im = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = 210, 210
    if kind == "owl":
        d.polygon([(cx - 16, cy - 10), (cx + 16, cy - 10), (cx + 34, cy + length * 0.8), (cx, cy + length), (cx - 24, cy + length * 0.7)], fill=color)
        return cutout(im, 5, 2)
    w = 30 if kind == "human" else 26
    d.rounded_rectangle([cx - w // 2, cy - 14, cx + w // 2, cy + length - 18], radius=w // 2, fill=color)
    hx, hy = cx, cy + length - 10
    d.ellipse([hx - 19, hy - 19, hx + 19, hy + 19], fill=skin)
    if hold == "wallet":
        d.rounded_rectangle([hx - 6, hy - 22, hx + 56, hy + 22], radius=8, fill=(120, 74, 40), outline=(70, 40, 20), width=4)
        d.rounded_rectangle([hx - 6, hy - 22, hx + 56, hy - 2], radius=8, fill=(146, 92, 52))
        d.rectangle([hx + 10, hy - 30, hx + 40, hy - 20], fill=(120, 190, 120))
    elif hold == "coin":
        d.ellipse([hx - 4, hy - 4, hx + 40, hy + 40], fill=(232, 186, 64), outline=(170, 120, 30), width=4)
    elif hold == "letter":
        d.rectangle([hx - 6, hy - 10, hx + 58, hy + 34], fill=(250, 246, 232))
        d.line([(hx - 6, hy - 10), (hx + 26, hy + 12), (hx + 58, hy - 10)], fill=(150, 130, 110), width=4)
    elif hold == "gift":
        d.rectangle([hx - 8, hy - 30, hx + 56, hy + 30], fill=COLORS["teal"])
        d.rectangle([hx + 18, hy - 30, hx + 30, hy + 30], fill=COLORS["red"])
    elif hold == "phone":
        d.rounded_rectangle([hx - 2, hy - 44, hx + 34, hy + 16], radius=6, fill=(30, 30, 36))
        d.rectangle([hx + 4, hy - 38, hx + 28, hy + 6], fill=(110, 184, 226))
    elif hold == "lantern":
        d.line([(hx, hy), (hx, hy + 40)], fill=INK, width=4)
        d.rounded_rectangle([hx - 22, hy + 40, hx + 22, hy + 100], radius=8, fill=(250, 214, 110), outline=INK, width=4)
    elif hold == "key":
        d.ellipse([hx - 2, hy - 18, hx + 26, hy + 10], outline=(210, 170, 60), width=7)
        d.line([(hx + 24, hy - 4), (hx + 64, hy - 4)], fill=(210, 170, 60), width=7)
    elif hold == "bag":
        d.ellipse([hx - 30, hy + 4, hx + 30, hy + 70], fill=(176, 136, 86))
        d.text((hx, hy + 38), "₺", font=font(FONT_BOLD, 34), fill=INK, anchor="mm")
    elif hold == "flower":
        d.line([(hx, hy), (hx + 10, hy - 70)], fill=(70, 130, 70), width=6)
        for a in range(5):
            ang = a / 5 * 6.283
            d.ellipse([hx + 10 + math.cos(ang) * 16 - 11, hy - 70 + math.sin(ang) * 16 - 11, hx + 10 + math.cos(ang) * 16 + 11, hy - 70 + math.sin(ang) * 16 + 11], fill=COLORS["pink"])
        d.ellipse([hx + 2, hy - 78, hx + 18, hy - 62], fill=(250, 214, 80))
    elif hold == "book":
        d.rectangle([hx - 6, hy - 34, hx + 50, hy + 30], fill=COLORS["red"])
        d.rectangle([hx - 6, hy - 34, hx + 2, hy + 30], fill=(120, 30, 30))
    elif hold == "cane":
        d.line([(hx, hy - 30), (hx + 6, hy + 190)], fill=(120, 80, 50), width=10)
        d.arc([hx - 34, hy - 54, hx + 6, hy - 14], 180, 360, fill=(120, 80, 50), width=10)
    elif hold == "bread":
        d.ellipse([hx - 10, hy - 18, hx + 80, hy + 22], fill=(214, 164, 92))
        for i in range(3):
            d.line([(hx + 10 + i * 20, hy - 10), (hx + 22 + i * 20, hy + 10)], fill=(160, 110, 60), width=4)
    elif hold == "cup":
        d.rectangle([hx - 4, hy - 30, hx + 34, hy + 14], fill=(250, 246, 240))
        d.arc([hx + 24, hy - 22, hx + 48, hy + 4], 270, 90, fill=(250, 246, 240), width=6)
    return cutout(im, 5, 2)


def build_human(spec: dict) -> PuppetParts:
    age = spec.get("age", "adult")
    female = spec.get("gender") == "female"
    outfit = spec.get("outfit", "dress" if female else "vest")
    c = col(spec.get("color"), "blue")
    c2 = col(spec.get("color2"), "white") if spec.get("color2") else shade(c, 1.35)
    skin = SKINS.get(spec.get("skin", "light"), SKINS["light"])
    hair_c = {"black": (40, 30, 28), "brown": (96, 62, 40), "blond": (220, 180, 90), "red": (170, 70, 40), "gray": (180, 176, 170),
              "white": (236, 234, 228)}.get(spec.get("hair_color", "gray" if age == "old" else "brown"), (96, 62, 40))
    im = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hx, hy, hr = PCX, 250, 74
    sh_y = 340
    # gövde
    if outfit in ("dress", "robe"):
        d.polygon([(PCX - 72, sh_y), (PCX + 72, sh_y), (PCX + 140, 700), (PCX - 140, 700)], fill=c)
        d.polygon([(PCX - 130, 660), (PCX + 130, 660), (PCX + 140, 700), (PCX - 140, 700)], fill=c2)
        if outfit == "robe":
            d.line([(PCX, sh_y + 10), (PCX, 700)], fill=shade(c, 0.7), width=6)
            d.rectangle([PCX - 96, 470, PCX + 96, 492], fill=c2)
    else:
        d.polygon([(PCX - 78, sh_y), (PCX + 78, sh_y), (PCX + 104, 700), (PCX - 104, 700)], fill=c if outfit == "apron" else c2)  # gömlek
        if outfit == "vest":
            d.polygon([(PCX - 78, sh_y), (PCX - 14, sh_y), (PCX - 4, 600), (PCX - 98, 620)], fill=c)
            d.polygon([(PCX + 78, sh_y), (PCX + 14, sh_y), (PCX + 4, 600), (PCX + 98, 620)], fill=c)
        elif outfit == "suit":
            d.polygon([(PCX - 78, sh_y), (PCX + 78, sh_y), (PCX + 104, 700), (PCX - 104, 700)], fill=c)
            d.polygon([(PCX - 26, sh_y), (PCX + 26, sh_y), (PCX, 470)], fill=(250, 248, 244))
            d.polygon([(PCX - 8, sh_y + 10), (PCX + 8, sh_y + 10), (PCX + 12, 450), (PCX, 470), (PCX - 12, 450)], fill=COLORS["red"])
        elif outfit == "apron":
            d.rounded_rectangle([PCX - 70, 420, PCX + 70, 690], radius=16, fill=(244, 240, 230))
            d.line([(PCX - 70, 430), (PCX - 40, sh_y)], fill=(244, 240, 230), width=12)
            d.line([(PCX + 70, 430), (PCX + 40, sh_y)], fill=(244, 240, 230), width=12)
            d.rectangle([PCX - 40, 520, PCX + 40, 570], outline=shade(c, 0.8), width=4)
        if outfit != "apron":
            for i in range(3):
                d.ellipse([PCX - 6, 400 + i * 60, PCX + 6, 412 + i * 60], fill=shade(c, 0.6))
        d.rectangle([PCX - 104, 690, PCX + 104, 712], fill=shade(c, 0.55))
    # boyun
    d.rectangle([PCX - 20, 300, PCX + 20, sh_y + 6], fill=skin)
    # arka saç (uzun saç)
    hair = spec.get("hair", "long" if female else ("bald" if age == "old" else "short"))
    if hair == "long":
        d.rounded_rectangle([hx - hr - 12, hy - 40, hx + 30, hy + 150], radius=40, fill=hair_c)
    # kafa
    if spec.get("hat") == "scarf":
        d.ellipse([hx - hr - 16, hy - hr - 18, hx + hr + 10, hy + hr + 30], fill=col(spec.get("hat_color"), "purple"))
    d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=skin)
    d.ellipse([hx + hr - 22, hy + 2, hx + hr + 4, hy + 30], fill=shade(skin, 0.9))  # burun (3/4 profil)
    d.ellipse([hx + 14, hy + 26, hx + 44, hy + 44], fill=(236, 150, 136))  # yanak
    if spec.get("hat") == "scarf":  # başörtüsü alnı örter, gözlere inmez
        d.chord([hx - hr - 14, hy - hr - 16, hx + hr + 8, hy - 8], 180, 360, fill=col(spec.get("hat_color"), "purple"))
    # ön saç
    if hair == "short":
        d.chord([hx - hr - 4, hy - hr - 8, hx + hr + 4, hy + hr - 10], 170, 350, fill=hair_c)
        d.polygon([(hx - hr - 2, hy - 10), (hx - hr + 30, hy - 40), (hx - hr + 20, hy + 26)], fill=hair_c)
    elif hair == "long":
        d.chord([hx - hr - 8, hy - hr - 10, hx + hr + 6, hy + hr - 6], 160, 345, fill=hair_c)
    elif hair == "bun":
        d.ellipse([hx - 50, hy - hr - 52, hx + 10, hy - hr + 8], fill=hair_c)
        d.chord([hx - hr - 4, hy - hr - 8, hx + hr + 4, hy + hr - 10], 170, 350, fill=hair_c)
    elif hair == "bald":
        d.chord([hx - hr - 4, hy - 30, hx - 20, hy + 40], 90, 270, fill=hair_c)
    # sakal / bıyık
    if spec.get("beard"):
        d.polygon([(hx - 20, hy + 34), (hx + hr - 4, hy + 34), (hx + 40, hy + 120), (hx + 6, hy + 136), (hx - 30, hy + 90)], fill=hair_c)
    if spec.get("mustache") or spec.get("beard"):
        d.ellipse([hx + 24, hy + 36, hx + 74, hy + 54], fill=shade(hair_c, 0.9))
    # şapka
    hat = spec.get("hat")
    hc = col(spec.get("hat_color"), "red")
    if hat == "fez":
        d.polygon([(hx - 46, hy - hr + 10), (hx + 46, hy - hr + 10), (hx + 36, hy - hr - 70), (hx - 36, hy - hr - 70)], fill=hc)
        d.line([(hx, hy - hr - 70), (hx - 40, hy - hr - 30)], fill=INK, width=5)
        d.ellipse([hx - 50, hy - hr - 36, hx - 30, hy - hr - 16], fill=INK)
    elif hat == "cap":
        d.chord([hx - hr - 6, hy - hr - 20, hx + hr + 6, hy + 20], 180, 360, fill=hc)
        d.chord([hx + 10, hy - 34, hx + hr + 34, hy - 6], 180, 360, fill=shade(hc, 0.75))  # kısa siper
    elif hat == "crown":
        pts = [(hx - 56, hy - hr + 14), (hx - 56, hy - hr - 46), (hx - 28, hy - hr - 14), (hx, hy - hr - 56), (hx + 28, hy - hr - 14), (hx + 56, hy - hr - 46), (hx + 56, hy - hr + 14)]
        d.polygon(pts, fill=(236, 190, 60))
        d.ellipse([hx - 10, hy - hr - 22, hx + 10, hy - hr - 2], fill=COLORS["red"])
    elif hat == "beanie":
        d.chord([hx - hr - 6, hy - hr - 22, hx + hr + 6, hy + 30], 180, 360, fill=hc)
        d.ellipse([hx - 16, hy - hr - 46, hx + 16, hy - hr - 14], fill=hc)
    elif hat == "chef":
        d.rectangle([hx - 50, hy - hr - 40, hx + 50, hy - hr + 16], fill=(250, 250, 248))
        for dx in (-34, 0, 34):
            d.ellipse([hx + dx - 34, hy - hr - 96, hx + dx + 34, hy - hr - 28], fill=(250, 250, 248))
    # gözler (statik), ağız dinamik
    eyes = [(hx + 18, hy - 10), (hx + 52, hy - 12)]
    if spec.get("glasses"):
        for ex, ey in eyes:
            d.ellipse([ex - 18, ey - 18, ex + 18, ey + 18], outline=INK, width=5)
        d.line([(eyes[0][0] + 18, eyes[0][1]), (eyes[1][0] - 18, eyes[1][1])], fill=INK, width=5)
    for ex, ey in eyes:
        d.ellipse([ex - 7, ey - 9, ex + 7, ey + 9], fill=INK)
        d.ellipse([ex - 2, ey - 6, ex + 3, ey - 1], fill=(255, 255, 255))
        d.line([(ex - 12, ey - 24), (ex + 10, ey - 27)], fill=shade(hair_c, 0.8) if hair != "bald" else INK, width=6)
    # çubuk
    d.rectangle([PCX - 7, 700, PCX + 7, PH], fill=(120, 84, 54))
    torso = cutout(im)
    sleeve = c if outfit in ("vest", "suit", "dress", "robe", "apron") else c2
    arm_len = 150
    front = _arm(sleeve, skin, arm_len, hold=spec.get("holds"))
    back = _arm(shade(sleeve, 0.72), shade(skin, 0.85), arm_len)
    return PuppetParts(torso, front, back, (PCX + 30, sh_y + 14), (hx + 44, hy + 50), eyes, skin, "human", 700 - (hy - hr))


def build_animal(spec: dict) -> PuppetParts:
    kind = spec.get("type", "cat")
    c = col(spec.get("color"), {"cat": "orange", "dog": "brown", "fox": "orange", "owl": "brown", "crow": "black", "rabbit": "white"}[kind])
    belly = (244, 234, 216)
    im = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hx, hy, hr = PCX + 10, 330, 78
    if kind in ("owl", "crow"):
        d.ellipse([PCX - 110, 300, PCX + 110, 690], fill=c)
        d.ellipse([PCX - 64, 400, PCX + 70, 660], fill=belly if kind == "owl" else shade(c, 1.5))
        hy = 300
        d.ellipse([hx - 90, hy - 80, hx + 90, hy + 80], fill=c)
        if kind == "owl":
            d.polygon([(hx - 80, hy - 50), (hx - 60, hy - 120), (hx - 30, hy - 66)], fill=c)
            d.polygon([(hx + 80, hy - 50), (hx + 60, hy - 120), (hx + 30, hy - 66)], fill=c)
            for ex in (hx - 34, hx + 34):
                d.ellipse([ex - 30, hy - 30, ex + 30, hy + 30], fill=(250, 240, 200))
            eyes = [(hx - 30, hy - 4), (hx + 38, hy - 4)]
            mouth = (hx + 4, hy + 40)
        else:
            eyes = [(hx + 10, hy - 16), (hx + 46, hy - 16)]
            mouth = (hx + 96, hy + 10)
            d.polygon([(hx + 70, hy - 8), (hx + 140, hy + 10), (hx + 70, hy + 26)], fill=(70, 66, 70))
        for ex, ey in eyes:
            d.ellipse([ex - 12, ey - 12, ex + 12, ey + 12], fill=INK)
            d.ellipse([ex - 4, ey - 8, ex + 2, ey - 2], fill=(255, 255, 255))
        if kind == "owl":
            d.polygon([(hx - 6, hy + 8), (hx + 14, hy + 8), (hx + 4, hy + 34)], fill=(232, 170, 60))
        d.rectangle([PCX - 7, 680, PCX + 7, PH], fill=(120, 84, 54))
        torso = cutout(im)
        front = _arm(shade(c, 0.85), c, 150, kind="owl")
        back = _arm(shade(c, 0.6), c, 150, kind="owl")
        return PuppetParts(torso, front, back, (PCX + 70, 420), mouth, eyes, c, kind, 690 - (hy - 120))
    # dört ayaklı (oturan, ön patileri kol gibi)
    d.ellipse([PCX - 100, 400, PCX + 100, 700], fill=c)
    d.ellipse([PCX - 40, 440, PCX + 70, 680], fill=belly)
    if kind == "fox":  # gür kuyruk, beyaz uç
        d.ellipse([PCX - 200, 480, PCX - 50, 610], fill=c)
        d.ellipse([PCX - 206, 490, PCX - 150, 560], fill=belly)
    elif kind == "cat":  # ince uzun, yukarı kıvrık kuyruk
        d.rounded_rectangle([PCX - 190, 590, PCX - 60, 620], radius=15, fill=c)
        d.rounded_rectangle([PCX - 196, 420, PCX - 166, 615], radius=15, fill=c)
    elif kind == "dog":
        d.ellipse([PCX - 150, 520, PCX - 80, 560], fill=c)
    ear_c = shade(c, 0.8)
    if kind == "rabbit":
        for dx in (-40, 20):
            d.ellipse([hx + dx - 20, hy - hr - 150, hx + dx + 22, hy - hr + 20], fill=c)
            d.ellipse([hx + dx - 8, hy - hr - 130, hx + dx + 10, hy - hr], fill=(240, 180, 190))
    elif kind == "dog":
        d.ellipse([hx - hr - 20, hy - 50, hx - hr + 30, hy + 70], fill=ear_c)
    elif kind == "cat":
        for dx in (-46, 26):
            d.polygon([(hx + dx - 22, hy - hr + 34), (hx + dx + 2, hy - hr - 22), (hx + dx + 30, hy - hr + 30)], fill=c)
            d.polygon([(hx + dx - 10, hy - hr + 28), (hx + dx + 2, hy - hr - 4), (hx + dx + 18, hy - hr + 26)], fill=(240, 180, 170))
    else:
        for dx in (-50, 30):
            d.polygon([(hx + dx - 26, hy - hr + 30), (hx + dx + 4, hy - hr - 50), (hx + dx + 34, hy - hr + 24)], fill=c)
            d.polygon([(hx + dx - 12, hy - hr + 24), (hx + dx + 4, hy - hr - 24), (hx + dx + 20, hy - hr + 20)], fill=(240, 180, 170))
    d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=c)
    snout = (hx + 60, hy + 22)
    if kind == "fox":
        d.polygon([(hx + 20, hy - 6), (hx + hr + 64, hy + 26), (hx + 20, hy + 56)], fill=belly)
        snout = (hx + hr + 56, hy + 24)
    else:
        d.ellipse([hx + 20, hy, hx + 100, hy + 62], fill=belly)
    d.ellipse([snout[0] - 12, snout[1] - 10, snout[0] + 12, snout[1] + 8], fill=INK)
    eyes = [(hx + 8, hy - 22), (hx + 46, hy - 24)]
    for ex, ey in eyes:
        d.ellipse([ex - 10, ey - 12, ex + 10, ey + 12], fill=INK)
        d.ellipse([ex - 3, ey - 8, ex + 3, ey - 2], fill=(255, 255, 255))
    if kind == "cat":
        stripe = shade(c, 0.62)
        for i, dx in enumerate((-30, -6, 18)):
            d.line([(hx + dx, hy - hr + 6), (hx + dx + 6, hy - hr + 34)], fill=stripe, width=9)
        for i in range(4):
            y0 = 470 + i * 50
            d.arc([PCX - 100, y0 - 40, PCX - 20, y0 + 40], 120, 240, fill=stripe, width=10)
        for i in range(3):
            d.arc([PCX - 196 + i * 40, 500, PCX - 150 + i * 40, 600], 60, 120, fill=stripe, width=8)
        for s_ in (-1, 0, 1):
            d.line([(hx + 70, hy + 30), (hx + 130, hy + 26 + s_ * 14)], fill=INK, width=3)
            d.line([(hx + 14, hy + 30), (hx - 30, hy + 26 + s_ * 14)], fill=INK, width=3)
    d.rectangle([PCX - 7, 690, PCX + 7, PH], fill=(120, 84, 54))
    torso = cutout(im)
    front = _arm(c, belly, 120, kind="paw")
    back = _arm(shade(c, 0.75), shade(belly, 0.85), 120, kind="paw")
    return PuppetParts(torso, front, back, (PCX + 40, 470), (snout[0] - 14, snout[1] + 24), eyes, c, kind, 700 - (hy - hr))


class Puppet:
    def __init__(self, spec: dict):
        self.spec = spec
        self.id = spec["id"]
        self.name = spec.get("name", spec["id"])
        self.scale = 0.8 if spec.get("age") == "child" else (0.92 if spec.get("type") in ANIMALS else 1.0)
        self.parts = build_animal(spec) if spec.get("type") in ANIMALS else build_human(spec)
        self.color = col(spec.get("color"), "blue")
        self._arm_cache: dict = {}

    def _rot_arm(self, img, ang, which):
        key = (which, int(round(ang / 3)) * 3)
        if key not in self._arm_cache:
            self._arm_cache[key] = img.rotate(key[1], resample=Image.BICUBIC, center=(210, 210))
        return self._arm_cache[key]

    def render(self, front_ang, back_ang, mouth_open, blink, sad=False):
        p = self.parts
        layer = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
        sx, sy = p.shoulder
        layer.alpha_composite(self._rot_arm(p.back_arm, back_ang, "b"), (sx - 210 - 24, sy - 210))
        layer.alpha_composite(p.torso)
        d = ImageDraw.Draw(layer)
        mx, my = p.mouth
        if p.kind in ("human",):
            if mouth_open:
                d.ellipse([mx - 16, my - 10, mx + 16, my + 14], fill=(110, 30, 34))
                d.ellipse([mx - 9, my + 4, mx + 9, my + 13], fill=(220, 100, 110))
            elif sad:
                d.arc([mx - 18, my - 2, mx + 18, my + 20], 200, 340, fill=INK, width=5)
            else:
                d.arc([mx - 18, my - 18, mx + 18, my + 6], 20, 160, fill=INK, width=5)
        else:
            if mouth_open:
                d.ellipse([mx - 14, my - 8, mx + 14, my + 14], fill=(110, 30, 34))
            else:
                d.line([(mx - 14, my), (mx, my + 6), (mx + 14, my)], fill=INK, width=4)
        if blink:
            for ex, ey in p.eyes:
                d.ellipse([ex - 11, ey - 12, ex + 11, ey + 12], fill=p.skin)
                d.line([(ex - 10, ey + 2), (ex + 10, ey + 2)], fill=INK, width=4)
        layer.alpha_composite(self._rot_arm(p.front_arm, front_ang, "f"), (sx - 210, sy - 210))
        return layer


# ============================================================================ backdrops & props
def _paint_texture(img: Image.Image, seed=1, amount=10):
    rng = np.random.default_rng(seed)
    a = np.asarray(img, np.float32)
    n = rng.normal(0, amount * 0.5, a.shape[:2])[..., None]
    streak = np.array(Image.fromarray(rng.integers(0, 255, (a.shape[0] // 8, a.shape[1] // 2), dtype=np.uint8)).resize((a.shape[1], a.shape[0]), Image.BICUBIC), np.float32)[..., None]
    a = a + n + (streak / 255 - 0.5) * amount
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def paint_backdrop(name: str, light: str) -> Image.Image:
    bw, bh = OPEN_R - OPEN_L, BACK_BOT - BACK_TOP
    im = Image.new("RGB", (bw, bh), (200, 190, 170))
    d = ImageDraw.Draw(im)
    rng = random.Random(hash(name) % 1000)
    sky = {"day": ((150, 196, 226), (220, 232, 236)), "evening": ((236, 140, 96), (250, 206, 150)), "night": ((22, 30, 62), (50, 58, 102))}[light]
    def sky_grad(y1):
        for y in range(0, y1, 4):
            k = y / max(1, y1)
            d.rectangle([0, y, bw, y + 4], fill=tuple(int(sky[0][i] * (1 - k) + sky[1][i] * k) for i in range(3)))
    def stars(y1):
        if light == "night":
            for _ in range(40):
                x, y = rng.uniform(10, bw - 10), rng.uniform(10, y1 * 0.8)
                r = rng.uniform(1.5, 3.5)
                d.ellipse([x - r, y - r, x + r, y + r], fill=(250, 240, 200))
            d.ellipse([bw - 200, 50, bw - 110, 140], fill=(250, 236, 180))
        elif light == "day":
            for cx in (rng.uniform(80, 300), rng.uniform(500, 800)):
                for dx, r in ((-50, 38), (0, 54), (52, 40)):
                    d.ellipse([cx + dx - r, 90 - r * 0.7, cx + dx + r, 90 + r * 0.7], fill=(250, 250, 248))
        else:
            d.ellipse([bw * 0.62, bh * 0.36, bw * 0.62 + 150, bh * 0.36 + 150], fill=(250, 200, 110))
    lit = (252, 220, 120) if light == "night" else ((250, 214, 150) if light == "evening" else (170, 206, 230))
    if name in ("street", "village", "forest", "sea", "market", "school", "palace"):
        horizon = int(bh * (0.62 if name != "sea" else 0.55))
        sky_grad(horizon)
        stars(horizon)
        ground = {"street": (150, 140, 130), "village": (130, 160, 96), "forest": (90, 130, 80), "sea": (54, 106, 150),
                  "market": (176, 150, 116), "school": (150, 160, 120), "palace": (190, 170, 130)}[name]
        d.rectangle([0, horizon, bw, bh], fill=ground)
        if name == "street":
            x = -20
            while x < bw:
                w_ = rng.randint(150, 220)
                h_ = rng.randint(260, 420)
                c_ = rng.choice([(214, 170, 130), (190, 120, 100), (226, 206, 160), (160, 176, 186), (204, 150, 120)])
                d.rectangle([x, horizon - h_, x + w_, horizon + 10], fill=c_)
                d.polygon([(x - 10, horizon - h_), (x + w_ + 10, horizon - h_), (x + w_ / 2, horizon - h_ - 70)], fill=(150, 70, 56))
                for r_ in range(2):
                    for c2 in range(2):
                        wx, wy = x + 28 + c2 * (w_ / 2), horizon - h_ + 50 + r_ * 110
                        if wy + 70 < horizon - 20:
                            d.rectangle([wx, wy, wx + 50, wy + 70], fill=lit)
                            d.line([(wx + 25, wy), (wx + 25, wy + 70)], fill=shade(c_, 0.6), width=4)
                x += w_ + rng.randint(6, 30)
            for i in range(0, bw, 46):
                d.line([(i, horizon + 30), (i - 30, bh)], fill=shade(ground, 0.85), width=3)
        elif name == "village":
            for i, (cx, r) in enumerate([(160, 340), (560, 420), (900, 300)]):
                d.ellipse([cx - r, horizon - r * 0.45, cx + r, horizon + r * 0.6], fill=shade((130, 170, 100), 0.8 + 0.08 * i))
            for hx_ in (250, 640):
                d.rectangle([hx_, horizon - 120, hx_ + 140, horizon], fill=(230, 210, 170))
                d.polygon([(hx_ - 20, horizon - 120), (hx_ + 160, horizon - 120), (hx_ + 70, horizon - 200)], fill=(170, 80, 60))
                d.rectangle([hx_ + 50, horizon - 70, hx_ + 90, horizon], fill=(110, 76, 50))
                d.rectangle([hx_ + 100, horizon - 100, hx_ + 128, horizon - 70], fill=lit)
            d.polygon([(bw * 0.45, bh), (bw * 0.55, bh), (bw * 0.51, horizon), (bw * 0.49, horizon)], fill=(200, 180, 130))
        elif name == "forest":
            for layer_, k in ((0, 0.7), (1, 0.85), (2, 1.0)):
                for i in range(7):
                    cx = rng.uniform(-40, bw + 40)
                    h_ = rng.uniform(300, 520) * (0.7 + layer_ * 0.15)
                    tc = shade((60, 110, 70), k)
                    d.rectangle([cx - 12, horizon - h_ * 0.3, cx + 12, horizon + 20], fill=shade((100, 70, 50), k))
                    d.polygon([(cx - 110 * k, horizon - h_ * 0.25), (cx + 110 * k, horizon - h_ * 0.25), (cx, horizon - h_)], fill=tc)
        elif name == "sea":
            for i in range(6):
                yy = horizon + 40 + i * 60
                pts = [(x, yy + math.sin(x / 40 + i) * 8) for x in range(0, bw + 20, 20)]
                d.line(pts, fill=shade((54, 106, 150), 1.25), width=5)
            d.ellipse([bw * 0.1, horizon - 50, bw * 0.4, horizon + 30], fill=(120, 150, 100))
            d.polygon([(bw * 0.68, horizon + 10), (bw * 0.86, horizon + 10), (bw * 0.82, horizon + 40), (bw * 0.72, horizon + 40)], fill=(130, 80, 50))
            d.polygon([(bw * 0.77, horizon + 8), (bw * 0.77, horizon - 110), (bw * 0.85, horizon)], fill=(250, 246, 236))
        elif name == "market":
            for i in range(4):
                x = 30 + i * 230
                d.rectangle([x, horizon - 180, x + 200, horizon], fill=(170, 120, 80))
                for j in range(6):
                    d.polygon([(x - 10 + j * 37, horizon - 300), (x + 27 + j * 37, horizon - 300), (x + 8 + j * 37, horizon - 250)],
                              fill=(COLORS["red"] if (j + i) % 2 else (250, 244, 230)))
                d.rectangle([x - 10, horizon - 310, x + 210, horizon - 296], fill=(120, 80, 50))
                for j in range(5):
                    d.ellipse([x + 14 + j * 36, horizon - 210, x + 44 + j * 36, horizon - 180], fill=rng.choice([COLORS["red"], COLORS["orange"], COLORS["green"], (240, 210, 80)]))
        elif name == "school":
            d.rectangle([140, horizon - 380, bw - 140, horizon], fill=(206, 120, 96))
            d.polygon([(110, horizon - 380), (bw - 110, horizon - 380), (bw / 2, horizon - 480)], fill=(120, 60, 50))
            for r_ in range(2):
                for c2 in range(4):
                    d.rectangle([190 + c2 * 150, horizon - 330 + r_ * 150, 270 + c2 * 150, horizon - 240 + r_ * 150], fill=lit)
            d.ellipse([bw / 2 - 40, horizon - 460, bw / 2 + 40, horizon - 380], fill=(250, 246, 236))
        elif name == "palace":
            for tx in (120, bw - 220):
                d.rectangle([tx, horizon - 460, tx + 100, horizon], fill=(226, 210, 176))
                d.polygon([(tx - 20, horizon - 460), (tx + 120, horizon - 460), (tx + 50, horizon - 580)], fill=(60, 90, 150))
            d.rectangle([220, horizon - 320, bw - 220, horizon], fill=(236, 222, 190))
            d.ellipse([bw / 2 - 140, horizon - 470, bw / 2 + 140, horizon - 200], fill=(70, 110, 170))
            d.rectangle([bw / 2 - 60, horizon - 170, bw / 2 + 60, horizon], fill=(120, 80, 50))
    else:  # iç mekân: home, shop, office
        wall = {"home": (226, 196, 160), "shop": (200, 170, 120), "office": (190, 200, 206)}[name]
        d.rectangle([0, 0, bw, bh], fill=wall)
        if name == "home":
            for x in range(0, bw, 60):
                d.rectangle([x, 0, x + 24, bh], fill=shade(wall, 1.05))
        d.rectangle([0, bh - 160, bw, bh], fill=shade(wall, 0.75))
        wx, wy, ww, wh = (bw - 330, 120, 250, 280) if name != "office" else (120, 90, bw - 240, 330)
        d.rectangle([wx, wy, wx + ww, wy + wh], fill=sky[0])
        if light == "night":
            d.ellipse([wx + ww - 90, wy + 30, wx + ww - 30, wy + 90], fill=(250, 236, 180))
        if name == "office":
            for i in range(9):
                bx = wx + 10 + i * ww / 9
                bh_ = rng.uniform(80, 260)
                d.rectangle([bx, wy + wh - bh_, bx + ww / 9 - 8, wy + wh], fill=shade(sky[0], 0.55))
                for j in range(int(bh_ // 40)):
                    if rng.random() < 0.5:
                        d.rectangle([bx + 8, wy + wh - bh_ + 12 + j * 40, bx + 20, wy + wh - bh_ + 26 + j * 40], fill=lit)
        d.rectangle([wx, wy, wx + ww, wy + wh], outline=(110, 76, 50), width=14)
        d.line([(wx + ww / 2, wy), (wx + ww / 2, wy + wh)], fill=(110, 76, 50), width=10)
        if name == "home":
            d.polygon([(wx - 40, wy - 20), (wx + 40, wy - 20), (wx + 10, wy + wh + 30), (wx - 40, wy + wh + 30)], fill=COLORS["red"])
            d.polygon([(wx + ww + 40, wy - 20), (wx + ww - 40, wy - 20), (wx + ww - 10, wy + wh + 30), (wx + ww + 40, wy + wh + 30)], fill=COLORS["red"])
            d.rectangle([120, 160, 300, 320], fill=(240, 220, 170), outline=(150, 110, 60), width=12)
            d.ellipse([170, 200, 250, 280], fill=(130, 170, 110))
        if name == "shop":
            for r_ in range(3):
                y = 120 + r_ * 150
                d.rectangle([40, y + 100, 520, y + 116], fill=(120, 80, 50))
                x = 50
                while x < 500:
                    w_ = rng.randint(30, 60)
                    h_ = rng.randint(50, 96)
                    d.rectangle([x, y + 100 - h_, x + w_, y + 100], fill=rng.choice([COLORS["red"], COLORS["teal"], COLORS["ochre"], COLORS["green"], (240, 230, 200)]))
                    x += w_ + 8
        if name == "office":
            d.rectangle([60, bh - 380, 220, bh - 160], fill=(80, 90, 100))
            d.rectangle([80, bh - 360, 200, bh - 260], fill=(150, 200, 230))
    im = _paint_texture(im, seed=len(name), amount=14)
    # tuval dalgası (asılı fon bezi)
    a = np.asarray(im, np.float32)
    xs = np.arange(bw, dtype=np.float32)
    wave = 1 + 0.05 * np.sin(xs / 70)
    a *= wave[None, :, None]
    if light == "night":
        a *= np.array([0.78, 0.8, 0.95], np.float32)
    elif light == "evening":
        a *= np.array([1.0, 0.88, 0.78], np.float32)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def build_prop(p: dict) -> tuple[Image.Image, int]:
    """Karton sahne objesi -> (RGBA, taban y'si tuvalde)."""
    kind = p["kind"]
    im = Image.new("RGBA", (520, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    b = 560
    wood, dark = (164, 114, 70), (110, 74, 46)
    if kind == "wallet":  # yerde duran cüzdan, parlıyor (dikkat çeksin)
        d.ellipse([170, b - 70, 350, b - 10], fill=(255, 230, 140, 120))
        d.rounded_rectangle([200, b - 70, 320, b - 14], radius=10, fill=(120, 74, 40), outline=(70, 40, 20), width=5)
        d.rounded_rectangle([200, b - 70, 320, b - 44], radius=10, fill=(146, 92, 52))
        d.rectangle([224, b - 82, 290, b - 64], fill=(120, 190, 120))
    elif kind == "table":
        d.rectangle([60, b - 230, 460, b - 196], fill=wood)
        for x in (90, 410):
            d.rectangle([x - 12, b - 200, x + 12, b], fill=dark)
    elif kind == "counter":
        d.rectangle([40, b - 260, 480, b - 230], fill=dark)
        d.rectangle([60, b - 232, 460, b], fill=wood)
        d.rectangle([90, b - 200, 430, b - 30], outline=dark, width=8)
    elif kind == "chair":
        d.rectangle([200, b - 330, 222, b], fill=dark)
        d.rectangle([200, b - 160, 330, b - 136], fill=wood)
        d.rectangle([310, b - 140, 330, b], fill=dark)
        d.rectangle([200, b - 330, 222, b - 140], fill=wood)
    elif kind == "door":
        d.rectangle([150, b - 470, 370, b], fill=(150, 98, 60))
        d.rectangle([180, b - 440, 340, b - 260], outline=dark, width=8)
        d.rectangle([180, b - 230, 340, b - 30], outline=dark, width=8)
        d.ellipse([320, b - 250, 344, b - 226], fill=(230, 190, 80))
    elif kind == "chest":
        d.rectangle([120, b - 190, 400, b], fill=wood)
        d.chord([120, b - 290, 400, b - 110], 180, 360, fill=dark)
        d.rectangle([240, b - 210, 280, b - 160], fill=(230, 190, 80))
    elif kind == "sack":
        d.ellipse([150, b - 260, 370, b + 10], fill=(196, 160, 110))
        d.polygon([(220, b - 250), (300, b - 250), (330, b - 300), (190, b - 300)], fill=(196, 160, 110))
        d.line([(210, b - 250), (310, b - 250)], fill=dark, width=8)
    elif kind == "crate":
        d.rectangle([150, b - 220, 370, b], fill=wood)
        d.line([(150, b - 220), (370, b)], fill=dark, width=10)
        d.line([(370, b - 220), (150, b)], fill=dark, width=10)
    elif kind == "coins":
        for i in range(int(p.get("count", 9))):
            row = i // 4
            d.ellipse([140 + (i % 4) * 60 + row * 30, b - 60 - row * 46, 210 + (i % 4) * 60 + row * 30, b - 6 - row * 46], fill=(232, 186, 64), outline=(170, 120, 30), width=4)
    elif kind == "plant":
        d.polygon([(200, b - 140), (320, b - 140), (300, b), (220, b)], fill=(190, 100, 70))
        for ang in (-60, -30, 0, 30, 60):
            r = math.radians(ang - 90)
            d.ellipse([260 + math.cos(r) * 90 - 40, b - 180 + math.sin(r) * 120 - 24, 260 + math.cos(r) * 90 + 40, b - 180 + math.sin(r) * 120 + 24], fill=(80, 150, 80))
    elif kind == "bench":
        d.rectangle([40, b - 160, 480, b - 136], fill=wood)
        d.rectangle([40, b - 270, 480, b - 236], fill=wood)
        for x in (70, 450):
            d.rectangle([x - 10, b - 270, x + 10, b], fill=dark)
    elif kind == "sign":
        txt = str(p.get("text", ""))[:18]
        fnt = font(FONT_SERIF, 52)
        tw = max(160, d.textlength(txt, font=fnt) + 60)
        d.rectangle([250, b - 260, 270, b], fill=dark)
        d.rectangle([260 - tw / 2, b - 400, 260 + tw / 2, b - 270], fill=(236, 214, 164))
        d.text((260, b - 335), txt, font=fnt, fill=INK, anchor="mm")
    elif kind == "candle":
        d.rectangle([236, b - 150, 284, b], fill=(250, 244, 220))
        d.ellipse([244, b - 200, 276, b - 150], fill=(250, 190, 60))
    elif kind == "lantern":
        d.rectangle([250, b - 420, 270, b], fill=(60, 60, 66))
        d.rounded_rectangle([210, b - 520, 310, b - 410], radius=14, fill=(250, 214, 110), outline=(60, 60, 66), width=8)
    elif kind == "tree":
        d.rectangle([236, b - 300, 284, b], fill=dark)
        for dx, dy, r in ((0, -420, 130), (-100, -330, 100), (100, -330, 104)):
            d.ellipse([260 + dx - r, b + dy - r, 260 + dx + r, b + dy + r], fill=(84, 146, 84))
    elif kind == "well":
        d.rectangle([140, b - 170, 380, b], fill=(160, 160, 160))
        d.rectangle([150, b - 380, 166, b - 170], fill=dark)
        d.rectangle([354, b - 380, 370, b - 170], fill=dark)
        d.polygon([(110, b - 380), (410, b - 380), (260, b - 470)], fill=(170, 80, 60))
    elif kind == "bed":
        d.rectangle([30, b - 160, 490, b - 60], fill=(244, 240, 230))
        d.rectangle([30, b - 200, 60, b], fill=dark)
        d.rectangle([460, b - 130, 490, b], fill=dark)
        d.rectangle([60, b - 150, 160, b - 100], fill=(250, 250, 250))
        d.rectangle([160, b - 150, 460, b - 60], fill=COLORS["blue"])
    out = cutout(im, 6, 2)
    sc = float(p.get("scale", 1.0))
    if sc != 1.0:
        out = out.resize((int(520 * sc), int(600 * sc)), Image.LANCZOS)
    return out, int(b * sc)


# ============================================================================ static stage layers
_static: dict = {}


def curtain_panel(width, height, flip=False):
    key = ("panel", width, height, flip)
    if key in _static:
        return _static[key]
    xs = np.arange(width, dtype=np.float32)
    fold = 0.62 + 0.38 * (0.5 + 0.5 * np.sin(xs / 34.0 + (np.sin(xs / 90) * 1.5)))
    base = np.array([150, 22, 34], np.float32)
    arr = np.ones((height, width, 3), np.float32) * base * fold[None, :, None]
    yy = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    arr *= 0.85 + 0.25 * yy
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(img)
    edge = 0 if flip else width - 14
    d.rectangle([edge, 0, edge + 14, height], fill=(214, 170, 70))
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    _static[key] = img
    return img


def stage_frame() -> Image.Image:
    """Perde dışı sabit katman: duvar, yan perdeler, saçak, sahne önü, ön ışıklar, seyirci zemini."""
    if "frame" in _static:
        return _static["frame"]
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # duvar (sahne ağzı dışı)
    d.rectangle([0, 0, W, BACK_TOP + 40], fill=(44, 22, 26))
    d.rectangle([0, 0, OPEN_L, LIP_TOP], fill=(44, 22, 26))
    d.rectangle([OPEN_R, 0, W, LIP_TOP], fill=(44, 22, 26))
    # toplanmış yan perdeler
    left = curtain_panel(125, LIP_TOP - 120)
    im.alpha_composite(left, (-20, 120))
    im.alpha_composite(curtain_panel(125, LIP_TOP - 120, flip=True), (W - 105, 120))
    d.ellipse([-30, 760, 115, 820], fill=(214, 170, 70))
    d.ellipse([W - 115, 760, W + 30, 820], fill=(214, 170, 70))
    # saçak (valans)
    val = curtain_panel(W, 230)
    im.alpha_composite(val, (0, 60))
    for i in range(12):
        x0 = i * W / 12
        d.chord([x0 - 4, 230, x0 + W / 12 + 4, 330], 0, 180, fill=(140, 20, 32))
        d.arc([x0 - 4, 230, x0 + W / 12 + 4, 330], 0, 180, fill=(214, 170, 70), width=8)
    d.rectangle([0, 50, W, 76], fill=(214, 170, 70))
    d.rectangle([0, 0, W, 52], fill=(70, 40, 30))
    # sahne önü
    d.rectangle([0, LIP_TOP, W, LIP_BOT], fill=(96, 58, 36))
    d.rectangle([0, LIP_TOP, W, LIP_TOP + 10], fill=(150, 98, 60))
    d.rectangle([0, LIP_BOT - 8, W, LIP_BOT], fill=(60, 34, 22))
    for i in range(9):
        x = 90 + i * 112
        d.chord([x - 26, LIP_TOP - 18, x + 26, LIP_TOP + 26], 180, 360, fill=(255, 236, 170))
    # seyirci bölümü
    for y in range(LIP_BOT, H, 6):
        k = (y - LIP_BOT) / (H - LIP_BOT)
        d.rectangle([0, y, W, y + 6], fill=(int(28 - 10 * k), int(16 - 6 * k), int(22 - 8 * k)))
    _static["frame"] = im
    return im


def footlight_glow() -> Image.Image:
    if "glow" in _static:
        return _static["glow"]
    g = Image.new("L", (W, 420), 0)
    d = ImageDraw.Draw(g)
    for i in range(9):
        x = 90 + i * 112
        d.ellipse([x - 120, 260, x + 120, 520], fill=90)
    g = g.filter(ImageFilter.GaussianBlur(50))
    img = Image.new("RGBA", (W, 420), (255, 226, 160, 0))
    img.putalpha(g)
    _static["glow"] = img
    return img


def spot_mask() -> Image.Image:
    if "spot" in _static:
        return _static["spot"]
    sw, sh = 2 * W, 2 * H
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    r = np.sqrt(((xx - sw / 2) / 300) ** 2 + ((yy - sh / 2) / 560) ** 2)
    m = np.clip(1.25 - r, 0, 1) ** 0.8 * 255
    _static["spot"] = Image.fromarray(m.astype(np.uint8))
    return _static["spot"]


def floor_layer() -> Image.Image:
    if "floor" in _static:
        return _static["floor"]
    im = Image.new("RGBA", (W, FLOOR_FRONT - FLOOR_BACK + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    h = FLOOR_FRONT - FLOOR_BACK
    d.polygon([(OPEN_L, 0), (OPEN_R, 0), (W, h), (0, h)], fill=(150, 104, 66))
    for i in range(14):
        xb = OPEN_L + i * (OPEN_R - OPEN_L) / 13
        xf = i * W / 13
        d.line([(xb, 0), (xf, h)], fill=(110, 74, 46), width=3)
    for j in range(1, 4):
        y = h * (j / 4) ** 1.3
        d.line([(OPEN_L - (OPEN_L * y / h), y), (OPEN_R + (W - OPEN_R) * y / h, y)], fill=(126, 86, 54), width=2)
    _static["floor"] = im
    return im


# ============================================================================ captions
PUNCT = (".", ",", "!", "?", ":", ";", "…")
PARTICLES = {"da", "de", "ki", "mi", "mı", "mu", "mü"}


def chunk_words(words, max_chars=20):
    phrases, cur = [], []
    for i, w_ in enumerate(words):
        cur.append(i)
        if w_.endswith(PUNCT):
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)
    chunks = []
    for ph in phrases:
        chars = sum(len(words[j]) + 1 for j in ph)
        k = max(1, min(len(ph), math.ceil(chars / max_chars)))
        if k > 1 and len(ph) / k < 2:
            k = max(1, len(ph) // 2)
        per = len(ph) / k
        for g in range(k):
            part = ph[round(g * per):round((g + 1) * per)]
            if part:
                chunks.append(part)
    for a, b in zip(chunks, chunks[1:]):
        while len(b) > 1 and words[b[0]].strip(",.!?:;…").lower() in PARTICLES:
            a.append(b.pop(0))
        # sayı ile birimi ayırma ("2 / liraya")
        while len(b) > 1 and a and words[a[-1]].strip(",.!?").isdigit():
            a.append(b.pop(0))
    out = []
    for c in chunks:
        if out and len(c) == 1 and len(words[c[0]]) < 8 and len(out[-1]) < 4:
            out[-1] = out[-1] + c
        else:
            out.append(c)
    if len(out) > 1 and len(out[0]) == 1 and len(words[out[0][0]]) < 8 and len(out[1]) < 4:
        out[1] = out[0] + out[1]
        out.pop(0)
    return [c for c in out if c]


def draw_caption(img, scene, t, speaker_name, speaker_color):
    words = scene.words
    if not words:
        return
    d = ImageDraw.Draw(img)
    active = 0
    for i, ws in enumerate(scene.word_starts):
        if t >= ws - 0.02:
            active = i
    chunk = next((c for c in scene.chunks if active in c), scene.chunks[-1])
    shown = [i for i in chunk if i <= active]
    # konuşan etiketi
    tag = tr_upper(speaker_name)
    tf = font(FONT_BOLD, 38)
    tw = d.textlength(tag, font=tf)
    d.rounded_rectangle([W / 2 - tw / 2 - 26, CAP_Y - 34, W / 2 + tw / 2 + 26, CAP_Y + 30], radius=30, fill=speaker_color)
    light = (0.299 * speaker_color[0] + 0.587 * speaker_color[1] + 0.114 * speaker_color[2]) > 170  # açık renkte koyu yazı
    d.text((W / 2, CAP_Y - 2), tag, font=tf, fill=(30, 22, 20) if light else (255, 255, 255), anchor="mm",
           stroke_width=0 if light else 3, stroke_fill=shade(speaker_color, 0.5))
    size = 78
    fnt = font(FONT_SERIF, size)
    full = " ".join(words[i] for i in chunk)
    while d.textlength(full, font=fnt) > W - 110 and size > 52:
        size -= 4
        fnt = font(FONT_SERIF, size)
    # kelimeler söylendikçe belirir; görünen kısım ortalanır
    x = (W - d.textlength(" ".join(words[i] for i in shown), font=fnt)) / 2
    y = CAP_Y + 110
    for i in shown:
        w_ = words[i]
        if True:
            age = t - scene.word_starts[i]
            k = ease(age / 0.12)
            fill = (255, 246, 226) if i == active else (232, 222, 204)
            d.text((x, y + (1 - k) * 14), w_, font=fnt, fill=fill, anchor="lm", stroke_width=8, stroke_fill=(20, 10, 12))
        x += d.textlength(w_ + " ", font=fnt)


# ============================================================================ scenes
@dataclass
class TScene:
    text: str
    duration: float
    speaker: str = "narrator"
    backdrop: str = "street"
    light: str = "day"
    camera: str = "wide"
    on_stage: list = field(default_factory=list)
    props: list = field(default_factory=list)
    word_starts: list | None = None
    curtain_in: bool = False
    curtain_out: bool = False
    is_outro: bool = False

    def __post_init__(self):
        self.words = self.text.split()
        self.chunks = chunk_words(self.words) if self.words else []
        if not self.word_starts or len(self.word_starts) != len(self.words):
            weights = [len(w_) + 2 for w_ in self.words]
            tot, acc, speak = sum(weights) or 1, 0.05, max(0.1, self.duration - 0.35)
            self.word_starts = []
            for w_ in weights:
                self.word_starts.append(acc)
                acc += speak * w_ / tot
        self.word_ends = [b for b in self.word_starts[1:]] + [self.word_starts[-1] + 0.45] if self.words else []


def lint_scene(sd: dict, cast_ids: set) -> tuple[dict, list[str]]:
    sd = {**sd, "on_stage": [dict(p) for p in sd.get("on_stage", [])], "props": [dict(p) for p in sd.get("props", [])]}
    warn = []
    for k, allowed, default in (("backdrop", BACKDROPS, "street"), ("light", LIGHTS, "day"), ("camera", CAMERAS, "wide")):
        if sd.get(k) not in allowed:
            if sd.get(k) is not None:
                warn.append(f"geçersiz {k} '{sd.get(k)}' -> {default}")
            sd[k] = default
    keep = []
    for p in sd["on_stage"]:
        if p.get("id") not in cast_ids:
            warn.append(f"kadroda olmayan kukla '{p.get('id')}' atıldı")
            continue
        if p.get("action", "idle") not in ACTIONS:
            warn.append(f"geçersiz hareket '{p.get('action')}' -> idle")
            p["action"] = "idle"
        x = float(p.get("x", 0.5))
        if not 0.27 <= x <= 0.73:
            warn.append(f"'{p['id']}' x={x} perdeye çok yakın; 0.27-0.73'e çekildi")
            p["x"] = min(0.73, max(0.27, x))
        keep.append(p)
    if len(keep) > 3:
        warn.append("sahnede 3'ten fazla kukla; fazlası atıldı")
        keep = keep[:3]
    keep.sort(key=lambda p: p["x"])
    for a, b in zip(keep, keep[1:]):
        if b["x"] - a["x"] < 0.23 - 1e-6:  # kayan nokta payı
            warn.append(f"'{a['id']}' ve '{b['id']}' üst üste; aralandı")
            mid = (a["x"] + b["x"]) / 2
            a["x"], b["x"] = max(0.27, mid - 0.12), min(0.73, mid + 0.12)
    sd["on_stage"] = keep
    if sd.get("speaker", "narrator") not in ("narrator",) and sd.get("speaker") not in {p["id"] for p in keep}:
        warn.append(f"konuşan '{sd.get('speaker')}' sahnede değil")
    props = []
    for p in sd["props"]:
        if p.get("kind") not in PROP_KINDS:
            warn.append(f"geçersiz obje '{p.get('kind')}' atıldı")
            continue
        x = min(0.78, max(0.22, float(p.get("x", 0.5))))
        small = p["kind"] in ("coins", "sack", "crate", "chest", "candle", "wallet")
        margin = 0.10 if small else 0.12  # küçük objeler de kuklanın arkasında kaybolmasın
        for q in keep:
            if abs(q["x"] - x) < margin:
                nx = x + ((margin + 0.04) if x >= q["x"] else -(margin + 0.04))
                if 0.15 <= nx <= 0.85:
                    warn.append(f"'{p['kind']}' kuklanın {'arkasında kayboluyordu' if small else 'önünü kapatıyordu'}; kaydırıldı")
                    x = nx
        p["x"] = x
        if p["kind"] == "sign":
            if len(str(p.get("text", ""))) > 16:
                warn.append(f"tabela yazısı çok uzun: '{p.get('text')}'")
            placed = False
            # kadraj: yakın/orta planda kamera konuşana yaklaşır, tabela görünür pencerenin içinde kalmalı
            spx = next((q["x"] for q in keep if q["id"] == sd.get("speaker")), 0.5)
            win = {"close": 0.33, "medium": 0.42}.get(sd.get("camera"), 0.5)
            wl, wr = max(0.12, spx - win + 0.02), min(0.88, spx + win - 0.02)
            for sc_ in sorted({max(0.6, float(p.get("scale", 1.0))), 0.7, 0.6}, reverse=True):  # 0.6 altı telefonda okunmaz
                half = max(160, 30 * len(str(p.get("text", ""))) + 60) * sc_ / 2 / W
                lo, hi = wl + half, wr - half
                cands = sorted([lo + k * 0.01 for k in range(int((hi - lo) / 0.01) + 1)], key=lambda c: abs(c - x)) if hi >= lo else []
                for c in cands:
                    # kuklanın baktığı tarafta kolu uzanır: o tarafta daha geniş pay
                    if all(abs(q["x"] - c) >= half + (0.18 if (c - q["x"]) * (1 if q.get("face", 1) >= 0 else -1) > 0 else 0.12) for q in keep):
                        if abs(c - x) > 0.005 or sc_ != float(p.get("scale", 1.0)):
                            warn.append(f"tabela '{p.get('text')}' kuklaların arkasında kalıyordu; x={c:.2f}, ölçek {sc_}")
                        x, p["scale"], placed = c, sc_, True
                        break
                if placed:
                    break
            if not placed:  # yerde yer yok: kuklaların başının üstüne, iplerle asılı tabela
                p["hang"], p["scale"] = True, 0.75
                x = min(wr - 0.12, max(wl + 0.12, x))
                warn.append(f"tabela '{p.get('text')}' yerde sığmadığı için kuklaların üstüne asıldı (x={x:.2f})")
        p["x"] = x  # tabela için seçilen otomatik konum da kaydedilsin
        props.append(p)
    sd["props"] = props[:3]
    return sd, warn


class Theater:
    def __init__(self, cast: list[dict], scenes: list[TScene], banner: str = "", banner_color=None):
        self.banner = banner
        self.banner_color = banner_color
        self._banner = None
        self.puppets = {c["id"]: Puppet(c) for c in cast}
        self.scenes = scenes
        self._bd: dict = {}
        self._props: dict = {}
        self.starts = []
        acc = 0.0
        for s in scenes:
            self.starts.append(acc)
            acc += s.duration
        self.total = acc

    def backdrop(self, name, light):
        if (name, light) not in self._bd:
            self._bd[(name, light)] = paint_backdrop(name, light)
        return self._bd[(name, light)]

    def prop(self, p):
        key = (p["kind"], p.get("text"), p.get("count"), p.get("scale", 1.0))
        if key not in self._props:
            self._props[key] = build_prop(p)
        return self._props[key]

    def speaker_x(self, si):
        sc = self.scenes[si]
        for p in sc.on_stage:
            if p["id"] == sc.speaker:
                return p["x"]
        return None

    # -------------------------------------------------------------- puppet pose
    def pose(self, p, sc: TScene, t, idx):
        act = p.get("action", "idle")
        speaking = sc.speaker == p["id"] and not sc.is_outro
        ph = t * 2 * math.pi
        x = p["x"]
        dy, tilt = 0.0, math.sin(ph * 0.5 + idx) * 1.6
        front, back = 10 + 4 * math.sin(ph * 0.6 + idx), -8
        if act == "enter":
            side = p.get("from", "left" if x < 0.5 else "right")
            x0 = -0.15 if side == "left" else 1.15
            k = ease(t / 1.0)
            x = x0 + (x - x0) * k
            dy -= abs(math.sin(t * 9)) * 22 * (1 - k)
        elif act == "exit":
            side = p.get("to", "right" if x >= 0.5 else "left")
            x1 = 1.15 if side == "right" else -0.15
            k = ease((t - (sc.duration - 1.1)) / 1.0)
            x = x + (x1 - x) * k
            dy -= abs(math.sin(t * 9)) * 22 * (k > 0) * (k < 1)
        elif act == "walk":
            x0 = p.get("from_x", x)
            k = ease(t / 1.4)
            x = x0 + (x - x0) * k
            dy -= abs(math.sin(t * 8)) * 18 * (k < 1)
        if act == "point":  # hafif aşağı: komşu kuklanın yüzüne uzanmaz
            front = 80 + 3 * math.sin(ph)
        elif act == "think":
            front, tilt = 128, tilt + 4
        elif act == "cheer":  # ön el göğüs hizasında sallanır, arka kol yukarı: yüz ve elde tutulan eşya çakışmaz
            front, back = 76 + 14 * math.sin(ph * 3), -155 - 12 * math.sin(ph * 3)
            dy -= abs(math.sin(ph * 1.6)) * 26
        elif act == "sad":
            front, back, tilt, dy = 4, -2, tilt + 7, dy + 16
        elif act == "shake":
            tilt += math.sin(t * 70) * 4
            front, back = 70, -70
        elif act == "laugh":
            tilt = -6 + math.sin(t * 20) * 3
            dy -= abs(math.sin(t * 14)) * 12
            front, back = 50 + 20 * math.sin(t * 14), -50
        elif act == "bow":
            k = math.sin(min(1.0, t / 1.2) * math.pi)
            tilt += 24 * k
        elif act == "jump":
            dy -= math.sin(min(1.0, t / 0.5) * math.pi) * 70
        elif act == "give":
            front = 70
        if speaking:
            wi = None
            for i, (a_, b_) in enumerate(zip(sc.word_starts, sc.word_ends)):
                if a_ <= t < b_:
                    wi = i
            if wi is not None:
                a_, b_ = sc.word_starts[wi], sc.word_ends[wi]
                prog = (t - a_) / max(0.05, b_ - a_)
                dy -= math.sin(min(1, prog) * math.pi) * 10
                if act in ("idle", "talk"):  # konuşma jesti: göğüs hizasında, komşunun yüzüne uzanmaz
                    front = 32 + 24 * math.sin(wi * 1.7 + prog * 2)
        mouth = False
        if speaking:
            for a_, b_ in zip(sc.word_starts, sc.word_ends):
                if a_ <= t < a_ + (b_ - a_) * 0.62:
                    mouth = True
                    break
        blink = int((t + idx * 1.3) * 10) % 38 == 0
        return x, dy, tilt, front, back, mouth, blink, act == "sad"

    # -------------------------------------------------------------- frame
    def stage_image(self, si, t, gt):
        sc = self.scenes[si]
        img = Image.new("RGB", (W, H), (0, 0, 0))
        img.paste(self.backdrop(sc.backdrop, sc.light), (OPEN_L, BACK_TOP))
        img.paste(floor_layer(), (0, FLOOR_BACK), floor_layer())
        for p in sc.props:
            if p.get("hang"):
                continue
            pim, base = self.prop(p)
            x = int(p["x"] * W - pim.width / 2)
            y = int(FLOOR_BACK + 80 - base)
            sh = Image.new("RGBA", pim.size, (20, 10, 10, 0))
            sh.putalpha(pim.getchannel("A").point(lambda a: a * 0.35))
            img.paste(sh, (x + 14, y + 10), sh)
            img.paste(pim, (x, y), pim)
        for p in sc.props:  # asılı tabelalar: kuklaların üstünde
            if p.get("hang"):
                pim, base = self.prop(p)
                sc_ = float(p.get("scale", 0.75))
                top, bot = int((560 - 410) * sc_), int((560 - 260) * sc_)
                board = pim.crop((0, top, pim.width, bot))
                bx, by = int(p["x"] * W - board.width / 2), 420
                d0 = ImageDraw.Draw(img)
                bb = board.getbbox() or (0, 0, board.width, board.height)
                for rx in (bx + bb[0] + 20, bx + bb[2] - 20):
                    d0.line([(rx, BACK_TOP), (rx, by + 10)], fill=(70, 50, 36), width=5)
                img.paste(board, (bx, by), board)
        for idx, p in enumerate(sc.on_stage):
            pup = self.puppets[p["id"]]
            x, dy, tilt, front, back, mouth, blink, sad = self.pose(p, sc, t, idx)
            layer = pup.render(front, back, mouth, blink, sad)
            if p.get("face", 1) < 0:
                layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
                tilt = -tilt
            if pup.scale != 1.0:
                layer = layer.resize((int(PW * pup.scale), int(PH * pup.scale)), Image.BILINEAR)
            lw, lh = layer.size
            pivot = (lw / 2, PIV * pup.scale)
            if abs(tilt) > 0.3:
                layer = layer.rotate(tilt, resample=Image.BICUBIC, center=pivot)
            px, py = int(x * W - pivot[0]), int(PIVOT_Y + dy - pivot[1])
            # yumuşak, yakın gölge (keskin kopya "hayalet kukla" gibi görünüyordu)
            sa = layer.getchannel("A").resize((lw // 4, lh // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3)).resize((lw, lh), Image.BILINEAR)
            shadow = Image.new("RGBA", layer.size, (16, 8, 10, 0))
            shadow.putalpha(sa.point(lambda a: a * 0.28))
            img.paste(shadow, (px + 10, py + 4), shadow)
            img.paste(layer, (px, py), layer)
        frame = stage_frame()
        img.paste(frame, (0, 0), frame)
        glow = footlight_glow()
        img.paste(glow, (0, LIP_TOP - 300), glow)
        # spot ışık
        sx = self.speaker_x(si)
        if sx is not None and not sc.is_outro:
            prev = self.speaker_x(si - 1) if si > 0 else None
            k = ease(t / 0.35)
            cx = ((prev if prev is not None else sx) * (1 - k) + sx * k) * W
            stage = img.crop((0, 0, W, LIP_BOT))
            dark = stage.point(lambda v: int(v * 0.5))
            m = spot_mask().crop((int(W - cx), int(H - 820), int(W - cx) + W, int(H - 820) + LIP_BOT))
            img.paste(Image.composite(stage, dark, m), (0, 0))
        # ara perde (kapanma / açılma)
        close = 0.0
        if sc.curtain_in:
            close = max(close, 1 - ease(t / 0.4))
        if sc.curtain_out:
            close = max(close, ease((t - (sc.duration - 0.4)) / 0.4))
        if sc.is_outro:
            close = ease(t / 0.6)
        if close > 0.001:
            half = (OPEN_R - OPEN_L) / 2 + 40
            pw = int(half * close) + 1
            panel = curtain_panel(int(half) + 40, LIP_TOP - 70)
            img.paste(panel, (int(OPEN_L - 40 + pw - panel.width), 70), panel)
            rp = curtain_panel(int(half) + 40, LIP_TOP - 70, flip=True)
            img.paste(rp, (int(OPEN_R + 40 - pw), 70), rp)
            fr = stage_frame()
            img.paste(fr.crop((0, 0, W, 340)), (0, 0), fr.crop((0, 0, W, 340)))
        # seyirci kafaları
        d = ImageDraw.Draw(img)
        clap = sc.is_outro
        for i in range(11):
            hx = 40 + i * 100 + (i % 2) * 20
            bob = math.sin(gt * (9 if clap else 1.2) + i * 1.7) * (8 if clap else 3)
            hy = 1830 + (i % 3) * 18 + bob
            d.rounded_rectangle([hx - 82, hy + 40, hx + 82, H + 40], radius=50, fill=(40, 26, 30))
            d.ellipse([hx - 52, hy - 60, hx + 52, hy + 60], fill=(40, 26, 30))
            d.arc([hx - 52, hy - 60, hx + 52, hy + 60], 200, 340, fill=(96, 64, 56), width=5)
        return img

    def camera(self, img, si, t):
        sc = self.scenes[si]
        z, fx, fy = 1.0, W / 2, H / 2
        sx = self.speaker_x(si)
        if sc.camera == "medium":
            # konuşana ağırlık ver ama dinleyenleri de kadrajda tut
            # tüm kuklaları sığdıracak kadar yakınlaş (en fazla 1.16x), konuşana hafif ağırlık ver
            xs = [p["x"] for p in sc.on_stage] or [0.5]
            lo, hi = min(xs) * W - 190, max(xs) * W + 190
            z = max(1.0, min(1.16, W / max(1.0, hi - lo)))
            c = (lo + hi) / 2
            if sx is not None and (hi - lo) < 0.7 * W / z:  # yer varsa konuşana hafif yaklaş
                c = 0.8 * c + 0.2 * sx * W
            fx, fy = c, 860
        elif sc.camera == "close":
            z, fx, fy = 1.42, (sx if sx is not None else 0.5) * W, 800
        if sc.curtain_out and t > sc.duration - 0.45 or sc.is_outro:
            z = 1.0
        z += 0.012 * math.sin(t * 0.8)  # canlı kamera hissi
        if z <= 1.001:
            return img
        cw, ch = W / z, H / z
        left = max(0, min(W - cw, fx - cw / 2))
        top = max(0, min(H - ch, fy - ch / 2))
        out = img.resize((W, H), Image.BILINEAR, box=(left, top, left + cw, top + ch))
        # altyazı için alt bölgeyi karart
        band = Image.new("L", (W, H - 1330), 0)
        bd = ImageDraw.Draw(band)
        for y in range(band.height):
            bd.line([(0, y), (W, y)], fill=int(min(1, y / 160) * 200))
        out.paste((14, 8, 10), (0, 1330), band)
        return out

    def draw_banner(self, img):
        """Videonun merak başlığı: üstte, büyük, her planda okunur."""
        if not self.banner:
            return
        if self._banner is None:
            band = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
            d = ImageDraw.Draw(band)
            size = 76
            fnt = font(FONT_BOLD, size)
            lines = wrap(d, self.banner, fnt, W - 120)
            while len(lines) > 2 and size > 52:
                size -= 4
                fnt = font(FONT_BOLD, size)
                lines = wrap(d, self.banner, fnt, W - 120)
            h = 60 + len(lines) * int(size * 1.18)
            bc = tuple(self.banner_color) if self.banner_color else (150, 30, 40)
            d.rounded_rectangle([34, 40, W - 34, 40 + h], radius=26, fill=(250, 244, 228, 248), outline=bc + (255,), width=10)
            for i, l in enumerate(lines):
                d.text((W / 2, 40 + 30 + i * size * 1.18 + size / 2), l, font=fnt, fill=(40, 22, 20), anchor="mm")
            self._banner = band
        img.paste(self._banner, (0, 0), self._banner)

    def frame(self, si, t, gt, captions=True):
        sc = self.scenes[si]
        img = self.camera(self.stage_image(si, t, gt), si, t)
        if not sc.is_outro:
            self.draw_banner(img)
        if captions and not sc.is_outro:
            if sc.speaker == "narrator":
                name, c = "Anlatıcı", (150, 110, 40)
            else:
                pup = self.puppets[sc.speaker]
                name, c = pup.name, pup.color
            draw_caption(img, sc, t, name, c)
        if sc.is_outro:
            d = ImageDraw.Draw(img)
            k = ease((t - 0.5) / 0.4)
            if k > 0:
                f = font(FONT_SERIF, 96 * (0.8 + 0.2 * k))
                d.text((W / 2, 760), "Perde!", font=f, fill=(250, 220, 130), anchor="mm", stroke_width=6, stroke_fill=(60, 20, 20))
                d.text((W / 2, 880), "Yarın yeni oyun", font=font(FONT_SERIF, 52), fill=(250, 236, 210), anchor="mm", stroke_width=4, stroke_fill=(60, 20, 20))
        return img

    def render_video(self, audio_path, out_path):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-i", audio_path, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        gf = 0
        for si, sc in enumerate(self.scenes):
            for i in range(int(round(sc.duration * FPS))):
                proc.stdin.write(self.frame(si, i / FPS, gf / FPS).tobytes())
                gf += 1
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg başarısız")

    def preview(self, out_path, cols=4):
        tw, th, gap = 360, 640, 14
        n = len([s for s in self.scenes if not s.is_outro])
        rows = math.ceil(n / cols)
        sheet = Image.new("RGB", (cols * (tw + gap), rows * (th + gap)), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i in range(n):
            sc = self.scenes[i]
            t = min(sc.duration - 0.5, max(0.5, sc.duration * 0.6))
            img = self.frame(i, t, self.starts[i] + t)
            sheet.paste(img.resize((tw, th), Image.LANCZOS), ((i % cols) * (tw + gap), (i // cols) * (th + gap)))
            d.text(((i % cols) * (tw + gap) + 10, (i // cols) * (th + gap) + 8), f"#{i + 1}", font=font(FONT_BOLD, 34), fill=(255, 255, 0), stroke_width=4, stroke_fill=(0, 0, 0))
        sheet.save(out_path, quality=88)
        return out_path


def build(story: dict, durations: list[float], word_starts: list, outro=1.8):
    """story (cast + scenes) ve ses süreleri -> (Theater, uyarılar)"""
    cast_ids = {c["id"] for c in story["cast"]}
    scenes, warns = [], []
    for i, (sd, dur, ws) in enumerate(zip(story["scenes"], durations, word_starts)):
        fixed, w = lint_scene(sd, cast_ids)
        warns += [f"#{i + 1}: {x}" for x in w]
        scenes.append(TScene(text=sd["text"], duration=dur, speaker=fixed.get("speaker", "narrator"), backdrop=fixed["backdrop"],
                             light=fixed["light"], camera=fixed["camera"], on_stage=fixed["on_stage"], props=fixed["props"], word_starts=ws))
    for i, sc in enumerate(scenes):
        if i == 0:
            sc.curtain_in = True
        elif (sc.backdrop, sc.light) != (scenes[i - 1].backdrop, scenes[i - 1].light):
            sc.curtain_in = True
            scenes[i - 1].curtain_out = True
    last = scenes[-1]
    scenes.append(TScene(text="", duration=outro, speaker="narrator", backdrop=last.backdrop, light=last.light, camera="wide",
                         on_stage=[{**p, "action": "bow"} for p in last.on_stage], props=last.props, is_outro=True))
    return Theater(story["cast"], scenes, story.get("banner", ""), story.get("banner_color")), warns
