"""Kağıt-mürekkep (paper & ink) tarzı animasyon render motoru.

Videodaki analizden çıkan kurallar burada koda döküldü:
  * Ekranda sürekli hareket (yüksek "hareket oranı"): titreyen el çizimi çizgiler,
    nefes alan / hareket eden figürler, sallanan ağaçlar, kayan bulutlar.
  * ~2 saniyede bir görüntü değişimi: kamera vuruşları (punch-in / pan) ve sahne geçişleri.
  * Ses-görüntü senkronu: her sahnenin süresi o sahnenin seslendirme süresinden gelir.
  * Kelime kelime büyük altyazı (Shorts izleyicisinin çoğu sessiz izler).

Hiçbir ücretli araç yok: sadece Pillow + numpy + ffmpeg.
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
GROUND = int(H * 0.66)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

PALETTES = {
    "day": {"paper": (243, 234, 214), "ink": (34, 29, 25), "accent": (186, 48, 38), "soft": (120, 104, 86)},
    "dusk": {"paper": (238, 212, 178), "ink": (44, 28, 24), "accent": (200, 76, 30), "soft": (140, 96, 70)},
    "night": {"paper": (38, 44, 62), "ink": (232, 226, 210), "accent": (240, 196, 92), "soft": (140, 150, 170)},
}


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


# --------------------------------------------------------------------------- paper
_paper_cache: dict[str, Image.Image] = {}


def paper(mood: str) -> Image.Image:
    if mood in _paper_cache:
        return _paper_cache[mood]
    pal = PALETTES[mood]
    rng = np.random.default_rng(7)
    base = np.ones((H, W, 3), np.float32) * np.array(pal["paper"], np.float32)
    grain = rng.normal(0, 1, (H // 4, W // 4)).astype(np.float32)
    grain = np.array(Image.fromarray(((grain + 4) * 30).clip(0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), np.float32)
    grain = (grain / 255.0 - 0.47) * 18
    fine = rng.normal(0, 4, (H, W)).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vign = ((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.75)) ** 2
    shade = 1 - 0.35 * vign
    img = (base + (grain + fine)[..., None]) * shade[..., None]
    _paper_cache[mood] = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    return _paper_cache[mood]


# --------------------------------------------------------------------------- ink helpers
class Ink:
    """Titreyen ("boiling") el çizimi çizgiler. Titreşim her 3 karede bir değişir."""

    def __init__(self, d: ImageDraw.ImageDraw, frame: int, color, seed: int = 0):
        self.d = d
        self.color = color
        self.rng = random.Random(seed * 7919 + frame // 3)

    def j(self, amt=2.2):
        return self.rng.uniform(-amt, amt)

    def line(self, pts, width=9, color=None, jitter=2.2):
        c = color or self.color
        pts = [(x + self.j(jitter), y + self.j(jitter)) for x, y in pts]
        self.d.line(pts, fill=c, width=width, joint="curve")
        r = width / 2
        for x, y in (pts[0], pts[-1]):
            self.d.ellipse([x - r, y - r, x + r, y + r], fill=c)

    def circle(self, cx, cy, r, width=9, fill=None, color=None):
        c = color or self.color
        n = 28
        pts = []
        for i in range(n + 2):
            a = i / n * 2 * math.pi
            rr = r + self.j(1.6)
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        if fill is not None:
            self.d.polygon(pts, fill=fill)
        self.d.line(pts, fill=c, width=width, joint="curve")

    def poly(self, pts, fill=None, width=8, color=None):
        c = color or self.color
        pts = [(x + self.j(1.5), y + self.j(1.5)) for x, y in pts]
        if fill is not None:
            self.d.polygon(pts, fill=fill)
        self.d.line(pts + [pts[0]], fill=c, width=width, joint="curve")


# --------------------------------------------------------------------------- characters
@dataclass
class Char:
    x: float = 0.5           # 0..1 ekran genişliği
    pose: str = "stand"      # stand walk work sit laugh point think cheer sad run talk
    face: int = 1            # 1 sağa, -1 sola bakar
    scale: float = 1.0
    old: bool = False        # sakal + baston
    hat: bool = False
    holds: str | None = None # axe, book, coin, phone, sign
    label: str | None = None # figürün üstünde küçük etiket
    color: str | None = None # "accent" ise kırmızı mürekkep
    walk_to: float | None = None


def draw_char(ink: Ink, c: Char, t: float, pal, idx: int):
    s = 1.75 * c.scale
    x = c.x * W
    if c.walk_to is not None:
        x = (c.x + (c.walk_to - c.x) * ease(min(1, t / 2.5))) * W
    f = c.face
    col = pal["accent"] if c.color == "accent" else pal["ink"]
    ph = t * 2 * math.pi
    bob = math.sin(ph * 0.9 + idx) * 3 * s
    pose = c.pose
    if c.walk_to is not None and t < 2.5:
        pose = "walk"

    hip = [x, GROUND - 120 * s + bob]
    if pose == "sit":
        hip = [x, GROUND - 40 * s]
    neck = [hip[0], hip[1] - 115 * s]
    lean = 0.0
    if pose == "sad":
        lean = 0.15
    if pose == "laugh":
        lean = -0.18 + math.sin(ph * 4) * 0.08
    if pose == "run":
        lean = 0.25
    if pose == "work":
        lean = 0.12 + 0.12 * max(0, math.sin(ph * 1.3))
    neck[0] += f * math.sin(lean) * 115 * s
    head_r = 34 * s
    head = (neck[0] + f * math.sin(lean) * head_r, neck[1] - head_r - 4)
    if pose == "sad":
        head = (head[0] + f * 10 * s, head[1] + 14 * s)

    def limb(origin, a1, l1, a2, l2):
        k = (origin[0] + math.sin(a1) * l1 * f, origin[1] + math.cos(a1) * l1)
        e = (k[0] + math.sin(a2) * l2 * f, k[1] + math.cos(a2) * l2)
        return [tuple(origin), k, e], e

    # legs
    if pose == "sit":
        legs = [limb(hip, 1.5, 62 * s, 1.6, 60 * s), limb(hip, 1.35, 62 * s, 1.75, 58 * s)]
    elif pose in ("walk", "run"):
        sp = 3.2 if pose == "run" else 2.0
        amp = 0.7 if pose == "run" else 0.45
        a = math.sin(ph * sp) * amp
        legs = [limb(hip, a, 62 * s, a - 0.15 + max(0, -a) * 0.8, 60 * s),
                limb(hip, -a, 62 * s, -a - 0.15 + max(0, a) * 0.8, 60 * s)]
    elif pose == "cheer":
        jump = abs(math.sin(ph * 1.6)) * 22 * s
        hip[1] -= jump
        neck[1] -= jump
        head = (head[0], head[1] - jump)
        legs = [limb(hip, 0.25, 62 * s, -0.1, 60 * s), limb(hip, -0.25, 62 * s, 0.1, 60 * s)]
    else:
        legs = [limb(hip, 0.2, 62 * s, 0.05, 60 * s), limb(hip, -0.2, 62 * s, -0.05, 60 * s)]

    # arms
    sh = (neck[0] + (hip[0] - neck[0]) * 0.12, neck[1] + 14 * s)
    tool_hand = None
    tool_angle = 0.0
    if pose == "work":
        swing = (math.sin(ph * 1.3) + 1) / 2  # 0..1
        a = math.pi - 0.2 - swing * 2.3
        arms = [limb(sh, a, 52 * s, a + 0.3, 48 * s), limb(sh, a + 0.25, 52 * s, a + 0.5, 46 * s)]
        tool_hand, tool_angle = arms[0][1], a + 0.3
    elif pose == "point":
        arms = [limb(sh, 1.62, 54 * s, 1.58, 52 * s), limb(sh, -0.25, 52 * s, -0.1, 48 * s)]
    elif pose == "think":
        arms = [limb(sh, 0.5, 50 * s, math.pi - 0.3, 44 * s), limb(sh, -0.25, 52 * s, -0.05, 48 * s)]
    elif pose == "cheer":
        w = math.sin(ph * 3) * 0.25
        arms = [limb(sh, math.pi - 0.5 + w, 52 * s, math.pi - 0.3 + w, 48 * s),
                limb(sh, -(math.pi - 0.5) - w, 52 * s, -(math.pi - 0.3) - w, 48 * s)]
    elif pose == "laugh":
        arms = [limb(sh, 0.9, 50 * s, -0.6, 42 * s), limb(sh, -0.3, 50 * s, 0.9, 42 * s)]
    elif pose == "talk":
        g = math.sin(ph * 2.2) * 0.35
        arms = [limb(sh, 1.0 + g, 52 * s, 1.6 + g, 46 * s), limb(sh, -0.2, 52 * s, -0.05, 48 * s)]
    elif pose in ("walk", "run"):
        sp = 3.2 if pose == "run" else 2.0
        a = math.sin(ph * sp) * (0.9 if pose == "run" else 0.5)
        arms = [limb(sh, -a, 52 * s, -a + 0.4, 46 * s), limb(sh, a, 52 * s, a + 0.4, 46 * s)]
    elif pose == "sit":
        arms = [limb(sh, 0.6, 52 * s, 1.2, 46 * s), limb(sh, 0.3, 52 * s, 1.0, 46 * s)]
    elif pose == "sad":
        arms = [limb(sh, 0.12, 52 * s, 0.05, 48 * s), limb(sh, -0.05, 52 * s, 0.0, 48 * s)]
    else:
        sw = math.sin(ph * 0.9 + idx) * 0.06
        arms = [limb(sh, 0.18 + sw, 52 * s, 0.05, 48 * s), limb(sh, -0.18 - sw, 52 * s, -0.05, 48 * s)]

    lw = max(6, int(9 * s))
    for pts, _ in legs:
        ink.line(pts, lw, col)
    ink.line([tuple(hip), tuple(neck)], lw, col)
    for pts, _ in arms:
        ink.line(pts, lw, col)
    ink.circle(head[0], head[1], head_r, lw, fill=pal["paper"], color=col)
    # eyes
    ex = head[0] + f * 12 * s
    blink = (int(t * 10) + idx * 7) % 37 == 0
    if pose == "laugh":
        ink.line([(ex - 7 * s, head[1] - 4 * s), (ex, head[1] - 9 * s), (ex + 7 * s, head[1] - 4 * s)], max(3, int(4 * s)), col, 0.6)
        ink.line([(ex - 12 * s, head[1] + 10 * s), (ex + 6 * s, head[1] + 14 * s)], max(3, int(5 * s)), col, 0.6)
    elif not blink:
        ink.d.ellipse([ex - 4 * s, head[1] - 8 * s, ex + 4 * s, head[1]], fill=col)
    if pose == "sad":
        ink.line([(ex - 10 * s, head[1] + 16 * s), (ex + 4 * s, head[1] + 12 * s)], max(3, int(4 * s)), col, 0.5)
    if pose == "talk" and int(t * 8) % 2 == 0:
        ink.d.ellipse([ex - 6 * s, head[1] + 9 * s, ex + 4 * s, head[1] + 17 * s], fill=col)
    if c.old:
        bx = head[0] + f * 4 * s
        ink.poly([(bx - 22 * s, head[1] + 12 * s), (bx + 22 * s * f, head[1] + 14 * s), (bx + 6 * s * f, head[1] + 58 * s)], fill=pal["paper"], width=max(4, int(6 * s)), color=col)
        if pose not in ("work", "cheer", "sit"):
            hand = arms[1][1]
            ink.line([hand, (hand[0] - f * 6 * s, GROUND)], max(5, int(7 * s)), col)
    if c.hat:
        ink.poly([(head[0] - 44 * s, head[1] - 22 * s), (head[0] + 44 * s, head[1] - 22 * s),
                  (head[0] + 26 * s, head[1] - 64 * s), (head[0] - 26 * s, head[1] - 64 * s)], fill=col, width=4, color=col)
    hand = tool_hand or arms[0][1]
    if c.holds == "axe":
        ang = tool_angle if tool_hand else 0.6
        tip = (hand[0] + math.sin(ang) * 75 * s * f, hand[1] + math.cos(ang) * 75 * s)
        ink.line([hand, tip], max(6, int(8 * s)), pal["soft"])
        bl = (tip[0] + math.cos(ang) * 22 * s * f, tip[1] - math.sin(ang) * 22 * s)
        ink.poly([tip, bl, (bl[0] + math.sin(ang) * 26 * s * f, bl[1] + math.cos(ang) * 26 * s)], fill=pal["ink"], width=4)
    elif c.holds == "book":
        ink.poly([(hand[0] - 26 * s, hand[1] - 30 * s), (hand[0] + 26 * s, hand[1] - 30 * s), (hand[0] + 26 * s, hand[1] + 6 * s), (hand[0] - 26 * s, hand[1] + 6 * s)], fill=pal["accent"], width=5)
    elif c.holds == "coin":
        ink.circle(hand[0], hand[1] - 10 * s, 18 * s, 5, fill=(214, 172, 60))
    elif c.holds == "phone":
        ink.poly([(hand[0] - 14 * s, hand[1] - 40 * s), (hand[0] + 14 * s, hand[1] - 40 * s), (hand[0] + 14 * s, hand[1] + 4 * s), (hand[0] - 14 * s, hand[1] + 4 * s)], fill=pal["ink"], width=4)
    if c.label:
        fnt = ImageFont.truetype(FONT_BOLD, int(34 * min(1.2, s)))
        tw = ink.d.textlength(c.label, font=fnt)
        ly = head[1] - head_r - 70 * s - (40 if c.hat else 0)
        ink.d.text((head[0] - tw / 2, ly), c.label, font=fnt, fill=pal["soft"])
    return {"head": head, "hand": hand, "x": x}


# --------------------------------------------------------------------------- props
def draw_prop(ink: Ink, p: dict, t: float, pal, frame: int):
    kind = p.get("kind")
    x = p.get("x", 0.5) * W
    sc = p.get("scale", 1.0)
    col = pal["ink"]
    if kind == "tree":
        sway = math.sin(t * 1.4 + x) * 10 * sc
        ink.line([(x, GROUND), (x + sway * 0.3, GROUND - 260 * sc)], int(16 * sc), col)
        for i, (dx, dy, r) in enumerate([(0, -330, 95), (-70, -270, 70), (70, -275, 72), (0, -230, 60)]):
            ink.circle(x + dx * sc + sway, GROUND + dy * sc, r * sc, 7, fill=pal["soft"] if pal is PALETTES["night"] else (150, 160, 110))
    elif kind == "stump":
        ink.poly([(x - 50 * sc, GROUND), (x + 50 * sc, GROUND), (x + 42 * sc, GROUND - 50 * sc), (x - 42 * sc, GROUND - 50 * sc)], fill=(170, 130, 90), width=7)
    elif kind == "logs":
        n = int(p.get("count", 6))
        grow = p.get("grow", False)
        shown = n if not grow else max(1, int(n * ease(t / 3.0)))
        sc = sc * 1.3
        per_row = 6
        for i in range(shown):
            row, colm = divmod(i, per_row)
            cx = x + (colm - per_row / 2 + 0.5 + (row % 2) * 0.5) * 48 * sc
            cy = GROUND - 24 * sc - row * 40 * sc
            ink.circle(cx, cy, 22 * sc, 5, fill=(196, 150, 100))
            ink.circle(cx, cy, 8 * sc, 3)
    elif kind == "sun":
        y = p.get("y", 0.2) * H
        if p.get("setting"):
            y += ease(t / 4) * 0.25 * H
        r = 80 * sc
        ink.circle(x, y, r, 8, fill=(240, 190, 80))
        for i in range(12):
            a = i / 12 * 2 * math.pi + t * 0.5
            ink.line([(x + math.cos(a) * (r + 18), y + math.sin(a) * (r + 18)), (x + math.cos(a) * (r + 48), y + math.sin(a) * (r + 48))], 7, col)
    elif kind == "moon":
        y = p.get("y", 0.18) * H
        ink.circle(x, y, 70 * sc, 7, fill=pal["accent"])
        rng = random.Random(3)
        for _ in range(26):
            sx, sy = rng.uniform(0, W), rng.uniform(0, GROUND * 0.7)
            tw = 3 + 3 * (math.sin(t * 3 + sx) + 1)
            ink.d.ellipse([sx - tw, sy - tw, sx + tw, sy + tw], fill=pal["ink"])
    elif kind == "cloud":
        y = p.get("y", 0.15) * H
        cx = (x + t * 40 * p.get("speed", 1)) % (W + 400) - 200
        for dx, r in ((-60, 50), (0, 70), (65, 52)):
            ink.circle(cx + dx * sc, y, r * sc, 6, fill=pal["paper"])
    elif kind == "house":
        w, h = 260 * sc, 200 * sc
        ink.poly([(x - w / 2, GROUND), (x + w / 2, GROUND), (x + w / 2, GROUND - h), (x - w / 2, GROUND - h)], fill=(220, 200, 170), width=8)
        ink.poly([(x - w / 2 - 30, GROUND - h), (x + w / 2 + 30, GROUND - h), (x, GROUND - h - 140 * sc)], fill=pal["accent"], width=8)
        ink.poly([(x - 30 * sc, GROUND), (x + 30 * sc, GROUND), (x + 30 * sc, GROUND - 90 * sc), (x - 30 * sc, GROUND - 90 * sc)], fill=pal["ink"], width=6)
    elif kind == "mountain":
        ink.poly([(x - 380 * sc, GROUND), (x, GROUND - 520 * sc), (x + 380 * sc, GROUND)], fill=(200, 190, 170), width=8)
        ink.poly([(x - 95 * sc, GROUND - 390 * sc), (x, GROUND - 520 * sc), (x + 95 * sc, GROUND - 390 * sc)], fill=(250, 250, 245), width=6)
    elif kind == "coins":
        n = int(p.get("count", 5))
        for i in range(n):
            fall = ease((t - i * 0.25) / 0.6)
            cy = GROUND - 30 - (1 - fall) * 900 - (i // 5) * 0
            ink.circle(x + (i % 5 - 2) * 46 * sc, cy - (i // 5) * 30, 24 * sc, 5, fill=(214, 172, 60))
    elif kind == "clock":
        y = p.get("y", 0.3) * H
        r = 110 * sc
        ink.circle(x, y, r, 9, fill=pal["paper"])
        a = t * p.get("speed", 2.0)
        ink.line([(x, y), (x + math.sin(a) * r * 0.75, y - math.cos(a) * r * 0.75)], 8)
        ink.line([(x, y), (x + math.sin(a / 12) * r * 0.5, y - math.cos(a / 12) * r * 0.5)], 10)
    elif kind == "road":
        ink.line([(0, GROUND + 10), (W, GROUND + 10)], 6, pal["soft"])
        off = (t * 220) % 160
        for i in range(-1, 9):
            xx = i * 160 - off
            ink.line([(xx, GROUND + 90), (xx + 80, GROUND + 90)], 8, pal["soft"])
    elif kind == "birds":
        for i in range(4):
            bx = (x + t * 90 + i * 70) % (W + 200) - 100
            by = p.get("y", 0.25) * H + math.sin(t * 2 + i) * 20 + i * 25
            flap = math.sin(t * 9 + i) * 12
            ink.line([(bx - 22, by - flap), (bx, by), (bx + 22, by - flap)], 5, col)
    elif kind == "heart":
        y = p.get("y", 0.35) * H
        pulse = 1 + 0.1 * math.sin(t * 6)
        r = 60 * sc * pulse
        pts = []
        for i in range(40):
            a = i / 40 * 2 * math.pi
            hx = 16 * math.sin(a) ** 3
            hy = -(13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a))
            pts.append((x + hx * r / 16, y + hy * r / 16))
        ink.poly(pts, fill=pal["accent"], width=7)
    elif kind == "question":
        y = p.get("y", 0.3) * H
        fnt = ImageFont.truetype(FONT_SERIF, int(220 * sc))
        wob = math.sin(t * 3) * 8
        ink.d.text((x - 60 * sc, y - 120 * sc + wob), "?", font=fnt, fill=pal["accent"])
    elif kind == "bubble":
        # konuşma balonu
        y = p.get("y", 0.3) * H
        txt = p.get("text", "...")
        fnt = ImageFont.truetype(FONT_BOLD, 44)
        lines = wrap(ink.d, txt, fnt, 620)
        bw = max(ink.d.textlength(l, font=fnt) for l in lines) + 70
        bh = len(lines) * 56 + 50
        pop = ease_out_back(t / 0.35)
        bw, bh = bw * pop, bh * pop
        if pop > 0.05:
            ink.poly([(x - bw / 2, y - bh / 2), (x + bw / 2, y - bh / 2), (x + bw / 2, y + bh / 2), (x + 30 * p.get("tail", 1), y + bh / 2), (x + 70 * p.get("tail", 1), y + bh / 2 + 60), (x - 20 * p.get("tail", 1), y + bh / 2), (x - bw / 2, y + bh / 2)], fill=(255, 252, 244) if pal is not PALETTES["night"] else (60, 66, 88), width=6)
            if pop > 0.9:
                for i, l in enumerate(lines):
                    lw_ = ink.d.textlength(l, font=fnt)
                    ink.d.text((x - lw_ / 2, y - bh / 2 + 25 + i * 56), l, font=fnt, fill=pal["ink"])


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


# --------------------------------------------------------------------------- big text / counters
def draw_big(d: ImageDraw.ImageDraw, big: dict, t: float, pal):
    txt = str(big.get("text", ""))
    y = big.get("y", 0.2) * H
    size = big.get("size", 150)
    # sayaç: "count_to": 78 -> 0'dan 78'e sayar
    if "count_to" in big:
        n = int(big["count_to"] * ease(t / big.get("count_time", 1.6)))
        txt = big.get("prefix", "") + str(n) + big.get("suffix", "")
    pop = ease_out_back(t / 0.4)
    if pop <= 0.02:
        return
    fnt = ImageFont.truetype(FONT_SERIF, max(10, int(size * pop)))
    lines = wrap(d, txt, fnt, W - 140)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=fnt)
        yy = y + i * size * 1.1
        col = pal["accent"] if big.get("accent", True) else pal["ink"]
        d.text((W / 2 - tw / 2 + 6, yy + 6), l, font=fnt, fill=pal["soft"])
        d.text((W / 2 - tw / 2, yy), l, font=fnt, fill=col)


# --------------------------------------------------------------------------- captions
CAP_FONT = None


def draw_caption(img: Image.Image, words: list[str], active: int, pal):
    global CAP_FONT
    if CAP_FONT is None:
        CAP_FONT = ImageFont.truetype(FONT_BOLD, 78)
    d = ImageDraw.Draw(img)
    # aktif kelimenin bulunduğu 3'lü grup
    g0 = (active // 3) * 3
    group = words[g0:g0 + 3]
    if not group:
        return
    text_w = [d.textlength(w_, font=CAP_FONT) for w_ in group]
    gap = 24
    total = sum(text_w) + gap * (len(group) - 1)
    if total > W - 100:  # sığmazsa iki satır
        rows = [group[:2], group[2:]]
    else:
        rows = [group]
    y = int(H * 0.775)
    k = g0
    for row in rows:
        ws = [d.textlength(w_, font=CAP_FONT) for w_ in row]
        tot = sum(ws) + gap * (len(row) - 1)
        x = (W - tot) / 2
        for w_, ww in zip(row, ws):
            is_act = k == active
            fill = (255, 214, 64) if is_act else (255, 255, 255)
            yy = y - (8 if is_act else 0)
            d.text((x, yy), w_.upper() if False else w_, font=CAP_FONT, fill=fill, stroke_width=9, stroke_fill=(20, 16, 14))
            x += ww + gap
            k += 1
        y += 96


# --------------------------------------------------------------------------- scene / video
@dataclass
class Scene:
    text: str
    duration: float
    mood: str = "day"
    chars: list = field(default_factory=list)
    props: list = field(default_factory=list)
    big: dict | None = None
    camera: str = "auto"     # auto, push, pan, shake, still
    focus: float | None = None


def scene_from_dict(sd: dict, duration: float) -> Scene:
    return Scene(
        text=sd["text"],
        duration=duration,
        mood=sd.get("mood", "day"),
        chars=[Char(**c) for c in sd.get("chars", [])],
        props=sd.get("props", []),
        big=sd.get("big"),
        camera=sd.get("camera", "auto"),
        focus=sd.get("focus"),
    )


def word_times(text: str, dur: float, lead: float = 0.05):
    words = text.split()
    weights = [len(w_) + 2 for w_ in words]
    tot = sum(weights)
    times, acc = [], lead
    speak = max(0.1, dur - lead - 0.25)
    for w_ in weights:
        times.append(acc)
        acc += speak * w_ / tot
    return words, times


def render_frame(sc: Scene, t: float, frame: int, scene_idx: int, prev_img: Image.Image | None) -> Image.Image:
    pal = PALETTES.get(sc.mood, PALETTES["day"])
    img = paper(sc.mood).copy()
    d = ImageDraw.Draw(img)
    ink = Ink(d, frame, pal["ink"], seed=scene_idx)
    # zemin çizgisi
    ink.line([(-20, GROUND + 8), (W * 0.33, GROUND + 2), (W * 0.66, GROUND + 10), (W + 20, GROUND + 4)], 7, pal["ink"], 1.5)
    for p in sc.props:
        if p.get("kind") in ("bubble", "question", "heart"):
            continue
        draw_prop(ink, p, t, pal, frame)
    for i, c in enumerate(sc.chars):
        draw_char(ink, c, t, pal, i)
    for p in sc.props:
        if p.get("kind") in ("bubble", "question", "heart"):
            draw_prop(ink, p, max(0.0, t - p.get("delay", 0.25)), pal, frame)
    # kamera: ~2 sn'de bir değişen çerçeve (punch-in / pan)
    cam = sc.camera
    if cam == "auto":
        cam = ["push", "pan", "push", "still"][scene_idx % 4] if sc.duration > 1.2 else "still"
    beat = int(t / 2.0)
    z = 1.0
    cx, cy = W / 2, H / 2
    focus_x = (sc.focus if sc.focus is not None else (sc.chars[0].x if sc.chars else 0.5)) * W
    if cam == "push":
        z = 1.0 + 0.06 * ease(t / max(1.0, sc.duration)) + (0.07 if beat % 2 == 1 else 0.0) * ease((t - beat * 2.0) / 0.25)
        cx = W / 2 + (focus_x - W / 2) * 0.35 * (z - 1) * 6
        cy = H * 0.5 + (GROUND - 250 - H / 2) * 0.4 * (z - 1) * 5
    elif cam == "pan":
        z = 1.1
        cx = W / 2 + math.sin(t * 0.6) * 40 + (focus_x - W / 2) * 0.15
    elif cam == "shake":
        z = 1.06
        cx = W / 2 + math.sin(t * 40) * 10
        cy = H / 2 + math.cos(t * 37) * 10
    if z != 1.0 or cx != W / 2 or cy != H / 2:
        cw, ch = W / z, H / z
        left = max(0, min(W - cw, cx - cw / 2))
        top = max(0, min(H - ch, cy - ch / 2))
        img = img.resize((W, H), Image.BILINEAR, box=(left, top, left + cw, top + ch))

    if sc.big:
        draw_big(ImageDraw.Draw(img), sc.big, max(0.0, t - sc.big.get("delay", 0.0)), pal)

    # sahne geçişi: önceki karenin üstüne mürekkep dairesiyle açılış (ilk 0.3 sn)
    if prev_img is not None and t < 0.3:
        k = ease(t / 0.3)
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        r = k * math.hypot(W, H) * 0.6
        md.ellipse([W / 2 - r, H * 0.45 - r, W / 2 + r, H * 0.45 + r], fill=255)
        img = Image.composite(img, prev_img, mask)

    clean = img
    img = img.copy()
    words, times = word_times(sc.text, sc.duration)
    active = 0
    for i, tt in enumerate(times):
        if t >= tt:
            active = i
    draw_caption(img, words, active, pal)
    return clean, img


def render_video(scenes: list[Scene], audio_path: str, out_path: str, gap: float = 0.0):
    total_frames = sum(int(round(s.duration * FPS)) for s in scenes)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", audio_path,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
        out_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frame = 0
    prev_last = None
    for si, sc in enumerate(scenes):
        n = int(round(sc.duration * FPS))
        last = None
        for i in range(n):
            clean, img = render_frame(sc, i / FPS, frame, si, prev_last)
            proc.stdin.write(img.tobytes())
            frame += 1
            last = clean
        prev_last = last
        print(f"  sahne {si + 1}/{len(scenes)} ({sc.duration:.1f}s) bitti", flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg başarısız")
    return total_frames


def render_thumbnail(scene: Scene, title: str, out_path: str):
    base, _ = render_frame(Scene(text="", duration=scene.duration, mood=scene.mood, chars=scene.chars, props=scene.props, big=None, camera="still"), 1.2, 36, 0, None)
    d = ImageDraw.Draw(base)
    pal = PALETTES.get(scene.mood, PALETTES["day"])
    fnt = ImageFont.truetype(FONT_SERIF, 120)
    lines = wrap(d, title, fnt, W - 120)
    y = 170
    for l in lines:
        tw = d.textlength(l, font=fnt)
        d.text(((W - tw) / 2, y), l, font=fnt, fill=pal["accent"], stroke_width=10, stroke_fill=pal["paper"])
        y += 140
    base.convert("RGB").save(out_path, quality=92)
    return out_path
