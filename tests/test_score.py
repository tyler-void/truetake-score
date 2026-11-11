"""The score's rules: same cues give the same samples, a sound starts on its event, and bad cues are refused."""
import numpy as np
import pytest

from truetake_score import cues as cuesmod
from truetake_score.cli import sample_hash
from truetake_score.score import SR, events, freq, score


def make(events=(), camera=(), duration=4.0, key="D major"):
    return cuesmod.parse({"version": 1, "duration": duration, "fps": 60, "key": key,
                          "events": list(events), "camera": list(camera)})


def test_same_cues_same_samples():
    c = make([{"t": 0.5, "kind": "command"}, {"t": 1.0, "kind": "mcp_return"}], [{"t": 1.0, "zoom": 1.3}])
    assert sample_hash(score(c)) == sample_hash(score(c))
    assert sample_hash(score(c, seed=1)) != sample_hash(score(c, seed=2))  # the seed only moves the room


def test_length_is_the_film_to_the_sample():
    assert len(score(make(duration=2.5))) == int(2.5 * SR)


def test_an_event_sounds_on_its_own_time_and_not_before():
    c = make([{"t": 1.25, "kind": "command", "intensity": 1.0}])
    x = events(c, int(c.duration * SR))
    i0 = int(1.25 * SR)
    assert not x[:i0].any()  # silent until the event's own sample
    assert np.abs(x[i0:i0 + SR // 1000]).max() > 1e-4  # and audible within a millisecond (click-free attack)


def test_bursts_of_lines_are_thinned():
    burst = [{"t": 1.0 + i * 0.01, "kind": "line", "intensity": 1.0} for i in range(20)]
    one = events(make(burst[:1]), 4 * SR)
    many = events(make(burst), 4 * SR)
    assert np.allclose(one, many)  # one burst of output, one tap


def test_pitches_follow_the_key():
    assert freq(make(key="A major"), 0, 4) == pytest.approx(440.0)
    assert freq(make(key="D major"), 2, 4) == pytest.approx(369.99, abs=0.01)  # F#4, the major third
    assert freq(make(key="D minor"), 2, 4) == pytest.approx(349.23, abs=0.01)  # F4, the minor third


@pytest.mark.parametrize("raw, match", [
    ({"duration": 2, "events": [{"t": 3, "kind": "line"}]}, "outside the film"),
    ({"duration": 2, "events": [{"t": 1, "kind": "explosion"}]}, "kind must be one of"),
    ({"duration": 2, "events": [{"t": 1, "kind": "line", "intensity": 2}]}, "between 0 and 1"),
    ({"duration": 2, "events": [{"t": 1, "kind": "line"}, {"t": 0.5, "kind": "line"}]}, "time order"),
    ({"duration": 2, "key": "H major"}, "tonic"),
    ({"events": []}, "duration"),
])
def test_bad_cues_are_refused(raw, match):
    with pytest.raises(cuesmod.CueError, match=match):
        cuesmod.parse(raw)


def arranged(**kw):
    raw = {"version": 1, "duration": 12.0, "key": "D major", "tempo": 72,
           "sections": [{"t": 0, "progression": [0, 5], "intensity": 0.2},
                        {"t": 6.0, "progression": [3, 4], "intensity": 0.8}]}
    raw.update(kw)
    return cuesmod.parse(raw)


def test_arranged_is_deterministic_and_the_film_length():
    from truetake_score.arrange import arrange

    c = arranged()
    x = arrange(c)
    assert len(x) == int(12.0 * SR)
    assert sample_hash(x) == sample_hash(arrange(c))


def test_arranged_piano_rests_in_quiet_sections_and_plays_in_loud_ones():
    from truetake_score.arrange import arrange

    stems = {}
    arrange(arranged(), stems=stems)
    piano = np.abs(stems["piano"]).max(axis=1)
    assert piano[: int(5.5 * SR)].max() == 0.0  # intensity 0.2: below 0.3 the piano rests
    assert piano[int(6.0 * SR): int(9.0 * SR)].max() > 1e-3  # intensity 0.8: it plays


def test_arranged_accents_only_on_accent_events():
    from truetake_score.arrange import arrange

    quiet, loud = {}, {}
    arrange(arranged(events=[{"t": 3.0, "kind": "line"}]), stems=quiet)
    arrange(arranged(events=[{"t": 3.0, "kind": "accent", "intensity": 1.0}]), stems=loud)
    assert not quiet["accents"].any()
    assert np.abs(loud["accents"][int(3.0 * SR): int(3.1 * SR)]).max() > 1e-3


@pytest.mark.parametrize("bad, match", [
    ({"tempo": 300}, "tempo"),
    ({"sections": [{"t": 0, "progression": [9]}]}, "scale degrees"),
    ({"sections": [{"t": 5, "progression": [0]}, {"t": 1, "progression": [0]}]}, "time order"),
])
def test_arranged_refuses_bad_sections(bad, match):
    with pytest.raises(cuesmod.CueError, match=match):
        arranged(**bad)
