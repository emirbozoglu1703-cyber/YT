"""Seslendirme motorları + ses denetçisinin kullandığı ölçümler.

Her motor (ses dosyası, kelime başlangıç zamanları) üretir. Altyazılar bu gerçek zamanlara oturur.
  elevenlabs : ELEVENLABS_API_KEY ile, /with-timestamps uç noktası (karakter zamanları -> kelime zamanları)
  edge       : ücretsiz Microsoft nöral ses, WordBoundary olaylarından kelime zamanları
  silent     : test; metin uzunluğundan tahmin
"""
from __future__ import annotations

import asyncio
import base64
import difflib
import json
import os
import re
import subprocess

import requests

EDGE_VOICES = {  # Microsoft'ta 2 Türkçe ses var; karakterler perde (pitch) ve hızla ayrılır
    "narrator": {"voice": "tr-TR-AhmetNeural", "rate": "+4%", "pitch": "-4Hz"},
    "man": {"voice": "tr-TR-AhmetNeural", "rate": "+8%", "pitch": "+2Hz"},
    "old": {"voice": "tr-TR-AhmetNeural", "rate": "-2%", "pitch": "-16Hz"},
    "young": {"voice": "tr-TR-AhmetNeural", "rate": "+14%", "pitch": "+12Hz"},
    "woman": {"voice": "tr-TR-EmelNeural", "rate": "+6%", "pitch": "+0Hz"},
    "child": {"voice": "tr-TR-EmelNeural", "rate": "+12%", "pitch": "+28Hz"},
    "oldwoman": {"voice": "tr-TR-EmelNeural", "rate": "-2%", "pitch": "-10Hz"},
}
DEFAULT_SETTINGS = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def voice_config() -> dict:
    try:
        with open(os.path.join(ROOT, "config", "voices.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def pick_engine() -> str:
    return os.environ.get("TTS_ENGINE") or voice_config().get("engine") or ("elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "edge")


def _api_key() -> str:
    # Claude Code bulut ortamında anahtar ağ vekili tarafından başlığa eklenir; burada yer tutucu yeterli.
    return os.environ.get("ELEVENLABS_API_KEY") or "proxy-injected"


def _voice_id(speaker: str) -> str:
    voices = voice_config().get("voices", {})
    v = os.environ.get(f"ELEVENLABS_VOICE_{speaker.upper()}") or voices.get(speaker) or voices.get("narrator") or os.environ.get("ELEVENLABS_VOICE_NARRATOR")
    if not v:
        raise RuntimeError(f"'{speaker}' için ElevenLabs ses ID'si yok: config/voices.json dosyasını doldurun")
    return v


def duration(path: str) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path], stderr=subprocess.DEVNULL)
    return float(json.loads(out)["format"]["duration"])


TAG_RE = re.compile(r"\[[^\]]*\]")


def strip_tags(text: str) -> str:
    """v3 duygu işaretlerini ([whispers] vb.) metinden çıkarır."""
    return re.sub(r"\s+", " ", TAG_RE.sub("", text)).strip()


def _words_from_chars(chars, starts):
    words, cur, cur_start = [], "", None
    for ch, st in zip(chars, starts):
        if ch.isspace():
            if cur:
                words.append((cur, cur_start))
            cur, cur_start = "", None
        else:
            if not cur:
                cur_start = st
            cur += ch
    if cur:
        words.append((cur, cur_start))
    # [whispers] gibi duygu işaretleri okunmaz; kelime zamanlarından çıkar
    out, in_tag = [], False
    for w, st in words:
        if w.startswith("["):
            in_tag = True
        if not in_tag:
            out.append(st)
        if w.endswith("]"):
            in_tag = False
    return out


def tts_elevenlabs(text, speaker, out, settings=None):
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{_voice_id(speaker)}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": _api_key(), "Content-Type": "application/json"},
        json={"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL") or voice_config().get("model", "eleven_multilingual_v2"), "language_code": "tr",
              "voice_settings": {**DEFAULT_SETTINGS, **(settings or {})}},
        timeout=180,
    )
    if r.status_code == 400 and "language_code" in r.text:  # bazı modeller language_code kabul etmez
        r = requests.post(r.request.url, headers=r.request.headers,
                          json={k: v for k, v in json.loads(r.request.body).items() if k != "language_code"}, timeout=180)
    r.raise_for_status()
    data = r.json()
    with open(out, "wb") as f:
        f.write(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or data.get("normalized_alignment") or {}
    return _words_from_chars(al.get("characters", []), al.get("character_start_times_seconds", []))


def tts_edge(text, speaker, out, settings=None):
    import edge_tts

    text = strip_tags(text)  # Microsoft sesleri [whispers] gibi işaretleri anlamaz, okurdu
    v = {**EDGE_VOICES.get(speaker, EDGE_VOICES["narrator"]), **{k: s for k, s in (settings or {}).items() if k in ("rate", "pitch")}}

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy and os.path.exists("/root/.ccr/ca-bundle.crt"):  # Claude Code bulut ortamı: vekil sunucu + onun CA'sı
        import ssl
        import edge_tts.communicate as _c
        _c._SSL_CTX = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")

    async def run():
        comm = edge_tts.Communicate(text, v["voice"], rate=v["rate"], pitch=v["pitch"], boundary="WordBoundary", proxy=proxy)
        starts = []
        with open(out, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    starts.append(ch["offset"] / 1e7)
        return starts

    return asyncio.run(run())


def tts_silent(text, speaker, out, settings=None):
    secs = max(1.0, len(text) / 15.0)
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{secs:.2f}", "-q:a", "4", out])
    return None


def synth(text, speaker, out, engine, settings=None):
    """-> (süre, kelime_başlangıçları | None)"""
    fn = {"elevenlabs": tts_elevenlabs, "edge": tts_edge, "silent": tts_silent}[engine]
    last = None
    for _ in range(3):
        try:
            starts = fn(text, speaker, out, settings)
            return duration(out), starts
        except Exception as e:
            last = e
            print(f"  TTS tekrar ({e})")
    raise last


def map_word_starts(display_text: str, tts_starts, dur: float):
    """Ekranda görünen kelimelere zaman eşle. TTS metni farklıysa (ör. '36' -> 'otuz altı') oranla dağıt."""
    words = display_text.split()
    if tts_starts and len(tts_starts) == len(words):
        return list(tts_starts)
    if tts_starts:
        a, b = tts_starts[0], max(tts_starts[-1] + 0.3, tts_starts[0] + 0.5)
    else:
        a, b = 0.05, max(0.3, dur - 0.3)
    weights = [len(w) + 2 for w in words]
    tot, acc, out = sum(weights) or 1, a, []
    for w in weights:
        out.append(acc)
        acc += (b - a) * w / tot
    return out


# ------------------------------------------------------------------ ölçümler (ses denetçisi için)
def measure(path: str) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect,silencedetect=n=-40dB:d=0.45", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mx = re.search(r"max_volume: (-?[\d.]+)", err)
    mean = re.search(r"mean_volume: (-?[\d.]+)", err)
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err)]
    return {"duration": round(duration(path), 2), "max_db": float(mx.group(1)) if mx else None,
            "mean_db": float(mean.group(1)) if mean else None, "long_pauses": [round(s, 2) for s in silences if s > 0.45]}


def transcribe(path: str) -> str | None:
    """ElevenLabs Speech-to-Text; anahtar yoksa None."""
    if pick_engine() != "elevenlabs":
        return None
    try:
        with open(path, "rb") as f:
            r = requests.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": _api_key()},
                              data={"model_id": os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v1"), "language_code": "tur"},
                              files={"file": (os.path.basename(path), f, "audio/mpeg")}, timeout=120)
        r.raise_for_status()
        return r.json().get("text", "")
    except Exception as e:
        print(f"  STT başarısız: {e}")
        return None


def norm(s: str) -> str:
    return re.sub(r"[^\wçğıöşü ]", "", s.lower().replace("i̇", "i")).strip()


def similarity(a: str, b: str) -> float:
    a = strip_tags(a)
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def compress_pauses(path: str, starts, max_pause: float = 0.32):
    """Replik içindeki uzun sessizlikleri max_pause'a indirir (noktalama korunur, düz okuma olmaz).
    Kelime başlangıç zamanlarını kesilen süreye göre kaydırır."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", f"silencedetect=n=-42dB:d={max_pause}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ss = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ee = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    cuts = []
    for a, b in zip(ss, ee):
        a = max(0.0, a)
        if b - a > max_pause:
            mid = (a + b) / 2
            half = max_pause / 2
            cuts.append((a + half, b - half))  # ortadaki fazlalığı kes
    if not cuts:
        return starts
    expr = "+".join(f"between(t,{c0:.3f},{c1:.3f})" for c0, c1 in cuts)
    tmp = path + ".cp.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", path, "-af", f"aselect='not({expr})',asetpts=N/SR/TB", tmp], capture_output=True)
    if not os.path.exists(tmp) or duration(tmp) < 0.3:
        return starts
    os.replace(tmp, path)
    if not starts:
        return starts
    out = []
    for t in starts:
        shift = 0.0
        for c0, c1 in cuts:
            if t >= c1:
                shift += c1 - c0
            elif t > c0:
                shift += t - c0
        out.append(max(0.0, t - shift))
    return out


def trim_silence(path: str):
    """Sondaki fazla sessizliği kırpar (kelime zamanları değişmesin diye baş kısma dokunmaz)."""
    tmp = path + ".trim.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", path, "-af",
                    "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse", tmp], capture_output=True)
    try:
        ok = duration(tmp) > 0.3
    except Exception:
        ok = False
    if ok:
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)
