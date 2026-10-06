"""Little chiptune chimes: written as WAV files once, then played without blocking the window."""
import math
import struct
import wave

RATE = 22050
VIBRATO_HZ = 6
CHIMES = {  # (Hz, or several Hz played together, seconds, pulse width[, vibrato depth]); 0 Hz is a rest
    # the alerts, which always sound: nothing else may sound like them
    'done': [(523, .07, .25), (659, .07, .25), (784, .07, .25), (1047, .18, .25)],        # C E G C: all done!
    'waiting': [(988, .08, .5), (0, .05, .5), (988, .08, .5), (0, .07, .5), (1319, .16, .5)],  # bip bip BEEP
    # the effects, which ⚙ can mute: two voices and a long ringing note, unlike the alerts' single quick notes
    'levelup': [((587, 494), .07, .25), (0, .02, .25), ((587, 494), .07, .25), (0, .02, .25),
                ((587, 494), .07, .25), (0, .02, .25), ((784, 587), .55, .25, .012)],  # ta-ta-ta TAAA!
}


def notes(kind, volume=.22):
    """16-bit mono samples: pulse waves (a chord mixes several) that fade out, with a tiny fade-in so they don't
    click. A note with vibrato wobbles in pitch, more as it goes on, and rings longer before it fades."""
    samples = []
    for freq, secs, duty, *vibrato in CHIMES[kind]:
        freqs, depth = (freq if isinstance(freq, tuple) else (freq,)), (vibrato or [0])[0]
        n, phases = int(RATE * secs), [0.0] * len(freqs)
        for i in range(n):
            bend = 1 + depth * math.sin(2 * math.pi * VIBRATO_HZ * i / RATE) * min(1, 3 * i / n)
            level = 0
            for v, f in enumerate(freqs):
                level += 0 if f == 0 else (1 if phases[v] < duty else -1)
                phases[v] = (phases[v] + f * bend / RATE) % 1
            envelope = min(1, i / 60) * (1 - i / n) ** (.5 if depth else 1.6)
            samples.append(int(level / len(freqs) * envelope * volume * 32767))
    return samples


def chime_file(kind, folder):
    path = folder / f'chime-{kind}-v3.wav'  # bump v3 when CHIMES change
    if not path.exists():
        samples = notes(kind)
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(struct.pack(f'<{len(samples)}h', *samples))
    return path


def play(kind, folder):
    import winsound
    try:
        winsound.PlaySound(str(chime_file(kind, folder)),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except (OSError, RuntimeError):  # no sound device, or no room to write the file: the old system beep
        winsound.MessageBeep(winsound.MB_ICONASTERISK if kind == 'done' else winsound.MB_ICONEXCLAMATION)
