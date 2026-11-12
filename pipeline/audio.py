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
