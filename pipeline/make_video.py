"""Bir hikâye JSON'undan yayına hazır Shorts videosu üretir.

Kullanım:
  python pipeline/make_video.py stories/queue/01_oduncu.json
  python pipeline/make_video.py --next            # kuyruktaki ilk hikâye
  python pipeline/make_video.py --next --upload   # üret + YouTube'a yükle + published/'a taşı
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

import audio  # noqa: E402
import render  # noqa: E402
import tts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "stories", "queue")
PUBLISHED = os.path.join(ROOT, "stories", "published")
OUT = os.path.join(ROOT, "output")
PAD = 0.22  # cümleler arası nefes payı (sn)


def build(story_path: str, engine: str | None = None) -> dict:
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)
    sid = story["id"]
    work = os.path.join(OUT, sid)
    os.makedirs(work, exist_ok=True)
    engine = engine or tts.pick_engine()
    print(f"[{sid}] seslendirme motoru: {engine}")

    # 1) Her sahneyi ayrı seslendir -> süreleri öğren
    clips, scenes = [], []
    for i, sd in enumerate(story["scenes"]):
        clip = os.path.join(work, f"s{i:02d}.mp3")
        d = tts.synth(sd["text"], sd.get("speaker", "narrator"), clip, engine)
        clips.append((clip, d))
        scenes.append(render.scene_from_dict(sd, d + PAD))
    total = sum(s.duration for s in scenes)
    print(f"[{sid}] toplam süre {total:.1f}s, {len(scenes)} sahne")
    if total > 60:
        print("  UYARI: 60 sn üstü. Shorts limiti 3 dk ama 60 sn altı en iyi performansı verir.")

    # 2) Ses parçalarını sahne sürelerine göre birleştir (+ boşluk)
    voice = os.path.join(work, "voice.wav")
    inputs, filt = [], []
    for i, (clip, d) in enumerate(clips):
        inputs += ["-i", clip]
        filt.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=pad_dur={scenes[i].duration - d:.3f}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=0:a=1[v]")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[v]", voice])

    # 3) Müzik + geçiş efektleri, sesin altına karıştır
    mus = os.path.join(work, "music.wav")
    wsh = os.path.join(work, "whoosh.wav")
    audio.music(total + 0.5, mus, story.get("music", "warm"), seed=len(sid))
    cuts, acc = [], 0.0
    for s in scenes[:-1]:
        acc += s.duration
        cuts.append(acc)
    audio.whoosh_track(total + 0.5, cuts, wsh)
    mix = os.path.join(work, "mix.m4a")
    subprocess.check_call([
        "ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", mus, "-i", wsh,
        "-filter_complex",
        "[1:a]volume=0.55[m];[2:a]volume=0.35[w];[m][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[md];"
        "[0:a][md][w]amix=inputs=3:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[out]",
        "-map", "[out]", "-c:a", "aac", "-b:a", "192k", mix,
    ])

    # 4) Görüntü
    video = os.path.join(work, f"{sid}.mp4")
    render.render_video(scenes, mix, video)
    thumb = os.path.join(work, "thumbnail.jpg")
    render.render_thumbnail(scenes[0], story.get("thumbnail_text", story["title"]), thumb)

    # 5) Kalite kontrol: süre farkı ve kare örnekleri
    vdur = tts.duration(video)
    print(f"[{sid}] video süresi {vdur:.2f}s (beklenen {total:.2f}s)")
    if abs(vdur - total) > 0.5:
        raise RuntimeError("Ses/görüntü senkronu kaydı: süre farkı > 0.5 sn")
    qa = os.path.join(work, "qa")
    os.makedirs(qa, exist_ok=True)
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf", "fps=1/2,scale=270:-1,tile=6x4", "-frames:v", "1", os.path.join(qa, "contact_sheet.jpg")])

    meta = {"id": sid, "video": video, "thumbnail": thumb, "title": story["title"],
            "description": story.get("description", ""), "tags": story.get("tags", []),
            "story_path": story_path, "synthetic_realistic": story.get("synthetic_realistic", False)}
    with open(os.path.join(work, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[{sid}] HAZIR -> {video}")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story", nargs="?")
    ap.add_argument("--next", action="store_true", help="kuyruktaki ilk hikâyeyi al")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--engine", choices=["elevenlabs", "edge", "silent"])
    ap.add_argument("--privacy", default=os.environ.get("YT_PRIVACY", "public"))
    a = ap.parse_args()

    path = a.story
    if a.next:
        q = sorted(glob.glob(os.path.join(QUEUE, "*.json")))
        if not q:
            print("Kuyruk boş. `python pipeline/write_story.py` ile yeni hikâye üretin.")
            sys.exit(1)
        path = q[0]
    if not path:
        ap.error("hikâye yolu ya da --next verin")

    meta = build(path, a.engine)
    if a.upload:
        import upload

        vid = upload.upload(meta, privacy=a.privacy)
        os.makedirs(PUBLISHED, exist_ok=True)
        with open(path, encoding="utf-8") as f:
            story = json.load(f)
        story["youtube_id"] = vid
        with open(os.path.join(PUBLISHED, os.path.basename(path)), "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)
        os.remove(path)
        print(f"Yayınlandı: https://youtube.com/shorts/{vid}")


if __name__ == "__main__":
    main()
