"""Seslendirme. Üç motor:

  elevenlabs : en doğal ses (ELEVENLABS_API_KEY gerekir). Videodaki önerilen yol.
  edge       : Microsoft Edge nöral sesleri, ÜCRETSİZ, anahtar gerekmez (tr-TR-AhmetNeural / EmelNeural).
  silent     : sadece test için; metin uzunluğuna göre sessizlik üretir.

Her sahne ayrı ayrı seslendirilir, böylece sahne süresi = ses süresi olur (saniyesi saniyesine senkron).
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess

import requests

# Konuşmacı -> ses ayarı. Sahnede "speaker" alanı yoksa "narrator" kullanılır.
EDGE_VOICES = {
    "narrator": {"voice": "tr-TR-AhmetNeural", "rate": "+6%", "pitch": "-2Hz"},
    "old": {"voice": "tr-TR-AhmetNeural", "rate": "-6%", "pitch": "-12Hz"},
    "young": {"voice": "tr-TR-AhmetNeural", "rate": "+12%", "pitch": "+8Hz"},
    "woman": {"voice": "tr-TR-EmelNeural", "rate": "+4%", "pitch": "+0Hz"},
    "child": {"voice": "tr-TR-EmelNeural", "rate": "+10%", "pitch": "+25Hz"},
}


def _eleven_voice(speaker: str) -> str:
    # .env / GitHub Secrets ile özelleştirilebilir: ELEVENLABS_VOICE_NARRATOR, ELEVENLABS_VOICE_OLD ...
    env = os.environ.get(f"ELEVENLABS_VOICE_{speaker.upper()}") or os.environ.get("ELEVENLABS_VOICE_NARRATOR")
    if not env:
        raise RuntimeError("ELEVENLABS_VOICE_NARRATOR tanımlı değil (ElevenLabs Voice Library'den bir Türkçe ses ID'si girin).")
    return env


def duration(path: str) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path,
    ])
    return float(json.loads(out)["format"]["duration"])


def tts_elevenlabs(text: str, speaker: str, out: str):
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{_eleven_voice(speaker)}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True},
        },
        timeout=120,
    )
    r.raise_for_status()
    with open(out, "wb") as f:
        f.write(r.content)


def tts_edge(text: str, speaker: str, out: str):
    import edge_tts

    v = EDGE_VOICES.get(speaker, EDGE_VOICES["narrator"])
    asyncio.run(edge_tts.Communicate(text, v["voice"], rate=v["rate"], pitch=v["pitch"]).save(out))


def tts_silent(text: str, speaker: str, out: str):
    secs = max(1.0, len(text) / 15.0)
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                           "anullsrc=r=44100:cl=mono", "-t", f"{secs:.2f}", "-q:a", "4", out])


def pick_engine() -> str:
    e = os.environ.get("TTS_ENGINE")
    if e:
        return e
    return "elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "edge"


def synth(text: str, speaker: str, out: str, engine: str):
    fn = {"elevenlabs": tts_elevenlabs, "edge": tts_edge, "silent": tts_silent}[engine]
    for attempt in range(3):
        try:
            fn(text, speaker, out)
            return duration(out)
        except Exception as e:  # ağ hatalarında tekrar dene
            if attempt == 2:
                raise
            print(f"  TTS tekrar deneniyor ({e})")
