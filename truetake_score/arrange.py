"""arrange(cues) -> stereo float samples: a composed cue, not an event sonification.

The film is cut into sections (cues.sections), each with a chord progression in scale degrees and an intensity. The
arranger plays that harmony like a small ensemble scoring a documentary:

  bed      a warm string-like pad holding each chord, brighter and fuller as intensity rises
  bass     the chord's root, softly, on each change
  piano    an arpeggio in eighth notes over the chord tones; above intensity 0.7 an octave doubling joins it,
           below 0.3 it rests, so quiet stretches stay quiet
  accents  a bell on the chord's root for `accent` events only: the two or three moments that matter

Chords change every bar (4 beats at cues.tempo), restarting the progression at each section, so the harmony moves
when the film moves. Humanising (velocity, a few milliseconds of timing) comes from the seed: the same cues and seed
give the same samples. Nothing here is noise except inside the shared room reverb.
"""
from __future__ import annotations

import math

import numpy as np

from .cues import MODES, Cues
from .score import SR, env, place, room

ARP = (0, 2, 4, 7, 4, 2)  # chord-tone indices (0 root, 2 fifth, 4 ninth, 7 octave-third...) walked in eighths


def degree_freq(cues: Cues, degree: int, octave: int) -> float:
    steps = MODES[cues.mode]
    semis = steps[degree % 7] + 12 * (degree // 7)
    midi = 12 * (octave + 1) + cues.tonic + semis
    return 440.0 * 2 ** ((midi - 69) / 12)


def chord_tones(cues: Cues, root: int, octave: int) -> list[float]:
    """Root, third, fifth, seventh, ninth (stacked scale thirds), then the octave's third and fifth."""
    return [degree_freq(cues, root + d, octave) for d in (0, 2, 4, 6, 8, 9, 11)]


def piano(f: float, dur: float, vel: float, rng: np.random.Generator) -> np.ndarray:
    """Additive piano-like tone: decaying partials with slight inharmonicity and a soft hammer attack."""
    n = int(dur * SR)
    i = np.arange(n) / SR
    out = np.zeros(n)
    b = 0.00035
    for k in range(1, 9):
        fk = k * f * math.sqrt(1 + b * k * k)
        if fk > 9000:
            break
        amp = vel / k ** 1.35
        tau = 1.9 / (1 + 0.55 * k)
        out += amp * np.sin(2 * math.pi * fk * i + rng.uniform(0, 2 * math.pi)) * np.exp(-i / tau)
    return out * env(n, 0.004, 10.0)


def pad_chord(freqs: list[float], dur: float, bright: float, rng: np.random.Generator) -> np.ndarray:
    n = int(dur * SR)
    i = np.arange(n) / SR
    out = np.zeros((n, 2))
    att, rel = min(1.4, dur / 3), min(1.8, dur / 2.5)
    shape = np.minimum(1.0, i / att) * np.minimum(1.0, (dur - i) / rel)
    shape = 0.5 - 0.5 * np.cos(np.pi * np.clip(shape, 0, 1))
    for v, f in enumerate(freqs):
        for side, det in ((0, -0.0012), (1, 0.0012)):
            ph = 2 * math.pi * f * (1 + det) * i + rng.uniform(0, 2 * math.pi)
            tone = np.zeros(n)
            for k in range(1, 6):
                tone += (bright ** (k - 1)) / k * np.sin(k * ph)
            out[:, side] += tone * (0.9 + 0.1 * np.sin(2 * math.pi * (0.11 + 0.03 * v) * i))
    return out * shape[:, None] / len(freqs)


def bell(f: float, dur: float, vel: float) -> np.ndarray:
    n = int(dur * SR)
    i = np.arange(n) / SR
    tone = sum(a * np.sin(2 * math.pi * f * r * i) * np.exp(-i / (2.4 / r ** 0.5))
               for r, a in ((1, 1.0), (2.76, 0.42), (5.4, 0.18), (8.93, 0.07)))
    return vel * tone * env(n, 0.002, 10.0)


def arrange(cues: Cues, seed: int = 11, stems: dict | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(round(cues.duration * SR))
    beat = 60.0 / cues.tempo
    bar = 4 * beat
    secs = cues.sections or []
    if not secs:
        from .cues import Section
        secs = [Section(0.0, (0, 5, 3, 4), 0.5)]
    layers = {k: np.zeros((n, 2)) for k in ("bed", "bass", "piano", "accents")}

    chords = []  # (t0, t1, root degree, intensity)
    for si, s in enumerate(secs):
        end = secs[si + 1].t if si + 1 < len(secs) else cues.duration
        t, k = s.t, 0
        while t < end - 0.05:
            t1 = min(end, t + bar)
            chords.append((t, t1, s.progression[k % len(s.progression)], s.intensity))
            t, k = t1, k + 1

    for ci, (t0, t1, root, inten) in enumerate(chords):
        dur = t1 - t0
        # bed: hold the chord, overlapping the next a little so changes are seamless
        tones = chord_tones(cues, root, 3)[: 4 + int(inten > 0.5)]
        pad = pad_chord(tones, dur + 1.2, 0.25 + 0.45 * inten, rng)
        place(layers["bed"], t0, pad[:, 0] * (0.030 + 0.030 * inten), pan=-0.35)
        place(layers["bed"], t0, pad[:, 1] * (0.030 + 0.030 * inten), pan=0.35)
        # bass: on the change
        f_b = degree_freq(cues, root, 2)
        m = int(min(dur + 0.8, 4.0) * SR)
        i = np.arange(m) / SR
        tone = (np.sin(2 * math.pi * f_b * i) + 0.25 * np.sin(4 * math.pi * f_b * i)) * env(m, 0.03, 1.6)
        place(layers["bass"], t0, tone * (0.05 + 0.04 * inten))
        # piano: eighths over the chord tones, resting when the film is quiet
        if inten >= 0.3:
            tones5 = chord_tones(cues, root, 4)
            steps = int(dur / (beat / 2) + 1e-6)
            for s in range(steps):
                ts = t0 + s * beat / 2 + rng.normal(0, 0.006)
                idx = ARP[s % len(ARP)]
                f = tones5[min(idx, len(tones5) - 1)] if idx < 7 else tones5[1] * 2
                accent = 1.0 if s % 4 == 0 else 0.72
                vel = (0.035 + 0.035 * inten) * accent * rng.uniform(0.88, 1.08)
                note = piano(f, 2.2, vel, rng)
                place(layers["piano"], max(0.0, ts), note, pan=-0.15 + 0.3 * ((s % 6) / 5))
                if inten > 0.7 and s % 2 == 0:
                    place(layers["piano"], max(0.0, ts), piano(f * 2, 1.6, vel * 0.45, rng), pan=0.2)

    for e in cues.events:
        if e.kind != "accent":
            continue
        root = next((c[2] for c in reversed(chords) if c[0] <= e.t), 0)
        place(layers["accents"], e.t, bell(degree_freq(cues, root, 5), 3.0, 0.05 * e.intensity), pan=0.1)

    # fade the whole cue in and out
    t = np.arange(n) / SR
    fade = np.minimum(1.0, t / 2.0) * np.minimum(1.0, (cues.duration - t) / 3.0)
    for k in layers:
        layers[k] *= fade[:, None]
    if stems is not None:
        stems.update(layers)
    mix = room(sum(layers.values()), seed, seconds=2.4, wet=0.32)
    return np.tanh(mix * 1.3) / 1.3
