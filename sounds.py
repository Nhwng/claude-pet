"""Little chiptune chimes: written as WAV files once, then played without blocking the window."""
import struct
import wave

RATE = 22050
CHIMES = {  # (Hz, seconds, pulse width); 0 Hz is a rest
    # the alerts, which always sound: nothing else may sound like them
    'done': [(523, .07, .25), (659, .07, .25), (784, .07, .25), (1047, .18, .25)],        # C E G C: all done!
    'waiting': [(988, .08, .5), (0, .05, .5), (988, .08, .5), (0, .07, .5), (1319, .16, .5)],  # bip bip BEEP
    # the effects, which ⚙ can mute: thinner, higher and quicker than the alerts
    'levelup': [(1047, .03, .125), (1319, .03, .125), (1175, .03, .125), (1568, .03, .125),
                (1319, .03, .125), (1760, .03, .125), (1568, .03, .125), (2093, .14, .125)],  # a sparkle
}


def notes(kind, volume=.22):
    """16-bit mono samples: pulse waves that fade out, with a tiny fade-in so they don't click."""
    samples = []
    for freq, secs, duty in CHIMES[kind]:
        n = int(RATE * secs)
        for i in range(n):
            level = 0 if freq == 0 else (1 if (i * freq / RATE) % 1 < duty else -1)
            envelope = min(1, i / 60) * (1 - i / n) ** 1.6
            samples.append(int(level * envelope * volume * 32767))
    return samples


def chime_file(kind, folder):
    path = folder / f'chime-{kind}-v2.wav'  # bump v2 when CHIMES change
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
