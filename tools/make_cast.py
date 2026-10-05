"""Write a Game mode cast file from artists' sprite sheets (needs Pillow; the pet itself never does).

    python tools/make_cast.py <recipe.json> <cast.json>

A recipe names, per character, the sheets of each animation; this tool measures what the pet needs so it can start
fast without Pillow: how many frames each sheet has, the part of each frame anything is ever drawn in, where the body
stands (its feet and width, from the idle frames), which way it faces, and on which attack frame the blow lands.

Recipe: {"heroes": [...], "bugs": [...], "bosses": [...]}, each character:
    {"key": "knight", "name": {"en": "Knight", "vi": "Hiệp sĩ"}, "attack": "slash", "scale": 2,
     "dir": "Hero Knight 2/Hero Knight 2/Sprites",
     "anims": {"idle": {"sheet": "Idle.png", "w": 140, "h": 140}, "attack": {...}, ...}}
Paths in the recipe and in the cast are relative to the cast file's folder. An anim may set "count" to use only its
first frames (e.g. a run whose last frames turn back to idle) and "fps". A character may set "faces" ("right" or
"left") when the guess is wrong, "hit" (the attack frame a blow lands on), and "tone": [contrast, colour, brightness]
to liven up a dull palette next to the others (e.g. [1.25, 1.4, 1.12]). Besides "attack", a hero may have "attack2",
"attack3"…: each blow then picks one at random; "hits": {"attack2": 5} sets where one lands when the guess is wrong.
"height": 70 makes the body that many screen px tall (Scale2x up, smooth down), which evens out packs drawn at
different sizes; it replaces "scale".
"""
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageEnhance

FPS = {'idle': 8, 'run': 12, 'attack': 12, 'hurt': 10, 'death': 10}


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def toned(sheet, contrast, color, brightness):
    """A livelier copy: more contrast and colour, a little brighter; transparency untouched."""
    alpha = sheet.getchannel('A')
    rgb = ImageEnhance.Contrast(sheet.convert('RGB')).enhance(contrast)
    rgb = ImageEnhance.Brightness(ImageEnhance.Color(rgb).enhance(color)).enhance(brightness)
    out = rgb.convert('RGBA')
    out.putalpha(alpha)
    return out


def scale2x(img):
    """EPX / Scale2x: doubles pixel art, rounding off diagonal steps instead of making 2x2 blocks."""
    w, h = img.size
    src = img.load()
    out = Image.new('RGBA', (w * 2, h * 2))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            p = src[x, y]
            a, d = src[x, y - 1] if y else p, src[x, y + 1] if y < h - 1 else p
            c, b = src[x - 1, y] if x else p, src[x + 1, y] if x < w - 1 else p
            dst[2 * x, 2 * y] = a if c == a and c != d and a != b else p
            dst[2 * x + 1, 2 * y] = b if a == b and a != c and b != d else p
            dst[2 * x, 2 * y + 1] = c if d == c and d != b and c != a else p
            dst[2 * x + 1, 2 * y + 1] = d if b == d and b != a and d != c else p
    return out


def fit(img, factor):
    """Any size: grow with Scale2x until big enough, then shrink smoothly. Edges stay hard (each pixel fully in or
    out), because the pet's window turns one colour see-through and half-clear pixels would fringe."""
    while factor > 1:
        img, factor = scale2x(img), factor / 2
    size = (max(1, round(img.width * factor)), max(1, round(img.height * factor)))
    if size != img.size:
        img = img.resize(size, Image.LANCZOS)
    img.putalpha(img.getchannel('A').point(lambda a: 255 if a >= 110 else 0))
    return img


def measure(character, root, out_dir):
    """A character's cast entry. "tone": [contrast, colour, brightness] re-colours its sheets and "height" (the
    body's, in screen px) resizes them, so packs drawn at different sizes come out alike; either way the new
    sheets go to <cast folder>/art/<key>/ and the cast points there (the originals are left alone)."""
    folder = root / character['dir']
    anims, frames_of, raw = {}, {}, {}
    for name, spec in character['anims'].items():
        sheet = Image.open(folder / spec['sheet']).convert('RGBA')
        if character.get('tone'):
            sheet = toned(sheet, *character['tone'])
        w, h = spec['w'], spec['h']
        count = min(spec.get('count', sheet.width // w), sheet.width // w)
        raw[name] = (spec, sheet, [sheet.crop((i * w, 0, (i + 1) * w, h)) for i in range(count)])
    factor = None
    if character.get('height'):
        idle = union(f.getbbox() for f in raw['idle'][2])
        factor = character['height'] / (idle[3] - idle[1])
    for name, (spec, sheet, frames) in raw.items():
        source = folder / spec['sheet']
        w, h = spec['w'], spec['h']
        if factor:
            frames = [fit(f, factor) for f in frames]
            w, h = frames[0].size
            sheet = Image.new('RGBA', (w * len(frames), h))
            for i, f in enumerate(frames):
                sheet.paste(f, (i * w, 0))
        if factor or character.get('tone'):
            source = out_dir / 'art' / character['key'] / Path(spec['sheet']).name
            source.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(source)
        count = len(frames)
        frames_of[name] = frames
        crop = union(f.getbbox() for f in frames)
        anims[name] = {'sheet': os.path.relpath(source, out_dir).replace('\\', '/'), 'w': w, 'h': h,
                       'n': count, 'fps': spec.get('fps', FPS.get('attack' if name.startswith('attack') else name, 10)),
                       'crop': crop}
    body = union(f.getbbox() for f in frames_of['idle'])
    faces = 'right'
    if frames_of.get('attack'):
        reach = union(f.getbbox() for f in frames_of['attack'])
        faces = 'right' if reach[2] - body[2] >= body[0] - reach[0] else 'left'
    faces = character.get('faces', faces)  # a recipe may say, when the guess from the attack is wrong
    hits = {}
    for name, frames in frames_of.items():  # attack, attack2…: the frame reaching furthest is where it lands
        if name.startswith('attack'):
            boxes = [(f.getbbox() or (0, 0, 0, 0)) for f in frames]
            hits[name] = max(range(len(frames)), key=lambda i: boxes[i][2] if faces == 'right' else -boxes[i][0])
    hits.update(character.get('hits', {}))
    out = {k: v for k, v in character.items() if k not in ('dir', 'anims', 'hits')}
    out.update(anims=anims, body=body, faces=faces, hits=hits, hit=character.get('hit', hits.get('attack', 0)))
    if factor:
        out['scale'] = 1  # already the size it should be on screen
    return out


def main(recipe_path, cast_path):
    recipe = json.loads(Path(recipe_path).read_text('utf-8'))
    out_dir = Path(cast_path).resolve().parent
    root = Path(recipe_path).resolve().parent
    cast = {group: [measure(c, root, out_dir) for c in recipe.get(group, [])] for group in ('heroes', 'bugs', 'bosses')}
    Path(cast_path).write_text(json.dumps(cast, ensure_ascii=False, indent=1) + '\n', 'utf-8')
    for group, chars in cast.items():
        for c in chars:
            print(f"{group:7} {c['key']:10} faces {c['faces']:5} body {c['body']} hit {c['hit']}  "
                  + ' '.join(f"{a}:{v['n']}" for a, v in c['anims'].items()))


if __name__ == '__main__':
    main(*sys.argv[1:3])
