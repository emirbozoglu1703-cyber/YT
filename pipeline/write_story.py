"""Kuyruk azaldığında Claude ile yeni hikâye senaryosu yazar (ANTHROPIC_API_KEY gerekir).

  python pipeline/write_story.py            # kuyrukta 3'ten az hikâye varsa 3 tane yazar
  python pipeline/write_story.py --count 5 --force

Anahtar yoksa hiçbir şey yapmaz; kuyruğa elle (ya da Claude Code'a "yeni hikâye yaz" diyerek) JSON eklenebilir.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "stories", "queue")
PUBLISHED = os.path.join(ROOT, "stories", "published")

SYSTEM = """Sen Türkçe kısa video (YouTube Shorts) senaristisin. Kanal: kâğıt-mürekkep çizimli çöp adamlarla anlatılan, 30-45 saniyelik kıssalar/hikâyeler.

Viral formül (mutlaka uygula):
1. İLK CÜMLE bir çelişki ya da şaşırtıcı sonuç içerir ("Hiç durmadı, yine de kaybetti."). Hikâyenin sonunu ima eder ama açıklamaz.
2. Her sahne 1-2 kısa cümle, 1.5-3.5 saniye. Toplam 10-13 sahne, toplam metin 70-110 kelime.
3. Her sahnede ekranda bir şey değişir: yeni figür, poz, sayı, konuşma balonu, mekân/saat (day -> dusk -> night).
4. Ortada bir gerilim ya da sayı karşılaştırması (sayaçlar çok iyi çalışır).
5. Son sahne izleyiciye doğrudan bir soru sorar ve "Yorumlara yaz." ile biter.
6. Halk hikâyeleri, kıssalar, iş/para/disiplin/ilişki dersleri. Telifli eser, gerçek kişi, siyaset, din tartışması, sağlık iddiası YOK.
7. Doğal, sıcak bir anlatıcı dili; "-mış" geçmiş zamanı.

Çıktı: SADECE geçerli bir JSON nesnesi, başka metin yok. Şema:
{"id": "kisa_ascii_slug", "title": "<=60 karakter merak uyandıran başlık", "thumbnail_text": "<=30 karakter",
 "description": "1-2 cümle, sonu söylemeden merak uyandırır", "tags": ["4-6 Türkçe etiket"],
 "music": "warm|mystery|hopeful",
 "scenes": [{"text": "seslendirilecek metin", "speaker": "narrator|old|young|woman|child (opsiyonel)",
   "mood": "day|dusk|night", "camera": "auto|push|pan|shake|still", "focus": 0..1 (opsiyonel),
   "chars": [{"x": 0..1, "pose": "stand|walk|work|sit|laugh|point|think|cheer|sad|run|talk", "face": 1|-1,
              "scale": 0.8..1.3, "old": bool, "hat": bool, "holds": "axe|book|coin|phone|null",
              "label": "kısa etiket|null", "color": "accent|null", "walk_to": 0..1|null}],
   "props": [{"kind": "tree|stump|logs|sun|moon|cloud|house|mountain|coins|clock|road|birds|heart|question|bubble",
              "x": 0..1, "y": 0..1, "scale": 0.4..1.6, "count": int, "grow": bool, "setting": bool,
              "speed": num, "text": "balon metni (bubble için, <=5 kelime)", "tail": 1|-1}],
   "big": {"text": "kısa büyük yazı" | "count_to": int, "y": 0.1..0.25, "size": 80..260} (opsiyonel)}]}
Ekranda en fazla 3 figür. Figürler x=0.2..0.8 arasında. Büyük yazı ve balonlar y<=0.3."""


def existing_titles() -> list[str]:
    out = []
    for f in glob.glob(os.path.join(QUEUE, "*.json")) + glob.glob(os.path.join(PUBLISHED, "*.json")):
        try:
            out.append(json.load(open(f, encoding="utf-8"))["title"])
        except Exception:
            pass
    return out


def write_one(client, n_existing: int) -> str:
    avoid = "\n".join(f"- {t}" for t in existing_titles())
    resp = client.beta.messages.create(
        model=os.environ.get("STORY_MODEL", "claude-opus-5-5"),
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Yeni bir hikâye yaz. Daha önce kullanılanlarla aynı hikâye ya da ders olmasın:\n{avoid or '- (yok)'}"}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model isteği reddetti")
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    story = json.loads(m.group(0))
    assert story["scenes"] and all("text" in s for s in story["scenes"])
    slug = re.sub(r"[^a-z0-9_]", "", story["id"].lower())[:40] or "hikaye"
    story["id"] = f"{n_existing + 1:02d}_{slug}"
    path = os.path.join(QUEUE, story["id"] + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)
    print("yazıldı:", path, "-", story["title"])
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--min", type=int, default=3, help="kuyrukta bundan az varsa yaz")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY yok, hikâye yazımı atlandı.")
        return
    q = glob.glob(os.path.join(QUEUE, "*.json"))
    if len(q) >= a.min and not a.force:
        print(f"Kuyrukta {len(q)} hikâye var, yazmaya gerek yok.")
        return
    import anthropic

    client = anthropic.Anthropic()
    n = len(q) + len(glob.glob(os.path.join(PUBLISHED, "*.json")))
    for i in range(a.count):
        try:
            write_one(client, n + i)
        except Exception as e:
            print("hikâye yazılamadı:", e)


if __name__ == "__main__":
    main()
