#!/usr/bin/env python3
"""Claude Pet: pixel cats on your taskbar that tell you when Claude Code is done or needs you.

    python pet.py            run the cats (pythonw pet.py = no console window)
    python pet.py install    add the hooks to ~/.claude/settings.json (backup written next to it)
    python pet.py uninstall  remove them
    python pet.py pack [key] list the pet packs, or switch the running pet to one (e.g. hoenn)
    python pet.py hook       what Claude Code runs on each event (JSON on stdin)
    python pet.py test       self-check

Every Claude session gets its own pet: a cat breed, or one from packs/*.json (right-click to switch).
It trots while Claude works, sits up and hops with a bubble when Claude is done or needs a decision,
and naps otherwise. The cats hide while VS Code is in
front; click a cat to jump to its VS Code window, right-click to quit.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / '.claude-pet'
SETTINGS = Path.home() / '.claude' / 'settings.json'
CONFIG = 'config.json'    # lives in STATE_DIR next to the session files
ASK_TOOLS = {'AskUserQuestion': 'trả lời câu hỏi', 'ExitPlanMode': 'duyệt plan'}
HOOK_EVENTS = {'UserPromptSubmit': '*', 'PostToolUse': '*', 'PermissionRequest': '*', 'Notification': '*',
               'PreToolUse': '|'.join(ASK_TOOLS), 'Stop': '*', 'SessionEnd': '*'}
HOOK_MARK = 'pet.py" hook'
ALARMS = ('done', 'waiting')
STALE_SECS = 15 * 60      # 'working' with no event this long: probably interrupted (Esc fires no Stop)
FORGET_SECS = 6 * 3600    # VS Code can close without SessionEnd
LOG_MAX = 512 * 1024


# ---------- hook side: Claude Code event -> ~/.claude-pet/<session>.json ----------

def next_state(cur, event, payload):
    """Cat state after a hook event; None means forget the session."""
    if event == 'SessionEnd':
        return None
    if event == 'PostToolUse' and payload.get('agent_id') and cur in ALARMS:
        return cur  # a subagent's tool finishing doesn't answer the main session's question
    if event in ('UserPromptSubmit', 'PostToolUse'):
        return 'working'
    if event == 'Stop':
        # Turn ended but background agents still run: Claude resumes when they finish. Items look like
        # {"type": "shell" | "monitor" | ..., "description": ...}; only an agent type counts, not a shell
        # command that happens to mention agents.
        busy = any('agent' in str(t.get('type', '')).lower() for t in payload.get('background_tasks') or [])
        return 'working' if busy else 'done'
    if event == 'PermissionRequest' or event == 'PreToolUse' and payload.get('tool_name') in ASK_TOOLS:
        return 'waiting'
    if event == 'Notification' and payload.get('notification_type') in ('permission_prompt', 'elicitation_dialog'):
        return 'waiting'
    return cur


def plain(value):
    """Text out of a str, or out of message-like dicts and lists of content blocks."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(plain(v) for v in value)
    if isinstance(value, dict):
        return plain(value.get('text') or value.get('content') or '')
    return ''


def ask_text(payload, limit=56):
    """One short line for the bubble: what Claude asks you about, or how its last answer starts."""
    try:
        args = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
        if payload.get('hook_event_name') == 'Stop':
            text = plain(payload.get('last_assistant_message'))
        elif payload.get('tool_name') == 'AskUserQuestion':
            first = (args.get('questions') or [{}])[0]
            text = first.get('question', '') if isinstance(first, dict) else ''
        else:
            path = args.get('file_path') or args.get('notebook_path')
            text = args.get('command') or (Path(str(path)).name if path else '') or args.get('url') or ''
        line = next((s for s in str(text).splitlines() if s.strip(' *_`#>|-')), '')
        line = ' '.join(re.sub(r'[*_`#>|]+', '', line).split())
        return line if len(line) <= limit else line[:limit - 1].rstrip() + '…'
    except Exception:
        return ''  # an odd payload must never cost us the state change


def project_of(payload):
    """A stable key for a session's project: Claude keeps transcripts in a folder named after the
    directory it was started in, which (unlike cwd) doesn't change when the session cds around."""
    transcript = payload.get('transcript_path')
    return Path(transcript).parent.name.lower() if isinstance(transcript, str) and transcript else ''


def read_json(path):
    try:
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), 'utf-8')
    for _ in range(10):
        try:
            return os.replace(tmp, path)
        except PermissionError:  # Windows: the pet is reading it right now
            time.sleep(0.02)
    tmp.unlink(missing_ok=True)


def handle_event(payload, env=os.environ):
    sid = re.sub(r'[^\w-]', '', str(payload.get('session_id', '')))[:64]
    # Headless runs have nobody to notify: sdk-* = `claude -p` / Agent SDK; ECC's observer loop runs
    # `claude --print` with ECC_SKIP_OBSERVE set. A -p started inside a VS Code session inherits
    # entrypoint=claude-vscode, so the entrypoint alone can't tell.
    if not sid or env.get('CLAUDE_CODE_ENTRYPOINT', '').startswith('sdk') or 'ECC_SKIP_OBSERVE' in env:
        return
    path = STATE_DIR / f'{sid}.json'
    cur = read_json(path) or {}
    new = next_state(cur.get('state'), payload.get('hook_event_name'), payload)
    ask = ask_text(payload) if new in ALARMS else ''
    if new is None:
        path.unlink(missing_ok=True)
    elif not (new == cur.get('state') and new in ALARMS):  # repeated alarm keeps its ts, so a seen alarm stays seen
        write_json(path, {'state': new, 'cwd': payload.get('cwd') or cur.get('cwd', ''), 'ts': time.time(),
                          'project': project_of(payload) or cur.get('project', ''),
                          'detail': payload.get('tool_name', '') if new == 'waiting' else '', 'ask': ask})
    elif ask and not cur.get('ask'):  # the same alarm, but now we know what it is about
        write_json(path, {**cur, 'ask': ask})


def log_event(payload):
    log = STATE_DIR / 'events.log'
    if log.exists() and log.stat().st_size > LOG_MAX:
        log.replace(log.with_suffix('.log.old'))
    keep = {k: payload.get(k) for k in ('hook_event_name', 'session_id', 'cwd', 'notification_type', 'message', 'tool_name')}
    keep['entrypoint'] = os.environ.get('CLAUDE_CODE_ENTRYPOINT')
    keep['background_tasks'] = payload.get('background_tasks')
    keep['ask'], keep['project'] = ask_text(payload), project_of(payload)
    if isinstance(payload.get('tool_input'), dict):
        keep['tool_input_keys'] = sorted(payload['tool_input'])
    keep['keys'] = sorted(payload)
    with log.open('a', encoding='utf-8') as f:
        f.write(f"{time.strftime('%m-%d %H:%M:%S')} {json.dumps(keep, ensure_ascii=False)}\n")


def run_hook():
    # Never print and never fail: hook stdout / exit codes can steer Claude.
    try:
        payload = json.loads(sys.stdin.buffer.read().decode('utf-8', 'replace'))
        STATE_DIR.mkdir(exist_ok=True)
        handle_event(payload)
        log_event(payload)
    except Exception:
        pass


def install(remove=False):
    raw = SETTINGS.read_text('utf-8') if SETTINGS.exists() else '{}'
    settings = json.loads(raw)
    backup = SETTINGS.with_name(f'settings.json.pet-backup-{time.strftime("%Y%m%d-%H%M%S")}')
    backup.write_text(raw, 'utf-8')
    # `|| exit 0`: if pet.py is ever moved, python exits 2, which would block every prompt and Stop
    command = f'"{Path(sys.executable).as_posix()}" "{Path(__file__).resolve().as_posix()}" hook || exit 0'
    hooks = dict(settings.get('hooks', {}))
    for event, matcher in HOOK_EVENTS.items():
        groups = [g for g in hooks.get(event, [])
                  if not any(HOOK_MARK in h.get('command', '') for h in g.get('hooks', []))]
        if not remove:
            groups.append({'matcher': matcher, 'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]})
        hooks[event] = groups
        if not groups:
            del hooks[event]
    SETTINGS.write_text(json.dumps({**settings, 'hooks': hooks}, indent=2, ensure_ascii=False) + '\n', 'utf-8')
    print(f'{"Removed" if remove else "Installed"} Claude Pet hooks in {SETTINGS} (backup: {backup.name})')


def read_config():
    """{pack, big, picks}; picks = {pack: {project: pet name}}, so a project keeps its pet."""
    cfg = read_json(STATE_DIR / CONFIG) or {}
    picks = cfg.get('picks') if isinstance(cfg.get('picks'), dict) else {}
    return {'pack': cfg.get('pack', 'cats'), 'big': bool(cfg.get('big')), 'picks': picks}


def write_config(**changes):
    STATE_DIR.mkdir(exist_ok=True)
    write_json(STATE_DIR / CONFIG, {**(read_json(STATE_DIR / CONFIG) or {}), **changes})  # keep what we don't touch


def choose_pack(key=None):
    from sprites import packs
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if key in packs():
        write_config(pack=key)
        print(f'Đã chọn bộ {packs()[key]["name"]}. Pet đang chạy sẽ đổi ngay.')
        return
    print('Các bộ pet:', ', '.join(f'{k} ({pack["name"]})' for k, pack in packs().items()))
    print('Đổi bộ: python pet.py pack <tên>')


# ---------- pet side: pure helpers ----------

def mode(rec, acked_ts, now):
    """What a cat does: 'done' / 'waiting' (alarm), 'working' or 'idle'."""
    state, ts = rec.get('state'), rec.get('ts', 0)
    if state in ALARMS and ts > acked_ts:
        return state
    if state in ('working', 'waiting') and now - ts < STALE_SECS:
        return 'working'  # an acknowledged 'waiting' was approved in VS Code and is running
    return 'idle'


def folder_names(cwd):
    """Folder names a VS Code window for this session could be titled with, deepest first."""
    return list(reversed(Path(cwd).parts[1:])) if cwd else []


def is_title_of(title, name):
    return f' - {name.lower()} - visual studio code' in ' - ' + title.lower()


def title_matches(title, cwd):
    return any(is_title_of(title, name) for name in folder_names(cwd))


def is_fullscreen(rect, screen, window_class):
    """Does this window cover the whole screen, like a video or a game? A maximized one stops at the taskbar."""
    left, top, right, bottom = rect
    return (window_class not in ('Progman', 'WorkerW')  # the desktop itself is screen-sized too
            and left <= 0 and top <= 0 and right >= screen[0] and bottom >= screen[1])


def load_states(now):
    states = {}
    for path in STATE_DIR.glob('*.json'):
        if path.name == CONFIG:
            continue
        rec = read_json(path)
        if rec is None:
            continue  # mid-write; next poll gets it
        if now - rec.get('ts', 0) > FORGET_SECS:
            path.unlink(missing_ok=True)
            continue
        states[path.stem] = rec
    return states


def run_ui():
    from app import run  # the window (and the sprites) load only here, never in hooks
    run()


# ---------- self-check ----------

def selftest():
    global STATE_DIR
    import tempfile
    from sprites import FRAMES, MOVES, PARTICLES, packs
    assert next_state(None, 'UserPromptSubmit', {}) == 'working'
    assert next_state('working', 'Stop', {}) == 'done'
    assert next_state('working', 'Stop', {'background_tasks': [{'type': 'local_agent'}]}) == 'working'
    assert next_state('working', 'Stop', {'background_tasks': [{'type': 'shell', 'command': 'ls agents/'}]}) == 'done'
    assert next_state('working', 'Stop', {'background_tasks': [{'type': 'monitor'}]}) == 'done'
    assert next_state('working', 'PermissionRequest', {}) == 'waiting'
    assert next_state('waiting', 'PostToolUse', {}) == 'working'
    assert next_state('waiting', 'PostToolUse', {'agent_id': 'a1'}) == 'waiting'
    assert next_state('working', 'Notification', {'notification_type': 'permission_prompt'}) == 'waiting'
    assert next_state('done', 'Notification', {'notification_type': 'idle_prompt'}) == 'done'
    assert next_state('working', 'PreToolUse', {'tool_name': 'AskUserQuestion'}) == 'waiting'
    assert next_state('working', 'PreToolUse', {'tool_name': 'Bash'}) == 'working'
    assert next_state('done', 'SessionEnd', {}) is None
    stop = {'hook_event_name': 'Stop', 'last_assistant_message': '\n## **Done:** fixed the `login` bug\nmore'}
    assert ask_text(stop) == 'Done: fixed the login bug'
    assert ask_text({'hook_event_name': 'Stop', 'last_assistant_message': [{'type': 'text', 'text': 'Hi'}]}) == 'Hi'
    assert ask_text({'tool_name': 'Edit', 'tool_input': {'file_path': 'C:/code/shop/app.py'}}) == 'app.py'
    assert ask_text({'tool_name': 'AskUserQuestion', 'tool_input': {'questions': 'oops'}}) == ''
    assert ask_text({'tool_name': 'Bash', 'tool_input': {'command': 'x' * 80}}).endswith('…')
    assert len(ask_text({'tool_name': 'Bash', 'tool_input': {'command': 'x' * 80}})) == 56
    now = 100_000.0
    assert mode({'state': 'done', 'ts': now - 5}, 0, now) == 'done'
    assert mode({'state': 'done', 'ts': now - 5}, now - 5, now) == 'idle'
    assert mode({'state': 'waiting', 'ts': now - 5}, now - 5, now) == 'working'
    assert mode({'state': 'working', 'ts': now - STALE_SECS - 1}, 0, now) == 'idle'
    assert title_matches('● app.py - shop - Visual Studio Code', r'C:\code\shop')
    assert title_matches('shop - Visual Studio Code', r'C:\code\shop\api')
    assert not title_matches('x - shopping - Visual Studio Code', r'C:\code\shop')
    assert is_fullscreen((0, 0, 1920, 1080), (1920, 1080), 'Chrome_WidgetWin_1')
    assert not is_fullscreen((-8, -8, 1928, 1040), (1920, 1080), 'Chrome_WidgetWin_1'), 'maximized is not fullscreen'
    assert not is_fullscreen((0, 0, 1920, 1080), (1920, 1080), 'Progman'), 'the desktop is not a video'
    assert {'cats', 'hoenn'} <= set(packs()), packs().keys()
    assert packs()['cats']['working'] == 'walk' and packs()['hoenn']['working'] == 'attack'
    assert all(len(frames) >= 2 for frames in PARTICLES.values()), 'a big frame plus a small one'
    for key, pack in packs().items():
        for pet in pack['pets']:
            sizes = {(len(rows), len(rows[0])) for rows in pet['frames'].values()}
            assert set(FRAMES) <= set(pet['frames']) and len(sizes) == 1, (key, pet['name'], sizes)
            if pack['working'] == 'attack':
                (height, width), (mx, my) = sizes.pop(), pet['move']['mouth']
                assert pet['move']['kind'] in MOVES and 0 <= mx < width and 0 <= my < height, pet['name']
                assert {'squash', 'stretch'} <= set(pet['frames']), pet['name']
            for frame, rows in pet['frames'].items():
                assert all(len(r) == len(rows[0]) for r in rows), (pet['name'], frame)
                assert set(''.join(rows + pet['icon'])) - {'.'} <= set(pet['colors']), (pet['name'], frame)
    real_dir = STATE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        STATE_DIR = Path(tmp)
        path = STATE_DIR / 'abc.json'

        def send(event, env=None, **extra):
            handle_event({'session_id': 'abc', 'hook_event_name': event, 'cwd': 'D:/x', **extra}, env=env or {})

        send('UserPromptSubmit')
        assert read_json(path)['state'] == 'working'
        send('Stop')
        done = read_json(path)
        send('Notification', notification_type='idle_prompt')
        assert read_json(path) == done, 'a repeated alarm must keep its timestamp'
        send('PermissionRequest', tool_name='Bash', tool_input={'command': 'npm test'})
        assert read_json(path)['detail'] == 'Bash' and read_json(path)['ask'] == 'npm test'
        send('PostToolUse')
        send('Notification', notification_type='permission_prompt')       # no text yet...
        waiting = read_json(path)
        send('PreToolUse', tool_name='AskUserQuestion', tool_input={'questions': [{'question': 'Ship it?'}]})
        assert read_json(path) == {**waiting, 'ask': 'Ship it?'}, '...filled in later, same timestamp'
        send('Stop', transcript_path='C:/u/.claude/projects/C--code-shop/abc.jsonl')
        assert read_json(path)['project'] == 'c--code-shop'
        send('SessionEnd')
        assert not path.exists()
        send('Stop', env={'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'})
        send('Stop', env={'CLAUDE_CODE_ENTRYPOINT': 'claude-vscode', 'ECC_SKIP_OBSERVE': '1'})
        assert not path.exists(), 'headless runs are ignored'
        assert read_config() == {'pack': 'cats', 'big': False, 'picks': {}}
        write_config(pack='hoenn', picks={'hoenn': {'c--code-shop': 'Mudkip'}})
        write_config(big=True)
        assert read_config() == {'pack': 'hoenn', 'big': True, 'picks': {'hoenn': {'c--code-shop': 'Mudkip'}}}
        assert load_states(time.time()) == {} and read_config()['pack'] == 'hoenn', 'config is not a session'
    STATE_DIR = real_dir
    print('ok')


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'run'
    {'hook': run_hook, 'install': install, 'uninstall': lambda: install(remove=True), 'test': selftest,
     'pack': lambda: choose_pack(*sys.argv[2:3])}.get(command, run_ui)()
