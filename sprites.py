"""How the pets look: pixel art as rows of palette letters, the cat breeds, and the pet packs.

The cats are drawn here in code; every packs/*.json adds a pack of one-pose sprites (format in the README).
"""
import functools
import json
import math
from pathlib import Path

PACKS_DIR = Path(__file__).resolve().parent / 'packs'


# ---------- pixel art: faces right; '.' = transparent, letters index the breed palette ----------
# o outline  b fur  l/d light/dark fur  s stripes  k/q patches  w belly  m muzzle  p paws  t tail tip
# x/y inner ear  e/f left/right iris  a iris-or-pupil (slit vs round eyes)  u pupil  h eye shine
# n nose  c blush  i mouth  j shut eyelids  v whiskers  g sticker outline (added around it all)

HEAD = [  # 19 wide, centre column 9; whiskers are added by whiskered()
    '..oo...........oo..',
    '..olo.........obo..',
    '..olxo.......oxbo..',
    '..olxxo.....oxxbo..',
    '.ollxyxoooooxyxbdo.',
    '.olllllllllbqqqbdo.',
    'ollllsllsllsbqqbbdo',
    'olbbhuabbbbbhuabbdo',
    'obbbauabbbbbauabbdo',
    'obbbeuebbbbbfufbbdo',
    'obcbbbbmmnmmbbbbcdo',
    'obbbbbmmimimmbbbbdo',
    '.obbbbbmmmmmbbbbdo.',
    '..odbbbbbbbbbbbdo..',
    '....ooooooooooo....',
]
HEAD_SHUT = HEAD[:7] + ['olbbbbbbbbbbbbbbbdo', 'obbbjbjbbbbbjbjbbdo', 'obbbbjbbbbbbbjbbbdo'] + HEAD[10:]
TAIL = ['...ooo.', '..ottto', '.ottto.', '.olbo..', 'olbbo..', 'olbbo..', 'olbbo..', '.olbbo.', '.olbbbo',
        '..olbbo', '...obbo']
SIT_TAIL = ['...oo.', '..otto', '..otto', '.obbo.', '.obbo.', 'obbo..', 'obbo..', 'obbbo.', '.oooo.']
SLEEP_TAIL = ['.oooooooooooo', 'otttbbbbbbbbbo', '.oooooooooooo']
LEG = ['obbo', 'obbo', 'obbo', 'oppo', '.oo.']
LEG_FWD = ['obbo', 'obbo', '.obbo', '.oppo', '..oo.']
LEG_BACK = ['.obbo', '.obbo', 'obbo', 'oppo', '.oo.']
SIT_PAWS = ['opppoopppo', 'opppoopppo', '.oooooooo.']
ART_W, ART_H = 39, 26
FRAMES = ('walk1', 'walk2', 'sit', 'sit2', 'sleep1', 'sleep2')

# small overlays, drawn with fixed colours
ZZZ_BIG = ['zzzzz', '...z.', '..z..', '.z...', 'zzzzz']
ZZZ_SMALL = ['zzzz', '..z.', '.z..', 'zzzz']
MINI_CAT = ['b...b', 'bbbbb', 'bebeb', 'bbbbb']
SPARKLE = ['..y..', '..y..', 'yywyy', '..y..', '..y..']
TWINKLE = ['.y.', 'ywy', '.y.']
ICONS = {
    'done': ['.ccccc.', 'cccccwc', 'ccccwwc', 'cwcwwcc', 'cwwwccc', 'ccwcccc', '.ccccc.'],
    'waiting': ['.ccccc.', 'cccwccc', 'cccwccc', 'cccwccc', 'ccccccc', 'cccwccc', '.ccccc.'],
}


def blob(w, h, cx, cy, rx, ry, belly=None, stripes=False, patches=()):
    """A shaded oval body as palette rows: lit from the top-left, ringed with o."""
    def inside(x, y):
        return ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1

    def shade(x, y):
        nx, ny = (x + .5 - cx) / rx, (y + .5 - cy) / ry
        lit = -.45 * nx - .9 * ny
        ch = 'l' if lit > .5 else 'd' if lit < -.45 else 'b'
        if belly and belly(nx, ny):
            ch = 'w'
        elif stripes and ny < .1 and lit > -.3 and (x - int(cx)) % 4 == 0:
            ch = 's'
        return next((letter for letter, px, py, r in patches if (nx - px) ** 2 + (ny - py) ** 2 < r * r), ch)

    ring = ((0, 1), (1, 0), (0, -1), (-1, 0))
    return [''.join(shade(x, y) if inside(x, y) else 'o' if any(inside(x + dx, y + dy) for dx, dy in ring) else '.'
                    for x in range(w)) for y in range(h)]


WALK_BODY = blob(21, 11, 10.5, 5.5, 10, 4.8, belly=lambda nx, ny: ny > .5 and nx > 0 or nx > .8 and ny > -.1,
                 stripes=True, patches=(('k', -.55, -.05, .32), ('q', .3, -.45, .25)))
SIT_BODY = blob(19, 11, 9.5, 6, 8.6, 5.6, belly=lambda nx, ny: abs(nx) < .42 + .25 * ny and ny > -.85,
                patches=(('k', -.7, .2, .3), ('q', .7, .3, .25)))
SLEEP_BODY = blob(26, 10, 13, 5.5, 12.4, 4.6, stripes=True, patches=(('k', -.6, 0, .3), ('q', .25, -.4, .25)))


def whiskered(head):
    rows = [list('...' + r + '...') for r in head]
    for y, x in ((9, 0), (9, 1), (10, 2), (11, 0), (11, 1), (11, 2)):
        rows[y][x] = rows[y][24 - x] = 'v'
    return [''.join(r) for r in rows]


def far(art):
    """The leg on the far side sits in shadow."""
    return [r.replace('b', 'd').replace('p', 'd') for r in art]


def compose(layers, width=ART_W, height=ART_H):
    grid = [['.'] * width for _ in range(height)]
    for art, top, left in layers:
        for r, row in enumerate(art):
            for c, ch in enumerate(row):
                if ch != '.' and 0 <= top + r < height and 0 <= left + c < width:
                    grid[top + r][left + c] = ch
    return [''.join(row) for row in grid]


def with_outline(rows, ring='g'):
    """Pad by 1px and ring every opaque pixel (whiskers stay thin), so it reads on dark and light."""
    padded = ['.' * (len(rows[0]) + 2)] + [f'.{r}.' for r in rows] + ['.' * (len(rows[0]) + 2)]

    def touches(y, x):
        return any(0 <= y + dy < len(padded) and 0 <= x + dx < len(padded[0]) and padded[y + dy][x + dx] not in '.v'
                   for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)))
    return [''.join(ring if ch == '.' and touches(y, x) else ch for x, ch in enumerate(row))
            for y, row in enumerate(padded)]


def sprite(frame):
    if frame.startswith('walk'):
        bob = int(frame == 'walk2')
        if bob:
            legs_far, legs_near = [(far(LEG), 20, 8), (far(LEG), 20, 20)], [(LEG, 20, 11), (LEG, 20, 23)]
        else:
            legs_far = [(far(LEG_BACK), 20, 7), (far(LEG_FWD), 20, 19)]
            legs_near = [(LEG_FWD, 20, 10), (LEG_BACK, 20, 22)]
        layers = [(TAIL, 3 + bob, 1), *legs_far, (WALK_BODY, 11 + bob, 5), *legs_near, (whiskered(HEAD), bob, 14)]
    elif frame.startswith('sit'):
        up = int(frame == 'sit2')
        layers = [(SIT_TAIL, 17, 27), (SIT_BODY, 15 - up, 11), (SIT_PAWS, 23 - up, 15), (whiskered(HEAD), 3 - up, 8)]
    else:
        nod = int(frame == 'sleep2')
        layers = [(SLEEP_BODY, 16, 1), (SLEEP_TAIL, 23, 0), (whiskered(HEAD_SHUT), 11 + nod, 14)]
    return with_outline(compose(layers))


def tr(value, lang):
    """A name in the chosen language: packs may give {'en': ..., 'vi': ...} or one plain string."""
    return (value.get(lang) or value.get('en') or next(iter(value.values()), '')) if isinstance(value, dict) else value


def mix(color, other, amount):
    a, b = ([int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in (color, other))
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def breed(name, b, **over):
    """Palette for one breed. Shading is hue-shifted: warm highlights, cool purple shadows."""
    colors = dict(b=b, l=mix(b, '#fff8dc', .38), d=mix(b, '#2a1840', .24), o=mix(b, '#1a0f24', .78),
                  w='#fff4e2', x='#ffb3c1', y='#f07f9a', e='#e0a030', u='#2b2233', h='#ffffff',
                  n='#ff7f98', c='#ff9fb0', v='#a59cab', g='#ffffff')
    colors.update(over)
    for key, fallback in (('s', 'b'), ('k', 'b'), ('q', 'b'), ('m', 'w'), ('p', 'w'), ('t', 's'), ('f', 'e'),
                          ('a', 'u'), ('i', 'o'), ('j', 'o')):
        colors.setdefault(key, colors[fallback])
    return name, colors


BREEDS = [
    breed('Mèo cam', '#f6a54a', s='#de7a2c', e='#7cc46a'),
    breed('Mèo mun', '#2b2935', l='#4f4c66', d='#1c1a24', o='#0b0a10', w='#2b2935', p='#2b2935', e='#ffd23f',
          a='#ffd23f', u='#0b0a10', x='#9a6a84', y='#6e4660', n='#c98aa3', c='#4b3448', i='#7d7898', j='#7d7898',
          v='#8f8aa5'),
    breed('Mèo Xiêm', '#f2e2c4', w='#fbf3e3', m='#a8836b', p='#5e4334', t='#5e4334', x='#7a5646', y='#5e4334',
          e='#4aa8ff', n='#3a2a22', i='#5e4334', c='#e9a99a'),
    breed('Tam thể', '#fdf9f2', k='#f2a54a', q='#3d3c4c', w='#fdf9f2', t='#f2a54a', e='#e0a030'),
    breed('Mướp xám', '#aeb0bb', s='#6f717e', w='#f2f2f6', e='#7cc46a'),
    breed('Anh lông ngắn', '#8a99b4', w='#8a99b4', p='#8a99b4', e='#f2a33a', x='#d2a8bb', y='#b58aa0',
          n='#76839c', c='#a58fa8'),
    breed('Bò sữa', '#2e2d38', l='#4d4b60', d='#1f1e27', o='#0e0d13', w='#ffffff', p='#ffffff', e='#7ed957', a='#7ed957',
          x='#9a6a84', y='#6e4660', j='#8a85a0'),
    breed('Mèo trắng', '#ffffff', w='#ffffff', p='#ffffff', e='#4aa8ff', f='#ffd23f', o='#8a7f92'),
]
CAT_NAMES_EN = {'Mèo cam': 'Orange tabby', 'Mèo mun': 'Black cat', 'Mèo Xiêm': 'Siamese', 'Tam thể': 'Calico',
                'Mướp xám': 'Grey tabby', 'Anh lông ngắn': 'British Shorthair', 'Bò sữa': 'Tuxedo',
                'Mèo trắng': 'White cat'}


# ---------- moves: what a pack's pets fire while Claude works (sprite px, seconds) ----------

MOVE_FIRE, MOVE_END = (.3, 1.0), 1.3   # seconds into a move: the firing window, and fully recovered
MOVES = {  # speeds in effect px per second; 'every' = seconds between shots
    'water': {'every': .035, 'vx': (85, 105), 'vy': (-45, -30), 'ay': 170, 'life': 2.0, 'splash': True},
    'fire': {'every': .1, 'vx': (50, 70), 'vy': (-16, -4), 'ay': -22, 'life': .9},
    'leaf': {'every': .1, 'vx': (90, 115), 'vy': (-35, -12), 'ay': 30, 'life': 1.0},
}


def leaf_frames(turns=8, half=4.3, width=1.8):
    """A pointed leaf with a stem, drawn at `turns` angles so it spins: light on one side, dark on the other."""
    frames = []
    for i in range(turns):
        a = 2 * math.pi * i / turns
        cells = {}
        for y in range(-7, 8):
            for x in range(-7, 8):
                u, v = x * math.cos(a) + y * math.sin(a), y * math.cos(a) - x * math.sin(a)  # along, across
                if abs(u) <= half and abs(v) <= width * (1 - (u / half) ** 2) + .1:
                    cells[x, y] = 'e' if v < -.35 and u > half * .2 else 's' if v < .35 else 'S'
                elif -half - 1.7 <= u < -half + .3 and abs(v) < .55:
                    cells[x, y] = 'k'
        xs, ys = [x for x, _ in cells], [y for _, y in cells]
        frames.append(with_outline([''.join(cells.get((x, y), '.') for x in range(min(xs), max(xs) + 1))
                                    for y in range(min(ys), max(ys) + 1)], ring='k'))
    return frames

def yarn_frames(turns=4, radius=3.4):
    """A ball of yarn whose strands turn as it rolls."""
    frames = []
    for i in range(turns):
        a = math.pi * i / turns
        rows = [''.join('.' if x * x + y * y > radius * radius else 'h' if (x, y) in ((-1, -2), (-2, -1)) else
                        'q' if (x * math.cos(a) + y * math.sin(a) + 9) % 2.5 < .9 else 'p' for x in range(-3, 4))
                for y in range(-3, 4)]
        frames.append(with_outline(rows, ring='o'))
    return frames


YARN = yarn_frames()
YARN_COLORS = {'o': '#7a2c45', 'p': '#ff8fb1', 'q': '#d9466f', 'h': '#ffe1ea'}
PARTICLES = {  # big frames first (they flicker), the small one last (dying ember / splash bit)
    'water': (['..l..', '.lbb.', 'lbbbd', 'bbbbd', '.bdd.'], ['.l.', 'lbd', '.d.'], ['lb', 'bd']),
    'fire': (['..y..', '.yoy.', 'yoooy', 'orrro', 'orRro', '.rRr.'],
             ['.y...', '.yoy.', 'yooy.', 'oorro', 'orRro', '.rRr.'], ['.o.', 'oro', '.R.']),
    'leaf': (*leaf_frames(), ['sS', 'Sk']),
}
PARTICLE_COLORS = {'l': '#e9f9ff', 'b': '#3ab0ff', 'd': '#1a6fd8', 'y': '#fff7a0', 'o': '#ffb12e',
                   'r': '#f2541c', 'R': '#a92a0e', 'e': '#e4ffb0', 's': '#7ed957', 'S': '#3e9b3e', 'k': '#24561a'}


# ---------- pet packs: the cats above, plus every packs/*.json ----------

def pose_frames(rows, shut):
    """The six frames for a one-pose sprite: it hops while walking and breathes while asleep."""
    height = len(rows) + 3

    def at(art, top):
        return with_outline(compose([(art, top, 0)], len(rows[0]), height))
    chest = len(rows) * 3 // 5
    breathing = shut[:chest] + shut[chest + 1:]           # one row shorter: the chest sinks
    squash, stretch = rows[:chest] + rows[chest + 1:], rows[:chest + 1] + rows[chest:]
    return {'walk1': at(rows, 3), 'walk2': at(rows, 1), 'sit': at(rows, 3), 'sit2': at(rows, 2),
            'sleep1': at(shut, 3), 'sleep2': at(breathing, 4), 'squash': at(squash, 4), 'stretch': at(stretch, 2)}


def thumbnail(rows, step=3):
    """A tiny copy of a sprite for the name plate: the commonest colour of each step x step block."""
    from collections import Counter
    out = []
    for y in range(0, len(rows), step):
        line = ''
        for x in range(0, len(rows[0]), step):
            block = [rows[yy][xx] for yy in range(y, min(y + step, len(rows)))
                     for xx in range(x, min(x + step, len(rows[0])))]
            opaque = [ch for ch in block if ch != '.']
            line += Counter(opaque).most_common(1)[0][0] if len(opaque) * 2 > len(block) else '.'
        out.append(line)
    return out


def move_at(move):
    """A pack's move with its mouth moved into frame coordinates (outline pad + 3 rows of headroom)."""
    if not move or move.get('kind') not in MOVES:
        return None
    x, y = move['mouth']
    return {**move, 'mouth': (x + 1, y + 4)}


@functools.lru_cache(maxsize=None)
def packs():
    """{key: {name, scale, pets: [{name, call, colors, frames, icon}]}}; built on first use, never in hooks."""
    cat_frames = {f: sprite(f) for f in FRAMES}
    found = {'cats': {'name': {'en': 'Cats', 'vi': 'Mèo'}, 'scale': 2, 'working': 'walk', 'pets': [
        {'name': name, 'label': {'en': CAT_NAMES_EN[name], 'vi': name}, 'call': {'en': 'the cat', 'vi': 'mèo'},
         'colors': colors, 'frames': cat_frames, 'icon': with_outline(MINI_CAT, ring='o')}
        for name, colors in BREEDS]}}
    for path in sorted(PACKS_DIR.glob('*.json')):
        try:
            data = json.loads(path.read_text('utf-8'))
            pets = [{'name': pet['name'], 'label': pet.get('label', pet['name']), 'call': pet.get('label', pet['name']),
                     'colors': {**pet['colors'], 'g': '#ffffff'},
                     'frames': pose_frames(pet['rows'], pet['shut']), 'icon': thumbnail(pet['rows']),
                     'move': move_at(pet.get('move'))} for pet in data['pets']]
            working = 'attack' if all(pet['move'] for pet in pets) else 'walk'
            scale = min(max(int(data.get('scale', 1)), 1), 4)
            found[path.stem] = {'name': data['name'], 'scale': scale, 'working': working, 'pets': pets}
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue  # a broken pack file must not take the cats down with it
    return found
