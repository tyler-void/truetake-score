"""truetake-score render cues.json -o score.wav [--stems DIR] [--seed N]"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from . import cues as cuesmod
from .score import SR, score


def sample_hash(x: np.ndarray) -> str:
    """The hash of the samples themselves; a WAV file's header carries a timestamp, so its bytes differ."""
    return hashlib.sha256(np.ascontiguousarray(x, dtype="<f4").tobytes()).hexdigest()


def cmd_render(args) -> int:
    c = cuesmod.load(args.cues)
    stems: dict = {} if args.stems else None
    x = score(c, seed=args.seed, stems=stems)
    out = Path(args.output)
    sf.write(out, x.astype(np.float32), SR, subtype="FLOAT")
    if stems:
        d = Path(args.stems)
        d.mkdir(parents=True, exist_ok=True)
        for name, s in stems.items():
            sf.write(d / f"{name}.wav", s.astype(np.float32), SR, subtype="FLOAT")
    print(f"{out}: {len(x) / SR:.3f}s, {len(c.events)} events, peak {np.abs(x).max():.3f}, samples {sample_hash(x)[:16]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="truetake-score", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render a cue list to a WAV file")
    r.add_argument("cues")
    r.add_argument("-o", "--output", default="score.wav")
    r.add_argument("--stems", help="also write each layer to this directory")
    r.add_argument("--seed", type=int, default=7)
    r.set_defaults(fn=cmd_render)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except cuesmod.CueError as e:
        print(f"truetake-score: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
