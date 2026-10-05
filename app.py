"""The Claude Pet window: a transparent, click-through, never-focused strip above the taskbar.

pet.py writes each Claude session's state; this file draws one pet per session from it.
"""
import os
import random
import sys
import time
from pathlib import Path

import cast
import pet
from pet import (ALARMS, folder_names, is_fullscreen, is_title_of, load_states, mode, read_config, screen_area,
                 title_matches, write_config)
import sounds
from game import BOSS_ANIMS, GameMixin
from look import (ALARM_COLORS, CHIP_LINE, FONT_SUB, FONT_TAG, FONT_TITLE, FX_COLORS, ICON_COLORS, INK, MUTED, PAPER,
                  SHADOW, TEXT, TIER_COLORS, XP_COLOR)
from menu import MenuMixin
from sprites import (ICONS, MOVE_END, MOVE_FIRE, MOVES, PARTICLE_COLORS, PARTICLES, SPARKLE, TWINKLE, YARN, YARN_COLORS,
                     ZZZ_BIG, ZZZ_SMALL, packs, tr, with_outline)


KEY = '#ff00fe'                  # transparent colour key: these pixels are see-through and click-through
TICK_MS, IDLE_MS, POLL_MS = 33, 120, 500   # ~30 fps while anything moves, ~8 fps when all is still
JUMP_V, GRAVITY = 32.0, 54.0     # sprite px per second, and per second squared
HOP_V, HOP_VX = 24.0, 14.0       # a slime's hop: up and forward, sprite px per second
ZZZ = ((with_outline(ZZZ_BIG), 0), (with_outline(ZZZ_SMALL), 6))   # (art, phase offset)
DESKTOP = ('Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd')  # not "where you are working"


def user32():
    import ctypes
    from ctypes import wintypes as w
    u = ctypes.WinDLL('user32')
    u.GetForegroundWindow.restype = w.HWND
    u.GetWindowTextW.argtypes = (w.HWND, w.LPWSTR, ctypes.c_int)
    u.IsWindowVisible.argtypes = u.IsIconic.argtypes = u.SetForegroundWindow.argtypes = (w.HWND,)
    u.ShowWindow.argtypes = (w.HWND, ctypes.c_int)
    u.EnumWindows.argtypes = (ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM), w.LPARAM)
    u.SystemParametersInfoW.argtypes = (w.UINT, w.UINT, ctypes.c_void_p, w.UINT)
    u.GetWindowLongW.argtypes = (w.HWND, ctypes.c_int)
    u.SetWindowLongW.argtypes = (w.HWND, ctypes.c_int, w.LONG)
    u.SetWindowPos.argtypes = (w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT)
    u.GetWindowRect.argtypes = (w.HWND, ctypes.c_void_p)
    u.GetClassNameW.argtypes = (w.HWND, w.LPWSTR, ctypes.c_int)
    u.MonitorFromWindow.argtypes, u.MonitorFromWindow.restype = (w.HWND, w.DWORD), w.HMONITOR
    u.GetMonitorInfoW.argtypes = (w.HMONITOR, ctypes.c_void_p)
    u.EnumDisplayMonitors.argtypes = (w.HDC, ctypes.c_void_p,
                                      ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.c_void_p, w.LPARAM), w.LPARAM)
    return u


class Cat:
    """One Claude session's pet on the strip. Times are in seconds, positions in screen px."""

    def __init__(self, kind, x):
        self.kind, self.x = kind, x
        self.dir, self.speed = random.choice((-1, 1)), random.uniform(6, 10.5)  # ui px per second
        self.y = self.vy = 0.0                      # hop height, in sprite px above the ground
        self.t, self.hop_at = random.uniform(0, 10), 0.0
        self.move_t, self.rest, self.emit = None, random.uniform(.5, 2), 0.0  # move_t: time into a move
        self.fx = []                                # particles of the current move
        self.rec, self.mode, self.box, self.moving = {}, 'idle', (0, 0, 0, 0), False
        self.tag, self.item, self.shown, self.decor = f'pet{id(self)}', None, None, None  # its canvas items
        self.ball, self.swat, self.held = None, 0.0, False  # yarn (cats), pounce timer, being dragged
        self.crouch, self.wait = 0.0, random.uniform(.4, 1)  # hoppers: time since landing, and until the next hop
        self.level, self.tier, self.bar, self.flash = None, 0, 0, 0.0  # Game mode: a hero's level and its fight
        self.swing, self.spawn, self.queue, self.tools, self.beaten = 0.0, 0.0, 0, None, 0.0
        self.bugs, self.shots, self.bursts, self.boss = [], [], [], None
        self.ouch, self.home, self.goal, self.pause, self.stride = 0.0, None, None, 0.0, 1.0  # flinch, patrol
        self.move, self.shake = 'attack', 0.0              # which of its attacks it swings; a boss kill's shake


class PetApp(GameMixin, MenuMixin):
    def __init__(self):
        import tkinter as tk
        self.tk, self.u = tk, user32()
        previous = self.u.GetForegroundWindow()
        root = self.root = tk.Tk()
        root.title('Claude Pet')
        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-transparentcolor', KEY)
        root.report_callback_exception, self.errors = self.report, set()
        self.dpi =max(1, round(root.winfo_fpixels('1i') / 96))
        self.ui = 2 * self.dpi  # bubbles, plates and effects; the pets themselves use self.scale
        self.canvas = tk.Canvas(root, bg=KEY, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind('<ButtonPress-1>', self.on_press)
        self.canvas.bind('<B1-Motion>', self.on_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_release)
        self.drag, self.fullscreen = None, False
        self.canvas.bind('<Button-3>', lambda e: self.open_menu(e.x, e.y))
        self.canvas.bind('<Motion>', self.on_motion)
        self.fonts, self.menu_hits, self.menu_box, self.menu_until, self.menu_sid = {}, None, (0, 0, 0, 0), 0.0, None
        self.menu_x, self.area = 0, self.work_area()  # the strip sits on this monitor's work area
        self.cats, self.acked, self.sounded, self.images = {}, {}, {}, {}
        self.hide, self.settings, self.xp, self.sprites = True, None, {}, None
        self.apply(read_config())
        root.update_idletasks()
        self.hwnd = int(root.wm_frame(), 16)
        self.u.SetWindowLongW(self.hwnd, -20, self.u.GetWindowLongW(self.hwnd, -20) | 0x08000000)  # WS_EX_NOACTIVATE
        if previous:  # mapping the window activated it once; hand focus straight back
            self.u.SetForegroundWindow(previous)
        self.last = time.monotonic()
        self.poll()
        self.tick()
        root.mainloop()

    def report(self, *exc):
        """An error in a Tk callback. pythonw has no console, so each distinct one goes to errors.log once."""
        import traceback
        text = ''.join(traceback.format_exception(*exc))
        if text in self.errors or len(self.errors) > 20:
            return
        self.errors.add(text)
        try:
            with (pet.STATE_DIR / 'errors.log').open('a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%m-%d %H:%M:%S')} {text}\n")
        except OSError:
            pass

    def apply(self, settings):
        """Use a pet pack and size, or Game mode's cast. Pets are dealt again from it on this poll."""
        data, base = cast.load() if settings['mode'] == 'game' else ({}, None)
        self.pack = None
        if data:
            try:
                self.pack = self.hero_pack(data, base)
                self.sprites.check()  # a sheet tkinter can't read: the pets carry on instead
                self.pack_key = 'heroes'
            except (self.tk.TclError, OSError, ValueError):
                self.report(*sys.exc_info())
                self.pack = None
        if self.pack is None:  # Chill mode, or Game mode without a usable cast
            self.pack_key = settings['pack'] if settings['pack'] in packs() else 'cats'
            self.pack = packs()[self.pack_key]
        else:
            self.start_xp()
        self.canvas.delete('all')
        self.images, self.cats, self.menu_hits = {}, {}, None  # first: the old pets' kinds mean nothing in this pack
        if self.game:  # the cast's frames come zoomed already: screen px throughout
            self.scale = 1
            tallest = max(self.sprites.tallest('heroes'), self.sprites.tallest('bosses', BOSS_ANIMS))
            self.h = tallest + 10 * self.dpi + 40 * self.ui
        else:
            self.scale = (self.pack['scale'] + settings['big']) * self.dpi
            tallest = max(len(pet['frames']['sit']) for pet in self.pack['pets'])
            self.h = (tallest + 10) * self.scale + 40 * self.ui
        self.place(self.area)
        self.drop = float(self.h) if self.hide else 0.0
        self.settings = settings  # last: if anything above failed, the next poll tries again

    def place(self, area):
        """Put the strip along the bottom of a monitor's work area; pets past its new edge walk back in."""
        left, _, right, bottom = self.area = area
        self.w = right - left
        self.root.geometry(f'{self.w}x{self.h}+{left}+{bottom - self.h}')
        self.canvas.config(width=self.w, height=self.h)
        for cat in self.cats.values():
            cat.x, cat.fx = min(cat.x, self.w - self.width(cat.kind)), []
            if cat.ball:
                cat.ball['x'] = min(cat.ball['x'], self.w - 8 * self.ui)

    def monitor(self, hwnd):
        """(whole monitor, work area) of the screen a window is on, as (left, top, right, bottom)."""
        import ctypes
        from ctypes import wintypes as w

        class MonitorInfo(ctypes.Structure):
            _fields_ = [('cbSize', w.DWORD), ('rcMonitor', w.RECT), ('rcWork', w.RECT), ('dwFlags', w.DWORD)]
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        self.u.GetMonitorInfoW(self.u.MonitorFromWindow(hwnd, 2), ctypes.byref(info))  # 2: the nearest one
        return tuple((r.left, r.top, r.right, r.bottom) for r in (info.rcMonitor, info.rcWork))

    def monitors(self):
        """Every monitor as {device, primary, work}, the main one first, then left to right."""
        import ctypes
        from ctypes import wintypes as w

        class MonitorInfoEx(ctypes.Structure):
            _fields_ = [('cbSize', w.DWORD), ('rcMonitor', w.RECT), ('rcWork', w.RECT), ('dwFlags', w.DWORD),
                        ('szDevice', w.WCHAR * 32)]
        found = []

        def add(handle, *_):
            info = MonitorInfoEx(cbSize=ctypes.sizeof(MonitorInfoEx))
            self.u.GetMonitorInfoW(handle, ctypes.byref(info))
            r = info.rcWork
            found.append({'device': info.szDevice, 'primary': bool(info.dwFlags & 1),
                          'work': (r.left, r.top, r.right, r.bottom)})
            return True
        self.u.EnumDisplayMonitors(None, None, self.u.EnumDisplayMonitors.argtypes[2](add), 0)
        return sorted(found, key=lambda m: (not m['primary'], m['work'][0])) or [
            {'device': '', 'primary': True, 'work': self.work_area()}]

    def strip_rect(self):
        left, _, right, bottom = self.area
        return left, bottom - self.h, right, bottom

    def width(self, kind):
        if self.game:
            return self.sprites.body('heroes', kind)[0]
        return len(self.pack['pets'][kind]['frames']['sit'][0]) * self.scale

    # --- win32 ---
    def work_area(self):
        from ctypes import byref, wintypes
        r = wintypes.RECT()
        self.u.SystemParametersInfoW(0x30, 0, byref(r), 0)  # SPI_GETWORKAREA: screen minus taskbar
        return r.left, r.top, r.right, r.bottom

    def rect(self, hwnd):
        from ctypes import byref, wintypes
        r = wintypes.RECT()
        self.u.GetWindowRect(hwnd, byref(r))
        return r.left, r.top, r.right, r.bottom

    def window_class(self, hwnd):
        import ctypes
        buf = ctypes.create_unicode_buffer(64)
        self.u.GetClassNameW(hwnd, buf, 64)
        return buf.value

    def title(self, hwnd):
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        self.u.GetWindowTextW(hwnd, buf, 512)
        return buf.value

    def focus_vscode(self, cwd):
        import shutil
        import subprocess
        wins = []
        callback = self.u.EnumWindows.argtypes[0](
            lambda hwnd, _: wins.append((hwnd, self.title(hwnd))) or True if self.u.IsWindowVisible(hwnd) else True)
        self.u.EnumWindows(callback, 0)
        for name in folder_names(cwd):  # deepest folder first: the window opened closest to the session
            for hwnd, title in wins:
                if is_title_of(title, name):
                    if self.u.IsIconic(hwnd):
                        self.u.ShowWindow(hwnd, 9)  # SW_RESTORE
                    self.u.SetForegroundWindow(hwnd)
                    return
        # Start Code.exe itself, next to the bin\code.cmd on PATH: a .cmd would run through cmd.exe,
        # where a folder named like "R&D" could smuggle in a second command.
        code = shutil.which('code')
        exe = Path(code).resolve().parent.parent / 'Code.exe' if code else None
        if exe and exe.is_file() and os.path.isdir(cwd) and not cwd.startswith('-'):
            subprocess.Popen([str(exe), cwd], creationflags=subprocess.CREATE_NO_WINDOW)

    # --- loop ---
    def poll(self):
        self.root.after(POLL_MS, self.poll)  # first: an error below costs one poll, not the whole loop
        settings = read_config()
        if any(settings[key] != self.settings[key] for key in ('pack', 'big', 'mode')):
            self.apply(settings)
        self.settings = settings  # picks change without dealing the pets again
        now, cats = time.time(), {}
        for sid, rec in load_states(now).items():
            cat = self.cats.get(sid)
            if cat is None:
                kind = self.kind_for(rec, cats)
                cat = Cat(kind, self.free_spot(kind, cats))
            cat.rec = rec
            cats[sid] = cat
        for sid in self.cats.keys() - cats.keys():
            self.canvas.delete(self.cats[sid].tag)
        self.cats = cats
        front = self.u.GetForegroundWindow()
        title = self.title(front)
        in_code = 'Visual Studio Code' in title
        working_in = bool(front) and front != self.hwnd and self.window_class(front) not in DESKTOP
        screen, front_area = self.monitor(front) if working_in else (None, None)
        if self.settings['screen'] == 'auto':
            area = front_area or self.area  # follow you to the monitor you're working on
        else:
            area = screen_area(self.settings['screen'], self.monitors())
        # over a fullscreen video or game on the pets' own monitor, only pets with news show
        self.fullscreen = front_area == area and is_fullscreen(self.rect(front), screen, self.window_class(front))
        if area != self.area:
            self.place(area)
        elif max(abs(a - b) for a, b in zip(self.rect(self.hwnd), self.strip_rect())) > 2:
            # Windows once left it resized but not moved: put it back (2 px of slack for DPI rounding)
            x0, y0, x1, y1 = self.strip_rect()
            self.u.SetWindowPos(self.hwnd, -1, x0, y0, x1 - x0, y1 - y0, 0x10)  # HWND_TOPMOST, SWP_NOACTIVATE
        if in_code:  # looking at that project's window counts as having seen its alarm
            for sid, cat in cats.items():
                if title_matches(title, cat.rec.get('cwd')):
                    self.acked[sid] = cat.rec.get('ts', 0)
        self.hide = in_code or not cats
        # The taskbar steals z-order when clicked. Never activate: the pet must not eat your typing.
        self.u.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x13)  # HWND_TOPMOST; NOSIZE|NOMOVE|NOACTIVATE

    def free_spot(self, kind, new_cats):
        """The x, out of a dozen random tries, farthest from the pets already on the strip."""
        others = [c.x for c in (*self.cats.values(), *new_cats.values())]
        tries = [random.uniform(0, self.w - self.width(kind)) for _ in range(12)]
        return max(tries, key=lambda x: min((abs(x - o) for o in others), default=0))

    def kind_for(self, rec, new_cats):
        """The pet this project already has in this pack, else a free one, which then stays its pet."""
        names, project = [pet['name'] for pet in self.pack['pets']], self.project(rec)
        chosen = self.settings['picks'].get(self.pack_key, {}).get(project)
        if chosen in names:
            return names.index(chosen)
        kind = self.free_kind(new_cats)
        self.remember(project, kind)
        return kind

    @staticmethod
    def project(rec):
        return rec.get('project') or os.path.normcase(rec.get('cwd') or '?')

    def remember(self, project, kind):
        picks = dict(self.settings['picks'])
        picks[self.pack_key] = {**picks.get(self.pack_key, {}), project: self.pack['pets'][kind]['name']}
        self.settings = {**self.settings, 'picks': picks}
        write_config(picks=picks)

    def free_kind(self, new_cats):
        used, kinds = {c.kind for c in (*self.cats.values(), *new_cats.values())}, range(len(self.pack['pets']))
        return random.choice([k for k in kinds if k not in used] or kinds)

    def tick(self):
        busy = True
        try:
            now = time.monotonic()
            dt, self.last = min(now - self.last, .1), now
            # The window stays mapped (transparent, click-through); hiding just sinks the cats out of it.
            # withdraw/deiconify would activate it and steal focus.
            target = self.h if self.hide else 0
            self.drop += (target - self.drop) * (1 - .03 ** dt)
            busy = abs(target - self.drop) > 1
            self.canvas.delete('fx')  # particles, sparkles and z's are redrawn every frame; the rest is kept
            if self.drop < self.h - 2:
                wall = time.time()
                for sid, cat in self.cats.items():
                    self.step(sid, cat, wall, dt)
                    if self.fullscreen and cat.mode not in ALARMS and not cat.held:
                        self.canvas.delete(cat.tag)  # over a fullscreen video, only pets with news may show
                        cat.item = cat.decor = None
                        continue
                    self.draw(cat)
                    busy = (busy or cat.moving or cat.mode == 'working' or cat.y > 0 or cat.vy > 0 or bool(cat.fx)
                            or cat.held or bool(cat.bugs or cat.shots or cat.bursts) or cat.boss is not None
                            or cat.flash > 0)
                if self.menu_hits is not None:
                    self.close_menu() if now > self.menu_until or self.hide else self.canvas.tag_raise('menu')
            elif self.canvas.find_all():
                self.canvas.delete('all')
                self.menu_hits = None
                for cat in self.cats.values():
                    cat.item = cat.decor = None
        finally:  # an error costs one frame, not the loop
            self.root.after(TICK_MS if busy else IDLE_MS, self.tick)

    def step(self, sid, cat, now, dt):
        cat.mode = mode(cat.rec, self.acked.get(sid, 0), now)
        cat.t += dt
        if cat.mode != 'working':
            cat.move_t = cat.ball = None
        if cat.held:  # in your hand: no walking, no falling
            cat.moving = False
            self.fly(cat, dt)
            return
        right = self.w - self.width(cat.kind)
        crowd = self.crowding(cat) if cat.mode in ALARMS and cat.y == 0 else None
        cat.moving = crowd is not None
        if crowd:  # walk away until the bubbles stop overlapping
            cat.dir = 1 if (cat.x, id(cat)) > (crowd.x, id(crowd)) else -1
            cat.x = min(max(cat.x + cat.dir * 18 * self.ui * dt, 0), right)
        elif cat.mode == 'working' and self.pack['working'] == 'walk':
            cat.moving = self.play(cat, dt, right)
        elif cat.mode == 'working' and not self.game:
            self.use_move(cat, dt)
        elif cat.mode in ALARMS:
            if cat.y == 0 and cat.t >= cat.hop_at:
                cat.vy, cat.hop_at = JUMP_V, cat.t + (1 if cat.mode == 'waiting' else 2)
            self.chime(sid, cat)
        if self.game:
            self.game_step(cat, dt)
        if cat.y > 0 or cat.vy > 0:
            cat.y += cat.vy * dt
            cat.vy -= GRAVITY * dt
            if cat.y <= 0:
                cat.y = cat.vy = 0.0
        self.fly(cat, dt)

    def play(self, cat, dt, right):
        """While Claude works, a cat chases a ball of yarn: trots after it, pounces, bats it away again.
        Returns whether it is running."""
        u, w = self.ui, self.width(cat.kind)
        ball = cat.ball = cat.ball or {'x': min(max(cat.x + w / 2 + cat.dir * 40 * u, 8 * u), self.w - 8 * u),
                                       'vx': 0.0, 'y': 0.0, 'vy': 0.0, 'roll': 0.0}
        ball['x'] += ball['vx'] * dt
        if not 6 * u <= ball['x'] <= self.w - 6 * u:  # bounce off the screen edges
            ball['x'], ball['vx'] = min(max(ball['x'], 6 * u), self.w - 6 * u), -ball['vx']
        ball['vx'] *= .3 ** dt                         # and roll to a stop
        ball['roll'] += abs(ball['vx']) * dt
        if ball['y'] > 0 or ball['vy'] > 0:
            ball['y'], ball['vy'] = ball['y'] + ball['vy'] * dt, ball['vy'] - 320 * u * dt
            if ball['y'] <= 0:
                ball['y'], ball['vy'] = 0.0, -ball['vy'] * .45 if ball['vy'] < -60 * u else 0.0
        if cat.swat > 0:
            cat.swat -= dt
            return False
        gap = ball['x'] - (cat.x + (w * .82 if cat.dir > 0 else w * .18))  # from its front paw
        if abs(gap) > 5 * u:
            cat.dir = 1 if gap > 0 else -1
            cat.x = min(max(cat.x + cat.dir * cat.speed * 1.8 * u * dt, 0), right)
            return True
        if abs(ball['vx']) < 12 * u:  # caught it: pounce, and bat it away (mostly ahead, never into a wall)
            away = cat.dir if random.random() < .7 else -cat.dir
            if not .15 * self.w < ball['x'] < .85 * self.w:
                away = 1 if ball['x'] < self.w / 2 else -1
            cat.swat, cat.vy = .35, JUMP_V * .45
            ball['vx'], ball['vy'] = away * random.uniform(120, 220) * u, random.uniform(40, 110) * u
        return False

    def chime(self, sid, cat):
        """Beep once per alarm, when it is actually on screen."""
        ts = cat.rec.get('ts', 0)
        if self.sounded.get(sid, 0) < ts and self.drop < 1:
            self.sounded[sid] = ts
            if self.settings['sound']:
                sounds.play(cat.mode, pet.STATE_DIR)

    def use_move(self, cat, dt):
        """Stand still and use the pet's move every few seconds: wind up, lunge, fire, recover."""
        if cat.move_t is None:
            cat.rest -= dt
            if self.pack['hop']:
                self.hop(cat, dt)
            if cat.rest <= 0 and cat.y == cat.vy == 0:  # moves are used from the ground
                cat.move_t, cat.emit = 0.0, 0.0
                if random.random() < .3:
                    cat.dir = -cat.dir  # aim the other way now and then
            return
        cat.move_t += dt
        move = self.pack['pets'][cat.kind]['move']
        style = MOVES[move['kind']]
        if MOVE_FIRE[0] <= cat.move_t < MOVE_FIRE[1]:
            cat.emit += dt
            while cat.emit >= style['every']:
                cat.emit -= style['every']
                cat.fx.append(self.shot(cat, move, style))
        if cat.move_t >= MOVE_END:
            cat.move_t, cat.rest = None, random.uniform(1.2, 2.8) * (2 if self.pack['hop'] else 1)

    def hop(self, cat, dt):
        """Slimes get about like slimes between moves: sit a moment, squash, spring forward, land with a squish."""
        right = self.w - self.width(cat.kind)
        if cat.y > 0 or cat.vy > 0:  # in the air: drift forward; step() does the rising and falling
            cat.x = min(max(cat.x + cat.dir * HOP_VX * self.scale * dt, 0), right)
            return
        cat.crouch += dt
        if cat.crouch < cat.wait:
            return
        if cat.x <= 0 or cat.x >= right:  # turn back at the screen edges, and wander now and then
            cat.dir = 1 if cat.x <= 0 else -1
        elif random.random() < .25:
            cat.dir = -cat.dir
        cat.vy, cat.crouch, cat.wait = HOP_V, 0.0, random.uniform(.4, 1)

    def shot(self, cat, move, style):
        """A new particle leaving the pet's mouth; y is screen px above the ground (negative = up)."""
        s, fx, im = self.scale, self.fx_px(), self.image(cat.kind, 'sit', cat.dir < 0)
        mx, my = move['mouth']
        mx = im['width'] - 1 - mx if cat.dir < 0 else mx
        return {'x': cat.x + (mx + .5 + cat.dir) * s, 'y': -(im['height'] - my - .5) * s,
                'vx': cat.dir * random.uniform(*style['vx']) * fx, 'vy': random.uniform(*style['vy']) * fx,
                'ay': style['ay'] * fx, 'age': 0.0, 'life': style['life'], 'kind': move['kind'],
                'splash': style.get('splash', False), 'small': False}

    def fx_px(self):
        return max(self.scale, self.ui)

    def fly(self, cat, dt):
        """Move the particles; water that lands splashes into two small drops."""
        alive = []
        for p in cat.fx:
            p['age'] += dt
            p['vy'] += p['ay'] * dt
            p['x'] += p['vx'] * dt
            p['y'] += p['vy'] * dt
            if p['y'] >= 0 and p['ay'] > 0:
                if p['splash']:
                    alive += [{**p, 'y': -1.0, 'vx': side * random.uniform(15, 30) * self.fx_px(),
                               'vy': -random.uniform(35, 55) * self.fx_px(), 'age': 0.0, 'life': .5,
                               'splash': False, 'small': True} for side in (-1, 1)]
                continue
            if p['age'] < p['life'] and 0 <= p['x'] <= self.w:
                alive.append(p)
        cat.fx = alive

    def crowding(self, cat):
        """Another alarming cat whose bubble overlaps this one's, if any."""
        return next((o for o in self.cats.values() if o is not cat and o.mode in ALARMS
                     and o.box[0] < cat.box[2] and cat.box[0] < o.box[2]), None)

    # --- drawing ---
    def image(self, kind, frame, flip):
        """One pet/frame/direction, built once: the image plus where its head and edges are (sprite px)."""
        if self.game:
            return self.hero_image(kind, frame, flip)
        key = (kind, frame, flip)
        if key not in self.images:
            pet = self.pack['pets'][kind]
            rows = [r[::-1] for r in pet['frames'][frame]] if flip else pet['frames'][frame]
            top = next(i for i, r in enumerate(rows) if r.strip('.'))
            head = [i for i, ch in enumerate(rows[top]) if ch != '.']
            body = [i for r in rows for i, ch in enumerate(r) if ch != '.']
            self.images[key] = {'img': self.art(rows, pet['colors'], self.scale), 'top': top,
                                'head': (head[0] + head[-1] + 1) / 2, 'left': min(body), 'right': max(body) + 1,
                                'width': len(rows[0]), 'height': len(rows)}
        return self.images[key]

    def art(self, rows, colors, size):
        """Pixel rows as a zoomed PhotoImage, built once; colors must be a long-lived dict."""
        key = ('art', tuple(rows), id(colors), size)
        if key not in self.images:
            img = self.tk.PhotoImage(width=len(rows[0]), height=len(rows))
            for y, row in enumerate(rows):
                for x, ch in enumerate(row):
                    if ch != '.':
                        img.put(colors[ch], (x, y))
            self.images[key] = img.zoom(size)
        return self.images[key]

    def pose(self, cat):
        """(frame, lean in sprite px) for this moment."""
        if self.game:
            return self.game_pose(cat)
        if cat.held:  # dangling from your cursor
            return ('stretch' if 'stretch' in self.pack['pets'][cat.kind]['frames'] else 'sit'), 0
        if cat.mode == 'idle':
            return ('sleep2' if int(cat.t / .96) % 2 else 'sleep1'), 0
        if cat.swat > 0:
            return 'walk1', 2                                      # pounce on the yarn
        if cat.moving:
            return ('walk1' if int(cat.t / .24) % 2 else 'walk2'), 0
        if cat.mode != 'working':
            return ('sit2' if cat.y > 0 else 'sit'), 0
        if self.pack['working'] == 'walk':
            return 'walk2', 0                                      # watching the yarn roll
        t = cat.move_t
        if t is None and self.pack['hop']:
            if cat.y > 0:
                return ('stretch' if cat.vy > 0 else 'sit'), 0     # up stretched, down round
            return ('squash' if cat.crouch < .12 or cat.crouch > cat.wait - .15 else 'sit'), 0  # landed / about to spring
        if t is None:
            return ('walk2' if int(cat.t / .4) % 2 else 'walk1'), 0  # a little bounce between moves
        if t < .2:
            return 'squash', -1                                    # wind up
        if t < .3:
            return 'stretch', 2                                    # lunge
        return ('sit', 1) if t < MOVE_FIRE[1] else ('squash', 0)   # fire, then settle

    def draw(self, cat):
        s = self.scale
        frame, lean = self.pose(cat)
        pet, im = self.pack['pets'][cat.kind], self.image(cat.kind, frame, cat.dir < 0)
        x0, base = int(cat.x + lean * cat.dir * s), self.h + self.drop
        ground = int(base - cat.y * s)
        at = (x0 + im.get('dx', 0), ground + im.get('dy', 0))  # a hero's frame has room around its body
        if cat.item is None:
            cat.item = self.canvas.create_image(*at, image=im['img'], anchor=im.get('anchor', 'sw'), tags=(cat.tag,))
        else:
            self.canvas.coords(cat.item, *at)
            if cat.shown is not im['img']:
                self.canvas.itemconfig(cat.item, image=im['img'])
        cat.shown = im['img']
        for p in cat.fx:
            img = self.art(self.particle_art(p), PARTICLE_COLORS, self.fx_px())
            self.canvas.create_image(int(p['x']), int(base + p['y']), image=img, tags=('fx',))
        if cat.ball:
            yarn = YARN[int(cat.ball['roll'] / (4 * self.ui)) % len(YARN)]
            self.canvas.create_image(int(cat.ball['x']), int(base - cat.ball['y']), anchor='s',
                                     image=self.art(yarn, YARN_COLORS, self.ui), tags=('fx',))
        top, mid = ground - (im['height'] - im['top']) * s, x0 + int(im['head'] * s)
        left, right = x0 + im['left'] * s, x0 + im['right'] * s
        box = self.decor(cat, pet, mid, top)
        if self.game:
            self.draw_battle(cat, base)
            self.game_extras(cat, base, left, right, top, box)
        if cat.mode == 'done':
            self.sparkles(cat, left, right, top)
        elif cat.mode == 'idle':
            self.zzz(cat, box[2], box[3])
        cat.box = (min(left, box[0]), box[1], max(right, box[2]), ground)

    def decor(self, cat, pet, mid, top):
        """The bubble or name plate over a pet: built when its words change, otherwise only moved."""
        lang = self.settings['lang']
        text, name = TEXT[lang], Path(cat.rec.get('cwd') or '?').name
        click = text['click'].format(pet=tr(pet['call'], lang))
        if cat.mode == 'done':
            want = ('done', text['done'].format(name=name), cat.rec.get('ask') or click)
        elif cat.mode == 'waiting':
            detail = cat.rec.get('detail')
            line = {'AskUserQuestion': 'ask_q', 'ExitPlanMode': 'ask_plan'}.get(detail, 'ask_tool' if detail else 'ask_any')
            want = ('waiting', text[line].format(name=name, tool=detail), cat.rec.get('ask') or click)
        else:
            want = ('tag', f'{name} · Lv {cat.level}', cat.bar, cat.tier) if self.game else ('tag', name)
        bottom = top if want[0] != 'tag' else top - self.ui
        d, key = cat.decor, (*want, cat.kind)
        if d and d['key'] == key:
            dx, dy = self.card_x(mid, d['box'][2] - d['box'][0]) - d['box'][0], bottom - d['bottom']
            if dx or dy:
                self.canvas.move(d['tag'], dx, dy)
                d['box'], d['bottom'] = (d['box'][0] + dx, d['box'][1] + dy, d['box'][2] + dx, d['box'][3] + dy), bottom
            return d['box']
        tag = f'decor{id(cat)}'
        self.canvas.delete(tag)
        before = set(self.canvas.find_all())
        box = self.tag(mid, bottom, want[1], pet, *want[2:]) if want[0] == 'tag' else self.bubble(mid, bottom, *want)
        for item in set(self.canvas.find_all()) - before:
            self.canvas.addtag_withtag(tag, item)
            self.canvas.addtag_withtag(cat.tag, item)
        cat.decor = {'key': key, 'tag': tag, 'box': box, 'bottom': bottom}
        return box

    @staticmethod
    def particle_art(p):
        frames = PARTICLES[p['kind']]
        if p['small'] or p['age'] > p['life'] * .7:
            return frames[-1]                                       # dying ember / splash bit
        return frames[int(p['age'] / .08) % (len(frames) - 1)]      # flicker through the big frames

    def pixels(self, x, y, rows, colors, size=None, tags=()):
        self.canvas.create_image(x, y, image=self.art(rows, colors, size or self.ui), anchor='nw', tags=tags)

    def card(self, width, height, border, tail=None, paper=PAPER):
        """A pixel-rounded card with a hard drop shadow (and a speech tail at x=tail), as one cached image."""
        key = ('card', width, height, border, tail, paper)
        if key not in self.images:
            s = self.ui
            img = self.tk.PhotoImage(width=width + s, height=height + 3 * s)

            def fill(color, x0, y0, x1, y1):
                img.put(color, to=(x0, y0, x1, y1))
            fill(SHADOW, width, 2 * s, width + s, height)          # shadow, corners left out
            fill(SHADOW, 2 * s, height, width, height + s)
            fill(border, s, 0, width - s, height)                  # border, corners left out
            fill(border, 0, s, width, height - s)
            fill(paper, 2 * s, s, width - 2 * s, height - s)       # paper; its corners stay border
            fill(paper, s, 2 * s, width - s, height - 2 * s)
            if tail is not None:                                   # stepped tail pointing down
                fill(border, tail - 2 * s, height - s, tail + 2 * s, height + s)
                fill(PAPER, tail - s, height - s, tail + s, height + s)
                fill(border, tail - s, height + s, tail + s, height + 2 * s)
            self.images[key] = img
        return self.images[key]

    def text(self, value, font, fill):
        """Create text at the origin; returns (id, width, height) so callers can lay it out."""
        item = self.canvas.create_text(0, 0, text=value, font=font, fill=fill, anchor='nw')
        x0, y0, x1, y1 = self.canvas.bbox(item)
        return item, x1 - x0, y1 - y0

    def card_x(self, cx, width):
        return min(max(cx - width // 2, self.ui), self.w - width - 2 * self.ui)

    def bubble(self, cx, bottom, kind, title, sub):
        """Speech bubble whose pixel tail points down at (cx, bottom); returns its bbox."""
        c, s, color = self.canvas, self.ui, ALARM_COLORS[kind]
        t1, w1, h1 = self.text(title, FONT_TITLE, INK)
        t2, w2, h2 = self.text(sub, FONT_SUB, MUTED)
        icon, pad = 7 * s, 3 * s
        width, height = pad + icon + 2 * s + max(w1, w2) + pad, max(icon, h1 + h2) + 2 * pad
        x0 = self.card_x(cx, width)
        y1 = bottom - 3 * s
        y0 = y1 - height
        tail = min(max(cx - x0, 3 * s), width - 3 * s)  # the tail stays under the card
        c.create_image(x0, y0, image=self.card(width, height, color, tail), anchor='nw')
        self.pixels(x0 + pad, y0 + (height - icon) // 2, ICONS[kind], ICON_COLORS[kind])
        text_y = y0 + (height - h1 - h2) // 2
        c.move(t1, x0 + pad + icon + 2 * s, text_y)
        c.move(t2, x0 + pad + icon + 2 * s, text_y + h1)
        c.tag_raise(t1)
        c.tag_raise(t2)
        return x0, y0, x0 + width, y1 + 2 * s

    def tag(self, cx, bottom, name, pet, bar=None, tier=0):
        """Little name plate: a tiny picture of this pet and the project folder. A hero's also has an experience
        bar along the bottom (bar in 20ths) and a bronze, silver or gold rim for its tier."""
        c, s = self.canvas, self.ui
        face, px = pet['icon'], self.dpi * (2 if len(pet['icon'][0]) < 10 else 1)
        label, w, h = self.text(name, FONT_TAG, INK)
        face_w, face_h = len(face[0]) * px, len(face) * px
        under = 2 * s if bar is not None else 0
        width, height = 3 * s + face_w + 2 * s + w + 3 * s, max(h, face_h) + 2 * s + under
        x0, y0 = self.card_x(cx, width), bottom - height
        rim = TIER_COLORS[tier] or pet['colors'].get('o', INK)
        c.create_image(x0, y0, image=self.card(width, height, rim), anchor='nw')
        self.pixels(x0 + 3 * s, y0 + (height - under - face_h) // 2, face, pet['colors'], px)
        c.move(label, x0 + 3 * s + face_w + 2 * s, y0 + (height - under - h) // 2)
        c.tag_raise(label)
        if bar is not None:
            left, right, y = x0 + 3 * s, x0 + width - 3 * s, y0 + height - 3 * s
            c.create_rectangle(left, y, right, y + s, fill=CHIP_LINE, width=0)
            c.create_rectangle(left, y, left + (right - left) * bar // 20, y + s, fill=XP_COLOR, width=0)
        return x0, y0, x0 + width, bottom

    def zzz(self, cat, x, y):
        """Two z's drifting up and right from (x, y), beside the name plate."""
        s, phase = self.ui, int(cat.t / .24) % 12
        for art, offset in ZZZ:
            p = (phase + offset) % 12
            self.pixels(x + (1 + p // 2) * s, y - (p + 6) * s, art, FX_COLORS, tags=('fx',))

    def sparkles(self, cat, left, right, top):
        """Twinkling stars just outside the pet's outline, near its head."""
        s = self.ui
        for i, (x, dy) in enumerate(((left - 6 * s, 3), (right + s, 0), (right, 12), (left - 5 * s, 14))):
            phase = (int(cat.t / .32) + i * 2) % 6
            if phase < 4:
                art = SPARKLE if phase in (1, 2) else TWINKLE
                self.pixels(x, top + dy * s, art, FX_COLORS, tags=('fx',))

    # --- mouse: click a pet to open its VS Code window, or drag it somewhere else ---
    def pet_at(self, x, y):
        return next((sid for sid, c in self.cats.items() if c.box[0] <= x <= c.box[2] and c.box[1] <= y <= c.box[3]),
                    None)

    def on_press(self, event):
        if self.menu_press(event):
            return
        sid = self.pet_at(event.x, event.y)
        if sid:
            cat = self.cats[sid]
            self.drag = {'sid': sid, 'dx': cat.x - event.x, 'y': event.y, 'cat_y': cat.y, 'moved': False}

    def on_drag(self, event):
        d = self.drag
        cat = self.cats.get(d['sid']) if d else None
        if cat is None or not d['moved'] and abs(event.x + d['dx'] - cat.x) + abs(event.y - d['y']) < 5:
            return  # a wobble is still a click
        d['moved'], cat.held, cat.vy, cat.move_t, cat.swat = True, True, 0.0, None, 0.0
        tall = self.image(cat.kind, 'sit', False)['height']
        cat.x = min(max(event.x + d['dx'], 0), self.w - self.width(cat.kind))
        cat.y = min(max(d['cat_y'] + (d['y'] - event.y) / self.scale, 0), self.h / self.scale - tall)
        self.canvas.config(cursor='fleur')

    def on_release(self, event):
        d, self.drag = self.drag, None
        cat = self.cats.get(d['sid']) if d else None
        self.canvas.config(cursor='')
        if cat is None:
            return
        if d['moved']:
            cat.held, cat.home, cat.goal = False, None, None  # let go: it drops back onto the taskbar right there
        else:
            self.acked[d['sid']] = cat.rec.get('ts', 0)
            self.focus_vscode(cat.rec.get('cwd', ''))


def run():
    import ctypes
    import socket
    guard = socket.socket()  # single instance: the second pet can't bind
    try:
        guard.bind(('127.0.0.1', 47391))
    except OSError:
        sys.exit('Claude Pet is already running.')
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp pixels + real coordinates at 125%/150%
    except (AttributeError, OSError):
        pass
    ctypes.windll.winmm.timeBeginPeriod(1)  # 1 ms timers: a frame every 33 ms, not a 31/47 ms judder
    pet.STATE_DIR.mkdir(exist_ok=True)
    PetApp()
