# truetake-score

**A score for [truetake](https://github.com/tyler-void/truetake) films, computed from the film's own cue list.**

truetake exports a cue list: every visible event (a line appears, a command starts, an MCP call returns, a
score goes up) with its time, plus the camera's moves. `truetake-score` turns that list into music and
event sounds:

| Layer | What it does |
|---|---|
| bed | A pad on the key's major-ninth chord. It moves to the IV chord while the camera is pushed in, following the same spring as the picture |
| shimmer | Two soft high tones whose level follows how fast the camera moves, so a push is heard as a lift |
| events | One small sound per visible event. Like a haptic event, each has an intensity (gain) and a sharpness (brightness and attack). Every pitch is a degree of the key |
| room | One short, dark reverb shared by everything |

The rules are the film's rules:

- **A sound has a visible cause.** Events come only from the cue list, and each sounds on its own frame;
  nothing is pulled onto a beat grid. Bursts of output are thinned, so a long scroll doesn't rattle.
- **Same cues, same samples.** `score(cues, seed)` is a pure function. Randomness (only the reverb's
  impulse response) comes from the seed. The CLI prints a hash of the samples to compare renders.
- **No noise on its own.** Noise is used only inside the reverb.

## Use

```bash
uv venv && uv pip install -e .
truetake-score render cues.json -o score.wav             # 48 kHz float stereo
truetake-score render cues.json -o score.wav --stems stems/   # plus one WAV per layer
```

The output is not loudness-normalised: truetake mixes it into the film's single audio track and normalises
once. Under narration the bed should sit well below the voice; with no narration, about −21 LUFS integrated
is a calm level.

## The cue list

```json
{"version": 1, "duration": 20.0, "fps": 60, "key": "D major", "camera_spring_w": 1.5,
 "events": [{"t": 1.04, "kind": "message", "intensity": 0.4, "sharpness": 0.2}],
 "camera": [{"t": 5.0, "zoom": 1.3}, {"t": 16.0, "zoom": 1.0}]}
```

Event kinds: `line`, `command`, `message`, `mcp_call`, `mcp_return`, `score`. `intensity` and `sharpness`
are between 0 and 1. Events must be in time order and inside the film.
