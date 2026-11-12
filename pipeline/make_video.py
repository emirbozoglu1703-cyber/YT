"""Tek bir hikâye JSON'unu (ajanlar olmadan) videoya çevirir. Test ve elle üretim için.

  python pipeline/make_video.py stories/samples/bakkal_ferit.json [--engine edge|elevenlabs|silent]
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
    lines = [{"text": s["text"], "speaker": s.get("speaker", "narrator")} for s in story["scenes"]]
    vplan = [{"tts_text": s.get("tts_text", s["text"]), "speaker": s.get("speaker", "narrator"), "settings": s.get("voice_settings")} for s in story["scenes"]]
    print(f"[{story['id']}] ses: {engine}")
    vres = production.synth_lines(lines, vplan, work, engine)
    for i, issue in enumerate(production.voice_auto_issues(lines, vres, vplan, engine)):
        print("  ses uyarısı:", issue)
    scenes = production.build_scenes(lines, story["scenes"], vres)
    production.preview(scenes, os.path.join(work, "preview.jpg"))
    mix, total = production.mix_audio(vres, scenes, story.get("music", "warm"), work)
    video, thumb, sheet = production.render_final(scenes, mix, work, story["id"], story["title"])
    print(f"[{story['id']}] {total:.1f} sn -> {video}")


if __name__ == "__main__":
    main()
