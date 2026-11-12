"""Hazır bir oyun dosyasını (cast + scenes) ajanlar olmadan videoya çevirir. Test ve elle üretim için.

  python pipeline/make_video.py stories/samples/firinci_nuri.json [--engine elevenlabs|edge|silent]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import production  # noqa: E402
import tts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story")
    ap.add_argument("--engine", choices=["elevenlabs", "edge", "silent"])
    a = ap.parse_args()
    story = json.load(open(a.story, encoding="utf-8"))
    engine = a.engine or tts.pick_engine()
    work = os.path.join(ROOT, "output", "manual", story["id"])
    os.makedirs(work, exist_ok=True)
    script = {"cast": story["cast"], "lines": [{"speaker": s["speaker"], "text": s["text"]} for s in story["scenes"]]}
    vplan = [{"tts_text": s.get("tts_text") or s["text"], "settings": s.get("voice_settings")} for s in story["scenes"]]
    rep_path = os.path.join(work, "voice_report.json")
    prev = json.load(open(rep_path)) if os.path.exists(rep_path) else None
    res = production.synth_lines(script, vplan, work, engine, prev=prev)  # sadece değişen replikler yeniden üretilir
    json.dump(res, open(rep_path, "w"), ensure_ascii=False)
    for issue in production.voice_issues(script, res, vplan, engine):
        print("ses uyarısı:", issue)
    th, warns = production.build_theater(story, res)
    for w in warns:
        print("düzen uyarısı:", w)
    th.preview(os.path.join(work, "preview.jpg"))
    video, sheet, _ = production.render_final(story, res, work, story["id"])
    print("video:", video)


if __name__ == "__main__":
    main()
