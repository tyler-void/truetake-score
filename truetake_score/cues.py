"""The cue list: what truetake exports and the score answers.

    {"version": 1, "duration": 20.0, "fps": 60, "key": "D major",
     "camera_spring_w": 1.5,
     "events": [{"t": 1.04, "kind": "message", "intensity": 0.4, "sharpness": 0.2}, ...],
     "camera": [{"t": 5.0, "zoom": 1.3}, ...]}

Every event is something visible in the film at time `t` (seconds). `intensity` (0..1) is how strongly it
lands, `sharpness` (0..1) how bright and quick it sounds: the two axes of a haptic event, used for sound.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("line", "command", "message", "mcp_call", "mcp_return", "score", "accent")
MODES = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10)}
PITCH = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
         "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


class CueError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    t: float
    kind: str
    intensity: float = 0.5
    sharpness: float = 0.5


@dataclass(frozen=True)
class Camera:
    t: float
    zoom: float


@dataclass(frozen=True)
class Section:
    """A stretch of the film with one musical mood: a chord progression (scale degrees, 0 = tonic) and an intensity."""
    t: float
    progression: tuple[int, ...]
    intensity: float


@dataclass
class Cues:
    duration: float
    fps: int
    tonic: int  # pitch class, C = 0
    mode: str
    camera_spring_w: float = 1.5
    events: list[Event] = field(default_factory=list)
    camera: list[Camera] = field(default_factory=list)
    tempo: float = 72.0
    sections: list[Section] = field(default_factory=list)


def _unit(v, where: str) -> float:
    x = float(v)
    if not 0.0 <= x <= 1.0:
        raise CueError(f"{where}: must be between 0 and 1, got {x}")
    return x


def parse(raw: dict) -> Cues:
    if raw.get("version", 1) != 1:
        raise CueError("only cue list version 1 is supported")
    try:
        duration, fps = float(raw["duration"]), int(raw.get("fps", 60))
    except (KeyError, TypeError, ValueError):
        raise CueError("`duration` (seconds) is required")
    if duration <= 0:
        raise CueError("`duration` must be positive")
    key = str(raw.get("key", "D major")).split()
    if len(key) != 2 or key[0] not in PITCH or key[1] not in MODES:
        raise CueError(f"`key` is '<tonic> major|minor', e.g. 'D major'; got {raw.get('key')!r}")
    cues = Cues(duration=duration, fps=fps, tonic=PITCH[key[0]], mode=key[1],
                camera_spring_w=float(raw.get("camera_spring_w", 1.5)))
    for i, e in enumerate(raw.get("events") or []):
        where = f"events[{i}]"
        if e.get("kind") not in KINDS:
            raise CueError(f"{where}: kind must be one of {KINDS}, got {e.get('kind')!r}")
        t = float(e["t"])
        if not 0.0 <= t <= duration:
            raise CueError(f"{where}: t={t} is outside the film (0..{duration})")
        cues.events.append(Event(t=t, kind=e["kind"], intensity=_unit(e.get("intensity", 0.5), f"{where}.intensity"),
                                 sharpness=_unit(e.get("sharpness", 0.5), f"{where}.sharpness")))
    if [e.t for e in cues.events] != sorted(e.t for e in cues.events):
        raise CueError("events must be in time order")
    for i, c in enumerate(raw.get("camera") or []):
        cues.camera.append(Camera(t=float(c["t"]), zoom=float(c["zoom"])))
    cues.tempo = float(raw.get("tempo", 72))
    if not 40 <= cues.tempo <= 160:
        raise CueError("`tempo` is between 40 and 160 BPM")
    for i, sec in enumerate(raw.get("sections") or []):
        where = f"sections[{i}]"
        prog = tuple(int(d) for d in sec.get("progression") or [0])
        if any(not 0 <= d <= 6 for d in prog):
            raise CueError(f"{where}: progression is scale degrees 0..6 (0 = the tonic chord)")
        cues.sections.append(Section(t=float(sec["t"]), progression=prog,
                                     intensity=_unit(sec.get("intensity", 0.5), f"{where}.intensity")))
    if [s.t for s in cues.sections] != sorted(s.t for s in cues.sections):
        raise CueError("sections must be in time order")
    return cues


def load(path: str | Path) -> Cues:
    return parse(json.loads(Path(path).read_text(encoding="utf-8")))
