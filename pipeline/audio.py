"""Ücretsiz, telifsiz arka plan müziği ve geçiş efektleri (numpy ile üretilir).

Hazır müzik kullanmadığımız için Content ID / telif riski sıfırdır.
"""
from __future__ import annotations

import wave

import numpy as np

SR = 44100

# Hikâye anlatımına uygun yumuşak akor dizileri (Hz)
PROGRESSIONS = {
    "warm": [[220.0, 277.18, 329.63], [196.0, 246.94, 293.66], [174.61, 220.0, 261.63], [196.0, 246.94, 329.63]],
    "mystery": [[220.0, 261.63, 329.63], [207.65, 261.63, 311.13], [196.0, 233.08, 293.66], [207.65, 246.94, 311.13]],
    "hopeful": [[261.63, 329.63, 392.0], [220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [196.0, 246.94, 293.66]],
}


def _write(path: str, x: np.ndarray):
    x = np.clip(x, -1, 1)
    pcm = (x * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def music(seconds: float, path: str, mood: str = "warm", bpm: int = 84, seed: int = 0):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    prog = PROGRESSIONS.get(mood, PROGRESSIONS["warm"])
    bar = 60 / bpm * 4
    for b in range(int(seconds / bar) + 1):
        chord = prog[b % len(prog)]
        s0, s1 = int(b * bar * SR), min(n, int((b + 1) * bar * SR + SR * 0.5))
        if s0 >= n:
            break
        tt = t[s0:s1] - b * bar
        env = np.minimum(1, tt / 0.6) * np.exp(-tt / (bar * 1.4))
        for f in chord:
            out[s0:s1] += 0.06 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2.003 * tt))
        out[s0:s1] += 0.05 * env * np.sin(2 * np.pi * chord[0] / 2 * tt)
        # arpej / pluck
        beat = 60 / bpm
        for k in range(8):
            p0 = s0 + int(k * beat / 2 * SR)
            if p0 >= n:
                break
            f = chord[rng.integers(0, 3)] * (2 if k % 3 == 0 else 1)
            L = min(n - p0, int(SR * 0.6))
            pt = np.arange(L) / SR
            out[p0:p0 + L] += 0.035 * np.exp(-pt * 7) * np.sin(2 * np.pi * f * pt)
    fade = int(SR * 1.5)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    _write(path, out)


def whoosh_track(seconds: float, cut_times: list[float], path: str):
    n = int(seconds * SR)
    out = np.zeros(n)
    rng = np.random.default_rng(1)
    L = int(SR * 0.35)
    noise = rng.normal(0, 1, L)
    # basit alçak geçiren filtre
    for i in range(1, L):
        noise[i] = 0.85 * noise[i - 1] + 0.15 * noise[i]
    env = np.sin(np.linspace(0, np.pi, L)) ** 2
    w = noise * env * 0.5
    for c in cut_times:
        s = int(max(0, c - 0.12) * SR)
        e = min(n, s + L)
        out[s:e] += w[: e - s]
    _write(path, out)


# ------------------------------------------------------------------ kukla tiyatrosu sesleri
BOX = {  # müzik kutusu melodileri (3/4), Hz
    "playful": {"bpm": 132, "chords": [[523.25, 659.25, 783.99], [587.33, 698.46, 880.0], [493.88, 587.33, 783.99], [523.25, 659.25, 783.99]]},
    "warm": {"bpm": 108, "chords": [[392.0, 493.88, 587.33], [329.63, 392.0, 493.88], [349.23, 440.0, 523.25], [392.0, 493.88, 587.33]]},
    "mystery": {"bpm": 96, "chords": [[440.0, 523.25, 659.25], [415.3, 523.25, 622.25], [392.0, 466.16, 587.33], [415.3, 493.88, 622.25]]},
    "hopeful": {"bpm": 116, "chords": [[523.25, 659.25, 783.99], [440.0, 523.25, 659.25], [349.23, 440.0, 523.25], [392.0, 493.88, 587.33]]},
}


def music_box(seconds: float, path: str, mood: str = "playful", seed: int = 0):
    rng = np.random.default_rng(seed)
    cfg = BOX.get(mood, BOX["playful"])
    n = int(seconds * SR)
    out = np.zeros(n)
    beat = 60 / cfg["bpm"]
    t_note = np.arange(int(SR * 1.6)) / SR
    def bell(f, amp):
        return amp * np.exp(-t_note * 3.2) * (np.sin(2 * np.pi * f * t_note) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t_note) * np.exp(-t_note * 6))
    i = 0
    while True:
        bar = i // 6
        chord = cfg["chords"][bar % len(cfg["chords"])]
        s0 = int(i * beat / 2 * SR)
        if s0 >= n:
            break
        pos = i % 6
        if pos == 0:
            f, a = chord[0] / 2, 0.09
        else:
            f, a = chord[rng.integers(0, 3)] * (2 if rng.random() < 0.25 else 1), 0.05
        note = bell(f, a)
        e = min(n, s0 + len(note))
        out[s0:e] += note[: e - s0]
        i += 1
    fade = int(SR * 1.2)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    _write(path, out)


def theater_sfx(seconds: float, curtain_times: list[float], applause_at: float, path: str):
    """Perde hışırtısı + finalde alkış."""
    n = int(seconds * SR)
    out = np.zeros(n)
    rng = np.random.default_rng(3)
    L = int(SR * 0.55)
    noise = rng.normal(0, 1, L)
    for k in range(1, L):
        noise[k] = 0.92 * noise[k - 1] + 0.08 * noise[k]
    sw = noise * np.sin(np.linspace(0, np.pi, L)) ** 2 * 0.9
    for c in curtain_times:
        s = int(max(0, c) * SR)
        e = min(n, s + L)
        out[s:e] += sw[: e - s]
    s = int(applause_at * SR)
    clap_len = int(SR * 0.03)
    for _ in range(int((seconds - applause_at) * 90)):
        p = s + int(rng.uniform(0, (seconds - applause_at) * SR))
        if p + clap_len >= n:
            continue
        env = np.exp(-np.arange(clap_len) / (clap_len / 5))
        out[p:p + clap_len] += rng.normal(0, 1, clap_len) * env * rng.uniform(0.05, 0.18)
    if applause_at < seconds:
        tail = n - s
        out[s:] *= np.minimum(1, np.arange(tail) / (SR * 0.3)) * np.minimum(1, (tail - np.arange(tail)) / (SR * 0.6))
    _write(path, out)
