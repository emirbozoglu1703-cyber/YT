"""Kukla tiyatrosu üretim araçları: seslendirme, miksaj, render. tools.py ve upload iş akışı kullanır."""
from __future__ import annotations

import json
import os
import subprocess

import audio
import theater
import tts

PAD = 0.28  # replikler arası nefes


def voice_key(script: dict, speaker: str) -> str:
    if speaker == "narrator":
        return "narrator"
    for c in script["cast"]:
        if c["id"] == speaker:
            return c.get("voice", "narrator")
    return "narrator"


def synth_lines(script, voice_plan, work, engine, prev=None):
    """Her repliği seslendirir; prev verilirse yalnızca talimatı değişen replikler yeniden üretilir."""
    results = []
    for i, (line, vp) in enumerate(zip(script["lines"], voice_plan)):
        path = os.path.join(work, f"line{i:02d}.mp3")
        vkey = vp.get("voice") or voice_key(script, line["speaker"])
        key = [vp.get("tts_text") or line["text"], vkey, sorted((vp.get("settings") or {}).items())]
        key = json.dumps(key, ensure_ascii=False)
        if prev and i < len(prev) and prev[i].get("key") == key and os.path.exists(path):
            results.append(prev[i])
            continue
        _, starts = tts.synth(vp.get("tts_text") or line["text"], vkey, path, engine, vp.get("settings"))
        tts.trim_silence(path)
        dur = tts.duration(path)
        met = tts.measure(path)
        tr = tts.transcribe(path) if engine == "elevenlabs" else None
        words = len(line["text"].split())
        results.append({"key": key, "path": path, "voice": vkey, "duration": round(dur, 3), "tts_starts": starts, "metrics": met,
                        "words_per_sec": round(words / max(0.1, dur), 2), "transcript": tr,
                        "similarity": tts.similarity(vp.get("tts_text") or line["text"], tr) if tr else None})
    return results


def voice_issues(script, voice_res, voice_plan, engine):
    hard = []
    if len(voice_plan) != len(script["lines"]):
        return ["ses planındaki replik sayısı senaryoyla eşleşmiyor"]
    total = sum(r["duration"] / tempo() + PAD for r in voice_res)
    for i, r in enumerate(voice_res, 1):
        if engine == "silent":
            break
        if not 1.6 <= r["words_per_sec"] <= 4.2:
            hard.append(f"replik {i}: hız {r['words_per_sec']} kelime/sn (1.6-4.2 olmalı)")
        if r["metrics"]["max_db"] is not None and r["metrics"]["max_db"] > -0.3:
            hard.append(f"replik {i}: ses patlıyor (max {r['metrics']['max_db']} dB)")
        if any(p > 0.8 for p in r["metrics"]["long_pauses"]):
            hard.append(f"replik {i}: uzun duraklama {r['metrics']['long_pauses']}")
        if r["similarity"] is not None and r["similarity"] < 0.85:
            hard.append(f"replik {i}: yanlış okuma (benzerlik {r['similarity']}): duyulan '{r['transcript']}'")
    if not 25 <= total <= 58:
        hard.append(f"toplam süre {total:.1f} sn (25-58 olmalı)")
    return hard


def channel_cfg(name):
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "channels.json"), encoding="utf-8") as f:
            return json.load(f).get(name or "", {})
    except FileNotFoundError:
        return {}


def merged_story(script, staging, voice_plan=None):
    scenes = []
    for i, (line, st) in enumerate(zip(script["lines"], staging["scenes"])):
        sc = {**st, "speaker": line["speaker"], "text": line["text"]}
        if voice_plan:
            sc["tts_text"] = voice_plan[i].get("tts_text")
        scenes.append(sc)
    ch = channel_cfg(script.get("channel"))
    return {"id": script.get("id", "oyun"), "title": script.get("working_title", ""), "banner": script.get("banner", ""),
            "channel": script.get("channel"), "banner_color": ch.get("banner_color"), "music": script.get("music") or ch.get("music", "playful"),
            "moral": script.get("moral", ""), "cast": script["cast"], "scenes": scenes}


def tempo() -> float:
    """Sesi tonu bozmadan hızlandırma katsayısı (config/voices.json -> tempo)."""
    return float(tts.voice_config().get("tempo", 1.0))


def build_theater(story, voice_res):
    k = tempo()
    durs = [r["duration"] / k + PAD for r in voice_res]
    starts = [[x / k for x in tts.map_word_starts(sc["text"], r.get("tts_starts"), r["duration"])] for sc, r in zip(story["scenes"], voice_res)]
    return theater.build(story, durs, starts)


def mix(th: theater.Theater, voice_res, music_mood, work, seed=0):
    voice = os.path.join(work, "voice.wav")
    scenes = th.scenes
    inputs, filt = [], []
    for i, (vr, sc) in enumerate(zip(voice_res, scenes)):
        inputs += ["-i", vr["path"]]
        k = tempo()
        filt.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,atempo={k:.3f},apad=pad_dur={max(0.0, sc.duration - vr['duration'] / k):.3f},atrim=0:{sc.duration:.3f}[a{i}]")
    n = len(voice_res)
    outro = scenes[-1].duration
    filt.append(f"anullsrc=r=44100:cl=mono,atrim=0:{outro:.3f}[sil]")
    filt.append("".join(f"[a{i}]" for i in range(n)) + f"[sil]concat=n={n + 1}:v=0:a=1[v]")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[v]", voice])
    total = th.total
    mus, sfx = os.path.join(work, "music.wav"), os.path.join(work, "sfx.wav")
    audio.music_box(total + 0.3, mus, music_mood, seed=seed)
    curtain_times = [0.0]
    for i, sc in enumerate(scenes):
        if sc.curtain_out:
            curtain_times.append(th.starts[i] + sc.duration - 0.45)
        if sc.curtain_in and i > 0:
            curtain_times.append(th.starts[i])
    curtain_times.append(th.starts[-1])
    audio.theater_sfx(total + 0.3, curtain_times, th.starts[-1] + 0.3, sfx)
    out = os.path.join(work, "mix.m4a")
    subprocess.check_call([
        "ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", mus, "-i", sfx, "-filter_complex",
        "[1:a]volume=0.5[m];[2:a]volume=0.55[s];[m][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[md];"
        "[0:a][md][s]amix=inputs=3:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[out]",
        "-map", "[out]", "-c:a", "aac", "-b:a", "192k", out])
    return out


def render_final(story, voice_res, work, name):
    th, warns = build_theater(story, voice_res)
    m = mix(th, voice_res, story.get("music", "playful"), work, seed=len(story.get("id", "")))
    video = os.path.join(work, f"{name}.mp4")
    th.render_video(m, video)
    sheet = os.path.join(work, "final_sheet.jpg")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf", "fps=1/2,scale=270:-1,tile=6x4", "-frames:v", "1", sheet])
    vdur = tts.duration(video)
    if abs(vdur - th.total) > 0.5:
        raise RuntimeError(f"senkron hatası: video {vdur:.2f}s, beklenen {th.total:.2f}s")
    return video, sheet, warns
