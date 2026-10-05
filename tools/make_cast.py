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
to liven up a dull palette next to the others (e.g. [1.25, 1.4, 1.12]).
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


def measure(character, root, out_dir):
    """A character's cast entry. With "tone": [contrast, colour, brightness], its sheets are re-coloured into
    <cast folder>/art/<key>/ and the cast points there (the originals are left alone)."""
    folder = root / character['dir']
    anims, frames_of = {}, {}
    for name, spec in character['anims'].items():
        sheet = Image.open(folder / spec['sheet']).convert('RGBA')
        source = folder / spec['sheet']
        if character.get('tone'):
            sheet = toned(sheet, *character['tone'])
            source = out_dir / 'art' / character['key'] / Path(spec['sheet']).name
            source.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(source)
        w, h = spec['w'], spec['h']
        count = min(spec.get('count', sheet.width // w), sheet.width // w)
        frames = [sheet.crop((i * w, 0, (i + 1) * w, h)) for i in range(count)]
        frames_of[name] = frames
        crop = union(f.getbbox() for f in frames)
        anims[name] = {'sheet': os.path.relpath(source, out_dir).replace('\\', '/'), 'w': w, 'h': h,
                       'n': count, 'fps': spec.get('fps', FPS.get(name, 10)), 'crop': crop}
    body = union(f.getbbox() for f in frames_of['idle'])
    attack = frames_of.get('attack')
    faces, hit = 'right', 0
    if attack:
        reach = union(f.getbbox() for f in attack)
        faces = 'right' if reach[2] - body[2] >= body[0] - reach[0] else 'left'
        widths = [(f.getbbox() or (0, 0, 0, 0)) for f in attack]
        hit = max(range(len(attack)), key=lambda i: (widths[i][2] if faces == 'right' else -widths[i][0]))
    faces = character.get('faces', faces)  # a recipe may say, when the guess from the attack is wrong
    out = {k: v for k, v in character.items() if k not in ('dir', 'anims')}
    out.update(anims=anims, body=body, faces=faces, hit=character.get('hit', hit))
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
