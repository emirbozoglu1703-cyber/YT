"""Kıssa Defteri görsel motoru: "kesik kâğıt" (paper cut-out) stili.

Kanalın kendine ait görünümü: katman katman kesilmiş renkli kâğıt tepeler, renkli kıyafetli
karakterler, her katmanın altında kâğıt gölgesi ve hafif titreyen el çizimi kontur.

Kurgu kuralları kodda:
  * Sürekli hareket: nefes, yürüyüş, iş hareketleri, sallanan ağaçlar, kayan bulutlar, titreyen kontur.
  * ~2 sn'de bir görüntü değişimi: kamera vuruşları ve sahne geçişleri.
  * Ses/görüntü senkronu: sahne süresi = seslendirme süresi, altyazı = gerçek kelime zamanları.
  * lint_scene(): çakışan, ekrandan taşan, okunmayan öğeleri render öncesi yakalar ve düzeltir.
"""
from __future__ import annotations

import math
import random
import subprocess
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
GROUND = int(H * 0.66)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

MOODS = {
    "day": {"sky": ((250, 240, 216), (238, 214, 170)), "hills": [(222, 200, 160), (196, 166, 120), (160, 132, 92)],
            "ink": (40, 32, 26), "accent": (196, 62, 46), "soft": (120, 100, 80), "skin": (250, 228, 196),
            "foliage": (120, 156, 96), "bubble": (255, 251, 240)},
    "dusk": {"sky": ((250, 206, 150), (226, 132, 98)), "hills": [(198, 120, 100), (156, 86, 84), (110, 62, 68)],
             "ink": (46, 26, 26), "accent": (250, 210, 96), "soft": (90, 50, 50), "skin": (246, 214, 184),
             "foliage": (110, 112, 70), "bubble": (255, 244, 226)},
    "night": {"sky": ((24, 30, 56), (58, 62, 102)), "hills": [(66, 72, 112), (48, 52, 86), (32, 34, 60)],
              "ink": (236, 230, 214), "accent": (246, 200, 96), "soft": (170, 176, 200), "skin": (214, 204, 196),
              "foliage": (56, 84, 76), "bubble": (70, 76, 108)},
}
CLOTH = {"red": (196, 72, 56), "blue": (66, 104, 160), "green": (88, 140, 96), "ochre": (214, 160, 64),
         "purple": (132, 92, 152), "teal": (52, 138, 140), "gray": (128, 124, 120), "brown": (140, 96, 64)}
AUTO_CLOTH = ["blue", "red", "ochre", "green", "purple", "teal"]
POSES = {"stand", "walk", "work", "sit", "laugh", "point", "think", "cheer", "sad", "run", "talk"}
PROPS = {"tree", "stump", "logs", "sun", "moon", "cloud", "house", "mountain", "coins", "clock", "road", "birds",
         "heart", "question", "bubble", "bench", "stall", "lamp", "sea", "boat", "bag", "letter", "gift", "door"}
TALL = {"tree": 0.13, "house": 0.17, "stall": 0.15, "lamp": 0.05, "door": 0.08, "bench": 0.12}
OVERLAY = {"bubble", "question", "heart"}


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    return 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2


_font_cache: dict = {}


def font(path, size):
    k = (path, int(size))
    if k not in _font_cache:
        _font_cache[k] = ImageFont.truetype(path, int(size))
    return _font_cache[k]


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


# =========================================================================== layout lint
def lint_scene(sd: dict) -> tuple[dict, list[str]]:
    """Sahne düzenini kontrol eder, düzeltebildiğini düzeltir, uyarı listesini döndürür."""
    sd = {**sd, "chars": [dict(c) for c in sd.get("chars", [])], "props": [dict(p) for p in sd.get("props", [])]}
    warn = []
    if sd.get("mood") not in MOODS:
        sd["mood"] = "day"
    if len(sd["chars"]) > 3:
        warn.append(f"{len(sd['chars'])} karakter var, en fazla 3 olmalı; fazlası atıldı")
        sd["chars"] = sd["chars"][:3]
    for c in sd["chars"]:
        if c.get("pose") not in POSES:
            warn.append(f"bilinmeyen poz '{c.get('pose')}' -> stand")
            c["pose"] = "stand"
        x = float(c.get("x", 0.5))
        if not 0.15 <= x <= 0.85:
            warn.append(f"karakter x={x} kenara taşıyor, 0.15-0.85'e çekildi")
            c["x"] = min(0.85, max(0.15, x))
        if c.get("walk_to") is not None:
            c["walk_to"] = min(0.85, max(0.15, float(c["walk_to"])))
        c["scale"] = min(1.3, max(0.6, float(c.get("scale", 1.0))))
    # karakterler arası mesafe
    cs = sorted(sd["chars"], key=lambda c: c["x"])
    for a, b in zip(cs, cs[1:]):
        need = 0.17 * (a["scale"] + b["scale"]) / 2
        if b["x"] - a["x"] < need:
            warn.append(f"karakterler üst üste (x={a['x']:.2f}, {b['x']:.2f}); aralandı")
            mid = (a["x"] + b["x"]) / 2
            a["x"], b["x"] = max(0.15, mid - need / 2), min(0.85, mid + need / 2)
    keep = []
    for p in sd["props"]:
        k = p.get("kind")
        if k not in PROPS:
            warn.append(f"bilinmeyen obje '{k}' atıldı")
            continue
        if k == "bubble" and len(str(p.get("text", "")).split()) > 6:
            warn.append(f"balon metni çok uzun ({p.get('text')}); en fazla 6 kelime")
        if k in TALL:
            half = TALL[k] * p.get("scale", 1.0)
            x = float(p.get("x", 0.5))
            x = min(1 - half - 0.02, max(half + 0.02, x))
            for c in sd["chars"]:
                if abs(c["x"] - x) < half + 0.07:
                    nx = c["x"] + (half + 0.09) * (1 if c["x"] < 0.5 else -1)
                    if half + 0.02 <= nx <= 1 - half - 0.02:
                        warn.append(f"'{k}' karakterin üstüne biniyor; kaydırıldı")
                        x = nx
            p["x"] = x
        if k in OVERLAY:
            p["y"] = min(0.34, max(0.12, float(p.get("y", 0.27))))
        keep.append(p)
    sd["props"] = keep
    big = sd.get("big")
    if big:
        if "text" in big and len(str(big["text"]).split()) > 7:
            warn.append("büyük yazı 7 kelimeden uzun; kısaltılmalı")
        big["y"] = min(0.24, max(0.07, float(big.get("y", 0.14))))
        if any(p["kind"] in OVERLAY for p in keep):
            for p in keep:
                if p["kind"] in OVERLAY:
                    p["y"] = max(p["y"], big["y"] + 0.17)
    return sd, warn


# =========================================================================== backgrounds
_bg_cache: dict = {}


def background(mood: str, seed: int) -> Image.Image:
    key = (mood, seed % 7)
    if key in _bg_cache:
        return _bg_cache[key]
    m = MOODS[mood]
    top, bot = np.array(m["sky"][0], np.float32), np.array(m["sky"][1], np.float32)
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    sky = top * (1 - yy) + bot * yy
    img = Image.fromarray(np.broadcast_to(sky, (H, W, 3)).astype(np.uint8))
    rng = random.Random(seed % 7)
    shadow = tuple(max(0, int(c * 0.62)) for c in m["hills"][-1])
    # uzak -> yakın kâğıt tepeler
    bases = [GROUND - 330, GROUND - 170, GROUND - 40]
    for li, (col, base) in enumerate(zip(m["hills"], bases)):
        amp = [70, 55, 30][li]
        f1, f2, ph = rng.uniform(1.2, 2.2), rng.uniform(2.5, 4.0), rng.uniform(0, 6.28)
        pts = [(x, base - amp * (0.6 * math.sin(x / W * f1 * math.pi + ph) + 0.4 * math.sin(x / W * f2 * math.pi + ph * 2)))
               for x in range(-20, W + 40, 30)]
        poly = pts + [(W + 40, H), (-20, H)]
        d = ImageDraw.Draw(img)
        d.polygon([(x + 6, y + 10) for x, y in poly], fill=shadow)
        d.polygon(poly, fill=col)
    # zemin bandı (karakterlerin bastığı yer)
    d = ImageDraw.Draw(img)
    ground_col = tuple(int(c * 0.82) for c in m["hills"][-1])
    d.rectangle([0, GROUND, W, H], fill=ground_col)
    d.line([(0, GROUND), (W, GROUND)], fill=tuple(int(c * 0.6) for c in ground_col), width=6)
    # kâğıt dokusu
    nrng = np.random.default_rng(11)
    grain = nrng.normal(0, 6, (H, W, 1)).astype(np.float32)
    fib = np.array(Image.fromarray(nrng.integers(0, 255, (H // 6, W // 6), dtype=np.uint8)).resize((W, H), Image.BICUBIC), np.float32)[..., None]
    arr = np.asarray(img, np.float32) + grain + (fib / 255.0 - 0.5) * 10
    yy2, xx2 = np.mgrid[0:H, 0:W].astype(np.float32)
    vign = 1 - 0.28 * (((xx2 - W / 2) / (W * 0.8)) ** 2 + ((yy2 - H / 2) / (H * 0.8)) ** 2)
    arr *= vign[..., None]
    _bg_cache[key] = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    return _bg_cache[key]


# =========================================================================== ink
class Ink:
    """Her 3 karede bir değişen hafif titreşimli ("kaynayan") el çizimi kontur."""

    def __init__(self, d, frame, color, seed=0):
        self.d, self.color = d, color
        self.rng = random.Random(seed * 7919 + frame // 3)

    def oval(self, box, **kw):
        x0, y0, x1, y1 = box
        self.d.ellipse([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], **kw)

    def j(self, a=1.6):
        return self.rng.uniform(-a, a)

    def line(self, pts, width=9, color=None, jitter=1.6):
        c = color or self.color
        pts = [(x + self.j(jitter), y + self.j(jitter)) for x, y in pts]
        self.d.line(pts, fill=c, width=int(width), joint="curve")
        r = width / 2
        for x, y in (pts[0], pts[-1]):
            self.d.ellipse([x - r, y - r, x + r, y + r], fill=c)

    def circle(self, cx, cy, r, width=7, fill=None, color=None):
        c = color or self.color
        pts = [(cx + math.cos(i / 28 * 6.2832) * (r + self.j(1.2)), cy + math.sin(i / 28 * 6.2832) * (r + self.j(1.2))) for i in range(30)]
        if fill is not None:
            self.d.polygon(pts, fill=fill)
        if width:
            self.d.line(pts, fill=c, width=int(width), joint="curve")

    def poly(self, pts, fill=None, width=6, color=None):
        c = color or self.color
        pts = [(x + self.j(1.0), y + self.j(1.0)) for x, y in pts]
        if fill is not None:
            self.d.polygon(pts, fill=fill)
        if width:
            self.d.line(pts + [pts[0]], fill=c, width=int(width), joint="curve")


# =========================================================================== characters
@dataclass
class Char:
    x: float = 0.5
    pose: str = "stand"
    face: int = 1
    scale: float = 1.0
    old: bool = False
    woman: bool = False
    child: bool = False
    hat: bool = False
    holds: str | None = None
    label: str | None = None
    color: str | None = None
    walk_to: float | None = None


def draw_char(ink: Ink, c: Char, t: float, m: dict, idx: int):
    s = 1.7 * c.scale * (0.72 if c.child else 1.0)
    x = c.x * W
    pose = c.pose
    if c.walk_to is not None:
        k = ease(min(1, t / 2.4))
        x = (c.x + (c.walk_to - c.x) * k) * W
        if t < 2.4 and pose in ("stand", "walk", "run"):
            pose = "run" if pose == "run" else "walk"
    f = 1 if c.face >= 0 else -1
    ink_c = (40, 32, 26)
    cloth = CLOTH.get(c.color or AUTO_CLOTH[idx % len(AUTO_CLOTH)], CLOTH["blue"]) if c.color != "accent" else CLOTH["red"]
    ph = t * 2 * math.pi
    bob = math.sin(ph * 0.9 + idx) * 3 * s
    hip = [x, GROUND - 118 * s + bob]
    if pose == "sit":
        hip = [x, GROUND - 46 * s]
    lean = {"sad": 0.16, "run": 0.25}.get(pose, 0.0)
    if pose == "laugh":
        lean = -0.16 + math.sin(ph * 4) * 0.07
    if pose == "work":
        lean = 0.1 + 0.12 * max(0, math.sin(ph * 1.3))
    if c.old:
        lean += 0.08
    neck = [hip[0] + f * math.sin(lean) * 112 * s, hip[1] - 112 * s]
    hr = 33 * s
    head = [neck[0] + f * math.sin(lean) * hr, neck[1] - hr - 2]
    if pose == "sad":
        head = [head[0] + f * 9 * s, head[1] + 12 * s]

    def limb(o, a1, l1, a2, l2):
        k = (o[0] + math.sin(a1) * l1 * f, o[1] + math.cos(a1) * l1)
        e = (k[0] + math.sin(a2) * l2 * f, k[1] + math.cos(a2) * l2)
        return [tuple(o), k, e]

    if pose == "sit":
        legs = [limb(hip, 1.5, 60 * s, 0.1, 50 * s), limb(hip, 1.35, 60 * s, 0.2, 48 * s)]
    elif pose in ("walk", "run"):
        sp, amp = (3.2, 0.7) if pose == "run" else (2.0, 0.45)
        a = math.sin(ph * sp) * amp
        legs = [limb(hip, a, 60 * s, a - 0.15 + max(0, -a) * 0.8, 58 * s), limb(hip, -a, 60 * s, -a - 0.15 + max(0, a) * 0.8, 58 * s)]
    elif pose == "cheer":
        jump = abs(math.sin(ph * 1.6)) * 20 * s
        for p_ in (hip, neck, head):
            p_[1] -= jump
        legs = [limb(hip, 0.25, 60 * s, -0.1, 58 * s), limb(hip, -0.25, 60 * s, 0.1, 58 * s)]
    else:
        legs = [limb(hip, 0.18, 60 * s, 0.04, 58 * s), limb(hip, -0.18, 60 * s, -0.04, 58 * s)]

    sh = (neck[0] + (hip[0] - neck[0]) * 0.1, neck[1] + 16 * s)
    tool_ang = None
    if pose == "work":
        sw = (math.sin(ph * 1.3) + 1) / 2
        a = math.pi - 0.2 - sw * 2.3
        arms = [limb(sh, a, 50 * s, a + 0.3, 46 * s), limb(sh, a + 0.25, 50 * s, a + 0.5, 44 * s)]
        tool_ang = a + 0.3
    elif pose == "point":
        arms = [limb(sh, 1.62, 52 * s, 1.58, 50 * s), limb(sh, -0.25, 50 * s, -0.1, 46 * s)]
    elif pose == "think":
        arms = [limb(sh, 0.55, 48 * s, math.pi - 0.3, 42 * s), limb(sh, -0.25, 50 * s, -0.05, 46 * s)]
    elif pose == "cheer":
        w_ = math.sin(ph * 3) * 0.25
        arms = [limb(sh, math.pi - 0.5 + w_, 50 * s, math.pi - 0.3 + w_, 46 * s), limb(sh, -(math.pi - 0.5) - w_, 50 * s, -(math.pi - 0.3) - w_, 46 * s)]
    elif pose == "laugh":
        arms = [limb(sh, 0.9, 48 * s, -0.6, 40 * s), limb(sh, -0.3, 48 * s, 0.9, 40 * s)]
    elif pose == "talk":
        g = math.sin(ph * 2.2) * 0.35
        arms = [limb(sh, 1.0 + g, 50 * s, 1.6 + g, 44 * s), limb(sh, -0.2, 50 * s, -0.05, 46 * s)]
    elif pose in ("walk", "run"):
        sp = 3.2 if pose == "run" else 2.0
        a = math.sin(ph * sp) * (0.9 if pose == "run" else 0.5)
        arms = [limb(sh, -a, 50 * s, -a + 0.4, 44 * s), limb(sh, a, 50 * s, a + 0.4, 44 * s)]
    elif pose == "sit":
        arms = [limb(sh, 0.6, 50 * s, 1.2, 44 * s), limb(sh, 0.3, 50 * s, 1.0, 44 * s)]
    elif pose == "sad":
        arms = [limb(sh, 0.1, 50 * s, 0.04, 46 * s), limb(sh, -0.04, 50 * s, 0.0, 46 * s)]
    else:
        sw = math.sin(ph * 0.9 + idx) * 0.06
        if c.holds:
            arms = [limb(sh, 0.5 + sw, 50 * s, 1.4, 44 * s), limb(sh, -0.18 - sw, 50 * s, -0.05, 46 * s)]
        else:
            arms = [limb(sh, 0.18 + sw, 50 * s, 0.05, 46 * s), limb(sh, -0.18 - sw, 50 * s, -0.05, 46 * s)]

    lw = max(7, int(11 * s))
    trouser = tuple(int(v * 0.45) for v in cloth)
    for pts in legs:
        ink.line(pts, lw, trouser)
        ex, ey = pts[-1]
        ink.oval([ex - 10 * s, ey - 6 * s, ex + 12 * s * f, ey + 6 * s], fill=ink_c)
    # gövde (tunik / elbise)
    hw, shw = (30 if c.woman else 24) * s, 22 * s
    bottom = hip[1] + (40 * s if c.woman else 8 * s)
    if pose == "sit":
        bottom = hip[1] + 6 * s
    ink.poly([(sh[0] - shw, sh[1] - 4 * s), (sh[0] + shw, sh[1] - 4 * s), (hip[0] + hw, bottom), (hip[0] - hw, bottom)], fill=cloth, width=5, color=ink_c)
    for pts in arms:
        ink.line(pts, max(6, int(9 * s)), cloth)
        hx, hy = pts[-1]
        ink.oval([hx - 8 * s, hy - 8 * s, hx + 8 * s, hy + 8 * s], fill=m["skin"])
    # kafa
    if c.woman:
        ink.circle(head[0] - f * 6 * s, head[1] + 6 * s, hr * 1.12, 0, fill=(70, 44, 34))
        ink.poly([(head[0] - f * 30 * s, head[1]), (head[0] - f * 10 * s, head[1]), (head[0] - f * 14 * s, head[1] + 70 * s), (head[0] - f * 40 * s, head[1] + 62 * s)], fill=(70, 44, 34), width=0)
    ink.circle(head[0], head[1], hr, 5, fill=m["skin"], color=ink_c)
    if not c.woman and not c.hat and not c.old:
        ink.poly([(head[0] - hr * 0.95, head[1] - hr * 0.25), (head[0] - hr * 0.6, head[1] - hr * 1.0), (head[0] + hr * 0.6, head[1] - hr * 1.0), (head[0] + hr * 0.95, head[1] - hr * 0.3), (head[0] + hr * 0.3 * f, head[1] - hr * 0.62)], fill=(60, 40, 30), width=0)
    ex = head[0] + f * 12 * s
    blink = (int(t * 10) + idx * 7) % 37 == 0
    if pose == "laugh":
        ink.line([(ex - 7 * s, head[1] - 4 * s), (ex, head[1] - 9 * s), (ex + 7 * s, head[1] - 4 * s)], max(3, int(4 * s)), ink_c, 0.5)
        ink.d.chord([min(ex - 14 * s, ex + 8 * s), head[1] + 4 * s, max(ex - 14 * s, ex + 8 * s), head[1] + 20 * s], 0, 180, fill=ink_c)
    elif not blink:
        ink.oval([ex - 4 * s, head[1] - 8 * s, ex + 4 * s, head[1]], fill=ink_c)
    if pose == "sad":
        ink.d.arc([ex - 12 * s, head[1] + 10 * s, ex + 6 * s, head[1] + 22 * s], 200, 340, fill=ink_c, width=max(3, int(4 * s)))
    elif pose in ("cheer",) or (pose == "stand" and idx == 0 and c.holds in ("gift", "heart")):
        ink.d.arc([ex - 12 * s, head[1] + 2 * s, ex + 6 * s, head[1] + 16 * s], 20, 160, fill=ink_c, width=max(3, int(4 * s)))
    if pose == "talk" and int(t * 8) % 2 == 0:
        ink.oval([ex - 6 * s, head[1] + 9 * s, ex + 4 * s, head[1] + 17 * s], fill=ink_c)
    ink.oval([head[0] - f * 4 * s - 3, head[1] + 8 * s, head[0] - f * 4 * s + 9 * s, head[1] + 14 * s], fill=(236, 150, 130))  # yanak
    if c.old:
        ink.poly([(head[0] - 20 * s, head[1] + 10 * s), (head[0] + 24 * s * f, head[1] + 12 * s), (head[0] + 6 * s * f, head[1] + 56 * s)], fill=(244, 244, 238), width=3, color=ink_c)
        ink.poly([(head[0] - hr, head[1] - hr * 0.2), (head[0], head[1] - hr * 1.05), (head[0] + hr, head[1] - hr * 0.2)], fill=(232, 232, 226), width=0)
        if pose in ("stand", "talk", "point", "think", "sad", "walk"):
            hx, hy = arms[1][-1]
            ink.line([(hx, hy), (hx + f * 4, GROUND)], max(5, int(7 * s)), (110, 76, 50))
    if c.hat:
        ink.poly([(head[0] - 46 * s, head[1] - 20 * s), (head[0] + 46 * s, head[1] - 20 * s), (head[0] + 26 * s, head[1] - 60 * s), (head[0] - 26 * s, head[1] - 60 * s)], fill=(90, 60, 40), width=4, color=ink_c)
    hx, hy = arms[0][-1]
    if c.holds == "axe":
        ang = tool_ang if tool_ang is not None else 2.6
        tip = (hx + math.sin(ang) * 80 * s * f, hy + math.cos(ang) * 80 * s)
        ink.line([(hx, hy), tip], max(6, int(8 * s)), (150, 104, 60))
        nx, ny = math.cos(ang) * f, -math.sin(ang)
        bx, by = math.sin(ang) * f, math.cos(ang)
        ink.poly([(tip[0] - bx * 4 * s, tip[1] - by * 4 * s), (tip[0] + nx * 34 * s - bx * 14 * s, tip[1] + ny * 34 * s - by * 14 * s),
                  (tip[0] + nx * 36 * s + bx * 14 * s, tip[1] + ny * 36 * s + by * 14 * s), (tip[0] + bx * 8 * s, tip[1] + by * 8 * s)], fill=(170, 176, 186), width=4, color=ink_c)
    elif c.holds == "book":
        ink.poly([(hx - 26 * s, hy - 34 * s), (hx + 26 * s, hy - 34 * s), (hx + 26 * s, hy + 4 * s), (hx - 26 * s, hy + 4 * s)], fill=CLOTH["red"], width=4, color=ink_c)
    elif c.holds == "coin":
        ink.circle(hx, hy - 12 * s, 17 * s, 4, fill=(228, 182, 64), color=ink_c)
    elif c.holds == "phone":
        ink.poly([(hx - 13 * s, hy - 42 * s), (hx + 13 * s, hy - 42 * s), (hx + 13 * s, hy + 2 * s), (hx - 13 * s, hy + 2 * s)], fill=(30, 30, 36), width=3, color=ink_c)
        ink.d.rectangle([hx - 9 * s, hy - 37 * s, hx + 9 * s, hy - 4 * s], fill=(120, 190, 230))
    elif c.holds == "letter":
        ink.poly([(hx - 26 * s, hy - 30 * s), (hx + 26 * s, hy - 30 * s), (hx + 26 * s, hy + 4 * s), (hx - 26 * s, hy + 4 * s)], fill=(250, 246, 232), width=4, color=ink_c)
        ink.line([(hx - 26 * s, hy - 30 * s), (hx, hy - 10 * s), (hx + 26 * s, hy - 30 * s)], 3, ink_c, 0.3)
    elif c.holds == "gift":
        ink.poly([(hx - 26 * s, hy - 44 * s), (hx + 26 * s, hy - 44 * s), (hx + 26 * s, hy + 4 * s), (hx - 26 * s, hy + 4 * s)], fill=CLOTH["teal"], width=4, color=ink_c)
        ink.line([(hx, hy - 44 * s), (hx, hy + 4 * s)], 6, CLOTH["red"], 0.3)
    elif c.holds == "bag":
        ink.circle(hx, hy + 10 * s, 26 * s, 4, fill=(180, 140, 90), color=ink_c)
        ink.d.text((hx - 10 * s, hy - 6 * s), "₺", font=font(FONT_BOLD, 30 * s), fill=ink_c)
    if c.label:
        fnt = font(FONT_BOLD, 46 * min(1.15, s))
        tw = ink.d.textlength(c.label, font=fnt)
        ly = head[1] - hr - 66 * s - (40 * s if c.hat else 0)
        ink.d.text((head[0] - tw / 2, ly), c.label, font=fnt, fill=(255, 255, 255), stroke_width=5, stroke_fill=(40, 32, 26))


# =========================================================================== props
def draw_prop(ink: Ink, p: dict, t: float, m: dict, frame: int):
    k = p.get("kind")
    x = p.get("x", 0.5) * W
    sc = p.get("scale", 1.0)
    inkc = (40, 32, 26)
    if k == "tree":
        sway = math.sin(t * 1.4 + x) * 9 * sc
        ink.poly([(x - 14 * sc, GROUND), (x + 14 * sc, GROUND), (x + 8 * sc + sway * 0.3, GROUND - 250 * sc), (x - 8 * sc + sway * 0.3, GROUND - 250 * sc)], fill=(120, 84, 56), width=4, color=inkc)
        fol = m["foliage"]
        for dx, dy, r in [(0, -330, 95), (-72, -268, 70), (72, -272, 72), (0, -228, 60)]:
            ink.circle(x + dx * sc + sway, GROUND + dy * sc, r * sc, 4, fill=fol, color=tuple(int(v * 0.6) for v in fol))
    elif k == "stump":
        ink.poly([(x - 52 * sc, GROUND), (x + 52 * sc, GROUND), (x + 42 * sc, GROUND - 56 * sc), (x - 42 * sc, GROUND - 56 * sc)], fill=(150, 104, 66), width=5, color=inkc)
        ink.oval([x - 42 * sc, GROUND - 68 * sc, x + 42 * sc, GROUND - 44 * sc], fill=(214, 172, 120), outline=inkc, width=4)
    elif k == "logs":
        n = int(p.get("count", 6))
        shown = max(1, int(n * ease(t / 3.0))) if p.get("grow") else n
        for i in range(min(shown, 30)):
            row, col = divmod(i, 6)
            cx = x + (col - 2.5 + (row % 2) * 0.5) * 60 * sc
            cy = GROUND - 30 * sc - row * 50 * sc
            ink.circle(cx, cy, 28 * sc, 4, fill=(206, 160, 104), color=inkc)
            ink.circle(cx, cy, 10 * sc, 3, fill=None, color=(150, 104, 66))
    elif k == "sun":
        y = p.get("y", 0.16) * H + (ease(t / 4) * 0.2 * H if p.get("setting") else 0)
        r = 78 * sc
        for i in range(12):
            a = i / 12 * 6.2832 + t * 0.4
            ink.poly([(x + math.cos(a - 0.12) * (r + 10), y + math.sin(a - 0.12) * (r + 10)), (x + math.cos(a) * (r + 50), y + math.sin(a) * (r + 50)), (x + math.cos(a + 0.12) * (r + 10), y + math.sin(a + 0.12) * (r + 10))], fill=(246, 196, 82), width=0)
        ink.circle(x, y, r, 0, fill=(246, 186, 70))
    elif k == "moon":
        y = p.get("y", 0.14) * H
        rng = random.Random(3)
        for _ in range(24):  # yıldızlar sadece üst gökyüzünde
            sx, sy = rng.uniform(30, W - 30), rng.uniform(40, H * 0.30)
            r_ = 2.5 + 2.5 * (math.sin(t * 3 + sx) + 1)
            ink.oval([sx - r_, sy - r_, sx + r_, sy + r_], fill=(250, 240, 200))
        ink.circle(x, y, 70 * sc, 0, fill=(250, 232, 170))
        ink.circle(x + 28 * sc, y - 14 * sc, 60 * sc, 0, fill=MOODS["night"]["sky"][0])
    elif k == "cloud":
        y = p.get("y", 0.15) * H
        cx = (x + t * 36 * p.get("speed", 1)) % (W + 400) - 200
        for dx, dy, r in ((-62, 8, 48), (0, -10, 66), (64, 6, 50)):
            ink.circle(cx + dx * sc + 6, y + dy * sc + 8, r * sc, 0, fill=(200, 186, 160))
        for dx, dy, r in ((-62, 8, 48), (0, -10, 66), (64, 6, 50)):
            ink.circle(cx + dx * sc, y + dy * sc, r * sc, 0, fill=(255, 252, 244))
    elif k == "house":
        w_, h_ = 280 * sc, 210 * sc
        ink.poly([(x - w_ / 2, GROUND), (x + w_ / 2, GROUND), (x + w_ / 2, GROUND - h_), (x - w_ / 2, GROUND - h_)], fill=(232, 208, 172), width=5, color=inkc)
        ink.poly([(x - w_ / 2 - 30, GROUND - h_), (x + w_ / 2 + 30, GROUND - h_), (x, GROUND - h_ - 140 * sc)], fill=CLOTH["red"], width=5, color=inkc)
        ink.poly([(x - 30 * sc, GROUND), (x + 30 * sc, GROUND), (x + 30 * sc, GROUND - 96 * sc), (x - 30 * sc, GROUND - 96 * sc)], fill=(110, 74, 50), width=4, color=inkc)
        lit = (250, 220, 120) if m is MOODS["night"] else (150, 196, 220)
        ink.poly([(x + 60 * sc, GROUND - 150 * sc), (x + 110 * sc, GROUND - 150 * sc), (x + 110 * sc, GROUND - 105 * sc), (x + 60 * sc, GROUND - 105 * sc)], fill=lit, width=4, color=inkc)
    elif k == "mountain":
        ink.poly([(x - 380 * sc, GROUND), (x, GROUND - 520 * sc), (x + 380 * sc, GROUND)], fill=tuple(int(v * 0.9) for v in m["hills"][1]), width=5, color=inkc)
        ink.poly([(x - 95 * sc, GROUND - 390 * sc), (x, GROUND - 520 * sc), (x + 95 * sc, GROUND - 390 * sc), (x + 30 * sc, GROUND - 410 * sc), (x - 20 * sc, GROUND - 380 * sc)], fill=(250, 250, 245), width=0)
    elif k == "coins":
        n = int(p.get("count", 5))
        for i in range(min(n, 20)):
            fall = ease((t - i * 0.2) / 0.6)
            cy = GROUND - 26 - (1 - fall) * 900 - (i // 5) * 30
            ink.circle(x + (i % 5 - 2) * 50 * sc, cy, 25 * sc, 4, fill=(232, 186, 66), color=inkc)
    elif k == "clock":
        y = p.get("y", 0.24) * H
        r = 100 * sc
        ink.circle(x, y, r, 7, fill=(255, 252, 244), color=inkc)
        a = t * p.get("speed", 2.0)
        ink.line([(x, y), (x + math.sin(a) * r * 0.75, y - math.cos(a) * r * 0.75)], 7, inkc, 0.5)
        ink.line([(x, y), (x + math.sin(a / 12) * r * 0.5, y - math.cos(a / 12) * r * 0.5)], 9, inkc, 0.5)
    elif k == "road":
        off = (t * 220) % 160
        for i in range(-1, 9):
            xx = i * 160 - off
            ink.d.rectangle([xx, GROUND + 70, xx + 80, GROUND + 82], fill=(236, 226, 200))
    elif k == "birds":
        for i in range(4):
            bx = (x + t * 90 + i * 70) % (W + 200) - 100
            by = p.get("y", 0.2) * H + math.sin(t * 2 + i) * 20 + i * 25
            fl = math.sin(t * 9 + i) * 12
            ink.line([(bx - 22, by - fl), (bx, by), (bx + 22, by - fl)], 5, inkc, 0.4)
    elif k == "heart":
        y = p.get("y", 0.3) * H
        r = 60 * sc * (1 + 0.1 * math.sin(t * 6)) * ease_out_back(t / 0.4)
        pts = []
        for i in range(40):
            a = i / 40 * 6.2832
            pts.append((x + 16 * math.sin(a) ** 3 * r / 16, y - (13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)) * r / 16))
        if r > 2:
            ink.poly(pts, fill=CLOTH["red"], width=5, color=inkc)
    elif k == "question":
        y = p.get("y", 0.27) * H
        pop = ease_out_back(t / 0.4)
        if pop > 0.05:
            fnt = font(FONT_SERIF, 200 * sc * pop)
            ink.d.text((x, y + math.sin(t * 3) * 8), "?", font=fnt, fill=m["accent"], anchor="mm", stroke_width=6, stroke_fill=inkc)
    elif k == "bubble":
        y = p.get("y", 0.27) * H
        fnt = font(FONT_BOLD, 54)
        lines = wrap(ink.d, str(p.get("text", "...")), fnt, 640)
        bw = max(ink.d.textlength(l, font=fnt) for l in lines) + 80
        bh = len(lines) * 66 + 56
        pop = ease_out_back(t / 0.35)
        x = min(W - bw / 2 - 30, max(bw / 2 + 30, x))
        if pop > 0.05:
            tail = 1 if p.get("tail", 1) >= 0 else -1
            bw2, bh2 = bw * pop, bh * pop
            ink.poly([(x - bw2 / 2, y - bh2 / 2), (x + bw2 / 2, y - bh2 / 2), (x + bw2 / 2, y + bh2 / 2), (x + 30 * tail, y + bh2 / 2),
                      (x - 20 * tail, y + bh2 / 2 + 60), (x - 30 * tail, y + bh2 / 2), (x - bw2 / 2, y + bh2 / 2)], fill=m["bubble"], width=6, color=inkc)
            if pop > 0.9:
                txtc = (40, 32, 26) if m is not MOODS["night"] else (240, 236, 224)
                for i, l in enumerate(lines):
                    ink.d.text((x, y - bh / 2 + 28 + i * 66 + 30), l, font=fnt, fill=txtc, anchor="mm")
    elif k == "bench":
        ink.poly([(x - 130 * sc, GROUND - 70 * sc), (x + 130 * sc, GROUND - 70 * sc), (x + 130 * sc, GROUND - 52 * sc), (x - 130 * sc, GROUND - 52 * sc)], fill=(150, 104, 66), width=4, color=inkc)
        ink.poly([(x - 130 * sc, GROUND - 140 * sc), (x + 130 * sc, GROUND - 140 * sc), (x + 130 * sc, GROUND - 118 * sc), (x - 130 * sc, GROUND - 118 * sc)], fill=(150, 104, 66), width=4, color=inkc)
        for dx in (-110, 110):
            ink.line([(x + dx * sc, GROUND - 52 * sc), (x + dx * sc, GROUND)], 8, inkc, 0.5)
    elif k == "stall":
        w_ = 300 * sc
        ink.poly([(x - w_ / 2, GROUND), (x + w_ / 2, GROUND), (x + w_ / 2, GROUND - 120 * sc), (x - w_ / 2, GROUND - 120 * sc)], fill=(170, 120, 76), width=5, color=inkc)
        for i in range(6):
            cx = x - w_ / 2 + (i + 0.5) * w_ / 6
            ink.circle(cx, GROUND - 138 * sc, 20 * sc, 3, fill=[CLOTH["red"], CLOTH["ochre"], CLOTH["green"]][i % 3], color=inkc)
        for dx in (-w_ / 2 + 10, w_ / 2 - 10):
            ink.line([(x + dx, GROUND - 120 * sc), (x + dx, GROUND - 300 * sc)], 7, inkc, 0.5)
        for i in range(6):
            x0 = x - w_ / 2 - 20 + i * (w_ + 40) / 6
            ink.poly([(x0, GROUND - 300 * sc), (x0 + (w_ + 40) / 6, GROUND - 300 * sc), (x0 + (w_ + 40) / 12, GROUND - 250 * sc)], fill=CLOTH["red"] if i % 2 else (250, 246, 232), width=3, color=inkc)
    elif k == "lamp":
        ink.line([(x, GROUND), (x, GROUND - 420 * sc)], 10, (50, 50, 56), 0.5)
        ink.poly([(x - 34 * sc, GROUND - 420 * sc), (x + 34 * sc, GROUND - 420 * sc), (x + 20 * sc, GROUND - 470 * sc), (x - 20 * sc, GROUND - 470 * sc)], fill=(50, 50, 56), width=0)
        if m is MOODS["night"] or m is MOODS["dusk"]:
            glow = 60 + 6 * math.sin(t * 5)
            ink.circle(x, GROUND - 410 * sc, glow * sc, 0, fill=(250, 224, 140))
    elif k == "sea":
        for row in range(3):
            yb = GROUND + 20 + row * 60
            pts = [(xx, yb + math.sin(xx / 60 + t * 2 + row) * 10) for xx in range(-20, W + 40, 20)]
            ink.poly(pts + [(W + 40, H), (-20, H)], fill=[(84, 140, 176), (66, 118, 156), (50, 96, 136)][row], width=0)
    elif k == "boat":
        yb = GROUND + 30 + math.sin(t * 2) * 8
        ink.poly([(x - 130 * sc, yb - 50 * sc), (x + 130 * sc, yb - 50 * sc), (x + 90 * sc, yb + 10 * sc), (x - 90 * sc, yb + 10 * sc)], fill=(150, 90, 56), width=5, color=inkc)
        ink.line([(x, yb - 50 * sc), (x, yb - 260 * sc)], 7, inkc, 0.5)
        ink.poly([(x + 6, yb - 250 * sc), (x + 6, yb - 80 * sc), (x + 120 * sc, yb - 80 * sc)], fill=(250, 246, 232), width=4, color=inkc)
    elif k in ("bag", "letter", "gift"):
        y = GROUND - 40 * sc
        if k == "bag":
            ink.circle(x, y, 40 * sc, 4, fill=(180, 140, 90), color=inkc)
            ink.d.text((x, y), "₺", font=font(FONT_BOLD, 44 * sc), fill=inkc, anchor="mm")
        elif k == "letter":
            ink.poly([(x - 50 * sc, y - 34 * sc), (x + 50 * sc, y - 34 * sc), (x + 50 * sc, y + 34 * sc), (x - 50 * sc, y + 34 * sc)], fill=(250, 246, 232), width=4, color=inkc)
            ink.line([(x - 50 * sc, y - 34 * sc), (x, y), (x + 50 * sc, y - 34 * sc)], 4, inkc, 0.3)
        else:
            ink.poly([(x - 50 * sc, y - 50 * sc), (x + 50 * sc, y - 50 * sc), (x + 50 * sc, y + 40 * sc), (x - 50 * sc, y + 40 * sc)], fill=CLOTH["teal"], width=4, color=inkc)
            ink.line([(x, y - 50 * sc), (x, y + 40 * sc)], 10, CLOTH["red"], 0.3)
    elif k == "door":
        ink.poly([(x - 70 * sc, GROUND), (x + 70 * sc, GROUND), (x + 70 * sc, GROUND - 300 * sc), (x - 70 * sc, GROUND - 300 * sc)], fill=(120, 80, 52), width=6, color=inkc)
        ink.circle(x + 44 * sc, GROUND - 150 * sc, 9 * sc, 0, fill=(230, 190, 80))


# =========================================================================== big text
def draw_big(d, big: dict, t: float, m: dict):
    size = float(big.get("size", 150))
    txt = str(big.get("text", ""))
    if "count_to" in big:
        txt = big.get("prefix", "") + str(int(big["count_to"] * ease(t / big.get("count_time", 1.6)))) + big.get("suffix", "")
    pop = ease_out_back(t / 0.4)
    if pop <= 0.02 or not txt:
        return
    fnt = font(FONT_SERIF, max(10, size * pop))
    lines = wrap(d, txt, fnt, W - 140)
    while len(lines) > 3 and size > 60:  # sığmıyorsa küçült
        size *= 0.85
        fnt = font(FONT_SERIF, size * pop)
        lines = wrap(d, txt, fnt, W - 140)
    y = big.get("y", 0.14) * H
    col = m["accent"] if big.get("accent", True) else (255, 252, 244)
    for i, l in enumerate(lines):
        d.text((W / 2, y + i * size * 1.12), l, font=fnt, fill=col, anchor="ma", stroke_width=max(4, int(size / 18)), stroke_fill=(40, 32, 26))


# =========================================================================== captions
PUNCT = (".", ",", "!", "?", ":", ";", "…")
PARTICLES = {"da", "de", "ki", "mi", "mı", "mu", "mü", "ta"}


def chunk_words(words: list[str], max_chars=18):
    """Altyazı grupları: önce cümle/virgül sınırında böl, sonra her parçayı dengeli alt gruplara ayır.
    Böylece tek başına kalan kelime ("oldu.") ve cümle ortasında kırılma olmaz."""
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
        if k > 1 and len(ph) / k < 2:  # tek kelimelik grup oluşmasın
            k = max(1, len(ph) // 2)
        per = len(ph) / k
        for g in range(k):
            part = ph[round(g * per):round((g + 1) * per)]
            if part:
                chunks.append(part)
    # "da/de/ki/mi" gibi ekler önceki kelimeden ayrılmasın
    for a, b in zip(chunks, chunks[1:]):
        while len(b) > 1 and words[b[0]].strip(",.!?:;…").lower() in PARTICLES:
            a.append(b.pop(0))
    # çok kısa (1 kelime, <8 harf) ifadeyi komşusuna ekle (öncekine, yoksa sonrakine)
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


def draw_caption(img, words, chunks, active, m):
    if not words:
        return
    d = ImageDraw.Draw(img)
    chunk = next((c for c in chunks if active in c), chunks[-1])
    size = 80
    fnt = font(FONT_BOLD, size)
    gap = 22
    while True:
        widths = [d.textlength(words[i], font=fnt) for i in chunk]
        if sum(widths) + gap * (len(chunk) - 1) <= W - 120 or size <= 54:
            break
        size -= 4
        fnt = font(FONT_BOLD, size)
    total = sum(widths) + gap * (len(chunk) - 1)
    x = (W - total) / 2
    y = int(H * 0.78)
    for i, ww in zip(chunk, widths):
        act = i == active
        d.text((x, y - (10 if act else 0)), words[i], font=fnt, fill=(255, 214, 64) if act else (255, 255, 255), stroke_width=10, stroke_fill=(24, 18, 14))
        x += ww + gap


# =========================================================================== scenes
@dataclass
class Scene:
    text: str
    duration: float
    mood: str = "day"
    chars: list = field(default_factory=list)
    props: list = field(default_factory=list)
    big: dict | None = None
    camera: str = "auto"
    focus: float | None = None
    word_starts: list | None = None  # sahne başından itibaren, saniye

    def __post_init__(self):
        self.words = self.text.split()
        self.chunks = chunk_words(self.words)
        if not self.word_starts or len(self.word_starts) != len(self.words):
            weights = [len(w_) + 2 for w_ in self.words]
            tot, acc, speak = sum(weights) or 1, 0.05, max(0.1, self.duration - 0.35)
            self.word_starts = []
            for w_ in weights:
                self.word_starts.append(acc)
                acc += speak * w_ / tot


def scene_from_dict(sd: dict, duration: float, word_starts=None) -> Scene:
    sd, _ = lint_scene(sd)
    allowed = Char.__dataclass_fields__.keys()
    return Scene(text=sd["text"], duration=duration, mood=sd.get("mood", "day"),
                 chars=[Char(**{k: v for k, v in c.items() if k in allowed}) for c in sd.get("chars", [])],
                 props=sd.get("props", []), big=sd.get("big"), camera=sd.get("camera", "auto"),
                 focus=sd.get("focus"), word_starts=word_starts)


SHADOW = (20, 14, 10)


def render_frame(sc: Scene, t: float, frame: int, si: int, prev_clean, captions=True):
    m = MOODS.get(sc.mood, MOODS["day"])
    img = background(sc.mood, si).copy()
    fg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)
    ink = Ink(d, frame, (40, 32, 26), seed=si)
    for p in sc.props:
        if p.get("kind") not in OVERLAY:
            draw_prop(ink, p, t, m, frame)
    for i, c in enumerate(sc.chars):
        draw_char(ink, c, t, m, i)
    for p in sc.props:
        if p.get("kind") in OVERLAY:
            draw_prop(ink, p, max(0.0, t - p.get("delay", 0.25)), m, frame)
    # kesik kâğıt gölgesi
    alpha = fg.getchannel("A")
    img.paste(SHADOW, (7, 9, W + 7, H + 9), alpha.point(lambda a: a * 0.3))
    img.paste(fg, (0, 0), fg)

    cam = sc.camera
    if cam == "auto":
        cam = ["push", "pan", "push", "still"][si % 4] if sc.duration > 1.2 else "still"
    beat = int(t / 2.0)
    z, cx, cy = 1.0, W / 2, H / 2
    fx = (sc.focus if sc.focus is not None else (sc.chars[0].x if sc.chars else 0.5)) * W
    if cam == "push":
        z = 1.0 + 0.06 * ease(t / max(1.0, sc.duration)) + (0.07 if beat % 2 else 0.0) * ease((t - beat * 2.0) / 0.25)
        cx = W / 2 + (fx - W / 2) * 0.35 * (z - 1) * 6
        cy = H * 0.5 + (GROUND - 250 - H / 2) * 0.4 * (z - 1) * 5
    elif cam == "pan":
        z = 1.08
        cx = W / 2 + math.sin(t * 0.6) * 36 + (fx - W / 2) * 0.12
    elif cam == "shake":
        z = 1.05
        decay = max(0.0, 1 - t / 0.8)
        cx = W / 2 + math.sin(t * 40) * 12 * decay
        cy = H / 2 + math.cos(t * 37) * 12 * decay
    if z != 1.0 or cx != W / 2 or cy != H / 2:
        cw, ch = W / z, H / z
        left = max(0, min(W - cw, cx - cw / 2))
        top = max(0, min(H - ch, cy - ch / 2))
        img = img.resize((W, H), Image.BILINEAR, box=(left, top, left + cw, top + ch))
    if sc.big:
        draw_big(ImageDraw.Draw(img), sc.big, max(0.0, t - sc.big.get("delay", 0.0)), m)
    if prev_clean is not None and t < 0.3:
        k = ease(t / 0.3)
        mask = Image.new("L", (W, H), 0)
        r = k * math.hypot(W, H) * 0.6
        ImageDraw.Draw(mask).ellipse([W / 2 - r, H * 0.45 - r, W / 2 + r, H * 0.45 + r], fill=255)
        img = Image.composite(img, prev_clean, mask)
    clean = img
    if captions:
        img = img.copy()
        active = 0
        for i, ws in enumerate(sc.word_starts):
            if t >= ws:
                active = i
        draw_caption(img, sc.words, sc.chunks, active, m)
    return clean, img


def render_video(scenes: list[Scene], audio_path: str, out_path: str):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", audio_path, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frame, prev = 0, None
    for si, sc in enumerate(scenes):
        last = None
        for i in range(int(round(sc.duration * FPS))):
            clean, img = render_frame(sc, i / FPS, frame, si, prev)
            proc.stdin.write(img.tobytes())
            frame += 1
            last = clean
        prev = last
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg başarısız")


def render_preview(scenes: list[Scene], out_path: str, cols=4):
    """Denetçi için: her sahnenin %60 anından bir kare, altyazılı, ızgara halinde."""
    tw, th = 360, 640
    rows = math.ceil(len(scenes) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for i, sc in enumerate(scenes):
        t = sc.duration * 0.6
        _, img = render_frame(sc, t, int(t * FPS), i, None)
        sheet.paste(img.resize((tw, th), Image.LANCZOS), ((i % cols) * tw, (i // cols) * th))
        d.text(((i % cols) * tw + 10, (i // cols) * th + 8), f"#{i + 1}", font=font(FONT_BOLD, 34), fill=(255, 255, 0), stroke_width=4, stroke_fill=(0, 0, 0))
    sheet.save(out_path, quality=88)
    return out_path


def render_thumbnail(scene: Scene, title: str, out_path: str):
    base, _ = render_frame(Scene(text="", duration=scene.duration, mood=scene.mood, chars=scene.chars, props=[p for p in scene.props if p.get("kind") not in OVERLAY], camera="still"), 1.2, 36, 0, None, captions=False)
    d = ImageDraw.Draw(base)
    fnt = font(FONT_SERIF, 116)
    y = 170
    for l in wrap(d, title, fnt, W - 120):
        d.text((W / 2, y), l, font=fnt, fill=(255, 252, 244), anchor="ma", stroke_width=10, stroke_fill=(40, 32, 26))
        y += 136
    base.save(out_path, quality=92)
    return out_path
