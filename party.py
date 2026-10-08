"""Subagents as companions. While Claude runs subagents for a session, small pets come out beside its pet, one per
agent (three at most, then a "+2"), in a puff of sparkles, and puff away when their agent is done. In Game mode
they are the Critters slimes: they hop along with the hero, and each one's agent's tool calls are bugs of its own,
which it shoots its moves at (the hero takes over any left when the agent is done). In Chill mode they are little
ones of the pet's own pack. Mixed into PetApp.

Positions are screen px; a companion's x is its left edge and its y (and speeds) are its own sprite px.
"""
import random
import time
import zlib
from collections import Counter

from look import FONT_TAG, FX_COLORS, INK, PAPER, TEXT
from sprites import PARTICLE_COLORS, PARTICLES, SPARKLE, TWINKLE, packs

MAX_SHOWN = 3
POOF_SECS = .4               # the puff a companion arrives and leaves in
HOP_UP, FALL = 22.0, 60.0    # a hop: sprite px per second up, and per second squared down
HOP_DRIFT = 26.0             # sprite px per second toward its spot while in the air
WALK = 34.0                  # sprite px per second, for companions that walk (cats)
SHOT_SPEED = 120             # ui px per second
COOLDOWN = (1.0, 1.8)        # seconds between a companion's shots
RANGE = 150                  # ui px: how far away a bug can be for a companion to shoot at it
MATE_QUEUE, MATE_ON_SCREEN = 6, 2   # a companion's own bugs: waiting, and out at once
SPAWN_GAP = .6               # seconds between a companion's bugs coming out
FRESH_SECS = 10              # an agent younger than this when its companion comes out: all its tool calls count
RAYS = ((1, 0), (-1, 0), (.6, -.8), (-.6, -.8), (.6, .8), (-.6, .8))


class PartyMixin:
    """Uses PetApp's pack, cats (each with .agents from pet.load_agents and its .party), canvas, images, scale, ui,
    dpi, width(), art(), pixels(), fx_px(); in Game mode, damage() and spawn_bug()."""

    def party_source(self):
        """(pack, zoom) the companions come from, or (None, zoom) when there is none."""
        if not self.game:
            return self.pack, max(self.dpi, self.scale - self.dpi)  # a size smaller than the pet itself
        if not hasattr(self, 'critters'):
            self.critters = packs().get('critters')  # loaded once: the image cache keys on its colour dicts
        return self.critters, 1.5 * self.dpi  # smaller than the bugs, bigger than a kitten

    def mini_art(self, rows, colors, z):
        """art() at a zoom that may be half a step: 1.5x is zoom 3, then every other pixel."""
        if z == int(z):
            return self.art(rows, colors, int(z))
        key = ('half', tuple(rows), id(colors), z)
        if key not in self.images:
            self.images[key] = self.art(rows, colors, int(z * 2)).subsample(2)
        return self.images[key]

    def mate_spot(self, cat, agent):
        """(center x, width) of an agent's companion while it is out; None for no agent, or one gone."""
        mate = cat.party.get(agent) if agent is not None else None
        pack, z = self.party_source()
        if mate is None or mate['gone'] is not None or pack is None:
            return None
        mw, _ = self.mate_size(pack, mate['kind'], z)
        return mate['x'] + mw / 2, mw

    def party_step(self, cat, dt):
        pack, z = self.party_source()
        if pack is None:
            cat.party = {}
            return
        shown = cat.agents[:MAX_SHOWN]
        tools = {}
        for slot, (started, agent, kind, calls) in enumerate(shown):
            fresh = started > time.time() - FRESH_SECS  # a new agent's first calls are bugs; an old one's are history
            cat.party.setdefault(agent, self.summon(cat, pack, kind, z, 0 if fresh else calls))['slot'] = slot
            tools[agent] = calls
        live = {agent for _, agent, *_ in shown}
        for agent, mate in list(cat.party.items()):
            if agent not in live and mate['gone'] is None:
                mate['gone'] = 0.0  # its agent is done: off in a puff
            if mate['gone'] is not None:
                mate['gone'] += dt
                if mate['gone'] >= POOF_SECS:
                    del cat.party[agent]
                continue
            mate['born'] += dt
            self.follow(cat, mate, pack, z, dt)
            if self.game and cat.mode == 'working':  # like the hero, it holds still while Claude waits for you
                self.mate_bugs(cat, agent, mate, tools[agent], dt)
                self.mate_attack(cat, agent, mate, pack, z, dt)

    def summon(self, cat, pack, kind, z, calls):
        """A new companion at the pet's side; calls: its agent's tool calls so far that are not bugs. One agent type
        always brings the same one (another pet than the pet itself, when the pack has others)."""
        pets = range(len(pack['pets']))
        choices = [k for k in pets if self.game or k != cat.kind] or list(pets)
        pick = choices[zlib.crc32(kind.encode('utf-8')) % len(choices)]
        mw, _ = self.mate_size(pack, pick, z)
        return {'kind': pick, 'x': cat.x + self.width(cat.kind) / 2 - mw / 2, 'y': 0.0, 'vy': 0.0, 'dir': cat.dir,
                'slot': 0, 'crouch': 0.0, 'wait': random.uniform(.2, .6), 'moving': False, 'born': 0.0, 'gone': None,
                'cool': random.uniform(*COOLDOWN), 'cast': 9.0, 'shots': [], 'tools': calls, 'queue': 0, 'spawn': 0.0}

    @staticmethod
    def mate_size(pack, kind, z):
        rows = pack['pets'][kind]['frames']['sit']
        return len(rows[0]) * z, len(rows) * z

    def follow(self, cat, mate, pack, z, dt):
        """Keep to its spot: left of the pet, right of it, then further left. Slimes hop there (and bounce on the
        spot now and then), cats trot."""
        u, w = self.ui, self.width(cat.kind)
        mw, _ = self.mate_size(pack, mate['kind'], z)
        side = -1 if mate['slot'] % 2 == 0 else 1
        reach = w / 2 + mw / 2 + 3 * u + mate['slot'] // 2 * (mw + 2 * u)
        gap = min(max(cat.x + w / 2 + side * reach - mw / 2, 0), self.w - mw) - mate['x']
        far = abs(gap) > 2 * u
        if far:
            mate['dir'] = 1 if gap > 0 else -1
        elif mate['cast'] > .5:
            mate['dir'] = cat.dir
        mate['moving'] = False
        if mate['y'] > 0 or mate['vy'] > 0:  # in the air: drift toward the spot, rise, fall
            mate['x'] += min(HOP_DRIFT * z * dt, abs(gap)) * (1 if gap > 0 else -1)
            mate['y'] += mate['vy'] * dt
            mate['vy'] -= FALL * dt
            if mate['y'] <= 0:
                mate['y'] = mate['vy'] = mate['crouch'] = 0.0
        elif pack['hop']:
            mate['crouch'] += dt
            if mate['crouch'] >= mate['wait']:
                mate['vy'] = HOP_UP if far else HOP_UP * .45
                mate['wait'] = random.uniform(.3, .7) if far else random.uniform(1.2, 2.6)
        elif far:
            mate['x'] += min(WALK * z * dt, abs(gap)) * (1 if gap > 0 else -1)
            mate['moving'] = True

    def mate_bugs(self, cat, agent, mate, calls, dt):
        """Its agent's new tool calls join its queue as bugs, which come out past it, two at a time."""
        mate['queue'] = min(mate['queue'] + max(0, calls - mate['tools']), MATE_QUEUE)
        mate['tools'], mate['spawn'] = calls, max(0.0, mate['spawn'] - dt)
        out = sum(b['hit'] is None and b.get('owner') == agent for b in cat.bugs)
        if mate['queue'] and mate['spawn'] == 0 and out < MATE_ON_SCREEN and self.sprites.cast['bugs']:
            self.spawn_bug(cat, agent)
            mate['queue'], mate['spawn'] = mate['queue'] - 1, SPAWN_GAP

    def mate_attack(self, cat, agent, mate, pack, z, dt):
        """On the ground with one of its bugs in range, a slime uses its move on it every second or so; the shot
        lands like one of the hero's blows."""
        u = self.ui
        mw, mh = self.mate_size(pack, mate['kind'], z)
        mate['cool'] -= dt
        mate['cast'] += dt
        center = mate['x'] + mw / 2
        live = [b for b in cat.bugs if b['hit'] is None and b.get('owner') == agent]
        if mate['cool'] <= 0 and mate['y'] == 0 and live:
            bug = min(live, key=lambda b: abs(b['x'] - center))
            if abs(bug['x'] - center) <= RANGE * u:
                mate['dir'] = 1 if bug['x'] > center else -1
                mate['cool'], mate['cast'] = random.uniform(*COOLDOWN), 0.0
                mate['shots'].append({'x': center + mate['dir'] * mw / 2, 'h': mh * .5, 'dir': mate['dir'], 'age': 0.0})
        flying = []
        for shot in mate['shots']:
            shot['x'] += shot['dir'] * SHOT_SPEED * u * dt
            shot['age'] += dt
            bug = next((b for b in live if b['hit'] is None and abs(b['x'] - shot['x']) < b['w'] / 2), None)
            if bug:
                self.damage(cat, bug)
            elif 0 <= shot['x'] <= self.w and shot['age'] < 2:
                flying.append(shot)
        mate['shots'] = flying

    def mate_frame(self, cat, mate, pack):
        frames = pack['pets'][mate['kind']]['frames']
        if cat.mode == 'idle':
            return 'sleep2' if int(cat.t / .96) % 2 else 'sleep1'
        if mate['cast'] < .25 or mate['vy'] > 0:  # using its move, or springing up
            return 'stretch' if 'stretch' in frames else 'sit2'
        if mate['moving']:
            return 'walk1' if int(cat.t / .2) % 2 else 'walk2'
        if pack['hop'] and mate['y'] == 0 and mate['crouch'] < .1:
            return 'squash' if 'squash' in frames else 'sit'  # just landed
        return 'sit'

    # --- drawing (all tag 'fx': redrawn every frame) ---
    def draw_party(self, cat, base):
        pack, z = self.party_source()
        if pack is None or not cat.party:
            return
        for mate in cat.party.values():
            pet = pack['pets'][mate['kind']]
            mw, mh = self.mate_size(pack, mate['kind'], z)
            ground = base - mate['y'] * z
            if mate['gone'] is None:
                rows = pet['frames'][self.mate_frame(cat, mate, pack)]
                rows = [r[::-1] for r in rows] if mate['dir'] < 0 else rows
                self.canvas.create_image(int(mate['x']), int(ground), image=self.mini_art(rows, pet['colors'], z),
                                         anchor='sw', tags=('fx',))
            age = mate['born'] if mate['gone'] is None else mate['gone']
            if age < POOF_SECS:
                self.poof(mate['x'] + mw / 2, ground - mh / 2, age / POOF_SECS)
            art, size = PARTICLES[pet['move']['kind']] if pet.get('move') else None, self.fx_px()
            for shot in mate['shots'] if art else ():
                frame = art[int(shot['age'] / .08) % (len(art) - 1)]
                self.pixels(int(shot['x'] - len(frame[0]) * size / 2), int(base - shot['h']), frame, PARTICLE_COLORS,
                            size, tags=('fx',))
        if len(cat.agents) > MAX_SHOWN:
            self.more_badge(cat, pack, z, base, len(cat.agents) - MAX_SHOWN)

    def poof(self, x, y, k):
        """Sparkles flying out from (x, y) as k goes from 0 to 1."""
        s, r = self.ui, (4 + 10 * k) * self.ui
        for n, (dx, dy) in enumerate(RAYS):
            art = SPARKLE if (n + int(k * 6)) % 2 else TWINKLE
            self.pixels(int(x + dx * r - len(art[0]) * s / 2), int(y + dy * r - len(art) * s / 2), art, FX_COLORS,
                        tags=('fx',))

    def more_badge(self, cat, pack, z, base, extra):
        """'+2' over the last companion shown: more agents run than come out."""
        last = max(cat.party.values(), key=lambda m: m['slot'])
        mw, mh = self.mate_size(pack, last['kind'], z)
        x, y = last['x'] + mw / 2, base - last['y'] * z - mh - 5 * self.ui
        for dx, dy in ((-1, -1), (1, 1)):
            self.canvas.create_text(x + dx, y + dy, text=f'+{extra}', font=FONT_TAG, fill=INK, tags=('fx',))
        self.canvas.create_text(x, y, text=f'+{extra}', font=FONT_TAG, fill=PAPER, tags=('fx',))

    def party_line(self, cat, lang):
        """The hover card's line about them: 'Agents at work: Explore ×2, code-reviewer'."""
        kinds = Counter(agent[2] for agent in cat.agents)
        names = ', '.join(f'{kind[:18]} ×{n}' if n > 1 else kind[:18] for kind, n in kinds.most_common(3))
        return TEXT[lang]['agents'].format(kinds=names + (', …' if len(kinds) > 3 else ''))
