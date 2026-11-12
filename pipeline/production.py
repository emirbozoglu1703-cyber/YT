"""Üretim araçları: seslendirme, ses miksajı, render. Ajanlar bu araçları kullanır."""
from __future__ import annotations

import os
import subprocess

import audio
import render
import tts

PAD = 0.22  # cümleler arası nefes payı


def synth_lines(script_lines, voice_plan, work, engine, prev=None):
    """Her satırı seslendirir. prev verilirse sadece talimatı değişen satırlar yeniden üretilir."""
    results = []
    for i, (line, vp) in enumerate(zip(script_lines, voice_plan)):
        path = os.path.join(work, f"line{i:02d}.mp3")
        key = (vp.get("tts_text"), vp.get("speaker"), str(sorted((vp.get("settings") or {}).items())))
        if prev and i < len(prev) and prev[i].get("key") == key and os.path.exists(path):
            results.append(prev[i])
            continue
        dur, starts = tts.synth(vp.get("tts_text") or line["text"], vp.get("speaker") or line.get("speaker", "narrator"), path, engine, vp.get("settings"))
        tts.trim_silence(path)
        dur = tts.duration(path)
        met = tts.measure(path)
        tr = tts.transcribe(path) if engine == "elevenlabs" else None
        words = len(line["text"].split())
        results.append({"key": key, "path": path, "duration": dur, "tts_starts": starts, "metrics": met,
                        "words_per_sec": round(words / max(0.1, dur), 2), "transcript": tr,
                        "similarity": tts.similarity(vp.get("tts_text") or line["text"], tr) if tr else None})
    return results


def voice_auto_issues(script_lines, voice_res, voice_plan, engine="elevenlabs"):
    hard = []
    total = sum(r["duration"] + PAD for r in voice_res)
    for i, (r, line) in enumerate(zip(voice_res, script_lines), 1):
        if engine == "silent":  # test sesi: akustik kontroller anlamsız
            break
        wps = r["words_per_sec"]
        if wps > 4.2 or wps < 1.6:
            hard.append(f"satır {i}: hız {wps} kelime/sn (1.6-4.2 olmalı)")
        if r["metrics"]["max_db"] is not None and r["metrics"]["max_db"] > -0.3:
            hard.append(f"satır {i}: ses patlıyor (max {r['metrics']['max_db']} dB)")
        if any(p > 0.8 for p in r["metrics"]["long_pauses"]):
            hard.append(f"satır {i}: uzun duraklama {r['metrics']['long_pauses']}")
        if r["similarity"] is not None and r["similarity"] < 0.85:
            hard.append(f"satır {i}: yanlış okuma (benzerlik {r['similarity']}): duyulan '{r['transcript']}'")
    if not 25 <= total <= 58:
        hard.append(f"toplam süre {total:.1f} sn (25-58 olmalı)")
    if len(voice_plan) != len(script_lines):
        hard.append("ses planındaki satır sayısı senaryoyla eşleşmiyor")
    return hard


def build_scenes(script_lines, layout, voice_res):
    scenes = []
    for line, sd, vr in zip(script_lines, layout, voice_res):
        d = vr["duration"] + PAD
        starts = tts.map_word_starts(line["text"], vr.get("tts_starts"), vr["duration"])
        scenes.append(render.scene_from_dict({**sd, "text": line["text"]}, d, starts))
    return scenes


def preview(scenes, out):
    return render.render_preview(scenes, out)


def mix_audio(voice_res, scenes, music_mood, work, seed=0):
    voice = os.path.join(work, "voice.wav")
    inputs, filt = [], []
    for i, (vr, sc) in enumerate(zip(voice_res, scenes)):
        inputs += ["-i", vr["path"]]
        filt.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=pad_dur={max(0.0, sc.duration - vr['duration']):.3f},atrim=0:{sc.duration:.3f}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(scenes))) + f"concat=n={len(scenes)}:v=0:a=1[v]")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[v]", voice])
    total = sum(s.duration for s in scenes)
    mus, wsh = os.path.join(work, "music.wav"), os.path.join(work, "whoosh.wav")
    audio.music(total + 0.5, mus, music_mood, seed=seed)
    cuts, acc = [], 0.0
    for s in scenes[:-1]:
        acc += s.duration
        cuts.append(acc)
    audio.whoosh_track(total + 0.5, cuts, wsh)
    mix = os.path.join(work, "mix.m4a")
    subprocess.check_call([
        "ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", mus, "-i", wsh, "-filter_complex",
        "[1:a]volume=0.55[m];[2:a]volume=0.35[w];[m][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[md];"
        "[0:a][md][w]amix=inputs=3:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[out]",
        "-map", "[out]", "-c:a", "aac", "-b:a", "192k", mix])
    return mix, total


def render_final(scenes, mix, work, name, thumb_text):
    video = os.path.join(work, f"{name}.mp4")
    render.render_video(scenes, mix, video)
    thumb = render.render_thumbnail(scenes[0], thumb_text, os.path.join(work, "thumbnail.jpg"))
    sheet = os.path.join(work, "final_sheet.jpg")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf", "fps=1/2,scale=270:-1,tile=6x4", "-frames:v", "1", sheet])
    vdur, total = tts.duration(video), sum(s.duration for s in scenes)
    if abs(vdur - total) > 0.5:
        raise RuntimeError(f"senkron hatası: video {vdur:.2f}s, beklenen {total:.2f}s")
    return video, thumb, sheet
