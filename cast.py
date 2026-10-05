"""Game mode's cast: heroes, bugs and bosses drawn by artists, as sprite sheets described by a cast file
(made by tools/make_cast.py). Frames are cut, mirrored and zoomed with tkinter's own PhotoImage copy, once each,
on first use, so no imaging library is needed.

A frame comes with where the body is in it: the window places the body's left edge at a pet's x and its feet on the
ground, whatever room the artist left around it for swings and spells.
"""
import json
import random
from pathlib import Path

GROUPS = ('heroes', 'bugs', 'bosses')
ANIMS = ('idle', 'run', 'attack', 'hurt', 'death')
FILES = (Path(__file__).resolve().parent / 'packs' / 'cast.json',   # your own, from packs you downloaded
         Path(__file__).resolve().parent / 'art' / 'cast.json')     # the one that ships (CC0 art)


def box(value):
    return isinstance(value, list) and len(value) == 4 and all(isinstance(v, (int, float)) for v in value)


def usable(character, base):
    """Every animation is there, with a sheet on disk, a frame size and count, a speed and the box things are
    drawn in; and the body's box."""
    try:
        anims = character['anims']
        return box(character['body']) and all(a in anims for a in ANIMS) and all(
            (base / anim['sheet']).is_file() and box(anim['crop']) and anim['fps'] > 0
            and anim['n'] > 0 and anim['w'] > 0 and anim['h'] > 0 for anim in anims.values())
    except (KeyError, TypeError, AttributeError):
        return False


def load(files=FILES):
    """(cast, folder) from the first cast file with at least one usable hero; ({}, None) when there is none."""
    for path in files:
        try:
            data = json.loads(Path(path).read_text('utf-8'))
        except (OSError, ValueError):
            continue
        base = Path(path).parent
        if not isinstance(data, dict):
            continue
        cast = {g: [c for c in data.get(g) if usable(c, base)] if isinstance(data.get(g), list) else [] for g in GROUPS}
        if cast['heroes']:
            return cast, base
    return {}, None


def pick_boss(bosses, tier):
    """Which boss turns up for a hero of this tier: one its tier has unlocked (a boss's "tier" in the cast, 0 when
    missing), the higher ones more often. When none is unlocked yet, the lowest still come."""
    tiers = [max(0, b['tier']) if isinstance(b.get('tier'), int) else 0 for b in bosses]
    pool = [i for i, t in enumerate(tiers) if t <= tier] or [i for i, t in enumerate(tiers) if t == min(tiers)]
    return random.choices(pool, weights=[1 + tiers[i] for i in pool])[0]


class Sprites:
    """Frames of a loaded cast as PhotoImages: frame(group, index, anim, i, flip) -> dict, see below."""

    def __init__(self, tk, cast, base, dpi):
        self.tk, self.cast, self.base, self.dpi = tk, cast, Path(base), dpi
        self.sheets, self.frames = {}, {}

    def scale(self, group, index):
        """Zoom in whole or half steps (1.5 draws a bug a little bigger than its sheet without doubling it)."""
        return max(1.0, round(float(self.cast[group][index].get('scale', 1)) * 2) / 2) * self.dpi

    def body(self, group, index):
        """(width, height) of the body standing still, in screen px."""
        x0, y0, x1, y1 = self.cast[group][index]['body']
        s = self.scale(group, index)
        return round((x1 - x0) * s), round((y1 - y0) * s)

    def tallest(self, group, anims=None):
        """How far above the feet anything of this group is ever drawn (in these animations), in screen px."""
        return max((round((c['body'][3] - a['crop'][1]) * self.scale(group, i))
                    for i, c in enumerate(self.cast[group]) for name, a in c['anims'].items()
                    if anims is None or name in anims), default=0)

    def attacks(self, group, index):
        """'attack', 'attack2'…: the blows this character can pick from."""
        return sorted(a for a in self.cast[group][index]['anims'] if a.startswith('attack'))

    def hits(self, group, index, anim):
        """The frames of an attack where blows land (or shots leave): a combo has several."""
        c = self.cast[group][index]
        found = (c.get('hits') or {}).get(anim)
        found = [found] if isinstance(found, int) else found
        if not isinstance(found, list) or not all(isinstance(i, int) for i in found) or not found:
            found = [c['anims'][anim]['n'] // 2]
        return found

    def frames_in(self, group, index, anim):
        a = self.cast[group][index]['anims'][anim]
        return a['n'], a['fps']

    def check(self):
        """Load every sheet now, so an unreadable one fails here (and Game mode steps aside), not while drawing."""
        for group in GROUPS:
            for c in self.cast[group]:
                for a in c['anims'].values():
                    self.sheet(a['sheet'])

    def sheet(self, rel):
        if rel not in self.sheets:
            self.sheets[rel] = self.tk.PhotoImage(file=str(self.base / rel))
        return self.sheets[rel]

    def frame(self, group, index, anim, i, facing):
        """Frame i (wrapping) of an animation, facing +1 right or -1 left. Returns {'img', 'dx', 'dy', 'w', 'h'}:
        draw img with its top-left at (body left + dx, ground + dy); w, h are the body's size."""
        c = self.cast[group][index]
        a = c['anims'][anim]
        i %= a['n']
        flip = (facing > 0) != (c.get('faces', 'right') == 'right')
        key = (group, index, anim, i, flip)
        if key not in self.frames:
            s = self.scale(group, index)
            x0, y0, x1, y1 = a['crop']
            bx0, by0, bx1, by1 = c['body']
            cut = self.tk.PhotoImage()
            cut.tk.call(cut, 'copy', self.sheet(a['sheet']), '-from', i * a['w'] + x0, y0, i * a['w'] + x1, y1)
            if flip:  # a negative subsample mirrors it
                mirrored = self.tk.PhotoImage()
                mirrored.tk.call(mirrored, 'copy', cut, '-subsample', -1, 1)
                cut = mirrored
            img = self.tk.PhotoImage()
            if s == int(s):
                img.tk.call(img, 'copy', cut, '-zoom', int(s), int(s))
            else:  # half steps: zoom twice as much, then keep every other pixel
                twice = self.tk.PhotoImage()
                twice.tk.call(twice, 'copy', cut, '-zoom', int(s * 2), int(s * 2))
                img.tk.call(img, 'copy', twice, '-subsample', 2, 2)
            left = (x1 - bx1) if flip else (bx0 - x0)  # the body's left edge, inside the cut
            self.frames[key] = {'img': img, 'dx': round(-left * s), 'dy': round(-(by1 - y0) * s),
                                'w': round((bx1 - bx0) * s), 'h': round((by1 - by0) * s)}
        return self.frames[key]
