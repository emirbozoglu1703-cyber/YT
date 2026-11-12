"""Kıssa Defteri AI takımı: orkestratör.

  Ajan                    Denetçisi                Görev
  ----------------------  -----------------------  ----------------------------------------
  Strateji & Program      Strateji Denetçisi       günün 10 yayın saati + 10 hikâye özeti
  Senarist                Senaryo Denetçisi        özgün hikâye metni
  Ses Ajanı (ElevenLabs)  Ses Denetçisi            seslendirme + ölçüm + STT kontrolü
  Görsel Yönetmen         Görsel Denetçi (vizyon)  sahne düzeni -> render -> kare kontrolü
  Yayın Ajanı             Yayın Denetçisi          başlık/açıklama/etiket + zamanlanmış yükleme
  Baş Denetçi             -                        tüm denetçileri denetler, son onay / geri gönderme

Kullanım:
  python pipeline/team.py plan [--date YYYY-MM-DD]
  python pipeline/team.py produce --index 3 [--date ...] [--no-upload]
  python pipeline/team.py finalize [--date ...]
  python pipeline/team.py demo           # API anahtarı olmadan tüm akışı sahte ajanlarla test eder
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import traceback
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

import production  # noqa: E402
import render  # noqa: E402
import tts  # noqa: E402
from agents import roles  # noqa: E402
from agents.llm import LLM, VERDICT_SCHEMA  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("Europe/Istanbul")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")
BANNED = re.compile(r"yapay zek|\bai\b|\ba\.i\.|\bbot\b|otomatik üret|chatgpt|claude|elevenlabs", re.I)
MAX_ROUNDS = int(os.environ.get("MAX_REVIEW_ROUNDS", "3"))


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def today():
    return dt.datetime.now(TZ).date().isoformat()


class StageFailed(Exception):
    pass


def review_loop(name, log, work_fn, auto_fn, review_fn, notes=None, max_rounds=MAX_ROUNDS):
    """Ajan çalışır -> programatik kontrol -> denetçi. Onay yoksa geri bildirimle tekrar."""
    for rnd in range(1, max_rounds + 1):
        out = work_fn(notes)
        hard, soft = auto_fn(out)
        verdict = review_fn(out, hard, soft)
        approved = verdict["approved"] and not hard
        log.append({"stage": name, "round": rnd, "auto_hard": hard, "auto_soft": soft, "verdict": verdict, "approved": approved})
        print(f"  [{name}] tur {rnd}: {'ONAY' if approved else 'RED'} (puan {verdict.get('score')}) {('; '.join(hard + verdict['issues']))[:300]}")
        if approved:
            return out
        prev = {k: v for k, v in out.items() if k not in ("built", "results", "lint")} if isinstance(out, dict) else out
        notes = {"issues": hard + verdict["issues"], "instructions": verdict["instructions"], "previous": prev}
    raise StageFailed(f"{name}: {max_rounds} turda onay alınamadı")


def fb(notes):
    if not notes:
        return ""
    return ("\n\nDENETÇİ GERİ BİLDİRİMİ (mutlaka düzelt):\n- " + "\n- ".join(notes.get("issues", [])) +
            f"\nTalimat: {notes.get('instructions', '')}\nÖnceki çıktın:\n{json.dumps(notes.get('previous'), ensure_ascii=False, default=str)[:8000]}")


# =============================================================================== PLAN
def slot_performance(history):
    perf = {}
    for h in history:
        if h.get("views_48h") is None or not h.get("slot"):
            continue
        hh = h["slot"][11:13] + ":00"
        perf.setdefault(hh, []).append(h["views_48h"])
    return {k: {"n": len(v), "avg_views_48h": round(sum(v) / len(v))} for k, v in sorted(perf.items())}


def theme_performance(history):
    rows = [h for h in history if h.get("views_48h") is not None]
    rows.sort(key=lambda h: -h["views_48h"])
    return {"en_iyi": [(h["title"], h.get("theme"), h["views_48h"]) for h in rows[:8]],
            "en_kotu": [(h["title"], h.get("theme"), h["views_48h"]) for h in rows[-5:]] if len(rows) > 8 else []}


def update_stats(history):
    """48 saati geçmiş videoların izlenmelerini YouTube'dan çeker (1 kota birimi / 50 video)."""
    if not os.environ.get("YT_REFRESH_TOKEN"):
        return history
    import upload

    now = dt.datetime.now(dt.timezone.utc)
    need = [h for h in history if h.get("video_id") and h.get("views_48h") is None
            and now - dt.datetime.fromisoformat(h["slot"]) > dt.timedelta(hours=48)]
    if not need:
        return history
    yt = upload.client()
    for i in range(0, len(need), 50):
        batch = need[i:i + 50]
        resp = yt.videos().list(part="statistics", id=",".join(h["video_id"] for h in batch)).execute()
        st = {it["id"]: it["statistics"] for it in resp.get("items", [])}
        for h in batch:
            s = st.get(h["video_id"], {})
            h["views_48h"] = int(s.get("viewCount", 0))
            h["likes"] = int(s.get("likeCount", 0))
            h["comments"] = int(s.get("commentCount", 0))
    return history


def read_history():
    p = os.path.join(DATA, "history.jsonl")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_history(hist):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "history.jsonl"), "w", encoding="utf-8") as f:
        for h in hist:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")


def plan(date: str, llm):
    sched = load(os.path.join(ROOT, "config", "schedule.json"))
    n = int(os.environ.get("DAILY_VIDEOS", sched["daily_videos"]))
    d = dt.date.fromisoformat(date)
    weekend = d.weekday() >= 5
    defaults = sched["weekend" if weekend else "weekday"][:n]
    hist = update_stats(read_history())
    write_history(hist)
    recent = [h.get("title") for h in hist[-60:]]
    ctx = {"tarih": date, "gun": ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"][d.weekday()],
           "istenen_sayi": n, "varsayilan_saatler": defaults, "saat_performansi": slot_performance(hist),
           "tema_performansi": theme_performance(hist), "son_basliklar": recent, "notlar": sched.get("notes", "")}
    log = []

    def work(notes):
        return llm.ask("Strateji Ajanı", roles.ANALYST, json.dumps(ctx, ensure_ascii=False) + fb(notes))

    def auto(out):
        hard = []
        slots, briefs = out.get("slots", []), out.get("briefs", [])
        if len(slots) != n or len(briefs) != n:
            hard.append(f"{n} saat ve {n} brief gerekli (gelen {len(slots)}/{len(briefs)})")
        try:
            mins = [int(s[:2]) * 60 + int(s[3:5]) for s in slots]
            if mins != sorted(mins):
                hard.append("saatler artan sırada değil")
            if any(m < 7 * 60 or m > 23 * 60 + 59 for m in mins):
                hard.append("07:00-23:59 dışında saat var")
            if any(b - a < sched.get("min_gap_min", 40) for a, b in zip(mins, mins[1:])):
                hard.append("iki yayın arası 40 dk'dan az")
        except Exception:
            hard.append("saat formatı HH:MM değil")
        return hard, []

    def review(out, hard, soft):
        return llm.ask("Strateji Denetçisi", roles.ANALYST_REVIEW, json.dumps({"baglam": ctx, "plan": out, "programatik_hatalar": hard}, ensure_ascii=False),
                       schema=VERDICT_SCHEMA, review=True)

    out = review_loop("strateji", log, work, auto, review)
    items = []
    for i, (s, b) in enumerate(zip(out["slots"], out["briefs"])):
        slot = dt.datetime.combine(d, dt.time(int(s[:2]), int(s[3:5])), TZ).isoformat()
        items.append({"index": i, "slot": slot, "brief": b})
    p = {"date": date, "items": items, "reasoning": out.get("reasoning", ""), "log": log, "cost_usd": round(llm.cost, 3)}
    save(os.path.join(DATA, "plans", f"{date}.json"), p)
    print(f"Plan hazır: {len(items)} video. Saatler: {', '.join(out['slots'])}")
    return p


# =============================================================================== PRODUCE
class Production:
    def __init__(self, item, date, llm, engine, do_upload=True):
        self.item, self.date, self.llm, self.engine, self.do_upload = item, date, llm, engine, do_upload
        self.work = os.path.join(OUT, date, f"{item['index']:02d}")
        os.makedirs(self.work, exist_ok=True)
        llm.log_path = os.path.join(self.work, "agent_log.jsonl")
        self.log = []
        self.script = self.voice_plan = self.voice_res = self.layout = self.meta = None
        self.scenes = self.video = self.sheet = None

    # ---------------------------------------------------------------- senaryo
    def script_stage(self, extra=None):
        brief = self.item["brief"]
        recent = [h.get("title") for h in read_history()[-40:]]

        def work(notes):
            n = notes or extra
            return self.llm.ask("Senarist", roles.WRITER, f"Brief: {json.dumps(brief, ensure_ascii=False)}\nSon yayınlanan başlıklar (benzeme): {recent}" + fb(n), effort="high")

        def auto(s):
            hard = []
            lines = s.get("lines", [])
            words = sum(len(l.get("text", "").split()) for l in lines)
            if not 9 <= len(lines) <= 14:
                hard.append(f"{len(lines)} satır var (10-13 olmalı)")
            if not 60 <= words <= 120:
                hard.append(f"{words} kelime var (70-110 olmalı)")
            if lines and len(lines[0]["text"].split()) > 9:
                hard.append("ilk cümle (kanca) 8 kelimeden uzun")
            if lines and ("?" not in lines[-1]["text"] or "yorum" not in lines[-1]["text"].lower()):
                hard.append("son satır soru + 'Yorumlara yaz.' ile bitmeli")
            bad = [l["text"] for l in lines if BANNED.search(l.get("text", ""))]
            if bad:
                hard.append(f"yasaklı kelime: {bad}")
            for l in lines:
                if l.get("speaker", "narrator") not in tts.EDGE_VOICES:
                    hard.append(f"geçersiz speaker: {l.get('speaker')}")
            return hard, []

        def review(s, hard, soft):
            return self.llm.ask("Senaryo Denetçisi", roles.WRITER_REVIEW, json.dumps({"brief": brief, "senaryo": s, "programatik_hatalar": hard}, ensure_ascii=False),
                                schema=VERDICT_SCHEMA, review=True, effort="high")

        self.script = review_loop("senaryo", self.log, work, auto, review)
        self.voice_res = None

    # ---------------------------------------------------------------- ses
    def voice_stage(self, extra=None):
        lines = self.script["lines"]
        prev_res = self.voice_res

        def work(notes):
            n = notes or extra
            plan_ = self.llm.ask("Ses Ajanı", roles.VOICE, json.dumps({"senaryo": lines}, ensure_ascii=False) + fb(n))
            vp = plan_.get("lines", [])
            nonlocal prev_res
            res = production.synth_lines(lines, vp, self.work, self.engine, prev=prev_res) if len(vp) == len(lines) else []
            prev_res = res or prev_res
            return {"plan": vp, "results": res}

        def auto(o):
            if not o["results"]:
                return ["ses planı satır sayısı senaryoyla eşleşmiyor"], []
            return production.voice_auto_issues(lines, o["results"], o["plan"], self.engine), []

        def review(o, hard, soft):
            table = [{"satir": i + 1, "metin": l["text"], "tts_text": vp.get("tts_text"), "speaker": vp.get("speaker"),
                      "sure": r["duration"], "kelime_sn": r["words_per_sec"], "max_db": r["metrics"]["max_db"],
                      "duraklamalar": r["metrics"]["long_pauses"], "duyulan": r["transcript"], "benzerlik": r["similarity"]}
                     for i, (l, vp, r) in enumerate(zip(lines, o["plan"], o["results"]))]
            return self.llm.ask("Ses Denetçisi", roles.VOICE_REVIEW, json.dumps({"motor": self.engine, "satirlar": table, "programatik_hatalar": hard}, ensure_ascii=False),
                                schema=VERDICT_SCHEMA, review=True)

        o = review_loop("ses", self.log, work, auto, review)
        self.voice_plan, self.voice_res = o["plan"], o["results"]

    # ---------------------------------------------------------------- görsel
    def visual_stage(self, extra=None):
        lines = self.script["lines"]
        prev_path = os.path.join(self.work, "preview.jpg")

        def work(notes):
            n = notes or extra
            lay = self.llm.ask("Görsel Yönetmen", roles.VISUAL, json.dumps({"senaryo": lines}, ensure_ascii=False) + fb(n), effort="high")
            scenes = lay.get("scenes", [])
            if len(scenes) != len(lines):
                return {"scenes": scenes, "lint": [], "built": None}
            lint = []
            for i, sd in enumerate(scenes):
                _, w = render.lint_scene({**sd, "text": lines[i]["text"]})
                lint += [f"#{i + 1}: {x}" for x in w]
            built = production.build_scenes(lines, scenes, self.voice_res)
            production.preview(built, prev_path)
            return {"scenes": scenes, "lint": lint, "built": built}

        def auto(o):
            hard = []
            if o["built"] is None:
                return [f"sahne sayısı ({len(o['scenes'])}) satır sayısıyla ({len(lines)}) aynı olmalı"], []
            if sum(1 for s in o["scenes"] if s.get("camera") == "shake") > 2:
                hard.append("shake kamera 2'den fazla sahnede")
            for i, s in enumerate(o["scenes"], 1):
                for p in s.get("props", []):
                    if p.get("kind") == "bubble" and len(str(p.get("text", "")).split()) > 6:
                        hard.append(f"#{i}: balon metni çok uzun")
                if BANNED.search(json.dumps(s, ensure_ascii=False)):
                    hard.append(f"#{i}: yasaklı kelime")
            return hard, o["lint"]

        def review(o, hard, soft):
            if o["built"] is None:
                return {"approved": False, "score": 1, "issues": hard, "instructions": "Her satır için tam bir sahne üret."}
            content = [LLM.image(prev_path), {"type": "text", "text": json.dumps(
                {"senaryo": [l["text"] for l in lines], "duzen_uyarilari_otomatik_duzeltildi": soft, "programatik_hatalar": hard}, ensure_ascii=False)}]
            return self.llm.ask("Görsel Denetçi", roles.VISUAL_REVIEW, content, schema=VERDICT_SCHEMA, review=True, effort="high")

        o = review_loop("görsel", self.log, work, auto, review)
        self.layout = o["scenes"]

    # ---------------------------------------------------------------- render
    def render_stage(self):
        self.scenes = production.build_scenes(self.script["lines"], self.layout, self.voice_res)
        mix, _ = production.mix_audio(self.voice_res, self.scenes, self.script.get("music", "warm"), self.work, seed=self.item["index"])
        self.video, self.thumb, self.sheet = production.render_final(self.scenes, mix, self.work, f"short_{self.item['index']:02d}", self.script.get("working_title", ""))

    # ---------------------------------------------------------------- yayın metni
    def publish_stage(self, extra=None):
        story = {"senaryo": [l["text"] for l in self.script["lines"]], "ders": self.script.get("moral"), "calisma_basligi": self.script.get("working_title")}

        def work(notes):
            return self.llm.ask("Yayın Ajanı", roles.PUBLISHER, json.dumps(story, ensure_ascii=False) + fb(notes or extra))

        def auto(m):
            hard = []
            if len(m.get("title", "")) > 60:
                hard.append(f"başlık {len(m.get('title', ''))} karakter (<=60)")
            if BANNED.search(json.dumps(m, ensure_ascii=False)):
                hard.append("yasaklı kelime (AI/bot vb.) geçiyor")
            if not 6 <= len(m.get("tags", [])) <= 15:
                hard.append("etiket sayısı 8-12 olmalı")
            return hard, []

        def review(m, hard, soft):
            return self.llm.ask("Yayın Denetçisi", roles.PUBLISHER_REVIEW, json.dumps({"hikaye": story, "metinler": m, "programatik_hatalar": hard}, ensure_ascii=False),
                                schema=VERDICT_SCHEMA, review=True)

        self.meta = review_loop("yayın", self.log, work, auto, review)

    # ---------------------------------------------------------------- baş denetçi
    def chief(self):
        voice_table = [{"satir": i + 1, "sure": r["duration"], "kelime_sn": r["words_per_sec"], "benzerlik": r["similarity"]} for i, r in enumerate(self.voice_res)]
        content = [LLM.image(self.sheet), {"type": "text", "text": json.dumps({
            "brief": self.item["brief"], "senaryo": self.script, "ses": voice_table, "yayin_metinleri": self.meta,
            "denetim_kayitlari": [{k: v for k, v in r.items() if k != "verdict"} | {"denetci": r["verdict"]} for r in self.log]}, ensure_ascii=False)[:60000]}]
        v = self.llm.ask("Baş Denetçi", roles.CHIEF, content, schema=roles.CHIEF_SCHEMA, review=True, effort="high")
        self.log.append({"stage": "baş denetçi", "verdict": v, "approved": v["approved"]})
        print(f"  [baş denetçi] {'ONAY' if v['approved'] else 'RED -> ' + v['send_back_to']} (kalite {v['quality_score']}) {v['instructions'][:200]}")
        return v

    def full(self):
        self.script_stage()
        self.voice_stage()
        self.visual_stage()
        self.render_stage()
        self.publish_stage()

    def run(self):
        result = {"date": self.date, "index": self.item["index"], "slot": self.item["slot"], "brief": self.item["brief"], "status": "failed"}
        try:
            for attempt in range(2):  # 2. denemede tamamen yeni senaryo
                try:
                    self.full()
                    v = self.chief()
                    for _ in range(2):  # baş denetçi en fazla 2 kez geri gönderebilir
                        if v["approved"]:
                            break
                        extra = {"issues": [v["instructions"]], "instructions": "Baş denetçinin talimatını uygula.", "previous": None}
                        stage = v["send_back_to"]
                        if stage == "script":
                            self.script_stage(extra)
                            self.voice_stage()
                            self.visual_stage()
                            self.render_stage()
                            self.publish_stage()
                        elif stage == "voice":
                            self.voice_stage(extra)
                            self.render_stage()
                        elif stage in ("visual", "none"):
                            self.visual_stage(extra)
                            self.render_stage()
                        elif stage == "publish":
                            self.publish_stage(extra)
                        v = self.chief()
                    if v["approved"]:
                        break
                    raise StageFailed("baş denetçi onaylamadı")
                except StageFailed as e:
                    print(f"  deneme {attempt + 1} başarısız: {e}")
                    if attempt == 1:
                        raise
            result.update({"status": "approved", "title": self.meta["title"], "theme": self.item["brief"].get("theme"),
                           "pinned_comment": self.meta.get("pinned_comment"),
                           "chief_score": v["quality_score"], "video": self.video})
            story = {"script": self.script, "layout": self.layout, "voice_plan": self.voice_plan, "meta": self.meta}
            save(os.path.join(self.work, "story.json"), story)
            if self.do_upload:
                import upload

                slot = dt.datetime.fromisoformat(self.item["slot"])
                earliest = dt.datetime.now(TZ) + dt.timedelta(minutes=15)
                when = max(slot, earliest)
                vid = upload.upload({**self.meta, "video": self.video, "thumbnail": self.thumb}, privacy="private", publish_at=when)
                result.update({"status": "scheduled", "video_id": vid, "slot": when.isoformat()})
                print(f"  YÜKLENDİ: https://youtube.com/shorts/{vid} -> {when:%H:%M}")
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        result["cost_usd"] = round(self.llm.cost, 3)
        result["llm_calls"] = self.llm.calls
        result["review_log"] = self.log
        save(os.path.join(OUT, "results", f"{self.date}_{self.item['index']:02d}.json"), result)
        return result


# =============================================================================== FINALIZE
def finalize(date):
    results = []
    for p in sorted(glob.glob(os.path.join(OUT, "results", f"{date}_*.json"))):
        results.append(load(p))
    hist = read_history()
    have = {(h["date"], h["index"]) for h in hist}
    for r in results:
        if r["status"] == "scheduled" and (r["date"], r["index"]) not in have:
            hist.append({k: r.get(k) for k in ("date", "index", "slot", "video_id", "title", "theme", "chief_score", "cost_usd", "pinned_comment")}
                        | {"emotion": r["brief"].get("emotion"), "setting": r["brief"].get("setting"), "views_48h": None})
    write_history(hist)
    for r in results:
        src = os.path.join(OUT, date, f"{r['index']:02d}", "story.json")
        if os.path.exists(src):
            save(os.path.join(ROOT, "stories", "published", date, f"{r['index']:02d}.json"), load(src) | {"video_id": r.get("video_id"), "slot": r.get("slot")})
    ok = [r for r in results if r["status"] == "scheduled"]
    cost = sum(r.get("cost_usd", 0) for r in results) + (load(os.path.join(DATA, "plans", f"{date}.json"), {}) or {}).get("cost_usd", 0)
    lines = [f"# Günlük rapor {date}", "", f"Yayına alınan: **{len(ok)}/{len(results)}**, ajan maliyeti ~${cost:.2f}", "",
             "| # | Saat | Başlık | Durum | Kalite | Denetim turu |", "|---|---|---|---|---|---|"]
    for r in results:
        rounds = len([x for x in r.get("review_log", []) if x.get("stage") != "baş denetçi"])
        lines.append(f"| {r['index'] + 1} | {r['slot'][11:16]} | {r.get('title', '-')} | {r['status']} {r.get('error', '')[:60]} | {r.get('chief_score', '-')} | {rounds} |")
    perf = slot_performance(hist)
    if perf:
        lines += ["", "## Saat dilimi performansı (48 saatlik ortalama izlenme)", ""] + [f"- {k}: {v['avg_views_48h']} ({v['n']} video)" for k, v in perf.items()]
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", f"{date}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


# =============================================================================== YORUMLAR
def post_comments():
    """Yayına girmiş (saati geçmiş) videolara kanalın ilk yorumunu yazar. Zamanlanmış gizli videoya yorum yazılamadığı için ayrı adım."""
    import upload

    hist = read_history()
    now = dt.datetime.now(dt.timezone.utc)
    yt, changed = None, False
    for h in hist:
        if h.get("video_id") and h.get("pinned_comment") and not h.get("comment_posted") and dt.datetime.fromisoformat(h["slot"]) < now - dt.timedelta(minutes=5):
            yt = yt or upload.client()
            try:
                yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": h["video_id"], "topLevelComment": {"snippet": {"textOriginal": h["pinned_comment"]}}}}).execute()
                h["comment_posted"] = True
                changed = True
                print("yorum yazıldı:", h["title"])
            except Exception as e:
                print("yorum yazılamadı:", h.get("title"), e)
    if changed:
        write_history(hist)


# =============================================================================== CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "produce", "finalize", "demo", "comments"])
    ap.add_argument("--date", default=today())
    ap.add_argument("--index", type=int)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--engine")
    a = ap.parse_args()
    engine = a.engine or tts.pick_engine()

    if a.cmd == "demo":
        from agents.fake import FakeLLM

        llm = FakeLLM()
        p = plan(a.date, llm)
        r = Production(p["items"][0], a.date, llm, a.engine or "silent", do_upload=False).run()
        print(json.dumps({k: v for k, v in r.items() if k != "review_log"}, ensure_ascii=False, indent=2))
        return
    if a.cmd == "plan":
        p = plan(a.date, LLM())
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"indices={json.dumps([it['index'] for it in p['items']])}\n")
    elif a.cmd == "produce":
        p = load(os.path.join(DATA, "plans", f"{a.date}.json"))
        item = next(it for it in p["items"] if it["index"] == a.index)
        r = Production(item, a.date, LLM(), engine, do_upload=not a.no_upload).run()
        if r["status"] == "failed":
            sys.exit(1)
    elif a.cmd == "finalize":
        finalize(a.date)
    elif a.cmd == "comments":
        post_comments()


if __name__ == "__main__":
    main()
