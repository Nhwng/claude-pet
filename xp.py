"""Game mode experience: the output tokens Claude wrote, per project, read from Claude Code's transcripts.

Each scan reads only the whole lines written since the last one (an offset per file).
"""
import json
import math
from pathlib import Path

PROJECTS = Path.home() / '.claude' / 'projects'
TOKENS_PER_STEP = 20_000   # need(L) = TOKENS_PER_STEP * (L - 1) ** 2
MAX_LEVEL = 99
RECENT = 2000              # reply ids remembered: one reply is logged on many lines, up to ~800 replies apart
# ponytail: a resumed session that replays replies older than the last 2000 ids counts them again; keep every id
# per project if levels ever look inflated
TIERS = (50, 25, 10)       # from these levels: gold, silver, bronze


def need(level):
    """Tokens in total to reach a level."""
    return TOKENS_PER_STEP * (level - 1) ** 2


def level_of(tokens):
    return min(MAX_LEVEL, 1 + math.isqrt(max(0, int(tokens)) // TOKENS_PER_STEP))


def progress(tokens):
    """How far from this level to the next, 0..1 (a full bar at the top level)."""
    level = level_of(tokens)
    if level >= MAX_LEVEL:
        return 1.0
    return (tokens - need(level)) / (need(level + 1) - need(level))


def tier_of(level):
    """0 none, 1 bronze, 2 silver, 3 gold."""
    return next((3 - i for i, start in enumerate(TIERS) if level >= start), 0)


def count(lines, recent):
    """Output tokens in whole JSONL lines (bytes). recent = {reply id: tokens counted}, oldest first: a reply
    logged again (often with a bigger count) adds only what it adds. Returns (gained, recent)."""
    recent, gained = dict(recent), 0
    for line in lines:
        if b'"output_tokens"' not in line:
            continue
        try:
            message = json.loads(line).get('message')
        except (ValueError, AttributeError, RecursionError):  # not JSON, not an object, nested too deep
            continue
        usage = message.get('usage') if isinstance(message, dict) else None
        out = usage.get('output_tokens') if isinstance(usage, dict) else None
        if not isinstance(out, int) or out < 0:
            continue
        reply = message.get('id')
        if not isinstance(reply, str) or not reply:
            gained += out
            continue
        before = recent.pop(reply, 0)  # pop, then set again: the id moves to the newest end
        gained += max(0, out - before)
        recent[reply] = max(out, before)
    while len(recent) > RECENT:
        del recent[next(iter(recent))]
    return gained, recent


def whole_lines(f, read):
    """A file's complete lines from where it is, one at a time (one transcript can be gigabytes), adding up
    their bytes in read[0]; a half-written last line waits for the next scan."""
    for line in f:
        if not line.endswith(b'\n'):
            return
        read[0] += len(line)
        yield line


def scan(store, root=None):
    """The store after reading what Claude wrote since `store`. With no store yet, what is already there is
    history (everyone starts at Lv 1); files that appear later are read from their start. A store of
    {'files': {}} has no history: every transcript is read from its start."""
    root = root or PROJECTS
    store = store if isinstance(store, dict) else {}
    first = not isinstance(store.get('files'), dict)
    old = {} if first else store['files']
    tokens = store.get('tokens') if isinstance(store.get('tokens'), dict) else {}
    tokens = {k: v for k, v in tokens.items() if isinstance(v, int)}
    recent = {r[0]: r[1] for r in store.get('recent') or []
              if isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) and isinstance(r[1], int)}
    files = {}
    for path in sorted(root.glob('*/**/*.jsonl')):
        name = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            if name in old:
                files[name] = old[name]
            continue
        offset = size if first else old.get(name, 0)
        offset = min(offset, size) if isinstance(offset, int) else size  # cut short: carry on from its new end
        if size > offset:
            read = [offset]
            try:
                with path.open('rb') as f:
                    f.seek(offset)
                    gained, recent = count(whole_lines(f, read), recent)
                offset = read[0]
            except OSError:
                gained = 0  # can't read it now: the next scan tries again from the same place
            if gained:
                project = name.split('/', 1)[0].lower()
                tokens[project] = tokens.get(project, 0) + gained
        files[name] = offset
    return {'tokens': tokens, 'files': files, 'recent': [[k, v] for k, v in recent.items()]}
