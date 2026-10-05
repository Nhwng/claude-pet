"""Turn pixel-art grid images (one square cell per pixel, like cross-stitch charts) into a Claude Pet pack.

    python tools/grid_to_pack.py packs/mine.json "My pack" blob.png:Blob frog.png:Frog:flip --cell 10

Pets should face right; add :flip to one that faces left. A sleeping pet keeps its eyes open until you
edit its "shut" rows, and a pet only uses a move (instead of walking) once you give it a "move".
Needs Pillow (pip install pillow). Only make packs from art you are allowed to use.
"""
import argparse
import json
from collections import Counter

from PIL import Image

LETTERS = 'ABCDEFHIJKLMNOPQRSTUWXYZ'  # no G or V: the pet's outline ring and whiskers use g and v


def read_cells(path, cell):
    """The commonest colour in the middle of each cell; near-white cells are empty."""
    im = Image.open(path).convert('RGB')
    px, middle_of_cell = im.load(), range(cell * 3 // 10, cell * 8 // 10)  # clear of the grid lines
    grid = []
    for top in range(0, im.height - cell + 1, cell):
        row = []
        for left in range(0, im.width - cell + 1, cell):
            middle = [px[left + x, top + y] for x in middle_of_cell for y in middle_of_cell]
            colour = Counter(middle).most_common(1)[0][0]
            row.append(None if min(colour) > 232 else colour)
        grid.append(row)
    used_rows = [i for i, r in enumerate(grid) if any(r)]
    used_cols = [j for j in range(len(grid[0])) if any(r[j] for r in grid)]
    return [r[used_cols[0]:used_cols[-1] + 1] for r in grid[used_rows[0]:used_rows[-1] + 1]]


def to_letters(grid, threshold=34):
    """Merge noisy colours into the sprite's real palette: (rows of letters, {letter: '#rrggbb'})."""
    centres, owner = [], {}
    for colour, n in Counter(c for r in grid for c in r if c).most_common():
        best = min(centres, key=lambda k: sum((a - b / k[3]) ** 2 for a, b in zip(colour, k)), default=None)
        if best and sum((a - b / best[3]) ** 2 for a, b in zip(colour, best)) ** .5 < threshold:
            best[:] = [best[0] + colour[0] * n, best[1] + colour[1] * n, best[2] + colour[2] * n, best[3] + n]
        else:
            best = [colour[0] * n, colour[1] * n, colour[2] * n, n]
            centres.append(best)
        owner[colour] = best
    if len(centres) > len(LETTERS):
        raise SystemExit(f'{len(centres)} colours is too many; raise --threshold')
    centres.sort(key=lambda k: sum(k[:3]) / k[3])  # dark to light
    letter = {id(k): LETTERS[i] for i, k in enumerate(centres)}
    palette = {LETTERS[i]: '#%02x%02x%02x' % tuple(round(v / k[3]) for v in k[:3]) for i, k in enumerate(centres)}
    rows = [''.join(letter[id(owner[c])] if c else '.' for c in r) for r in grid]
    return fill_holes(rows), {**palette, 'W': '#ffffff'}


def fill_holes(rows):
    """Empty cells walled in by the sprite are white highlights (eye shine), not background."""
    h, w = len(rows), len(rows[0])
    outside, todo = set(), [(y, x) for y in range(h) for x in (0, w - 1)] + [(y, x) for x in range(w) for y in (0, h - 1)]
    while todo:
        y, x = todo.pop()
        if 0 <= y < h and 0 <= x < w and (y, x) not in outside and rows[y][x] == '.':
            outside.add((y, x))
            todo += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
    return [''.join('W' if ch == '.' and (y, x) not in outside else ch for x, ch in enumerate(r)) for y, r in enumerate(rows)]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    parser.add_argument('name')
    parser.add_argument('images', nargs='+', help='image.png:PetName[:flip]')
    parser.add_argument('--cell', type=int, default=10, help='pixels per grid cell')
    parser.add_argument('--threshold', type=float, default=34, help='how different two colours must be to stay apart')
    args = parser.parse_args()
    pets = []
    for spec in args.images:
        flip = spec.endswith(':flip')
        path, name = (spec[:-len(':flip')] if flip else spec).rsplit(':', 1)  # from the right: C:\ stays whole
        rows, colors = to_letters(read_cells(path, args.cell), args.threshold)
        if flip:
            rows = [r[::-1] for r in rows]
        pets.append({'name': name, 'about': '', 'colors': colors, 'rows': rows, 'shut': rows})
        print(f'{name}: {len(rows[0])}x{len(rows)} px, {len(colors)} colours')
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'name': args.name, 'scale': 1, 'pets': pets}, f, ensure_ascii=False, indent=1)
    print(f'wrote {args.out}; restart the pet, then: python pet.py pack <file name without .json>')


if __name__ == '__main__':
    main()
