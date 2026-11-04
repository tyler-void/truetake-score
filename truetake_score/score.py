"""score(cues) -> stereo float samples at 48 kHz. A pure function of the cue list and the seed.

Layers, quietest first:
  bed      a pad on the tonic's major-ninth chord; it moves to the IV chord while the camera is pushed in
           (the spring curve of the picture drives the crossfade) and opens a little brighter
  shimmer  two soft high sines whose level follows how fast the camera moves, so a push is heard as a lift
  events   one small sound per visible event, haptic-style: intensity is gain, sharpness is brightness and
           attack. Every pitch is a degree of the key, so the events are part of the music
  room     a short, dark reverb shared by everything, so sounds sit in one space

No noise reaches the output dry and nothing is quantised to a beat grid: an event sounds on its own frame.
"""
from __future__ import annotations

import math

import numpy as np

from .cues import MODES, Cues

SR = 48000
LINE_GAP = 0.08  # a line this close to the previous line joins its burst: one tap per burst of output


def freq(cues: Cues, degree: int, octave: int) -> float:
    """The frequency of a scale degree (0 = tonic, may exceed 6) in an octave (4 = the octave of A440)."""
    steps = MODES[cues.mode]
    semis = steps[degree % 7] + 12 * (degree // 7)
    midi = 12 * (octave + 1) + cues.tonic + semis
    return 440.0 * 2 ** ((midi - 69) / 12)


def spring_step(t: np.ndarray, t0: float, w: float) -> np.ndarray:
    u = np.maximum(t - t0, 0.0)
    return np.where(t >= t0, 1.0 - (1.0 + w * u) * np.exp(-w * u), 0.0)


def env(n: int, attack: float, decay: float) -> np.ndarray:
    i = np.arange(n) / SR
    a = np.clip(i / max(attack, 1e-4), 0.0, 1.0)
    return (0.5 - 0.5 * np.cos(np.pi * a)) * np.exp(-i / decay)  # a raised-cosine attack never clicks


def pad_voice(t: np.ndarray, f: float, bright: np.ndarray, detune: float = 0.001) -> np.ndarray:
    out = np.zeros_like(t)
    for d in (-detune, detune):
        ph = 2 * np.pi * f * (1 + d) * t
        out += np.sin(ph) + bright * (0.22 * np.sin(2 * ph) + 0.07 * np.sin(3 * ph))
    return out * 0.5


def place(buf: np.ndarray, t: float, sig: np.ndarray, pan: float = 0.0) -> None:
    i0 = int(round(t * SR))
    if i0 >= buf.shape[0]:
        return
    sig = sig[: buf.shape[0] - i0]
    a = (pan + 1) * math.pi / 4
    buf[i0:i0 + len(sig), 0] += sig * math.cos(a)
    buf[i0:i0 + len(sig), 1] += sig * math.sin(a)


def camera_curve(cues: Cues, t: np.ndarray) -> np.ndarray:
    """0 at the opening zoom, 1 at the deepest push, following the picture's spring."""
    if not cues.camera:
        return np.zeros_like(t)
    base = 1.0
    deepest = max((abs(c.zoom - base) for c in cues.camera), default=0.0) or 1.0
    z, prev = np.zeros_like(t), base
    for c in cues.camera:
        z += (c.zoom - prev) * spring_step(t, c.t, cues.camera_spring_w)
        prev = c.zoom
    return np.clip(np.abs(z) / deepest, 0.0, 1.0)


def bed(cues: Cues, t: np.ndarray, cam: np.ndarray) -> np.ndarray:
    out = np.zeros((len(t), 2))
    bright = 0.2 + 0.4 * cam
    chords = {0: (0, 2, 4, 6, 8), 3: (3, 5, 7, 9, 11)}  # I9 and IV9, stacked thirds of the scale
    for root, weight in ((0, 1.0 - cam), (3, cam)):
        for k, deg in enumerate(chords[root]):
            f = freq(cues, deg, 3 if deg < 7 else 3)
            lfo = 1.0 + 0.1 * np.sin(2 * np.pi * (0.05 + 0.011 * k) * t + 1.7 * k)
            v = pad_voice(t, f, bright) * weight * lfo * 0.032
            place(out, 0.0, v, pan=(k - 2) * 0.22)
    fade = np.minimum(1.0, t / 3.0) * np.minimum(1.0, (cues.duration - t) / 2.0)
    return out * fade[:, None]


def shimmer(cues: Cues, t: np.ndarray, cam: np.ndarray) -> np.ndarray:
    speed = np.abs(np.gradient(cam)) * SR
    speed = speed / (speed.max() or 1.0)
    level = np.convolve(speed, np.ones(2400) / 2400, mode="same") * 0.022  # 50 ms smoothing
    sig = np.sin(2 * np.pi * freq(cues, 0, 5) * t) + 0.6 * np.sin(2 * np.pi * freq(cues, 4, 5) * t + 0.8)
    out = np.zeros((len(t), 2))
    place(out, 0.0, sig * level * 0.7, pan=-0.4)
    place(out, 0.0, np.roll(sig, 480) * level * 0.7, pan=0.4)
    return out


def tone(f: float, dur: float, attack: float, decay: float, partials=((1.0, 1.0),)) -> np.ndarray:
    n = int(dur * SR)
    i = np.arange(n) / SR
    return sum(a * np.sin(2 * np.pi * f * r * i) for r, a in partials) * env(n, attack, decay)


def events(cues: Cues, n: int) -> np.ndarray:
    out = np.zeros((n, 2))
    last_line, msg_step, score_step = -1.0, 0, 0
    penta = (0, 1, 2, 4, 5) if cues.mode == "major" else (0, 2, 3, 4, 6)
    for e in cues.events:
        g, s = e.intensity, e.sharpness
        if e.kind == "line":
            burst = e.t - last_line < LINE_GAP
            last_line = e.t
            if burst:
                continue
        attack = 0.001 + (1.0 - s) * 0.012
        if e.kind == "line":
            place(out, e.t, 0.018 * g * tone(freq(cues, 4, 6), 0.08, attack + 0.001, 0.02), pan=0.35)
        elif e.kind == "command":
            sig = tone(freq(cues, 0, 4), 0.4, attack, 0.12, ((1, 1.0), (4, 0.18 * s)))
            place(out, e.t, 0.07 * g * sig, pan=-0.1)
        elif e.kind == "mcp_call":
            sig = tone(freq(cues, 1, 5), 0.6, attack, 0.22, ((1, 1.0), (2.76, 0.2 * s)))
            place(out, e.t, 0.04 * g * sig, pan=-0.3)
        elif e.kind == "mcp_return":
            for j, deg in enumerate((2, 4)):
                sig = tone(freq(cues, deg, 5), 0.6, attack, 0.2, ((1, 1.0), (2.76, 0.15 * s)))
                place(out, e.t + j * 0.07, 0.04 * g * sig, pan=-0.3 + 0.2 * j)
        elif e.kind == "message":
            deg = penta[msg_step % len(penta)] + 7 * (msg_step // len(penta))
            msg_step += 1
            sig = tone(freq(cues, deg, 4), 1.4, 0.012, 0.5, ((1, 1.0), (2, 0.25), (3, 0.06)))
            place(out, e.t, 0.05 * g * sig)
        elif e.kind == "score":
            deg = penta[score_step % len(penta)] + 7 * (score_step // len(penta))
            score_step += 1
            sig = tone(freq(cues, deg, 5), 1.6, attack, 0.6, ((1, 1.0), (2, 0.3), (3, 0.1 * s)))
            place(out, e.t, 0.07 * g * sig, pan=0.15)
    return out


def room(x: np.ndarray, seed: int, seconds: float = 1.6, wet: float = 0.2) -> np.ndarray:
    """A dark convolution reverb: seeded noise, smoothed and decaying. Same seed, same room."""
    rng = np.random.default_rng(seed)
    m = int(seconds * SR)
    decay = np.exp(-np.arange(m) / SR * (6.9 / seconds))
    out = np.empty_like(x)
    for ch in range(2):
        ir = np.convolve(rng.standard_normal(m), np.ones(24) / 24, mode="same") * decay
        ir /= np.sqrt(np.sum(ir ** 2))
        size = 1 << int(np.ceil(np.log2(len(x) + m)))
        y = np.fft.irfft(np.fft.rfft(x[:, ch], size) * np.fft.rfft(ir, size), size)[: len(x)]
        out[:, ch] = x[:, ch] + wet * y
    return out


def score(cues: Cues, seed: int = 7, stems: dict | None = None) -> np.ndarray:
    n = int(round(cues.duration * SR))
    t = np.arange(n) / SR
    cam = camera_curve(cues, t)
    layers = {"bed": bed(cues, t, cam), "shimmer": shimmer(cues, t, cam), "events": events(cues, n)}
    if stems is not None:
        stems.update(layers)
    mix = room(sum(layers.values()), seed)
    return np.tanh(mix * 1.2) / 1.2
