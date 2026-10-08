"""Game mode ("Bắt bug"): every Claude session is a hero drawn by an artist (cast.py). Its bugs come from Claude's
tool calls, a boss shows up when Claude is done, and it levels up on the tokens Claude writes for its project
(xp.py). Mixed into PetApp; Chill mode never gets here.

Positions are screen px, as in app.py; a hero's x is the left edge of its body.
"""
import random
import sys
import threading
import time

import cast
import pet
import sounds
import xp
from look import (CLASS_ICON_COLORS, CLASS_ICONS, FONT_TAG, FONT_TITLE, FX_COLORS, INK, PAPER, TEXT, TIER_COLORS,
                  XP_COLOR)
from sprites import SPARKLE, TWINKLE

SCAN_SECS = 5                 # how often Claude's transcripts are read for new tokens (for levels)
ALL_EVERY = 6                 # scans between reads for the all-time totals on the hover cards
FLASH_SECS = 2.0              # how long "LEVEL UP!" shows
MAX_ON_SCREEN, MAX_QUEUE = 3, 20
SPAWN_GAP = .45               # seconds between bugs coming out of the queue
SPAWN_AT = (55, 95)           # ui px in front of the hero
MATE_SPAWN_AT = (30, 55)      # ui px past a companion, for its own bugs
BUG_SPEED = 30                # ui px per second
REACH = {'slash': 14, 'punch': 22, 'spell': 80, 'arrow': 90}   # ui px from the hero's side to a bug it can hit
SHOT_SPEED = {'arrow': 150, 'spell': 110}                       # ui px per second, for the attacks that fly
BURST_LIFE = {'spell': .35, 'arrow': .35, 'spark': .16, 'big': .45, 'pop': .8}  # seconds each effect lasts
CRIT_CHANCE = .15             # a blow's number shows big and gold now and then (it's only for show)
SHAKE_SECS = .35              # the boss's last blow shakes it and the hero
ORB = ('#5b2aa8', '#a46bff', '#e6d4ff')                         # glow, orb, heart
SPARK = ('#ffffff', '#ffd23f')                                   # a blow's spark, a crit's number
RAYS = ((1, 0), (0, 1), (-1, 0), (0, -1), (.7, .7), (-.7, .7), (.7, -.7), (-.7, -.7))
BOSS_AT = 45                  # ui px from the hero where the boss turns up
BOSS_SPEED = 26               # ui px per second: it marches, it does not scuttle
BUG_HP, BOSS_HP = (1, 2, 2, 3), 3   # blows it takes (a bug's is picked from these; a boss's, plus the hero's tier)
BOSS_ANIMS = ('idle', 'run', 'hurt', 'death')   # a boss never swings back, so its attack frames never show
KNOCKBACK = 12                # ui px a blow sends a bug sliding back (half that for the boss)
MELEE = ('slash', 'punch')    # these run up to a bug; the others shoot from where they stand
CHARGE_SPEED, PATROL_SPEED = 40, 14   # ui px per second
PATROL_SPAN = 40              # ui px either side of where a hero was put
CHASE_SPAN = 60               # how far from there it runs after a bug, so heroes keep to their own ground


def ints(found):
    """{name: count} from a file someone could have edited: anything but whole numbers is dropped."""
    return {k: v for k, v in found.items() if isinstance(v, int)} if isinstance(found, dict) else {}


def tallies(found):
    """{project: {'bosses': n, 'bugs': n}} from game.json, likewise."""
    return {p: ints(c) for p, c in found.items() if isinstance(c, dict)} if isinstance(found, dict) else {}


class GameMixin:
    """Uses PetApp's settings, pack, cats, canvas, drop, ui/dpi, project(), card(), card_x(), text(), pixels(), report()."""

    # --- the cast ---
    @property
    def game(self):
        return self.pack['working'] == 'game'

    def hero_pack(self, data, base):
        """The cast's heroes as a pack the rest of the window can use (name plates, swapping, picks)."""
        self.sprites = cast.Sprites(self.tk, data, base, self.dpi)
        pets = [{'name': tr_en(h['name']), 'label': h['name'], 'call': h['name'], 'attack': h.get('attack', 'slash'),
                 'icon': CLASS_ICONS.get(h.get('attack'), CLASS_ICONS['slash']), 'colors': CLASS_ICON_COLORS}
                for h in data['heroes']]
        return {'name': {'en': 'Heroes', 'vi': 'Anh hùng'}, 'scale': 1, 'working': 'game', 'hop': False, 'pets': pets}

    def hero_image(self, kind, frame, flip):
        """What app.draw needs for a hero frame named 'anim:i' (anything else means standing still)."""
        anim, _, i = frame.partition(':')
        anim = anim if anim in self.sprites.cast['heroes'][kind]['anims'] else 'idle'
        f = self.sprites.frame('heroes', kind, anim, int(i or 0), -1 if flip else 1)
        return {'img': f['img'], 'anchor': 'nw', 'dx': f['dx'], 'dy': f['dy'], 'top': 0, 'height': f['h'],
                'head': f['w'] / 2, 'left': 0, 'right': f['w'], 'width': f['w']}

    # --- tokens and tallies, in game.json ---
    def start_counting(self):
        """Read Claude's transcripts for new tokens on a thread, in either mode: since Game mode was first on, for
        levels (only while it is on), and all of them, for the hover cards (one long first read, then a look every
        half minute). The thread also saves the bosses and bugs beaten. The window only reads self.xp,
        self.written (None while the first read runs) and self.kills, all swapped for fresh dicts, never changed
        in place."""
        if getattr(self, 'counter', None):
            return
        path = pet.STATE_DIR / pet.GAME
        saved = pet.read_json(path)
        saved = saved if isinstance(saved, dict) else {}
        every = saved.get('all') if isinstance(saved.get('all'), dict) else {}
        every = every if isinstance(every.get('files'), dict) else {'files': {}}  # no offsets: from the start
        self.xp, self.kills = ints(saved.get('tokens')), tallies(saved.get('kills'))
        self.written = ints(every['tokens']) if isinstance(every.get('tokens'), dict) else None

        def loop():
            store, total, last, rounds = saved, every, saved, 0
            while True:
                try:
                    if (self.settings or {}).get('mode') == 'game':
                        store = xp.scan(store)
                        self.xp = store['tokens']
                    if rounds % ALL_EVERY == 0:
                        total = xp.scan(total)
                        self.written = total['tokens']
                    rounds += 1
                    out = {**{k: store[k] for k in ('tokens', 'files', 'recent') if k in store},
                           'all': total, 'kills': self.kills}
                    if out != last:
                        pet.write_json(path, out)
                        last = out
                except Exception:  # a bad scan waits for the next round; this thread must never die
                    self.report(*sys.exc_info())
                time.sleep(SCAN_SECS)
        self.counter = threading.Thread(target=loop, daemon=True)
        self.counter.start()

    def tally(self, cat, what):
        """One more of 'bosses' or 'bugs' beaten for this hero's project."""
        project = self.project(cat.rec)
        mine = self.kills.get(project, {})
        self.kills = {**self.kills, project: {**mine, what: mine.get(what, 0) + 1}}

    def hero_label(self, cat, name):
        """A hero's name plate: its project, level and, once it has some, the bosses it has beaten."""
        bosses = self.kills.get(self.project(cat.rec), {}).get('bosses', 0)
        return f'{name} · Lv {cat.level}' + (f' · ☠ {bosses}' if bosses else '')

    # --- each frame ---
    def game_step(self, cat, dt):
        """A hero's level and timers, then its fight: bugs while Claude works, the boss when it's done, a standstill
        while it waits for you, nothing while it sleeps."""
        tokens = self.xp.get(self.project(cat.rec), 0)
        level = xp.level_of(tokens)
        if cat.level is not None and level > cat.level:
            cat.flash = FLASH_SECS
            if self.settings['sound'] and self.drop < 1:
                sounds.play('levelup', pet.STATE_DIR)
        cat.level, cat.tier, cat.bar = level, xp.tier_of(level), int(xp.progress(tokens) * 20)
        cat.flash, cat.shake = max(0.0, cat.flash - dt), max(0.0, cat.shake - dt)
        self.count_tools(cat)
        for bug in cat.bugs:
            bug['t'] += dt
        cat.bugs = [b for b in cat.bugs if b['hit'] is None or b['t'] - b['hit'] < self.anim_secs('bugs', b['kind'], 'death')]
        if cat.mode != 'done':  # a new prompt before the boss went down: that fight is over
            cat.boss = None
        if cat.mode == 'idle':
            cat.bugs, cat.shots, cat.queue, cat.boss, cat.swing = [], [], 0, None, 0.0
        elif cat.mode == 'done':
            self.finish(cat, dt)
        elif cat.mode == 'working':
            self.fight(cat, dt)
        self.fly_shots(cat, dt)

    def anim_secs(self, group, index, anim):
        n, fps = self.sprites.frames_in(group, index, anim)
        return n / fps

    def count_tools(self, cat):
        """New tool calls since the last look join the queue as bugs; the first look (or a count that went down:
        another session file) only sets the mark."""
        tools = cat.rec.get('tools') if isinstance(cat.rec.get('tools'), int) else 0
        if cat.tools is not None and tools > cat.tools:
            cat.queue = min(cat.queue + tools - cat.tools, MAX_QUEUE)
        cat.tools = tools

    def start_swing(self, cat):
        """A blow, picked at random from the hero's attacks so it doesn't repeat itself."""
        cat.move = random.choice(self.sprites.attacks('heroes', cat.kind))
        cat.swing = self.anim_secs('heroes', cat.kind, cat.move)

    def swing(self, cat, dt):
        """Advance a blow already started; True on a frame where it lands (a combo lands several times)."""
        if cat.swing <= 0:
            return False
        n, fps = self.sprites.frames_in('heroes', cat.kind, cat.move)
        before = n / fps - cat.swing
        cat.swing = max(0.0, cat.swing - dt)
        after = n / fps - cat.swing
        return any(before < (f + .5) / fps <= after for f in self.sprites.hits('heroes', cat.kind, cat.move))

    def fight(self, cat, dt):
        u, w = self.ui, self.width(cat.kind)
        attack, center = self.pack['pets'][cat.kind]['attack'], cat.x + w / 2
        cat.spawn = max(0.0, cat.spawn - dt)
        live = [b for b in cat.bugs if b['hit'] is None]
        mine = [b for b in live if self.mate_spot(cat, b.get('owner')) is None]  # companions see to their own
        if cat.queue and cat.spawn == 0 and len(mine) < MAX_ON_SCREEN and self.sprites.cast['bugs']:
            self.spawn_bug(cat)
        for bug in live:
            if bug['stun'] > 0:   # reeling from a blow: sliding back, no crawling, no biting
                bug['stun'] = max(0.0, bug['stun'] - dt)
                bug['x'] = min(max(bug['x'] + bug['push'] * dt, bug['w']), self.w - bug['w'])
                bug['near'] = False
                continue
            foe, foe_w = self.foe_of(cat, bug)
            gap = bug['x'] - foe
            bug['near'] = abs(gap) <= foe_w / 2 + bug['w'] / 2 + 2 * u
            if not bug['near']:   # crawl up to the hero, or to its companion
                bug['x'] -= (1 if gap > 0 else -1) * BUG_SPEED * u * dt
            self.bite(cat, bug, dt)
        live = mine
        cat.ouch = max(0.0, cat.ouch - dt)
        if self.swing(cat, dt):
            self.strike(cat, attack, live)
        elif cat.swing <= 0 and live:
            target = min(live, key=lambda b: abs(b['x'] - center))
            cat.dir = 1 if target['x'] > center else -1
            if abs(target['x'] - center) - w / 2 - target['w'] / 2 <= REACH[attack] * u:
                self.start_swing(cat)
            elif attack in MELEE and cat.ouch <= 0:  # swords and fists go to the bug, within their own ground
                if cat.home is None:
                    cat.home = cat.x
                span = CHASE_SPAN * u
                gap = min(max(target['x'] - center, cat.home - span - cat.x), cat.home + span - cat.x)
                if abs(gap) >= 1:
                    self.walk(cat, gap, CHARGE_SPEED, dt)
        elif cat.swing <= 0:
            self.patrol(cat, dt)
        if live or cat.swing > 0:
            cat.goal = None  # back to strolling from wherever the fight ended

    def foe_of(self, cat, bug):
        """(center x, width) of who a bug goes for: its companion while that is out, otherwise the hero."""
        spot = self.mate_spot(cat, bug.get('owner'))
        if spot:
            return spot
        w = self.width(cat.kind)
        return cat.x + w / 2, w

    def bite(self, cat, bug, dt):
        """A bug at its foe's feet has a go now and then; if that's the hero and it isn't busy swinging, it
        flinches."""
        bug['bite'] = max(0.0, bug.get('bite', 0.0) - dt)
        if not bug['near']:
            return
        bug['next'] = bug.get('next', random.uniform(.5, 1.5)) - dt
        if bug['next'] <= 0:
            bug['next'], bug['bite'] = random.uniform(1.6, 3.2), self.anim_secs('bugs', bug['kind'], 'attack')
            if cat.swing <= 0 and self.mate_spot(cat, bug.get('owner')) is None:
                cat.ouch = self.anim_secs('heroes', cat.kind, 'hurt')

    def walk(self, cat, gap, speed, dt):
        """Step toward a point `gap` px away (sign = side), running."""
        step = min(speed * self.ui * dt, abs(gap))
        cat.dir = 1 if gap > 0 else -1
        cat.x = min(max(cat.x + cat.dir * step, 0), self.w - self.width(cat.kind))
        cat.moving, cat.stride = True, max(.5, speed / CHARGE_SPEED)

    def patrol(self, cat, dt):
        """No bugs yet: stroll a few steps this way and that around where it stands, with pauses, on guard."""
        if cat.home is None:
            cat.home = cat.x
        cat.pause -= dt
        if cat.pause > 0:
            return
        if cat.goal is None:
            span = PATROL_SPAN * self.ui
            cat.goal = min(max(cat.home + random.uniform(-span, span), 0), self.w - self.width(cat.kind))
        gap = cat.goal - cat.x
        if abs(gap) < 2:
            cat.goal, cat.pause = None, random.uniform(1.2, 3.5)
            return
        self.walk(cat, gap, PATROL_SPEED, dt)

    def spawn_bug(self, cat, owner=None):
        """One bug out of a queue: the hero's, a little way in front of it (or behind it, if a wall is in front),
        or one for a companion (owner: its agent), on its far side from the hero."""
        u, w = self.ui, self.width(cat.kind)
        kind = random.randrange(len(self.sprites.cast['bugs']))
        bw = self.sprites.body('bugs', kind)[0]
        spot = self.mate_spot(cat, owner)
        if spot:
            side = 1 if spot[0] >= cat.x + w / 2 else -1
            x = spot[0] + side * (spot[1] / 2 + random.uniform(*MATE_SPAWN_AT) * u)
            x = x if bw <= x <= self.w - bw else spot[0] - side * (spot[1] / 2 + MATE_SPAWN_AT[0] * u)
            cat.bugs.append({'x': min(max(x, bw), self.w - bw), 'kind': kind, 'w': bw, 't': 0.0, 'hit': None,
                             'near': False, 'hp': random.choice(BUG_HP), 'stun': 0.0, 'push': 0.0, 'owner': owner})
            return
        others = [c.x for c in self.cats.values() if c is not cat]
        room_left = cat.x - max([o for o in others if o < cat.x], default=0)
        room_right = min([o for o in others if o > cat.x], default=self.w) - cat.x - w
        side = 1 if room_right >= room_left else -1  # from the emptier side, away from the other heroes
        for _ in range(2):
            x = cat.x + w / 2 + side * (w / 2 + random.uniform(*SPAWN_AT) * u)
            if bw <= x <= self.w - bw:
                break
            side = -side
        cat.bugs.append({'x': min(max(x, bw), self.w - bw), 'kind': kind, 'w': bw, 't': 0.0, 'hit': None,
                         'near': False, 'hp': random.choice(BUG_HP), 'stun': 0.0, 'push': 0.0})
        cat.queue, cat.spawn = cat.queue - 1, SPAWN_GAP

    def strike(self, cat, attack, live):
        """Melee: every bug in reach on the side it faces. Spell: the nearest bug in reach. Arrow: a shot leaves."""
        u, w = self.ui, self.width(cat.kind)
        center = cat.x + w / 2
        ahead = [b for b in live if (b['x'] > center) == (cat.dir > 0)
                 and abs(b['x'] - center) - w / 2 - b['w'] / 2 <= REACH[attack] * u]
        if attack in SHOT_SPEED:  # an arrow, or a magic orb off the staff
            cat.shots.append({'x': center + cat.dir * w / 2, 'dir': cat.dir, 'age': 0.0, 'kind': attack})
        else:
            for bug in ahead:
                self.damage(cat, bug)

    def damage(self, cat, bug):
        """One blow: off comes a hit point, and the bug reels back (its hurt frames, pushed away) or goes down."""
        bug['hp'] -= 1
        self.impact(cat, bug['x'], self.sprites.body('bugs', bug['kind'])[1] * .6)
        if bug['hp'] <= 0:
            bug['hit'] = bug['t']
            self.tally(cat, 'bugs')
            return
        side = 1 if bug['x'] > self.foe_of(cat, bug)[0] else -1  # away from whoever hit it
        bug['stun'] = self.anim_secs('bugs', bug['kind'], 'hurt')
        bug['push'], bug['bite'] = side * KNOCKBACK * self.ui / bug['stun'], 0.0

    def fly_shots(self, cat, dt):
        u, flying = self.ui, []
        for shot in cat.shots:
            shot['x'] += shot['dir'] * SHOT_SPEED[shot['kind']] * u * dt
            shot['age'] += dt
            bug = next((b for b in cat.bugs if b['hit'] is None and abs(b['x'] - shot['x']) < b['w'] / 2
                        and self.mate_spot(cat, b.get('owner')) is None), None)  # the hero's own bugs only
            if bug:
                self.damage(cat, bug)
                cat.bursts.append({'x': bug['x'], 't': 0.0, 'kind': shot['kind']})
            elif 0 <= shot['x'] <= self.w and shot['age'] < 2:
                flying.append(shot)
        cat.shots = flying
        cat.bursts = [{**b, 't': b['t'] + dt} for b in cat.bursts if b['t'] + dt < BURST_LIFE[b['kind']]]

    def impact(self, cat, x, height, boss=False, kill=False):
        """What a blow looks like where it lands: a spark, and a number flying up (big and gold on a crit). The
        numbers are only for show; bugs count blows. The boss's last blow gets a big spark and a shake."""
        crit = random.random() < CRIT_CHANCE
        hit = (random.randint(6, 12) + (cat.level or 1) // 3) * (random.choice((2, 3)) if crit else 1) * (3 if boss else 1)
        cat.bursts.append({'x': x, 'h': height, 't': 0.0, 'kind': 'big' if kill else 'spark'})
        cat.bursts.append({'x': x + random.uniform(-4, 4) * self.ui, 'h': height + 6 * self.ui, 't': 0.0, 'kind': 'pop',
                           'text': f'{hit}!' if crit else str(hit), 'crit': crit})
        if kill:
            cat.shake = SHAKE_SECS

    def finish(self, cat, dt):
        """Claude is done: this task's boss walks up beside the hero and is cut down, blow by blow; the rest flee.
        The higher the hero's tier, the more blows it takes and the bigger the bosses that can come."""
        ts = cat.rec.get('ts', 0)
        if cat.beaten == ts:
            return
        cat.bugs, cat.shots, cat.queue = [b for b in cat.bugs if b['hit'] is not None], [], 0  # the rest flee
        if not self.sprites.cast['bosses']:
            cat.beaten = ts
            return
        u, w = self.ui, self.width(cat.kind)
        if cat.boss is None:
            kind = cast.pick_boss(self.sprites.cast['bosses'], cat.tier)
            bw = self.sprites.body('bosses', kind)[0]
            room_right = cat.x + w + BOSS_AT * u + bw <= self.w
            cat.dir = 1 if room_right else -1
            x = cat.x + w + BOSS_AT * u + bw / 2 if room_right else cat.x - BOSS_AT * u - bw / 2
            cat.boss = {'kind': kind, 'x': min(max(x, bw / 2), self.w - bw / 2), 't': 0.0, 'hit': None, 'w': bw,
                        'hp': BOSS_HP + cat.tier, 'max': BOSS_HP + cat.tier, 'stun': 0.0, 'push': 0.0, 'near': False}
        boss, kind = cat.boss, cat.boss['kind']
        boss['t'] += dt
        gap = boss['x'] - (cat.x + w / 2)
        boss['near'] = abs(gap) <= w / 2 + boss['w'] / 2 + 2 * u
        if boss['stun'] > 0:                                             # staggered back by a blow
            boss['stun'] = max(0.0, boss['stun'] - dt)
            boss['x'] = min(max(boss['x'] + boss['push'] * dt, boss['w'] / 2), self.w - boss['w'] / 2)
        elif boss['hit'] is None and not boss['near'] and cat.swing <= 0:
            boss['x'] -= (1 if gap > 0 else -1) * BOSS_SPEED * u * dt   # it marches up to the hero...
        elif boss['hit'] is None and boss['near'] and cat.swing <= 0:
            self.start_swing(cat)                                        # ...who cuts it down, blow by blow
        if self.swing(cat, dt) and boss['hit'] is None and boss['near']:
            boss['hp'] -= 1
            self.impact(cat, boss['x'], self.sprites.body('bosses', kind)[1] * .6, boss=True, kill=boss['hp'] <= 0)
            if boss['hp'] <= 0:
                boss['hit'] = boss['t']
                self.tally(cat, 'bosses')
            else:
                boss['stun'] = self.anim_secs('bosses', kind, 'hurt')
                boss['push'] = (1 if gap > 0 else -1) * KNOCKBACK / 2 * u / boss['stun']
        if boss['hit'] is not None and boss['t'] - boss['hit'] >= self.anim_secs('bosses', kind, 'death') + .4:
            cat.boss, cat.beaten, cat.swing = None, ts, 0.0

    def game_pose(self, cat):
        """(frame 'anim:i', lean) for a hero, jittering for a moment after it beats a boss."""
        frame, lean = self.hero_pose(cat)
        return frame, (random.choice((-2, -1, 1, 2)) * self.dpi if cat.shake > 0 else lean)

    def hero_pose(self, cat):
        def at(anim, t, once=False):
            n, fps = self.sprites.frames_in('heroes', cat.kind, anim)
            i = int(t * fps)
            return f'{anim}:{min(i, n - 1) if once else i % n}', 0
        if cat.held:
            return at('hurt', 0)
        if cat.swing > 0:
            return at(cat.move, self.anim_secs('heroes', cat.kind, cat.move) - cat.swing, once=True)
        if cat.ouch > 0:                                          # a bug got a bite in
            return at('hurt', self.anim_secs('heroes', cat.kind, 'hurt') - cat.ouch, once=True)
        if cat.mode == 'idle':
            return 'idle:0', 0                                    # dozing by the fire
        return at('run', cat.t * cat.stride) if cat.moving else at('idle', cat.t)  # a stroll steps slower

    # --- drawing (all tag 'fx': redrawn every frame) ---
    def draw_battle(self, cat, base):
        c, u = self.canvas, self.ui
        ground = int(base)
        center = cat.x + self.width(cat.kind) / 2
        for bug in cat.bugs:
            if bug['hit'] is not None:
                anim, t = 'death', bug['t'] - bug['hit']
            elif bug['stun'] > 0:
                anim, t = 'hurt', self.anim_secs('bugs', bug['kind'], 'hurt') - bug['stun']
            elif bug.get('bite', 0) > 0:
                anim, t = 'attack', self.anim_secs('bugs', bug['kind'], 'attack') - bug['bite']
            else:
                anim, t = ('idle' if bug['near'] else 'run'), bug['t']
            n, fps = self.sprites.frames_in('bugs', bug['kind'], anim)
            i = min(int(t * fps), n - 1) if anim in ('death', 'attack', 'hurt') else int(t * fps)
            self.put_sprite('bugs', bug['kind'], anim, i, 1 if bug['x'] < self.foe_of(cat, bug)[0] else -1, bug['x'],
                            ground)
        boss = cat.boss
        if boss:
            if boss['hit'] is not None:
                anim, t = 'death', boss['t'] - boss['hit']
            elif boss['stun'] > 0:
                anim, t = 'hurt', self.anim_secs('bosses', boss['kind'], 'hurt') - boss['stun']
            else:
                anim, t = ('idle' if boss['near'] else 'run'), boss['t']
            n, fps = self.sprites.frames_in('bosses', boss['kind'], anim)
            i = min(int(t * fps), n - 1) if anim in ('death', 'hurt') else int(t * fps)
            f = self.put_sprite('bosses', boss['kind'], anim, i, 1 if boss['x'] < center else -1, boss['x'], ground)
            c.tag_lower(f['item'], cat.item)  # the hero's "done!" bubble stays readable over a big boss
            if boss['hit'] is None:  # its life bar, shorter with every blow
                top, half = ground - f['h'] - 3 * u, f['w'] // 2
                left, life = boss['x'] - half, 2 * half * boss['hp'] / boss['max']
                for x0, x1, color in ((left, left + 2 * half, INK), (left, left + life, '#e5484d')):
                    bar = c.create_rectangle(x0, top, x1, top + u, fill=color, width=0, tags=('fx',))
                    c.tag_lower(bar, cat.item)  # under the hero and its bubble, which may reach over the boss
        hand_y = ground - self.sprites.body('heroes', cat.kind)[1] * .55
        for shot in cat.shots:
            x, d = int(shot['x']), shot['dir']
            if shot['kind'] == 'spell':  # a glowing orb with a fading trail
                for k, r in ((3, 1), (2, 1.5), (1, 2)):
                    c.create_oval(x - d * k * 4 * u - r * u, hand_y - r * u, x - d * k * 4 * u + r * u, hand_y + r * u,
                                  fill=ORB[1], outline='', stipple='gray50', tags=('fx',))
                for r, color in ((4, ORB[0]), (3, ORB[1]), (1.5, ORB[2])):
                    c.create_oval(x - r * u, hand_y - r * u, x + r * u, hand_y + r * u, fill=color, outline='',
                                  tags=('fx',))
            else:
                c.create_line(x - d * 7 * u, hand_y, x, hand_y, fill='#7a4a24', width=u, tags=('fx',))
                c.create_line(x, hand_y, x - d * 2 * u, hand_y - u, fill='#e9eef7', width=u, tags=('fx',))
        for burst in cat.bursts:
            if burst['kind'] in SHOT_SPEED:  # where an orb hit: sparks flying out
                spread, y = (2 + burst['t'] / BURST_LIFE[burst['kind']] * 10) * u, hand_y
                for k in range(8):
                    dx, dy = RAYS[k]
                    px, py = burst['x'] + dx * spread, y + dy * spread
                    c.create_rectangle(px - u, py - u, px + u, py + u, fill=ORB[2] if k % 2 else ORB[1], width=0,
                                       tags=('fx',))
            elif burst['kind'] == 'pop':
                self.hit_number(burst, ground)
            else:
                self.hit_spark(burst, ground)

    def hit_spark(self, burst, ground):
        """A star of light where a blow lands, flaring out and gone in a few frames; bigger for the boss's end."""
        c, u = self.canvas, self.ui
        k = burst['t'] / BURST_LIFE[burst['kind']]
        size = (3 + 7 * k) * u * (2 if burst['kind'] == 'big' else 1)
        x, y = burst['x'], ground - burst['h']
        for n, (dx, dy) in enumerate(RAYS):
            reach = size if n < 4 else size * .6
            c.create_line(x + dx * reach * .3, y + dy * reach * .3, x + dx * reach, y + dy * reach,
                          fill=SPARK[n % 2], width=u, tags=('fx',))
        c.create_rectangle(x - u, y - u, x + u, y + u, fill=SPARK[0], width=0, tags=('fx',))

    def hit_number(self, burst, ground):
        """A number flying up off a blow, with a dark edge so it reads on any screen."""
        c, u = self.canvas, self.ui
        k = burst['t'] / BURST_LIFE['pop']
        x, y = burst['x'], ground - burst['h'] - (k * 16 - (k * 4) ** 2 * .3) * u   # up fast, then slower
        font, color = (FONT_TITLE, SPARK[1]) if burst['crit'] else (FONT_TAG, PAPER)
        for dx, dy in ((-1, -1), (1, 1)):  # two shadows are enough to read it, and cheap every frame
            c.create_text(x + dx, y + dy, text=burst['text'], font=font, fill=INK, tags=('fx',))
        c.create_text(x, y, text=burst['text'], font=font, fill=color, tags=('fx',))

    def put_sprite(self, group, index, anim, i, facing, cx, ground):
        """A bug or boss with the middle of its body at cx, feet on the ground."""
        f = self.sprites.frame(group, index, anim, i, facing)
        item = self.canvas.create_image(int(cx - f['w'] / 2 + f['dx']), int(ground + f['dy']), image=f['img'],
                                        anchor='nw', tags=('fx',))
        return {**f, 'item': item}  # the cached frame itself stays as it was

    def game_extras(self, cat, base, left, right, top, box):
        """Around a hero: its tier's aura and glitter, a campfire while it sleeps, "LEVEL UP!" over its plate."""
        s, c, ground = self.ui, self.canvas, int(base - cat.y)
        if cat.tier >= 2:  # silver and gold: a glow under the feet, behind the hero
            glow = c.create_oval(left - 4 * s, ground - 2 * s, right + 4 * s, ground + s, width=0,
                                 fill=TIER_COLORS[cat.tier], stipple='gray50', tags=('fx',))
            c.tag_lower(glow, cat.item)
        if cat.tier >= 3:
            for k in range(3):
                phase = (int(cat.t / .25) + k * 3) % 8
                if phase < 5:
                    x = left + (right - left) * ((k * 37 + int(cat.t * 7)) % 100) / 100
                    self.pixels(int(x), top + (phase + k * 4) * s, SPARKLE if phase in (1, 2) else TWINKLE,
                                FX_COLORS, tags=('fx',))
        if cat.mode == 'idle':
            self.campfire(cat, right + 2 * s if cat.dir > 0 else left - 9 * s, ground)
        if cat.flash > 0:
            item, w, h = self.text(TEXT[self.settings['lang']]['levelup'], FONT_TAG, INK)
            width, height = w + 6 * s, h + 2 * s
            x0, y0 = self.card_x((box[0] + box[2]) // 2, width), box[1] - height - 2 * s
            c.create_image(x0, y0, image=self.card(width, height, XP_COLOR, paper=PAPER), anchor='nw', tags=('fx',))
            c.move(item, x0 + 3 * s, y0 + s)
            c.addtag_withtag('fx', item)
            c.tag_raise(item)

    def campfire(self, cat, x, ground):
        """A little fire: two logs and flickering flames."""
        c, s = self.canvas, self.ui
        flick = int(cat.t / .15) % 3
        c.create_rectangle(x, ground - s, x + 7 * s, ground, fill='#6b4426', width=0, tags=('fx',))
        for k, (dx, h, color) in enumerate(((1, 5, '#e5484d'), (3, 7 - flick, '#ff9f3a'), (5, 4 + flick, '#ffd23f'))):
            c.create_rectangle(x + dx * s, ground - s - h * s, x + (dx + 2) * s, ground - s, fill=color, width=0,
                               tags=('fx',))


def tr_en(name):
    return name.get('en', next(iter(name.values()), '')) if isinstance(name, dict) else str(name)
