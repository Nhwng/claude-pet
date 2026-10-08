#!/usr/bin/env python3
"""Claude Pet: pixel pets above your taskbar that tell you when Claude Code is done or needs you.

    python pet.py install    add the hooks to ~/.claude/settings.json (backup written next to it)
                             and a "Claude Pet" Start Menu shortcut
    python pet.py            run the pets (pythonw pet.py = no console window)
    python pet.py uninstall  remove the hooks and the shortcut
    python pet.py pack [key] list the pet packs, or switch the running pet to one
    python pet.py hook       what Claude Code runs on each event (JSON on stdin)
    python pet.py test       self-check

Every Claude session gets its own pet: a cat breed, or one from packs/*.json. While Claude works the
cats chase yarn (or a pack's pets use their moves); when Claude is done or needs a decision the pet
hops with a bubble saying what about; otherwise it naps. Pets hide while VS Code is in front.
Click a pet to jump to its VS Code window, drag it to move it, right-click it for settings.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / '.claude-pet'
SETTINGS = Path.home() / '.claude' / 'settings.json'
CONFIG, GAME = 'config.json', 'game.json'   # live in STATE_DIR next to the session files
RESERVED = (CONFIG, GAME)                   # names a session file must never take
ASK_TOOLS = ('AskUserQuestion', 'ExitPlanMode')  # tools that always mean "Claude needs you"
HOOK_EVENTS = {'UserPromptSubmit': '*', 'PostToolUse': '*', 'PermissionRequest': '*', 'Notification': '*',
               'PreToolUse': '|'.join(ASK_TOOLS), 'Stop': '*', 'SessionEnd': '*', 'SubagentStart': '*',
               'SubagentStop': '*'}
HOOK_MARK = '/pet.py" hook'  # install writes posix paths; the slash keeps other-pet.py's hooks safe
ALARMS = ('done', 'waiting')
STALE_SECS = 15 * 60      # 'working' with no event this long: probably interrupted (Esc fires no Stop)
FORGET_SECS = 6 * 3600    # VS Code can close without SessionEnd
AGENT_SECS = 3600         # a subagent "running" this long ended without its SubagentStop (an interrupt, a crash)
LOG_MAX = 512 * 1024
PROGRAMS = Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
START_LINK, STARTUP_LINK = PROGRAMS / 'Claude Pet.lnk', PROGRAMS / 'Startup' / 'Claude Pet.lnk'  # menu; sign-in


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
    if f'{sid}.json'.lower() in RESERVED:
        return  # a session named "config" or "game" must not overwrite those files
    if payload.get('hook_event_name') in ('SubagentStart', 'SubagentStop'):
        return agent_event(sid, payload)
    path = STATE_DIR / f'{sid}.json'
    cur = read_json(path) or {}
    new = next_state(cur.get('state'), payload.get('hook_event_name'), payload)
    ask = ask_text(payload) if new in ALARMS else ''
    if new is None:
        path.unlink(missing_ok=True)
        for agent in STATE_DIR.glob(f'{sid}~*.agent'):
            agent.unlink(missing_ok=True)
    elif not (new == cur.get('state') and new in ALARMS):  # repeated alarm keeps its ts, so a seen alarm stays seen
        write_json(path, {'state': new, 'cwd': payload.get('cwd') or cur.get('cwd', ''), 'ts': time.time(),
                          'project': project_of(payload) or cur.get('project', ''),
                          'detail': payload.get('tool_name', '') if new == 'waiting' else '', 'ask': ask,
                          'tools': (cur.get('tools') if isinstance(cur.get('tools'), int) else 0)
                                   + (payload.get('hook_event_name') == 'PostToolUse')})
    elif ask and not cur.get('ask'):  # the same alarm, but now we know what it is about
        write_json(path, {**cur, 'ask': ask})


def agent_event(sid, payload):
    """A subagent starting or stopping. Each running one is a file of its own, <session>~<agent>.agent: Claude
    starts several at once, and their hooks run side by side, so one shared file would lose some of them."""
    agent = re.sub(r'[^\w-]', '', str(payload.get('agent_id', '')))[:80]
    if not agent:
        return
    path = STATE_DIR / f'{sid}~{agent}.agent'
    if payload.get('hook_event_name') == 'SubagentStart':
        write_json(path, {'type': str(payload.get('agent_type') or 'agent')[:40], 'ts': time.time()})
    else:
        path.unlink(missing_ok=True)


def log_event(payload):
    log = STATE_DIR / 'events.log'
    if log.exists() and log.stat().st_size > LOG_MAX:
        log.replace(log.with_suffix('.log.old'))
    keep = {k: payload.get(k) for k in ('hook_event_name', 'session_id', 'cwd', 'notification_type', 'tool_name')}
    keep['message'] = str(payload.get('message') or '')[:120]
    keep['entrypoint'] = os.environ.get('CLAUDE_CODE_ENTRYPOINT')
    keep['background_tasks'] = [t.get('type') for t in payload.get('background_tasks') or [] if isinstance(t, dict)]
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
    SETTINGS.parent.mkdir(exist_ok=True)
    raw = SETTINGS.read_text('utf-8-sig') if SETTINGS.exists() else '{}'
    settings = json.loads(raw)  # unreadable settings: stop here, before touching anything
    backup = SETTINGS.with_name(f'settings.json.pet-backup-{time.strftime("%Y%m%d-%H%M%S")}')
    backup.write_text(raw, 'utf-8')
    for old in sorted(SETTINGS.parent.glob('settings.json.pet-backup-*'))[:-3]:
        old.unlink()  # keep the three newest
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
    tmp = SETTINGS.with_name('settings.json.pet-tmp')
    tmp.write_text(json.dumps({**settings, 'hooks': hooks}, indent=2, ensure_ascii=False) + '\n', 'utf-8')
    os.replace(tmp, SETTINGS)  # all or nothing: a crash can't leave half a settings file
    print(f'{"Removed" if remove else "Installed"} Claude Pet hooks in {SETTINGS} (backup: {backup.name})')
    shortcut(remove)
    if remove:
        STARTUP_LINK.unlink(missing_ok=True)
    elif STARTUP_LINK.exists():
        shortcut(link=STARTUP_LINK)  # "start with Windows" is on: point it at this folder and Python too


def shortcut(remove=False, link=START_LINK):
    """A shortcut that starts the pet: the Start Menu entry, or STARTUP_LINK to start it when you sign in
    (paths go through env vars, so any folder name is fine)."""
    import subprocess
    if remove:
        link.unlink(missing_ok=True)
        return
    here = Path(__file__).resolve().parent
    env = {**os.environ, 'PET_LINK': str(link), 'PET_PYTHONW': str(Path(sys.executable).with_name('pythonw.exe')),
           'PET_SCRIPT': f'"{here / "pet.py"}"', 'PET_DIR': str(here), 'PET_ICON': f'{here / "pet.ico"},0'}
    script = ('$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PET_LINK); $s.TargetPath = $env:PET_PYTHONW; '
              '$s.Arguments = $env:PET_SCRIPT; $s.WorkingDirectory = $env:PET_DIR; $s.IconLocation = $env:PET_ICON; $s.Save()')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    done = subprocess.run([str(powershell), '-NoProfile', '-Command', script], env=env, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW).returncode == 0  # no console flash from the pet
    print(f'Shortcut: {link}' if done else 'Could not create the shortcut (start it with pythonw pet.py)')


def read_config():
    """{pack, big, sound, lang, screen, mode, picks}; picks = {pack: {project: pet name}}, so a project keeps its pet.
    mode: 'chill' (pets) or 'game' (heroes fighting bugs).
    sound: Game mode's effects (level-up); the done and needs-you chimes always sound.
    screen: 'main', 'auto' (follow the window you're in) or a monitor's device name."""
    cfg = read_json(STATE_DIR / CONFIG) or {}
    picks = cfg.get('picks') if isinstance(cfg.get('picks'), dict) else {}
    lang = cfg.get('lang') if cfg.get('lang') in ('en', 'vi') else 'en'
    return {'pack': cfg.get('pack', 'cats'), 'big': bool(cfg.get('big')), 'sound': cfg.get('sound') is not False,
            'lang': lang, 'screen': cfg.get('screen') if isinstance(cfg.get('screen'), str) else 'main',
            'mode': cfg.get('mode') if cfg.get('mode') in ('chill', 'game') else 'chill', 'picks': picks}


def write_config(**changes):
    STATE_DIR.mkdir(exist_ok=True)
    write_json(STATE_DIR / CONFIG, {**(read_json(STATE_DIR / CONFIG) or {}), **changes})  # keep what we don't touch


CLI_TEXT = {'en': ('Switched to {name}; the running pet changes right away.', 'Pet packs:', 'python pet.py pack <name>'),
            'vi': ('Đã chọn bộ {name}. Pet đang chạy sẽ đổi ngay.', 'Các bộ pet:', 'python pet.py pack <tên>')}


def choose_pack(key=None):
    from sprites import packs, tr
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    lang = read_config()['lang']
    switched, listing, usage = CLI_TEXT[lang]
    if key in packs():
        write_config(pack=key)
        print(switched.format(name=tr(packs()[key]['name'], lang)))
        return
    print(listing, ', '.join(f'{k} ({tr(pack["name"], lang)})' for k, pack in packs().items()))
    print(usage)


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


def is_fullscreen(rect, monitor, window_class):
    """Does this window cover its whole monitor, like a video or a game? A maximized one stops at the taskbar.
    Both are (left, top, right, bottom); a second monitor's left or top need not be 0."""
    return (window_class not in ('Progman', 'WorkerW')  # the desktop itself is screen-sized too
            and rect[0] <= monitor[0] and rect[1] <= monitor[1] and rect[2] >= monitor[2] and rect[3] >= monitor[3])


def screen_area(choice, monitors):
    """The work area of the chosen monitor ('main' or a device name); an unplugged one means the main one.
    monitors: [{'device', 'primary', 'work'}], work = (left, top, right, bottom)."""
    main = next((m for m in monitors if m['primary']), monitors[0])
    return next((m for m in monitors if m['device'] == choice), main)['work']


def load_states(now):
    states = {}
    for path in STATE_DIR.glob('*.json'):
        if path.name.lower() in RESERVED:
            continue
        rec = read_json(path)
        if not isinstance(rec, dict) or not isinstance(rec.get('ts', 0), (int, float)):
            continue  # mid-write (next poll gets it) or not ours
        if now - rec.get('ts', 0) > FORGET_SECS:
            path.unlink(missing_ok=True)
            continue
        states[path.stem] = rec
    return states


def load_agents(now):
    """{session: [(started, agent id, agent type), ...]} of the subagents running now, oldest first. One that has
    been running for over AGENT_SECS surely ended without a SubagentStop: its file goes."""
    found = {}
    for path in STATE_DIR.glob('*~*.agent'):
        rec = read_json(path)
        ts = rec.get('ts') if isinstance(rec, dict) else None
        if not isinstance(ts, (int, float)):
            continue  # being written right now (or not ours)
        if now - ts > AGENT_SECS:
            path.unlink(missing_ok=True)
            continue
        sid, agent = path.stem.split('~', 1)
        found.setdefault(sid, []).append((ts, agent, str(rec.get('type') or 'agent')))
    return {sid: sorted(agents) for sid, agents in found.items()}


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
    screen, right_screen = (0, 0, 1920, 1080), (1920, 0, 3840, 1080)
    assert is_fullscreen((0, 0, 1920, 1080), screen, 'Chrome_WidgetWin_1')
    assert not is_fullscreen((-8, -8, 1928, 1040), screen, 'Chrome_WidgetWin_1'), 'maximized is not fullscreen'
    assert not is_fullscreen((0, 0, 1920, 1080), screen, 'Progman'), 'the desktop is not a video'
    assert is_fullscreen((1920, 0, 3840, 1080), right_screen, 'Chrome_WidgetWin_1'), 'fullscreen on a second monitor'
    assert not is_fullscreen((0, 0, 1920, 1080), right_screen, 'Chrome_WidgetWin_1')
    monitors = [{'device': 'DISPLAY1', 'primary': True, 'work': (0, 0, 1920, 1032)},
                {'device': 'DISPLAY2', 'primary': False, 'work': (-2560, 0, -853, 1019)}]
    assert screen_area('main', monitors) == (0, 0, 1920, 1032) and screen_area('auto', monitors) == (0, 0, 1920, 1032)
    assert screen_area('DISPLAY2', monitors) == (-2560, 0, -853, 1019)
    assert screen_area('DISPLAY9', monitors) == (0, 0, 1920, 1032), 'an unplugged screen falls back to the main one'
    from look import TEXT
    from sounds import CHIMES, notes
    assert all(notes(kind) and max(abs(v) for v in notes(kind)) < 32767 for kind in CHIMES), 'chimes render, no clipping'
    assert TEXT['en'].keys() == TEXT['vi'].keys(), 'every line in both languages'
    import sprites
    real_packs_dir = sprites.PACKS_DIR
    with tempfile.TemporaryDirectory() as tmp:  # a sample pack, so this passes on a fresh clone too
        rows = ['..AAAA..', '.ABBBBA.', 'ABWBBWBA', 'ABBBBBBA', '.AAAAAA.']
        sample = {'name': 'Blob', 'colors': {'A': '#1b1b22', 'B': '#3ab0ff', 'W': '#ffffff'}, 'rows': rows,
                  'shut': rows, 'move': {'name': 'Water Gun', 'kind': 'water', 'mouth': [7, 2]}}
        Path(tmp, 'sample.json').write_text(json.dumps({'name': 'Sample', 'hop': True, 'pets': [sample]}), 'utf-8')
        Path(tmp, 'broken.json').write_text('{"name": "Broken", "pets": [{"rows": []}]}', 'utf-8')
        sprites.PACKS_DIR = Path(tmp)
        packs.cache_clear()
        assert set(packs()) == {'cats', 'sample'}, 'the broken pack is skipped, not fatal'
        assert packs()['cats']['working'] == 'walk' and packs()['sample']['working'] == 'attack'
        assert packs()['sample']['hop'] and not packs()['cats']['hop'], 'only packs that ask for it hop'
        checked = packs()
    sprites.PACKS_DIR = real_packs_dir
    packs.cache_clear()
    assert all(len(frames) >= 2 for frames in PARTICLES.values()), 'a big frame plus a small one'
    for key, pack in checked.items():
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
    import xp
    assert [xp.level_of(t) for t in (0, 19_999, 20_000, 320_000, 1_620_000, 7_220_000, 192_080_000, 10 ** 12)] == \
        [1, 1, 2, 5, 10, 20, 99, 99]
    assert xp.progress(0) == 0 and abs(xp.progress(30_000) - 1 / 6) < 1e-9 and xp.progress(10 ** 12) == 1.0
    assert [xp.tier_of(lv) for lv in (1, 9, 10, 24, 25, 49, 50, 99)] == [0, 0, 1, 1, 2, 2, 3, 3]

    def reply(rid, out):
        return json.dumps({'type': 'assistant', 'message': {'id': rid, 'usage': {'output_tokens': out}}}) + '\n'

    def add(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(text)
    with tempfile.TemporaryDirectory() as tmp:
        root, log = Path(tmp), Path(tmp, 'C--code-Shop', 's1.jsonl')
        add(log, reply('old', 500))
        store = xp.scan(None, root)
        assert store['tokens'] == {}, 'what Claude wrote before Game mode is history: everyone starts at Lv 1'
        half = reply('h', 7)
        add(log, reply('a', 100) + reply('a', 150) + '{"type": "user"}\n' + reply('b', 40) + reply('a', 150)
            + 'not json\n' + half[:20])
        store = xp.scan(store, root)
        assert store['tokens'] == {'c--code-shop': 190}, 'a reply counts once, at its largest; half a line waits'
        add(log, half[20:] + reply(None, 10))
        add(Path(tmp, 'C--code-Shop', 's1', 'subagents', 'x.jsonl'), reply('s', 3))
        store = xp.scan(store, root)
        assert store['tokens'] == {'c--code-shop': 210}, 'the rest of that line, a reply with no id, a new file'
        assert xp.scan({'files': {}}, root)['tokens'] == {'c--code-shop': 710}, 'no offsets: history counts too'
        log.write_text(reply('z', 1), 'utf-8')
        assert xp.scan(store, root)['tokens'] == {'c--code-shop': 210}, 'a file cut short adds nothing'
        assert xp.scan({'tokens': 'junk', 'files': 'junk'}, root)['tokens'] == {}, 'a broken store starts over'
    import cast
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, 'Idle.png').write_bytes(b'png')
        anim = {'sheet': 'Idle.png', 'w': 32, 'h': 32, 'n': 4, 'fps': 8, 'crop': [0, 0, 32, 32]}
        hero = {'key': 'k', 'name': 'K', 'body': [4, 2, 20, 32], 'anims': {a: anim for a in cast.ANIMS}}
        lame = {**hero, 'anims': {'idle': anim}}
        Path(tmp, 'broken.json').write_text('{', 'utf-8')
        Path(tmp, 'cast.json').write_text(json.dumps({'heroes': [hero, lame], 'bugs': [hero]}), 'utf-8')
        found, base = cast.load([Path(tmp, 'missing.json'), Path(tmp, 'broken.json'), Path(tmp, 'cast.json')])
        assert base == Path(tmp) and [h['key'] for h in found['heroes']] == ['k'] and found['bosses'] == [], \
            'the first usable cast file; characters missing an animation are left out'
        assert cast.load([Path(tmp, 'broken.json')]) == ({}, None), 'no cast: Game mode waits'
        combo = {**hero, 'anims': {**hero['anims'], 'attack2': {**anim, 'n': 10}}, 'hits': {'attack2': [1, 3, 7]}}
        Path(tmp, 'combo.json').write_text(json.dumps({'heroes': [combo]}), 'utf-8')
        sprites = cast.Sprites(None, *cast.load([Path(tmp, 'combo.json')]), 1)
        assert sprites.attacks('heroes', 0) == ['attack', 'attack2'] and sprites.hits('heroes', 0, 'attack2') == [1, 3, 7], \
            'every attack a hero has, a combo landing several blows'
        assert sprites.hits('heroes', 0, 'attack') == [2], 'no hits measured: the middle frame'
        Path(tmp, 'odd.json').write_text(json.dumps({'heroes': [hero], 'bugs': 5, 'bosses': [{**hero, 'body': 'x'}]}))
        odd, _ = cast.load([Path(tmp, 'odd.json')])
        assert odd['bugs'] == [] and odd['bosses'] == [], 'a malformed group or box is left out, not fatal'
        assert cast.load([Path(tmp, 'odd.json')]) and not cast.usable({**hero, 'anims': {
            **hero['anims'], 'run': {**anim, 'fps': 0}}}, Path(tmp)), 'an animation needs a speed'
    bosses = [{'tier': 0}, {'tier': 2}, {'tier': 'big'}, {}]
    assert {cast.pick_boss(bosses, 0) for _ in range(200)} == {0, 2, 3}, 'a boss waits for its tier; no tier is 0'
    assert {cast.pick_boss(bosses, 3) for _ in range(200)} == {0, 1, 2, 3}, 'gold meets them all'
    assert {cast.pick_boss([{'tier': 3}, {'tier': 2}, {'tier': -5}], 0) for _ in range(50)} == {2}, \
        'a tier below 0 counts as 0'
    from game import tallies
    from menu import short
    assert [short(n, 'en') for n in (999, 1234, 999_949, 999_950, 1_268_220)] == \
        ['999', '1.2k', '999.9k', '1.00M', '1.27M'] and short(1234, 'vi') == '1,2k', 'short token counts'
    assert tallies({'p': {'bosses': 2, 'bugs': 'x'}, 'q': 'x'}) == {'p': {'bosses': 2}}, 'a hand-edited tally'
    assert {cast.pick_boss([{'tier': 3}, {'tier': 2}], 0) for _ in range(50)} == {1}, 'none unlocked: the lowest'
    gained, recent = xp.count([reply(f'r{i}', 1).encode() for i in range(xp.RECENT + 50)], {})
    assert gained == xp.RECENT + 50 and len(recent) == xp.RECENT, 'remembered ids stay bounded'
    real_dir = STATE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        STATE_DIR = Path(tmp)
        path = STATE_DIR / 'abc.json'

        def send(event, env=None, **extra):
            handle_event({'session_id': 'abc', 'hook_event_name': event, 'cwd': 'D:/x', **extra}, env=env or {})

        send('UserPromptSubmit')
        assert read_json(path)['state'] == 'working'
        send('PostToolUse')
        send('PostToolUse')
        assert read_json(path)['tools'] == 2, 'each tool call counts once (a bug in Game mode)'
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
        before = read_json(path)
        send('SubagentStart', agent_id='subagent_1', agent_type='Explore')
        send('SubagentStart', agent_id='subagent_2', agent_type='code-reviewer')
        assert [a[2] for a in load_agents(time.time())['abc']] == ['Explore', 'code-reviewer'], 'agents, oldest first'
        assert read_json(path) == before, "agents coming and going don't touch the session (nor a seen alarm)"
        send('SubagentStop', agent_id='subagent_1', agent_type='Explore')
        assert [a[1] for a in load_agents(time.time())['abc']] == ['subagent_2'], 'a finished agent goes'
        write_json(STATE_DIR / 'abc~old.agent', {'type': 'Plan', 'ts': time.time() - AGENT_SECS - 1})
        assert len(load_agents(time.time())['abc']) == 1 and not (STATE_DIR / 'abc~old.agent').exists(), \
            'an agent that never stopped is let go after an hour'
        send('SessionEnd')
        assert not path.exists() and load_agents(time.time()) == {}, 'the session ends: its agents too'
        send('Stop', env={'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'})
        send('Stop', env={'CLAUDE_CODE_ENTRYPOINT': 'claude-vscode', 'ECC_SKIP_OBSERVE': '1'})
        assert not path.exists(), 'headless runs are ignored'
        assert read_config() == {'pack': 'cats', 'big': False, 'sound': True, 'lang': 'en', 'screen': 'main',
                                 'mode': 'chill', 'picks': {}}
        write_config(pack='sample', picks={'sample': {'c--code-shop': 'Blob'}})
        write_config(big=True)
        assert read_config() == {'pack': 'sample', 'big': True, 'sound': True, 'lang': 'en', 'screen': 'main',
                                 'mode': 'chill', 'picks': {'sample': {'c--code-shop': 'Blob'}}}
        assert load_states(time.time()) == {} and read_config()['pack'] == 'sample', 'config is not a session'
        write_json(STATE_DIR / 'game.json', {'tokens': {'c--code-shop': 5}, 'files': {}})
        handle_event({'session_id': 'GAME', 'hook_event_name': 'Stop', 'cwd': 'D:/x'}, env={})
        assert load_states(time.time()) == {} and read_json(STATE_DIR / 'game.json')['tokens'], 'game.json is no session'
        write_config(mode='game')
        assert read_config()['mode'] == 'game'
        write_config(mode='bogus')
        assert read_config()['mode'] == 'chill'
    STATE_DIR = real_dir
    print('ok')


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'run'
    {'hook': run_hook, 'install': install, 'uninstall': lambda: install(remove=True), 'test': selftest,
     'pack': lambda: choose_pack(*sys.argv[2:3])}.get(command, run_ui)()
