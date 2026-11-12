"""Claude Code ajanlarının kullandığı araçlar. Her komut sonucu ekrana yazar; ajanlar bunu okuyup karar verir.

  python pipeline/tools.py context [--date D]          strateji ajanı için: varsayılan saatler, saat/tema performansı, son başlıklar
  python pipeline/tools.py check-plan D                 data/plans/D.json kurallara uyuyor mu
  python pipeline/tools.py new D N                      work/D/N klasörünü plandaki brief ile açar
  python pipeline/tools.py check-script DIR             script.json programatik kontroller
  python pipeline/tools.py voice DIR                    voice.json'a göre seslendir (sadece değişen replikler), ölçüm tablosu
  python pipeline/tools.py preview DIR                  staging.json -> düzen kontrolü + preview.jpg (her sahneden bir kare)
  python pipeline/tools.py render DIR                   son video + final_sheet.jpg
  python pipeline/tools.py check-meta DIR               meta.json programatik kontroller
  python pipeline/tools.py package DIR                  onaylı videoyu queue/D/N'ye koyar (GitHub yükler)
  python pipeline/tools.py status D                     günün tüm videolarının durumu
Çıkış kodu: 0 = sorun yok, 2 = programatik hata var (çıktıda listelenir).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

import production  # noqa: E402
import theater  # noqa: E402
import tts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("Europe/Istanbul")
BANNED = re.compile(r"yapay zek|\bai\b|\ba\.i\.|\bbot\b|otomatik üret|chatgpt|claude|elevenlabs|anthropic", re.I)
VOICE_KEYS = {"narrator", "man", "old", "young", "woman", "child"}


def load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def history():
    p = os.path.join(ROOT, "data", "history.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def report(issues, warnings=()):
    for w in warnings:
        print("UYARI (otomatik düzeltildi):", w)
    if issues:
        print("HATALAR:")
        for i in issues:
            print(" -", i)
        sys.exit(2)
    print("PROGRAMATİK KONTROL: TEMİZ")


# ------------------------------------------------------------------ strateji
def cmd_context(a):
    sched = load(os.path.join(ROOT, "config", "schedule.json"))
    d = dt.date.fromisoformat(a.date)
    hist = history()
    perf = {}
    for h in hist:
        if h.get("views_48h") is not None:
            perf.setdefault(h["slot"][11:13] + ":00", []).append(h["views_48h"])
    rows = sorted([h for h in hist if h.get("views_48h") is not None], key=lambda h: -h["views_48h"])
    out = {
        "tarih": a.date, "gun": ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"][d.weekday()],
        "istenen_video_sayisi": sched["daily_videos"], "varsayilan_saatler": sched["weekend" if d.weekday() >= 5 else "weekday"][:sched["daily_videos"]],
        "kurallar": {"min_ara_dk": sched["min_gap_min"], "pencere": "07:00-23:59", "gunluk_max_kaydirma": "en fazla 2 saat, her biri en fazla 45 dk"},
        "saat_performansi_48s_ort_izlenme": {k: {"video": len(v), "ort": round(sum(v) / len(v))} for k, v in sorted(perf.items())},
        "en_iyi_videolar": [{"baslik": h["title"], "tema": h.get("theme"), "izlenme_48s": h["views_48h"], "saat": h["slot"][11:16]} for h in rows[:8]],
        "en_kotu_videolar": [{"baslik": h["title"], "tema": h.get("theme"), "izlenme_48s": h["views_48h"]} for h in rows[-5:]] if len(rows) > 8 else [],
        "son_60_baslik": [h.get("title") for h in hist[-60:]],
        "notlar": sched.get("notes"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_check_plan(a):
    sched = load(os.path.join(ROOT, "config", "schedule.json"))
    p = load(os.path.join(ROOT, "data", "plans", f"{a.date}.json"))
    if not p:
        report([f"data/plans/{a.date}.json yok"])
    items, issues = p.get("items", []), []
    n = sched["daily_videos"]
    if len(items) != n:
        issues.append(f"{n} video gerekli, planda {len(items)} var")
    try:
        mins = [int(i["time"][:2]) * 60 + int(i["time"][3:5]) for i in items]
        if mins != sorted(mins):
            issues.append("saatler artan sırada değil")
        if any(m < 420 or m > 1439 for m in mins):
            issues.append("07:00-23:59 dışında saat var")
        if any(b - a_ < sched["min_gap_min"] for a_, b in zip(mins, mins[1:])):
            issues.append(f"iki yayın arası {sched['min_gap_min']} dk'dan az")
    except Exception:
        issues.append("her öğede 'time': 'HH:MM' olmalı")
    for i, it in enumerate(items):
        for k in ("theme", "emotion", "backdrop_idea", "hook_idea", "cast_idea"):
            if not it.get("brief", {}).get(k):
                issues.append(f"#{i}: brief.{k} boş")
    themes = [it.get("brief", {}).get("theme", "").lower() for it in items]
    if len(set(themes)) != len(themes):
        issues.append("aynı tema birden fazla kez kullanılmış")
    report(issues)


def cmd_new(a):
    p = load(os.path.join(ROOT, "data", "plans", f"{a.date}.json"))
    it = p["items"][a.index]
    work = os.path.join(ROOT, "work", a.date, f"{a.index:02d}")
    os.makedirs(work, exist_ok=True)
    slot = dt.datetime.combine(dt.date.fromisoformat(a.date), dt.time(int(it["time"][:2]), int(it["time"][3:5])), TZ)
    save(os.path.join(work, "brief.json"), {**it, "slot": slot.isoformat(), "date": a.date, "index": a.index})
    print(work)


# ------------------------------------------------------------------ senaryo
def cmd_check_script(a):
    s = load(os.path.join(a.dir, "script.json"))
    issues = []
    if not s:
        report(["script.json yok"])
    cast = s.get("cast", [])
    ids = {c.get("id") for c in cast}
    if not 1 <= len(cast) <= 4:
        issues.append(f"kadroda {len(cast)} kukla var (1-4 olmalı)")
    for c in cast:
        if c.get("type", "human") not in ("human", *theater.ANIMALS):
            issues.append(f"{c.get('id')}: geçersiz tür {c.get('type')}")
        if c.get("voice") not in VOICE_KEYS:
            issues.append(f"{c.get('id')}: voice {sorted(VOICE_KEYS)} içinden olmalı")
        if not c.get("name"):
            issues.append(f"{c.get('id')}: name (ekranda görünen ad) boş")
    lines = s.get("lines", [])
    words = sum(len(l.get("text", "").split()) for l in lines)
    if not 9 <= len(lines) <= 14:
        issues.append(f"{len(lines)} replik var (10-13 olmalı)")
    if not 65 <= words <= 120:
        issues.append(f"{words} kelime var (70-110 olmalı)")
    narr = sum(1 for l in lines if l.get("speaker") == "narrator")
    if narr > 3:
        issues.append(f"anlatıcı {narr} replik konuşuyor (en fazla 3; hikâye diyalogla ilerlemeli)")
    for i, l in enumerate(lines, 1):
        if l.get("speaker") != "narrator" and l.get("speaker") not in ids:
            issues.append(f"replik {i}: konuşan '{l.get('speaker')}' kadroda yok")
        if len(l.get("text", "").split()) > 16:
            issues.append(f"replik {i}: 16 kelimeden uzun")
        if BANNED.search(l.get("text", "")):
            issues.append(f"replik {i}: yasaklı kelime")
    if lines:
        if lines[0].get("speaker") == "narrator":
            issues.append("açılış repliğini bir kukla söylemeli (seyirciye dönük kanca)")
        if len(lines[0]["text"].split()) > 10:
            issues.append("açılış repliği 10 kelimeden uzun")
        if "?" not in lines[-1]["text"]:
            issues.append("son replik seyirciye bir seçim sorusu olmalı")
        if "yorumlara yaz" in " ".join(l["text"].lower() for l in lines):
            issues.append("'Yorumlara yaz' kalıbı kullanma; soru kendi başına yeterli")
    if not 8 <= len(s.get("banner", "")) <= 34:
        issues.append(f"banner {len(s.get('banner', ''))} karakter (8-34 olmalı): videonun üstünde duran merak başlığı")
    for k in ("working_title", "moral", "music"):
        if not s.get(k):
            issues.append(f"{k} boş")
    if s.get("music") not in ("playful", "warm", "mystery", "hopeful"):
        issues.append("music: playful|warm|mystery|hopeful")
    report(issues)


# ------------------------------------------------------------------ ses
def cmd_voice(a):
    s = load(os.path.join(a.dir, "script.json"))
    vp = load(os.path.join(a.dir, "voice.json"), {}).get("lines", [])
    engine = a.engine or tts.pick_engine()
    prev = load(os.path.join(a.dir, "voice_report.json"), {}).get("results")
    if len(vp) != len(s["lines"]):
        report([f"voice.json'da {len(vp)} satır var, senaryoda {len(s['lines'])} replik"])
    res = production.synth_lines(s, vp, a.dir, engine, prev=prev)
    issues = production.voice_issues(s, res, vp, engine)
    save(os.path.join(a.dir, "voice_report.json"), {"engine": engine, "results": res})
    print(f"motor: {engine}")
    print(f"{'#':>2} {'ses':<9} {'süre':>5} {'k/sn':>5} {'maxdB':>6} {'benzerlik':>9}  duyulan")
    for i, r in enumerate(res, 1):
        print(f"{i:>2} {r['voice']:<9} {r['duration']:>5.2f} {r['words_per_sec']:>5} {str(r['metrics']['max_db']):>6} {str(r['similarity']):>9}  {(r['transcript'] or '-')[:70]}")
    print(f"toplam (tempo {production.tempo()} ile): {sum(r['duration'] / production.tempo() + production.PAD for r in res):.1f} sn")
    report(issues)


def _voice_res(d):
    vr = load(os.path.join(d, "voice_report.json"))
    if not vr:
        report(["önce ses aşaması tamamlanmalı (voice_report.json yok)"])
    return vr["results"]


# ------------------------------------------------------------------ görsel
def cmd_preview(a):
    s = load(os.path.join(a.dir, "script.json"))
    st = load(os.path.join(a.dir, "staging.json"))
    if not st:
        report(["staging.json yok"])
    issues = []
    if len(st.get("scenes", [])) != len(s["lines"]):
        report([f"staging'de {len(st.get('scenes', []))} sahne var, senaryoda {len(s['lines'])} replik"])
    for i, sc in enumerate(st["scenes"], 1):
        if BANNED.search(json.dumps(sc, ensure_ascii=False)):
            issues.append(f"#{i}: yasaklı kelime")
        line = s["lines"][i - 1]
        ids = [p.get("id") for p in sc.get("on_stage", [])]
        if line["speaker"] != "narrator" and line["speaker"] not in ids:
            issues.append(f"#{i}: konuşan '{line['speaker']}' sahnede yok")
        if not ids:
            issues.append(f"#{i}: sahnede hiç kukla yok")
    if st["scenes"] and st["scenes"][0].get("camera") == "wide":
        issues.append("#1: açılış sahnesi 'medium' ya da 'close' olmalı (ilk saniyede yüz)")
    story = production.merged_story(s, st)
    res = _voice_res(a.dir)
    th, warns = production.build_theater(story, res)
    out = os.path.join(a.dir, "preview.jpg")
    th.preview(out)
    print("önizleme:", out)
    report(issues, warns)


def cmd_render(a):
    s = load(os.path.join(a.dir, "script.json"))
    st = load(os.path.join(a.dir, "staging.json"))
    vp = load(os.path.join(a.dir, "voice.json"), {}).get("lines")
    story = production.merged_story(s, st, vp)
    save(os.path.join(a.dir, "story.json"), story)
    video, sheet, warns = production.render_final(story, _voice_res(a.dir), a.dir, "short")
    print("video:", video)
    print("kare ızgarası:", sheet)
    report([], warns)


# ------------------------------------------------------------------ yayın
def cmd_check_meta(a):
    m = load(os.path.join(a.dir, "meta.json"))
    if not m:
        report(["meta.json yok"])
    issues = []
    if not 10 <= len(m.get("title", "")) <= 60:
        issues.append(f"başlık {len(m.get('title', ''))} karakter (10-60)")
    if BANNED.search(json.dumps(m, ensure_ascii=False)):
        issues.append("yasaklı kelime (AI/bot vb.)")
    if not 6 <= len(m.get("tags", [])) <= 15:
        issues.append("etiket sayısı 8-12 olmalı")
    if not m.get("pinned_comment"):
        issues.append("pinned_comment boş")
    if "#" not in m.get("description", ""):
        issues.append("açıklamada hashtag yok")
    report(issues)


def cmd_package(a):
    b = load(os.path.join(a.dir, "brief.json"))
    approval = load(os.path.join(a.dir, "approval.json"))
    if not approval or not approval.get("approved"):
        report(["approval.json'da baş denetçi onayı yok"])
    dst = os.path.join(ROOT, "queue", b["date"], f"{b['index']:02d}")
    os.makedirs(dst, exist_ok=True)
    res = _voice_res(a.dir)
    for r in res:
        shutil.copy(r["path"], os.path.join(dst, os.path.basename(r["path"])))
    slim = [{**{k: r[k] for k in ("duration", "tts_starts", "voice")}, "path": os.path.basename(r["path"])} for r in res]
    save(os.path.join(dst, "package.json"), {"story": load(os.path.join(a.dir, "story.json")), "voice": slim,
                                              "meta": load(os.path.join(a.dir, "meta.json")), "brief": b,
                                              "approval": approval})
    print("paket:", dst)
    report([])


def cmd_status(a):
    base = os.path.join(ROOT, "work", a.date)
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        f = lambda n: "✓" if os.path.exists(os.path.join(d, n)) else "·"
        ap = load(os.path.join(d, "approval.json"), {})
        q = os.path.exists(os.path.join(ROOT, "queue", a.date, os.path.basename(d), "package.json"))
        print(f"{os.path.basename(d)}  senaryo{f('script.json')} ses{f('voice_report.json')} sahne{f('staging.json')} "
              f"video{f('short.mp4')} metin{f('meta.json')} onay{'✓' if ap.get('approved') else ('✗' if ap else '·')} paket{'✓' if q else '·'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    today = dt.datetime.now(TZ).date().isoformat()
    p = sub.add_parser("context"); p.add_argument("--date", default=today)
    p = sub.add_parser("check-plan"); p.add_argument("date")
    p = sub.add_parser("new"); p.add_argument("date"); p.add_argument("index", type=int)
    for c in ("check-script", "preview", "render", "check-meta", "package"):
        p = sub.add_parser(c); p.add_argument("dir")
    p = sub.add_parser("voice"); p.add_argument("dir"); p.add_argument("--engine")
    p = sub.add_parser("status"); p.add_argument("date")
    a = ap.parse_args()
    {"context": cmd_context, "check-plan": cmd_check_plan, "new": cmd_new, "check-script": cmd_check_script, "voice": cmd_voice,
     "preview": cmd_preview, "render": cmd_render, "check-meta": cmd_check_meta, "package": cmd_package, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
