"""Game mode's cast: heroes, bugs and bosses drawn by artists, as sprite sheets described by a cast file
(made by tools/make_cast.py). Frames are cut, mirrored and zoomed with tkinter's own PhotoImage copy, once each,
on first use, so no imaging library is needed.

A frame comes with where the body is in it: the window places the body's left edge at a pet's x and its feet on the
ground, whatever room the artist left around it for swings and spells.
"""
import json
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
        return box(character['body']) and all(
            (base / anims[a]['sheet']).is_file() and box(anims[a]['crop']) and anims[a]['fps'] > 0
            and anims[a]['n'] > 0 and anims[a]['w'] > 0 and anims[a]['h'] > 0 for a in ANIMS)
    except (KeyError, TypeError):
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

    def tallest(self, group):
        """How far above the feet anything of this group is ever drawn, in screen px."""
        return max((round((c['body'][3] - a['crop'][1]) * self.scale(group, i))
                    for i, c in enumerate(self.cast[group]) for a in c['anims'].values()), default=0)

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
